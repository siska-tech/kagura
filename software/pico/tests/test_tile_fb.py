# SPDX-License-Identifier: Apache-2.0
"""Differential test: C TileFramebuffer (tile_fb.c/tile_fb_io.c) vs Python.

Builds tests/tile_fb_host.c with the host gcc (ASan/UBSan) and replays the
same drawing, initialize and flush calls on the Python TileFramebuffer over
the register model of test_driver.py. Buffer, dirty map, flush statistics,
the VRAM write sequence and failure handling must match exactly. Also checks
that fb_bench.c's SCENE_CRC is the Python result for the benchmark scene.
"""
import os
import random
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from unittest import TestCase, main

HERE = Path(__file__).resolve().parent
PICO = HERE.parent
ROOT = PICO.parents[1]
sys.path.insert(0, str(ROOT / "software/micropython/tests"))
sys.dont_write_bytecode = True
import test_driver as T  # noqa: E402  (also puts the SDK on sys.path)
from kagura import Kagura, regs as R  # noqa: E402
from kagura.framebuffer import TileFramebuffer  # noqa: E402

BUILD = Path(tempfile.mkdtemp(prefix="tile_fb_host_"))
BINARY = BUILD / "tile_fb_host"


def setUpModule():
    cc = os.environ.get("CC", "gcc")
    subprocess.run([cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(PICO), "-I", str(ROOT / "software/include"),
                    str(PICO / "tile_fb.c"), str(PICO / "tile_fb_io.c"), str(HERE / "tile_fb_host.c"),
                    "-o", str(BINARY)], check=True)


def run_c(commands):
    result = subprocess.run([str(BINARY)], input="\n".join(commands) + "\n",
                            capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def scene():
    """fb_bench.c draw_scene(), call for call."""
    ops = [("fill", 0)]
    ops += [("fill_rect", c * 20, 0, 20, 24, c) for c in range(16)]
    ops += [("line", 160, 132, n * 10 - 5, 239, 1 + n % 15) for n in range(32)]
    ops += [("circle", 160, 132, r, r % 15 + 1) for r in range(4, 101, 12)]
    ops += [("rect", -10, -10, 40, 40, 15), ("rect", 300, 220, 40, 40, 14),
            ("fill_rect", 3, 201, 13, 37, 9), ("hline", -5, 205, 400, 10),
            ("vline", 319, -3, 300, 11), ("line", -40, 260, 360, -20, 12)]
    ops += [("pixel", (n * 37) % 320, 26 + (n * 11) % 20, n & 15) for n in range(64)]
    return ops


def random_ops(seed, count):
    rng = random.Random(seed)
    ops = []
    for n in range(count):
        kind = n % 8
        c = rng.randrange(16)
        # Mostly near the screen, sometimes far outside it.
        span = 3000 if rng.random() < 0.15 else 60
        x, y = rng.randrange(-span, 320 + span), rng.randrange(-span, 240 + span)
        w, h = rng.randrange(-5, 120), rng.randrange(-5, 120)
        if kind == 0:
            ops.append(("line", x, y, rng.randrange(-span, 320 + span), rng.randrange(-span, 240 + span), c))
        elif kind == 1:
            ops.append(("fill_rect", x, y, w, h, c))
        elif kind == 2:
            ops.append(("rect", x, y, w, h, c))
        elif kind == 3:
            ops.append(("circle", x, y, rng.randrange(0, 200 if span == 60 else 1500), c))
        elif kind == 4:
            ops.append(("hline", x, y, w * 3, c))
        elif kind == 5:
            ops.append(("vline", x, y, h * 2, c))
        elif kind == 6:
            for _ in range(20):
                ops.append(("pixel", rng.randrange(-2, 322), rng.randrange(-2, 242), rng.randrange(16)))
        else:
            ops.append(("fill", c) if rng.random() < 0.05 else ("fill_rect", x, y, 8 * (w // 8), 8, c))
    return ops


def line_of(op):
    return " ".join(str(v) for v in op)


class Python:
    """Python TileFramebuffer with the same VRAM write / FENCE log as the C harness."""

    def __init__(self):
        model = T.RegisterModel()
        model.ext[R.EXT_SCREEN_HEIGHT] = 240
        model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        self.d = d = Kagura(model).probe()
        self.fb = TileFramebuffer(d)
        self.fb.set_viper(False)
        self.log = []
        self.fail_write = self.fail_fence = 0
        write, fence = d.write_memory, d.fence

        def write_memory(address, data):
            if self.fail_write:
                self.fail_write -= 1
                if not self.fail_write:
                    self.log.append("W FAIL")
                    raise RuntimeError("injected write failure")
            write(address, data)
            self.log.append("W %x %s" % (address, bytes(data).hex()))

        def fenced():
            if self.fail_fence:
                self.fail_fence -= 1
                if not self.fail_fence:
                    self.log.append("F FAIL")
                    raise RuntimeError("injected fence failure")
            fence()
            self.log.append("F")
        d.write_memory, d.fence = write_memory, fenced

    def apply(self, op):
        name, args = op[0], op[1:]
        fb = self.fb
        if name == "clean":
            fb.dirty[:] = bytes(1200)
        elif name == "failwrite":
            self.fail_write = args[0]
        elif name == "failfence":
            self.fail_fence = args[0]
        elif name == "init":
            fb.initialize()
            self.log.append("INIT 0")
        elif name == "flush":
            try:
                fb.flush(args[0])
                status = 0
            except RuntimeError:
                status = None   # compared as "non-zero" below
            st = fb.last_flush
            self.log.append(("FLUSH", status, st["tiles"], st["bytes"], st["runs"], st["writes"], st["fences"]))
        else:
            getattr(fb, name)(*args)


def flush_line(line):
    fields = line.split()
    status = int(fields[1])
    return ("FLUSH", 0 if status == 0 else None, *map(int, fields[2:]))


class TileFramebufferDifferential(TestCase):
    def compare(self, ops):
        """Replays ops on both sides; returns the C buffer."""
        py = Python()
        for op in ops:
            py.apply(op)
        out = run_c([line_of(op) for op in ops] + ["dump"])
        buffer = bytes.fromhex(out[-2].split()[1])
        dirty = bytes.fromhex(out[-1].split()[1])
        c_log = [flush_line(line) if line.startswith("FLUSH") else line for line in out[:-2]]
        self.assertEqual(c_log, py.log)
        self.assertEqual(buffer, bytes(py.fb.buffer))
        self.assertEqual(dirty, bytes(py.fb.dirty))
        return buffer

    def test_primitives_seeded(self):
        for seed in range(6):
            with self.subTest(seed=seed):
                self.compare([("clean",)] + random_ops(seed, 400))

    def test_tile_edges_and_nibbles(self):
        ops = [("clean",)]
        for x in range(0, 17):
            for w in range(1, 18):
                ops.append(("fill_rect", x, x * 3, w, 2, (x + w) % 16))
        ops += [("hline", -1, 0, 2, 3), ("hline", 319, 239, 5, 4), ("vline", 7, 7, 2, 5),
                ("vline", 8, -1, 9, 6), ("rect", 0, 0, 1, 1, 7), ("rect", 5, 5, 1, 9, 8),
                ("fill_rect", 2147483000, 0, 2147483000, 9, 1), ("fill_rect", -2147483000, -5, 2147483000, 9, 2),
                ("circle", 0, 0, 0, 9), ("circle", 319, 239, 1, 10), ("line", 5, 5, 5, 5, 11),
                ("line", -32767, -32767, 32767, 32767, 12), ("circle", 160, 120, 2000, 13),
                ("fill", 0), ("fill", 0)]
        self.compare(ops)

    def test_scene_crc_matches_fb_bench(self):
        buffer = self.compare(scene())
        crc = zlib.crc32(buffer)
        source = (PICO / "fb_bench.c").read_text()
        constant = int(re.search(r"#define SCENE_CRC 0x([0-9a-fA-F]{8})u", source).group(1), 16)
        self.assertEqual(constant, crc, "update SCENE_CRC in fb_bench.c to 0x%08xu" % crc)

    def test_initialize_and_flush_sequence(self):
        ops = [("init",)] + random_ops(42, 60) + [("flush", 0)]
        ops += [("pixel", t % 40 * 8, t // 40 * 8, 3) for t in range(1000, 1060, 3)] + [("flush", 0)]
        for gap in (1, 2, 7, 1198):
            ops += [("pixel", t % 40 * 8 + 1, t // 40 * 8, 1 + gap % 15) for t in range(0, 1200, 5)]
            ops += [("flush", gap)]
        ops += [("mark_dirty", 0, 0, 320, 240), ("flush", 0), ("flush", 0),
                ("mark_dirty", 1015 % 40 * 8, 1015 // 40 * 8, 200, 1), ("flush", 0)]
        self.compare(ops)

    def test_failures_keep_unconfirmed_runs_dirty(self):
        setup = [("init",), ("fill", 0), ("flush", 0)]
        for fail in (("failwrite", 1), ("failwrite", 2), ("failwrite", 3), ("failfence", 1), ("failfence", 2)):
            with self.subTest(fail=fail):
                ops = setup + [("pixel", 8, 0, 1), ("fill_rect", 0, 200, 320, 16, 5),   # run 1013..1052
                               ("pixel", 319, 239, 2), fail, ("flush", 0), ("flush", 0)]
                self.compare(ops)

    def test_invalid_colour_is_noop_in_c(self):
        out = run_c(["clean", "pixel 0 0 16", "fill 99", "fill_rect 0 0 9 9 16", "line 0 0 9 9 200",
                     "circle 5 5 3 16", "dump"])
        self.assertEqual(out[-2], "BUF " + "00" * 38400)
        self.assertEqual(out[-1], "DIRTY " + "00" * 1200)


if __name__ == "__main__":
    main()
