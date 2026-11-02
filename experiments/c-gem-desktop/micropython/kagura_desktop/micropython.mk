# SPDX-License-Identifier: Apache-2.0
# kagura_desktop user C module (Make ports, e.g. unix):
#   make -C ports/unix USER_C_MODULES=<repo>/experiments/c-gem-desktop/micropython
KD_MOD_DIR := $(USERMOD_DIR)
KD_CORE_DIR := $(KD_MOD_DIR)/../../src

SRC_USERMOD_C += $(KD_MOD_DIR)/modkagura_desktop.c
SRC_USERMOD_LIB_C += $(KD_MOD_DIR)/kdm.c
SRC_USERMOD_LIB_C += $(addprefix $(KD_CORE_DIR)/, \
	kd_fb.c kd_region.c kd_tile4.c kd_font.c kd_font_data.c kd_sprite.c kd_gfx.c kd_app.c kd_desktop.c)

CFLAGS_USERMOD += -I$(KD_MOD_DIR) -I$(KD_CORE_DIR)
