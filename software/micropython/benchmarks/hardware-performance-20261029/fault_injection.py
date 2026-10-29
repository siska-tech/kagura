import time
import kagura_acceleration
from kagura.transport_rp2 import TransferTimeout
from kagura import regs as R
dev=kagura_console.screen.device
raw=dev.transport
old_timeout=raw.timeout_us
kagura_console.pause()
try:
    raw.timeout_us=10000
    with kagura_acceleration.Acceleration(raw,TransferTimeout,chunk=512):
        for case in ('PIO_STOP','DMA_STOP'):
            base=raw._xfer_dma
            def stalled_dma(data,queued):
                raw._sm.active(0)
                return base(data,queued)
            t=time.ticks_us()
            caught=False
            try:
                if case=='PIO_STOP':
                    raw._sm.active(0)
                    raw.write(R.REG_INC_L,b'\x01\x00',True)
                else:
                    raw._xfer_dma=stalled_dma
                    dev.write_memory(0x7000,bytearray(512))
            except TransferTimeout as error:
                caught=True
                print('FAULT_TIMEOUT',case,error.completed,time.ticks_diff(time.ticks_us(),t))
                time.sleep_ms(10)
            finally:
                raw._xfer_dma=base
            print('FAULT_RECOVERY',case,caught,not raw._active,raw._cs.value(),not raw._dma_tx.active(),not raw._dma_rx.active(),dev.read_reg(R.REG_ID0),dev.read_reg(R.REG_ERROR_CODE))
            time.sleep_ms(10)
finally:
    raw.timeout_us=old_timeout
    kagura_console.resume()
print('FAULT_REPL',not kagura_console.paused)
