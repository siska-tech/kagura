import bench_transfer,time
import kagura_acceleration
from kagura.transport_rp2 import TransferTimeout
raw=kagura_console.screen.device.transport
kagura_console.pause()
try:
    for chunk in (128,512):
        with kagura_acceleration.Acceleration(raw,TransferTimeout,chunk=chunk):
            result=bench_transfer.profile_dma(kagura_console.screen.device,chunk=chunk)
            for name in sorted(result):
                row=result[name]
                if isinstance(row,dict):
                    print('PROFILE',chunk,name,row['mean_us'],row['median_us'],row['p95_us'],row['max_us'])
                    time.sleep_ms(10)
finally:
    kagura_console.resume()
