# SPDX-License-Identifier: Apache-2.0
# Explicit files work with v1.26's manifest path-variable handling.
freeze("$(BOARD_DIR)/../..", (
    "kagura/__init__.py",
    "kagura/regs.py",
    "kagura/transport_rp2.py",
    "kagura/dma_pack.py",
    "kagura/dma_pack_viper.py",
    "kagura/fifo_xfer.py",
    "kagura/fifo_xfer_viper.py",
    "kagura/acceleration.py",
    "kagura/device.py",
    "kagura/video.py",
    "kagura/audio.py",
    "kagura/terminal.py",
    "kagura/console.py",
))
