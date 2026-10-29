import machine,time
import kagura_acceleration
from kagura.transport_rp2 import TransferTimeout
from kagura import regs as R
dev=kagura_console.screen.device
raw=dev.transport
uart=kagura_console.uart
old_cr=machine.mem32[0x40034030]
timer=None
caught=False
entered=False
active_seen=False
caught_in_dma=False
kagura_console.pause()
def send_interrupt(t):
    global active_seen
    if raw._dma_rx.active() or raw._dma_tx.active():
        active_seen=True
        uart.write(bytes((3,)))
        t.deinit()
try:
    machine.mem32[0x40034030]=old_cr|0x80
    with kagura_acceleration.Acceleration(raw,TransferTimeout,chunk=512):
        base=raw._xfer_dma
        def interrupted_dma(data,queued):
            global timer,entered,caught_in_dma
            entered=True
            timer=machine.Timer(period=1,mode=machine.Timer.PERIODIC,callback=send_interrupt,hard=False)
            try:
                return base(data,queued)
            except KeyboardInterrupt:
                caught_in_dma=True
                raise
        raw._xfer_dma=interrupted_dma
        try:
            dev.write_memory(0,bytearray(8192))
        except KeyboardInterrupt:
            caught=True
        finally:
            if timer is not None:timer.deinit()
        print('DMA_INTERRUPTED',entered,caught,active_seen,caught_in_dma)
        time.sleep_ms(10)
        print('DMA_CLEAN',not raw._active,raw._cs.value(),not raw._dma_tx.active(),not raw._dma_rx.active())
        time.sleep_ms(10)
        print('DMA_REUSE_ID_ERROR',dev.read_reg(R.REG_ID0),dev.read_reg(R.REG_ERROR_CODE))
finally:
    if timer is not None:timer.deinit()
    machine.mem32[0x40034030]=old_cr
    kagura_console.resume()
print('DMA_REPL_RESTORED',not kagura_console.paused)

