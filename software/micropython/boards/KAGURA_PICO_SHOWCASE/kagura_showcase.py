# SPDX-License-Identifier: Apache-2.0
"""Run the live showcase from this firmware (board KAGURA_PICO_SHOWCASE).

    import kagura_showcase
    kagura_showcase.run()      # one pass of about four minutes; Q / Ctrl-C stops

Needs the ABI 0.6 FPGA build qspipsram (480p, PSRAM) and the Pico wired for
QSPI. The modules are frozen; the slides, game video, piano sample and font
are read from the ROMFS partition, mounted read-only at /rom.
"""
import gc
import os
import vfs

ROOT = '/rom'


def mount():
    """Mount the ROMFS partition at /rom (once) and return the path."""
    try:
        os.stat(ROOT + '/fonts')
        return ROOT
    except OSError:
        pass
    vfs.mount(vfs.VfsRom(vfs.rom_ioctl(2, 0)), ROOT)
    return ROOT


def run(loops=1, speed=1):
    root = mount()
    # A console from boot.py holds the PIO and the link: release it first.
    import __main__
    console = getattr(__main__, 'kagura_console', None)
    if console is not None:
        console.close()
        __main__.kagura_console = None
    console = None
    gc.collect()
    import showcase
    showcase.run(assets=root + '/showcase_assets', star_assets=root + '/starfall_assets',
                 sakura_assets=root + '/sakura_assets', font=root + '/fonts/misaki8.kfnt',
                 loops=loops, speed=speed)
