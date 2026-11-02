/* SPDX-License-Identifier: Apache-2.0 */
#include "wj_title.h"
#include "kj_text.h"
#include <string.h>
wj_title_status wj_title_copy(char out[WJ_TITLE_CAPACITY],const char *text,size_t bytes) {
    if (!out || (!text && bytes)) return WJ_TITLE_ARGUMENT;
    if (bytes>WJ_TITLE_INPUT_MAX) return WJ_TITLE_LIMIT;
    for (size_t pos=0;pos<bytes;) {
        kj_decoded d=kj_utf8_next((const uint8_t *)text+pos,bytes-pos);
        if (!d.valid) return WJ_TITLE_UTF8;
        if (!d.scalar) return WJ_TITLE_NUL;
        if (d.scalar<32 || d.scalar==127) return WJ_TITLE_CONTROL;
        pos+=d.consumed;
    }
    size_t n=kj_utf8_prefix((const uint8_t *)text,bytes,WJ_TITLE_CAPACITY-1);
    if (n) memmove(out,text,n);
    memset(out+n,0,WJ_TITLE_CAPACITY-n); return WJ_TITLE_OK;
}
const char *wj_title_error(wj_title_status status) {
    switch (status) {
        case WJ_TITLE_ARGUMENT:return "invalid title span";
        case WJ_TITLE_LIMIT:return "title exceeds 1024-byte input limit";
        case WJ_TITLE_NUL:return "embedded NUL in title";
        case WJ_TITLE_UTF8:return "malformed UTF8 title";
        case WJ_TITLE_CONTROL:return "C0/DEL control in title";
        default:return "title accepted";
    }
}
