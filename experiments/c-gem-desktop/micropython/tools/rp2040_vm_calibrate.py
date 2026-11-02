# SPDX-License-Identifier: Apache-2.0
"""Times bench/calibrate.py on the RP2040's installed MicroPython.

Runs the loops from the raw REPL (code in RAM only): no flashing, no
filesystem writes, no FPGA access. The HDMI console is paused during the
loops, so REPL output does not go to the FPGA, and resumed afterwards. The
flash SHA-256 is read before and after as a check that nothing was written.
Prints us per loop and machine.freq().

Uses mpremote/pyserial (Windows: uv CPython with
build/transport-analysis/python-deps on PYTHONPATH). Never prints the USB
serial.
  python tools/rp2040_vm_calibrate.py [--n 2000] [--repeat 5]
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
import rp2040_sram_bench as stage1  # noqa: E402

RESUME = 'try:\n kagura_console.resume()\nexcept NameError:\n pass\n'
RUNNER = '''
import time, machine, gc
_T = [0] * 8
_k = [0]
def _mark():
    _T[_k[0]] = time.ticks_us()
    _k[0] += 1
gc.collect()
_res = []
for _r in range(%(repeat)d):
    _k[0] = 0
    loops(%(n)d, _mark, _mark)
    _res.append([time.ticks_diff(_T[2 * j + 1], _T[2 * j]) for j in range(4)])
try:
    kagura_console.resume()
except NameError:
    pass
print('FREQ', machine.freq())
for _row in _res:
    print('LOOPS', *_row)
'''


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--n', type=int, default=2000)
    p.add_argument('--repeat', type=int, default=5)
    p.add_argument('--port')
    p.add_argument('--expected-serial')
    args = p.parse_args()
    stage1.resolve_device(args)
    h0, c0 = stage1.flash_hash(args.port, True)
    print('FLASH_BEFORE', h0, 'console', c0)
    source = (stage1.PAUSE + (HERE.parent / 'bench' / 'calibrate.py').read_text() +
              RUNNER % {'n': args.n, 'repeat': args.repeat})
    out = stage1.micropython_exec(args.port, source, timeout=120)
    rows = []
    for line in out.splitlines():
        if line.startswith(('FREQ', 'LOOPS')):
            print(line)
        if line.startswith('LOOPS'):
            rows.append([int(v) for v in line.split()[1:]])
    h1, c1 = stage1.flash_hash(args.port, True)
    print('FLASH_AFTER', h1, 'console', c1)
    print('FLASH_UNCHANGED', 'yes' if h1 == h0 else 'NO')
    stage1.micropython_exec(args.port, RESUME)   # the hash paused it
    names = ('empty loop', 'Python call, 2 args', "str.find('g', 1, 8)", 'bytearray store')
    for j, name in enumerate(names):
        best = min(r[j] for r in rows)
        print('BEST %s: %d us for %d iterations = %.3f us/iteration' % (name, best, args.n, best / args.n))


if __name__ == '__main__':
    main()
