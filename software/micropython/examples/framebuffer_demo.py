# SPDX-License-Identifier: Apache-2.0
"""TileFramebuffer showcase, the MicroPython twin of the Pico C `fbdemo`.

Plasma and tunnel are drawn once into the buffer by Viper loops and moved by
palette cycling; the tesseract over parallax stars and the line ribbon are
redrawn every frame with TileFramebuffer.lines() and only changed tiles are
flushed. Each frame ends with commit(wait=False): the palette applies at the
next VBlank while the next frame is drawn, and the device queue keeps that
frame's patterns behind it. A PSG song runs on its own clock through
device.audio_writes().
Needs a 480p ABI 0.6 bitstream. Usage: import framebuffer_demo; framebuffer_demo.run(60)
"""
import gc
import math
import micropython
from array import array
import time
import kagura
from kagura.framebuffer import TileFramebuffer

SCENE_MS = 12000
FADE = 24
TICK_US = 125000    # one 16th note at 120 BPM
SINE = bytes(127 + round(127 * math.sin(2 * math.pi * i / 256)) for i in range(256))   # offset by 127


def _sin(i):
    return SINE[i & 255] - 127


def ramp(phase, r, g, b):
    return ((8 + _sin(phase + r) * 7 // 127) << 8 | (8 + _sin(phase + g) * 7 // 127) << 4 |
            (8 + _sin(phase + b) * 7 // 127))


def scale(rgb, level):
    return ((rgb >> 8 & 15) * level // 16) << 8 | ((rgb >> 4 & 15) * level // 16) << 4 | (rgb & 15) * level // 16


RAINBOW = array('H', [ramp(i, 0, 85, 170) for i in range(256)])   # ramp(phase, 0, 85, 170)


@micropython.viper
def _pack(raw, pal, level: int):
    """16 RGB444 entries of an array('H') scaled by level/16 into 32 little-endian bytes."""
    b = ptr8(raw)
    p = ptr16(pal)
    for i in range(16):
        v = int(p[i])
        v = (((v >> 8) & 15) * level // 16) << 8 | (((v >> 4) & 15) * level // 16) << 4 | (v & 15) * level // 16
        b[2 * i] = v & 255
        b[2 * i + 1] = v >> 8


# ---- plasma: four sines, 16 colour bands wrapping about four times ----

@micropython.viper
def _plasma(buf, sine, y0: int, y1: int):
    b = ptr8(buf)
    s = ptr8(sine)
    for y in range(y0, y1):
        dy = y - 100
        for x in range(320):
            dx = x - 160
            n = dx * dx + dy * dy
            r = 0
            bit = 1 << 16
            while bit > n:
                bit >>= 2
            while bit:
                if n >= r + bit:
                    n -= r + bit
                    r = (r >> 1) + bit
                else:
                    r >>= 1
                bit >>= 2
            v = (int(s[((x * 3) >> 1) & 255]) + int(s[(y * 2 + 64) & 255]) + int(s[(x + y) & 255]) +
                 int(s[(r * 2) & 255]) - 508)
            c = ((v + 512) >> 4) & 15
            o = ((y >> 3) * 40 + (x >> 3)) * 32 + (y & 7) * 4 + ((x & 7) >> 1)
            if x & 1:
                b[o] = (b[o] & 0xf0) | c
            else:
                b[o] = (b[o] & 15) | (c << 4)


class Plasma:
    name = 'plasma'

    def enter(self, fb, play):
        for y in range(0, 240, 8):   # eight rows per call keep the music going
            _plasma(fb.buffer, SINE, y, y + 8)
            play()
        fb.mark_dirty()

    def frame(self, fb, t, pal):
        for i in range(16):
            pal[i] = ramp(i * 16 + t * 2, 0, 85 + t // 3, 170 + t // 2)


# ---- tunnel: depth 1/d plus a two-arm angle term, one quadrant mirrored ----

@micropython.viper
def _tunnel_row(buf, y: int, depth, angle):
    b = ptr8(buf)
    dp = ptr8(depth)
    an = ptr8(angle)
    for x in range(160):
        d = int(dp[x])
        a = int(an[x])
        for q in range(4):
            px = 160 + x if q == 0 or q == 3 else 159 - x
            py = 120 + y if q < 2 else 119 - y
            ang = a if q == 0 else (128 - a if q == 1 else (128 + a if q == 2 else 256 - a))
            c = (d + (ang >> 3)) & 15
            o = ((py >> 3) * 40 + (px >> 3)) * 32 + (py & 7) * 4 + ((px & 7) >> 1)
            if px & 1:
                b[o] = (b[o] & 0xf0) | c
            else:
                b[o] = (b[o] & 15) | (c << 4)


class Tunnel:
    name = 'tunnel'

    def enter(self, fb, play):
        depth, angle = bytearray(160), bytearray(160)   # one quadrant row at a time
        for y in range(120):
            fy = y + 0.5
            for x in range(160):
                fx = x + 0.5
                depth[x] = int(1024 / math.sqrt(fx * fx + fy * fy)) & 15
                angle[x] = int(math.atan2(fy, fx) * 128 / math.pi)
            _tunnel_row(fb.buffer, y, depth, angle)
            play()
        fb.mark_dirty()

    def frame(self, fb, t, pal):
        for i in range(16):
            light = 9 + _sin(i * 16 + t * 6) * 7 // 127
            pal[i] = scale(RAINBOW[(t // 2 + i * 4) & 255], light)


# ---- tesseract: 4D rotation, perspective twice, depth-coloured edges ----

STARS = 48
TRIG = array('h', [round(16384 * math.sin(2 * math.pi * i / 1024)) for i in range(1024)])   # Q14


@micropython.viper
def _tesseract(segs, work, trig, t: int):
    """Fill segs (array('i')) with STARS star records then 32 edge records, Q14.

    work: array('i') of 3 words per star (x << 8, y, speed), then px, py, pz
    for the 16 vertices. Angles step 0.021, 0.013 and 0.009 rad per frame.
    """
    s = ptr32(segs)
    w = ptr32(work)
    sn = ptr16(trig)
    i = 0
    for k in range(48):                                          # parallax stars
        x = (int(w[k * 3]) + int(w[k * 3 + 2]) * 96) % 81920
        w[k * 3] = x
        y = int(w[k * 3 + 1])
        s[i] = x >> 8
        s[i + 1] = y
        s[i + 2] = x >> 8
        s[i + 3] = y
        s[i + 4] = int(w[k * 3 + 2])
        i += 5
    pa = (t * 3504) >> 10
    pb = (t * 2169) >> 10
    pc = (t * 1502) >> 10
    sa = int(sn[pa & 1023])
    ca = int(sn[(pa + 256) & 1023])
    sb = int(sn[pb & 1023])
    cb = int(sn[(pb + 256) & 1023])
    sc = int(sn[pc & 1023])
    cc = int(sn[(pc + 256) & 1023])
    # ptr16 reads are unsigned; restore the sign of negative table entries.
    if sa > 32767:
        sa -= 65536
    if ca > 32767:
        ca -= 65536
    if sb > 32767:
        sb -= 65536
    if cb > 32767:
        cb -= 65536
    if sc > 32767:
        sc -= 65536
    if cc > 32767:
        cc -= 65536
    for v in range(16):
        x = 16384 if v & 1 else -16384
        y = 16384 if v & 2 else -16384
        z = 16384 if v & 4 else -16384
        q = 16384 if v & 8 else -16384
        x1 = (x * ca - q * sa) >> 14                             # XW
        w1 = (x * sa + q * ca) >> 14
        z1 = (z * cb - w1 * sb) >> 14                            # ZW
        w2 = (z * sb + w1 * cb) >> 14
        d = 42598 - w2                                           # 4D -> 3D: 1 / (2.6 - w)
        x1 = x1 * 16384 // d
        y1 = y * 16384 // d
        z1 = z1 * 16384 // d
        x2 = (x1 * cc + z1 * sc) >> 14                           # Y axis
        z2 = (z1 * cc - x1 * sc) >> 14
        y2 = (y1 * cc - z2 * sc) >> 14                           # X axis
        z3 = (y1 * sc + z2 * cc) >> 14
        d = 36045 - z3                                           # 3D -> 2D: 230 / (2.2 - z)
        w[144 + v] = 160 + x2 * 230 // d
        w[160 + v] = 120 + y2 * 230 // d
        w[176 + v] = z3
    for v in range(16):
        bit = 1
        while bit < 16:
            if (v & bit) == 0:
                u = v | bit
                colour = 8 + ((int(w[176 + v]) + int(w[176 + u])) * 5 + 122880) // 32768
                if colour < 8:
                    colour = 8
                if colour > 15:
                    colour = 15
                s[i] = int(w[144 + v])
                s[i + 1] = int(w[160 + v])
                s[i + 2] = int(w[144 + u])
                s[i + 3] = int(w[160 + u])
                s[i + 4] = colour
                i += 5
            bit <<= 1


class Tesseract:
    name = 'tesseract'

    def __init__(self):
        # Allocated once, before the heap fragments. Stars first, then the
        # 32 edges, so edges are drawn on top.
        self.segs = array('i', (0 for _ in range(5 * (STARS + 32))))
        self.work = array('i', (0 for _ in range(3 * STARS + 48)))

    def enter(self, fb, play):
        fb.fill(0)
        for k in range(STARS):
            self.work[3 * k], self.work[3 * k + 1], self.work[3 * k + 2] = rnd(320) << 8, rnd(240), 1 + rnd(4)
        self.drawn = False

    def frame(self, fb, t, pal):
        pal[0] = 0x002
        for k in range(1, 5):
            pal[k] = 0x111 * (k * 3) + k
        for k in range(8):
            pal[8 + k] = scale(RAINBOW[(t // 2 + k * 10) & 255], 6 + k * 10 // 7)
        if self.drawn:
            fb.lines(self.segs, color=0)   # erase last frame's stars and edges
        _tesseract(self.segs, self.work, TRIG, t)
        fb.lines(self.segs)
        self.drawn = True


# ---- ribbon: a bouncing line and its point mirror leave a rainbow trail ----

TRAIL = 24


class Ribbon:
    name = 'ribbon'

    def __init__(self):
        self.ring = array('i', (0 for _ in range(10 * TRAIL)))   # TRAIL pairs of (line, mirrored line)

    def enter(self, fb, play):
        fb.fill(0)
        self.head = self.count = self.serial = 0
        self.p = [40, 30, 250, 200]
        self.v = [3, 2, -2, 3]

    def frame(self, fb, t, pal):
        pal[0] = 0
        for i in range(15):
            pal[1 + i] = RAINBOW[(i * 17 + t * 3) & 255]
        ring, h = self.ring, self.head
        if self.count == TRAIL:
            fb.lines(ring[h * 10:h * 10 + 10], color=0)   # erase the oldest pair
        p, v = self.p, self.v
        for k in range(4):
            limit = 239 if k & 1 else 319
            p[k] += v[k]
            if p[k] < 0 or p[k] > limit:
                p[k] = 0 if p[k] < 0 else limit
                v[k] = (-1 if p[k] else 1) * (2 + rnd(4))
        colour = 1 + self.serial % 15
        o = h * 10
        ring[o], ring[o + 1], ring[o + 2], ring[o + 3], ring[o + 4] = p[0], p[1], p[2], p[3], colour
        ring[o + 5], ring[o + 6], ring[o + 7], ring[o + 8] = 319 - p[0], 239 - p[1], 319 - p[2], 239 - p[3]
        ring[o + 9] = colour
        self.serial += 1
        self.head = (h + 1) % TRAIL
        self.count = min(self.count + 1, TRAIL)
        # Redraw the whole trail oldest first so the erase above leaves no gaps.
        if self.count == TRAIL:
            h = self.head
            fb.lines(ring[h * 10:])
            if h:
                fb.lines(ring[:h * 10])
        else:
            fb.lines(ring, self.count * 2)


_rng = [0x2545f491]


def rnd(n):
    _rng[0] = (_rng[0] * 1664525 + 1013904223) & 0xffffffff
    return (_rng[0] >> 16) % n


# ---- music: Am F C G, 16th-note arpeggio, eighth-note lead ----

CHORD = ((57, 60, 64), (57, 60, 65), (55, 60, 64), (55, 59, 62))
BASS = (45, 41, 48, 43)
LEAD = (76, 0, 72, 74, 76, 79, 76, 74, 72, 0, 69, 72, 77, 76, 72, 69,
        67, 72, 76, 79, 77, 76, 72, 74, 74, 0, 71, 67, 74, 76, 74, 71)
STEP = tuple(round(440 * 2 ** ((m - 69) / 12) * 16777216 / 48000) for m in range(96))


class Music:
    """Register writes are queued as (index, value) pairs and sent per tick
    with device.audio_writes(), one Viper call when accelerate() is on."""

    def __init__(self, d, R):
        self.d, self.R = d, R
        self.ops, self.n = bytearray(128), 0
        self.write(R.AUDIO_MASTER_GAIN, 48)
        for ch in range(6):
            self.gain(ch, 0, 0)
            if ch < 3:
                self.write(ch * 16 + R.AUDIO_DUTY, (32, 128, 64)[ch])
            if ch >= 4:
                self.write(ch * 16 + R.AUDIO_LEN_LOG2, 8)
            self.write(ch * 16 + R.AUDIO_CONTROL, R.AUDIO_CONTROL_ENABLE | R.AUDIO_CONTROL_PHASE_RESET)
        self.write(3 * 16 + R.AUDIO_NOISE_PERIOD_L, 6)
        self.write(3 * 16 + R.AUDIO_NOISE_PERIOD_H, 0)
        self.send()
        wave = bytearray(512)   # triangle then sine; AUDIO_COMMIT swaps banks, so write both
        for i in range(256):
            wave[i] = (i * 2 - 128 if i < 128 else 383 - i * 2) & 255
            wave[256 + i] = (SINE[i] - 127) & 255
        for _ in range(2):
            d.write_memory(0x9800, wave)
            d.audio_commit()

    def write(self, index, value):
        ops, n = self.ops, self.n
        ops[n], ops[n + 1] = index, value
        self.n = n + 2

    def send(self):
        d, ops, n = self.d, self.ops, self.n
        d.audio_writes(memoryview(ops)[:n])
        self.n = 0

    def note(self, ch, midi):
        step, base = STEP[midi], ch * 16 + self.R.AUDIO_STEP_L
        self.write(base, step & 255)
        self.write(base + 1, step >> 8 & 255)
        self.write(base + 2, step >> 16)

    def gain(self, ch, left, right):
        self.write(ch * 16 + self.R.AUDIO_GAIN_L, left)
        self.write(ch * 16 + self.R.AUDIO_GAIN_R, right)

    def tick(self, n):
        bar, s16 = n // 16 & 3, n & 15
        c, m = CHORD[bar], LEAD[bar * 8 + s16 // 2]
        self.note(0, c[s16 % 3] + 12 + 12 * (s16 // 3 & 1))                      # arpeggio
        self.gain(0, 12, 6)
        if m and not s16 & 1:
            self.note(1, m)
        lead = 0 if not m else (9 if s16 & 1 else 16)                            # lead, eighth-note decay
        self.gain(1, lead, lead)
        if s16 == 0:
            self.note(2, c[1])
        self.gain(2, 3, 5)                                                       # quiet third
        hat = 6 if s16 % 4 == 2 else 2
        self.gain(3, hat, hat)                                                   # hi-hat
        self.note(4, BASS[bar] + (12 if s16 & 4 else 0))                         # bass
        self.gain(4, 16 if s16 & 1 else 40, 16 if s16 & 1 else 40)
        if s16 == 0:
            self.note(5, BASS[bar] + 19)                                         # fifth pad
        self.gain(5, 10, 14)
        self.send()
        self.d.audio_commit()

    def stop(self):
        for ch in range(6):
            self.write(ch * 16 + self.R.AUDIO_CONTROL, 0)
        self.send()
        self.d.audio_commit()


def run(seconds=60, max_gap=16, fb=None):
    """Play the scenes for `seconds` (Ctrl-C stops). max_gap is passed to flush().

    Pass a TileFramebuffer created early when the heap is fragmented (its
    38400-byte buffer needs one contiguous block); its device is used as is.
    connect() turns on kagura.link: flush, COMMIT and the music are one Viper
    call per operation.
    """
    from kagura import regs as R
    own = fb is None
    if own:
        d = kagura.connect(mode='qspi', baudrate=5_000_000)
    else:
        d = fb.device
    music = None
    try:
        if own:
            fb = TileFramebuffer(d)
        pal, raw = array('H', [0] * 16), bytearray(32)
        base = 0x9400 + fb.palette * 32

        def show(level):
            _pack(raw, pal, level)
            d.write_memory(base, raw)

        d.clear_errors()
        show(0)   # initialize()'s COMMIT applies it
        fb.initialize()
        music = Music(d, R)
        print('FBDEMO GO viper=%s link=%s max_gap=%d' % (fb.viper_enabled, d.transport.link is not None, max_gap))
        scenes = (Plasma(), Tesseract(), Tunnel(), Ribbon())
        end = time.ticks_add(time.ticks_ms(), seconds * 1000)
        next_tick, tick, total, n = time.ticks_us(), 0, 0, 0

        def play():
            """Send the music tick when due; its duration in us, 0 when not due."""
            nonlocal next_tick, tick
            m0 = time.ticks_us()
            if time.ticks_diff(m0, next_tick) < 0:
                return 0
            music.tick(tick)
            tick += 1
            late = time.ticks_diff(m0, next_tick) > TICK_US
            next_tick = time.ticks_add(m0 if late else next_tick, TICK_US)   # resync after a stall
            return time.ticks_diff(time.ticks_us(), m0)

        while time.ticks_diff(end, time.ticks_ms()) > 0:
            scene = scenes[n % len(scenes)]
            n += 1
            gc.collect()
            t0 = time.ticks_ms()
            scene.enter(fb, play)   # long first pictures call play() as they go
            enter_ms = time.ticks_diff(time.ticks_ms(), t0)
            t0 = time.ticks_ms()
            leave = min(SCENE_MS, max(0, time.ticks_diff(end, t0)))
            draw_us = flush_us = busy_us = music_us = ticks = tiles = runs = frames = 0
            out, t = FADE, 0
            while out:
                if time.ticks_diff(time.ticks_ms(), t0) >= leave:
                    out -= 1
                now = time.ticks_us()
                f0 = time.ticks_us()
                scene.frame(fb, t, pal)
                draw_us += time.ticks_diff(time.ticks_us(), f0)
                stats = fb.flush(max_gap)   # its writes queue behind the previous COMMIT
                flush_us += stats['total_us']
                tiles += stats['tiles']
                runs += stats['runs']
                # The previous COMMIT has applied by now, so AUDIO_COMMIT does
                # not wait behind it for VBlank.
                us = play()
                if us:
                    music_us += us
                    ticks += 1
                show(min(16, t * 16 // FADE, out * 16 // FADE))
                busy_us += time.ticks_diff(time.ticks_us(), now)
                # Applied at the next VBlank. The next frame draws meanwhile;
                # its flush and this COMMIT stay in order in the device queue.
                d.commit(wait=False)
                frames += 1
                t += 1
            elapsed = time.ticks_diff(time.ticks_ms(), t0) / 1000
            print('FBDEMO scene=%s draw_first_ms=%d frames=%d fps=%.1f draw_mean_ms=%.2f flush_mean_ms=%.2f '
                  'busy_mean_ms=%.2f music_tick_ms=%.2f tiles_per_frame=%d runs_per_frame=%.1f'
                  % (scene.name, enter_ms, frames, frames / elapsed, draw_us / 1000 / frames, flush_us / 1000 / frames,
                     busy_us / 1000 / frames, music_us / 1000 / max(1, ticks), tiles // frames, runs / frames))
            total += frames
        d.check_errors()
        print('FBDEMO DONE after %d frames' % total)
    finally:
        if music:
            music.stop()
        if own:
            d.deinit()
