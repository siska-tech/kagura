#include "transport.h"
#include "kd_gfx.h"
#include <string.h>
#define TIMEOUT 500000u
static bool checked(wd_transport *t, kh_status status) {
    if (status == KH_OK) return true;
    t->ready = false; t->faulted = true; t->error = status; return false;
}
static bool ack(wd_transport *t) {
    uint8_t done;
    return checked(t,kh_read_reg(KAGURA_REG_DONE_TAG,&done)) &&
           checked(t,kh_fence((uint8_t)(done+1u),TIMEOUT)) && checked(t,kh_check_errors());
}
bool wd_transport_init(wd_transport *t, uint8_t scratch[1280]) {
    memset(t,0,sizeof(*t));
    uint8_t id[5], height, lo, hi;
    if (!checked(t,kh_wait_ready(KH_DEFAULT_TIMEOUT_US)) ||
        !checked(t,kh_read(KAGURA_REG_ID0,true,id,5)) ||
        !checked(t,kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT,&height)) ||
        !checked(t,kh_ext_read(KAGURA_EXT_PATTERN_COUNT_L,&lo)) ||
        !checked(t,kh_ext_read(KAGURA_EXT_PATTERN_COUNT_H,&hi)) || !checked(t,kh_check_errors())) return false;
    if (id[0]!=KAGURA_ID0 || id[1]!=KAGURA_ID1 || id[2]!=0 || id[3]!=6 || height!=240 || (lo|(hi<<8))!=1200)
        return checked(t,KH_BAD_ARGUMENT); /* no writes before compatibility */
    if (!checked(t,kh_write_reg(KAGURA_REG_DISPLAY_CTRL,0)) || !checked(t,kh_commit(TIMEOUT))) return false;
    for (unsigned i=0;i<16;i++) {
        uint8_t word[2]={(uint8_t)kd_palette_rgb444[i],(uint8_t)(kd_palette_rgb444[i]>>8)};
        if (!checked(t,kh_vram_write(KAGURA_VRAM_PALETTE_BASE+2*i,word,2))) return false;
    }
    /* Init-only map row and high-bit table reuse the render/export scratch.
       All cells outside the 1000-tile plane select blank pattern 1000 (<1024). */
    memset(scratch+128,0,256);
    for (unsigned y=0;y<32;y++) {
        for (unsigned x=0;x<64;x++) {
            unsigned pattern=kd_kagura_map_pattern(KD_PLACE_TOP,x,y);
            scratch[x*2]=(uint8_t)pattern; scratch[x*2+1]=(uint8_t)(pattern>>8);
        }
        if (!checked(t,kh_vram_write(KAGURA_VRAM_MAP_BASE+y*128,scratch,128))) return false;
    }
    if (!checked(t,kh_vram_write(KAGURA_VRAM_MAP_EXT_BASE,scratch+128,256))) return false;
    memset(scratch,0,32);
    if (!checked(t,kh_vram_write(KD_BLANK_PATTERN*32,scratch,32))) return false;
    for (unsigned r=KAGURA_EXT_SCROLL_X_L;r<=KAGURA_EXT_SCROLL_Y;r++)
        if (!checked(t,kh_ext_write((uint8_t)r,0))) return false;
    if (id[4]&KAGURA_CAPS_RSCROLL) {
        if (!checked(t,kh_wait_status(KAGURA_STATUS_COMMIT_BUSY,0,TIMEOUT)) ||
            !checked(t,kh_ext_write(KAGURA_EXT_RS_INDEX,0)) || !checked(t,kh_ext_write(KAGURA_EXT_RS_COUNT,0))) return false;
    }
    if (!checked(t,kh_ext_write(KAGURA_EXT_BACKDROP,0)) || !ack(t)) return false;
    /* Pixels are uploaded before display enable by wd_ui_start(). */
    t->ready=true; return true;
}
bool wd_transport_sink(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    wd_transport *t=ctx;
    if (!t->ready || t->faulted || !count || first>=KD_TILES || count>KD_TILES-first) return false;
    /* Desktop patterns 0..999 never cross the 1024-pattern bank boundary. */
    if (!checked(t,kh_vram_write(KAGURA_VRAM_PATTERN_BASE+first*32,data,count*32)) || !ack(t)) return false;
    t->acknowledged_runs++; t->acknowledged_tiles+=count;
    return true; /* kd_tile4_flush clears dirtiness ONLY after this acknowledgement */
}
