// SPDX-License-Identifier: Apache-2.0
#include "backend.h"
#include <string.h>
#include "pico/time.h"
uint32_t sf_transfer_us,sf_blank_overruns,sf_commit_wait_us;
uint32_t sf_scene_load_us;
uint64_t sf_payload_bytes;
uint64_t sf_map_payload_bytes;
#define TRY(call) do { kh_status s_=(call);if(s_!=KH_OK)return s_; } while(0)
static uint8_t previous[SF_SPRITES*8],scratch[SF_PATTERNS*32];
static uint16_t previous_scroll;
static uint16_t previous_sky;
static bool raster;
static bool raster_active;
static uint32_t previous_tick,last_map_col;
static bool title_map;
static uint8_t previous_fade;
static void (*idle_callback)(void);
void sf_backend_set_idle(void (*callback)(void)) { idle_callback=callback; }
/* Pace status reads instead of saturating SPI during the 16ms COMMIT wait. */
static kh_status commit(const SfGame *g) {
    uint64_t start=time_us_64();
    TRY(kh_write_reg(KAGURA_REG_COMMAND,KAGURA_CMD_COMMIT));
    TRY(kh_check_errors());
    /* Logging/sorting runs only after the next frame has been submitted.
     * It cannot consume the VBlank needed for that frame's OAM staging. */
    if(idle_callback)idle_callback();
    /* Submit video first. AUDIO_COMMIT can queue behind it and wait for the
     * synth without delaying this frame's video COMMIT admission. Logging
     * precedes that wait so it does not run in the following frame's blank. */
    TRY(sf_audio_update(g));
    for(;;) {
        uint8_t status;TRY(kh_read_reg(KAGURA_REG_STATUS,&status));
        if(!(status&KAGURA_STATUS_COMMIT_BUSY))break;
        if(time_us_64()-start>KH_DEFAULT_TIMEOUT_US)return KH_TIMEOUT_STATUS;
        sleep_us(50);
    }
    sf_commit_wait_us=(uint32_t)(time_us_64()-start);return KH_OK;
}
kh_status sf_backend_init(unsigned *height) {
    uint8_t id[5],h,lo,hi,limit;
    TRY(kh_wait_ready(KH_DEFAULT_TIMEOUT_US));
    TRY(kh_read(KAGURA_REG_ID0,true,id,sizeof id));
    if(id[0]!=KAGURA_ID0 || id[1]!=KAGURA_ID1 || id[2]!=KAGURA_ABI_MAJOR ||
       id[3]!=KAGURA_ABI_MINOR || !(id[4]&KAGURA_CAPS_SPR16))return KH_BAD_ARGUMENT;
    TRY(kh_wait_status(KAGURA_STATUS_INIT_DONE,KAGURA_STATUS_INIT_DONE,KH_DEFAULT_TIMEOUT_US));
    TRY(kh_check_errors());
    TRY(kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT,&h));
    TRY(kh_ext_read(KAGURA_EXT_PATTERN_COUNT_L,&lo));TRY(kh_ext_read(KAGURA_EXT_PATTERN_COUNT_H,&hi));
    TRY(kh_ext_read(KAGURA_EXT_MAX_LINE_SPRITES,&limit));
    if((h!=180 && h!=240) || ((unsigned)lo+((unsigned)hi<<8))<SF_PATTERNS || limit<16)return KH_BAD_ARGUMENT;
    *height=h;
    TRY(kh_write_reg(KAGURA_REG_DISPLAY_CTRL,0));TRY(kh_commit(KH_DEFAULT_TIMEOUT_US));
    raster=(id[4]&KAGURA_CAPS_RSCROLL)!=0;
    if(raster) {
        TRY(kh_ext_read(KAGURA_EXT_RS_MAX,&limit));raster=limit>=2;
        TRY(kh_ext_write(KAGURA_EXT_RS_COUNT,0));
    }
    TRY(kh_ext_write(KAGURA_EXT_SCROLL_Y,0));TRY(kh_ext_write(KAGURA_EXT_BACKDROP,0));
    sf_make_patterns(scratch);TRY(kh_vram_write(KAGURA_VRAM_PATTERN_BASE,scratch,SF_PATTERNS*32));
    sf_make_map(scratch,h);TRY(kh_vram_write(KAGURA_VRAM_MAP_BASE,scratch,4096));
    TRY(kh_fill(KAGURA_VRAM_MAP_EXT_BASE,KAGURA_VRAM_MAP_EXT_SIZE,0));
    TRY(kh_fill(KAGURA_VRAM_OAM_BASE,KAGURA_VRAM_OAM_SIZE,0));
    sf_make_palette(scratch);TRY(kh_vram_write(KAGURA_VRAM_PALETTE_BASE,scratch,SF_PALETTE_BYTES));
    TRY(sf_audio_init(id[4]));TRY(kh_fence(1,KH_DEFAULT_TIMEOUT_US));
    memset(previous,0,sizeof previous);previous_scroll=previous_sky=0;sf_payload_bytes=sf_map_payload_bytes=0;
    previous_tick=0;last_map_col=63;raster_active=raster;
    title_map=false;previous_fade=255;
    if(raster) {
        TRY(kh_ext_write(KAGURA_EXT_RS_INDEX,0));
        for(unsigned i=0;i<2;i++) {
            TRY(kh_ext_write(KAGURA_EXT_RS_LINE,(uint8_t)(i?SF_SKY_BOTTOM(h):48)));
            TRY(kh_ext_write(KAGURA_EXT_RS_X_L,0));TRY(kh_ext_write(KAGURA_EXT_RS_X_H,0));
            TRY(kh_ext_write(KAGURA_EXT_RS_Y,0)); /* advances index */
        }
        TRY(kh_ext_write(KAGURA_EXT_RS_COUNT,2));
    }
    TRY(kh_ext_write(KAGURA_EXT_SCROLL_X_L,0));TRY(kh_ext_write(KAGURA_EXT_SCROLL_X_H,0));
    TRY(kh_write_reg(KAGURA_REG_DISPLAY_CTRL,KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE|
        KAGURA_DISPLAY_CTRL_BG_ENABLE|KAGURA_DISPLAY_CTRL_SPR_ENABLE));
    return kh_commit(KH_DEFAULT_TIMEOUT_US);
}
kh_status sf_backend_present(const SfGame *g,const SfFrame *f) {
    bool title=g->state==SF_TITLE || g->state==SF_BOOT;
    bool layout_changed=title!=title_map;
    sf_scene_load_us=0;
    /* A new run restores the ring with the display stopped. No live map rewrite. */
    if(layout_changed || (!title && g->stage_tick<previous_tick)) {
        uint64_t loading=time_us_64();
        TRY(kh_write_reg(KAGURA_REG_DISPLAY_CTRL,0));TRY(kh_commit(KH_DEFAULT_TIMEOUT_US));
        if(title)sf_make_title_map(scratch,g->height);else sf_make_map(scratch,g->height);
        TRY(kh_vram_write(KAGURA_VRAM_MAP_BASE,scratch,4096));sf_map_payload_bytes+=4096;
        TRY(kh_fence(2,KH_DEFAULT_TIMEOUT_US));last_map_col=63;
        TRY(kh_write_reg(KAGURA_REG_DISPLAY_CTRL,KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE|
            KAGURA_DISPLAY_CTRL_BG_ENABLE|KAGURA_DISPLAY_CTRL_SPR_ENABLE));
        sf_scene_load_us=(uint32_t)(time_us_64()-loading);
    }
    /* OAM/palette/registers are shadowed until COMMIT. Ring columns below
     * are offscreen. Stage immediately rather than waiting a whole frame
     * when CPU/audio work has already crossed the short live blank. */
    uint64_t start=time_us_64();
    if(layout_changed && raster) {
        TRY(kh_ext_write(KAGURA_EXT_RS_COUNT,0));TRY(kh_ext_write(KAGURA_EXT_RS_INDEX,0));
        for(unsigned i=0;i<2;i++) {
            TRY(kh_ext_write(KAGURA_EXT_RS_LINE,(uint8_t)(title?(i?104:40):(i?SF_SKY_BOTTOM(g->height):48))));
            TRY(kh_ext_write(KAGURA_EXT_RS_X_L,0));TRY(kh_ext_write(KAGURA_EXT_RS_X_H,0));TRY(kh_ext_write(KAGURA_EXT_RS_Y,0));
        }
    }
    uint32_t desired_col=g->stage_tick/8+63;
    /* This column is 23 tiles beyond the right edge. Only low bytes change;
     * all tiles stay <256, map attributes and upper bits remain zero. */
    while(!title && last_map_col<desired_col) {
        uint32_t col=last_map_col+1;uint8_t column[32];sf_make_column(column,g->height,col);
        TRY(kh_set_inc(128));TRY(kh_set_vram_addr(KAGURA_VRAM_MAP_BASE+(col&63)*2));
        TRY(kh_write(KAGURA_REG_VRAM_WRITE,false,column,sizeof column));
        TRY(kh_check_errors());sf_map_payload_bytes+=sizeof column;last_map_col=col;
    }
    /* Merge adjacent dirty records into one VRAM transaction. */
    for(unsigned i=0;i<SF_SPRITES;) {
        if(!memcmp(previous+i*8,f->oam+i*8,8)) { i++;continue; }
        unsigned first=i++;
        while(i<SF_SPRITES && memcmp(previous+i*8,f->oam+i*8,8))i++;
        unsigned bytes=(i-first)*8;
        TRY(kh_vram_write(KAGURA_VRAM_OAM_BASE+first*8,f->oam+first*8,bytes));sf_payload_bytes+=bytes;
    }
    uint16_t sky=(uint16_t)((title?g->state_age/8:g->stage_tick/3)&511u);
    unsigned scroll=title?(raster?sky:0):g->scroll;
    if((scroll&255u)!=(previous_scroll&255u))TRY(kh_ext_write(KAGURA_EXT_SCROLL_X_L,(uint8_t)scroll));
    if((scroll>>8)!=(previous_scroll>>8))TRY(kh_ext_write(KAGURA_EXT_SCROLL_X_H,(uint8_t)(scroll>>8)));
    bool use_raster=raster && (title || !sf_stage_base_visible(g));
    if(use_raster!=raster_active || layout_changed)TRY(kh_ext_write(KAGURA_EXT_RS_COUNT,use_raster?2:0));
    if(use_raster)for(unsigned i=0;i<2;i++) {
        unsigned x=title?(i?sky:0):(i?g->scroll:sky),old=i?previous_scroll:previous_sky;
        if(x==old && raster_active && !layout_changed)continue;
        TRY(kh_ext_write(KAGURA_EXT_RS_INDEX,(uint8_t)i));
        if((x&255)!=(old&255) || !raster_active || layout_changed)TRY(kh_ext_write(KAGURA_EXT_RS_X_L,(uint8_t)x));
        if((x>>8)!=(old>>8) || !raster_active || layout_changed)TRY(kh_ext_write(KAGURA_EXT_RS_X_H,(uint8_t)(x>>8)));
    }
    unsigned fade=title?g->state_age/4:15;if(fade>15)fade=15;
    if(fade!=previous_fade) { uint8_t palette[32];sf_title_palette(g,palette);TRY(kh_vram_write(KAGURA_VRAM_PALETTE_BASE+128,palette,32)); }
    uint8_t status;TRY(kh_read_reg(KAGURA_REG_STATUS,&status));
    if(!(status&KAGURA_STATUS_VBLANK_LIVE))sf_blank_overruns++;
    sf_transfer_us=(uint32_t)(time_us_64()-start);TRY(commit(g));
    memcpy(previous,f->oam,sizeof previous);previous_scroll=(uint16_t)scroll;previous_sky=sky;
    previous_tick=g->stage_tick;raster_active=use_raster;title_map=title;previous_fade=(uint8_t)fade;return kh_check_errors();
}
