# SPDX-License-Identifier: Apache-2.0
"""Convert a picture to KAGURA pseudo-256 colours and send it to `imgdemo recv`.

16 palettes of 16 RGB444 colours, one palette per 8x8 cell, chosen by the same
steps as img_quant.c (colour 0 shared by all palettes, because pixel value 0
shows BACKDROP) (cell grouping, per-palette k-means, cell reassignment,
4x4 ordered dither), with more iterations since the PC is fast. The picture is
scaled to cover 320x240 and centre-cropped. Needs Pillow and NumPy, and
pyserial to send:

    uv run --with pillow --with numpy --with pyserial software/pico/send_image.py --port COM9 photo.jpg
    uv run --with pillow --with numpy software/pico/send_image.py --preview out.png photo.jpg

The wire format is described in img_demo.h. pack() and frame() need neither
NumPy nor Pillow, so the tests can import them.
"""
import argparse
import struct
import sys
import time
import zlib

MAGIC = b'KIMG'
PAYLOAD = 512 + 1200 + 38400
WEIGHT = (2, 4, 3)   # R, G, B weights of the squared colour distance, as img_quant.c
BAYER = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)


def pack(index):
    """1200 cells x 64 palette indices (row-major in the cell) -> 38400 tile-native bytes."""
    out = bytearray(38400)
    for t in range(1200):
        cell = index[t]
        for i in range(0, 64, 2):
            out[t * 32 + i // 2] = cell[i] << 4 | cell[i + 1]
    return bytes(out)


def frame(palette, cells, pixels):
    """MAGIC, payload and its CRC-32, as `imgdemo recv` reads them."""
    if len(palette) != 256 or any(not 0 <= v <= 0xfff for v in palette):
        raise ValueError('palette: 256 RGB444 words')
    if len(cells) != 1200 or any(not 0 <= c <= 15 for c in cells):
        raise ValueError('cells: 1200 palette numbers 0..15')
    if len(pixels) != 38400:
        raise ValueError('pixels: 38400 bytes')
    payload = struct.pack('<256H', *palette) + bytes(cells) + bytes(pixels)
    return MAGIC + payload + struct.pack('<I', zlib.crc32(payload))


def load(path):
    from PIL import Image
    import numpy as np
    img = Image.open(path).convert('RGB')
    scale = max(320 / img.width, 240 / img.height)
    w, h = max(320, round(img.width * scale)), max(240, round(img.height * scale))
    img = img.resize((w, h), Image.LANCZOS)
    left, top = (w - 320) // 2, (h - 240) // 2
    return np.asarray(img.crop((left, top, left + 320, top + 240)), dtype=np.int32)


def quantize(rgb, rounds=3, iterations=10):
    """rgb (240, 320, 3) -> (palette words, cell palettes, cell indices (1200, 64))."""
    import numpy as np
    weight = np.array(WEIGHT)
    tiles = rgb.reshape(30, 8, 40, 8, 3).transpose(0, 2, 1, 3, 4).reshape(1200, 64, 3)

    def dist(a, b):   # a (..., 3), b (k, 3) -> (..., k)
        return ((a[..., None, :] - b) ** 2 * weight).sum(-1)

    def farthest(points, k, first):
        seeds = list(first)
        best = dist(points, np.array(seeds))[:, 0]
        while len(seeds) < k:
            i = int(best.argmax())
            if best[i] <= 0:
                seeds.append(seeds[-1])
                continue
            seeds.append(points[i])
            best = np.minimum(best, dist(points, points[i:i + 1])[:, 0])
        return np.array(seeds)

    def kmeans(points, centre, rounds, fixed=0):
        """The first `fixed` centres stay put."""
        for _ in range(rounds):
            label = dist(points, centre).argmin(-1)
            for k in range(fixed, len(centre)):
                member = points[label == k]
                if len(member):
                    centre[k] = np.round(member.mean(0))
        return centre

    mean = np.round(tiles.mean(1)).astype(np.int32)
    first = mean[dist(mean, np.round(mean.mean(0))[None])[:, 0].argmax()]
    group = kmeans(mean, farthest(mean, 16, [first]).astype(np.int32), 12)
    cells = dist(mean, group).argmin(-1)
    # Pixel value 0 is transparent and shows BACKDROP (palette 0 colour 0), so
    # colour 0 is the same in every palette: the darkest cell mean.
    shared = mean[(mean * np.array((2, 5, 1))).sum(1).argmin()]
    centre = np.zeros((16, 16, 3), np.int32)
    centre[:, 0] = shared
    for p in range(16):
        points = tiles[cells == p].reshape(-1, 3)
        if len(points):
            centre[p] = kmeans(points, farthest(points, 16, [shared]).astype(np.int32), iterations, 1)
    for _ in range(rounds):
        err = np.stack([dist(tiles, centre[p]).min(-1).sum(-1) for p in range(16)], 1)
        cells = err.argmin(1)
        for p in range(16):
            points = tiles[cells == p].reshape(-1, 3)
            if len(points):
                centre[p] = kmeans(points, centre[p], iterations // 2, 1)
    level = (centre * 15 + 127) // 255
    colour = level * 17
    palette = [int(v) for v in (level[..., 0] << 8 | level[..., 1] << 4 | level[..., 2]).reshape(256)]
    i = np.arange(64)
    offset = ((np.array(BAYER)[(i // 8 & 3) * 4 + (i % 8 & 3)] * 2 - 15) * 17 // 32)[:, None]
    target = np.clip(tiles + offset, 0, 255)
    index = np.stack([dist(target[t], colour[cells[t]]).argmin(-1) for t in range(1200)])
    return palette, [int(c) for c in cells], index.tolist()


def preview(path, palette, cells, index):
    from PIL import Image
    img = Image.new('RGB', (320, 240))
    for t in range(1200):
        for i in range(64):
            v = palette[cells[t] * 16 + index[t][i] if index[t][i] else 0]   # 0 shows BACKDROP
            img.putpixel((t % 40 * 8 + i % 8, t // 40 * 8 + i // 8),
                         ((v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17))
    img.resize((640, 480), Image.NEAREST).save(path)


def send(port, data, setup, timeout=30):
    import serial
    with serial.Serial(port, 115200, timeout=0.2) as link:
        def lines(until):
            text, end = b'', time.monotonic() + timeout
            while time.monotonic() < end:
                text += link.read(4096)
                for want in until:
                    if want in text:
                        return text.decode(errors='replace')
            raise TimeoutError('no %r from the Pico; got %r' % (until, text[-200:]))
        for command in setup:
            link.write(command.encode() + b'\r')
            print(lines((b'OK', b'ERR')).strip())
        link.reset_input_buffer()
        link.write(b'imgdemo recv\r')
        lines((b'IMG READY',))
        link.write(data)
        result = lines((b'IMG DONE', b'IMG FAIL', b'ERR'))
        print(result.strip())
        return 'IMG DONE' in result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('image')
    parser.add_argument('--port', help='Pico serial port running the kagura_host firmware')
    parser.add_argument('--preview', help='write the converted picture (640x480 PNG) here')
    parser.add_argument('--no-setup', action='store_true', help="skip 'mode qspi' and 'div 2'")
    args = parser.parse_args()
    if not args.port and not args.preview:
        parser.error('give --port, --preview or both')
    start = time.monotonic()
    palette, cells, index = quantize(load(args.image))
    print('converted in %.1f s, %d palettes used' % (time.monotonic() - start, len(set(cells))))
    if args.preview:
        preview(args.preview, palette, cells, index)
    if args.port:
        ok = send(args.port, frame(palette, cells, pack(index)), [] if args.no_setup else ['mode qspi', 'div 2'])
        sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
