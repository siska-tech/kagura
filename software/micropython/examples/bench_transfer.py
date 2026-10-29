# SPDX-License-Identifier: Apache-2.0
"""Transfer-only A/B/C/D benchmark; prints nothing during measurements.

Pause the console, connect at the desired lane count/clock, then call run(dev).
Repeat for SPI/QSPI at 1/2.5/5 MHz. This changes OAM; restore the console after.
Numbers are write_memory latency (including ERROR_CODE), not display FPS.
"""
import gc
from time import ticks_us, ticks_diff
try:
    from kagura import dma_pack
    from kagura.acceleration import Acceleration
except ImportError:
    import kagura_dma_pack as dma_pack
    from kagura_acceleration import Acceleration
from kagura.transport_rp2 import TransferTimeout


def distribution(values):
    ordered = sorted(values)
    n = len(values)
    return dict(mean_us=sum(values)/n,
                median_us=(ordered[(n-1)//2]+ordered[n//2])/2,
                p95_us=ordered[(n*95+99)//100-1], max_us=ordered[-1])


def run(device, repeats=16, lengths=(64,128,256,512,1024,2048)):
    if repeats < 4:
        raise ValueError('at least four repeats required')
    raw = device.transport
    results = []
    original = raw.__dict__.get('_xfer_dma')
    enabled = gc.isenabled()
    try:
        for method in ('A', 'B', 'C', 'D'):
            session = None
            try:
                if method in ('C','D'):
                    session = Acceleration(raw, TransferTimeout,
                                           fifo=method=='D', chunk=512 if method=='D' else 128)
                else:
                    packer = dma_pack.python_pack if method=='A' else dma_pack.pack
                    raw._xfer_dma = lambda data, queued: dma_pack.transfer(
                        raw, data, queued, TransferTimeout, packer=packer)
                for length in lengths:
                    # OAM writes mask reserved fields in FPGA kagura_vram.sv.
                    # Use valid records so readback compares actual ABI data.
                    masks = (255,3,255,127,255,63,0,0)
                    data = bytearray(((j*37+11)&255)&masks[j&7] for j in range(length))
                    values = [0]*repeats
                    device.fence()
                    gc.collect()
                    gc.disable()
                    for j in range(repeats):
                        stamp = ticks_us()
                        device.write_memory(0xA000, data)
                        values[j] = ticks_diff(ticks_us(), stamp)
                    if enabled:
                        gc.enable()
                    device.fence()
                    # Endpoint readback is correctness evidence, not timing.
                    for address, expected in ((0xA000, data[:8]),
                                              (0xA000+length-8, data[-8:])):
                        back = bytearray(8)
                        device.read_memory_into(address, back)
                        if back != expected:
                            raise OSError('transfer readback mismatch')
                    result = distribution(values)
                    result.update(method=method, length=length, repeats=repeats,
                                  lanes=raw.lanes, baudrate=raw.baudrate,
                                  fpga_error=device.read_reg(0x17))
                    results.append(result)
                    gc.collect()
                if method == 'D':
                    # Pattern RAM is unmasked; validate every possible byte too.
                    pattern = bytearray(range(256))
                    back = bytearray(256)
                    device.write_memory(0x7000,pattern)
                    device.fence()
                    device.read_memory_into(0x7000,back)
                    if back != pattern:
                        raise OSError('unmasked 256-byte readback mismatch')
            finally:
                if session:
                    session.close()
                elif original is None:
                    if '_xfer_dma' in raw.__dict__:
                        del raw._xfer_dma
                else:
                    raw._xfer_dma = original
        return results
    finally:
        if enabled:
            gc.enable()


def profile_dma(device, length=512, repeats=16, chunk=128):
    """Nested latency profile, separate from the uninstrumented A-D matrix.

    configure uses trigger=False, then starts RX before TX explicitly so setup
    and start can be separated. These additional API calls are instrumentation;
    do not compare their total with matrix latency as if they were identical.
    inc/address/payload/error/outer are exclusive. pack/config/start/wait/PIO
    partition payload. Each row's components sum exactly to total.
    """
    raw = device.transport
    names = ('inc','address','payload','error','pack','dma_config','dma_start',
             'dma_wait','payload_other','outer','total')
    columns = {name: [0]*repeats for name in names}
    current = [0]*8
    original_dma = raw.__dict__.get('_xfer_dma')
    original_write, original_read = raw.write, raw.readinto
    previous_write = raw.__dict__.get('write')
    previous_read = raw.__dict__.get('readinto')
    data = bytearray(length)

    def write(offset, data, inc=False):
        stamp = ticks_us()
        try:
            return original_write(offset, data, inc)
        finally:
            if offset in (0x10,4,7):
                current[(0x10,4,7).index(offset)] += ticks_diff(ticks_us(), stamp)

    def read(offset, data, inc=False):
        stamp = ticks_us()
        try:
            return original_read(offset, data, inc)
        finally:
            if offset == 0x17:
                current[3] += ticks_diff(ticks_us(), stamp)

    def dma(data, queued):
        done, n = 0, len(data)
        while done < n:
            m = min(chunk, n-done)
            stamp = ticks_us()
            dma_pack.pack32(data, raw._high[queued], raw._words, done, m)
            current[4] += ticks_diff(ticks_us(), stamp)
            stamp = ticks_us()
            raw._dma_rx.config(read=raw._sm, write=raw._sink, count=m,
                               ctrl=raw._rx_ctrl, trigger=False)
            raw._dma_tx.config(read=raw._words, write=raw._sm, count=m,
                               ctrl=raw._tx_ctrl, trigger=False)
            current[5] += ticks_diff(ticks_us(), stamp)
            stamp = ticks_us()
            raw._dma_rx.active(1)
            raw._dma_tx.active(1)
            current[6] += ticks_diff(ticks_us(), stamp)
            stamp = progress = ticks_us()
            left = m
            while raw._dma_rx.active():
                count = raw._dma_rx.count
                if count != left:
                    left, progress = count, ticks_us()
                elif ticks_diff(ticks_us(),progress) >= raw.timeout_us:
                    raise TransferTimeout(done+max(0,m-left-1))
            current[7] += ticks_diff(ticks_us(), stamp)
            done += m

    try:
        raw.write, raw.readinto, raw._xfer_dma = write, read, dma
        for j in range(repeats):
            device.fence()
            gc.collect()
            for k in range(8):
                current[k] = 0
            stamp = ticks_us()
            device.write_memory(0xA000,data)
            total = ticks_diff(ticks_us(),stamp)
            for k in range(8):
                columns[names[k]][j] = current[k]
            columns['payload_other'][j] = current[2]-sum(current[4:])
            columns['outer'][j] = total-sum(current[:4])
            columns['total'][j] = total
        result = {name: distribution(values) for name,values in columns.items()}
        result.update(length=length, repeats=repeats, chunk=chunk)
        return result
    finally:
        for name, previous in (('write',previous_write),('readinto',previous_read),('_xfer_dma',original_dma)):
            if previous is None:
                delattr(raw,name)
            else:
                setattr(raw,name,previous)
