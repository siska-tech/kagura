// SPDX-License-Identifier: Apache-2.0
#include "backend.h"
#include "music.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include <stdio.h>
static SfGame game;
static SfFrame frame;
static uint32_t samples[256],frames,max_us,wire_max,overflows,audio_faults,missed,last_interval;
static unsigned peak_max;
static uint64_t sum,wire,total_us,payload;
static bool report_pending;
static void report(void) {
    if(!report_pending)return;
    report_pending=false;
    /* Work happens during COMMIT wait, after the frame has been submitted. */
    for(unsigned i=1;i<256;i++) {
        uint32_t v=samples[i];unsigned j=i;
        while(j && samples[j-1]>v) { samples[j]=samples[j-1];j--; }samples[j]=v;
    }
    printf("SF frames=%lu hz_x100=%llu work_avg_us=%llu work_max_us=%lu p95_us=%lu wire_avg=%llu wire_max=%lu oam_avg=%llu peak=%u overflow=%lu audio_fault=%lu missed=%lu interval_us=%lu blank_overruns=%lu map_bytes=%llu bgm=%s\n",
        (unsigned long)frames,(unsigned long long)(total_us?(uint64_t)frames*100000000/total_us:0),
        (unsigned long long)(sum/frames),(unsigned long)max_us,(unsigned long)samples[243],
        (unsigned long long)(wire/frames),(unsigned long)wire_max,(unsigned long long)(payload/frames),
        peak_max,(unsigned long)overflows,(unsigned long)audio_faults,(unsigned long)missed,
        (unsigned long)last_interval,(unsigned long)sf_blank_overruns,(unsigned long long)sf_map_payload_bytes,
        sf_music_name(sf_music_cue(&game)));
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
        last_interval=(uint32_t)(time_us_64()-begin);total_us=time_us_64()-run_start;
        uint32_t sent=(uint32_t)(kh_get_stats()->bytes_sent-bytes),work=cpu+sf_transfer_us;
        samples[frames%256]=work;frames++;sum+=work;wire+=sent;payload+=sf_payload_bytes-old_payload;
        if(work>max_us)max_us=work;
        if(sent>wire_max)wire_max=sent;
        if(frame.peak_line>peak_max)peak_max=frame.peak_line;
        if(frames%256==0)report_pending=true;
    }
    printf("STARFALL stopped status=%d device_error=%u\n",status,kh_last_error());return 1;
}
