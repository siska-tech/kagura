# SPDX-License-Identifier: Apache-2.0
"""Small video preloader, independent of the native game code heap layout."""
from starfall_scores import VIDEO_SIZE, VIDEO_CRC

CACHE_BASE = 0x690000


def preload(d, assets='starfall_assets'):
    import binascii
    chunk = bytearray(512)
    tail = bytearray(VIDEO_SIZE%512)
    offset,crc = 0,0
    with open(assets+'/video.bin','rb') as f:
        while offset < VIDEO_SIZE:
            target = chunk if VIDEO_SIZE-offset >= 512 else tail
            if f.readinto(target) != len(target): raise ValueError('STARFALL truncated video asset')
            crc = binascii.crc32(target,crc)
            d.write_memory(CACHE_BASE+offset,target)
            offset += len(target)
        if f.read(1) or crc&0xffffffff != VIDEO_CRC: raise ValueError('STARFALL video CRC')
    d.fence()
