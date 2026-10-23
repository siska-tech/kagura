#!/usr/bin/env python3
"""Generate the shooter demo's tile art (8x8, 4bpp) for kagura_demo_sequencer.

Writes rtl/core/kagura_demo_art.sv (registered ROM, one 32-bit word per tile
row, pixel 0 in bits 31:28) and sim/tests/demo_art.hex (the same words for the
testbench model). Tiles:
  0 blank, 1..5 background stars, 6 streak star sprite, 7 player shot,
  8 enemy shot, 9..10 engine flame, 12..15 ship, 16..23 enemy A (two frames),
  24..31 enemy B (two frames), 32..47 planet (4x4 tiles, row-major),
  48..58 title font K A G U R - 9 D E M O (colour 1 with a colour 2 shadow).
"""
from pathlib import Path
import math

ROOT = Path(__file__).resolve().parent.parent
TILES = 64


def grid(rows, width):
    assert len(rows) <= width, rows
    out = []
    for r in rows + ["." * width] * (width - len(rows)):
        assert len(r) == width, r
        out.append([0 if c == "." else int(c, 16) for c in r])
    return out


def mirrored(halves):
    return [h + h[::-1] for h in halves]


def split16(g):
    """16x16 grid -> four 8x8 tiles: top-left, top-right, bottom-left, bottom-right."""
    return [[row[x0:x0 + 8] for row in g[y0:y0 + 8]] for y0 in (0, 8) for x0 in (0, 8)]


tiles = [grid([], 8) for _ in range(TILES)]
tiles[1] = grid(["........", "........", "........", "........", "...3...."], 8)
tiles[2] = grid(["........", "........", ".....4.."], 8)
tiles[3] = grid(["........", "........", "........", "...4....", "..454...", "...4...."], 8)
tiles[4] = grid(["........", "........", "........", "........", ".....6..", "....666.", ".....6.."], 8)
tiles[5] = grid(["........", "........", "..7....."], 8)
tiles[6] = grid(["........", "...3....", "...4....", "...4....", "...5....", "...5...."], 8)
tiles[7] = grid(["...11...", "..2112..", "..2112..", "..3223..", "...33...", "...33..."], 8)
tiles[8] = grid(["........", "...44...", "..4554..", "..4554..", "...44..."], 8)
tiles[9] = grid(["...77...", "..7667..", "..6556..", "...55..."], 8)
tiles[10] = grid(["...77...", "..7667..", "..6556..", "..6556..", "...55...", "...55...", "....5..."], 8)

ship = grid([
    ".......11.......",
    "......1221......",
    "......1441......",
    ".....124421.....",
    ".....124421.....",
    "....12244221....",
    "....12222221....",
    "...1222332221...",
    ".5.1223333221.5.",
    ".51222333322215.",
    "5122233333322215",
    "5122222332222215",
    "5112211331122115",
    ".11.1.1331.1.11.",
    "....5..55..5....",
], 16)
enemy_a = [
    grid(mirrored(["..1.....", "...1....", "...2111.", "..211111", ".2113311", ".2114511",
                   "21111111", "21212222", "2.211111", "2.21....", "..2.....", "...22..."]), 16),
    grid(mirrored(["..1.....", "...1....", "...2111.", "..211111", ".2113311", ".2114511",
                   "21111111", "21212222", "..211111", ".21.....", "2......."]), 16),
]
enemy_b = [
    grid(mirrored(["......11", ".....111", "....1111", "...11111", "..114511", "..113311",
                   "..111111", "...2.2.2", "..2.2..2", ".2..2...", "2..2...."]), 16),
    grid(mirrored(["......11", ".....111", "....1111", "...11111", "..114511", "..113311",
                   "..111111", "...2.2.2", "...2.2.2", "..2..2.2", "...2..2."]), 16),
]
for base, art in [(12, ship), (16, enemy_a[0]), (20, enemy_a[1]), (24, enemy_b[0]), (28, enemy_b[1])]:
    tiles[base:base + 4] = split16(art)

# Planet: banded sphere lit from the upper left, colours 8 (dark) .. 12.
planet = [[0] * 32 for _ in range(32)]
for gy in range(32):
    for gx in range(32):
        dx, dy = gx - 15.5, gy - 15.5
        if dx * dx + dy * dy > 15.5 * 15.5:
            continue
        shade = 4 - min(4, int(math.hypot(gx - 9, gy - 9) / 6))
        if int((gy + 0.3 * gx) / 5) % 3 == 1:
            shade = max(0, shade - 1)
        if dx * dx + dy * dy > 13.5 * 13.5:
            shade = min(shade, 1)
        planet[gy][gx] = 8 + shade
for ty in range(4):
    for tx in range(4):
        tiles[32 + ty * 4 + tx] = [row[tx * 8:tx * 8 + 8] for row in planet[ty * 8:ty * 8 + 8]]

# 5x7 font at columns 1..5, rows 0..6; the shadow is the glyph moved by (1,1).
FONT = {
    "K": ["X...X", "X..X.", "X.X..", "XX...", "X.X..", "X..X.", "X...X"],
    "A": [".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
    "G": [".XXX.", "X...X", "X....", "X.XXX", "X...X", "X...X", ".XXXX"],
    "U": ["X...X", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
    "R": ["XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"],
    "-": [".....", ".....", ".....", "XXXXX", ".....", ".....", "....."],
    "9": [".XXX.", "X...X", "X...X", ".XXXX", "....X", "...X.", ".XX.."],
    "D": ["XXXX.", "X...X", "X...X", "X...X", "X...X", "X...X", "XXXX."],
    "E": ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
    "M": ["X...X", "XX.XX", "X.X.X", "X.X.X", "X...X", "X...X", "X...X"],
    "O": [".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
}
for n, ch in enumerate("KAGUR-9DEMO"):
    t = [[0] * 8 for _ in range(8)]
    for y, line in enumerate(FONT[ch]):
        for x, c in enumerate(line):
            if c == "X":
                if t[y + 1][x + 2] == 0:
                    t[y + 1][x + 2] = 2
                t[y][x + 1] = 1
    tiles[48 + n] = t

words = []
for t in tiles:
    for row in t:
        w = 0
        for p in row:
            w = (w << 4) | p
        words.append(w)

lines = [f"            9'd{a}: data<=32'h{w:08x};" for a, w in enumerate(words) if w]
rtl = f"""// SPDX-License-Identifier: Apache-2.0
// Generated by tools/gen-demo-art.py; edit the script, not this file.
// Shooter demo tile art: word tile*8+row, pixel 0 in bits 31:28, one cycle
// read latency.
module kagura_demo_art (
    input wire clk,
    input wire [8:0] addr,
    output reg [31:0] data
);
    always @(posedge clk)
        case(addr)
{chr(10).join(lines)}
            default: data<=32'h0;
        endcase
endmodule
"""
(ROOT / "rtl/core/kagura_demo_art.sv").write_text(rtl, newline="\n")
(ROOT / "sim/tests/demo_art.hex").write_text("".join(f"{w:08x}\n" for w in words), newline="\n")
print(f"{TILES} tiles, {len(words)} rows ({len(lines)} non-zero)")
