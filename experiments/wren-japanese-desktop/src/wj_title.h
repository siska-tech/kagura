/* SPDX-License-Identifier: Apache-2.0 */
#ifndef WJ_TITLE_H
#define WJ_TITLE_H
#include <stddef.h>
#define WJ_TITLE_CAPACITY 24
#define WJ_TITLE_INPUT_MAX 1024
typedef enum { WJ_TITLE_OK,WJ_TITLE_ARGUMENT,WJ_TITLE_LIMIT,WJ_TITLE_NUL,WJ_TITLE_UTF8,WJ_TITLE_CONTROL } wj_title_status;
/* Validate the WHOLE bounded span, then copy <=23 complete UTF8 bytes.
   No mutation of out on error. Valid unsupported scalars use native fallback. */
wj_title_status wj_title_copy(char out[WJ_TITLE_CAPACITY],const char *text,size_t bytes);
const char *wj_title_error(wj_title_status status);
#endif
