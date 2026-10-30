import sys,gc,hashlib,binascii
sys.path.insert(0,'/fbx')
for path,expected in {'/lib/kagurafbx/__init__.py': 'e6893051d4a23de6726c58cbc238865e88df4ad5b1da8e1b882e06357f10f9be', '/lib/kagurafbx/regs.py': '8d587b4f00c8ef182bec2d790c127ad78300e6a02bc63906564fe39a6169fc59', '/lib/kagurafbx/device.py': '787b3d3c180cf9d0ab7803d8ba376c1c71230381c288ff942f8921ddde80fddd', '/lib/kagurafbx/video.py': '4c7315b431ed12945b5e2acc69a2b42485982e53e24721d384fb9c8d99f0fc78', '/lib/kagurafbx/audio.py': '553227ebef8ea9b56deb35c6520706e5ba3e6adb380e9c520398be3e6b105de9', '/lib/kagurafbx/transport_rp2.py': '3f88087006b489a0c483c99e2df0fd2aef5fd8f52d88883983eef9990deee32e', '/lib/kagurafbx/dma_pack.py': '88873707c3c502cce3956a04e7409ec4f446e5ae0f18964569c6d48571b77f74', '/lib/kagurafbx/fifo_xfer.py': 'e0aa4bb55a0bc7f4f6a3a7bcf1633032bdafd3dbadabefdae09620e381b93d97', '/lib/kagurafbx/acceleration.py': '7bb1bdde65aba80e53f4154c3ec2a6adeeddde426454aab7ee0e32d118d330e2', '/lib/kagurafbx/framebuffer.py': '5fd68d616f25efbcf6f59676eb52839a9487d49acc88a8995cb5bb844c346de1', '/lib/kagurafbx/framebuffer_viper.py': 'ba1f378e9360cfc2b0ba3774213df53108cef26bf2286c5dd030d86c5b40d93d', '/fbx/framebuffer_diagnostic.py': 'c1d3a2349f90ac79b8af0ac6b6f89eb65198efde9886e5472e98446baf2dba28', '/fbx/framebuffer_benchmark.py': 'd6028ddb9b32bb4e7a6a769d464cfc33fa53448fede12e38a7ee4f1d2905a957', '/fbx/framebuffer_viper_cases.py': '192bf0d3143cf34f54a776e5c5cfef4756f0dd9625dcb83e5338b936114b23f7', '/fbx/framebuffer_viper_validation.py': '6a3ccd2eb30f4d0894eed7ca051959c815d46333cffc3f786e7c903805eef8d1', '/fbx/framebuffer_shapes.py': '38304f6ad85f382c91a2f0548e853fa3f5774f25d9786590fdb1a6d150976191'}.items():
 h=hashlib.sha256()
 with open(path,'rb') as file:
  while True:
   block=file.read(512)
   if not block:break
   h.update(block)
 assert binascii.hexlify(h.digest()).decode()==expected,path
print('GAP_BASELINE_SDK_HASHES_PASS',16)
del h,block
gc.collect()
from time import ticks_us,ticks_diff

# SPDX-License-Identifier: Apache-2.0
"""ABI 0.6 baseline. Run with an initialized framebuffer_diagnostic.Session.

No printing in timed regions. Samples are bounded per case, not a recent ring.
Transport profiling is a separate, deliberately instrumented pass.
"""
import gc
import time
from array import array
from framebuffer_diagnostic import report, icons


def detail(values):
    v = sorted(values)
    n = len(v)
    return dict(count=n, mean_us=sum(v)/n,
                median_us=(v[(n-1)//2]+v[n//2])/2,
                p95_us=v[(95*n+99)//100-1], max_us=v[-1],
                samples_us=list(values))


def indices(count, layout):
    if layout == 'compact_rect':
        width=16 if count<=256 else 32
        return array('H',(n//width*40+n%width for n in range(count))) if count<=width*30 else None
    if layout == 'boundary':
        start=max(0,min(1023 if count==1 else 1024-count//2,1200-count))
        return range(start,start+count)
    if layout == 'contiguous':
        return range(count)
    if layout == 'dispersed':
        # Coprime permutation, exactly count unique tiles, including >600.
        marks=bytearray(1200)
        for n in range(count):marks[(n*599)%1200]=1
        return array('H',(n for n in range(1200) if marks[n]))
    width = 4 if layout == 'narrow_rect' else 40
    return array('H',(n//width*40+n%width for n in range(count))) if count <= width*30 else None


def micro(session, repetitions=30, counts=(0,1,2,10,32,100,256,512,1023,1024,1200),
          layouts=('contiguous','dispersed','narrow_rect','wide_rect','boundary')):
    f = session.fb
    for count in counts:
        for layout in layouts:
            selected=None;gc.collect()
            selected = indices(count, layout)
            if selected is None:
                report('micro_skipped', tiles=count, layout=layout, reason='exceeds 30 rows')
                continue
            times = {k:array('I') for k in ('draw','flush','transfer','wait','gc','residual')}
            last = None
            for n in range(repetitions+3):
                # Only modify selected tiles; prior flush has confirmed all dirty.
                before=time.ticks_us();gc.collect();g=time.ticks_diff(time.ticks_us(),before)
                before=time.ticks_us()
                for tile in selected:f.pixel(tile%40*8,tile//40*8,1+n%15)
                draw=time.ticks_diff(time.ticks_us(),before)
                session.counter.reset()
                before=time.ticks_us();last=f.flush();elapsed=time.ticks_diff(time.ticks_us(),before)
                if n>=3:
                    for key,value in (('draw',draw),('flush',elapsed),('transfer',last['transfer_us']),
                                      ('wait',last['wait_us']),('gc',g),
                                      ('residual',last['total_us']-last['transfer_us']-last['wait_us'])):
                        times[key].append(value)
            report('transport_micro',tiles=count,layout=layout,warmup=3,
                   timing={k:detail(v) for k,v in times.items()},last_flush=last,
                   register_writes=session.counter.writes,register_reads=session.counter.reads,
                   tx_payload=session.counter.tx_bytes,rx_payload=session.counter.rx_bytes,
                   telemetry=session.telemetry(),heap_free=gc.mem_free())
            gc.collect()


def scenes(session, repetitions=30, gc_interval=32, names=('A','B','C','D'), full_source=None,
           memory_interval=32):
    f=session.fb
    badge,gem=icons(session.FBM)
    for name in names:
        source=(full_source,320,240,session.FBM.TILE4) if name=='D' and full_source is not None else None
        column=bytearray(960) if name=='D' and source is None else None
        f.fill(0);f.flush()
        metrics={k:array('I') for k in ('draw','flush','loop','gc','memory_sampling','tiles','bytes','transactions')}
        free_min=gc.mem_free()
        free_max=free_min;allocated_max=gc.mem_alloc();free_before_gc_min=free_min
        for n in range(repetitions+3):
            if n==3:scene_start=time.ticks_us()
            begin=time.ticks_us()
            if name=='A':
                old=max(0,n-1)*5%240;x=n*5%240
                f.fill_rect(old,40,64,48,0);f.fill_rect(x,40,64,48,3)
                f.rect(x,40,64,48,1);f.blit(gem,x+8,56,None,None,0)
                f.fill_rect(8,16,120,8,0);f.text('GUI %03d'%n,8,16,1)
                f.fill_rect(8,30,8,8,1 if n%2 else 0)
            elif name=='B':
                for obj in range(6):
                    old=((max(0,n-1)*5+obj*43)%296,32+obj*28)
                    x=(n*5+obj*43)%296;y=32+obj*28
                    f.fill_rect(old[0],old[1],16,16,0);f.blit(gem,x,y,None,None,0)
            elif name=='C':
                f.fill_rect(32,32,256,176,0)
                f.line(32,32,287,207,1);f.rect(48,48,224,144,2)
                f.ellipse(160,120,80,48,3);f.paint(160,120,4+n%8)
            else:
                if n%3==0:f.fill(1+n%15)
                elif n%3==1:
                    if source is not None:f.blit(source,0,0)
                    else:
                        # Actual whole-plane copy without a second 38400 B plane.
                        # Pattern creation belongs to this scene's draw cost.
                        f.fill(0)
                        for col in range(40):f.fill_rect(col*8,0,8,240,1+(col+n)%15)
                        for row in range(30):column[row*32:(row+1)*32]=f._view[row*1280:row*1280+32]
                        f.blit(f,0,0,312,240,None,8,0)
                        f.blit((column,8,240,session.FBM.TILE4),312,0)
                else:f.fill_rect(0,0,320,240,1+n%15)
            draw=time.ticks_diff(time.ticks_us(),begin)
            session.counter.reset()
            start=time.ticks_us();stats=f.flush();flush=time.ticks_diff(time.ticks_us(),start)
            transactions=session.counter.writes+session.counter.reads
            memory_us=0
            if n%memory_interval==0:
                start=time.ticks_us()
                free_before_gc_min=min(free_before_gc_min,gc.mem_free())
                allocated_max=max(allocated_max,gc.mem_alloc())
                memory_us=time.ticks_diff(time.ticks_us(),start)
            start=time.ticks_us()
            if n%gc_interval==0:gc.collect()
            g=time.ticks_diff(time.ticks_us(),start) if n%gc_interval==0 else 0
            if n%memory_interval==0:
                start=time.ticks_us();free=gc.mem_free()
                free_min=min(free_min,free);free_max=max(free_max,free)
                memory_us+=time.ticks_diff(time.ticks_us(),start)
            telemetry=session.telemetry()
            elapsed=time.ticks_diff(time.ticks_us(),begin)
            if n>=3:
                for key,value in (('draw',draw),('flush',flush),('loop',elapsed),('gc',g),('memory_sampling',memory_us),
                                  ('tiles',stats['tiles']),('bytes',stats['bytes']),
                                  ('transactions',transactions)):
                    metrics[key].append(value)
        wall_elapsed=time.ticks_diff(time.ticks_us(),scene_start)
        report('transport_scene',scene=name,pcm=session.pcm,warmup=3,gc_interval=gc_interval,
               memory_sample_interval=memory_interval,memory_read_calls_per_sample=3,scene_definition_revision=2,
               full_blit_mode=('independent_source' if source is not None else 'inplace_scroll_wrap') if name=='D' else None,
               full_blit_source_bytes=(38400 if source is not None else 960) if name=='D' else None,
               loop_includes_telemetry=True,
               timing={k:detail(v) for k,v in metrics.items() if k not in ('tiles','bytes','transactions')},
               tiles=list(metrics['tiles']),bytes=list(metrics['bytes']),
               transactions=list(metrics['transactions']),
               application_updates_s=1e6*repetitions/wall_elapsed,wall_elapsed_us=wall_elapsed,
               application_work_updates_s=1e6*repetitions/sum(metrics['loop']),
               physically_presented_updates_hz=None,heap_free_sample_min=free_min,
               heap_free_sample_max=free_max,heap_alloc_sample_max=allocated_max,
               heap_free_before_gc_min=free_before_gc_min,telemetry=telemetry)
        session.verify(full=False)
        source=None;column=None;gc.collect()


def calibration(repetitions=30):
    values=array('I');empty=array('I')
    gc.collect()
    for _ in range(repetitions):
        start=time.ticks_us();empty.append(time.ticks_diff(time.ticks_us(),start))
        start=time.ticks_us()
        gc.mem_free();gc.mem_alloc();gc.mem_free();gc.mem_free()
        values.append(time.ticks_diff(time.ticks_us(),start))
    report('transport_calibration',heap_api_four_calls=detail(values),clock_pair=detail(empty),
           note='Old scene used four heap scans per update; no correction subtracted from raw samples')


class Profile:
    """Inclusive transport buckets. Never add parent and child totals."""
    def __init__(self, session):
        self.session=session
        self.saved=[]
        self.values={}
    def wrap(self,obj,name,label):
        previous=getattr(obj,name)
        own=obj.__dict__.get(name)
        self.saved.append((obj,name,own))
        self.values[label]=[0,0]
        def call(*args,**kwargs):
            start=time.ticks_us()
            try:return previous(*args,**kwargs)
            finally:
                v=self.values[label];v[0]+=time.ticks_diff(time.ticks_us(),start);v[1]+=1
        setattr(obj,name,call)
    def close(self):
        for obj,name,own in reversed(self.saved):
            if own is None:delattr(obj,name)
            else:setattr(obj,name,own)
    def run(self):
        s=self.session;r=s.raw;d=s.d
        package=s.FBM.__name__.rsplit('.',1)[0]
        pack=__import__(package+'.dma_pack',None,None,['pack32']).pack32
        timeout=__import__(package+'.transport_rp2',None,None,['TransferTimeout']).TransferTimeout
        dma=[0,0,0,0]
        # Same synchronous handshake as dma_pack.transfer; adapted from the
        # existing benchmarks/dma_profile.py. Timing additions are intrusive.
        def profiled_dma(data,queued):
            high,words=r._high[queued],r._words
            tx,rx=r._dma_tx,r._dma_rx
            n,done=len(data),0
            while done<n:
                m=min(128,n-done)
                start=time.ticks_us();pack(data,high,words,done,m)
                dma[0]+=time.ticks_diff(time.ticks_us(),start)
                start=time.ticks_us()
                rx.config(read=r._sm,write=r._sink,count=m,ctrl=r._rx_ctrl,trigger=True)
                tx.config(read=words,write=r._sm,count=m,ctrl=r._tx_ctrl,trigger=True)
                dma[1]+=time.ticks_diff(time.ticks_us(),start)
                start=time.ticks_us();left=m;progress=time.ticks_us()
                while rx.active():
                    count=rx.count
                    if count!=left:left=count;progress=time.ticks_us()
                    elif time.ticks_diff(time.ticks_us(),progress)>=r.timeout_us:
                        raise timeout(done+max(0,m-left-1))
                dma[2]+=time.ticks_diff(time.ticks_us(),start)
                dma[3]+=1;done+=m
        self.saved.append((r,'_xfer_dma',r.__dict__.get('_xfer_dma')))
        r._xfer_dma=profiled_dma
        previous_write=d.write_reg
        self.saved.append((d,'write_reg',d.__dict__.get('write_reg')))
        self.values['command_issue']=[0,0]
        def write_reg(offset,value):
            if offset!=s.R.REG_COMMAND:return previous_write(offset,value)
            start=time.ticks_us()
            try:return previous_write(offset,value)
            finally:
                v=self.values['command_issue'];v[0]+=time.ticks_diff(time.ticks_us(),start);v[1]+=1
        d.write_reg=write_reg
        for obj,name,label in ((r,'_begin','transaction_begin'),(r,'_end','transaction_end'),
                (r,'_xfer','fifo_pump'),(r,'_xfer_dma','dma_pack_config_wait'),
                (d,'_address','vram_address'),(d,'check_errors','error_check'),
                (d,'_wait','completion_poll'),(d,'fence','fence')):
            self.wrap(obj,name,label)
        if s.accel.pump is not None:
            self.wrap(s.accel.pump,'_packet','native_packet')
        try:
            for index,(count,layout) in enumerate(((0,'contiguous'),(1,'contiguous'),(100,'contiguous'),
                                 (100,'dispersed'),(1024,'contiguous'),(1200,'contiguous'))):
                for k in self.values:self.values[k][0]=self.values[k][1]=0
                for k in range(4):dma[k]=0
                for tile in indices(count,layout):s.fb.pixel(tile%40*8,tile//40*8,7+index)
                dirty=s.fb.dirty
                probe=DirtyProbe(dirty)
                gc.collect()
                try:
                    s.fb.dirty=probe
                    stats=s.fb.flush()
                finally:s.fb.dirty=dirty
                assert stats['tiles']==count
                report('transport_profile',tiles=count,layout=layout,inclusive_us_calls=self.values,
                       profile_revision=2,
                       dirty_scan_us=probe.scan_us,dirty_confirm_us=probe.confirm_us,
                       dma_pack_config_wait_us_chunks=dma,
                       flush=stats,instrumented=True)
        finally:self.close()
        s.verify(full=False)


class DirtyProbe:
    # Used ONLY for _flush's find/slice assignment, never a raster pointer.
    def __init__(self, data):
        self.data=data
        self.scan_us=self.confirm_us=0
    def find(self,*args):
        start=time.ticks_us()
        try:return self.data.find(*args)
        finally:self.scan_us+=time.ticks_diff(time.ticks_us(),start)
    def __setitem__(self,key,value):
        start=time.ticks_us()
        try:self.data[key]=value
        finally:self.confirm_us+=time.ticks_diff(time.ticks_us(),start)


def chunks(session, repetitions=30):
    """Existing reversible options only; same payload and safety checks."""
    s=session
    s.accel.close()
    try:
        for chunk in (128,256,512):
            s.accel=s.raw.accelerate(chunk=chunk)
            assert s.accel.enabled
            for count in (1,100,1200):
                values=array('I')
                for n in range(repetitions+3):
                    for tile in range(count):s.fb.pixel(tile%40*8,tile//40*8,1+n%15)
                    gc.collect();stats=s.fb.flush()
                    if n>=3:values.append(stats['total_us'])
                report('transport_chunk',chunk=chunk,tiles=count,timing=detail(values),
                       telemetry=s.telemetry())
            s.verify(full=False)
            s.accel.close()
    finally:
        if not s.accel.closed:s.accel.close()
        s.accel=s.raw.accelerate(chunk=128)


def primitives(session,repetitions=30):
    f=session.fb
    _,gem=icons(session.FBM)
    source=(bytes(range(256))*37+bytes(range(128)),160,120,session.FBM.TILE4)
    cases=(('blit16',lambda:f.blit(gem,80,64)),
           ('blit160x120',lambda:f.blit(source,80,64)),
           ('line',lambda:f.line(0,0,319,239,7)),
           ('rect256x176',lambda:f.rect(32,32,256,176,7)),
           ('ellipse_outline',lambda:f.ellipse(160,120,150,110,7)),
           ('ellipse_fill',lambda:f.ellipse(160,120,150,110,7,True)),
           ('paint254x174',lambda:f.paint(160,120,7)))
    for name,draw in cases:
        values=array('I');gc_values=array('I')
        for n in range(repetitions+3):
            f.fill(0)
            if name.startswith('paint'):f.rect(32,32,256,176,1)
            before=time.ticks_us();gc.collect();g=time.ticks_diff(time.ticks_us(),before)
            before=time.ticks_us();result=draw();elapsed=time.ticks_diff(time.ticks_us(),before)
            if name.startswith('paint'):assert result and f.last_paint['complete']
            if n>=3:values.append(elapsed);gc_values.append(g)
        report('transport_primitive',name=name,timing=detail(values),gc=detail(gc_values),
               viper=f.viper_enabled,kernel_counts=f.kernel_counts)
    f.mark_dirty();f.flush();session.verify(full=False)


def run(session, repetitions=30, full_source=None):
    if not 10<=repetitions<=100:raise ValueError('repetitions 10..100')
    assert session.fb.viper_enabled and session.d.abi==(0,6)
    machine=__import__('machine')
    sm=session.raw._sm_id
    clkdiv=machine.mem32[0x50200000+(sm//4)*0x100000+0xc8+(sm%4)*0x18]
    report('transport_begin',repetitions=repetitions,clock_hz=machine.freq(),pio_clkdiv_register=clkdiv,
           baudrate=session.raw.baudrate,accelerated=session.accel.enabled,
           dma_chunk=128,pcm_policy='looping PSRAM 2ch, all measured cases')
    session.pcm_start()
    calibration(repetitions)
    micro(session,repetitions)
    scenes(session,repetitions,full_source=full_source)
    Profile(session).run()
    chunks(session,repetitions)
    primitives(session,repetitions)
    session.verify(full=True)
    report('transport_complete',telemetry=session.telemetry())

from kagurafbx.framebuffer import TileFramebuffer as OriginalFramebuffer
from kagurafbx.device import _range
class GapFramebuffer(OriginalFramebuffer):
    def flush(self, max_gap=0):
            """No I/O if clean; failure keeps the entire unconfirmed run dirty.
    
            Counters count requested pattern writes/bytes, not individual SPI
            register transactions. transfer_us includes write_memory error checks;
            wait_us includes FENCE and its checks, not a pure FPGA execution time.
            max_gap opts into sending clean gaps of at most this many tiles between
            dirty runs. Default 0 preserves exact dirty transfer. Counts describe
            sent tiles, including gaps. The buffer must be the sole VRAM owner.
            """
            if not self.initialized:
                raise RuntimeError('call initialize() successfully before flush()')
            _range(max_gap, 0, 1198, 'max_gap')
            return self._flush(max_gap)
    def _flush(self, max_gap=0):
            stats = self._stats()
            self.last_flush = stats
            start = ticks_us()
            d = self.device
            d.busy += 1
            try:
                if max_gap:
                    # Mark additional writes dirty before I/O. A failed write or
                    # FENCE must never leave any part of its expanded run clean.
                    first = self.dirty.find(b'\x01')
                    while first >= 0:
                        end = self.dirty.find(b'\x00', first)
                        if end < 0:
                            break
                        following = self.dirty.find(b'\x01', end)
                        if following < 0:
                            break
                        if following - end <= max_gap:
                            self.dirty[end:following] = b'\x01' * (following - end)
                        first = following
                tile = 0
                while tile < 1200:
                    first = self.dirty.find(b'\x01', tile)
                    if first < 0:
                        break
                    tile = self.dirty.find(b'\x00', first)
                    if tile < 0:
                        tile = 1200
                    count = tile - first
                    stats['runs'] += 1
                    stats['bytes'] += count * 32
                    stats['writes'] += 1 + int(first < 1024 < tile)
                    begin = ticks_us()
                    try:
                        self.video.tiles(first, self._view[first * 32:tile * 32])
                    finally:
                        stats['transfer_us'] += ticks_diff(ticks_us(), begin)
                    begin = ticks_us()
                    stats['fences'] += 1
                    try:
                        d.fence()
                        d.check_errors()
                    finally:
                        stats['wait_us'] += ticks_diff(ticks_us(), begin)
                    # No callback may draw while busy; only a confirmed run is clean.
                    self.dirty[first:tile] = bytes(count)
                    stats['tiles'] += count
            finally:
                d.busy -= 1
                stats['total_us'] = ticks_diff(ticks_us(), start)
            return stats
import kagurafbx.framebuffer as _fb_module
_fb_module.TileFramebuffer=GapFramebuffer

# SPDX-License-Identifier: Apache-2.0
"""Paired opt-in dirty-gap / existing DMA-option experiment, not default tuning.

Run with an exclusive initialized framebuffer_diagnostic.Session. Requires
framebuffer_transport_benchmark.py on the import path. No timed logging.
"""
import gc
import time
from array import array
from framebuffer_diagnostic import report



def run(session, repetitions=30):
    if not 10 <= repetitions <= 100:
        raise ValueError('repetitions 10..100')
    f = session.fb
    original = f.flush
    overridden = False
    session.pcm_start()
    try:
        for chunk, gap in ((128, 0), (128, 1), (512, 1)):
            session.accel.close()
            session.accel = session.raw.accelerate(chunk=chunk)
            assert session.accel.enabled
            # Same renderer, buffers, stimulus, FW and observer for all options.
            f.flush = lambda: original(max_gap=gap)
            overridden = True
            report('gap_config', chunk=chunk, max_gap=gap,
                   clock_hz=__import__('machine').freq(), baudrate=session.raw.baudrate)
            cases = (('clean', ()), ('one', (0,)), ('bank_gap', (1022, 1024)),
                     ('dispersed100', indices(100, 'dispersed')),
                     ('compact256', indices(256, 'compact_rect')),
                     ('full1200', range(1200)))
            for name, selected in cases:
                f.fill(0)
                f.flush()
                elapsed = array('I')
                for n in range(repetitions + 3):
                    for tile in selected:
                        f.pixel(tile % 40 * 8, tile // 40 * 8, 1 + n % 15)
                    gc.collect()
                    session.counter.reset()
                    start = time.ticks_us()
                    stats = f.flush()
                    duration = time.ticks_diff(time.ticks_us(), start)
                    if n >= 3:
                        elapsed.append(duration)
                report('gap_micro', case=name, chunk=chunk, max_gap=gap,
                       warmup=3, timing=detail(elapsed), last_flush=stats,
                       transactions=session.counter.writes+session.counter.reads,
                       telemetry=session.telemetry())
            scenes(session, repetitions)
            report('gap_config_complete', chunk=chunk, max_gap=gap,
                   telemetry=session.telemetry())
        # Final full-plane/map/upper check with PCM still running.
        session.verify(full=True)
        report('gap_complete', telemetry=session.telemetry())
    finally:
        # Remove instance override rather than retain a captured bound method.
        if overridden:
            del f.flush

from framebuffer_diagnostic import Session
_session=None
gc.collect()
try:
 _session=Session(sdk='kagurafbx',accelerated=True,viper=True)
 assert isinstance(_session.fb,GapFramebuffer)
 run(_session,30)
finally:
 if _session is not None:_session.close()
 print('GAP_SESSION_CLOSED')
