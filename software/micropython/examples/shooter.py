# SPDX-License-Identifier: Apache-2.0
"""STAR RUNNER v2: original horizontal shooter / AV benchmark for ABI 0.5.

BASE/PSG modes need no PSRAM; generated PCM assets enable FULL/PCM modes.
See shooter.md for installation, controls and hardware validation limits.
"""
import math
import gc
from array import array
from time import ticks_ms, ticks_us, ticks_diff, sleep_ms
from kagura.video import Video
from kagura import regs as R
from shooter_pool import Pool
from shooter_sound import Sound, SHOT, ENEMY_SHOT, POWERUP, EXPLOSION, STAGE, SPECIAL, WARNING, ERROR_MASK
import shooter_stats as T

LEFT, RIGHT, UP, DOWN, FIRE, QUIT, AUTO = 1, 2, 4, 8, 16, 32, 64
SPECIAL_KEY, LOAD_KEY, PARTICLE_KEY = 128, 256, 512
MODES = ('BASE', 'PSG', 'PCM', 'FULL', 'HEAVY', 'EXTREME')
LOADS = ('NORMAL', 'HEAVY', 'STRESS', 'EXTREME')
LAST_STATS = None
WAVE = tuple(int(math.sin(i * math.pi / 32) * 20) for i in range(64))

# Eight pixels per row; hexadecimal digits are palette indices.
ART = (
    ("00000000",) * 8,
    ("00001100", "0001ff10", "011ffff1", "1ff55fff",
     "1fffffff", "011ffff1", "0001ff10", "00001100"),
    ("00000000", "00000000", "10000000", "ff111000",
     "fffff110", "ff111000", "10000000", "00000000"),
    ("00000000", "00000000", "00000000", "eeeeeeee",
     "eeeeeeee", "00000000", "00000000", "00000000"),
    ("00444400", "04466440", "446ff644", "46f44f64",
     "446ff644", "04466440", "04000040", "40000004"),
    ("00000000", "000aa000", "00affa00", "0affffa0",
     "0affffa0", "00affa00", "000aa000", "00000000"),
    ("00a00a00", "a00ee00a", "0aeeeea0", "0eeffee0",
     "0eeffee0", "0aeeeea0", "a00ee00a", "00a00a00"),
    ("00333300", "03222230", "32111123", "32133123",
     "32133123", "32111123", "03222230", "00333300"),
    ("88898889", "89988898", "98889888", "88898889",
     "89988898", "98889888", "88898889", "89988898"),
    ("00000000", "00000000", "00000000", "000d0000",
     "00000000", "00000000", "00000000", "00000000"),
    ("000ee000", "00effe00", "0ef77fe0", "ef7ff7fe",
     "ef7ff7fe", "0ef77fe0", "00effe00", "000ee000"),
)
FONT = {
    "0": "111101101101111", "1": "010110010010111",
    "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111",
    "6": "111100111101111", "7": "111001010010010",
    "8": "111101111101111", "9": "111101111001111",
    "S": "111100111001111", "L": "100100100100111",
    "P": "110101110100100", "A": "010101111101101",
    "M": "101111111101101", "G": "111100101101111",
    "E": "111100110100111", "O": "111101101101111",
    "V": "101101101101010", "R": "110101110101101",
    " ": "000000000000000",
}


def pack_tile(rows):
    return bytes(int(row[x:x + 2], 16) for row in rows for x in range(0, 8, 2))


class Keyboard:
    """Poll stdin (USB REPL and attached UART dupterm); retain split CSI."""
    def __init__(self):
        import sys
        import select
        self.stream = sys.stdin
        self.poll = select.poll()
        self.poll.register(self.stream, select.POLLIN)
        self.escape = 0
        self.held = 0
        self.until = 0

    def __call__(self):
        now = ticks_ms()
        result = 0
        # Bound work when a terminal sends a large paste.
        for _ in range(32):
            if not self.poll.poll(0):
                break
            c = self.stream.read(1)
            if c == "\x1b":
                self.escape = 1
                continue
            if self.escape == 1 and c == "[":
                self.escape = 2
                continue
            if self.escape == 2:
                key = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT}.get(c, 0)
                self.escape = 0
            else:
                self.escape = 0
                key = {"w": UP, "s": DOWN, "a": LEFT, "d": RIGHT,
                       " ": FIRE, "z": FIRE, "q": QUIT, "t": AUTO,
                       "x": SPECIAL_KEY, "n": LOAD_KEY, "p": PARTICLE_KEY}.get(c.lower(), 0)
            if key & (QUIT | AUTO | SPECIAL_KEY | LOAD_KEY | PARTICLE_KEY):
                result |= key
            elif key:
                self.held = key
                self.until = now
        if ticks_diff(now, self.until) < 180:
            result |= self.held
        return result


class Game:
    """The v1 game rules, with fixed pools and separate movement/collisions."""
    def __init__(self, device, autoplay=True, sound=True, music=True, mode='FULL',
                 load='NORMAL', particles=8, sprites=128, enhanced=True,
                 assets='star_runner_assets', stats=None, bgm_gain=224, renderer='python'):
        if mode not in MODES or load not in LOADS:
            raise ValueError('unknown mode/load')
        if particles not in (8, 16, 32, 64) or sprites not in (128, 256):
            raise ValueError('particles=8/16/32/64, sprites=128/256')
        if renderer not in ('python', 'viper'):
            raise ValueError('renderer must be python or viper')
        self.renderer = renderer
        self._oam_builder = None
        if renderer == 'viper':
            from shooter_oam_viper import build
            self._oam_builder = build
        self.device, self.video = device, Video(device)
        self.mode, self.load, self.extreme_sprites = mode, load, sprites
        if mode == 'HEAVY':
            self.load = 'STRESS'
        elif mode == 'EXTREME':
            self.load = 'EXTREME'
        self.stats = stats if stats is not None else T.Stats()
        self.autoplay, self.enhanced = autoplay, enhanced
        self.height = device.height
        self.sound = Sound(device, psg=sound and mode not in ('BASE', 'PCM'),
                           pcm=sound and mode not in ('BASE', 'PSG'),
                           music=music, assets=assets, bgm_gain=bgm_gain)
        # Reserve the full OAM once; cached views avoid per-frame slicing.
        self.oam = bytearray(2048)
        view = memoryview(self.oam)
        self.views = (view[:256], view[:512], view[:1024], view)
        self.oam_count = 32
        self.active_sprites = self.oam_bytes = 0
        # Conservative 8-line bands: an 8px sprite touches at most two bands.
        # Capping each band at 16 also caps every individual line at 16.
        self.scanlines = bytearray(32)
        self.glyphs = {}
        self.hud = bytearray(16)
        self.hud_records = bytearray(128)
        for i in range(16):
            self.hud_records[i * 8] = 8 + i * 8
            self.hud_records[i * 8 + 2] = 8
            self.hud_records[i * 8 + 3] = 4
        self.last_score = self.last_lives = self.last_power = -1
        self.last_auto = None
        self.last_dead = None
        self.frame = self.scroll = self.score = self.stage = 0
        self.x, self.y = 56, self.height // 2
        self.lives, self.power, self.invincible, self.dead = 3, 0, 60, 0
        self.bullets, self.enemies, self.hostile = Pool(12), Pool(12), Pool(8)
        self.particles = Pool(64)
        self.particle_limit = particles
        self.pickup_x = -32
        self.pickup_y = self.height // 2
        self.burst_x = self.burst_y = self.burst_life = 0
        self.trail_x = array('h', [self.x - 18] * 12)
        self.trail_y = array('h', [self.y] * 12)
        self.trail_index = 0
        self.old_scroll_high = -1
        self.pending_commit = False
        self.last_audio_error = self.last_pcm0_error = self.last_pcm1_error = 0
        self.monitor_wire = 0
        self.last_overflow = False
        self.last_bgm_stopped = False
        self.stress_x = array('h', [(i * 37) % 320 for i in range(256)])
        self.stress_y = array('h', [24 + (i * 17) % (self.height - 40) for i in range(256)])
        self.stars_x = array('h', [(i * 71) % 1280 for i in range(8)])
        self.stars_y = array('h', [48 + (i * 29) % (self.height - 88) for i in range(8)])
        self.bg_color = -1

    def bounds(self, world_x):
        col = (world_x // 8) & 63
        ridge = (0, 0, 1, 1, 2, 2, 1, 0)[col // 8]
        return 24 + ridge * 8, (self.height // 8 - 2 - ridge) * 8

    def initialize(self):
        d = self.device
        d.write_reg(R.REG_DISPLAY_CTRL, 0)
        d.commit()
        d.fill(0xA000, 2048, 0)
        if d.caps & R.CAPS_RSCROLL:
            self.video.raster_scroll(())
        palette = (0x001, 0x69B, 0xCEF, 0x246, 0xF47, 0x4DF, 0xA25, 0x248,
                   0x123, 0x345, 0xF83, 0xFA8, 0x578, 0x68A, 0xFE6, 0xFFF)
        d.ext_write(R.EXT_BACKDROP, 0)
        for i, color in enumerate(palette):
            self.video.palette(i, color)
        for i, rows in enumerate(ART):
            self.video.tile(i, pack_tile(rows))
        # New art extends the existing tiles; v1 ship/enemies remain intact.
        effects = (
            ('00000000', '00000000', '00000ee0', '00eeeffe', '0aaffffe', '00eeeffe', '00000ee0', '00000000'),
            ('00000000', '00000000', '00000000', '000ee000', '000ee000', '00000000', '00000000', '00000000'),
            ('00000000', '00000000', '00000000', '000d0000', '00000000', '00000000', '00000000', '00000000'),
            ('00000000', '00000000', '000d0000', '00dfd000', '000d0000', '00000000', '00000000', '00000000'),
            ('00000000', '00000000', 'eeeeeeee', 'effffffe', 'effffffe', 'eeeeeeee', '00000000', '00000000'))
        for i, rows in enumerate(effects):
            self.video.tile(11 + i, pack_tile(rows))
        for i, ch in enumerate(sorted(FONT)):
            tile = 32 + i
            self.glyphs[ch] = tile
            bits = FONT[ch]
            rows = ['00000000']
            for y in range(5):
                rows.append('00' + ''.join('f' if b == '1' else '0' for b in bits[y * 3:y * 3 + 3]) + '000')
            rows.extend(('00000000', '00000000'))
            self.video.tile(tile, pack_tile(rows))
        bg = bytearray(4096)
        for row in range(32):
            for col in range(64):
                top, bottom = self.bounds(col * 8)
                tile = 8 if row * 8 < top or row * 8 >= bottom else 0
                if not tile and (col * 29 + row * 43) % 37 == 0:
                    tile = 9
                bg[(row * 64 + col) * 2] = tile
        d.write_memory(0x8000, bg)
        self.video.scroll(0, 0)
        self.sound.initialize()
        d.fence()
        d.write_reg(R.REG_DISPLAY_CTRL, 7)
        d.commit()

    def emit(self, x, y, bright=False):
        self.burst_x, self.burst_y, self.burst_life = x, y, 7
        if not self.enhanced:
            return
        for n in range(8 if self.load == 'NORMAL' else 16):
            index = -1
            for i in range(self.particle_limit):
                if not self.particles.life[i]:
                    index = i
                    break
            if index < 0:
                break
            p = self.particles
            p.x[index], p.y[index] = x, y
            p.vx[index], p.vy[index] = (n * 3) % 7 - 4, (n * 5) % 7 - 3
            p.life[index], p.kind[index] = 12 + n % 5, bool(bright)

    def damage(self):
        if self.invincible or self.dead:
            return
        self.emit(self.x, self.y)
        self.lives -= 1
        self.power, self.invincible = 0, 75
        self.x, self.y = 56, self.height // 2
        for i in range(12):
            self.trail_x[i], self.trail_y[i] = self.x - 18, self.y
        self.sound.enqueue(EXPLOSION)
        if not self.lives:
            self.dead = 90

    def movement(self, keys=0):
        if keys & AUTO:
            self.autoplay = not self.autoplay
        if keys & LOAD_KEY:
            self.load = LOADS[(LOADS.index(self.load) + 1) % len(LOADS)]
        if keys & PARTICLE_KEY:
            self.particle_limit = 8 if self.particle_limit == 64 else self.particle_limit * 2
        if keys & SPECIAL_KEY and not self.dead:
            self.sound.enqueue(SPECIAL)
            for i in range(self.enemies.size):
                if self.enemies.life[i]:
                    self.emit(self.enemies.x[i], self.enemies.y[i], True)
                    self.enemies.life[i] = 0
                    self.score = min(999999, self.score + 100)
        self.frame += 1
        self.scroll = (self.scroll + 2) & 511
        self.stage = self.frame // 900
        if self.frame % 900 == 0:
            self.sound.enqueue(STAGE)
        if self.enhanced and self.frame % 180 == 0:
            self.sound.enqueue(WARNING)
        if self.load in ('STRESS', 'EXTREME') and self.frame % 120 == 0:
            self.sound.enqueue(SPECIAL)
        if self.invincible:
            self.invincible -= 1
        if self.dead:
            self.dead -= 1
            if not self.dead:
                self.lives, self.score, self.power = 3, 0, 0
                self.enemies.clear()
                self.hostile.clear()
                self.bullets.clear()
                self.pickup_x = -32
                self.invincible = 60
        else:
            if self.autoplay:
                target = self.pickup_y if self.pickup_x > -16 else self.height // 2 + WAVE[(self.frame // 3) & 63]
                self.y += max(-3, min(3, target - self.y))
                firing = True
            else:
                speed = 4 if self.power else 3
                self.x += speed * (bool(keys & RIGHT) - bool(keys & LEFT))
                self.y += speed * (bool(keys & DOWN) - bool(keys & UP))
                firing = bool(keys & FIRE)
            self.x = max(8, min(280, self.x))
            self.y = max(24, min(self.height - 16, self.y))
            if firing and self.frame % (5 if self.power >= 2 else 8) == 0:
                limit = 4 if self.load == 'NORMAL' else self.bullets.size
                active = 0
                for i in range(self.bullets.size):
                    active += bool(self.bullets.life[i])
                if active < limit:
                    self.bullets.spawn(self.x + 16, self.y)
                    self.sound.enqueue(SHOT)
                    active += 1
                if self.power >= 3 and active < limit:
                    self.bullets.spawn(self.trail_x[self.trail_index] + 8,
                                       self.trail_y[self.trail_index], kind=1)
        self.trail_x[self.trail_index] = self.x - 18
        self.trail_y[self.trail_index] = self.y
        self.trail_index = (self.trail_index + 1) % 12
        interval = max(12, 32 - min(16, self.stage * 2)) if self.enhanced else 32
        if self.load != 'NORMAL':
            interval = max(6, interval // 2)
        if self.frame % interval == 0:
            base = self.height // 2 + WAVE[(self.frame // 4) & 63]
            kind = (self.frame // (interval * 4)) % 3 if self.enhanced else 1
            direction = (self.frame // (interval * 9)) % 4 if self.enhanced else 0
            speed = 3 + min(3, self.stage)
            x, vx, vy = 320, -speed, 0
            if direction == 1:
                x, vx = -8, speed
            elif direction >= 2:
                x, base, vy = 240, (24 if direction == 2 else self.height - 16), (2 if direction == 2 else -2)
            # Normal retains four enemies; heavy load expands the fixed pool.
            count = 0
            for i in range(self.enemies.size):
                count += bool(self.enemies.life[i])
            if count < (4 if self.load == 'NORMAL' else 12):
                self.enemies.spawn(x, base, vx, vy, kind=kind, phase=self.frame & 63)
        e = self.enemies
        for i in range(e.size):
            if e.life[i]:
                old_phase = e.phase[i]
                e.phase[i] = (old_phase + 2) & 63
                e.x[i] += e.vx[i]
                e.base[i] += e.vy[i]
                if e.kind[i] == 0:
                    e.y[i] = e.base[i]
                else:
                    e.y[i] = e.base[i] + WAVE[e.phase[i]]
                    if e.kind[i] == 2:
                        e.x[i] += WAVE[(e.phase[i] + 16) & 63] - WAVE[(old_phase + 16) & 63]
                if not -16 <= e.x[i] <= 336 or not 16 <= e.y[i] < self.height:
                    e.life[i] = 0
                elif (self.frame + e.phase[i]) % 53 == 0:
                    count = 0
                    for k in range(self.hostile.size):
                        count += bool(self.hostile.life[k])
                    if count < (2 if self.load == 'NORMAL' else 8):
                        self.hostile.spawn(e.x[i], e.y[i], -4,
                                           1 if self.y > e.y[i] else -1)
                        self.sound.enqueue(ENEMY_SHOT)
        b = self.bullets
        for i in range(b.size):
            if b.life[i]:
                b.x[i] += 9 if self.power < 2 else 12
                if b.x[i] > 319:
                    b.life[i] = 0
        h = self.hostile
        for i in range(h.size):
            if h.life[i]:
                h.x[i] += h.vx[i]
                h.y[i] += h.vy[i]
                if h.x[i] < -8 or not 24 <= h.y[i] < self.height - 8:
                    h.life[i] = 0
        if self.frame % 240 == 0 and self.pickup_x <= -16 and not self.dead:
            self.pickup_x = 320
        if self.pickup_x > -16:
            self.pickup_x -= 3
        if self.burst_life:
            self.burst_life -= 1
        p = self.particles
        for i in range(p.size):
            if p.life[i]:
                p.x[i] += p.vx[i]
                p.y[i] += p.vy[i]
                p.life[i] -= 1
                if not -8 <= p.x[i] < 320 or not 24 <= p.y[i] < self.height - 8:
                    p.life[i] = 0
        for i in range(8):
            self.stars_x[i] = (self.stars_x[i] - (1 if i & 1 else 2)) % 1280

    def collisions(self):
        if not self.dead:
            top, bottom = self.bounds(self.x + self.scroll)
            top2, bottom2 = self.bounds(self.x + self.scroll + 15)
            if self.y < max(top, top2) or self.y + 8 > min(bottom, bottom2):
                self.damage()
        e, b, h = self.enemies, self.bullets, self.hostile
        for i in range(e.size):
            if e.life[i] and abs(e.x[i] - self.x - 4) < 12 and abs(e.y[i] - self.y) < 7:
                self.damage()
        for i in range(b.size):
            if b.life[i]:
                for k in range(e.size):
                    if e.life[k] and abs(b.x[i] - e.x[k]) < 10 and abs(b.y[i] - e.y[k]) < 8:
                        b.life[i] = e.life[k] = 0
                        self.score = min(999999, self.score + 100)
                        self.emit(e.x[k], e.y[k])
                        self.sound.enqueue(EXPLOSION)
                        break
        for i in range(h.size):
            if h.life[i] and abs(h.x[i] - self.x - 4) < 11 and abs(h.y[i] - self.y) < 7:
                h.life[i] = 0
                self.damage()
        if not self.dead and self.pickup_x > -16 and abs(self.pickup_x - self.x - 4) < 14 and abs(self.pickup_y - self.y) < 12:
            self.power = min(3, self.power + 1)
            self.score = min(999999, self.score + 500)
            self.emit(self.x, self.y, True)
            self.pickup_x = -32
            self.sound.enqueue(POWERUP)

    def step(self, keys=0):
        stamp = ticks_us()
        self.movement(keys)
        self.stats.add(T.MOVE, ticks_diff(ticks_us(), stamp))
        stamp = ticks_us()
        self.collisions()
        self.stats.add(T.COLLIDE, ticks_diff(ticks_us(), stamp))

    def sprite(self, index, x, y, tile, limit=True):
        if not -8 <= x < 320 or not 0 <= y < self.height:
            return False
        first, last = y >> 3, (y + 7) >> 3
        counts = self.scanlines
        if limit:
            if counts[first] >= 16 or counts[last] >= 16:
                self.stats.particle_culled += 1
                return False
        if counts[first] < 255:
            counts[first] += 1
        if last != first and counts[last] < 255:
            counts[last] += 1
        offset = index * 8
        b = self.oam
        b[offset], b[offset + 1] = x & 255, (x >> 8) & 3
        b[offset + 2], b[offset + 3] = y & 255, ((y >> 8) & 3) | 4
        b[offset + 4] = tile
        self.active_sprites += 1
        return True

    def update_hud(self):
        if (self.score == self.last_score and self.lives == self.last_lives and
                self.power == self.last_power and self.autoplay == self.last_auto and bool(self.dead) == self.last_dead):
            return
        label = ('GAME OVER       ' if self.dead else
                 'S%06d L%d P%d %s ' % (self.score, self.lives, self.power, 'A' if self.autoplay else 'M'))
        for i in range(16):
            self.hud[i] = self.glyphs[label[i]]
            self.hud_records[i * 8 + 4] = self.hud[i]
        self.last_score, self.last_lives, self.last_power = self.score, self.lives, self.power
        self.last_auto = self.autoplay
        self.last_dead = bool(self.dead)

    def build_oam(self):
        if self._oam_builder is not None:
            self.update_hud()
            upload_count = self._oam_builder(self)
            return self.views[0 if upload_count == 32 else 1 if upload_count == 64 else 2 if upload_count == 128 else 3]
        return self._build_oam_python()

    def _build_oam_python(self):
        previous_count = self.oam_count
        count = 32
        if self.enhanced or self.load != 'NORMAL':
            count = self.extreme_sprites if self.load == 'EXTREME' else 64
            if self.load not in ('STRESS', 'EXTREME') and self.particle_limit >= 32:
                count = 128
        self.oam_count = count
        self.active_sprites = 16  # Cached, fixed HUD on its own scanline.
        upload_count = max(count, previous_count)
        for i in range(upload_count):
            self.oam[i * 8 + 3] = 0
        for y in range(32):
            self.scanlines[y] = 0
        self.scanlines[1] = 16
        slot = 0
        if not self.dead and (not self.invincible or self.frame & 2):
            self.sprite(slot, self.x, self.y, 1)
            self.sprite(slot + 1, self.x + 8, self.y, 2)
            slot += 2
            if self.enhanced:
                self.sprite(slot, self.x - 8, self.y, 11 if self.frame & 1 else 5)
                slot += 1
        if self.power >= 3 and not self.dead:
            self.sprite(slot, self.trail_x[self.trail_index], self.trail_y[self.trail_index], 5)
            slot += 1
        for pool, tile in ((self.bullets, 15 if self.enhanced and self.frame & 2 else 3),
                           (self.enemies, 4), (self.hostile, 10)):
            for i in range(pool.size):
                if pool.life[i] and slot < count - 16:
                    self.sprite(slot, pool.x[i], pool.y[i], tile)
                    slot += 1
        if self.pickup_x > -16 and slot < count - 16:
            self.sprite(slot, self.pickup_x, self.pickup_y, 7)
            slot += 1
        if self.burst_life and slot < count - 16:
            self.sprite(slot, self.burst_x, self.burst_y, 6)
            slot += 1
        self.update_hud()
        self.oam[(count - 16) * 8:count * 8] = self.hud_records
        if self.enhanced:
            for i in range(8):
                if slot < count - 16:
                    self.sprite(slot, self.stars_x[i] // 4, self.stars_y[i], 13 + (i & 1))
                    slot += 1
            p = self.particles
            for i in range(self.particle_limit):
                if p.life[i] and slot < count - 16:
                    if self.sprite(slot, p.x[i], p.y[i], 14 if p.kind[i] else 12):
                        slot += 1
        if self.load in ('STRESS', 'EXTREME'):
            # Keep all selected OAM records enabled and moving. STRESS packs
            # them in <=16-per-line bands; EXTREME deliberately bypasses culling.
            bands = max(1, (self.height - 40) // 10)
            for i in range(slot, count - 16):
                x = (self.stress_x[i] - self.frame * (1 + i % 3)) % 312
                y = 24 + (i % bands) * 10
                if self.load == 'EXTREME':
                    y = 40 + (i % 4) * 4
                self.sprite(i, x, y, 12 + (i & 1), limit=self.load != 'EXTREME')
        # On a load decrease, upload the disabled tail once. Otherwise stale
        # high OAM records would remain enabled in FPGA shadow/active memory.
        self.oam_bytes = upload_count * 8
        return self.views[0 if upload_count == 32 else 1 if upload_count == 64 else 2 if upload_count == 128 else 3]

    def draw(self):
        stamp = ticks_us()
        data = self.build_oam()
        self.stats.add(T.BUILD, ticks_diff(ticks_us(), stamp))
        stamp = ticks_us()
        # Never change OAM/palette shadows while a previous COMMIT is in flight.
        if self.pending_commit:
            self.device.wait_status(R.STATUS_COMMIT_BUSY, 0)
            elapsed = ticks_diff(ticks_us(), stamp)
            self.stats.add(T.COMMIT, elapsed)
            self.stats.add(T.COMMIT_WAIT, elapsed)
            self.stats.commit_completed += 1
            self.pending_commit = False
        stamp = ticks_us()
        self.device.write_memory(0xA000, data)
        self.stats.oam_writes += 1
        self.stats.oam_bytes += len(data)
        self.stats.add(T.TRANSFER, ticks_diff(ticks_us(), stamp))
        stamp = ticks_us()
        # Y stays zero; the high X bit changes only twice per 512px cycle.
        self.device.ext_write(R.EXT_SCROLL_X_L, self.scroll & 255)
        high = self.scroll >> 8
        if high != self.old_scroll_high:
            self.device.ext_write(R.EXT_SCROLL_X_H, high)
            self.old_scroll_high = high
        color = (0x001, 0x013, 0x102, 0x021)[self.stage & 3] if self.enhanced else 0x001
        if color != self.bg_color:
            self.video.palette(0, color)
            self.bg_color = color
        self.stats.add(T.SCROLL, ticks_diff(ticks_us(), stamp))
        stamp = ticks_us()
        # COMMIT_BUSY was already checked above (initialization also waits).
        # The application has one owner, so no second preflight poll is needed.
        self.device.write_reg(R.REG_COMMAND, R.CMD_COMMIT)
        self.device.check_errors()
        self.pending_commit = True
        self.stats.commits += 1
        elapsed = ticks_diff(ticks_us(), stamp)
        self.stats.add(T.COMMIT, elapsed)
        self.stats.add(T.COMMIT_ISSUE, elapsed)

    def monitor(self, wire_bytes=0):
        d = self.device
        meter_start = getattr(d.transport, 'wire_bytes', None)
        now = ticks_us()
        self.stats.counter(d.read_reg(R.REG_FRAME_COUNT_L), now)
        code = d.read_reg(R.REG_ERROR_CODE)
        irq = d.read_reg(R.REG_IRQ_STATUS)
        self.sound.monitor()
        a = self.sound.audio_status & (R.AUDIO_STATUS_FIFO_UNDERFLOW | R.AUDIO_STATUS_OVERFLOW)
        p0, p1 = self.sound.status0 & ERROR_MASK, self.sound.status1 & ERROR_MASK
        new_audio = (a & ~self.last_audio_error) | (p0 & ~self.last_pcm0_error) | (p1 & ~self.last_pcm1_error)
        bgm_stopped = (self.sound.pcm and self.sound.music and
                       not self.sound.status0 & R.AUDIO_PCM_STATUS_ACTIVE)
        if bgm_stopped and not self.last_bgm_stopped:
            new_audio |= 0x100
        overflow = bool(irq & R.IRQ_STATUS_SPR_OVERFLOW)
        if code or new_audio or overflow:
            index = d.read_reg(R.REG_SPR_OVERFLOW_INDEX) if overflow else 0
            line = d.read_reg(R.REG_SPR_OVERFLOW_LINE) if overflow else 0
            context_bytes = wire_bytes
            if meter_start is not None:
                context_bytes += d.transport.wire_bytes - meter_start
            self.stats.error(self.active_sprites, self.oam_bytes, context_bytes, code,
                             self.sound.audio_status, self.sound.status0, self.sound.status1,
                             index, line)
            if new_audio:
                self.stats.audio_errors += 1
            if overflow:
                self.stats.sprite_overflows += 1
                d.write_reg(R.REG_IRQ_STATUS, R.IRQ_STATUS_SPR_OVERFLOW)
            if code:
                # Log first, then clear only the observed sticky error bits.
                d.write_reg(R.REG_ERROR_CODE, code)
                d.write_reg(R.REG_IRQ_STATUS, R.IRQ_STATUS_ERROR)
        self.last_audio_error, self.last_pcm0_error, self.last_pcm1_error = a, p0, p1
        self.last_bgm_stopped = bgm_stopped


def run(device=None, console=None, autoplay=True, sound=True, duration=None,
        input_fn=None, music=True, mode='FULL', load='NORMAL', particles=8,
        sprites=128, enhanced=True, assets='star_runner_assets', target_fps=30,
        samples=1024, report=True, gc_interval=4, frames=None, bgm_gain=224, renderer='python', dma='driver',
        profile=False, instrument_transport=True, dma_chunk=128):
    """Compatible v1 entry point. Returns bounded benchmark results on exit.

    target_fps=0 measures maximum throughput. BASE only silences audio at setup.
    See shooter.md for mode matrix, controls, assets and timing definitions.
    """
    global LAST_STATS
    if duration is not None and duration < 0 or frames is not None and frames < 0:
        raise ValueError('duration/frames must be nonnegative')
    if not 0 <= target_fps <= 120 or not 1 <= gc_interval <= 60:
        raise ValueError('invalid target_fps/gc_interval')
    if dma not in ('driver', 'python', 'viper', 'accelerated'):
        raise ValueError('dma must be driver, python, viper or accelerated')
    if dma_chunk not in (128, 256, 512):
        raise ValueError('dma_chunk must be 128, 256 or 512')
    if console is not None:
        if console.screen is None:
            raise RuntimeError('KAGURA console has no display device')
        if device is not None and device is not console.screen.device:
            raise ValueError('device differs from console device')
        device = console.screen.device
    gc.collect()
    stats = T.Stats(samples, detail=profile)
    owned = device is None
    if owned:
        from kagura import connect
        device = connect()
    game = None
    meter = T.TransportMeter(device.transport)
    old_transport = device.transport
    paused = console is not None and not console.paused
    gc_enabled = gc.isenabled()
    start = None
    failure = None
    cleanup_errors = []
    wire_start = 0
    minimum_free = None
    free_memory = getattr(gc, 'mem_free', None)
    dma_override = False
    prior_dma_override = None
    acceleration = None
    try:
        if paused:
            console.pause()
        if dma == 'accelerated':
            try:
                from kagura.acceleration import Acceleration
            except ImportError:
                from kagura_acceleration import Acceleration
            from kagura.transport_rp2 import TransferTimeout
            acceleration = Acceleration(old_transport, TransferTimeout, chunk=dma_chunk)
        elif dma != 'driver':
            try:
                from kagura import dma_pack as dma_helper
            except ImportError:
                # Compatibility with UF2s freezing the pre-acceleration driver.
                import kagura_dma_pack as dma_helper
            from kagura.transport_rp2 import TransferTimeout
            if not getattr(old_transport, '_dma_tx', None):
                raise RuntimeError('DMA transport unavailable')
            if dma == 'viper' and dma_helper.viper_pack is None:
                raise RuntimeError('Viper DMA kernel unavailable')
            packer = dma_helper.pack if dma == 'viper' else dma_helper.python_pack
            try:
                prior_dma_override = old_transport.__dict__.get('_xfer_dma')
            except AttributeError:
                pass
            old_transport._xfer_dma = lambda data, queued: dma_helper.transfer(old_transport, data, queued, TransferTimeout, packer=packer)
            dma_override = True
        game = Game(device, autoplay, sound, music, mode, load, particles, sprites,
                    enhanced, assets, stats, bgm_gain, renderer)
        keyboard = input_fn if input_fn is not None else Keyboard()
        game.initialize()
        device.transport = meter if instrument_transport else old_transport
        device.clear_errors()
        # The previous EXTREME run (or its console transition) may leave this
        # sticky IRQ set. Initial OAM is already cleared and committed above.
        device.write_reg(R.REG_IRQ_STATUS, R.IRQ_STATUS_SPR_OVERFLOW)
        game.monitor()
        gc.collect()
        gc.disable()
        start = ticks_us()
        start_ms = ticks_ms()
        while (duration is None or ticks_diff(ticks_ms(), start_ms) < duration * 1000) and (frames is None or stats.frames < frames):
            begin = ticks_us()
            wire_start = meter.wire_bytes
            stamp = ticks_us()
            keys = keyboard()
            stats.add(T.INPUT, ticks_diff(ticks_us(), stamp))
            if keys & QUIT:
                break
            game.step(keys)
            stamp = ticks_us()
            game.sound.service(ticks_ms())
            stats.add(T.AUDIO, ticks_diff(ticks_us(), stamp))
            game.draw()
            # Read low frame counter often enough to disambiguate wrap. Other
            # sticky status reads share this cadence and are included in cost.
            if stats.frames % 15 == 14:
                stamp = ticks_us()
                game.monitor(meter.wire_bytes - wire_start)
                stats.add(T.MONITOR, ticks_diff(ticks_us(), stamp))
            # RP2040 mem_free walks the entire heap (~6.7ms measured). Sample
            # before scheduled collections, rather than scanning every frame.
            # Collection cadence is unchanged; a low sample collects at once.
            stamp = ticks_us()
            free = free_memory() if free_memory and (stats.frames == 0 or stats.frames % gc_interval == gc_interval - 1) else None
            stats.add(T.MEMORY_POLL, ticks_diff(ticks_us(), stamp))
            if free is not None:
                minimum_free = free if minimum_free is None else min(minimum_free, free)
            if stats.frames % gc_interval == gc_interval - 1 or free is not None and free < 24576:
                stamp = ticks_us()
                gc.collect()
                stats.add(T.GC, ticks_diff(ticks_us(), stamp))
            stamp = ticks_us()
            if target_fps:
                sleep_ms(max(0, (1000000 // target_fps - ticks_diff(stamp, begin)) // 1000))
            stats.add(T.SLEEP, ticks_diff(ticks_us(), stamp))
            stats.finish(ticks_diff(ticks_us(), begin), begin=begin)
        if stats.frames:
            stats.period_end(ticks_us())
        if game.pending_commit:
            device.wait_status(R.STATUS_COMMIT_BUSY, 0)
            stats.commit_completed += 1
            game.pending_commit = False
        game.monitor()
    except BaseException as error:
        failure = error
        if game is not None:
            try:
                game.monitor(meter.wire_bytes - wire_start)
            except BaseException:
                pass
        raise
    finally:
        if start is not None:
            stats.elapsed_us = ticks_diff(ticks_us(), start)
        if gc_enabled:
            gc.enable()
        # Cleanup attempts are independent, so an unplugged device cannot
        # prevent console.resume() or owned-transport deinitialization.
        if game is not None:
            try:
                game.sound.stop()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        device.transport = old_transport
        if acceleration is not None:
            try:
                acceleration.close()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        if dma_override:
            if prior_dma_override is None:
                del old_transport._xfer_dma
            else:
                old_transport._xfer_dma = prior_dma_override
        try:
            if paused:
                console.resume()
            elif console is None:
                device.wait_status(R.STATUS_COMMIT_BUSY, 0)
                device.fill(0xA000, 2048, 0)
                device.write_reg(R.REG_DISPLAY_CTRL, 0)
                device.commit()
        except BaseException as error:
            cleanup_errors.append(repr(error))
        if owned:
            try:
                device.deinit()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        gc.collect()  # Recover temporary allocations before building the report.
        stats.dropped_events = game.sound.dropped if game else 0
        LAST_STATS = stats.summary()
        LAST_STATS.update(mode=mode, load=game.load if game else load,
                          height=device.height, caps=device.caps,
                          lanes=getattr(old_transport, 'lanes', None),
                          baudrate=getattr(old_transport, 'baudrate', None),
                          target_fps=target_fps, enhanced=enhanced, gc_interval=gc_interval,
                          bgm_gain=bgm_gain,
                          renderer=renderer,
                          dma=dma,
                          dma_chunk=dma_chunk,
                          profile=profile, instrument_transport=instrument_transport,
                          minimum_free_bytes=minimum_free,
                          wire_bytes=meter.wire_bytes if instrument_transport else None,
                          transport_us=meter.io_us if instrument_transport else None,
                          dma_payload_bytes=meter.dma_payload if instrument_transport else None,
                          failure=repr(failure) if failure else None,
                          cleanup_errors=cleanup_errors)
        if game is not None:
            LAST_STATS.update(pcm_enabled=game.sound.pcm, wave_enabled=game.sound.wave,
                              audio_reason=game.sound.reason, bgm_inactive_polls=game.sound.bgm_inactive,
                              last_audio_status=game.sound.audio_status,
                              last_pcm0_status=game.sound.status0, last_pcm1_status=game.sound.status1,
                              oam_records=game.oam_count, enabled_sprites=game.active_sprites,
                              game_state=(game.frame,game.x,game.y,game.score,game.lives,game.power),
                              particles=game.particle_limit)
        if report:
            # Console output is paused only for the report; USB still receives
            # it. Restore the previous paused state even if output is interrupted.
            was_paused = console.paused if console else False
            if console and not was_paused:
                console.pause()
            try:
                for key in sorted(LAST_STATS):
                    value = LAST_STATS[key]
                    if isinstance(value, dict):
                        for subkey in sorted(value):
                            print('STAR_RUNNER', key + '.' + subkey, value[subkey])
                            sleep_ms(10)
                    elif key == 'errors':
                        for i in range(len(value)):
                            print('STAR_RUNNER', 'error.%d' % i, value[i])
                            sleep_ms(10)
                    else:
                        print('STAR_RUNNER', key, value)
                        sleep_ms(10)
            finally:
                if console and not was_paused:
                    console.resume()
        if cleanup_errors and failure is None:
            raise OSError('STAR RUNNER cleanup failed: ' + '; '.join(cleanup_errors))
    return LAST_STATS


if __name__ == '__main__':
    run()
