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
