# SPDX-License-Identifier: Apache-2.0
"""Optional native kernels; import failure leaves the Python driver usable."""
import micropython
from time import ticks_us, ticks_diff, sleep_ms

@micropython.viper
def pump(tx, rx, settings) -> int:
    source = ptr8(tx)
    destination = ptr8(rx)
    c = ptr32(settings)
    registers = ptr32(c[0])
    sm = int(c[1])
    n = int(c[2])
    shift = int(c[3])
    flags = int(c[4])
    offset = int(c[5])
    increment = int(c[6])
    last = int(c[7])
    timeout = int(c[8])
    tx_length = int(c[10])
    rx_start = int(c[11])
    payload_start = int(c[12])
    sent = 0
    got = 0
    spins = 0
    progress = int(ticks_us())
    while got < n:
        status = uint(registers[1])
        if sent < n and (status & (uint(1) << (16 + sm))) == uint(0):
            value = uint(0)
            if flags & 1 and sent < tx_length:
                value = uint(source[sent]) << shift
            current = offset
            if increment:
                current = (offset + sent - payload_start) & 31
            if sent >= payload_start and (current == 7 or current == 8 or current == 14):
                value |= uint(0x80000000)
            if sent == last:
                value |= uint(0x40000000)
            registers[4 + sm] = value
            sent += 1
        if (uint(registers[1]) & (uint(1) << (8 + sm))) == uint(0):
            value = uint(registers[8 + sm]) & 255
            if got == 0:
                c[13] = value
            if flags & 2 and got >= rx_start:
                destination[got - rx_start] = value
            got += 1
            progress = int(ticks_us())
        spins += 1
        # Yield only occasionally. sleep_ms(0) services pending Ctrl-C on
        # RP2, including a PIO stalled indefinitely on the FPGA BUSY pin.
        if spins == 32:
            spins = 0
            sleep_ms(0)
            if int(ticks_diff(ticks_us(), progress)) >= timeout:
                c[9] = uint(got - 1 if got else 0)
                return 0
    return 1
