// SPDX-License-Identifier: Apache-2.0
#include "backend.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static bool enabled,fail_write,pending;
static unsigned oam_bytes,commits,fences,blank_waits,sleeps,idles,wave_writes,audio_commits;
static uint8_t audio[256];
static uint8_t rs_index,rs_lines[2],rs_count;
static uint64_t clock_us;
static uint8_t map_image[4096];
static uint32_t vram_addr,view_tick;
static unsigned column_writes;
static uint8_t device_height=240;
kh_status kh_set_inc(uint16_t inc) { assert(inc==128);return KH_OK; }
kh_status kh_set_vram_addr(uint32_t addr) { vram_addr=addr;return KH_OK; }
kh_status kh_write(uint8_t reg,bool inc,const uint8_t *data,size_t n) {
    assert(reg==KAGURA_REG_VRAM_WRITE && !inc && n==32 && enabled && blank_waits);
    assert(vram_addr>=KAGURA_VRAM_MAP_BASE && vram_addr<KAGURA_VRAM_MAP_BASE+128);
    unsigned col=(vram_addr-KAGURA_VRAM_MAP_BASE)/2;
    for(unsigned i=0;i<=40;i++)assert(col!=((view_tick/8+i)&63));
    if(fail_write)return KH_TIMEOUT_BUSY;
    for(unsigned row=0;row<32;row++)map_image[row*128+col*2]=data[row];
    column_writes++;return KH_OK;
}
uint64_t time_us_64(void) { return ++clock_us; }
void sleep_us(uint64_t us) { assert(us==50);clock_us+=us;sleeps++; }
static void idle(void) { idles++; }
kh_status kh_wait_ready(uint32_t t) { (void)t;return KH_OK; }
kh_status kh_check_errors(void) { return KH_OK; }
kh_status kh_read(uint8_t r,bool inc,uint8_t *p,size_t n) {
    assert(r==KAGURA_REG_ID0 && inc && n==5);
    const uint8_t id[]={KAGURA_ID0,KAGURA_ID1,KAGURA_ABI_MAJOR,KAGURA_ABI_MINOR,KAGURA_CAPS_VALUE_FULL};
    memcpy(p,id,n);return KH_OK;
}
kh_status kh_wait_status(uint8_t mask,uint8_t value,uint32_t t) {
    (void)t;if(mask==KAGURA_STATUS_VBLANK_LIVE) { assert(value==mask);blank_waits++; }return KH_OK;
}
kh_status kh_ext_read(uint8_t r,uint8_t *v) {
    switch(r) {
    case KAGURA_EXT_SCREEN_HEIGHT:*v=device_height;break;
    case KAGURA_EXT_PATTERN_COUNT_L:*v=176;break;
    case KAGURA_EXT_PATTERN_COUNT_H:*v=4;break;
    case KAGURA_EXT_MAX_LINE_SPRITES:*v=16;break;
    case KAGURA_EXT_RS_MAX:*v=8;break;
    default:assert(false);
    }return KH_OK;
}
kh_status kh_write_reg(uint8_t r,uint8_t v) {
    if(r==KAGURA_REG_DISPLAY_CTRL)enabled=v!=0;
    else { assert(r==KAGURA_REG_COMMAND && v==KAGURA_CMD_COMMIT);commits++;pending=true; }
    return KH_OK;
}
kh_status kh_read_reg(uint8_t r,uint8_t *v) {
    assert(r==KAGURA_REG_STATUS);*v=KAGURA_STATUS_VBLANK_LIVE;
    if(pending) { *v|=KAGURA_STATUS_COMMIT_BUSY;pending=false; }return KH_OK;
}
kh_status kh_ext_write(uint8_t r,uint8_t v) {
    if(r==KAGURA_EXT_RS_INDEX) { assert(v<2);rs_index=v; }
    if(r==KAGURA_EXT_RS_LINE)rs_lines[rs_index]=v;
    if(r==KAGURA_EXT_RS_Y)rs_index++;
    if(r==KAGURA_EXT_RS_COUNT)rs_count=v;
    return KH_OK;
}
kh_status kh_commit(uint32_t t) { (void)t;commits++;return KH_OK; }
kh_status kh_audio_write(uint8_t r,uint8_t v) { audio[r]=v;return KH_OK; }
kh_status kh_audio_commit(uint32_t t) {
    (void)t;audio_commits++;
    for(unsigned ch=0;ch<6;ch++)assert(!(audio[KAGURA_AUDIO_INDEX(ch,KAGURA_AUDIO_STEP_H)]&128));
    return KH_OK;
}
kh_status kh_fence(uint8_t tag,uint32_t t) { (void)tag;(void)t;assert(!enabled);fences++;return KH_OK; }
kh_status kh_fill(uint32_t addr,uint16_t n,uint8_t v) {
    assert(!enabled && v==0);
    assert((addr==KAGURA_VRAM_MAP_EXT_BASE && n==KAGURA_VRAM_MAP_EXT_SIZE) ||
           (addr==KAGURA_VRAM_OAM_BASE && n==KAGURA_VRAM_OAM_SIZE));return KH_OK;
}
kh_status kh_vram_write(uint32_t addr,const uint8_t *p,size_t n) {
    if(addr==KAGURA_VRAM_MAP_BASE) { assert(!enabled && n==4096);memcpy(map_image,p,n); }
    if(addr==KAGURA_VRAM_WAVE_BASE) { assert(!enabled && n==512);wave_writes++; }
    else if(enabled) {
        assert(blank_waits>0 && addr>=KAGURA_VRAM_OAM_BASE && addr+n<=KAGURA_VRAM_OAM_BASE+SF_SPRITES*8);
        assert(n%8==0);if(fail_write)return KH_TIMEOUT_BUSY;oam_bytes+=(unsigned)n;
    }else assert(n<=SF_PATTERNS*32);
    return KH_OK;
}
int main(void) {
    unsigned h;SfGame g;SfFrame f;
    assert(sf_backend_init(&h)==KH_OK && h==240 && fences==1 && commits==2);
    assert(wave_writes==2 && audio_commits==2);
    assert(rs_count==2 && rs_lines[0]==48 && rs_lines[1]==SF_SKY_BOTTOM(h));
    sf_backend_set_idle(idle);sf_init(&g,h,1);sf_start(&g);g.invincible=0;
    assert(sf_render(&g,&f));assert(sf_backend_present(&g,&f)==KH_OK);
    unsigned before=oam_bytes;
    assert(sf_backend_present(&g,&f)==KH_OK && oam_bytes==before);
    sf_step(&g,SF_RIGHT|SF_FIRE);assert(sf_render(&g,&f));
    fail_write=true;unsigned c=commits;
    assert(sf_backend_present(&g,&f)==KH_TIMEOUT_BUSY && commits==c);
    fail_write=false;
    assert(sf_backend_present(&g,&f)==KH_OK && oam_bytes==before+24); /* ship, shot, muzzle */
    assert(sf_blank_overruns==0 && sleeps==3 && idles==3);
    assert(audio_commits>2);
    for(unsigned tick=8;tick<=4000;tick+=8) {
        g.stage_tick=view_tick=tick;g.scroll=(uint16_t)(tick&511);g.sound=0;
        if(tick==8) {
            fail_write=true;unsigned count=column_writes;
            assert(sf_backend_present(&g,&f)==KH_TIMEOUT_BUSY && column_writes==count);
            fail_write=false;
        }
        assert(sf_backend_present(&g,&f)==KH_OK);
        for(unsigned i=0;i<=40;i++) {
            unsigned world=tick/8+i;uint8_t expected[32];sf_make_column(expected,h,world);
            for(unsigned row=0;row<32;row++) {
                unsigned address=row*128+(world&63)*2;
                assert(map_image[address]==expected[row] && map_image[address+1]==0);
            }
        }
        assert(rs_count==(tick<SF_BASE_APPROACH_TICK?2:0));
    }
    assert(column_writes==500 && sf_map_payload_bytes==500*32);
    sf_start(&g);view_tick=0;assert(sf_render(&g,&f));assert(sf_backend_present(&g,&f)==KH_OK);
    assert(fences==2 && rs_count==2 && sf_map_payload_bytes==500*32+4096);
    uint8_t initial[4096];sf_make_map(initial,h);assert(!memcmp(initial,map_image,4096));
    device_height=180;assert(sf_backend_init(&h)==KH_OK && h==180);
    sf_init(&g,h,1);sf_start(&g);assert(sf_render(&g,&f));
    for(unsigned tick=8;tick<=4000;tick+=8) {
        g.stage_tick=view_tick=tick;g.scroll=(uint16_t)(tick&511);g.sound=0;
        assert(sf_backend_present(&g,&f)==KH_OK);
        for(unsigned i=0;i<=40;i++) {
            unsigned world=tick/8+i;uint8_t expected[32];sf_make_column(expected,h,world);
            for(unsigned row=0;row<32;row++)assert(map_image[row*128+(world&63)*2]==expected[row]);
        }
        assert(rs_count==(tick<SF_BASE_APPROACH_TICK?2:0));
    }
    assert(column_writes==1000 && sf_map_payload_bytes==500*32);
    puts("PASS backend dirty runs/failure/blank/poll/audio/ring INC128/offscreen columns/space-base/restart");
    return 0;
}
