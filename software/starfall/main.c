// SPDX-License-Identifier: Apache-2.0
#include "backend.h"
#include "music.h"
#include "profile.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include <stdio.h>
static SfGame game;
static SfFrame frame;
static uint32_t frames,wire_max,overflows,audio_faults,missed;
static uint32_t load_max;
static SfProfile cpu_profile,io_profile,commit_profile;
static unsigned peak_max;
static uint64_t wire,total_us,payload;
static bool report_pending;
static void report(void) {
    if(!report_pending)return;
    report_pending=false;
    printf("SF frames=%lu hz100=%llu cpu_us=%llu/%lu/%lu io_us=%llu/%lu/%lu commit_us=%llu/%lu/%lu wire=%llu/%lu oam=%llu peak=%u overflow=%lu audio=%lu missed=%lu blank=%lu map=%llu load_max=%lu bgm=%s stage=%u scene=%u demo=%u\n",
        (unsigned long)frames,(unsigned long long)(total_us?(uint64_t)frames*100000000/total_us:0),
        (unsigned long long)(cpu_profile.sum/frames),(unsigned long)sf_profile_p95(&cpu_profile),(unsigned long)cpu_profile.max,
        (unsigned long long)(io_profile.sum/frames),(unsigned long)sf_profile_p95(&io_profile),(unsigned long)io_profile.max,
        (unsigned long long)(commit_profile.sum/frames),(unsigned long)sf_profile_p95(&commit_profile),(unsigned long)commit_profile.max,
        (unsigned long long)(wire/frames),(unsigned long)wire_max,(unsigned long long)(payload/frames),
        peak_max,(unsigned long)overflows,(unsigned long)audio_faults,(unsigned long)missed,
        (unsigned long)sf_blank_overruns,(unsigned long long)sf_map_payload_bytes,
        (unsigned long)load_max,
        sf_music_name(sf_music_cue(&game)),game.stage_index+1,sf_scene(&game),game.attract);
}
int main(void) {
    set_sys_clock_khz(120000,true);stdio_init_all();sf_input_init();
#ifndef STARFALL_LANES
#define STARFALL_LANES KH_SPI
#endif
    const kh_config config={STARFALL_LANES,2,2,6,7,8,9,10};kh_init(&config);
    unsigned height=0;kh_status status=sf_backend_init(&height);
    if(status!=KH_OK) { printf("STARFALL init failed %d error=%u\n",status,kh_last_error());return 1; }
    sf_init(&game,height,0x53544152u);game.state=SF_BOOT;sf_backend_set_idle(report);
    uint8_t last_frame=0;status=kh_read_reg(KAGURA_REG_FRAME_COUNT_L,&last_frame);
    if(status!=KH_OK)return 1;
    uint64_t run_start=time_us_64();
    for(;;) {
        uint64_t begin=time_us_64(),bytes=kh_get_stats()->bytes_sent,old_payload=sf_payload_bytes;
        sf_step(&game,sf_input_poll());
        if(!sf_render(&game,&frame)) { puts("STARFALL sprite budget failed");break; }
        uint32_t cpu=(uint32_t)(time_us_64()-begin);
        status=sf_backend_present(&game,&frame);if(status!=KH_OK)break;
        uint8_t irq=0,audio=0,now=0;
        status=kh_read_reg(KAGURA_REG_IRQ_STATUS,&irq);if(status!=KH_OK)break;
        if(irq&KAGURA_IRQ_STATUS_SPR_OVERFLOW) {
            overflows++;status=kh_write_reg(KAGURA_REG_IRQ_STATUS,KAGURA_IRQ_STATUS_SPR_OVERFLOW);
            if(status!=KH_OK)break;
        }
        status=kh_audio_read(KAGURA_AUDIO_STATUS,&audio);if(status!=KH_OK)break;
        if(audio&(KAGURA_AUDIO_STATUS_FIFO_UNDERFLOW|KAGURA_AUDIO_STATUS_OVERFLOW))audio_faults++;
        status=kh_read_reg(KAGURA_REG_FRAME_COUNT_L,&now);if(status!=KH_OK)break;
        unsigned delta=(uint8_t)(now-last_frame);if(delta>1)missed+=delta-1;last_frame=now;
        total_us=time_us_64()-run_start;
        uint32_t sent=(uint32_t)(kh_get_stats()->bytes_sent-bytes);
        sf_profile_add(&cpu_profile,cpu);sf_profile_add(&io_profile,sf_transfer_us);sf_profile_add(&commit_profile,sf_commit_wait_us);
        frames++;wire+=sent;payload+=sf_payload_bytes-old_payload;
        if(sent>wire_max)wire_max=sent;
        if(frame.peak_line>peak_max)peak_max=frame.peak_line;
        if(sf_scene_load_us>load_max)load_max=sf_scene_load_us;
        if(frames%256==0)report_pending=true;
    }
    printf("STARFALL stopped status=%d device_error=%u\n",status,kh_last_error());return 1;
}
