// SPDX-License-Identifier: Apache-2.0
// MicroPython configuration of the instruction-count build (embed port,
// Cortex-M0+, freestanding Linux user-mode ELF under qemu-arm). The VM
// options that decide call cost follow ports/rp2/mpconfigport.h (v1.26.0):
// EXTRA_FEATURES ROM level, computed goto, MPZ ints, single float. Features
// needing an OS, a filesystem or extmod are off; none is on the counted path.
#include <port/mpconfigport_common.h>

#define MICROPY_CONFIG_ROM_LEVEL                (MICROPY_CONFIG_ROM_LEVEL_EXTRA_FEATURES)
#define MICROPY_ENABLE_COMPILER                 (1)
#define MICROPY_ENABLE_GC                       (1)
#define MICROPY_GC_STACK_ENTRY_TYPE             uint16_t
#define MICROPY_STACK_CHECK_MARGIN              (256)
#define MICROPY_OPT_COMPUTED_GOTO               (1)
#define MICROPY_LONGINT_IMPL                    (MICROPY_LONGINT_IMPL_MPZ)
#define MICROPY_FLOAT_IMPL                      (MICROPY_FLOAT_IMPL_FLOAT)
#define MICROPY_ENABLE_EXTERNAL_IMPORT          (0)
#define MICROPY_PERSISTENT_CODE_LOAD            (0)
#define MICROPY_PY_SYS_STDFILES                 (0)
#define MICROPY_PY_SYS_STDIO_BUFFER             (0)
#define MICROPY_PY_IO                           (0)
#define MICROPY_HELPER_REPL                     (0)
#define MICROPY_PY_BUILTINS_INPUT               (0)
#define MICROPY_PY_BUILTINS_HELP                (0)
#define MICROPY_PY_THREAD                       (0)
#define MICROPY_ENABLE_SCHEDULER                (0)
#define MICROPY_KBD_EXCEPTION                   (0)
#define MICROPY_PY_SYS_EXIT                     (0)
#define MICROPY_PY_SYS_PLATFORM                 "rp2"
#define MP_SSIZE_MAX                            (0x7fffffff)
#define MICROPY_PY_BUILTINS_EXECFILE            (0)
#define MICROPY_PY_UCTYPES                      (0)
