#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Host-side checks for tools/make-boot-image.py."""
import importlib.util
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("make_boot_image", ROOT / "tools/make-boot-image.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def expect_error(payload: bytes, load: int, entry: int) -> None:
    try:
        MODULE.make_image(payload, load, entry)
    except ValueError:
        return
    raise AssertionError("invalid image layout was accepted")


payload = bytes(value ^ 0xA5 for value in range(256))
image = MODULE.make_image(payload, 0x0200, 0x0210)
assert len(image) == 288
fields = struct.unpack("<4sBBBBHHII8sI", image[:32])
assert fields[:8] == (b"K9BT", 1, 32, 0, 1, 0x0200, 0x0210, 256)
assert fields[8] == zlib.crc32(payload) & 0xFFFFFFFF
assert fields[9] == bytes(8)
assert fields[10] == zlib.crc32(image[:28]) & 0xFFFFFFFF
assert image[32:] == payload

padded = MODULE.make_image(bytes(257), 0xA000, 0xA100, pad=True, pad_byte=0xFF)
assert len(padded) == 32 + 512 and padded[-255:] == bytes([0xFF]) * 255

expect_error(bytes(256), 0x0201, 0x0201)
expect_error(bytes(255), 0x0200, 0x0200)
expect_error(bytes(256), 0x9F00, 0x9F00)
expect_error(bytes(256), 0x0200, 0x0300)
expect_error(bytes(0x9E00), 0x0200, 0x0200)

print("PASS: boot-image header, CRCs, padding and layout rejection")
