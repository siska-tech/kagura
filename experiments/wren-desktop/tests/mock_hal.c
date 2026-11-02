#include "mock_hal.h"
#include <string.h>
/* Fake external FPGA VRAM: test fixture ONLY, never linked in Pico firmware.
   No second kd_desktop or reference framebuffer is needed by the tests. */
static uint8_t mock_device_vram[65536];
static MockFailure failure;
static uint8_t done;
static unsigned writes,fences,rejected;
static bool reenter;
static bool owned_only;
static bool failing(MockFailure kind) { return failure==kind && (!owned_only || wd_ui_owned()); }
void mock_reset(void) { memset(mock_device_vram,0,sizeof mock_device_vram); failure=MOCK_OK; done=0; writes=fences=rejected=0; reenter=owned_only=false; }
void mock_failure(MockFailure kind) { failure=kind; owned_only=false; }
void mock_failure_when_owned(MockFailure kind) { failure=kind; owned_only=true; }
void mock_reenter(bool enable) { reenter=enable; }
unsigned mock_reentry_rejections(void) { return rejected; }
unsigned mock_writes(void) { return writes; }
unsigned mock_fences(void) { return fences; }
uint8_t mock_byte(unsigned address) { return mock_device_vram[address]; }
uint32_t mock_crc(unsigned length) {
    uint32_t c=~0u;
    for (unsigned i=0;i<length;i++) {
        c^=mock_device_vram[i]; for (int j=0;j<8;j++) c=(c>>1)^(0xedb88320u&(0u-(c&1u)));
    }
    return ~c;
}
kh_status kh_wait_ready(uint32_t t) { (void)t; return KH_OK; }
kh_status kh_read(uint8_t reg,bool inc,uint8_t *out,size_t n) {
    (void)inc;
    if (reg!=KAGURA_REG_ID0 || n!=5) return KH_BAD_ARGUMENT;
    const uint8_t id[5]={KAGURA_ID0,KAGURA_ID1,0,6,KAGURA_CAPS_RSCROLL};
    memcpy(out,id,5); if (failing(MOCK_ABI)) out[3]=99; return KH_OK;
}
kh_status kh_ext_read(uint8_t reg,uint8_t *v) {
    *v=reg==KAGURA_EXT_SCREEN_HEIGHT?240:reg==KAGURA_EXT_PATTERN_COUNT_L?(1200&255):reg==KAGURA_EXT_PATTERN_COUNT_H?(1200>>8):0;
    return KH_OK;
}
kh_status kh_read_reg(uint8_t reg,uint8_t *v) {
    if (reg==KAGURA_REG_DONE_TAG && failing(MOCK_DONE)) return KH_TIMEOUT_STATUS;
    *v=reg==KAGURA_REG_DONE_TAG?done:0; return KH_OK;
}
kh_status kh_write_reg(uint8_t reg,uint8_t v) { (void)reg; (void)v; writes++; return KH_OK; }
kh_status kh_ext_write(uint8_t reg,uint8_t v) { (void)reg; (void)v; writes++; return KH_OK; }
kh_status kh_commit(uint32_t t) { (void)t; return failing(MOCK_COMMIT)?KH_TIMEOUT_STATUS:KH_OK; }
kh_status kh_wait_status(uint8_t mask,uint8_t expected,uint32_t t) { (void)mask;(void)expected;(void)t; return KH_OK; }
kh_status kh_vram_write(uint32_t address,const uint8_t *data,size_t n) {
    writes++;
    if (reenter && !wd_ui_present() && !wd_ui_rect(1,1,4,4,1) && !wd_ui_open("reentry") && wd_ui_event()==0) rejected++;
    if (failing(MOCK_WRITE)) return KH_TIMEOUT_BUSY;
    if (address>sizeof mock_device_vram || n>sizeof mock_device_vram-address) return KH_BAD_ARGUMENT;
    memcpy(mock_device_vram+address,data,n); return KH_OK;
}
kh_status kh_fence(uint8_t tag,uint32_t t) {
    (void)t; fences++;
    if (failing(MOCK_FENCE)) return KH_TIMEOUT_STATUS;
    done=tag; return KH_OK;
}
kh_status kh_check_errors(void) { return failing(MOCK_ERROR)?KH_DEVICE_ERROR:KH_OK; }
