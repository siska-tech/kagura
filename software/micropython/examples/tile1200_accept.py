# SPDX-License-Identifier: Apache-2.0
"""Pico numerical acceptance for ABI 0.6; never claims visual/audio quality.

Use run(sdk='kagura1200') for an isolated copy beside existing Pico libraries.
Only scratch VRAM/PSRAM contents are overwritten; no firmware/Flash writes.
"""
import time
import gc
import json
import binascii

BOUNDARIES = (0, 63, 1023, 1024, 1087, 1088, 1151, 1152, 1196, 1199, 1200, 2047)


def tile_bytes(tile):
    return bytes((tile * 17 + (tile >> 8) * 31 + j * 13 + 0x5A) & 255 for j in range(32))


def tile_address(tile):
    return tile * 32 if tile < 1024 else 0xB000 + (tile - 1024) * 32


def _log(event, **values):
    values['event'] = event
    print('T1200 ' + json.dumps(values))
    time.sleep_ms(2)


def _read(d, address, expected, label):
    actual = bytearray(len(expected))
    d.read_memory_into(address, actual)
    if actual != expected:
        for i in range(len(actual)):
            if actual[i] != expected[i]:
                raise AssertionError('%s at %06x: %02x != %02x' %
                                     (label, address + i, actual[i], expected[i]))
    return binascii.crc32(actual) & 0xFFFFFFFF


def _verify_patterns(d, full=True):
    crc = 0
    starts = range(0, 1200, 4) if full else [t for t in BOUNDARIES if t < 1200]
    for first in starts:
        if full and first % 128 == 0:
            _log('verify_progress', first_tile=first)
            gc.collect()
        expected = b''.join(tile_bytes(t) for t in range(first, min(first + (4 if full else 1), 1200)))
        actual = bytearray(len(expected))
        d.read_memory_into(tile_address(first), actual)
        if actual != expected:
            raise AssertionError('pattern readback tiles %d..%d' % (first, first + 3))
        crc = binascii.crc32(actual, crc)
    return crc & 0xFFFFFFFF


def _verify_map(d, data, full):
    crc = 0
    for offset in (range(0, 4096, 128) if full else (0, 3968)):
        block = data[offset:offset + 128]
        _read(d, 0x8000 + offset, block, 'map')
        crc = binascii.crc32(block, crc)
    return crc & 0xFFFFFFFF


def _pack_sprite(tile, n, phase, height, poison=False):
    x = (phase * 3 + n * 23) % 352 - 16
    y = (phase + n * 13) % (height + 16) - 8
    flags = 4 | ((n & 1) << 3) | ((n & 2) << 3) | ((n & 4) << 3)
    return bytes((x & 255, (x >> 8) & 3, y & 255, ((y >> 8) & 3) | flags,
                  tile & 255, ((tile >> 8) & 3) | ((n & 15) << 2) |
                  ((tile >> 10) << 6) | (128 if poison else 0),
                  0xAA if poison else 0, 0x55 if poison else 0))


def run(seconds=60, mode='qspi', sdk='kagura', baudrate=5_000_000, pcm=True, full=True, cold=False):
    if seconds < 1:
        raise ValueError('seconds must be positive')
    gc.enable()
    gc.collect()
    package = __import__(sdk, None, None, ['connect'])
    R = __import__(sdk + '.regs', None, None, ['REG_STATUS'])
    Video = __import__(sdk + '.video', None, None, ['Video']).Video
    Audio = __import__(sdk + '.audio', None, None, ['Audio']).Audio
    d = package.connect(mode=mode, baudrate=baudrate)
    # Numerical acceptance uses the portable packer, independently of optional
    # native/Viper support in a particular Pico firmware.
    packing = __import__(sdk + '.dma_pack', None, None, ['python_pack'])
    packing.viper_pack = packing.viper_pack32 = None
    v, audio = Video(d), Audio(d)
    pcm_on = bool(pcm and d.caps & R.CAPS_PSRAM)
    checks = 0
    try:
        count = d.ext_read(R.EXT_PATTERN_COUNT_L) | d.ext_read(R.EXT_PATTERN_COUNT_H) << 8
        if d.abi != (0, 6) or count != 1200:
            raise AssertionError('ABI/pattern count mismatch')
        _log('probe', abi=list(d.abi), caps=d.caps, height=d.height, patterns=count,
             mode=mode, baudrate=baudrate, pcm=pcm_on, heap=gc.mem_free(),
             full_readback=full, pack_backend='python')
        # A prior interrupted host may have left an unread result on the FPGA.
        d.wait_status(R.STATUS_READ_BUSY, 0)
        if d.read_reg(R.REG_STATUS) & R.STATUS_READ_READY:
            d.read_reg(R.REG_VRAM_READ_RESULT)
        d.clear_errors()
        d.write_reg(R.REG_DISPLAY_CTRL, 0)
        d.commit()
        if cold:
            for bank in range(19):
                for tile in (bank * 64, min(bank * 64 + 63, 1199)):
                    _read(d, tile_address(tile), bytes(32), 'cold pattern clear')
            for address, length in ((0x8000, 128), (0x9000, 256), (0x9400, 512),
                                    (0x9800, 512), (0xA000, 128)):
                _read(d, address, bytes(length), 'cold clear')
            _log('cold_clear', sampled_bytes=2752, banks=19)
        for channel in range(6):
            audio.stop(channel)
        d.audio_commit()
        d.clear_errors()
        d.fill(0x8000, 4096, 0x23)
        d.fill(0x9000, 256, 0)
        d.fill(0xA000, 2048, 0)
        d.fence()
        _log('cleared')
        for first in range(0, 1200, 32):
            v.tiles(first, b''.join(tile_bytes(t) for t in range(first, min(first + 32, 1200))))
            if first % 128 == 0:
                _log('upload_progress', first_tile=first)
        v.tiles(1023, tile_bytes(1023) + tile_bytes(1024))
        d.fence()
        alias_bytes = 4096 if full else 32
        _read(d, 0x8000, bytes([0x23]) * alias_bytes, 'pattern/map alias')
        initial_crc = _verify_patterns(d, full)
        pattern_bytes = 38400 if full else 32 * len([t for t in BOUNDARIES if t < 1200])
        _log('patterns', bytes=pattern_bytes, crc32=initial_crc, full=full)
        checks += pattern_bytes + alias_bytes
        # Valid FILL covers the complete additional region and its two ends.
        d.fill(0xB000, 5632, 0x6D)
        d.fill(0x9000, 256, 0xA5)
        d.fence()
        fill_addresses = range(0xB000, 0xC600, 128) if full else (0xB000, 0xB780, 0xB800, 0xBF80, 0xC000, 0xC580)
        for address in fill_addresses:
            _read(d, address, bytes([0x6D]) * 128, 'extra FILL')
        _read(d, 0x9000, bytes([0xA5]) * 256, 'table FILL')
        checks += len(fill_addresses) * 128 + 256
        for first in range(1024, 1200, 16):
            v.tiles(first, b''.join(tile_bytes(t) for t in range(first, min(first + 16, 1200))))
        d.fence()
        # Bypass SDK range checks: verify actual FPGA rejection and no advance.
        def rejected(address, length=None, opcode=R.CMD_FILL):
            d._address(address)
            if length is None:
                d.write_reg(R.REG_VRAM_READ_REQUEST, 0)
            else:
                d.transport.write(R.REG_LENGTH_L,
                                  bytes((length & 255, length >> 8, 0x55)), True)
                d.write_reg(R.REG_COMMAND, opcode)
            error = d.read_reg(R.REG_ERROR_CODE)
            if error != R.ERROR_CODE_INVALID_ADDRESS:
                raise AssertionError('FPGA range rejection %06x: %02x' % (address, error))
            address_after = sum(d.read_reg(R.REG_VRAM_ADDR_L + i) << (i * 8) for i in range(3))
            if address_after != address:
                raise AssertionError('rejected command moved address')
            d.clear_errors()
        for address, length in ((0xC5FF, 2), (0x90FF, 2), (0x8FFF, 2), (0x7FFF, 0x3002)):
            rejected(address, length)
        rejected(0xC600)
        rejected(0x9100)
        _read(d, 0xC5E0, tile_bytes(1199), 'rejected FILL pattern side effect')
        _read(d, 0x90FF, b'\xA5', 'rejected FILL table side effect')
        _read(d, 0x8000, bytes([0x23]) * alias_bytes, 'rejected FILL map side effect')
        _log('ranges', rejected=6, preserved=True)
        # Every palette/flip and all bank boundaries appear in the workload.
        map_data, table = bytearray(4096), bytearray(256)
        for i in range(2048):
            tile = BOUNDARIES[i % len(BOUNDARIES)]
            word = (tile & 1023) | ((i & 15) << 10) | ((i & 3) << 14)
            map_data[i * 2] = word & 255
            map_data[i * 2 + 1] = word >> 8
            table[i // 8] |= (tile >> 10) << (i % 8)
        d.write_memory(0x8000, map_data)
        d.write_memory(0x9000, table)
        d.fence()
        for col, tile, palette, flip in ((7, 1199, 15, True), (8, 1024, 6, False), (7, 1023, 0, False)):
            v.map_entry(col, 0, tile, palette, flip, flip)
            word = (tile & 1023) | (palette << 10) | (3 << 14 if flip else 0)
            map_data[col * 2:col * 2 + 2] = bytes((word & 255, word >> 8))
            table[col // 8] = (table[col // 8] & ~(1 << (col % 8))) | ((tile >> 10) << (col % 8))
        d.fence()
        map_crc = _verify_map(d, map_data, full)
        table_crc = _read(d, 0x9000, table, 'map extension')
        for n in range(256):
            v.palette(n, ((n & 15) << 8) | (((n >> 4) & 15) << 4) | ((n * 7) & 15))
        expected_oam = bytearray()
        for n in range(16):
            record = _pack_sprite(BOUNDARIES[n % len(BOUNDARIES)], n, 0, d.height, True)
            d.write_memory(0xA000 + n * 8, record)
            record = bytearray(record)
            record[5] &= 127
            record[6] = record[7] = 0
            expected_oam.extend(record)
        d.fence()
        oam_crc = _read(d, 0xA000, expected_oam, '11-bit OAM masks')
        if d.caps & R.CAPS_PSRAM:
            for first in range(1024, 1200, 16):
                data = b''.join(tile_bytes(t) for t in range(first, min(first + 16, 1200)))
                d.write_memory(0x500000 + (first - 1024) * 32, data)
            d.write_memory(0x510000, table)
            d.fence()
            d.copy(0x500000, 0xB000, 5632)
            d.copy(0x510000, 0x9000, 256)
            d.fence()
            for t in (1024, 1087, 1088, 1151, 1152, 1199):
                _read(d, tile_address(t), tile_bytes(t), 'COPY boundary')
            _read(d, 0x9000, table, 'COPY table')
            for address, length in ((0xC5FF, 2), (0x90FF, 2), (0x7FFF, 0x3002)):
                rejected(address, length, R.CMD_COPY)
            _log('copy', pattern_bytes=5632, table_bytes=256, rejected=3)
        # Exercise all six PSG channels plus two looped PCM channels.
        for _ in range(2):
            for channel in (4, 5):
                audio.wave(channel, bytes((i * 16 - 128) & 255 for i in range(32)))
            d.audio_commit()
        for channel in (0, 1, 2, 4, 5):
            audio.tone(channel, (220, 330, 440, 0, 550, 660)[channel], left=4, right=4)
        audio.noise(200, left=2, right=2)
        d.audio_write(R.AUDIO_MASTER_GAIN, 32)
        d.audio_commit()
        if pcm_on:
            # Build one short period before repeating it. MicroPython's bytes
            # iterable constructor can otherwise need a second growing 4 KiB
            # allocation while the first is still live on a fragmented heap.
            gc.collect()
            sample = bytes((i * 2 - 128) & 255 for i in range(128)) * 32
            for channel, address in ((0, 0x400000), (1, 0x410000)):
                d.write_memory(address, sample)
                d.fence()
                if full:
                    _read(d, address, sample, 'PCM source')
                else:
                    _read(d, address, sample[:128], 'PCM source start')
                    _read(d, address + len(sample) - 128, sample[-128:], 'PCM source end')
                audio.prepare_pcm(channel, address, address + len(sample), loop=address)
                audio.play_pcm(channel, left=16 if channel == 0 else 0,
                               right=16 if channel == 1 else 0)
        if d.caps & R.CAPS_RSCROLL:
            v.raster_scroll(())
        v.scroll(0, 0)
        d.write_reg(R.REG_DISPLAY_CTRL, 7)
        d.commit()
        time.sleep_ms(100)
        d.audio_write(0xE2, 6)
        d.clear_errors()
        d.write_reg(R.REG_IRQ_STATUS, 0x7F)
        _log('scene', map_crc32=map_crc, table_crc32=table_crc, oam_crc32=oam_crc,
             visual_verified=False, audio_quality_verified=False)
        gc.collect()
        start = last_report = last_sample = time.ticks_ms()
        last_frame = d.read_reg(R.REG_FRAME_COUNT_L)
        frames = loops = copies = reads = 0
        minimum_heap = gc.mem_free()
        while time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
            t = 1024 + loops % 176
            if d.caps & R.CAPS_PSRAM:
                d.copy(0x500000 + (t - 1024) * 32, tile_address(t), 32)
                copies += 1
            else:
                v.tile(t, tile_bytes(t))
            for n in range(16):
                d.write_memory(0xA000 + n * 8,
                               _pack_sprite(BOUNDARIES[n % len(BOUNDARIES)], n, loops, d.height))
            v.scroll(loops % 512, (loops // 2) % 256)
            d.commit()
            _read(d, tile_address(t), tile_bytes(t), 'live tile')
            i = (loops * 17) % 256
            _read(d, 0x9000 + i, table[i:i + 1], 'live table')
            reads += 33
            error, irq = d.read_reg(R.REG_ERROR_CODE), d.read_reg(R.REG_IRQ_STATUS)
            status = d.audio_read(0xE1)
            if error or irq & R.IRQ_STATUS_SPR_OVERFLOW or status & 6:
                raise AssertionError('telemetry error=%02x irq=%02x audio=%02x' % (error, irq, status))
            pcm_status = [audio.pcm_status(c) for c in (0, 1)] if pcm_on else []
            if any((s & 0x78) or not (s & R.AUDIO_PCM_STATUS_ACTIVE) for s in pcm_status):
                raise AssertionError('PCM stopped/faulted: ' + repr(pcm_status))
            now = time.ticks_ms()
            if time.ticks_diff(now, last_sample) > 3000:
                raise AssertionError('frame counter sample gap too long')
            frame = d.read_reg(R.REG_FRAME_COUNT_L)
            frames += (frame - last_frame) & 255
            last_frame, last_sample = frame, now
            loops += 1
            minimum_heap = min(minimum_heap, gc.mem_free())
            if time.ticks_diff(now, last_report) >= 10000:
                gc.collect()
                _log('progress', elapsed_ms=time.ticks_diff(now, start), frames=frames,
                     loops=loops, copies=copies, read_bytes=reads, pcm=pcm_status,
                     error=error, audio=status, min_heap=minimum_heap, heap_after_gc=gc.mem_free())
                last_report = now
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        fps = frames * 1000 / elapsed
        if not 55 < fps < 65:
            raise AssertionError('unexpected video frame counter rate: ' + str(fps))
        final_crc = _verify_patterns(d, full)
        _verify_map(d, map_data, full)
        _read(d, 0x9000, table, 'final table')
        d.check_errors()
        if final_crc != initial_crc:
            raise AssertionError('pattern CRC changed')
        result = dict(passed=True, elapsed_ms=elapsed, frames=frames, fps=fps,
                      loops=loops, copies=copies, live_read_bytes=reads,
                      pattern_crc32=final_crc, map_crc32=map_crc, table_crc32=table_crc,
                      mode=mode, height=d.height, caps=d.caps, pcm=pcm_on,
                      min_heap=minimum_heap, initial_checked_bytes=checks,
                      full_readback=full, pattern_bytes_verified=pattern_bytes,
                      cold_clear_verified=cold,
                      visual_verified=False, audio_quality_verified=False)
        _log('pass', **result)
        return result
    finally:
        try:
            for c in range(6):
                audio.stop(c)
            if pcm_on:
                for c in (0, 1):
                    base = R.AUDIO_PCM_BASE + c * R.AUDIO_PCM_STRIDE
                    d.audio_write(base + R.AUDIO_PCM_CONTROL, 0)
                    d.audio_write(base + R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_STOP)
            d.audio_commit()
        finally:
            d.deinit()
