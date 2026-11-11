#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Combine a KAGURA_PICO_SHOWCASE firmware UF2 and the showcase ROMFS into one UF2.

The ROMFS holds the showcase assets and the Misaki font:
  /showcase_assets/  /starfall_assets/  /sakura_assets/  /fonts/misaki8.kfnt
It is placed at the partition the board reserves below the filesystem
(boards/KAGURA_PICO_SHOWCASE/mpconfigboard.h). Blocks are renumbered so the
RP2040 boot ROM sees one consistent UF2.

  python tools/make-showcase-firmware.py --firmware firmware.uf2 --out kagura-showcase.uf2

Needs mpremote's romfs.py (build/transport-analysis/python-deps by default);
only that file is loaded.
"""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import re
import shutil
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'software/micropython/boards/KAGURA_PICO_SHOWCASE/mpconfigboard.h'
EXAMPLES = ROOT / 'software/micropython/examples'
ASSET_DIRS = ('showcase_assets', 'starfall_assets', 'sakura_assets')
FONT = ROOT / 'software/micropython/fonts/misaki8.kfnt'

XIP = 0x10000000
FLASH_BYTES = 2 * 1024 * 1024
FAMILY_RP2040 = 0xE48BFF56
MAGIC0, MAGIC1, MAGIC_END = 0x0A324655, 0x9E5D5157, 0x0AB16F30
FLAG_FAMILY = 0x00002000
PAYLOAD = 256


def board_sizes(path=BOARD):
    text = path.read_text(encoding='utf-8')
    sizes = {}
    for name in ('MICROPY_HW_FLASH_STORAGE_BYTES', 'MICROPY_HW_ROMFS_BYTES'):
        m = re.search(r'#define\s+%s\s+\((\d+)\s*\*\s*1024\)' % name, text)
        if not m:
            raise SystemExit('%s not found in %s' % (name, path))
        sizes[name] = int(m.group(1)) * 1024
    storage, romfs = sizes['MICROPY_HW_FLASH_STORAGE_BYTES'], sizes['MICROPY_HW_ROMFS_BYTES']
    return XIP + FLASH_BYTES - storage - romfs, romfs


def load_romfs_writer(path):
    spec = importlib.util.spec_from_file_location('kagura_romfs_writer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_romfs


def build_romfs(make_romfs):
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for name in ASSET_DIRS:
            shutil.copytree(EXAMPLES / name, stage / name)
        (stage / 'fonts').mkdir()
        shutil.copyfile(FONT, stage / 'fonts' / FONT.name)
        return bytes(make_romfs(str(stage), mpy_cross=False))


def read_uf2(path):
    data = Path(path).read_bytes()
    if len(data) % 512:
        raise SystemExit('%s: not a whole number of UF2 blocks' % path)
    blocks = []
    for off in range(0, len(data), 512):
        m0, m1, flags, addr, size, _no, _count, family = struct.unpack_from('<8I', data, off)
        if (m0, m1) != (MAGIC0, MAGIC1) or struct.unpack_from('<I', data, off + 508)[0] != MAGIC_END:
            raise SystemExit('%s: bad UF2 block %d' % (path, off // 512))
        if not flags & FLAG_FAMILY or family != FAMILY_RP2040 or size != PAYLOAD:
            raise SystemExit('%s: block %d is not an RP2040 256-byte flash block' % (path, off // 512))
        blocks.append((addr, data[off + 32:off + 32 + PAYLOAD]))
    return blocks


def write_uf2(path, blocks):
    out = bytearray()
    for n, (addr, payload) in enumerate(blocks):
        head = struct.pack('<8I', MAGIC0, MAGIC1, FLAG_FAMILY, addr, PAYLOAD, n, len(blocks), FAMILY_RP2040)
        out += head + payload.ljust(476, b'\0') + struct.pack('<I', MAGIC_END)
    Path(path).write_bytes(out)
    return bytes(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--firmware', required=True, type=Path, help='KAGURA_PICO_SHOWCASE firmware.uf2')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--romfs-out', type=Path, help='also write the raw ROMFS image')
    p.add_argument('--romfs-py', type=Path,
                   default=ROOT / 'build/transport-analysis/python-deps/mpremote/romfs.py')
    args = p.parse_args()

    base, limit = board_sizes()
    fw = read_uf2(args.firmware)
    fw_end = max(addr + PAYLOAD for addr, _ in fw)
    if min(addr for addr, _ in fw) < XIP or fw_end > base:
        raise SystemExit('firmware 0x%08x..0x%08x overlaps the ROMFS at 0x%08x' % (
            min(a for a, _ in fw), fw_end, base))

    image = build_romfs(load_romfs_writer(args.romfs_py))
    if len(image) > limit:
        raise SystemExit('ROMFS image %d B exceeds the %d B partition' % (len(image), limit))
    padded = image + b'\xff' * (-len(image) % PAYLOAD)
    rom = [(base + off, padded[off:off + PAYLOAD]) for off in range(0, len(padded), PAYLOAD)]
    # One contiguous image: the gap between the firmware and the ROMFS is
    # written as erased pages, so the UF2 covers every page it spans.
    gap = [(addr, b'\xff' * PAYLOAD) for addr in range(fw_end, base, PAYLOAD)]
    fw = sorted(fw)
    out = write_uf2(args.out, fw + gap + rom)
    if args.romfs_out:
        args.romfs_out.write_bytes(image)

    print('firmware  0x%08x..0x%08x  %7d B  (%d B free below ROMFS)' % (
        XIP, fw_end, fw_end - XIP, base - fw_end))
    print('romfs     0x%08x..0x%08x  %7d B  of %d B' % (base, base + len(image), len(image), limit))
    print('romfs sha256 %s' % hashlib.sha256(image).hexdigest())
    print('uf2 %s  %d blocks  sha256 %s' % (args.out, len(out) // 512, hashlib.sha256(out).hexdigest()))


if __name__ == '__main__':
    main()
