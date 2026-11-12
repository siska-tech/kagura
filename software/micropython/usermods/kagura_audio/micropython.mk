# SPDX-License-Identifier: Apache-2.0
# Make ports (unix) take one USER_C_MODULES directory: each subdirectory names
# one KAGURA module and includes the module's own file (software/audio).
USERMOD_DIR := $(USERMOD_DIR)/../../../audio/binding
include $(USERMOD_DIR)/micropython.mk
