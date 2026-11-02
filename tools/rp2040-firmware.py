# SPDX-License-Identifier: Apache-2.0
"""Flash and roll back KAGURA MicroPython firmware on the Pico, with checks.

  check     REPL alive, firmware build, flash and filesystem hashes, FPGA ABI
  uf2-info  firmware UF2: blocks, family, address range (must end below the
            filesystem), payload SHA-256
  flash     --uf2 F (--backup-sha S | --current-uf2 C) [--approved]
            1. the whole flash must equal the verified backup (SHA-256), or the
               flash must hold exactly the UF2 C flashed before (reflashing);
            2. the UF2 must be RP2040 flash blocks that end below the
               filesystem (KAGURA_PICO: 0x100A0000, 1,408 KB at the end);
            3. machine.bootloader(), copy the UF2, wait for the REPL;
            4. the filesystem region hash must be unchanged and the flash
               must hold the UF2's bytes (read back).
  rollback-uf2  --backup-dir D --out F: a UF2 of the whole 2 MB backup
            (firmware and filesystem) to restore the board through BOOTSEL.
  rollback  --uf2 F --backup-sha S [--approved]: copies it, then checks that
            the whole flash equals the backup again.

Uses mpremote/pyserial (Windows: uv CPython with
build/transport-analysis/python-deps on PYTHONPATH). Never prints the USB serial.
"""
import argparse
import hashlib
import shutil
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/c-gem-desktop/tools'))
import rp2040_sram_bench as dev  # noqa: E402  (verified device helpers of stage 1)

FLASH = 0x10000000
FLASH_BYTES = 2 * 1024 * 1024
FS_START = FLASH + FLASH_BYTES - 1408 * 1024     # boards/KAGURA_PICO MICROPY_HW_FLASH_STORAGE_BYTES
FAMILY_RP2040 = 0xE48BFF56

REGION_HASH = dev.PAUSE + (
    "import uctypes,hashlib,binascii\n"
    "def _h(a,n):\n"
    " h=hashlib.sha256()\n"
    " for o in range(0,n,4096): h.update(uctypes.bytearray_at(a+o,min(4096,n-o)))\n"
    " return binascii.hexlify(h.digest()).decode()\n")
INFO = (
    "import os,gc\n"
    "gc.collect()\n"
    "print('BUILD',os.uname().version,os.uname().machine)\n"
    "print('HEAP',gc.mem_free(),gc.mem_alloc())\n"
    "try:\n d=kagura_console.screen.device\n print('FPGA',d.abi,hex(d.caps),d.height)\n"
    "except Exception as e:\n print('FPGA none',repr(e))\n"
    "try:\n import kagura_desktop\n print('NATIVE kagura_desktop',sorted(kagura_desktop.sizes().items()))\n"
    "except ImportError:\n print('NATIVE none')\n"
    "try:\n kagura_console.resume()\nexcept NameError:\n pass\n")


def uf2_blocks(path):
    data = Path(path).read_bytes()
    if len(data) % 512:
        raise SystemExit('UF2 size is not a multiple of 512')
    blocks = []
    for i in range(0, len(data), 512):
        m0, m1, flags, addr, size, no, count, family = struct.unpack_from('<8I', data, i)
        if (m0, m1, struct.unpack_from('<I', data, i + 508)[0]) != (0x0A324655, 0x9E5D5157, 0x0AB16F30):
            raise SystemExit('bad UF2 magic in block %d' % (i // 512))
        if not flags & 0x2000 or family != FAMILY_RP2040 or size != 256:
            raise SystemExit('block %d is not a 256-byte RP2040 block' % (i // 512))
        blocks.append((addr, data[i + 32:i + 32 + size]))
    return blocks


def uf2_info(path, below=None):
    blocks = uf2_blocks(path)
    lo, hi = min(a for a, _ in blocks), max(a + 256 for a, _ in blocks)
    if lo < FLASH or hi > FLASH + FLASH_BYTES:
        raise SystemExit('UF2 writes outside the 2 MB flash')
    if below is not None and hi > below:
        raise SystemExit('UF2 reaches 0x%08x, beyond 0x%08x' % (hi, below))
    image = bytearray(b'\xff' * (hi - lo))
    for a, d in blocks:
        image[a - lo:a - lo + 256] = d
    return dict(blocks=len(blocks), lo=lo, hi=hi, image=bytes(image),
                sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def bin_to_uf2(data, base, out):
    blocks = [data[i:i + 256] for i in range(0, len(data), 256)]
    with open(out, 'wb') as f:
        for n, chunk in enumerate(blocks):
            chunk = chunk.ljust(256, b'\xff')
            f.write(struct.pack('<8I', 0x0A324655, 0x9E5D5157, 0x2000, base + n * 256, 256, n, len(blocks),
                                FAMILY_RP2040) + chunk + bytes(476 - 256) + struct.pack('<I', 0x0AB16F30))


def hashes(port, ranges):
    src = REGION_HASH + ''.join("print('H',%d,%d,_h(%d,%d))\n" % (a, n, a, n) for a, n in ranges) + \
        "try:\n kagura_console.resume()\nexcept NameError:\n pass\n"
    out = dev.micropython_exec(port, src, timeout=300)
    got = {}
    for line in out.splitlines():
        if line.startswith('H '):
            _, a, n, h = line.split()
            got[(int(a), int(n))] = h
    return got


def info(port):
    return dev.micropython_exec(port, INFO, timeout=60)


def copy_uf2(args, uf2):
    try:
        dev.micropython_exec(args.port, "import machine\nmachine.bootloader()\n", timeout=5)
    except Exception:
        pass
    drive, desc = dev.find_bootsel_drive()
    print('BOOTSEL', ' | '.join(l.strip() for l in desc.splitlines() if l.strip()))
    with open(uf2, 'rb') as src, open(drive / Path(uf2).name, 'wb') as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
    print('COPIED', Path(uf2).name)
    port = dev.wait_port(args.expected_serial, seconds=60)
    if not port:
        raise SystemExit('MicroPython did not enumerate after the copy; the board is in BOOTSEL '
                         'or not booting: copy the rollback UF2 (BOOTSEL button if needed)')
    args.port = port
    time.sleep(4)   # boot.py: console start


def cmd_check(args):
    dev.resolve_device(args)
    print(info(args.port).strip())
    h = hashes(args.port, [(FLASH, FLASH_BYTES), (FS_START, FLASH + FLASH_BYTES - FS_START)])
    print('FLASH_SHA256', h[(FLASH, FLASH_BYTES)])
    print('FS_SHA256', h[(FS_START, FLASH + FLASH_BYTES - FS_START)])


def cmd_flash(args):
    if not args.approved:
        raise SystemExit('refusing to flash without --approved')
    if not args.backup_sha and not args.current_uf2:
        raise SystemExit('give --backup-sha or --current-uf2')
    u = uf2_info(args.uf2, below=FS_START)
    print('UF2 %s: %d blocks 0x%08x..0x%08x (filesystem at 0x%08x), sha256 %s'
          % (Path(args.uf2).name, u['blocks'], u['lo'], u['hi'], FS_START, u['sha256']))
    dev.resolve_device(args)
    fs = (FS_START, FLASH + FLASH_BYTES - FS_START)
    before = hashes(args.port, [(FLASH, FLASH_BYTES), fs])
    print('FLASH_BEFORE', before[(FLASH, FLASH_BYTES)])
    if args.current_uf2:
        c = uf2_info(args.current_uf2)
        region = (c['lo'], c['hi'] - c['lo'])
        held = hashes(args.port, [region])[region]
        print('CURRENT_FIRMWARE', 'matches %s' % Path(args.current_uf2).name
              if held == hashlib.sha256(c['image']).hexdigest() else 'DIFFERS')
        if held != hashlib.sha256(c['image']).hexdigest():
            raise SystemExit('the flash does not hold --current-uf2. Nothing written.')
    elif before[(FLASH, FLASH_BYTES)] != args.backup_sha:
        raise SystemExit('flash differs from the verified backup; take a new backup first. Nothing written.')
    copy_uf2(args, args.uf2)
    print(info(args.port).strip())
    image = (u['lo'], u['hi'] - u['lo'])
    after = hashes(args.port, [fs, image])
    ok_fs = after[fs] == before[fs]
    ok_fw = after[image] == hashlib.sha256(u['image']).hexdigest()
    print('FS_UNCHANGED', 'yes' if ok_fs else 'NO')
    print('FIRMWARE_READBACK', 'match' if ok_fw else 'MISMATCH')
    if not (ok_fs and ok_fw):
        raise SystemExit('post-flash check failed: run rollback')


def cmd_rollback_uf2(args):
    folder = Path(args.backup_dir)
    data = (folder / 'flash-2MiB.bin').read_bytes()
    want = (folder / 'sha256.txt').read_text().split()[0]
    if hashlib.sha256(data).hexdigest() != want or len(data) != FLASH_BYTES:
        raise SystemExit('backup does not match its sha256.txt')
    bin_to_uf2(data, FLASH, args.out)
    print('ROLLBACK_UF2 %s: whole flash of backup %s, sha256 %s'
          % (args.out, want, hashlib.sha256(Path(args.out).read_bytes()).hexdigest()))


def cmd_rollback(args):
    if not args.approved:
        raise SystemExit('refusing to flash without --approved')
    uf2_info(args.uf2)
    try:
        dev.resolve_device(args)
        copy_uf2(args, args.uf2)
    except SystemExit:
        raise
    h = hashes(args.port, [(FLASH, FLASH_BYTES)])[(FLASH, FLASH_BYTES)]
    print('FLASH_AFTER_ROLLBACK', h, 'equals backup' if h == args.backup_sha else 'DIFFERS')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'flash', 'rollback'):
        s = sub.add_parser(name)
        s.add_argument('--port')
        s.add_argument('--expected-serial')
        if name != 'check':
            s.add_argument('--uf2', required=True)
            s.add_argument('--backup-sha', required=name == 'rollback')
            s.add_argument('--approved', action='store_true')
            if name == 'flash':
                s.add_argument('--current-uf2')
    s = sub.add_parser('uf2-info')
    s.add_argument('uf2')
    s = sub.add_parser('rollback-uf2')
    s.add_argument('--backup-dir', required=True)
    s.add_argument('--out', required=True)
    args = p.parse_args()
    if args.cmd == 'uf2-info':
        u = uf2_info(args.uf2)
        print('%d blocks 0x%08x..0x%08x, ends %s the filesystem, sha256 %s'
              % (u['blocks'], u['lo'], u['hi'], 'below' if u['hi'] <= FS_START else 'INSIDE', u['sha256']))
        return
    {'check': cmd_check, 'flash': cmd_flash, 'rollback': cmd_rollback, 'rollback-uf2': cmd_rollback_uf2}[args.cmd](args)


if __name__ == '__main__':
    main()
