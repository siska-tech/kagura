# SPDX-License-Identifier: Apache-2.0
"""SRAM-only RP2040 benchmark of the C desktop core (pico/README.md).

  verify-uf2 --uf2 F --elf F      offline: every UF2 block targets main SRAM,
                                  matches the ELF load image, enters at its lowest
                                  address. No device access.
  flash-hash [--port P --expected-serial S]
                                  read-only SHA-256 of the whole 2 MB flash via
                                  the installed MicroPython (raw REPL, no soft reset)
  run [--port P --expected-serial S] --uf2 F --elf F --approved --log L
                                  the whole procedure: hash, control reboot, hash,
                                  BOOTSEL, verified copy of the RAM-only UF2, collect
                                  results, return to flash MicroPython, hash again.
  summarize LOG [--crc FILE] [--counts FILE]
                                  results table, CRC check against the PC, measured
                                  cycles against the qemu instruction counts.

Port and serial default to the only Raspberry Pi USB device present (refused
if there is not exactly one). Never prints the USB serial. Run with the Windows Python that has mpremote and
pyserial (see docs/kagura-ui-validation.md for the existing device setup).
"""
import argparse
import hashlib
import shutil
import string
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

UF2_MAGIC = (0x0A324655, 0x9E5D5157, 0x0AB16F30)
UF2_FLAG_FAMILY = 0x00002000
RP2040_FAMILY = 0xE48BFF56
RAM_LO, RAM_HI = 0x20000000, 0x20042000     # datasheet 2.8.4.2 b: main RAM range
FLASH_BYTES = 2 * 1024 * 1024               # Raspberry Pi Pico (PICO_BOARD pico)
PICO_VID = 0x2E8A
NO_FLASH_SERIAL = 'E' * 16                  # pico_unique_id in PICO_NO_FLASH builds

HASH_SOURCE = (
    "import uctypes,hashlib,binascii\n"
    "h=hashlib.sha256()\n"
    "for o in range(0,%d,4096): h.update(uctypes.bytearray_at(0x10000000+o,4096))\n"
    "print('FLASH_SHA256',binascii.hexlify(h.digest()).decode())\n" % FLASH_BYTES)


def elf_load_image(path):
    """{address: byte} of every PT_LOAD file byte, and the entry point."""
    data = Path(path).read_bytes()
    if data[:4] != b'\x7fELF' or data[4] != 1 or data[5] != 1:
        raise SystemExit('not a little-endian ELF32 file')
    entry, phoff = struct.unpack_from('<II', data, 24)
    phentsize, phnum = struct.unpack_from('<HH', data, 42)
    image = {}
    for i in range(phnum):
        p_type, p_offset, _vaddr, p_paddr, p_filesz = struct.unpack_from('<IIIII', data, phoff + i * phentsize)
        if p_type == 1 and p_filesz:
            for k in range(p_filesz):
                image[p_paddr + k] = data[p_offset + k]
    return image, entry


def verify_uf2(uf2_path, elf_path):
    """Returns a list of check lines; raises SystemExit on any failure."""
    data = Path(uf2_path).read_bytes()
    if not data or len(data) % 512:
        raise SystemExit('UF2 size %d is not a multiple of 512' % len(data))
    blocks = [data[i:i + 512] for i in range(0, len(data), 512)]
    seen, written = set(), {}
    first_target = None
    for index, b in enumerate(blocks):
        m0, m1, flags, target, size, number, count, family = struct.unpack_from('<8I', b, 0)
        (m_end,) = struct.unpack_from('<I', b, 508)
        problems = []
        if (m0, m1, m_end) != UF2_MAGIC:
            problems.append('bad magic')
        if flags != UF2_FLAG_FAMILY:
            problems.append('flags %#x (only familyID-present allowed)' % flags)
        if family != RP2040_FAMILY:
            problems.append('family %#x' % family)
        if size != 256:
            problems.append('payload %d' % size)
        if count != len(blocks) or number != index or number in seen:
            problems.append('block %d/%d at position %d' % (number, count, index))
        if not (RAM_LO <= target and target + size <= RAM_HI):
            problems.append('target %#010x outside main SRAM' % target)
        if problems:
            raise SystemExit('UF2 block %d rejected: %s' % (index, ', '.join(problems)))
        if first_target is None:
            first_target = target
        seen.add(number)
        for k in range(size):
            if target + k in written:
                raise SystemExit('UF2 blocks overlap at %#010x' % (target + k))
            written[target + k] = b[32 + k]
    image, entry = elf_load_image(elf_path)
    missing = [a for a in image if written.get(a) != image[a]]
    if missing:
        raise SystemExit('UF2 differs from the ELF load image at %d byte(s), first %#010x' % (len(missing), min(missing)))
    extra = [a for a in written if a not in image and written[a] != 0]
    if extra:
        raise SystemExit('UF2 writes %d non-zero byte(s) outside the ELF load image' % len(extra))
    lowest = min(written)
    if (entry & ~1) != lowest:
        raise SystemExit('ELF entry %#010x is not the lowest UF2 address %#010x' % (entry, lowest))
    return ['UF2 %s: %d blocks, sha256 %s' % (Path(uf2_path).name, len(blocks), hashlib.sha256(data).hexdigest()),
            'all blocks: magic ok, flags=familyID only, family RP2040, payload 256, numbered 0..%d' % (len(blocks) - 1),
            'targets %#010x..%#010x, all inside main SRAM %#010x..%#010x; first block %#010x (RAM binary)'
            % (lowest, max(written) + 1, RAM_LO, RAM_HI, first_target),
            'no target in flash (0x10000000..0x11000000) or XIP cache-as-SRAM (0x15000000..)',
            'payload equals the ELF load image (%d bytes); padding is zero' % len(image),
            'entry %#010x = lowest loaded address (bootrom enters RAM binaries there)' % entry]


def resolve_device(args):
    """Fills args.port / args.expected_serial. Given values must match; omitted
    ones are taken from the only Raspberry Pi USB device present. The serial is
    kept in memory and never printed."""
    from serial.tools.list_ports import comports
    picos = [p for p in comports() if p.vid == PICO_VID]
    if len(picos) != 1:
        raise SystemExit('expected exactly one Raspberry Pi USB device, found %d; no device action taken' % len(picos))
    found = picos[0]
    if args.port and args.port.lower() != found.device.lower():
        raise SystemExit('the Raspberry Pi device is not on the given port; no device action taken')
    if args.expected_serial and args.expected_serial.lower() != (found.serial_number or '').lower():
        raise SystemExit('USB serial mismatch; no device action taken')
    if (found.serial_number or '').upper() == NO_FLASH_SERIAL:
        raise SystemExit('a no_flash program is running (serial EEEE...); reset the Pico first')
    args.port, args.expected_serial = found.device, found.serial_number or ''


def find_port(expected_serial, serial=None):
    from serial.tools.list_ports import comports
    want = (serial or expected_serial).lower()
    ports = [p for p in comports() if p.vid == PICO_VID and (p.serial_number or '').lower() == want]
    return ports[0].device if len(ports) == 1 else None


def wait_port(expected_serial, serial=None, seconds=30):
    for _ in range(seconds * 4):
        port = find_port(expected_serial, serial)
        if port:
            return port
        time.sleep(0.25)
    return None


def wait_gone(expected_serial, serial=None, seconds=15):
    """Waits until the device has left the bus (after a reset request)."""
    for _ in range(seconds * 4):
        if not find_port(expected_serial, serial):
            return True
        time.sleep(0.25)
    return False


def micropython_exec(port, source, timeout=120):
    from mpremote.transport_serial import SerialTransport
    transport = SerialTransport(port, timeout=0.2)
    try:
        transport.enter_raw_repl(soft_reset=False)
        output, error = transport.exec_raw(source, timeout=timeout)
        if error:
            raise SystemExit('device exception: %s' % error.decode('utf8', 'replace'))
        try:
            transport.exit_raw_repl()
        except Exception:
            pass   # the source may have reset the device
        return output.decode('utf8', 'replace')
    finally:
        transport.close()


def flash_hash(port):
    out = micropython_exec(port, HASH_SOURCE, timeout=180)
    for line in out.splitlines():
        if line.startswith('FLASH_SHA256 '):
            return line.split()[1]
    raise SystemExit('no FLASH_SHA256 line')


def find_bootsel_drive(seconds=30):
    """The single drive whose INFO_UF2.TXT names an RP2 bootloader."""
    for _ in range(seconds * 4):
        drives = []
        for letter in string.ascii_uppercase:
            info = Path('%s:/INFO_UF2.TXT' % letter)
            try:
                text = info.read_text(errors='replace')
            except OSError:
                continue
            if 'Board-ID: RPI-RP2' in text:   # the RP2040 bootrom's drive
                drives.append((Path('%s:/' % letter), text))
        if len(drives) == 1:
            return drives[0]
        if len(drives) > 1:
            raise SystemExit('more than one RP2 BOOTSEL drive; no copy made')
        time.sleep(0.25)
    raise SystemExit('no RPI-RP2 drive appeared')


def run(args):
    import serial
    if not args.approved:
        raise SystemExit('refusing to touch the device without --approved')
    resolve_device(args)
    port = args.port
    checks = verify_uf2(args.uf2, args.elf)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open('w', encoding='utf8', newline='\n') as log:
        def emit(line):
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()

        emit('HOST_START %s' % datetime.now(timezone.utc).isoformat())
        for c in checks:
            emit('HOST_UF2 ' + c)
        h0 = flash_hash(port)
        emit('HOST_FLASH_BEFORE %s' % h0)
        # Control: a normal reboot must not change the hash (boot.py writes nothing).
        try:
            micropython_exec(port, "import machine\nmachine.reset()\n", timeout=5)
        except Exception:
            pass
        if not wait_gone(args.expected_serial):
            raise SystemExit('the control reset did not take place')
        port = wait_port(args.expected_serial)
        if not port:
            raise SystemExit('MicroPython did not come back after the control reset')
        time.sleep(3)
        h1 = flash_hash(port)
        emit('HOST_FLASH_CONTROL %s' % h1)
        if h1 != h0:
            raise SystemExit('flash hash changed across a normal reboot; stopping before BOOTSEL')
        try:
            micropython_exec(port, "import machine\nmachine.bootloader()\n", timeout=5)
        except Exception:
            pass
        drive, info = find_bootsel_drive()
        emit('HOST_BOOTSEL %s' % ' | '.join(l.strip() for l in info.splitlines() if l.strip()))
        verify_uf2(args.uf2, args.elf)   # re-check the exact file right before copying
        target = drive / Path(args.uf2).name
        with open(args.uf2, 'rb') as src, open(target, 'wb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
        emit('HOST_COPIED %s' % Path(args.uf2).name)
        bench = wait_port(args.expected_serial, NO_FLASH_SERIAL, seconds=30)
        if not bench:
            raise SystemExit('the RAM program did not enumerate (watchdog returns the Pico to MicroPython)')
        with serial.Serial(bench, 115200, timeout=0.5) as s:
            time.sleep(0.5)
            s.write(b'g')
            deadline = time.time() + args.timeout
            done = False
            while time.time() < deadline and not done:
                line = s.readline().decode('utf8', 'replace').rstrip()
                if line:
                    emit(line)
                    done = line == 'KDRP_DONE'
            s.write(b'r')
        wait_gone(args.expected_serial, NO_FLASH_SERIAL, seconds=20)   # watchdog reboot into flash
        if not done:
            emit('HOST_RESULT incomplete (no KDRP_DONE)')
        port = wait_port(args.expected_serial, seconds=60)
        if not port:
            raise SystemExit('MicroPython did not come back; unplug/replug USB (RAM image is lost on power-off)')
        time.sleep(3)
        h2 = flash_hash(port)
        emit('HOST_FLASH_AFTER %s' % h2)
        ok = h2 == h0 and done
        emit('HOST_FLASH_UNCHANGED %s' % ('yes' if h2 == h0 else 'NO'))
        emit('HOST_END %s %s' % (datetime.now(timezone.utc).isoformat(), 'OK' if ok else 'FAILED'))
        if not ok:
            sys.exit(1)


def summarize(args):
    lines = Path(args.log).read_text(encoding='utf8').splitlines()
    crc_ref = {}
    if args.crc:
        for l in Path(args.crc).read_text().splitlines():
            name, value = l.split()
            crc_ref[name] = value
    counts = {}
    if args.counts:
        for l in Path(args.counts).read_text().splitlines():
            parts = [p.strip() for p in l.strip('|').split('|')]
            if len(parts) == 2 and parts[1].isdigit():
                counts[parts[0]] = int(parts[1])
    clk = 125_000_000
    for l in lines:
        if l.startswith('KDRP_INFO'):
            f = l.split()
            clk = int(f[f.index('clk_sys_hz') + 1])
    bad = 0
    for l in lines:
        if l.startswith('KDRP_CRC'):
            _, name, value = l.split()
            ref = crc_ref.get(name)
            if ref is not None and ref != value:
                bad += 1
                print('CRC MISMATCH %s device %s pc %s' % (name, value, ref))
    if crc_ref:
        print('CRC: %d workloads, %d mismatches' % (sum(l.startswith('KDRP_CRC') for l in lines), bad))
    print('| workload | total p50 cycles | ms @%.0f MHz | render p50 | export p50 | instructions (qemu) | cycles/instruction |'
          % (clk / 1e6))
    print('|---|---:|---:|---:|---:|---:|---:|')
    for l in lines:
        if not l.startswith('KDRP_TIME'):
            continue
        f = l.split()
        v = {f[i]: f[i + 1] for i in range(2, len(f) - 1, 2)}
        total = int(v['total_p50'])
        n = counts.get(f[1])
        print('| %s | %d | %.2f | %s | %s | %s | %s |' % (
            f[1], total, total * 1000 / clk, v['render_p50'], v['export_p50'],
            n if n is not None else '', '%.2f' % (total / n) if n else ''))
    for l in lines:
        if l.startswith(('KDRP_MEM', 'KDRP_LAYOUT', 'HOST_FLASH')):
            print(l)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verify-uf2')
    v.add_argument('--uf2', required=True)
    v.add_argument('--elf', required=True)
    h = sub.add_parser('flash-hash')
    h.add_argument('--port')
    h.add_argument('--expected-serial')
    r = sub.add_parser('run')
    r.add_argument('--port')
    r.add_argument('--expected-serial')
    r.add_argument('--uf2', required=True)
    r.add_argument('--elf', required=True)
    r.add_argument('--approved', action='store_true')
    r.add_argument('--timeout', type=int, default=300)
    r.add_argument('--log', type=Path, default=Path('build/c-gem-rp2040/device.txt'))
    s = sub.add_parser('summarize')
    s.add_argument('log')
    s.add_argument('--crc')
    s.add_argument('--counts')
    args = p.parse_args()
    if args.cmd == 'verify-uf2':
        for line in verify_uf2(args.uf2, args.elf):
            print(line)
    elif args.cmd == 'flash-hash':
        resolve_device(args)
        print('FLASH_SHA256 %s' % flash_hash(args.port))
    elif args.cmd == 'run':
        run(args)
    else:
        summarize(args)


if __name__ == '__main__':
    main()
