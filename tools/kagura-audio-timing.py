# SPDX-License-Identifier: Apache-2.0
"""Note timing in a recording of KAGURA-9's HDMI audio (48 kHz WAV).

The KSNG player changes the synthesizer only on ticks, so every note onset
should fall on the tick grid t0 + k * tick (tick = 2.5 s / BPM). This finds
onsets from silence (record the click song, songs/click.ksn, for timing),
splits the recording into sections at silences of --gap seconds or more,
and fits each section's onsets to the grid by least squares, giving:
  * the fitted tick period against the nominal one (tempo error, ppm), and
  * the residuals (jitter of the onsets, detection error included).
Pure Python (wave, array): no numpy needed.

  python tools/kagura-audio-timing.py audio.wav --bpm 140 [--min-onsets 50]
"""
import argparse
import array
import math
import sys
import wave


def load_mono(path):
    with wave.open(path, 'rb') as w:
        if w.getsampwidth() != 2:
            raise SystemExit('16-bit PCM expected')
        rate, ch = w.getframerate(), w.getnchannels()
        data = array.array('h', w.readframes(w.getnframes()))
    if sys.byteorder == 'big':
        data.byteswap()
    if ch == 2:
        data = array.array('i', (data[i] + data[i + 1] for i in range(0, len(data), 2)))
    return rate, data


def onsets(x, rate, quiet_ms=5.0, level=0.2):
    """Onsets from silence: the first sample above level x (99th percentile of
    |x|) after at least quiet_ms below it. Exact to one sample for signals
    like the click song (songs/click.ksn); not meant for dense music."""
    mags = sorted(abs(v) for v in x[::97])
    thr = mags[int(len(mags) * 0.99)] * level
    quiet = int(rate * quiet_ms / 1000)
    found, run = [], 0
    for i, v in enumerate(x):
        if -thr < v < thr:
            run += 1
        else:
            if run >= quiet:
                found.append(i / rate)
            run = 0
    return found, thr


def sections(times, gap):
    out, cur = [], []
    for t in times:
        if cur and t - cur[-1] > gap:
            out.append(cur)
            cur = []
        cur.append(t)
    if cur:
        out.append(cur)
    return out


def fit(times, tick):
    """Least squares t = t0 + k * p with integer k from the nominal tick."""
    t0 = times[0]
    ks = [round((t - t0) / tick) for t in times]
    n = len(times)
    mk, mt = sum(ks) / n, sum(times) / n
    sxx = sum((k - mk) ** 2 for k in ks)
    if sxx == 0:
        return None
    p = sum((k - mk) * (t - mt) for k, t in zip(ks, times)) / sxx
    b = mt - p * mk
    # Re-assign ticks with the fitted period, once.
    ks = [round((t - b) / p) for t in times]
    mk = sum(ks) / n
    sxx = sum((k - mk) ** 2 for k in ks)
    p = sum((k - mk) * (t - mt) for k, t in zip(ks, times)) / sxx
    b = mt - p * mk
    res = sorted((t - (b + p * k)) * 1e6 for k, t in zip(ks, times))
    return p, res, ks[-1] - ks[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wav')
    ap.add_argument('--bpm', type=float, required=True)
    ap.add_argument('--gap', type=float, default=1.0, help='seconds of silence between sections')
    ap.add_argument('--min-onsets', type=int, default=40)
    a = ap.parse_args()
    rate, x = load_mono(a.wav)
    tick = 2.5 / a.bpm
    times, thr = onsets(x, rate)
    print('FILE %s seconds %.1f rate %d onsets %d nominal_tick_us %.1f' % (a.wav, len(x) / rate, rate, len(times),
                                                                          tick * 1e6))
    for i, sec in enumerate(sections(times, a.gap)):
        if len(sec) < a.min_onsets:
            print('SECTION %d start %.2f onsets %d (too few to fit)' % (i, sec[0], len(sec)))
            continue
        r = fit(sec, tick)
        if r is None:
            continue
        p, res, span = r
        n = len(res)
        rms = math.sqrt(sum(v * v for v in res) / n)
        absr = sorted(abs(v) for v in res)
        print('SECTION %d start %.2f end %.2f onsets %d span_ticks %d tick_us %.3f tempo_error_ppm %+.0f '
              'jitter_us p50 %.0f p95 %.0f max %.0f rms %.0f' % (
                  i, sec[0], sec[-1], n, span, p * 1e6, (p / tick - 1) * 1e6,
                  absr[n // 2], absr[int(n * 0.95)], absr[-1], rms))


if __name__ == '__main__':
    main()
