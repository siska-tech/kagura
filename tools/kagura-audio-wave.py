# SPDX-License-Identifier: Apache-2.0
"""Does the hardware play the wave tables the tracker's editor made?

Takes a recording of KAGURA-9's HDMI audio (48 kHz WAV) and the board log of
`tools/kagura-audio-board.py wave`, which holds one note per table with
silence between and prints `WAVE name step hex` for each. For every note,
the steady middle of the recording is folded onto one period of the note
(its frequency is exact: STEP * 48000 / 2^24) and compared with the table
played by the FPGA (nearest sample, no interpolation): the Pearson
correlation over the best phase. A value near 1 means the shape matches.
Pure Python, no numpy.

  python tools/kagura-audio-wave.py audio.wav board.log [--min 0.95]
"""
import argparse
import importlib.util
import math
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('timing', Path(__file__).with_name('kagura-audio-timing.py'))
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


def notes(x, rate, quiet_s=0.4, level=0.05):
    """(start, end) sample ranges of sound separated by quiet_s of silence."""
    mags = sorted(abs(v) for v in x[::97])
    thr = mags[int(len(mags) * 0.99)] * level
    out, start, run = [], None, 0
    quiet = int(quiet_s * rate)
    for i, v in enumerate(x):
        if -thr < v < thr:
            run += 1
            if start is not None and run >= quiet:
                out.append((start, i - run))
                start = None
        else:
            if start is None:
                start = i
            run = 0
    if start is not None:
        out.append((start, len(x)))
    return out


def correlate(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sab = sum((p - ma) * (q - mb) for p, q in zip(a, b))
    saa = sum((p - ma) ** 2 for p in a)
    sbb = sum((q - mb) ** 2 for q in b)
    return sab / math.sqrt(saa * sbb) if saa and sbb else 0.0


def fold_score(x, start, end, step, table, rate=48000):
    """Best correlation of the recording with the table over 64 phases."""
    n = len(table)
    # The steady middle (skip the attack and the release), at most 0.5 s.
    a = start + (end - start) // 4
    b = min(end - (end - start) // 4, a + rate // 2)
    seg = x[a:b]
    best = -1.0
    for k in range(64):
        off = k / 64
        expect = [table[int(((i * step / 16777216.0) + off) % 1.0 * n)] for i in range(len(seg))]
        c = correlate(seg, expect)
        if c > best:
            best = c
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wav')
    ap.add_argument('log')
    ap.add_argument('--min', type=float, default=0.95)
    a = ap.parse_args()
    waves = []
    for line in Path(a.log).read_text(encoding='utf8').splitlines():
        if line.startswith('WAVE '):
            _, name, step, data = line.split()
            raw = bytes.fromhex(data)
            waves.append((name, int(step), [v - 256 if v > 127 else v for v in raw]))
    rate, x = timing.load_mono(a.wav)
    found = [r for r in notes(x, rate) if r[1] - r[0] > rate // 2]
    print('NOTES recorded %d, tables %d' % (len(found), len(waves)))
    ok = len(found) == len(waves)
    for (name, step, table), (s, e) in zip(waves, found):
        c = fold_score(x, s, e, step, table, rate)
        good = c >= a.min
        ok = ok and good
        print('WAVE %-8s len %3d at %.2f s, %.2f s long: correlation %.4f %s' % (
            name, len(table), s / rate, (e - s) / rate, c, 'ok' if good else 'LOW'))
    print('RESULT', 'ok' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
