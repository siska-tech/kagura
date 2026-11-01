# SPDX-License-Identifier: Apache-2.0
"""Stream the exact C-golden Sakura background without a runtime tile cache."""
import binascii
from kagura import regs as R

CACHE_BASE = 0x680000  # outside slide slots 0..6 and both demos' PCM/aurora
TILES = 265


def load(d, work, path, cache=False):
    # Real bytearrays avoid mpremote's buffer_nbytes(memoryview) fallback,
    # which copies a whole view after its serial transaction has begun.
    chunk = bytearray(512)
    with open(path, 'rb') as f:
        header = f.read(6)
        if len(header) != 6 or header[:4] != b'SCN1':
            raise ValueError('not a showcase scenery file')
        count = header[4] | header[5] << 8
        if not 1 <= count <= 512:
            raise ValueError('scenery tile count')
        if cache and count != TILES:
            raise ValueError('cached scenery must contain 265 C-golden tiles')
        last = bytearray(count * 32 % 512 or 512)
        left, crc = count * 32 + 4096, 0
        while left:
            target = last if left < len(chunk) else chunk
            n = f.readinto(target)
            if n != len(target):
                raise ValueError('truncated scenery file')
            crc = binascii.crc32(target, crc)
            left -= n
        tail = f.read(5)
        if len(tail) != 4 or (crc & 0xffffffff) != int.from_bytes(tail, 'little'):
            raise ValueError('scenery CRC mismatch')
    print('SHOWCASE scenery checked', count)
    # Verification precedes I/O. The two small buffers are reused for upload.
    with open(path, 'rb') as f:
        f.read(6)
        targets = ((CACHE_BASE, count * 32), (CACHE_BASE + count * 32, 4096)) if cache else (
            (256 * 32, count * 32), (R.VRAM_MAP_BASE, 4096))
        for address, size in targets:
            while size:
                target = last if size < len(chunk) else chunk
                n = f.readinto(target)
                if n != len(target):
                    raise OSError('scenery changed while loading')
                d.write_memory(address, target)
                address += n
                size -= n
    print('SHOWCASE scenery streamed', count)
    return count


def preload(d, path):
    load(d, None, path, cache=True)
    d.fence()


def restore(d, strip, packed, work):
    """No file/VFS traffic while Sakura's text/audio buffers occupy RAM."""
    d.copy(CACHE_BASE, 256 * 32, TILES * 32)
    d.copy(CACHE_BASE + TILES * 32, R.VRAM_MAP_BASE, 4096)
    d.fence()
    return TILES
