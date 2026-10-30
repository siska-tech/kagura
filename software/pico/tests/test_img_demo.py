# SPDX-License-Identifier: Apache-2.0
"""PC test of the pseudo-256-colour picture demo (img_quant.c, img_scene.c).

Builds tests/img_quant_host.c with the host gcc (ASan/UBSan), renders the
procedural scene, quantizes it as the firmware does and checks the result:
RGB444 palettes sharing colour 0 (pixel value 0 shows BACKDROP), cell
palettes 0..15, all 16 palettes used, the picture as displayed close to the
source, determinism. Also checks that send_image.py packs
pixels in the same tile-native layout and frames the payload the way
img_demo.h describes. Needs no NumPy or Pillow.
"""
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from unittest import TestCase, main

HERE = Path(__file__).resolve().parent
PICO = HERE.parent
sys.path.insert(0, str(PICO))
sys.dont_write_bytecode = True
import send_image  # noqa: E402

BUILD = Path(tempfile.mkdtemp(prefix="img_quant_host_"))
BINARY = BUILD / "img_quant_host"
ROUNDS = "1"   # as kagura_img_demo


def setUpModule():
    cc = os.environ.get("CC", "gcc")
    subprocess.run([cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    str(PICO / "img_quant.c"), str(PICO / "img_scene.c"), str(HERE / "img_quant_host.c"),
                    "-lm", "-o", str(BINARY)], check=True)


def run_c(rounds):
    data = subprocess.run([str(BINARY), rounds], capture_output=True, check=True).stdout
    assert len(data) == 230400 + 512 + 1200 + 38400, len(data)
    source, rest = data[:230400], data[230400:]
    return source, list(struct.unpack("<256H", rest[:512])), list(rest[512:1712]), rest[1712:]


def indices(pixels):
    """Tile-native bytes -> 1200 cells x 64 indices, independent of send_image.pack."""
    out = []
    for t in range(1200):
        cell = []
        for i in range(64):
            b = pixels[t * 32 + (i // 8) * 4 + (i % 8) // 2]
            cell.append(b & 15 if i % 2 else b >> 4)
        out.append(cell)
    return out


class PictureTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.palette, cls.cells, cls.pixels = run_c(ROUNDS)

    def test_output_ranges(self):
        self.assertTrue(all(0 <= v <= 0xfff for v in self.palette))
        # Pixel value 0 shows BACKDROP (palette 0 colour 0) in every cell.
        self.assertEqual({self.palette[p * 16] for p in range(16)}, {self.palette[0]})
        self.assertTrue(all(0 <= c <= 15 for c in self.cells))
        self.assertEqual(len(set(self.cells)), 16, "every palette should serve some cells")

    def test_picture_close_to_source(self):
        error = 0
        for t, cell in enumerate(indices(self.pixels)):
            for i, index in enumerate(cell):
                x, y = t % 40 * 8 + i % 8, t // 40 * 8 + i // 8
                v = self.palette[self.cells[t] * 16 + index if index else 0]   # 0 shows BACKDROP
                q = ((v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17)
                o = (y * 320 + x) * 3
                error += sum((a - b) ** 2 for a, b in zip(self.source[o:o + 3], q))
        psnr = 10 * math.log10(255 ** 2 / (error / (76800 * 3)))
        self.assertGreater(psnr, 31.0, "PSNR %.2f dB" % psnr)

    def test_deterministic(self):
        self.assertEqual(run_c("0")[1:], run_c("0")[1:])

    def test_send_image_packs_like_c(self):
        self.assertEqual(send_image.pack(indices(self.pixels)), self.pixels)

    def test_frame_matches_img_demo_h(self):
        header = (PICO / "img_demo.h").read_text()
        magic = re.search(r'#define IMG_MAGIC "(\w+)"', header).group(1).encode()
        parts = [int(n) for n in re.search(r"#define IMG_PAYLOAD \(([\du +]+)\)", header).group(1).replace("u", "").split("+")]
        self.assertEqual((magic, sum(parts)), (send_image.MAGIC, send_image.PAYLOAD))
        data = send_image.frame(self.palette, self.cells, self.pixels)
        self.assertEqual(len(data), 4 + send_image.PAYLOAD + 4)
        payload = data[4:-4]
        self.assertEqual(struct.unpack("<I", data[-4:])[0], zlib.crc32(payload))
        self.assertEqual(payload[512:1712], bytes(self.cells))
        with self.assertRaises(ValueError):
            send_image.frame(self.palette[:255] + [0x1000], self.cells, self.pixels)
        with self.assertRaises(ValueError):
            send_image.frame(self.palette, self.cells[:1199] + [16], self.pixels)


if __name__ == "__main__":
    main()
