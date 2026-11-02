#!/usr/bin/env python3
"""Offline RP2040 SRAM ELF/UF2 validator. Never accesses a device."""
import argparse
import hashlib
import pathlib
import struct

LOW, HIGH = 0x20000000, 0x20042000

def verify(elf, uf2):
    assert elf[:7] == b'\x7fELF\x01\x01\x01', 'expected ELF32 little endian'
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', elf)
    assert h[1:3] == (2, 40), 'expected ARM executable'
    entry, phoff, shoff = h[4:7]
    assert h[9] == 32 and h[11] == 40
    image, headers = {}, []
    for i in range(h[10]):
        kind, offset, va, pa, fs, ms, flags, alignment = struct.unpack_from('<8I', elf, phoff + 32*i)
        if kind != 1:
            continue
        assert LOW <= va <= va+ms <= HIGH and va == pa and fs <= ms
        assert offset + fs <= len(elf)
        headers.append(dict(vaddr=hex(va), filesz=fs, memsz=ms, flags=flags))
        for j, byte in enumerate(elf[offset:offset+fs]):
            assert va+j not in image, 'overlapping ELF data'
            image[va+j] = byte
    assert image and (entry & ~1) == min(image) == LOW and entry & 1
    sections = []
    names_header = struct.unpack_from('<10I', elf, shoff + h[13]*40)
    names = elf[names_header[4]:names_header[4]+names_header[5]]
    for i in range(h[12]):
        name, kind, flags, va, offset, size, *_ = struct.unpack_from('<10I', elf, shoff + i*40)
        if flags & 2 and size:
            assert LOW <= va <= va+size <= HIGH, 'allocatable section outside SRAM'
            sections.append((names[name:].split(b'\0', 1)[0].decode(), hex(va), size, 'NOLOAD' if kind == 8 else 'LOAD'))
    assert len(uf2) and len(uf2) % 512 == 0
    count, seen, targets, actual = len(uf2)//512, set(), set(), {}
    for i in range(count):
        block = uf2[i*512:(i+1)*512]
        m0, m1, flags, address, size, number, total, family = struct.unpack_from('<8I', block)
        assert (m0, m1, struct.unpack_from('<I', block, 508)[0]) == (0x0a324655, 0x9e5d5157, 0x0ab16f30)
        assert flags == 0x2000 and family == 0xe48bff56 and size == 256
        assert total == count and number not in seen and number < count
        assert LOW <= address <= address+size <= HIGH and address % 256 == 0
        assert address not in targets
        if i == 0:
            assert address == LOW, 'first UF2 block must select SRAM binary'
        seen.add(number); targets.add(address)
        actual.update((address+j, byte) for j, byte in enumerate(block[32:32+size]))
    assert seen == set(range(count))
    assert all(actual.get(a) == b for a, b in image.items()), 'UF2 does not match ELF'
    assert all(a in image or b == 0 for a, b in actual.items()), 'nonzero ELF padding'
    assert max(actual) < (max(image)//256+1)*256, 'extra UF2 blocks'
    return headers, sections, count

def selftest(elf, uf2):
    cases = []
    for offset, value in [(12,0x10000000),(512+12,0x10000100),(8,0x2001),(12,HIGH),
                          (28,0),(24,0),(20,1)]:
        b = bytearray(uf2); struct.pack_into('<I', b, offset, value); cases.append(b)
    b = bytearray(uf2); b[32] ^= 1; cases.append(b)
    for b in cases:
        try:
            verify(elf, b)
        except AssertionError:
            continue
        raise AssertionError('malformed image accepted')
    print('SELFTEST rejected', len(cases), 'mutated UF2 files')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('elf', type=pathlib.Path); ap.add_argument('uf2', type=pathlib.Path)
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    elf, uf2 = args.elf.read_bytes(), args.uf2.read_bytes()
    headers, sections, count = verify(elf, uf2)
    print('ELF_SHA256', hashlib.sha256(elf).hexdigest())
    print('UF2_SHA256', hashlib.sha256(uf2).hexdigest())
    print('ENTRY 0x20000001; all PT_LOAD and allocated sections in SRAM')
    for header in headers: print('PT_LOAD', header)
    for section in sections: print('SECTION', *section)
    print('UF2_PASS blocks=%d; payload matches ELF; no flash targets' % count)
    if args.selftest: selftest(elf, uf2)
