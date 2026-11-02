# SPDX-License-Identifier: Apache-2.0
"""Compare stage 2 HDMI captures with the PC references (kd_hdmi_ref).

  python hdmi_compare.py REF_DIR RUN_DIR      (needs numpy and pillow)

Geometry: the 640x480p60 output is captured at 1280x960, so logical pixel
(x, y) of the 320x240 screen is the 4x4 block at (4x, 4y). Each block is
sampled at its centre; a +-1 capture-pixel phase search confirms the
alignment. Colour: HDMI YCbCr transport and the capture's conversion change
RGB values, so the observed colour of each palette index is learned from block
interiors whose 3x3 logical neighbourhood has a single reference index
(across all scenes), and every sample is classified to the nearest learned
colour. A pixel is a mismatch when its class differs from the reference index.

Recordings (RUN_DIR/video/<scene>/*.png, already point-sampled to 320x240):
every 8x1 segment of every frame must equal the previous scene's reference
(old) or this scene's reference (new). Frames mixing old and new segments are
the expected non-atomic intermediates; a segment matching neither is
corruption. Writes RUN_DIR/compare.md, diff images and a montage.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SCENES = ['01-desktop', '02-files-open', '03-files-closed', '04-overlap', '05-activate', '06-menu',
          '07-menu-closed', '08-about', '09-about-closed', '10-move-live', '11-outline-drag',
          '12-outline-drop', '13-sprite-draw']
PALETTE444 = [0x0A5, 0x000, 0xFFF, 0xBBB, 0x666, 0x23C, 0xD22, 0xEC2,
              0x063, 0x2BC, 0xC4C, 0x842, 0x8AF, 0x8E8, 0xF82, 0xFFC]


def load_ref(path):
    return np.array(Image.open(path))   # indexed: palette indices


def sample(still, dx=0, dy=0):
    a = np.asarray(Image.open(still).convert('RGB')).astype(np.int32)
    ys = np.arange(240) * 4 + 2 + dy
    xs = np.arange(320) * 4 + 2 + dx
    return a[ys][:, xs]


def interior(ref):
    """True where the 3x3 neighbourhood has one index (no edge blur)."""
    m = np.ones_like(ref, dtype=bool)
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            m[1:-1, 1:-1] &= ref[1:-1, 1:-1] == ref[1 + oy:239 + oy, 1 + ox:319 + ox]
    m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = False
    return m


def classify(samples, centroids):
    d = ((samples[:, :, None, :] - centroids[None, None, :, :]) ** 2).sum(-1)
    return d.argmin(-1)


LUMA = np.array([0.299, 0.587, 0.114])


def explained(ref, samples, centroids):
    """Pixels whose colour may be off because of 4:2:2 chroma: they sit on a
    horizontal colour edge of the reference and their luma matches the
    reference colour within 48. (Luma is carried at full resolution.)"""
    edge = np.zeros_like(ref, dtype=bool)
    edge[:, 1:] |= ref[:, 1:] != ref[:, :-1]
    edge[:, :-1] |= ref[:, :-1] != ref[:, 1:]
    edge[:, 0] |= ref[:, 0] != 1     # next to the blanking interval
    edge[:, -1] |= ref[:, -1] != 1
    luma_ok = np.abs(samples @ LUMA - centroids[ref] @ LUMA) < 48
    # Horizontal filtering by the HDMI receiver/capture scaler (blur and the
    # overshoot of its sharpening): the sample lies on the line through its
    # own colour and a differing left/right neighbour's colour, at most 60%
    # of the colour difference towards or away from the neighbour, within
    # 40 RGB units of that line. Measured: light grey before black reads
    # 246 instead of 197 (overshoot).
    blend = np.zeros_like(edge)
    own = centroids[ref].astype(float)
    for side in (-1, 1):
        nb = np.roll(ref, -side, 1)
        # Beyond the first and last column the HDMI line is blanking (black).
        if side == -1:
            nb[:, 0] = 1
        else:
            nb[:, -1] = 1
        other = centroids[nb].astype(float)
        d = other - own
        t = ((samples - own) * d).sum(-1) / np.maximum((d * d).sum(-1), 1)
        resid = np.sqrt(((samples - own - t[..., None] * d) ** 2).sum(-1))
        blend |= (nb != ref) & (np.abs(t) <= 0.6) & (resid < 40)
    return edge & (luma_ok | blend)


def shift(a, dx, dy):
    """a moved by (dx, dy) logical pixels; uncovered borders repeat the edge."""
    a = np.roll(np.roll(a, dy, 0), dx, 1)
    if dx > 0: a[:, :dx] = a[:, dx:dx + 1]
    if dx < 0: a[:, dx:] = a[:, dx - 1:dx]
    if dy > 0: a[:dy] = a[dy:dy + 1]
    if dy < 0: a[dy:] = a[dy - 1:dy]
    return a


def main():
    global SCENES
    ref_dir, run = Path(sys.argv[1]), Path(sys.argv[2])
    # Other scene sets (e.g. the Japanese desktop demo): every NN-name.png reference.
    names = sorted(p.stem for p in ref_dir.glob('[0-9][0-9]-*.png'))
    if names and names != SCENES:
        SCENES = names
    stills = run / 'stills'
    refs = {n: load_ref(ref_dir / ('%s.png' % n)) for n in SCENES}
    present = [n for n in SCENES if (stills / ('%s.png' % n)).exists()]
    expected = np.array([[((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17] for c in PALETTE444])

    def learn(samples):
        """Observed colour of each index: mean of per-scene interior medians."""
        sums, counts = np.zeros((16, 3)), np.zeros(16)
        for n in present:
            m = interior(refs[n])
            for i in range(16):
                sel = m & (refs[n] == i)
                if sel.any():
                    sums[i] += np.median(samples[n][sel], axis=0)
                    counts[i] += 1
        return np.where(counts[:, None] > 0, sums / np.maximum(counts, 1)[:, None], expected), counts

    # Phase search: the sampling offset whose classification agrees best.
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            trial = {n: sample(stills / ('%s.png' % n), dx, dy) for n in present}
            cents, _ = learn(trial)
            score = sum(int((classify(trial[n], cents) == refs[n]).sum()) for n in present)
            if best is None or score > best[0]:
                best = (score, dx, dy, trial)
    _, dx, dy, samples = best
    centroids, counts = learn(samples)
    lines = ['# HDMI capture vs PC reference', '',
             'Sampling phase: dx %+d, dy %+d capture pixels from the block centre.' % (dx, dy), '',
             '| index | expected RGB | observed (median) | scenes |', '|---:|---|---|---:|']
    for i in range(16):
        lines.append('| %d | %s | %s | %d |' % (i, tuple(int(v) for v in expected[i]),
                                                tuple(int(v) for v in centroids[i]), counts[i]))
    lines += ['', 'A mismatch is "chroma" when explained by 4:2:2 colour blur (on a horizontal colour edge of the '
              'reference, luma correct); every other mismatch is "unexplained".', '',
              '| scene | colour mismatches | of 76,800 | chroma | unexplained | unexplained tiles |',
              '|---|---:|---:|---:|---:|---|']
    montage = []
    total_bad = total_unexplained = 0
    for n in present:
        cls = classify(samples[n], centroids)
        bad = cls != refs[n]
        unexplained = bad & ~explained(refs[n], samples[n], centroids)
        total_bad += int(bad.sum())
        total_unexplained += int(unexplained.sum())
        tiles = sorted({(int(y) // 8) * 40 + int(x) // 8 for y, x in zip(*np.nonzero(unexplained))})
        lines.append('| %s | %d | %.4f%% | %d | %d | %s |' % (
            n, bad.sum(), 100.0 * bad.sum() / bad.size, bad.sum() - unexplained.sum(), unexplained.sum(),
            ', '.join(map(str, tiles[:12])) + (' ...' if len(tiles) > 12 else '')))
        pal = Image.open(ref_dir / ('%s.png' % n)).convert('RGB')
        cap = Image.open(stills / ('%s.png' % n)).convert('RGB').resize((640, 480), Image.BOX)
        diff = np.array(pal.resize((640, 480), Image.NEAREST)) // 3
        diff[np.kron(bad, np.ones((2, 2), dtype=bool))] = (255, 200, 0)          # chroma: amber
        diff[np.kron(unexplained, np.ones((2, 2), dtype=bool))] = (255, 0, 0)   # unexplained: red
        row = Image.new('RGB', (1920, 480))
        row.paste(pal.resize((640, 480), Image.NEAREST), (0, 0))
        row.paste(cap, (640, 0))
        row.paste(Image.fromarray(diff.astype(np.uint8)), (1280, 0))
        row.save(run / ('compare-%s.png' % n))
        montage.append(row.resize((960, 240), Image.BOX))
    if montage:
        m = Image.new('RGB', (960, 240 * len(montage)))
        for i, r in enumerate(montage):
            m.paste(r, (0, 240 * i))
        m.save(run / 'montage.png')
    lines += ['', 'Total colour mismatches: %d, of which unexplained: %d' % (total_bad, total_unexplained), '']
    # Intermediate frames.
    video = run / 'video'
    if video.exists():
        lines += ['## Recorded transitions', '',
                  'Capture-to-capture: the settled frames before the transition (median of the first 10) and '
                  'after it (median of the last 10) are the "old" and "new" images, so static capture artefacts '
                  'cancel. A pixel is old or new when within 40 RGB units of that image, or a blend (on the line '
                  'between its old and new colour). Frames with both old and new pixels are the expected '
                  'non-atomic intermediates: runs land while the frame is scanned out, byte by byte, so an 8x1 '
                  'tile-row segment can be partly written ("partial segments"). A remaining pixel at the edge of '
                  'a segment whose neighbouring segment is in a different update state is a "torn-row boundary" '
                  '(the capture filter mixes the new colour on one side with the old on the other). Any other '
                  'pixel is corrupt. The settled endpoints are also checked against the PC references (after the '
                  'recording path alignment, found by search, and with colours learned from the recording).', '',
                  '| scene | frames | old | new | mixed (non-atomic) | partial segments | torn-row boundary px | '
                  'corrupt px | settled new vs PC: unexplained px |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        load = lambda f: np.asarray(Image.open(f).convert('RGB')).astype(np.int32)  # noqa: E731
        for folder in sorted(p for p in video.iterdir() if p.is_dir()):
            n = folder.name
            new_ref = refs[n]
            frames = sorted(folder.glob('*.png'))
            imgs = [load(f) for f in frames]
            old_img = np.median(np.stack(imgs[:10]), axis=0)
            new_img = np.median(np.stack(imgs[-10:]), axis=0)
            kinds = {'old': 0, 'new': 0, 'mixed': 0}
            partial = corrupt = torn = 0
            d = new_img - old_img
            for s in imgs:
                ok_old = np.abs(s - old_img).max(-1) < 40
                ok_new = np.abs(s - new_img).max(-1) < 40
                t = ((s - old_img) * d).sum(-1) / np.maximum((d * d).sum(-1), 1)
                blend = (t >= 0) & (t <= 1) & (np.sqrt(((s - old_img - t[..., None] * d) ** 2).sum(-1)) < 40)
                seg_old = ok_old.reshape(240, 40, 8).all(-1)
                seg_new = ok_new.reshape(240, 40, 8).all(-1)
                state = np.where(seg_old, 0, np.where(seg_new, 1, 2))          # old, new, partial
                differs = np.zeros((240, 40, 8), dtype=bool)
                differs[:, :-1, 7] = state[:, :-1] != state[:, 1:]              # last pixel, next segment
                differs[:, 1:, 0] = state[:, 1:] != state[:, :-1]               # first pixel, previous one
                cand = ~ok_old & ~ok_new & ~blend
                boundary = cand & differs.reshape(240, 320)
                torn += int(boundary.sum())
                corrupt += int((cand & ~boundary).sum())
                partial += int((~seg_old & ~seg_new).sum())
                if ok_new.all():
                    kinds['new'] += 1
                elif ok_old.all():
                    kinds['old'] += 1
                else:
                    kinds['mixed'] += 1
            best = None
            for ddy in range(-2, 3):
                for ddx in range(-2, 3):
                    agree = (classify(shift(new_img, ddx, ddy), centroids) == new_ref).mean()
                    if best is None or agree > best[0]:
                        best = (agree, ddx, ddy)
            aligned = shift(new_img, best[1], best[2])
            rec_c = centroids.copy()
            m = interior(new_ref)
            for i in range(16):
                sel = m & (new_ref == i)
                if sel.any():
                    rec_c[i] = np.median(aligned[sel], axis=0)
            cls = classify(aligned, rec_c)
            unexplained = int(((cls != new_ref) & ~explained(new_ref, aligned, rec_c)).sum())
            lines.append('| %s | %d | %d | %d | %d | %d | %d | %d | %d (alignment dx %+d dy %+d) |' % (
                n, len(frames), kinds['old'], kinds['new'], kinds['mixed'], partial, torn, corrupt,
                unexplained, best[1], best[2]))
        lines.append('')
    # Console before/after: thresholded text comparison.
    before, after = stills / '00-console-before.png', stills / '15-console-final.png'
    if before.exists() and after.exists():
        a = sample(before).sum(-1) > 384
        b = sample(after).sum(-1) > 384
        lines += ['Console after the run vs before: %d of 76,800 logical pixels differ (text threshold).' %
                  int((a != b).sum()), '']
    (run / 'compare.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
