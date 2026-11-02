# SPDX-License-Identifier: Apache-2.0
# Count build only: the kdmark marker module plus the kagura_desktop module
# and the C core it wraps.
KDMARK_DIR := $(USERMOD_DIR)
KD_MOD_DIR := $(KDMARK_DIR)/../../../../kagura_desktop
KD_CORE_DIR := $(KD_MOD_DIR)/../../src
SRC_USERMOD_C += $(KDMARK_DIR)/modkdmark.c $(KD_MOD_DIR)/modkagura_desktop.c
CFLAGS_USERMOD += -I$(KD_MOD_DIR) -I$(KD_CORE_DIR)
