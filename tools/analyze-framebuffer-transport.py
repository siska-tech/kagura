# SPDX-License-Identifier: Apache-2.0
"""Archive on-device TILEFB records and derive payload rates and affine fits.

No CPython elapsed times are treated as Pico performance measurements.
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def fit(points):
    n=len(points)
    if n<2:return None
    x=sum(p[0] for p in points)/n;y=sum(p[1] for p in points)/n
    xx=sum((a-x)**2 for a,b in points)
    if not xx:return None
    slope=sum((a-x)*(b-y) for a,b in points)/xx
    intercept=y-slope*x
    return dict(model='host_us = intercept_us + slope_us_per_payload_byte * bytes',
                count=n,intercept_us=intercept,slope_us_per_payload_byte=slope,
                residual_us=[b-intercept-slope*a for a,b in points],
                scope='contiguous 1..1024 tiles; excludes clean and address-bank split')


def spans(tiles, gap=0):
    result=[]
    for tile in tiles:
        if not result or tile-result[-1][1]>gap:result.append([tile,tile+1])
        else:result[-1][1]=tile+1
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log',type=Path)
    p.add_argument('--extra-log',type=Path,action='append',default=[])
    p.add_argument('--flash-saved',action='store_true')
    p.add_argument('--flash-verification',choices=('not_checked','passed','failed'),default='not_checked')
    p.add_argument('--firmware-rewritten',action='store_true')
    p.add_argument('--firmware-sha256')
    p.add_argument('--workload',type=Path,action='append',default=[])
    p.add_argument('--output',type=Path,default=ROOT/'docs/framebuffer-transport-results.json')
    a=p.parse_args()
    records=[]
    logs=([a.log] if a.log else [])+a.extra_log
    for logfile in logs:
        raw=logfile.read_bytes()
        decoded=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
        for line in decoded.splitlines():
            for prefix in ('TILEFB ','VIPERFB '):
                start=line.find(prefix)
                if start>=0:
                    record=json.loads(line[start+len(prefix):])
                    record['acquisition_log']=str(logfile)
                    records.append(record)
                    break
    historical=json.loads((ROOT/'docs/framebuffer-primitives-results.json').read_text(encoding='utf-8-sig'))
    def walk(value):
        if isinstance(value,dict):
            if value.get('event')=='paired_flush' and value.get('viper_enabled'):
                yield value
            for child in value.values():yield from walk(child)
        elif isinstance(value,list):
            for child in value:yield from walk(child)
    previous=list(walk(historical))
    for r in previous:
        for name in ('flush','transfer','fence_host_wait'):
            v=sorted(r[name]['samples_us']);n=len(v)
            r[name]['median_us']=(v[(n-1)//2]+v[n//2])/2
        r['payload_Bps_over_transfer']=r['last_flush']['bytes']*1e6/r['transfer']['mean_us']
        r['payload_Bps_over_flush']=r['last_flush']['bytes']*1e6/r['flush']['mean_us']
    micro=[r for r in records if r.get('event')=='transport_micro']
    rates=[]
    for r in micro:
        n=r['last_flush']['bytes']
        rates.append(dict(tiles=r['tiles'],layout=r['layout'],
                          payload_Bps_over_flush=n*1e6/r['timing']['flush']['mean_us'],
                          payload_Bps_over_transfer=(n*1e6/r['timing']['transfer']['mean_us']
                            if r['timing']['transfer']['mean_us'] else None)))
    points=[(r['last_flush']['bytes'],r['timing']['flush']['mean_us']) for r in micro
            if r['layout']=='contiguous' and 0<r['tiles']<=1024]
    flush_fit=fit(points)
    scene_records={r['scene']:r for r in records if r.get('event')=='transport_scene'}
    scene_summary={name:dict(revision=r.get('scene_definition_revision',1),
        memory_sample_interval=r.get('memory_sample_interval',1),
        draw_mean_us=r['timing']['draw']['mean_us'],flush_mean_us=r['timing']['flush']['mean_us'],
        loop_mean_us=r['timing']['loop']['mean_us'],application_updates_s=r['application_updates_s'],
        dirty_tiles_min=min(r['tiles']),dirty_tiles_max=max(r['tiles']),
        bytes_mean=sum(r['bytes'])/len(r['bytes']),transactions_mean=sum(r['transactions'])/len(r['transactions']),
        gc=r['timing']['gc'],telemetry=r['telemetry'],full_blit_mode=r.get('full_blit_mode'))
        for name,r in sorted(scene_records.items())}
    estimates={}
    chunk_rows=[r for r in records if r.get('event')=='transport_chunk' and r['tiles']==1200]
    if len(chunk_rows)==3:
        pts=[((32768+r['chunk']-1)//r['chunk']+(5632+r['chunk']-1)//r['chunk'],r['timing']['mean_us']) for r in chunk_rows]
        model=fit(pts)
        times={r['chunk']:r['timing']['mean_us'] for r in chunk_rows}
        estimates['dma_chunk_model']=dict(classification='fit of measured existing options, not a wire-time model',
            points_chunks_host_us=pts,aggregate_us_per_chunk=model['slope_us_per_payload_byte'],
            fixed_plus_byte_dependent_us=model['intercept_us'],residual_us=model['residual_us'],
            reduction_128_to_512_percent=(times[128]-times[512])/times[128]*100,
            note='The intercept still includes packing, wire time, protocol, FENCE and checks; no extrapolation beyond tested chunks')
    dispersed=next((r for r in micro if r['tiles']==100 and r['layout']=='dispersed'),None)
    clean=next((r for r in micro if r['tiles']==0 and r['layout']=='contiguous'),None)
    if dispersed and clean and flush_fit:
        indices=sorted((n*599)%1200 for n in range(100))
        merged=spans(indices,1);sent=sum(b-a for a,b in merged)
        beta=flush_fit['slope_us_per_payload_byte'];global_us=clean['timing']['flush']['mean_us']
        per_run=(dispersed['timing']['flush']['mean_us']-global_us-beta*3200)/100
        estimates['one_tile_gap_100']=dict(classification='unimplemented design estimate; not measured improvement',
            original_runs=100,merged_runs=len(merged),original_tiles=100,sent_tiles=sent,
            payload_bytes=sent*32,spans=merged,assumed_fixed_us_per_run=per_run,
            estimated_flush_us_excluding_merge_cpu=global_us+per_run*len(merged)+beta*sent*32,
            merge_cpu_us=None,scope='Same 100-tile permutation and original acquisition phase only')
    dense_d=next((r for r in reversed(records) if r.get('event')=='transport_scene' and
                  r.get('scene')=='D' and r.get('full_blit_mode')=='inplace_scroll_wrap'),None)
    if dense_d and flush_fit:
        d=dense_d;raw=d['timing']['flush']['samples_us']
        if d.get('full_blit_mode')=='inplace_scroll_wrap':
            full=[v for i,v in enumerate(raw) if i%3!=2];rect=raw[2::3]
            merged=spans([i for i in range(1200) if i%40%15!=0],1)
            estimates['dense_scene_d_rectangle']=dict(classification='unimplemented design estimate; not measured improvement',
                original_dirty_tiles=1110,original_runs=90,original_transactions=994,
                merged_runs=len(merged),sent_tiles=sum(b-a for a,b in merged),
                measured_rectangle_flush_mean_us=sum(rect)/len(rect),
                measured_full_flush_mean_us=sum(full)/len(full),
                estimated_merged_flush_us_excluding_merge_cpu=sum(full)/len(full)-32*flush_fit['slope_us_per_payload_byte'],
                merge_cpu_us=None,note='Mask reconstructed from the documented deterministic stripe/rectangle scene; CPU cost of merging unmeasured')
    coverage=dict(micro_tile_counts=sorted({r['tiles'] for r in micro}),
                  scenes=sorted({r['scene'] for r in records if r.get('event')=='transport_scene' and r.get('loop_includes_telemetry')}),
                  full_vram_readback=any(r.get('event')=='readback_pass' and r.get('full') for r in records),
                  raster_differential=any(r.get('event')=='differential_pass' and r.get('passed') for r in records),
                  console_restored=any(r.get('event')=='transport_console_restored' and r.get('console_active') for r in records),
                  completion_marker=any(r.get('event')=='transport_complete' for r in records))
    complete=(coverage['completion_marker'] and coverage['full_vram_readback'] and
              coverage['micro_tile_counts']==[0,1,2,10,32,100,256,512,1023,1024,1200] and
              coverage['scenes']==['A','B','C','D'] and coverage['raster_differential'] and coverage['console_restored'])
    begin=next((r for r in records if r.get('event')=='transport_begin'),None)
    derived_clock=None
    if begin:
        divider=begin['pio_clkdiv_register']/65536
        pio=begin['clock_hz']/divider
        derived_clock=dict(classification='derived from reported CPU clock and SM_CLKDIV; not logic analyzer',
                           divider=divider,pio_hz=pio,intra_byte_sck_hz=pio/12,
                           queued_payload_limit_Bps=pio/30)
    for r in micro:
        if r['tiles']!=r['last_flush']['tiles']:
            raise ValueError('stimulus tile count mismatch: '+str((r['tiles'],r['layout'])))
    result=dict(schema_version=1,generated_utc=datetime.now(timezone.utc).isoformat(),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        current_run=dict(status='complete' if complete else ('partial' if records else 'awaiting_device_recovery'),
                         log=str(a.log) if a.log else None,
                         log_sha256=hashlib.sha256(a.log.read_bytes()).hexdigest() if a.log else None,
                         logs=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in logs],
                         measurements=records,payload_rates=rates,contiguous_flush_fit=flush_fit,
                         scene_summary=scene_summary,design_estimates=estimates,
                         workloads=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in a.workload],
                         sdk_verified_manifest=historical['deployed'],
                         native_helpers=[dict(path=r['path'],bytes=r['bytes'],sha256=r['sha256'],acquisition_log=r['acquisition_log'])
                             for r in records if r.get('event')=='transport_native_helper'],
                         environment=dict(host='RP2040 Raspberry Pi Pico',fpga='Tang Nano 9K',
                             micropython='v1.26.0-1.g3069c562f KAGURA_PICO',abi=[0,6],
                             framebuffer=[320,240,4,1200],qspi_baudrate=5000000,
                             renderer='Viper',transport='Viper FIFO and pack32; baseline DMA chunk128',
                             firmware_recovery_artifact_sha256=a.firmware_sha256,
                             note='0..1024 acquired before recovery; initial binary hash not recorded. Other measurements acquired after recovery. Logs distinguish phases.'),
                         register_derived_clock=derived_clock,
                         coverage=coverage,
                         physically_presented_updates_hz=None,busy_pin_wait_us=None,
                         fpga_internal_execution_us=None),
        historical_baseline=dict(source='docs/framebuffer-primitives-results.json',
             source_sha256=hashlib.sha256((ROOT/'docs/framebuffer-primitives-results.json').read_bytes()).hexdigest(),
             date=historical['date'],hardware=historical['hardware'],
             acquisition='Prior on-device paired_flush, 10 repetitions, PCM 2ch; not acquired by this investigation',
             measurements=previous),
        theoretical=dict(classification='calculated, not measured',pio_hz=60000000,
             intra_byte_sck_hz=5000000,queued_byte_cycles=30,unqueued_byte_cycles=29,
             queued_continuous_payload_Bps=2000000,
             ideal_qspi_5MHz_payload_Bps=2500000,
             excludes='FIFO starvation, DMA chunk gaps, BUSY-high extension, CS gaps, host code'),
        unavailable=['logic analyzer capture','direct HDMI presentation cadence',
                     'FPGA internal timing independent of host polling',
                     *([] if any(r.get('event')=='transport_fullblit_complete' for r in records) else
                       ['independent 38400-byte full-screen blit source (RAM allocation failed)']),
                     'automatic GC pause attribution and true heap high-water mark'],
        safety=dict(rtl_abi_protocol_changed=False,firmware_written=a.firmware_rewritten,
                    canonical_lib_written=False,fpga_flash_written=a.flash_saved,
                    fpga_flash_programmer_verification=a.flash_verification if a.flash_saved else 'not attempted',
                    fpga_flash_operational_reload='ABI0.6 console confirmed' if a.flash_saved and coverage['console_restored'] else 'not confirmed',
                    pico_firmware_flash_readback_verified=False,
                    firmware_recovery_method='BOOTSEL UF2 copy; filesystem outside UF2 range; SDK16 hashes checked after recovery' if a.firmware_rewritten else None))
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(a.output)


if __name__=='__main__':main()
