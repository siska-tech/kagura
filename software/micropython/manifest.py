# SPDX-License-Identifier: Apache-2.0
# Explicit files work with v1.26's manifest path-variable handling.
freeze("$(BOARD_DIR)/../..", (
    "kagura/__init__.py",
    "kagura/regs.py",
    "kagura/transport_rp2.py",
    "kagura/dma_pack.py",
    "kagura/acceleration.py",
    "kagura/link.py",
    "kagura/link_viper.py",
    "kagura/device.py",
    "kagura/video.py",
    "kagura/framebuffer.py",
    "kagura/framebuffer_viper.py",
    "kagura/image256.py",
    "kagura/audio.py",
    "kagura/terminal.py",
    "kagura/console.py",
))
