# SPDX-License-Identifier: Apache-2.0
"""Destructive scratch test. Run with console paused; overwrites tile RAM."""
from time import ticks_ms, ticks_diff


def run(device):
    start = ticks_ms()
    device.clear_errors()
    data = bytearray((i * 37 + 11) & 255 for i in range(2048))
    actual = bytearray(len(data))
    for address in range(0, 32768, len(data)):
        device.write_memory(address, data)
        device.fence()
        device.read_memory_into(address, actual)
        if actual != data:
            raise AssertionError("VRAM mismatch at 0x%06x" % address)
    device.fill(0, 2048, 0x5A)
    device.fence()
    device.read_memory_into(0, actual)
    if actual != b"\x5a" * len(actual):
        raise AssertionError("FILL mismatch")
    # Repeated queue-consuming commands exercise BUSY gating.
    for _ in range(64):
        device.fill(0, 64, 0)
    device.fence()
    device.check_errors()
    print("DIAG PASS (32KiB verify + FILL/FENCE), %d ms" % ticks_diff(ticks_ms(), start))
