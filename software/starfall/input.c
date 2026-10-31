// SPDX-License-Identifier: Apache-2.0
#include "backend.h"
#include "pico/stdlib.h"
/* Active-low switches GP11..16: left/right/up/down/fire/equip.
 * USB serial packet: '@' followed by 'A'+six-bit mask (65..128).
 * Serial state expires after 250ms; sender refreshes at >=10Hz. */
static unsigned serial_mask;
static uint64_t serial_time;
static bool packet;
void sf_input_init(void) {
    for (unsigned p=11;p<=16;p++) { gpio_init(p); gpio_set_dir(p,GPIO_IN); gpio_pull_up(p); }
}
unsigned sf_input_poll(void) {
    for (unsigned n=0;n<64;n++) {
        int c=getchar_timeout_us(0); if(c==PICO_ERROR_TIMEOUT) break;
        if(packet && c>='A' && c<='A'+63) { serial_mask=(unsigned)(c-'A'); serial_time=time_us_64(); }
        packet=c=='@';
    }
    unsigned mask=time_us_64()-serial_time<250000 ? serial_mask : 0;
    for(unsigned i=0;i<6;i++) if(!gpio_get(11+i)) mask|=1u<<i;
    return mask;
}
