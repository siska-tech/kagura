// SPDX-License-Identifier: Apache-2.0
// kj_misaki8: the repository's Misaki KJ8F font (software/micropython/fonts/
// misaki8.kfnt, 7,171 glyphs, 71,718 B) embedded unchanged in read-only
// memory with .incbin, so it stays in flash on the RP2040. The font data is
// licensed separately (LicenseRef-Misaki, see NOTICE.md).
//
// The build passes the font's path: -DKJ_MISAKI8_PATH="\"/abs/path/misaki8.kfnt\""
// (software/desktop/binding/micropython.cmake and .mk, CMakeLists.txt).
// GCC/Clang only. The assembler stops the build if the file's size changes.
#include "kj_text.h"

#ifndef KJ_MISAKI8_PATH
#error "define KJ_MISAKI8_PATH as the quoted path of software/micropython/fonts/misaki8.kfnt"
#endif

#define KJ_MISAKI8_BYTES 71718
#define KJ_MISAKI8_GLYPHS 7171
#define KJ_STR2(x) #x
#define KJ_STR(x) KJ_STR2(x)

__asm__(".section .rodata.kj_misaki8_bytes,\"a\"\n"
        ".balign 4\n"
        ".global kj_misaki8_bytes\n"
        "kj_misaki8_bytes:\n"
        ".incbin " KJ_STR(KJ_MISAKI8_PATH) "\n"
        "kj_misaki8_bytes_end:\n"
        ".if kj_misaki8_bytes_end - kj_misaki8_bytes - " KJ_STR(KJ_MISAKI8_BYTES) "\n"
        ".error \"misaki8.kfnt is not the pinned 71,718-byte font\"\n"
        ".endif\n"
        ".previous\n");

extern const uint8_t kj_misaki8_bytes[];
const kj_font kj_misaki8 = {kj_misaki8_bytes, KJ_MISAKI8_BYTES, KJ_MISAKI8_GLYPHS, NULL, 0, 0};
