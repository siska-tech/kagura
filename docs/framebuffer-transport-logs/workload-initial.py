import sys, gc, hashlib, binascii
sys.path.insert(0, '/fbx')
for path, expected in {'/lib/kagurafbx/__init__.py': 'e6893051d4a23de6726c58cbc238865e88df4ad5b1da8e1b882e06357f10f9be', '/lib/kagurafbx/regs.py': '8d587b4f00c8ef182bec2d790c127ad78300e6a02bc63906564fe39a6169fc59', '/lib/kagurafbx/device.py': '787b3d3c180cf9d0ab7803d8ba376c1c71230381c288ff942f8921ddde80fddd', '/lib/kagurafbx/video.py': '4c7315b431ed12945b5e2acc69a2b42485982e53e24721d384fb9c8d99f0fc78', '/lib/kagurafbx/audio.py': '553227ebef8ea9b56deb35c6520706e5ba3e6adb380e9c520398be3e6b105de9', '/lib/kagurafbx/transport_rp2.py': '3f88087006b489a0c483c99e2df0fd2aef5fd8f52d88883983eef9990deee32e', '/lib/kagurafbx/dma_pack.py': '88873707c3c502cce3956a04e7409ec4f446e5ae0f18964569c6d48571b77f74', '/lib/kagurafbx/fifo_xfer.py': 'e0aa4bb55a0bc7f4f6a3a7bcf1633032bdafd3dbadabefdae09620e381b93d97', '/lib/kagurafbx/acceleration.py': '7bb1bdde65aba80e53f4154c3ec2a6adeeddde426454aab7ee0e32d118d330e2', '/lib/kagurafbx/framebuffer.py': '5fd68d616f25efbcf6f59676eb52839a9487d49acc88a8995cb5bb844c346de1', '/lib/kagurafbx/framebuffer_viper.py': 'ba1f378e9360cfc2b0ba3774213df53108cef26bf2286c5dd030d86c5b40d93d', '/fbx/framebuffer_diagnostic.py': 'c1d3a2349f90ac79b8af0ac6b6f89eb65198efde9886e5472e98446baf2dba28', '/fbx/framebuffer_benchmark.py': 'd6028ddb9b32bb4e7a6a769d464cfc33fa53448fede12e38a7ee4f1d2905a957', '/fbx/framebuffer_viper_cases.py': '192bf0d3143cf34f54a776e5c5cfef4756f0dd9625dcb83e5338b936114b23f7', '/fbx/framebuffer_viper_validation.py': '6a3ccd2eb30f4d0894eed7ca051959c815d46333cffc3f786e7c903805eef8d1', '/fbx/framebuffer_shapes.py': '38304f6ad85f382c91a2f0548e853fa3f5774f25d9786590fdb1a6d150976191'}.items():
    h=hashlib.sha256()
    with open(path,'rb') as file:
        while True:
            block=file.read(512)
            if not block:break
            h.update(block)
    assert binascii.hexlify(h.digest()).decode()==expected, path
print('TRANSPORT_SDK_HASHES_PASS',16)
del h, block
gc.collect()

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
    if layout == 'boundary':
        start=max(0,min(1023 if count==1 else 1024-count//2,1200-count))
        return list(range(start,start+count))
    if layout == 'contiguous':
        return list(range(count))
    if layout == 'dispersed':
        # Coprime permutation, exactly count unique tiles, including >600.
        return sorted((n*599)%1200 for n in range(count))
    width = 4 if layout == 'narrow_rect' else 40
    return [n//width*40+n%width for n in range(count)] if count <= width*30 else None


def micro(session, repetitions=30):
    f = session.fb
    for count in (0,1,2,10,32,100,256,512,1023,1024,1200):
        for layout in ('contiguous','dispersed','narrow_rect','wide_rect','boundary'):
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


def scenes(session, repetitions=30):
    f=session.fb
    badge,gem=icons(session.FBM)
    for name in ('A','B','C','D'):
        source=(bytes(range(256))*150,320,240,session.FBM.TILE4) if name=='D' else None
        f.fill(0);f.flush()
        metrics={k:array('I') for k in ('draw','flush','loop','gc','tiles','bytes','transactions')}
        free_min=gc.mem_free()
        for n in range(repetitions+3):
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
                elif n%3==1:f.blit(source,0,0)
                else:f.fill_rect(0,0,320,240,1+n%15)
            draw=time.ticks_diff(time.ticks_us(),begin)
            session.counter.reset()
            start=time.ticks_us();stats=f.flush();flush=time.ticks_diff(time.ticks_us(),start)
            transactions=session.counter.writes+session.counter.reads
            start=time.ticks_us();gc.collect();g=time.ticks_diff(time.ticks_us(),start)
            elapsed=time.ticks_diff(time.ticks_us(),begin)
            free_min=min(free_min,gc.mem_free())
            # Telemetry outside the application interval; no logging inside it.
            telemetry=session.telemetry()
            if n>=3:
                for key,value in (('draw',draw),('flush',flush),('loop',elapsed),('gc',g),
                                  ('tiles',stats['tiles']),('bytes',stats['bytes']),
                                  ('transactions',transactions)):
                    metrics[key].append(value)
        report('transport_scene',scene=name,pcm=session.pcm,warmup=3,
               timing={k:detail(v) for k,v in metrics.items() if k not in ('tiles','bytes','transactions')},
               tiles=list(metrics['tiles']),bytes=list(metrics['bytes']),
               transactions=list(metrics['transactions']),
               application_updates_s=1e6*repetitions/sum(metrics['loop']),
               physically_presented_updates_hz=None,heap_after_gc_min=free_min,telemetry=telemetry)
        session.verify(full=False)
        source=None;gc.collect()


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
        for obj,name,label in ((r,'_begin','transaction_begin'),(r,'_end','transaction_end'),
                (r,'_xfer','fifo_pump'),(r,'_xfer_dma','dma_pack_config_wait'),
                (d,'_address','vram_address'),(d,'check_errors','error_check'),(d,'fence','fence')):
            self.wrap(obj,name,label)
        if s.accel.pump is not None:
            self.wrap(s.accel.pump,'_packet','native_packet')
        try:
            for count,layout in ((0,'contiguous'),(1,'contiguous'),(100,'contiguous'),
                                 (100,'dispersed'),(1024,'contiguous'),(1200,'contiguous')):
                for k in self.values:self.values[k][0]=self.values[k][1]=0
                for k in range(4):dma[k]=0
                for tile in indices(count,layout):s.fb.pixel(tile%40*8,tile//40*8,7)
                dirty=s.fb.dirty
                probe=DirtyProbe(dirty)
                gc.collect()
                try:
                    s.fb.dirty=probe
                    stats=s.fb.flush()
                finally:s.fb.dirty=dirty
                report('transport_profile',tiles=count,layout=layout,inclusive_us_calls=self.values,
                       dirty_scan_us=probe.scan_us,dirty_confirm_us=probe.confirm_us,
                       dma_pack_config_wait_us_chunks=dma,
                       flush=stats,instrumented=True)
        finally:self.close()


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


def run(session, repetitions=30):
    if not 10<=repetitions<=100:raise ValueError('repetitions 10..100')
    assert session.fb.viper_enabled and session.d.abi==(0,6)
    machine=__import__('machine')
    sm=session.raw._sm_id
    clkdiv=machine.mem32[0x50200000+(sm//4)*0x100000+0xc8+(sm%4)*0x18]
    report('transport_begin',repetitions=repetitions,clock_hz=machine.freq(),pio_clkdiv_register=clkdiv,
           baudrate=session.raw.baudrate,accelerated=session.accel.enabled,
           dma_chunk=128,pcm_policy='looping PSRAM 2ch, all measured cases')
    session.pcm_start()
    micro(session,repetitions)
    scenes(session,repetitions)
    Profile(session).run()
    chunks(session,repetitions)
    session.verify(full=True)
    report('transport_complete',telemetry=session.telemetry())

from framebuffer_diagnostic import Session
_session=None
try:
    _session=Session(sdk='kagurafbx',accelerated=True,viper=True)
    run(_session,30)
finally:
    if _session is not None:_session.close()
    print('TRANSPORT_SESSION_CLOSED')
