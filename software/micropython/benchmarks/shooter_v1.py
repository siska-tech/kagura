# SPDX-License-Identifier: Apache-2.0
"""STAR RUNNER: original horizontal shooter for KAGURA ABI 0.5.

No external assets, PSRAM, or 16x16 sprite capability required.
See shooter.md for installation, controls and hardware validation limits.
"""
import math
from time import ticks_ms, ticks_diff, sleep_ms
from kagura.video import Video
from kagura.audio import Audio
from kagura import regs as R

LEFT, RIGHT, UP, DOWN, FIRE, QUIT, AUTO = 1, 2, 4, 8, 16, 32, 64
WAVE = tuple(int(math.sin(i * math.pi / 32) * 20) for i in range(64))

# Original eight-bar, two-voice chiptune, 120 BPM / sixteenth-note steps.
# MIDI note 0 is a rest. Effects retain pulse ch0 and noise ch3.
MELODY = (
    (76, 0, 71, 74, 76, 0, 79, 78, 76, 74, 71, 0, 74, 76, 78, 0),
    (79, 0, 78, 76, 74, 0, 71, 74, 78, 0, 76, 74, 71, 0, 69, 71),
    (72, 0, 76, 79, 81, 0, 79, 76, 79, 0, 76, 74, 72, 0, 74, 76),
    (78, 0, 74, 71, 74, 0, 78, 81, 83, 81, 78, 74, 78, 0, 74, 0),
    (76, 79, 83, 0, 81, 79, 78, 76, 78, 0, 79, 78, 76, 0, 74, 71),
    (72, 76, 79, 0, 81, 79, 76, 72, 74, 0, 76, 74, 72, 0, 71, 69),
    (71, 0, 74, 78, 81, 0, 78, 74, 83, 0, 81, 78, 74, 0, 78, 81),
    (83, 0, 81, 78, 79, 0, 78, 74, 76, 0, 71, 74, 76, 0, 0, 0),
)
BASS_ROOTS = (40, 43, 36, 38, 40, 36, 38, 40)
BASS_PATTERN = (0, None, 12, None, 7, None, 12, None,
                0, None, 12, 7, 0, None, 7, 12)
NOTE_HZ = tuple(round(440 * 2 ** ((note - 69) / 12)) for note in range(36, 85))


class Music:
    """Nonblocking wall-clock sequencer; delayed frames skip expired notes."""
    def __init__(self, audio, device):
        self.audio, self.device = audio, device
        self.start = None
        self.step = -1
        self.lead_on = self.bass_on = False

    def update(self, now):
        if self.start is None:
            self.start = now
        elapsed = ticks_diff(now, self.start)
        step, phase = elapsed // 125, elapsed % 125
        changed = False
        if step != self.step:
            self.step = step
            bar, beat = (step // 16) % 8, step % 16
            note = MELODY[bar][beat]
            bass = BASS_PATTERN[beat]
            self.lead_on = bool(note) and phase < 100
            self.bass_on = bass is not None and phase < 85
            if self.lead_on:
                self.audio.tone(1, NOTE_HZ[note - 36], left=26, right=20, duty=64)
            else:
                self.audio.stop(1)
            if self.bass_on:
                note = BASS_ROOTS[bar] + bass
                self.audio.tone(2, NOTE_HZ[note - 36], left=22, right=26, duty=128)
            else:
                self.audio.stop(2)
            changed = True
        if self.lead_on and phase >= 100:
            self.audio.stop(1)
            self.lead_on = False
            changed = True
        if self.bass_on and phase >= 85:
            self.audio.stop(2)
            self.bass_on = False
            changed = True
        if changed:
            self.device.audio_commit()

    def stop(self):
        self.audio.stop(1)
        self.audio.stop(2)


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
                       " ": FIRE, "z": FIRE, "q": QUIT, "t": AUTO}.get(c.lower(), 0)
            if key & (QUIT | AUTO):
                result |= key
            elif key:
                self.held = key
                self.until = now
        if ticks_diff(now, self.until) < 180:
            result |= self.held
        return result


class Game:
    def __init__(self, device, autoplay=True, sound=True, music=True):
        self.device = device
        self.video = Video(device)
        self.audio = Audio(device)
        self.sound = sound and bool(device.caps & R.CAPS_HDMI_AUDIO)
        self.music = Music(self.audio, device) if self.sound and music else None
        self.autoplay = autoplay
        self.height = device.height
        self.oam = bytearray(32 * 8)
        self.glyphs = {}
        self.frame = self.scroll = self.score = 0
        self.x, self.y = 56, self.height // 2
        self.lives, self.power, self.invincible = 3, 0, 60
        self.dead = 0
        self.bullets = []  # [x, y, option shot]
        self.enemies = []  # [x, y, base_y, phase]
        self.hostile = []  # [x, y, dy]
        self.pickup = None
        self.burst = None
        self.trail = [(self.x - 18, self.y)] * 12
        self.sound_left = 0

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
        for i, ch in enumerate(sorted(FONT)):
            tile = 32 + i
            self.glyphs[ch] = tile
            bits = FONT[ch]
            rows = ["00000000"]
            rows.extend("00" + "".join("f" if b == "1" else "0"
                                      for b in bits[y * 3:y * 3 + 3]) + "000"
                        for y in range(5))
            rows.extend(("00000000", "00000000"))
            self.video.tile(tile, pack_tile(rows))
        # One static, seamless 512px map; only scroll and OAM change per frame.
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
        d.fence()
        d.write_reg(R.REG_DISPLAY_CTRL, 7)
        d.commit()

    def bounds(self, world_x):
        col = (int(world_x) // 8) & 63
        ridge = (0, 0, 1, 1, 2, 2, 1, 0)[col // 8]
        return 24 + ridge * 8, (self.height // 8 - 2 - ridge) * 8

    def effect(self, explosion=False):
        if self.sound:
            if explosion:
                self.audio.stop(0)
                self.audio.noise(220, left=36, right=36)
                self.sound_left = 5
            else:
                self.audio.stop(3)
                self.audio.tone(0, 1200 if self.power else 800, left=18, right=18)
                self.sound_left = 2
            self.device.audio_commit()

    def damage(self):
        if self.invincible or self.dead:
            return
        self.lives -= 1
        self.power = 0
        self.invincible = 75
        self.burst = [self.x, self.y, 10]
        self.x, self.y = 56, self.height // 2
        self.trail[:] = [(self.x - 18, self.y)] * 12
        self.effect(True)
        if not self.lives:
            self.dead = 90

    def step(self, keys=0):
        if self.music is not None:
            self.music.update(ticks_ms())
        if keys & AUTO:
            self.autoplay = not self.autoplay
        self.frame += 1
        self.scroll = (self.scroll + 2) & 511
        if self.sound_left:
            self.sound_left -= 1
            if not self.sound_left and self.sound:
                self.audio.stop(0)
                self.audio.stop(3)
                self.device.audio_commit()
        if self.invincible:
            self.invincible -= 1
        if self.dead:
            self.dead -= 1
            if not self.dead:
                self.lives, self.score, self.power = 3, 0, 0
                self.enemies.clear()
                self.hostile.clear()
                self.bullets.clear()
                self.pickup = None
                self.invincible = 60
        else:
            if self.autoplay:
                target = self.height // 2 + WAVE[(self.frame // 3) & 63]
                if self.pickup:
                    target = self.pickup[1]
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
                if len(self.bullets) < 4:
                    self.bullets.append([self.x + 16, self.y, False])
                    self.effect()
                if self.power >= 3 and len(self.bullets) < 4:
                    ox, oy = self.trail[0]
                    self.bullets.append([ox + 8, oy, True])
            top, bottom = self.bounds(self.x + self.scroll)
            top2, bottom2 = self.bounds(self.x + self.scroll + 15)
            if self.y < max(top, top2) or self.y + 8 > min(bottom, bottom2):
                self.damage()
        self.trail.pop(0)
        self.trail.append((self.x - 18, self.y))
        if self.frame % 32 == 0 and len(self.enemies) < 4:
            base = self.height // 2 + WAVE[(self.frame // 4) & 63]
            self.enemies.append([320, base, base, self.frame & 63])
        for enemy in self.enemies[:]:
            enemy[0] -= 3
            enemy[3] = (enemy[3] + 2) & 63
            enemy[1] = enemy[2] + WAVE[enemy[3]]
            if enemy[0] < -8:
                self.enemies.remove(enemy)
                continue
            if (self.frame + enemy[3]) % 53 == 0 and len(self.hostile) < 2:
                self.hostile.append([enemy[0], enemy[1],
                                     1 if self.y > enemy[1] else -1])
            if abs(enemy[0] - self.x - 4) < 12 and abs(enemy[1] - self.y) < 7:
                self.damage()
        for bullet in self.bullets[:]:
            bullet[0] += 9 if self.power < 2 else 12
            if bullet[0] > 319:
                self.bullets.remove(bullet)
                continue
            for enemy in self.enemies[:]:
                if abs(bullet[0] - enemy[0]) < 10 and abs(bullet[1] - enemy[1]) < 8:
                    self.bullets.remove(bullet)
                    self.enemies.remove(enemy)
                    self.score = min(999999, self.score + 100)
                    self.burst = [enemy[0], enemy[1], 7]
                    self.effect(True)
                    break
        for shot in self.hostile[:]:
            shot[0] -= 4
            shot[1] += shot[2]
            if shot[0] < -8 or not 24 <= shot[1] < self.height - 8:
                self.hostile.remove(shot)
            elif abs(shot[0] - self.x - 4) < 11 and abs(shot[1] - self.y) < 7:
                self.hostile.remove(shot)
                self.damage()
        if self.frame % 240 == 0 and not self.pickup and not self.dead:
            self.pickup = [320, self.height // 2]
        if self.pickup:
            self.pickup[0] -= 3
            if abs(self.pickup[0] - self.x - 4) < 14 and abs(self.pickup[1] - self.y) < 12:
                self.power = min(3, self.power + 1)
                self.score = min(999999, self.score + 500)
                self.pickup = None
                self.effect()
            elif self.pickup[0] < -8:
                self.pickup = None
        if self.burst:
            self.burst[2] -= 1
            if not self.burst[2]:
                self.burst = None

    def sprite(self, index, x, y, tile):
        # Same 8-byte ABI record as Video.sprite(), batched into one upload.
        offset = index * 8
        x, y = int(x), int(y)
        b = self.oam
        b[offset] = x & 255
        b[offset + 1] = (x >> 8) & 3
        b[offset + 2] = y & 255
        b[offset + 3] = ((y >> 8) & 3) | 4
        b[offset + 4] = tile

    def draw(self):
        # Disable stale slots, including objects removed by collisions.
        for i in range(32):
            self.oam[i * 8 + 3] = 0
        slot = 0
        if not self.dead and (not self.invincible or self.frame & 2):
            self.sprite(slot, self.x, self.y, 1)
            self.sprite(slot + 1, self.x + 8, self.y, 2)
            slot += 2
        if self.power >= 3 and not self.dead:
            ox, oy = self.trail[0]
            self.sprite(slot, ox, oy, 5)
            slot += 1
        for bullet in self.bullets:
            self.sprite(slot, bullet[0], bullet[1], 3)
            slot += 1
        for enemy in self.enemies:
            self.sprite(slot, enemy[0], enemy[1], 4)
            slot += 1
        for shot in self.hostile:
            self.sprite(slot, shot[0], shot[1], 10)
            slot += 1
        if self.pickup:
            self.sprite(slot, self.pickup[0], self.pickup[1], 7)
            slot += 1
        if self.burst:
            self.sprite(slot, self.burst[0], self.burst[1], 6)
        # <=15 playfield sprites, <=16 HUD sprites on a separate scanline.
        label = ("GAME OVER" if self.dead else
                 "S%06d L%d P%d %s" % (self.score, self.lives, self.power,
                                       "A" if self.autoplay else "M"))
        for i, ch in enumerate(label):
            self.sprite(16 + i, 8 + i * 8, 8, self.glyphs[ch])
        self.device.write_memory(0xA000, self.oam)
        self.video.scroll(self.scroll, 0)
        self.device.commit()


def run(device=None, console=None, autoplay=True, sound=True,
        duration=None, input_fn=None, music=True):
    """Run until Q/Ctrl-C or duration seconds. input_fn returns a key bitmask.

    Pass console=kagura_console when the HDMI REPL is attached. Without an
    existing device, connect SPI at the driver's conservative 1MHz default.
    """
    if duration is not None and duration < 0:
        raise ValueError("duration must be nonnegative")
    if console is not None:
        if console.screen is None:
            raise RuntimeError("KAGURA console has no display device")
        if device is not None and device is not console.screen.device:
            raise ValueError("device differs from console device")
        device = console.screen.device
    owned = device is None
    if owned:
        from kagura import connect
        device = connect()
    game = Game(device, autoplay, sound, music)
    paused = console is not None and not console.paused
    try:
        if paused:
            console.pause()
        keyboard = input_fn if input_fn is not None else Keyboard()
        game.initialize()
        start = ticks_ms()
        while duration is None or ticks_diff(ticks_ms(), start) < duration * 1000:
            frame_start = ticks_ms()
            keys = keyboard()
            if keys & QUIT:
                break
            game.step(keys)
            game.draw()
            # Target 30 updates/sec. Slow transports reduce actual FPS.
            sleep_ms(max(0, 33 - ticks_diff(ticks_ms(), frame_start)))
    finally:
        try:
            if game.sound:
                game.audio.stop(0)
                game.audio.stop(3)
                if game.music is not None:
                    game.music.stop()
                device.audio_commit()
        finally:
            try:
                if paused:
                    console.resume()
                elif console is None:
                    device.fill(0xA000, 2048, 0)
                    device.write_reg(R.REG_DISPLAY_CTRL, 0)
                    device.commit()
            finally:
                if owned:
                    device.deinit()


if __name__ == "__main__":
    run()
