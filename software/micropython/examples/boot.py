# SPDX-License-Identifier: Apache-2.0
# Copy as /boot.py on Pico. Match mode to the FPGA bitstream.
try:
    from kagura.console import start
    kagura_console = start(mode="spi")
except Exception as error:
    print("KAGURA console startup failed:", error)
