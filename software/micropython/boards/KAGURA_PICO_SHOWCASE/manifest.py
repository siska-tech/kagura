# SPDX-License-Identifier: Apache-2.0
# The KAGURA_PICO firmware plus the live showcase (examples/showcase.md).
# Frozen bytecode and qstrs stay in flash, which leaves the heap to the
# showcase; its assets go to ROMFS (tools/make-showcase-firmware.py).
include("$(PORT_DIR)/boards/manifest.py")
include("$(BOARD_DIR)/../../manifest.py")
freeze("$(BOARD_DIR)/../..", ("kagura_ja/__init__.py",))
# The same modules as tools/prepare-showcase.py.
freeze("$(BOARD_DIR)/../../examples", (
    "showcase.py",
    "showcase_slides.py",
    "showcase_music.py",
    "showcase_graphics.py",
    "showcase_scenery.py",
    "framebuffer_demo.py",
    "starfall.py",
    "starfall_core.py",
    "starfall_render.py",
    "starfall_sound.py",
    "starfall_scores.py",
    "starfall_viper.py",
    "starfall_video.py",
    "sakura.py",
    "sakura_viper.py",
    "sakura_hud.py",
    "sakura_hud_viper.py",
))
freeze("$(BOARD_DIR)", ("kagura_showcase.py",))
