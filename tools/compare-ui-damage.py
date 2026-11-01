# SPDX-License-Identifier: Apache-2.0
"""PC register-model comparison of UI dirty tiles for damage_limit values.

Runs examples/ui_benchmark.py workloads on test_driver.RegisterModel.
Tile/payload counts are deterministic; host times are not RP2040 times and are not printed.
"""
import argparse
import binascii
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / 'software/micropython'
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT), str(ROOT / 'examples')]

import test_driver as T  # noqa: E402
from kagura import Kagura, regs as R  # noqa: E402
from kagura_ja import Font  # noqa: E402
from test_framebuffer import decode  # noqa: E402
import ui_benchmark  # noqa: E402


def measure(limit, samples):
    model = T.RegisterModel()
    model.ext[R.EXT_SCREEN_HEIGHT] = 240
    model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
    model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
    font = Font(str(ROOT / 'fonts/misaki8.kfnt'))
    app, widgets = ui_benchmark.make(Kagura(model).probe(), font, exclusive=True)
    app.damage_limit = limit
    rows = []
    try:
        ui_benchmark.run(app, widgets, samples=samples, cycles=1,
                         report=lambda tag, value: rows.append((tag, value)))
        crc = binascii.crc32(decode(app.backend.fb.buffer)) & 0xffffffff
    finally:
        app.close()
        font.close()
    return {v['workload']: (v['tiles'], v['pattern_payload_bytes'])
            for tag, v in rows if tag == 'UI_BENCH'}, crc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=32)
    parser.add_argument('--limits', type=int, nargs='+', default=[1, 4])
    args = parser.parse_args()
    results = [(limit,) + measure(limit, args.samples) for limit in args.limits]
    print('workload ' + ' '.join('limit%d tiles/bytes' % r[0] for r in results))
    for workload in results[0][1]:
        print('%-8s ' % workload + ' '.join('%7d/%-11d' % r[1][workload] for r in results))
    print('final buffer crc32 ' + ' '.join(str(r[2]) for r in results))
    if len({r[2] for r in results}) != 1:
        raise SystemExit('final buffers differ')


if __name__ == '__main__':
    main()
