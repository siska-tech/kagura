/* SPDX-License-Identifier: Apache-2.0 */
/* Link the actual application owner and acknowledged sink without any VM. */
#include "mock_hal.h"
#include <stdio.h>
#include <string.h>
static unsigned frames;
static void observe(void) {
    printf("NATIVE_CRC frame=%u crc=%08x\n",frames++,mock_crc(32000));
}
int main(void) {
    mock_reset(); wd_ui_observer(observe); wd_ui_prepare(false);
    if (!wd_ui_start() || !wd_ui_open_utf8(u8"神楽 Desktop",strlen(u8"神楽 Desktop"),NULL)) return 1;
    int x=4,color=12;
    if (!wd_ui_rect(x,8,48,24,color) || !wd_ui_present()) return 1;
    for (int i=1;i<=4;i++) {
        if (wd_ui_event()!=i) return 1;
        x+=i; color=(color+i)%16;
        if (!wd_ui_rect(x,8,48,24,color) || !wd_ui_present()) return 1;
    }
    if (wd_ui_event()!=0 || wd_ui_events()!=4) return 1;
    wd_ui_abort(); if (!wd_ui_present() || wd_ui_owned() || frames!=7) return 1;
    return 0;
}
