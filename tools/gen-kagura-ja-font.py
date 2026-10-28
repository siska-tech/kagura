#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Convert Misaki Gothic (2021-05-05) into the kagura_ja KJ8F font file.

    python3 -I tools/gen-kagura-ja-font.py misaki_bdf_2021-05-05.zip \
        software/micropython/fonts/misaki8.kfnt [--check]

The archive is https://littlelimit.net/arc/misaki/misaki_bdf_2021-05-05.zip
(Misaki font, Copyright (C) 2002-2021 Num Kadoma; see
software/micropython/fonts/README.md). Both the archive and misaki_gothic.bdf
inside it must match the pinned SHA-256. --check compares instead of writing.

KJ8F, all numbers little endian:
  header  "KJ8F", u16 format (1), u16 glyph count
  record  u16 Unicode BMP code, 8 glyph rows; sorted by code, no duplicates
Rows run top to bottom, bit 7 is the leftmost pixel. Every glyph is an 8x8
cell; 4 px (half-width) glyphs are centred in it.
"""
import hashlib
import io
import struct
import sys
import zipfile

ARCHIVE_SHA256 = "a275f173cf5935890f84d3e65d05b1bf73028e4d4bf41cb3de0ef3b5ebe8e217"
BDF_NAME = "misaki_gothic.bdf"
BDF_SHA256 = "28a8745552c844f7c73f11bdf4470225f5e08645a98c5404b2e25bb326a5cabd"
MAGIC = b"KJ8F"
FORMAT = 1


def parse_bdf(text):
    """Return {code: rows} with every glyph placed in an 8x8 cell."""
    lines = iter(text.splitlines())
    ascent = None
    glyphs = {}
    for line in lines:
        if line.startswith("FONT_ASCENT "):
            ascent = int(line.split()[1])
        if not line.startswith("STARTCHAR"):
            continue
        if ascent is None:
            raise ValueError("FONT_ASCENT missing before glyphs")
        name = line[10:].strip()
        code = width = bbx = None
        for line in lines:
            fields = line.split()
            key = fields[0] if fields else ""
            if key == "ENCODING":
                code = int(fields[1])
            elif key == "DWIDTH":
                width = int(fields[1])
            elif key == "BBX":
                bbx = tuple(int(v) for v in fields[1:5])
            elif key == "BITMAP":
                break
        else:
            raise ValueError("unterminated glyph %s" % name)
        if code is None or width is None or bbx is None:
            raise ValueError("glyph %s lacks ENCODING/DWIDTH/BBX" % name)
        w, h, xoff, yoff = bbx
        if width not in (4, 8):
            raise ValueError("glyph U+%04X width %d is not 4 or 8" % (code, width))
        # Half-width glyphs keep their own 4 px box, centred in the cell.
        shift = (8 - width) // 2 + xoff
        top = ascent - (yoff + h)
        if xoff < 0 or xoff + w > width or top < 0 or top + h > 8:
            raise ValueError("glyph U+%04X is outside its 8x8 cell" % code)
        rows = bytearray(8)
        for r in range(h):
            bits = next(lines).strip()
            if len(bits) != 2:
                raise ValueError("glyph U+%04X bitmap row %r" % (code, bits))
            rows[top + r] = int(bits, 16) >> shift
        if next(lines, "").strip() != "ENDCHAR":
            raise ValueError("glyph U+%04X has extra bitmap rows" % code)
        if not 0 <= code <= 0xFFFF:
            continue  # KJ8F stores BMP codes only
        if code in glyphs:
            raise ValueError("duplicate glyph U+%04X" % code)
        glyphs[code] = bytes(rows)
    if not glyphs:
        raise ValueError("no glyphs")
    return glyphs


def encode(glyphs):
    if not 0 < len(glyphs) <= 0xFFFF:
        raise ValueError("glyph count")
    out = bytearray(MAGIC + struct.pack("<HH", FORMAT, len(glyphs)))
    for code in sorted(glyphs):
        rows = glyphs[code]
        if len(rows) != 8:
            raise ValueError("glyph U+%04X needs 8 rows" % code)
        out += struct.pack("<H", code) + rows
    return bytes(out)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def convert_archive(archive, archive_sha256=ARCHIVE_SHA256, bdf_sha256=BDF_SHA256):
    if _sha256(archive) != archive_sha256:
        raise ValueError("archive SHA-256 mismatch; expected misaki_bdf_2021-05-05.zip")
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        bdf = z.read(BDF_NAME)
    if _sha256(bdf) != bdf_sha256:
        raise ValueError(BDF_NAME + " SHA-256 mismatch")
    return encode(parse_bdf(bdf.decode("ascii")))


def main(argv):
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if len(args) != 2:
        sys.exit(__doc__)
    with open(args[0], "rb") as f:
        data = convert_archive(f.read())
    if check:
        with open(args[1], "rb") as f:
            if f.read() != data:
                sys.exit(args[1] + " differs from the regenerated font")
        print("%s matches (%d glyphs)" % (args[1], (len(data) - 8) // 10))
    else:
        with open(args[1], "wb") as f:
            f.write(data)
        print("wrote %s (%d glyphs, %d bytes)" % (args[1], (len(data) - 8) // 10, len(data)))


if __name__ == "__main__":
    main(sys.argv[1:])
