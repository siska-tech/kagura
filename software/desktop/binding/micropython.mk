# SPDX-License-Identifier: Apache-2.0
# kagura_desktop user C module for Make ports (e.g. unix):
#   make -C ports/unix USER_C_MODULES=<repo>/software/desktop
KD_MOD_DIR := $(USERMOD_DIR)
KD_ROOT := $(KD_MOD_DIR)/..

SRC_USERMOD_C += $(KD_MOD_DIR)/modkagura_desktop.c
SRC_USERMOD_LIB_C += $(KD_ROOT)/retained/kdm.c $(KD_ROOT)/text/kj_text.c $(KD_ROOT)/text/kj_misaki8.c
SRC_USERMOD_LIB_C += $(addprefix $(KD_ROOT)/core/, \
	kd_fb.c kd_region.c kd_tile4.c kd_font.c kd_font_data.c kd_sprite.c kd_gfx.c kd_app.c kd_desktop.c)

CFLAGS_USERMOD += -I$(KD_ROOT)/retained -I$(KD_ROOT)/core -I$(KD_ROOT)/text -DKD_UTF8=1
CFLAGS_USERMOD += -DKJ_MISAKI8_PATH='"$(abspath $(KD_ROOT)/../micropython/fonts/misaki8.kfnt)"'
