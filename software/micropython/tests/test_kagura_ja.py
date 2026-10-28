# SPDX-License-Identifier: Apache-2.0
"""Host tests for kagura_ja and tools/gen-kagura-ja-font.py.

python -I software/micropython/tests/test_kagura_ja.py
With MISAKI_ZIP=path/to/misaki_bdf_2021-05-05.zip the committed font is also
regenerated from the pinned archive and compared byte for byte.
"""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_driver as T  # installs the fake machine/rp2 modules

from kagura import Kagura
from kagura import regs as R
from kagura_ja import Font, TextLayer, _tile

spec = importlib.util.spec_from_file_location("gen_font", T.ROOT / "tools/gen-kagura-ja-font.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
FONT_FILE = T.ROOT / "software/micropython/fonts/misaki8.kfnt"

# Definitions copied from misaki_gothic.bdf 2021-05-05.
REAL_GLYPHS = """\
STARTCHAR A
ENCODING 65
SWIDTH 500 0
DWIDTH 4 0
BBX 3 6 0 0
BITMAP
40
A0
A0
E0
A0
A0
ENDCHAR
STARTCHAR uni304C
ENCODING 12364
SWIDTH 1000 0
DWIDTH 8 0
BBX 7 7 0 -1
BITMAP
2A
20
F4
2A
4A
48
B0
ENDCHAR
STARTCHAR uniFF9E
ENCODING 65438
SWIDTH 500 0
DWIDTH 4 0
BBX 3 1 0 5
BITMAP
A0
ENDCHAR
STARTCHAR full
ENCODING 9608
SWIDTH 1000 0
DWIDTH 8 0
BBX 8 8 0 -2
BITMAP
FF
81
81
81
81
81
81
FF
ENDCHAR
"""


def bdf(glyphs=REAL_GLYPHS, ascent=6):
    return ("STARTFONT 2.1\nFONTBOUNDINGBOX 8 8 0 -2\nFONT_DESCENT 2\n"
            "FONT_ASCENT %d\nCHARS 0\n%sENDFONT\n" % (ascent, glyphs))


def glyph(code, rows, width=8, bbx=None):
    w, h, x, y = bbx or (8, len(rows), 0, 6 - len(rows))
    return ("STARTCHAR c%X\nENCODING %d\nDWIDTH %d 0\nBBX %d %d %d %d\nBITMAP\n%sENDCHAR\n"
            % (code, code, width, w, h, x, y, "".join("%02X\n" % r for r in rows)))


def rows(text):
    return bytes(int(line.replace(".", "0").replace("#", "1"), 2) for line in text.split())


class ConverterTests(unittest.TestCase):
    def test_position_halfwidth_and_dakuten(self):
        g = gen.parse_bdf(bdf())
        # Half-width: 4 px box centred, so the BBX moves right by 2 px.
        self.assertEqual(g[0x41], rows("...#.... ..#.#... ..#.#... ..###... "
                                       "..#.#... ..#.#... ........ ........"))
        self.assertEqual(g[0x304C], rows("..#.#.#. ..#..... ####.#.. ..#.#.#. "
                                         ".#..#.#. .#..#... #.##.... ........"))
        self.assertEqual(g[0xFF9E], rows("..#.#... " + "........ " * 7))
        self.assertEqual(g[0x2588], bytes((0xFF,) + (0x81,) * 6 + (0xFF,)))

    def test_encode_layout(self):
        data = gen.encode({0x3042: bytes(range(8)), 0x41: bytes(8)})
        self.assertEqual(data[:8], b"KJ8F\x01\x00\x02\x00")
        self.assertEqual(data[8:18], b"\x41\x00" + bytes(8))
        self.assertEqual(data[18:], b"\x42\x30" + bytes(range(8)))

    def test_rejects_malformed_bdf(self):
        cases = (
            glyph(0x41, (0xF0,), width=4, bbx=(4, 1, 1, 0)),  # past 4 px advance
            glyph(0x41, (0xFF,), width=6),
            glyph(0x41, (0xFF,)) + glyph(0x41, (0xFF,)),
            glyph(0x41, (0xFF,) * 9, bbx=(8, 9, 0, -2)),
            glyph(0x41, (0xFF,)).replace("ENDCHAR\n", ""),
            "STARTCHAR x\nENCODING 65\nBITMAP\nENDCHAR\n",
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises((ValueError, StopIteration)):
                gen.parse_bdf(bdf(text))
        with self.assertRaises(ValueError):
            gen.parse_bdf(bdf(""))
        self.assertNotIn(0x1F600, gen.parse_bdf(bdf(glyph(0x1F600, (1,)) + glyph(0x41, (1,)))))

    def test_archive_and_bdf_hashes_are_checked(self):
        text = bdf().encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr(gen.BDF_NAME, text)
        archive = buffer.getvalue()
        good = (hashlib.sha256(archive).hexdigest(), hashlib.sha256(text).hexdigest())
        self.assertEqual(gen.convert_archive(archive, *good), gen.encode(gen.parse_bdf(bdf())))
        with self.assertRaisesRegex(ValueError, "archive"):
            gen.convert_archive(archive, "0" * 64, good[1])
        with self.assertRaisesRegex(ValueError, "bdf"):
            gen.convert_archive(archive, good[0], "0" * 64)
        with self.assertRaisesRegex(ValueError, "archive"):
            gen.convert_archive(archive)  # not the pinned upstream file

    def test_committed_font_is_well_formed(self):
        data = FONT_FILE.read_bytes()
        count = struct.unpack_from("<H", data, 6)[0]
        self.assertEqual(data[:6], b"KJ8F\x01\x00")
        self.assertEqual((count, len(data)), (7171, 8 + count * 10))
        codes = [struct.unpack_from("<H", data, 8 + i * 10)[0] for i in range(count)]
        self.assertEqual(codes, sorted(set(codes)))
        for ch in "あア神楽A?、！ﾞ":
            self.assertIn(ord(ch), codes)

    def test_committed_font_regenerates(self):
        archive = os.environ.get("MISAKI_ZIP")
        if not archive:
            self.skipTest("set MISAKI_ZIP to the pinned misaki_bdf_2021-05-05.zip")
        self.assertEqual(gen.convert_archive(Path(archive).read_bytes()), FONT_FILE.read_bytes())


class FontFileMixin:
    def write_font(self, data):
        path = Path(self.tmp.name) / ("f%d.kfnt" % len(os.listdir(self.tmp.name)))
        path.write_bytes(data)
        return str(path)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()


class FontTests(FontFileMixin, unittest.TestCase):
    def test_lookup(self):
        data = gen.encode({c: bytes((c & 255,)) * 8 for c in (0x20, 0x41, 0x3042, 0xFFE5)})
        with Font(self.write_font(data)) as font:
            self.assertEqual(font.count, 4)
            for code in (0x20, 0x41, 0x3042, 0xFFE5):
                self.assertEqual(font.glyph(code), bytes((code & 255,)) * 8)
            for code in (0, 0x42, 0x3041, 0xFFFF, 0x1F600, -1):
                self.assertIsNone(font.glyph(code))
        with self.assertRaisesRegex(ValueError, "closed"):
            font.glyph(0x41)
        font.close()  # idempotent

    def test_committed_font_lookup(self):
        with Font(str(FONT_FILE)) as font:
            self.assertEqual(font.glyph(ord("が")), gen.parse_bdf(bdf())[0x304C])
            self.assertIsNone(font.glyph(0x4E02))  # not in Misaki

    def test_invalid_and_missing_files(self):
        good = gen.encode({0x41: bytes(8), 0x42: bytes(8)})
        cases = {
            "magic": b"KJ8X" + good[4:],
            "format": good[:4] + b"\x02\x00" + good[6:],
            "truncated": good[:-1],
            "extra": good + b"\x00",
            "empty": b"KJ8F\x01\x00\x00\x00",
            "short header": b"KJ8F\x01",
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                Font(self.write_font(data))
        with self.assertRaises(OSError):
            Font(str(Path(self.tmp.name) / "missing.kfnt"))


# Distinct, non-blank synthetic glyphs for capacity tests.
CJK = [chr(0x4E00 + i) for i in range(300)]


class LayerTests(FontFileMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        glyphs = gen.parse_bdf(bdf())
        glyphs[0x20] = glyphs[0x3000] = bytes(8)
        glyphs[0x3F] = rows("...#.... ..#.#... ....#... ...#.... "
                            "........ ...#.... ........ ........")
        glyphs[0x30A2] = bytes((0x7E,) * 8)  # ア
        for i, ch in enumerate(CJK):
            glyphs[ord(ch)] = bytes((i & 255, i >> 8 | 0x80)) + bytes(6)
        self.glyphs = glyphs
        self.font = Font(self.write_font(gen.encode(glyphs)))
        self.model = T.RegisterModel()
        self.d = Kagura(self.model, timeout_us=500).probe()

    def tearDown(self):
        self.font.close()
        super().tearDown()

    def layer(self, **kw):
        layer = TextLayer(self.d, self.font, **kw)
        layer.clear()
        return layer

    def cell(self, col, row):
        address = 0x8000 + (row * 64 + col) * 2
        return int.from_bytes(self.model.memory[address:address + 2], "little")

    def tile(self, index):
        return bytes(self.model.memory[index * 32:index * 32 + 32])

    def test_tile_packing(self):
        self.assertEqual(_tile(b"\x80\x01" + bytes(6))[:8], b"\x10\x00\x00\x00\x00\x00\x00\x01")

    def test_mixed_text(self):
        layer = self.layer(palette=3)
        self.assertEqual(layer.text("がアA一 が", col=1, row=2), (7, 2))
        layer.flush()
        self.assertEqual([self.cell(c, 2) & 1023 for c in range(8)],
                         [128, 129, 130, 131, 132, 128, 129, 128])
        self.assertEqual(self.cell(1, 2) >> 10, 3)
        self.assertEqual(self.cell(0, 2), 128 | 3 << 10)  # blank from clear()
        self.assertEqual(self.tile(129), _tile(self.glyphs[0x304C]))
        self.assertEqual(self.tile(131), _tile(self.glyphs[0x41]))
        self.assertEqual(self.tile(128), bytes(32))
        self.assertEqual(layer.glyphs, 4)
        self.assertEqual(self.d.busy, 0)

    def test_missing_and_control_characters_share_question_tile(self):
        layer = self.layer()
        layer.text("龠\t😀?", col=0, row=0)  # U+9FA0 is not in the test font
        layer.flush()
        self.assertEqual({self.cell(c, 0) for c in range(4)}, {129})
        self.assertEqual(self.tile(129), _tile(self.glyphs[0x3F]))
        self.assertEqual(layer.glyphs, 1)

    def test_newline_wrap_and_clip(self):
        layer = self.layer(map_x=10, map_y=5, width=4, height=2)
        # B is not in the test font, so it becomes '?'.
        self.assertEqual(layer.text("AB\nがアA一丁七", col=1), (2, 2))
        layer.flush()
        A, question, ga, a, one = 129, 130, 131, 132, 133
        self.assertEqual([self.cell(10 + c, 5) for c in range(4)], [128, A, question, 128])
        self.assertEqual([self.cell(10 + c, 6) for c in range(4)], [ga, a, A, one])
        self.assertEqual(self.cell(10, 7), 0)  # row 2 is clipped: never written
        self.assertEqual(layer.glyphs, 5)  # clipped 丁七 took no tiles
        # Cursor carries over: the next character wraps to a clipped row.
        self.assertEqual(layer.text("丁", *layer.text("", 4, 1)), (1, 2))
        calls = len(self.model.calls)
        self.assertEqual(layer.text("ABCDEF", col=-2, row=-1), (4, -1))
        self.assertEqual(len(self.model.calls), calls)  # fully clipped
        self.assertEqual(layer.text("一AB\rが", col=-1, row=0), (1, 0))
        layer.flush()
        self.assertEqual([self.cell(10 + c, 5) for c in range(4)], [ga, question, question, 128])
        self.assertEqual(self.cell(9, 5), 0)
        self.assertEqual(self.model.memory[0x8000 + (5 * 64 + 14) * 2], 0)

    def test_tile_reuse(self):
        layer = self.layer()
        layer.text("一二一二")
        calls = len(self.model.calls)
        layer.text("二一", row=1)
        self.assertEqual(layer.glyphs, 2)
        layer.flush()
        self.assertEqual([self.cell(c, 1) for c in range(2)], [130, 129])
        tile_writes = [c for c in self.model.calls[calls:] if c[0] == R.REG_VRAM_ADDR_L
                       and int.from_bytes(c[1], "little") < 0x8000]
        self.assertEqual(tile_writes, [])

    def test_capacity_boundary_and_overflow_leaves_display(self):
        layer = self.layer()
        layer.text("".join(CJK[:200]))
        layer.text("".join(CJK[150:255]), row=10)
        self.assertEqual(layer.glyphs, 255)
        layer.flush()
        self.assertEqual(self.cell(24, 12), 128 + 255)  # tile 383 is the last
        before = bytes(self.model.memory)
        calls = len(self.model.calls)
        with self.assertRaises(MemoryError):
            layer.text("一" + CJK[255], row=20)
        self.assertEqual(len(self.model.calls), calls)  # nothing was sent
        layer.flush()
        self.assertEqual(bytes(self.model.memory), before)
        self.assertEqual(layer.glyphs, 255)
        layer.text("一 " + CJK[254], row=20)  # registered glyphs need no tile
        with self.assertRaises(MemoryError):
            layer.text("龠", row=21)  # '?' itself would be a new tile
        layer.flush()
        self.assertEqual([self.cell(c, 20) for c in range(3)], [129, 128, 383])
        self.assertEqual(self.cell(0, 21), 128)
        self.assertEqual(self.d.busy, 0)

    def test_single_call_overflow(self):
        layer = self.layer(tile_count=4)
        with self.assertRaisesRegex(MemoryError, "4 glyph tiles, 3"):
            layer.text("".join(CJK[:4]))
        self.assertEqual(layer.glyphs, 0)
        layer.text("".join(CJK[:3]) + "  ")
        self.assertEqual(layer.glyphs, 3)

    def test_clear_fences_then_reregisters(self):
        layer = self.layer()
        layer.text("一二三", row=1)
        layer.flush()
        tag = self.model.reg[R.REG_DONE_TAG]
        layer.clear()
        self.assertNotEqual(self.model.reg[R.REG_DONE_TAG], tag)  # FENCE completed
        self.assertEqual(layer.glyphs, 0)
        self.assertEqual(self.cell(0, 1), 128)
        layer.text("三")
        layer.flush()
        self.assertEqual(self.cell(0, 0), 129)
        self.assertEqual(self.tile(129), _tile(self.glyphs[0x4E09]))

    def test_requires_clear_and_recovers_after_transfer_error(self):
        layer = TextLayer(self.d, self.font)
        with self.assertRaisesRegex(RuntimeError, "clear"):
            layer.text("A")
        layer.clear()
        write = self.model.write
        def fail(offset, data, inc=False):
            if offset == R.REG_VRAM_WRITE:
                raise OSError("link lost")
            return write(offset, data, inc)
        self.model.write = fail
        with self.assertRaises(OSError):
            layer.text("A")
        self.model.write = write
        self.assertEqual(self.d.busy, 0)
        with self.assertRaises(RuntimeError):
            layer.text("A")
        layer.clear()
        layer.text("A")

    def test_validation(self):
        self.assertEqual(TextLayer(self.d, self.font).height, 22)
        bad = ({"tile_base": 900}, {"tile_count": 1}, {"width": 41, "map_x": 24},
               {"map_y": 10, "height": 23}, {"palette": 16}, {"width": 0})
        for kw in bad:
            with self.subTest(kw), self.assertRaises(ValueError):
                TextLayer(self.d, self.font, **kw)
        layer = self.layer()
        with self.assertRaises(TypeError):
            layer.text(b"A")


class MenuExampleTests(unittest.TestCase):
    def test_menu_runs_with_committed_font(self):
        sys.path.insert(0, str(T.ROOT / "software/micropython/examples"))
        import ja_menu
        source = (T.ROOT / "software/micropython/examples/ja_menu.py").read_text(encoding="utf-8")
        with Font(str(FONT_FILE)) as font:
            missing = {c for c in source if ord(c) > 0x7F and font.glyph(ord(c)) is None}
        self.assertEqual(missing, set())
        model = T.RegisterModel()
        d = Kagura(model, timeout_us=500).probe()
        with mock.patch.object(sys, "stdin", io.StringIO("s\x1b[Bw\x1b[B\r")):
            self.assertEqual(ja_menu.run(None, d, font_path=str(FONT_FILE)), 2)
        self.assertEqual(model.memory[0x9400 + 17 * 2:0x9400 + 18 * 2], b"\xff\x0f")
        # Title starts at column 2 with 神 in palette 1; the marker sits on item 2.
        self.assertEqual(int.from_bytes(model.memory[0x8000 + (64 + 2) * 2:][:2], "little"),
                         129 | 1 << 10)
        marker = int.from_bytes(model.memory[0x8000 + (8 * 64 + 2) * 2:][:2], "little")
        self.assertNotEqual(marker & 1023, 128)
        self.assertEqual(d.busy, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
