import gc,json,time
from kagura import connect
from kagura.terminal import TileScreen
import bench_transfer
font=kagura_console.screen.font
mode='qspi' if kagura_console.screen.device.transport.lanes==4 else 'spi'
try:
    for baud in (1000000,2500000,5000000):
        kagura_console.pause()
        kagura_console.screen.device.deinit()
        dev=connect(mode=mode,baudrate=baud)
        kagura_console.screen=TileScreen(dev,font=font)
        print('MATRIX_BEGIN',mode,baud,dev.height,dev.caps)
        results=bench_transfer.run(dev,repeats=16)
        for row in results:
            print('TRANSFER',row['method'],row['length'],row['lanes'],row['baudrate'],row['mean_us'],row['median_us'],row['p95_us'],row['max_us'],row['fpga_error'])
            time.sleep_ms(10)
        del results
        gc.collect()
        print('MATRIX_END',mode,baud)
finally:
    kagura_console.resume()

