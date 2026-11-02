# SPDX-License-Identifier: Apache-2.0
"""Cross-check the C desktop's output with the repository's Python code.

Independent readers of the same bytes:
  * TILE4 export vs the SDK test decoder (test_framebuffer.decode, 320x240
    tile-native) and vs the linear working buffer dumped by kd_headless;
  * sprite data vs KAGURA-UI's Sprite4 (kagura.ui.canvas);
  * the generated font table vs tools/gen_font.py --check.

Usage: python3 -I test_sdk_reference.py PATH/TO/kd_headless
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / 'software/micropython/tests'), str(ROOT / 'software/micropython')]
from test_framebuffer import decode  # noqa: E402
from kagura.ui.canvas import Sprite4  # noqa: E402

HEADLESS = None


def unpack_linear(data):
    out = bytearray(320 * 200)
    for i, b in enumerate(data):
        out[2 * i], out[2 * i + 1] = b >> 4, b & 15
    return out


class SdkReference(TestCase):
    def test_tile4_export_decodes_like_the_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([HEADLESS, '--scenario', tmp], check=True, capture_output=True)
            tiles = (Path(tmp) / 'desktop.tile4').read_bytes()
            linear = (Path(tmp) / 'desktop.linear4').read_bytes()
        self.assertEqual(len(tiles), 32000)
        self.assertEqual(len(linear), 32000)
        # Patterns 0..999 are the 320x200 plane; 1000..1199 stay blank.
        image = decode(tiles + bytes(6400))
        self.assertEqual(bytes(image[:320 * 200]), bytes(unpack_linear(linear)))
        self.assertGreater(len(set(image[:320 * 200])), 8)

    def test_sprite_matches_kagura_ui_sprite4(self):
        for n in range(2):
            out = subprocess.run([HEADLESS, '--sprite', str(n)], check=True,
                                 capture_output=True, text=True).stdout.split()
            self.assertEqual(out[0], 'hex')
            sprite = Sprite4(16, 16, bytearray.fromhex(out[1]))
            rows = out[2:]
            self.assertEqual(len(rows), 16)
            for y in range(16):
                for x in range(16):
                    self.assertEqual(sprite.get(x, y), int(rows[y][x], 16))
            self.assertEqual(bytes(sprite.export()).hex(), out[1])

    def test_font_table_is_generated(self):
        subprocess.run([sys.executable, '-I', str(EXP / 'tools/gen_font.py'), '--check'],
                       check=True, capture_output=True)


if __name__ == '__main__':
    HEADLESS = str(Path(sys.argv.pop(1)).resolve())
    main()
