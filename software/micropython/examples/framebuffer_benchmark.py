# SPDX-License-Identifier: Apache-2.0
"""Reproducible Pico metrics, leaving scene A visible after run()."""
import gc
import time
from array import array
from framebuffer_diagnostic import report


def summary(values):
    ordered=sorted(values)
    return dict(count=len(ordered),mean_us=sum(ordered)/len(ordered),
                p95_us=ordered[max(0,(len(ordered)*95+99)//100-1)],max_us=ordered[-1])


class Samples:
    # Bounded ring: exact lifetime mean/max, exact p95 of last <=256 samples.
    def __init__(self):
        self.values=array('I',[0]*256)
        self.count=self.total=self.maximum=0
    def append(self,value):
        self.values[self.count%256]=value
        self.count+=1;self.total+=value;self.maximum=max(self.maximum,value)
    def stats(self):
        n=min(self.count,256)
        recent=sorted(self.values[:n])
        return dict(count=self.count,mean_us=self.total/self.count,max_us=self.maximum,
                    p95_recent_us=recent[(n*95+99)//100-1],recent_count=n)


def run(session,seconds=120):
    if not isinstance(seconds,int) or not 1<=seconds<=1800:raise ValueError('seconds 1..1800')
    f,d=session.fb,session.d
    for count in (1,10,100,1200):
        draw,transfer,wait,total=array('I'),array('I'),array('I'),array('I')
        results=None
        for repetition in range(5):
            gc.collect()
            start=time.ticks_us()
            f.fill_rect(0,0,320,240,0)
            f.flush()
            start=time.ticks_us()
            for tile in range(count):f.pixel(tile%40*8,tile//40*8,1+repetition)
            draw.append(time.ticks_diff(time.ticks_us(),start))
            session.counter.reset()
            results=f.flush()
            transfer.append(results['transfer_us']);wait.append(results['wait_us']);total.append(results['total_us'])
        report('transfer_benchmark',dirty_tiles=count,draw=summary(draw),transfer=summary(transfer),
               fence_host_wait=summary(wait),flush=summary(total),last_flush=results,
               register_write_calls=session.counter.writes,register_read_calls=session.counter.reads,
               register_tx_payload_bytes=session.counter.tx_bytes,register_rx_payload_bytes=session.counter.rx_bytes)
    for name,draw in (('line',lambda:f.line(0,0,319,239,7)),
                       ('fill_rect',lambda:f.fill_rect(16,16,288,208,5))):
        samples=array('I')
        for _ in range(10):
            f.fill(0);f.flush();gc.collect()
            start=time.ticks_us();draw();samples.append(time.ticks_diff(time.ticks_us(),start))
        f.flush();report('draw_benchmark',name=name,timing=summary(samples))
    session.pcm_start()
    f.fill(0);f.text('PARTIAL UPDATES + PCM',8,8,1);f.flush()
    elapsed_samples=Samples();gc_samples=Samples();draw_samples=Samples()
    tx_samples=Samples();wait_samples=Samples()
    start=last_report=last_sample=time.ticks_ms()
    last_frame=d.read_reg(session.R.REG_FRAME_COUNT_L)
    frames=loops=bytes_sent=writes=0
    previous=None
    gc.collect()
    min_free=max_free=gc.mem_free()
    try:
        while time.ticks_diff(time.ticks_ms(),start)<seconds*1000:
            begin=time.ticks_us()
            if previous is not None:
                x,y=previous;f.fill_rect(x,y,56,40,0)
            x=(loops*5)%264;y=40+(loops*3)%152
            f.fill_rect(x,y,56,40,4)
            f.rect(x,y,56,40,1);f.fill_rect(x+4,y+4,48,8,3)
            f.fill_rect(8,24,8,8,1 if loops%2 else 0)
            previous=x,y
            draw_samples.append(time.ticks_diff(time.ticks_us(),begin))
            stats=f.flush();tx_samples.append(stats['transfer_us']);wait_samples.append(stats['wait_us'])
            bytes_sent+=stats['bytes'];writes+=stats['writes']
            telemetry=session.telemetry();now=time.ticks_ms()
            if time.ticks_diff(now,last_sample)>=3000:raise AssertionError('frame sample gap >=3s')
            frames+=(telemetry['frame']-last_frame)&255;last_frame=telemetry['frame'];last_sample=now
            if loops%32==0:
                before=time.ticks_us();gc.collect();gc_samples.append(time.ticks_diff(time.ticks_us(),before));min_free=min(min_free,gc.mem_free());max_free=max(max_free,gc.mem_free())
            elapsed_samples.append(time.ticks_diff(time.ticks_us(),begin));loops+=1
            if time.ticks_diff(now,last_report)>=10000:
                report('continuous_progress',loops=loops,elapsed_ms=time.ticks_diff(now,start),heap_free=gc.mem_free(),**telemetry)
                last_report=now
        elapsed=time.ticks_diff(time.ticks_ms(),start)
        report('continuous_pass',elapsed_ms=elapsed,loops=loops,application_hz=loops*1000/elapsed,
               hdmi_counter_frames=frames,hdmi_counter_hz=frames*1000/elapsed,
               physically_presented_updates_hz=None,draw=draw_samples.stats(),transfer=tx_samples.stats(),
               fence_host_wait=wait_samples.stats(),iteration=elapsed_samples.stats(),gc=gc_samples.stats(),
               heap_after_gc_min=min_free,heap_after_gc_max=max_free,bytes_sent=bytes_sent,pattern_writes=writes,**session.telemetry())
    finally:
        # Keep PCM on for user observation; close() handles stop even after failure.
        gc.collect()
    session.scene('C');session.verify(full=False)
    session.scene('B');report('scene_B_generated')
    session.scene('A');report('scene_A_ready_for_user',visual_verified=False)
    session.verify(full=True)
    report('benchmark_pass',visual_verified=False)

# Paired CPU-only measurements. Drawing, transfer and fence timings stay separate.
def compare_draw(session,repetitions=10):
    import math
    def detail(values):
        result=summary(values)
        mean=result['mean_us']
        variance=sum((v-mean)*(v-mean) for v in values)/len(values)
        result['variance_us2']=variance
        result['stdev_us']=math.sqrt(variance)
        result['samples_us']=list(values)
        return result
    f=session.fb
    def pixels():
        for n in range(1024):f.pixel((n*17)%320,(n*13)%240,1+n%15)
    workloads=(('pixel_1024',pixels),('hline',lambda:f.hline(0,120,320,9)),
               ('vline',lambda:f.vline(160,0,240,7)),
               ('line',lambda:f.line(0,0,319,239,7)),
               ('fill_rect',lambda:f.fill_rect(16,16,288,208,5)),
               ('fill',lambda:f.fill(6)),('circle',lambda:f.circle(160,120,80,12)),
               ('text',lambda:f.text('KAGURA 1200 Viper',16,16,15)))
    for enabled in (False,True):
        f.set_viper(enabled)
        for name,draw in workloads:
            samples=array('I')
            for n in range(repetitions):
                f.fill(0);f.dirty[:]=bytes(1200);gc.collect()
                start=time.ticks_us();draw();samples.append(time.ticks_diff(time.ticks_us(),start))
            report('paired_draw',viper_enabled=enabled,name=name,timing=detail(samples),
                   kernel_counts=f.kernel_counts)
        f.flush()
        samples=array('I');scan=array('I')
        session.counter.reset()
        for n in range(repetitions):
            start=time.ticks_us();f.dirty.find(b'\x01');scan.append(time.ticks_diff(time.ticks_us(),start))
            start=time.ticks_us();stats=f.flush();samples.append(time.ticks_diff(time.ticks_us(),start))
            assert stats['bytes']==0
        assert session.counter.writes==0 and session.counter.reads==0
        report('paired_clean_flush',viper_enabled=enabled,timing=detail(samples),
               dirty_scan=detail(scan),register_write_calls=0,register_read_calls=0)


def compare_flush(session,repetitions=10):
    """Paired flushes with PCM active in both modes; identical prep and payload."""
    import math
    def detail(values):
        result=summary(values);mean=result['mean_us']
        variance=sum((v-mean)*(v-mean) for v in values)/len(values)
        result.update(variance_us2=variance,stdev_us=math.sqrt(variance),samples_us=list(values))
        return result
    if not session.pcm:raise RuntimeError('paired flush comparison requires PCM active')
    f=session.fb
    for count in (1,10,100,1200):
        for enabled in (False,True):
            transfer=array('I');wait=array('I');total=array('I')
            for repetition in range(repetitions):
                # Common untimed preparation, independent of measured renderer.
                f.set_viper(True);f.fill(0);f.flush()
                f.set_viper(enabled)
                for tile in range(count):f.pixel(tile%40*8,tile//40*8,1+repetition%15)
                gc.collect();session.counter.reset()
                stats=f.flush()
                transfer.append(stats['transfer_us']);wait.append(stats['wait_us']);total.append(stats['total_us'])
            report('paired_flush',viper_enabled=enabled,dirty_tiles=count,
                   transfer=detail(transfer),fence_host_wait=detail(wait),flush=detail(total),
                   last_flush=stats,register_write_calls=session.counter.writes,
                   register_read_calls=session.counter.reads,**session.telemetry())
    f.set_viper(True)


def _detail(values):
    import math
    result=summary(values);mean=result['mean_us']
    variance=sum((v-mean)*(v-mean) for v in values)/len(values)
    result.update(min_us=min(values),stdev_us=math.sqrt(variance),samples_us=list(values))
    return result


def _measure(session,enabled,prepare,draw,repetitions,flush):
    """prepare(n) runs untimed on Viper; GC, draw and optional flush timed apart."""
    f=session.fb
    draw_t=array('I');gc_t=array('I');tx=array('I');wait=array('I');heap=[]
    for n in range(repetitions):
        f.set_viper(True);prepare(n)
        if flush:f.flush()  # untimed: only this draw's tiles are sent below
        f.set_viper(enabled)
        start=time.ticks_us();gc.collect();gc_t.append(time.ticks_diff(time.ticks_us(),start))
        heap.append(gc.mem_free())
        start=time.ticks_us();draw();draw_t.append(time.ticks_diff(time.ticks_us(),start))
        if flush:
            stats=f.flush();tx.append(stats['transfer_us']);wait.append(stats['wait_us'])
    result=dict(viper_enabled=enabled,draw=_detail(draw_t),gc_before_draw=summary(gc_t),
                heap_after_gc_min=min(heap),heap_after_gc_max=max(heap))
    if flush:
        result.update(transfer=_detail(tx),fence_host_wait=_detail(wait),last_flush=stats)
    return result


def compare_primitives(session,repetitions=10):
    """blit/ellipse/paint for Python and Viper on identical untimed inputs."""
    import framebuffer_shapes as shapes
    if not isinstance(repetitions,int) or not 10<=repetitions<=100:raise ValueError('repetitions 10..100')
    f,M=session.fb,session.FBM
    gc.collect();heap_before=gc.mem_free()
    # One transient 9600 B source (up to 160x120), viewed as TILE4 or GS4_HMSB.
    # 320x240 uses the plane itself (scroll copy): no second plane is allocated.
    big=bytearray(9600)
    for n in range(9600):big[n]=(n*73+(n>>7)*29)&255
    view=memoryview(big)
    gc.collect()
    report('bench_source',bytes=len(big),heap_before=heap_before,heap_after=gc.mem_free())
    def reset(n):f.fill(5)
    def stripes(n):
        f.fill(5)
        for x in range(0,320,16):f.fill_rect(x,0,8,240,9)
        for y in range(0,240,16):f.fill_rect(0,y,320,4,2)
    for w,h in ((8,8),(16,16),(32,32),(64,64),(160,120),(320,240)):
        for fmt in (('TILE4','GS4_HMSB') if w<320 else ('framebuffer',)):
            source=f if w==320 else (view[:w*h//2],w,h,getattr(M,fmt))
            for aligned in (True,False):
                x,y=(0,0) if w==320 else ((80,64) if w==160 else (64,48))
                sx,sy=(8,8) if w==320 else (0,0)
                if not aligned:x+=3;y+=1;sx=sy=0
                for key in (None,0):
                    if w==320 and key is not None:key=5
                    flush=key is None and aligned and fmt in ('TILE4','framebuffer') and w in (16,64,320)
                    for enabled in (False,True):
                        result=_measure(session,enabled,stripes if w==320 else reset,
                                        lambda:f.blit(source,x,y,None,None,key,sx,sy),repetitions,flush)
                        report('primitive',name='blit',width=w,height=h,format=fmt,
                               tile_aligned=aligned,x=x,y=y,sx=sx,sy=sy,key=key,**result)
    def clear(n):f.fill(0)
    for name,args in (('ellipse_outline',(160,120,150,110,7,False)),('ellipse_fill',(160,120,150,110,7,True)),
                      ('ellipse_small',(160,120,24,16,7,False)),('ellipse_small_fill',(160,120,24,16,7,True))):
        for enabled in (False,True):
            result=_measure(session,enabled,clear,lambda:f.ellipse(*args),repetitions,name in ('ellipse_outline','ellipse_fill'))
            report('primitive',name=name,args=args,**result)
    view=None;big=None;gc.collect()
    for shape in ('box8','box32','box160','full','corridor','maze','comb','noise'):
        seeds=[]
        def restore(n):
            seeds.append(shapes.prepare(f,shape))  # deterministic; untimed on Viper
        for enabled in (False,True):
            result=_measure(session,enabled,restore,lambda:f.paint(seeds[-1][0],seeds[-1][1],12),
                            repetitions,shape in ('box32','full'))
            report('primitive',name='paint',shape=shape,seed=seeds[-1],complete=f.last_paint['complete'],
                   paint=dict(f.last_paint),stack_bytes=4*f.paint_capacity,**result)
            del seeds[:]
    f.set_viper(True);f.flush();gc.collect()
    report('primitives_done',heap_after=gc.mem_free())


def run_primitives(session,seconds=300):
    """Continuous blit+ellipse+paint with PCM 2ch, dirty flushes and telemetry."""
    if not isinstance(seconds,int) or not 1<=seconds<=1800:raise ValueError('seconds 1..1800')
    f,d,M=session.fb,session.d,session.FBM
    if not session.pcm:session.pcm_start()
    f.fill(0)
    # Sprite lane (0..159 x 0..119) with stripes kept in a 9600 B GS4 copy.
    for x in range(0,160,8):f.fill_rect(x,0,4,120,8)
    lane=bytearray(9600)
    for y in range(120):
        for x in range(0,160,2):
            lane[y*80+x//2]=f.pixel(x,y)<<4|f.pixel(x+1,y)
    background=(lane,160,120,M.GS4_HMSB)
    sprite=bytearray(512)
    for y in range(32):
        for x in range(32):
            d2=(2*x-31)*(2*x-31)+(2*y-31)*(2*y-31)
            c=0 if d2>900 else (1 if d2>700 else (3 if x<y else 11))
            sprite[y*16+x//2]|=c<<(0 if x&1 else 4)
    sprite=(bytes(sprite),32,32,M.GS4_HMSB)
    # Paint panel: walled box with internal baffles; flood-filled every loop.
    f.rect(0,120,320,120,1)
    for x in range(20,300,20):f.vline(x,121+(x//20&1)*20,98,1)
    for y in range(140,230,30):f.hline(10,y,140,1)
    f.flush()
    draw_samples=Samples();tx_samples=Samples();wait_samples=Samples()
    iteration=Samples();gc_samples=Samples();paint_samples=Samples()
    start=last_report=time.ticks_ms()
    last_frame=d.read_reg(session.R.REG_FRAME_COUNT_L)
    frames=loops=bytes_sent=0;previous=None;peak=0
    gc.collect();min_free=max_free=gc.mem_free()
    while time.ticks_diff(time.ticks_ms(),start)<seconds*1000:
        begin=time.ticks_us()
        if previous is not None:
            px,py,prx,pry=previous
            f.blit(background,px,py,32,32,None,px,py)       # erase from the copy
            f.ellipse(240,60,prx,pry,0,True)
        t=loops%200
        x=3*t if t<100 else 3*(200-t);x=x*128//300
        y=(loops*5)%176;y=y if y<88 else 176-y
        f.blit(sprite,x,y,None,None,0)                      # moving transparent sprite
        rx,ry=20+(loops*3)%55,10+(loops*2)%45
        f.ellipse(240,60,rx,ry,9);f.ellipse(240,60,rx//2,ry//2,13,True)
        previous=x,y,rx,ry
        before=time.ticks_us()
        assert f.paint(5,125,2+(loops&1)*12)               # real flood fill each loop
        paint_samples.append(time.ticks_diff(time.ticks_us(),before))
        peak=max(peak,f.last_paint['peak'])
        draw_samples.append(time.ticks_diff(time.ticks_us(),begin))
        stats=f.flush();tx_samples.append(stats['transfer_us']);wait_samples.append(stats['wait_us'])
        bytes_sent+=stats['bytes']
        telemetry=session.telemetry();now=time.ticks_ms()
        frames+=(telemetry['frame']-last_frame)&255;last_frame=telemetry['frame']
        if loops%32==0:
            g=time.ticks_us();gc.collect();gc_samples.append(time.ticks_diff(time.ticks_us(),g))
            min_free=min(min_free,gc.mem_free());max_free=max(max_free,gc.mem_free())
        iteration.append(time.ticks_diff(time.ticks_us(),begin));loops+=1
        if time.ticks_diff(now,last_report)>=10000:
            report('primitives_progress',loops=loops,elapsed_ms=time.ticks_diff(now,start),heap_free=gc.mem_free(),**telemetry)
            last_report=now
    elapsed=time.ticks_diff(time.ticks_ms(),start)
    report('primitives_continuous_pass',viper_enabled=f.viper_enabled,elapsed_ms=elapsed,loops=loops,
           application_updates_hz=loops*1000/elapsed,hdmi_counter_hz=frames*1000/elapsed,
           physically_presented_updates_hz=None,draw=draw_samples.stats(),paint=paint_samples.stats(),
           paint_stack_peak=peak,transfer=tx_samples.stats(),fence_host_wait=wait_samples.stats(),
           iteration=iteration.stats(),gc=gc_samples.stats(),heap_after_gc_min=min_free,
           heap_after_gc_max=max_free,bytes_sent=bytes_sent,kernel_counts=f.kernel_counts,**session.telemetry())
    session.verify(full=True)
