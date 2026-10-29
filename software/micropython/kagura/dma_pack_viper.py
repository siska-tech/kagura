# SPDX-License-Identifier: Apache-2.0
"""Optional native kernels; import failure leaves the Python driver usable."""
import micropython

@micropython.viper
def viper_pack(data, high, words, start: int, count: int):
    source = ptr8(data)
    table = ptr16(high)
    destination = ptr16(words)
    for j in range(count):
        destination[j * 2 + 1] = table[source[start + j]]

@micropython.viper
def viper_pack32(data, high, words, start: int, count: int):
    source = ptr8(data)
    table = ptr16(high)
    destination = ptr32(words)
    for j in range(count):
        destination[j] = uint(table[source[start + j]]) << 16
