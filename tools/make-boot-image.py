#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build the KAGURA ROM-less boot image documented in section 9."""
import argparse
import struct
import zlib
from pathlib import Path

HEADER_SIZE = 32
MAX_LENGTH = 0x9D00


def parse_address(text: str) -> int:
    value = int(text, 0)
    if not 0 <= value <= 0xFFFF:
        raise argparse.ArgumentTypeError("address must fit in 16 bits")
    return value


def validate_layout(load_addr: int, entry_addr: int, length: int) -> None:
    if load_addr & 0xFF:
        raise ValueError("load address must be page aligned")
    if length < 256 or length > MAX_LENGTH or length & 0xFF:
        raise ValueError("payload length must be a 256-byte multiple from 256 to 0x9d00")
    end = load_addr + length
    in_low = load_addr >= 0x0200 and end <= 0x9F00
    in_high = load_addr >= 0xA000 and end <= 0xFF00
    if not (in_low or in_high):
        raise ValueError("payload must fit wholly in $0200-$9eff or $a000-$feff")
    if not load_addr <= entry_addr < end:
        raise ValueError("entry address must be inside the payload")


def make_image(payload: bytes, load_addr: int, entry_addr: int, pad: bool = False,
               pad_byte: int = 0) -> bytes:
    if pad and len(payload) % 256:
        payload += bytes([pad_byte]) * (-len(payload) % 256)
    validate_layout(load_addr, entry_addr, len(payload))
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    prefix = struct.pack(
        "<4sBBBBHHII8s",
        b"K9BT", 1, HEADER_SIZE, 0, 1,
        load_addr, entry_addr, len(payload), payload_crc, bytes(8),
    )
    assert len(prefix) == 28
    header_crc = zlib.crc32(prefix) & 0xFFFFFFFF
    return prefix + struct.pack("<I", header_crc) + payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="raw W65C02 payload")
    parser.add_argument("output", nargs="?", type=Path, help="32-byte header plus payload")
    parser.add_argument("--load", required=True, type=parse_address,
                        help="load address, for example 0x0200")
    parser.add_argument("--entry", type=parse_address,
                        help="entry address (default: load address)")
    parser.add_argument("--pad", action="store_true",
                        help="pad payload to the next 256-byte boundary")
    parser.add_argument("--pad-byte", type=lambda value: int(value, 0), default=0,
                        help="padding byte used with --pad (default: 0)")
    parser.add_argument("--smoke-loop", action="store_true",
                        help="generate a 256-byte NOP/JMP-to-load hardware-test payload")
    args = parser.parse_args()
    if not 0 <= args.pad_byte <= 0xFF:
        parser.error("--pad-byte must fit in 8 bits")
    if args.smoke_loop and args.output is None and args.input is not None:
        args.output, args.input = args.input, None
    if args.output is None:
        parser.error("output path is required")
    if args.smoke_loop == (args.input is not None):
        parser.error("specify exactly one input file or --smoke-loop")
    entry = args.load if args.entry is None else args.entry
    try:
        if args.smoke_loop:
            payload = bytes([0xEA, 0x4C, args.load & 0xFF, args.load >> 8]) + bytes([0xEA]) * 252
        else:
            payload = args.input.read_bytes()
        image = make_image(payload, args.load, entry, args.pad, args.pad_byte)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(
        f"K9BT: {len(image) - HEADER_SIZE} payload bytes, "
        f"load=${args.load:04x}, entry=${entry:04x}, total={len(image)}"
    )


if __name__ == "__main__":
    main()
