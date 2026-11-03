# SPDX-License-Identifier: Apache-2.0
# kagura_audio user C module for Make ports (e.g. unix); with the desktop:
#   make -C ports/unix USER_C_MODULES=<repo>/software/micropython/usermods
KA_MOD_DIR := $(USERMOD_DIR)
KA_ROOT := $(KA_MOD_DIR)/..

SRC_USERMOD_C += $(KA_MOD_DIR)/modkagura_audio.c
SRC_USERMOD_LIB_C += $(KA_ROOT)/hal/ka_audio.c $(KA_ROOT)/hal/ka_render.c $(KA_ROOT)/seq/ks_song.c $(KA_ROOT)/seq/ks_player.c

CFLAGS_USERMOD += -I$(KA_ROOT)/hal -I$(KA_ROOT)/seq
