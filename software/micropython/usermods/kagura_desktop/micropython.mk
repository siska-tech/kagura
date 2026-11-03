# SPDX-License-Identifier: Apache-2.0
# Make ports take one USER_C_MODULES directory: this one lists the KAGURA
# modules, each including its own file (software/desktop, software/audio).
USERMOD_DIR := $(USERMOD_DIR)/../../../desktop/binding
include $(USERMOD_DIR)/micropython.mk
