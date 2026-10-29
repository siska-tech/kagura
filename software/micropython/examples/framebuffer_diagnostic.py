# SPDX-License-Identifier: Apache-2.0
"""480p framebuffer scenes and numerical readback; see framebuffer-benchmark.py."""
import binascii
import gc
import json
import time

COLORS = (0x000,0xFFF,0xF33,0x3F3,0x33F,0xFF3,0xF3F,0x3FF,
          0x888,0xF93,0x93F,0x3F9,0x39F,0xF39,0x9F3,0xDDD)


def report(event, **values):
    values['event'] = event
    print('TILEFB ' + json.dumps(values))


def icons(M):
    """8x8 TILE4 badge, 16x16 GS4_HMSB opaque gem, 16x16 gem with key 0."""
    badge=bytearray(32)
    for y in range(8):
        for x in range(8):
            c=1 if x in (0,7) or y in (0,7) else (2+(x+y)%4 if abs(x-3.5)+abs(y-3.5)<4 else 9)
            badge[y*4+x//2]|=c<<(0 if x&1 else 4)
    gem=bytearray(128)
    for y in range(16):
        for x in range(16):
            d=abs(2*x-15)+abs(2*y-15)
            c=0 if d>15 else (1 if d>12 else (5 if y<8 else 13))
            gem[y*8+x//2]|=c<<(0 if x&1 else 4)
    return ((bytes(badge),8,8,M.TILE4),(bytes(gem),16,16,M.GS4_HMSB))


def draw_scene(f, name, M):
    """Font-free scenes F (blit), G (ellipse), H (paint); PC computes the same CRC."""
    if name=='F':
        badge,gem=icons(M)
        for x in range(0,320,16):f.fill_rect(x,0,8,240,8)  # stripes reveal the key
        for n in range(19):f.blit(badge,8+16*n,8)                    # aligned 8x8
        for n in range(9):f.blit(gem,8+32*n,24,None,None,None)       # opaque 16x16
        for n in range(14):f.blit(gem,3+22*n,49,None,None,0)         # keyed, odd x
        for n in range(26):f.blit(badge,5+12*n,75)                   # unaligned 8x8
        for x,y in ((-6,100),(312,100),(100,-7),(150,233),(-8,-8),(316,236)):
            f.blit(gem,x,y,None,None,0)                               # clipping
        for n in range(12):f.blit(gem,40+9*n,104+3*n,None,None,0)    # overlaps
        f.blit(gem,200,100,10,7,None,3,5)                             # sub-rectangle
        f.blit(f,170,150,140,80,None,0,0)       # self copy, no overlap
        f.blit(f,4,160,120,60,None,0,150)       # self copy, overlapping source
        return {}
    if name=='G':
        for k in range(8):f.ellipse(80,80,10+8*k,6+5*k,1+k)
        f.ellipse(240,40,70,12,9);f.ellipse(240,150,12,70,10)
        f.ellipse(160,200,50,25,11,True);f.ellipse(160,200,50,25,1)
        f.ellipse(230,200,25,25,12,True);f.circle(230,200,25,1)
        f.ellipse(-20,120,60,90,13);f.ellipse(330,250,80,40,14,True)
        f.ellipse(160,-30,100,50,15)
        f.ellipse(300,220,0,0,1);f.ellipse(306,220,3,0,1);f.ellipse(300,228,0,3,1)
        return {}
    if name=='H':
        results=[];peaks=[]
        def paint(x,y,c):
            results.append(f.paint(x,y,c));peaks.append(f.last_paint['peak'])
        f.rect(10,10,100,60,1);paint(50,40,2)                    # closed box
        f.ellipse(200,50,60,35,1);paint(200,50,3)                 # ellipse interior
        for a,b,c,d in ((20,85,70,170),(70,170,120,85),(120,85,20,140),(20,140,120,140),(120,140,20,85)):
            f.line(a,b,c,d,1)                                     # star outline
        paint(70,125,4);paint(70,150,5);paint(40,135,6)
        f.rect(140,90,170,140,1)                                  # thin corridor maze
        for y in range(93,228,3):
            f.hline(141,y,168,1);f.pixel(307 if (y//3)&1 else 142,y,0)
        paint(150,91,6)
        for n in range(12):                                       # adjacent cells
            x,y=10+n%4*30,180+n//4*18
            f.rect(x,y,31,19,1)
        for n in range(12):paint(15+n%4*30,185+n//4*18,7+n%8)
        # Same colour: no-op. CRCs, not a 38400 B copy (one plane only).
        before=binascii.crc32(f.buffer),binascii.crc32(f.dirty)
        paint(50,40,2)
        noop=f.last_paint['pixels']==0 and (binascii.crc32(f.buffer),binascii.crc32(f.dirty))==before
        paint(0,239,8)                                            # everything outside
        return dict(paint_results=results,paint_peaks=peaks,same_color_noop=noop)
    raise ValueError(name)


class Counter:
    def __init__(self, raw):
        self.raw = raw
        self.reset()
    def reset(self):
        self.writes = self.reads = self.tx_bytes = self.rx_bytes = 0
    def write(self, offset, data, inc=False):
        self.writes += 1
        self.tx_bytes += len(data)
        return self.raw.write(offset, data, inc)
    def readinto(self, offset, data, inc=False):
        self.reads += 1
        self.rx_bytes += len(data)
        return self.raw.readinto(offset, data, inc)
    def __getattr__(self, name):
        return getattr(self.raw, name)


class Session:
    def __init__(self, sdk='kagura', accelerated=True, viper=None):
        K = __import__(sdk, None, None, ['connect'])
        self.R = __import__(sdk+'.regs',None,None,['REG_STATUS'])
        self.FBM = __import__(sdk+'.framebuffer',None,None,['TileFramebuffer'])
        FB = self.FBM.TileFramebuffer
        self.Audio = __import__(sdk+'.audio',None,None,['Audio']).Audio
        self.d = K.connect(mode='qspi',baudrate=5_000_000)
        self.accel = None
        self.raw = self.d.transport
        self.pcm = False
        self.fb = None
        try:
            if accelerated:
                self.accel = self.raw.accelerate()
            self.counter = Counter(self.raw)
            self.d.transport = self.counter
            gc.collect()
            heap_before=gc.mem_free()
            self.fb = FB(self.d)
            self.fb.set_viper(viper)
            gc.collect()
            self.framebuffer_heap_bytes=heap_before-gc.mem_free()
            for i,c in enumerate(COLORS):self.fb.video.palette(i,c)
            gc.collect()
            start=time.ticks_us()
            self.fb.initialize()
            self.initialization_us=time.ticks_diff(time.ticks_us(),start)
            report('initialized',initialization_us=self.initialization_us,
                   viper_enabled=self.fb.viper_enabled,kernel_counts=self.fb.kernel_counts,
                   framebuffer_bytes=len(self.fb.buffer),dirty_bytes=len(self.fb.dirty),
                   framebuffer_heap_bytes=self.framebuffer_heap_bytes,
                   accelerated=accelerated,heap_free=gc.mem_free(),abi=list(self.d.abi),height=self.d.height)
        except BaseException:
            self.close()
            raise

    def scene(self, name):
        f=self.fb
        start=time.ticks_us()
        f.fill(0)
        if name=='A':
            # Encodes all 11 index bits without a second framebuffer.
            for tile in range(1200):
                x,y=tile%40*8,tile//40*8
                f.fill_rect(x+1,y+1,7,7,2+tile%14)
                for bit in range(11):
                    f.pixel(x+1+bit%6,y+2+bit//6,1 if tile&(1<<bit) else 0)
            # 3x5 corner glyphs occupy rows 1..5; rows 6..7 remain index code.
            glyphs={'T':(7,2,2,2,2),'L':(4,4,4,4,7),
                    'B':(6,5,6,5,6),'R':(6,5,6,5,5)}
            for x,y,label in ((0,0,'TL'),(312,0,'TR'),(0,232,'BL'),(312,232,'BR')):
                f.fill_rect(x,y,8,6,0)
                for n,ch in enumerate(label):
                    for yy,bits in enumerate(glyphs[ch]):
                        for xx in range(3):
                            if bits&(4>>xx):f.pixel(x+n*4+xx,y+1+yy,1)
            # Preserve a complete index code even in tiles covered by corner labels.
            for tile in range(1200):
                x,y=tile%40*8,tile//40*8
                for bit in range(11):
                    f.pixel(x+bit%6,y+6+bit//6,1 if tile&(1<<bit) else 0)
        elif name=='B':
            for c in range(16):f.fill_rect(c*20,0,20,32,c)
            for c in range(16):
                f.hline(0,40+c*2,320,c)
                f.vline(8+c*20,80,80,c)
            f.line(-20,70,340,220,1);f.line(319,70,0,239,7)
            f.rect(-10,90,80,80,5);f.fill_rect(250,170,90,100,9)
            for radius in (8,16,24,32,48):f.circle(160,155,radius,1+radius%15)
            f.rect(0,0,320,240,1)
        elif name=='C':
            # Tiles 1023=(23,25), 1024=(24,25), 1199=(39,29).
            f.text('1023 / 1024 ->',40,184,1)
            f.fill_rect(184,200,8,8,2);f.fill_rect(192,200,8,8,3)
            f.line(180,204,212,204,1)
            f.rect(311,231,9,9,7);f.text('1199 BR',240,216,1)
            f.fill_rect(312,232,8,8,6)
            f.rect(0,0,320,240,1);f.text('ABI 0.6 TILE BOUNDARY',8,8,1)
        elif name in ('F','G','H'):
            extra=draw_scene(f,name,self.FBM)
        else:raise ValueError('scene must be A, B, C, F, G or H')
        draw_us=time.ticks_diff(time.ticks_us(),start)
        crc=binascii.crc32(f.buffer)&0xFFFFFFFF
        stats=f.flush()
        if name not in ('F','G','H'):extra={}
        report('scene',name=name,draw_us=draw_us,flush=stats,buffer_crc32=crc,
               viper_enabled=f.viper_enabled,**extra)
        return stats

    def verify(self, full=True):
        # Also verify unused map entries, attributes and every upper-table byte.
        d,f=self.d,self.fb
        row=bytearray(128)
        for y in range(32):
            d.read_memory_into(0x8000+y*128,row)
            for x in range(64):
                expected=((y*40+x)&1023) if y<30 and x<40 else 0
                word=row[x*2]|row[x*2+1]<<8
                if word!=expected:raise AssertionError('map word %d,%d'%(x,y))
        upper=bytearray(256);d.read_memory_into(0x9000,upper)
        if upper!=f._map_high:raise AssertionError('map tile-bit10 table')
        data=bytearray(128)
        tiles=range(0,1200,4) if full else (0,1020,1024,1196)
        verified=0
        for tile in tiles:
            address=tile*32 if tile<1024 else 0xB000+(tile-1024)*32
            d.read_memory_into(address,data)
            if data!=f._view[tile*32:(tile+4)*32]:raise AssertionError('VRAM tile %d'%tile)
            verified+=128
            if tile%128==0:
                gc.collect();report('readback_progress',first_tile=tile,verified_bytes=verified)
        d.check_errors()
        report('readback_pass',full=full,pattern_bytes=verified,map_bytes=4096,upper_bytes=256)

    def pcm_start(self):
        R,d=self.R,self.d
        if not d.caps&R.CAPS_PSRAM:raise NotImplementedError('PSRAM build required')
        a=self.Audio(d)
        for c in range(6):a.stop(c)
        d.audio_write(R.AUDIO_MASTER_GAIN,64);d.audio_commit()
        self.pcm=True
        self.audio=a
        for channel,address,period in ((0,0x400000,128),(1,0x410000,64)):
            half=period//2
            cycle=bytes((((i if i<half else period-1-i)*(256//half))-128)&255 for i in range(period))
            d.write_memory(address,cycle*(4096//period));d.fence()
            a.prepare_pcm(channel,address,address+4096,loop=address)
            a.play_pcm(channel,left=12 if channel==0 else 0,right=12 if channel==1 else 0)
        self.pcm=True
        self.audio=a

    def telemetry(self):
        d,R=self.d,self.R
        error=d.read_reg(R.REG_ERROR_CODE)
        fifo=d.audio_read(R.AUDIO_STATUS)
        pcm=[self.audio.pcm_status(c) for c in (0,1)] if self.pcm else []
        if error or fifo&6 or any(s&0x78 or not s&R.AUDIO_PCM_STATUS_ACTIVE for s in pcm):
            raise AssertionError('telemetry fault %r'%((error,fifo,pcm),))
        return dict(error=error,fifo=fifo,pcm=pcm,frame=d.read_reg(R.REG_FRAME_COUNT_L))

    def close(self):
        try:
            if self.pcm:
                for c in (0,1):
                    base=self.R.AUDIO_PCM_BASE+c*self.R.AUDIO_PCM_STRIDE
                    self.d.audio_write(base+self.R.AUDIO_PCM_CONTROL,0)
                    self.d.audio_write(base+self.R.AUDIO_PCM_CMD,self.R.AUDIO_PCM_CMD_STOP)
                self.d.audio_commit()
        finally:
            self.d.transport=self.raw
            if self.accel is not None:self.accel.close()
            self.d.deinit()
