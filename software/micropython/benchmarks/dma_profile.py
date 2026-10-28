# SPDX-License-Identifier: Apache-2.0
"""On-device attribution of existing write_memory/DMA; patches restored on exit."""
import gc
from array import array
from time import ticks_us, ticks_diff, sleep_ms
from kagura import regs as R
from kagura.transport_rp2 import PIOTransport, TransferTimeout, _DMA_CHUNK
import shooter


def run(console, iterations=64, packing='python'):
    d = console.screen.device
    raw = d.transport
    if not isinstance(raw, PIOTransport) or raw._dma_tx is None:
        raise RuntimeError('requires real RP2 DMA transport')
    # Packing, DMA config, DMA wait, INC, ADDR, payload transport, reads,
    # total write_memory, DMA chunks, DMA bytes, poll iterations.
    sums = array('I', [0] * 11)
    pack = None
    if packing == 'viper':
        from kagura_dma_pack import viper_pack
        pack = viper_pack
    old_dma, old_write, old_read = PIOTransport._xfer_dma, PIOTransport.write, PIOTransport.readinto

    def profiled_dma(self, data, queued):
        high, words = self._high[queued], self._words
        tx, rx = self._dma_tx, self._dma_rx
        done, n = 0, len(data)
        while done < n:
            m = min(_DMA_CHUNK, n - done)
            stamp = ticks_us()
            if pack is None:
                j = 1
                for k in range(done, done + m):
                    words[j] = high[data[k]]
                    j += 2
            else:
                pack(data, high, words, done, m)
            sums[0] += ticks_diff(ticks_us(), stamp)
            stamp = ticks_us()
            rx.config(read=self._sm, write=self._sink, count=m, ctrl=self._rx_ctrl, trigger=True)
            tx.config(read=words, write=self._sm, count=m, ctrl=self._tx_ctrl, trigger=True)
            sums[1] += ticks_diff(ticks_us(), stamp)
            stamp = ticks_us()
            left = m
            progress = ticks_us()
            while rx.active():
                sums[10] += 1
                count = rx.count
                if count != left:
                    left = count
                    progress = ticks_us()
                elif ticks_diff(ticks_us(), progress) >= self.timeout_us:
                    raise TransferTimeout(done + max(0, m - left - 1))
            sums[2] += ticks_diff(ticks_us(), stamp)
            sums[8] += 1
            sums[9] += m
            done += m

    def profiled_write(self, offset, data, inc=False):
        stamp = ticks_us()
        result = old_write(self, offset, data, inc)
        category = 3 if offset == R.REG_INC_L else 4 if offset == R.REG_VRAM_ADDR_L else 5
        sums[category] += ticks_diff(ticks_us(), stamp)
        return result

    def profiled_read(self, offset, buffer, inc=False):
        stamp = ticks_us()
        result = old_read(self, offset, buffer, inc)
        sums[6] += ticks_diff(ticks_us(), stamp)
        return result

    console.pause()
    game = shooter.Game(d, mode='HEAVY')
    samples = array('I', [0] * iterations)
    try:
        game.initialize()
        for _ in range(4):
            game.step()
            game.draw()
        d.wait_status(R.STATUS_COMMIT_BUSY, 0)
        data = game.build_oam()
        d.fence()
        for i in range(iterations):
            gc.collect()
            PIOTransport._xfer_dma = profiled_dma
            PIOTransport.write, PIOTransport.readinto = profiled_write, profiled_read
            stamp = ticks_us()
            try:
                d.write_memory(0xA000, data)
            finally:
                samples[i] = ticks_diff(ticks_us(), stamp)
                sums[7] += samples[i]
                PIOTransport._xfer_dma = old_dma
                PIOTransport.write, PIOTransport.readinto = old_write, old_read
            d.fence()  # Start the next timed write with the queue drained.
        game.sound.monitor()
        result = dict(packing=packing,height=d.height, lanes=raw.lanes, baudrate=raw.baudrate,
                      iterations=iterations, bytes_per_write=len(data),
                      dma_pack_us=sums[0]/iterations, dma_config_us=sums[1]/iterations,
                      dma_wait_us=sums[2]/iterations, inc_us=sums[3]/iterations,
                      address_us=sums[4]/iterations, payload_transport_us=sums[5]/iterations,
                      error_read_us=sums[6]/iterations, total_us=sums[7]/iterations,
                      chunks=sums[8], dma_bytes=sums[9], poll_iterations=sums[10],
                      max_us=max(samples), pcm0=game.sound.status0, pcm1=game.sound.status1,
                      fpga_error=d.read_reg(R.REG_ERROR_CODE))
    finally:
        PIOTransport._xfer_dma = old_dma
        PIOTransport.write, PIOTransport.readinto = old_write, old_read
        try:
            game.sound.stop()
        finally:
            console.resume()
    for key in sorted(result):
        print('DMA_PROFILE',key,result[key])
        sleep_ms(10)
    return result
