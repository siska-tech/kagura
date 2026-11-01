# SPDX-License-Identifier: Apache-2.0
"""MicroPython PROJECT STARFALL. Original C Stage 1; no firmware changes.

run(autoplay=True) for the showcase, run() for keyboard play. See starfall.md.
"""
import gc
import time
import micropython
from array import array
import starfall_viper as V
from kagura import regs as R
from starfall_core import Game, terrain, TITLE, BOOT, FIRE, EQUIP, LEFT, RIGHT, UP, DOWN
from starfall_render import Renderer
from starfall_sound import Sound
from starfall_scores import VIDEO_SIZE, VIDEO_CRC
from starfall_video import preload, CACHE_BASE

PATTERNS = 704*32
TITLE_OFFSET = PATTERNS+160
MAP_OFFSET = TITLE_OFFSET+4096
QUIT = 64


@micropython.native
def make_column(buffer,height,col):
    top,bottom = terrain(col,height)
    rng = (0x53544152 ^ (col*2654435761))&0xffffffff
    hud = (height//8-3)*8
    for row in range(32):
        rng = (rng*1664525+1013904223)&0xffffffff
        tile = 1 if rng>>27 == 0 else 2 if rng>>26 == 1 else 0
        if row*8 < top: tile = 173 if row*8 == top-8 else 175 if col%8 == 0 else 170
        if row*8 >= bottom and col >= 180: tile = 174 if row*8 == bottom else 175 if col%8 == 0 else 172 if (row+col)%4 == 0 else 171
        if tile in (170,171) and col%8 == 3: tile = 178 if row%2 else 179
        if row*8 >= hud: tile = 168 if row*8 == hud else 169
        buffer[row] = tile


class Backend:
    def __init__(self,d):
        self.d = d
        self.previous = bytearray(512)
        self.view = memoryview(self.previous)
        self.spans = array('H',[0]*128)
        self.column = bytearray(32)
        self.palette = bytearray(32)
        self.full_palette = None
        self.title = None
        self.tick = self.scroll = self.sky = 0
        self.last_col = 63
        self.raster = bool(d.caps&R.CAPS_RSCROLL)
        self.active_raster = False
        self.fade = -1
        self.oam_bytes = self.map_bytes = 0

    def load(self):
        d = self.d
        d.wait_status(R.STATUS_COMMIT_BUSY,0)
        d.write_reg(R.REG_DISPLAY_CTRL,0)
        d.commit()
        d.copy(CACHE_BASE,0,PATTERNS)
        d.copy(CACHE_BASE+PATTERNS,R.VRAM_PALETTE_BASE,160)
        d.fill(R.VRAM_MAP_EXT_BASE,R.VRAM_MAP_EXT_SIZE,0)
        d.fill(R.VRAM_OAM_BASE,R.VRAM_OAM_SIZE,0)
        d.ext_writes(bytes((R.EXT_SCROLL_Y,0,R.EXT_BACKDROP,0,R.EXT_RS_COUNT,0,
                           R.EXT_SCROLL_X_L,0,R.EXT_SCROLL_X_H,0)))
        d.fence()
        # Palette4 fade can be calculated from the original palette constants.
        self.full_palette = (0x001,0xeff,0x345,0x568,0x168,0x6ef,0xf93,0xf45,
                             0x8bf,0x647,0xff7,0x123,0x246,0x469,0x79a,0xfff)

    @micropython.native
    def present(self,g,oam):
        d = self.d
        d.wait_status(R.STATUS_COMMIT_BUSY,0)
        title = g.state in (TITLE,BOOT)
        changed = title != self.title
        if changed or not title and g.stage_tick < self.tick:
            d.write_reg(R.REG_DISPLAY_CTRL,0)
            d.commit()
            offset = TITLE_OFFSET if title else MAP_OFFSET+(4096 if g.height == 240 else 0)
            d.copy(CACHE_BASE+offset,R.VRAM_MAP_BASE,4096)
            d.fence()
            self.last_col = 63
            d.write_reg(R.REG_DISPLAY_CTRL,7)
        if changed and self.raster:
            d.ext_writes(bytes((R.EXT_RS_COUNT,0,R.EXT_RS_INDEX,0,
                               R.EXT_RS_LINE,40 if title else 48,R.EXT_RS_X_L,0,R.EXT_RS_X_H,0,R.EXT_RS_Y,0,
                               R.EXT_RS_LINE,104 if title else (g.height//8-3)*8-48,R.EXT_RS_X_L,0,R.EXT_RS_X_H,0,R.EXT_RS_Y,0)))
        desired = g.stage_tick//8+63
        while not title and self.last_col < desired:
            col = self.last_col+1
            make_column(self.column,g.height,col)
            # Existing API exposes a strided write through the public transport.
            # Busy ownership covers the INDEX/ADDR/WRITE compound operation.
            d.busy += 1
            try:
                d.transport.write(R.REG_INC_L,b'\x80\x00',True)
                address = R.VRAM_MAP_BASE+(col&63)*2
                d.transport.write(R.REG_VRAM_ADDR_L,bytes((address&255,(address>>8)&255,address>>16)),True)
                d.transport.write(R.REG_VRAM_WRITE,self.column)
                d.check_errors()
            finally: d.busy -= 1
            self.last_col = col
            self.map_bytes += 32
        # Merge contiguous changed records. 512 bytes maximum, no OAM objects.
        view = memoryview(oam)
        spans = self.spans
        n = V.dirty(oam,self.previous,spans)
        if n:
            # One bounded span beats several tiny synchronous Python calls.
            # Clean gaps cost at most 512 payload bytes, without extra headers.
            first,end = spans[0],spans[n-1]
            d.write_memory(R.VRAM_OAM_BASE+first,view[first:end])
            self.oam_bytes += end-first
        sky = (g.state_age//8 if title else g.stage_tick//3)&511
        scroll = (sky if self.raster else 0) if title else g.scroll
        pairs = bytearray()
        if scroll&255 != self.scroll&255: pairs.extend((R.EXT_SCROLL_X_L,scroll&255))
        if scroll>>8 != self.scroll>>8: pairs.extend((R.EXT_SCROLL_X_H,scroll>>8))
        use = self.raster and (title or g.stage_tick < 1120)
        if use != self.active_raster or changed: pairs.extend((R.EXT_RS_COUNT,2 if use else 0))
        if use:
            for i in range(2):
                x = (sky if i else 0) if title else (g.scroll if i else sky)
                old = self.scroll if i else self.sky
                if x != old or not self.active_raster or changed:
                    pairs.extend((R.EXT_RS_INDEX,i,R.EXT_RS_X_L,x&255,R.EXT_RS_X_H,x>>8))
        if pairs: d.ext_writes(pairs)
        fade = min(15,g.state_age//4) if title else 15
        if fade != self.fade:
            for i in range(16):
                c,out = self.full_palette[i],0
                for shift in (0,4,8): out |= ((c>>shift&15)*fade//15)<<shift
                self.palette[i*2],self.palette[i*2+1] = out&255,out>>8
            d.write_memory(R.VRAM_PALETTE_BASE+128,self.palette)
        d.commit(False)
        self.previous[:] = oam
        self.title,self.tick,self.scroll,self.sky,self.active_raster,self.fade = title,g.stage_tick,scroll,sky,use,fade


class Keyboard:
    def __init__(self):
        import sys,select
        self.stream = sys.stdin
        self.poller = select.poll()
        self.poller.register(sys.stdin,select.POLLIN)
        self.ready = getattr(self.poller,'ipoll',self.poller.poll)
        self.keys = self.until = 0

    def __call__(self):
        now = time.ticks_ms()
        if time.ticks_diff(now,self.until) >= 0: self.keys = 0
        for _ in range(16):
            found = False
            for _ in self.ready(0):
                found = True
                key = self.stream.read(1).lower()
                if key == 'q': return QUIT
                value = {'a':LEFT,'d':RIGHT,'w':UP,'s':DOWN,' ':FIRE,'\r':FIRE,'\n':FIRE,'x':EQUIP}.get(key,0)
                self.keys |= value
                self.until = time.ticks_add(now,140)
            if not found: break
        return self.keys


def run(device=None,assets='starfall_assets',duration=0,autoplay=False,input_fn=None,
        cached=False,report=True):
    """0 duration repeats; autoplay uses the real C attract inputs, not video."""
    if duration < 0 or not gc.isenabled(): raise ValueError('duration >= 0 and GC enabled required')
    import kagura
    start = time.ticks_us()
    own = device is None
    d = kagura.connect(mode='qspi',baudrate=5000000) if own else device
    sound = None
    frames = peak = cpu_sum = cpu_max = io_sum = io_max = 0
    step_sum = render_sum = sound_sum = staging_sum = 0
    try:
        if d.abi != (0,6) or d.height not in (180,240): raise ValueError('STARFALL needs ABI 0.6, 180/240 lines')
        d.require(R.CAPS_SPR16|R.CAPS_PSRAM)
        d.check_errors()
        if not cached: preload(d,assets)
        backend,renderer,g = Backend(d),Renderer(d.height),Game(d.height)
        g.fit = renderer.fit
        control = input_fn if input_fn is not None else Keyboard()
        sound = Sound(d)
        backend.load()
        sound.load()
        if autoplay: g.start(True)
        gc.collect()
        loaded = time.ticks_diff(time.ticks_us(),start)
        if report: print('STARFALL ready_us',loaded,'free',gc.mem_free())
        begin = time.ticks_us()
        clock_last,clock_units,simulation_ticks = begin,1001000,0
        lag_max = 0
        limit = int(duration*1000000)
        while not limit or time.ticks_diff(time.ticks_us(),begin) < limit:
            keys = control()
            if keys&QUIT: break
            t = time.ticks_us()
            # Run the 59.94 Hz simulation independently of rendered frames.
            # Bound catch-up work, keep the debt, and never teleport projectiles.
            clock_units += time.ticks_diff(t,clock_last)*60
            clock_last = t
            due = min(4,clock_units//1001000)
            clock_units -= due*1001000
            lag_max = max(lag_max,clock_units//1001000)
            frame_sound = 0
            for _ in range(due):
                g.step(keys)
                frame_sound = max(frame_sound,g.sound)
            g.sound = frame_sound
            simulation_ticks += due
            stepped = time.ticks_us()
            oam = renderer.render(g)
            step_sum += time.ticks_diff(stepped,t)
            render_sum += time.ticks_diff(time.ticks_us(),stepped)
            cpu = time.ticks_diff(time.ticks_us(),t)
            t = time.ticks_us()
            backend.present(g,oam)
            staged = time.ticks_us()
            # Sound and next frame CPU work overlap the pending video COMMIT.
            sound.update(g,due)
            sound_sum += time.ticks_diff(time.ticks_us(),staged)
            staging_sum += time.ticks_diff(staged,t)
            elapsed = time.ticks_diff(time.ticks_us(),t)
            frames += 1
            cpu_sum += cpu
            cpu_max = max(cpu_max,cpu)
            io_sum += elapsed
            io_max = max(io_max,elapsed)
            peak = max(peak,renderer.peak)
        d.wait_status(R.STATUS_COMMIT_BUSY,0)
        elapsed = time.ticks_diff(time.ticks_us(),begin)
        d.check_errors()
        irq = d.read_reg(R.REG_IRQ_STATUS)
        audio = d.audio_read(R.AUDIO_STATUS) if sound.enabled else 0
        result = dict(frames=frames,elapsed_us=elapsed,ready_us=loaded,peak_line=peak,
                      simulation_ticks=simulation_ticks,lag_max_ticks=lag_max,
                      cpu_mean_us=cpu_sum//max(1,frames),cpu_max_us=cpu_max,
                      step_mean_us=step_sum//max(1,frames),render_mean_us=render_sum//max(1,frames),
                      sound_mean_us=sound_sum//max(1,frames),staging_mean_us=staging_sum//max(1,frames),
                      present_mean_us=io_sum//max(1,frames),present_max_us=io_max,
                      oam_bytes=backend.oam_bytes,map_bytes=backend.map_bytes,
                      sprite_overflow=bool(irq&R.IRQ_STATUS_SPR_OVERFLOW),
                      audio_fault=audio&(R.AUDIO_STATUS_FIFO_UNDERFLOW|R.AUDIO_STATUS_OVERFLOW))
        if report: print('STARFALL result',result)
        if result['sprite_overflow'] or result['audio_fault']: raise RuntimeError('STARFALL hardware fault')
        return result
    except KeyboardInterrupt:
        return None
    finally:
        try:
            d.wait_status(R.STATUS_COMMIT_BUSY,0)
            if sound is not None: sound.stop()
            d.write_reg(R.REG_DISPLAY_CTRL,0)
            d.commit()
        finally:
            if own: d.deinit()
