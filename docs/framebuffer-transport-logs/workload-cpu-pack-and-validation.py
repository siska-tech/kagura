import gc,time,json
from array import array

def _pack_summary(values):
 v=sorted(values);n=len(v)
 return dict(count=n,mean_us=sum(v)/n,median_us=(v[(n-1)//2]+v[n//2])/2,p95_us=v[(95*n+99)//100-1],max_us=v[-1],samples_us=list(values))

if '_session' in globals() and _session is not None:
 assert _session.raw._closed
 _pack_mod=__import__('kagurafbx.dma_pack',None,None,['pack32'])
 _pack_data=_session.fb._view
 _pack_high=_session.raw._high[1]
 _pack_words=_session.raw._words
 _pack_functions=(('wrapper',_pack_mod.pack32),('native',_pack_mod.viper_pack32),('empty_loop',None))
 for _pack_mode,_pack_fn in _pack_functions:
  _pack_values=array('I')
  for _pack_rep in range(30):
   gc.collect()
   _pack_start=time.ticks_us()
   if _pack_fn is None:
    for _pack_offset in range(0,38400,128):pass
   else:
    for _pack_offset in range(0,38400,128):_pack_fn(_pack_data,_pack_high,_pack_words,_pack_offset,128)
   _pack_values.append(time.ticks_diff(time.ticks_us(),_pack_start))
  print('TILEFB '+json.dumps(dict(event='transport_cpu_pack_batch',mode=_pack_mode,bytes=38400,chunks=300,chunk=128,includes_python_loop=True,dma_closed=True,timing=_pack_summary(_pack_values))))
 del _pack_data,_pack_high,_pack_words,_pack_functions,_pack_fn,_pack_values
 gc.collect()

import sys,gc
if 'transport_bench_20261030' in sys.modules:sys.modules.pop('transport_bench_20261030')
globals().pop('transport_bench_20261030',None)
_session=None
gc.collect()
sys.path.insert(0,'/fbx')
from framebuffer_viper_validation import run as validate_transport_raster
validate_transport_raster(sdk='kagurafbx',count=512,expected={'operations':1090,'rolling_crc32':1028220238,'buffer_crc32':1578755449,'dirty_crc32':206457449})
print('TRANSPORT_DIFFERENTIAL_COMPLETE')
gc.collect()
