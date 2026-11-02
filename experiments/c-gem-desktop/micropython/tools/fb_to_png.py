# SPDX-License-Identifier: Apache-2.0
"""Converts raw desktop snapshots (Desktop.snapshot: 320x200, 4bpp, rows of
160 bytes, even x in the high nibble) to indexed PNGs in the desktop palette,
plus a montage of all of them. CPython, standard library only.

  python3 -I tools/fb_to_png.py DIR [--scale 2] [--ref240 OUT]   (OUT: 320x240 HDMI references)
"""
import struct
import sys
import zlib
from pathlib import Path

# src/kd_gfx.c kd_palette_rgb444
PALETTE = (0x0A5, 0x000, 0xFFF, 0xBBB, 0x666, 0x23C, 0xD22, 0xEC2,
           0x063, 0x2BC, 0xC4C, 0x842, 0x8AF, 0x8E8, 0xF82, 0xFFC)
W, H = 320, 200


def pixels(raw):
    rows = []
    for y in range(H):
        row = bytearray()
        for b in raw[y * 160:(y + 1) * 160]:
            row += bytes((b >> 4, b & 15))
        rows.append(row)
    return rows


def write_png(path, rows, scale):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    plte = b''.join(bytes(((c >> 8) * 17, (c >> 4 & 15) * 17, (c & 15) * 17)) for c in PALETTE)
    body = bytearray()
    for row in rows:
        wide = bytes(v for v in row for _ in range(scale))
        for _ in range(scale):
            body += b'\0' + wide
    w, h = len(rows[0]) * scale, len(rows) * scale
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 3, 0, 0, 0)) +
           chunk(b'PLTE', plte) + chunk(b'IDAT', zlib.compress(bytes(body), 9)) + chunk(b'IEND', b''))
    Path(path).write_bytes(png)


def main():
    folder = Path(sys.argv[1])
    scale = int(sys.argv[sys.argv.index('--scale') + 1]) if '--scale' in sys.argv else 2
    shots = sorted(folder.glob('*.raw'))
    images = []
    for raw in shots:
        rows = pixels(raw.read_bytes())
        write_png(raw.with_suffix('.png'), rows, scale)
        images.append(rows)
    cols, gap = 2, 4   # montage at 1x, colour 1 (black) between shots
    n_rows = (len(images) + cols - 1) // cols
    mw, mh = cols * W + (cols - 1) * gap, n_rows * H + (n_rows - 1) * gap
    canvas = [bytearray([1]) * mw for _ in range(mh)]
    for k, rows in enumerate(images):
        ox, oy = (k % cols) * (W + gap), (k // cols) * (H + gap)
        for y, row in enumerate(rows):
            canvas[oy + y][ox:ox + W] = row
    write_png(folder / 'montage.png', canvas, 1)
    if '--ref240' in sys.argv:   # 320x240 HDMI references: plane centred (SCROLL_Y 236), border colour 0
        out = Path(sys.argv[sys.argv.index('--ref240') + 1])
        out.mkdir(parents=True, exist_ok=True)
        for raw, rows in zip(shots, images):
            frame = [bytearray(W) for _ in range(20)] + rows + [bytearray(W) for _ in range(20)]
            write_png(out / (raw.stem + '.png'), frame, 1)
    print('%d snapshots -> PNG, montage %dx%d' % (len(images), mw, mh))


if __name__ == '__main__':
    main()
