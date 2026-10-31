// SPDX-License-Identifier: Apache-2.0
// Host-only wall-clock benchmark. Never presented as Pico/FPGA performance.
#include "starfall.h"
#include "profile.h"
#include <assert.h>
#include <stdio.h>
#include <time.h>
static SfGame game;
static SfFrame frame;
static SfProfile cpu;
static uint64_t now_ns(void) {
    struct timespec t;assert(timespec_get(&t,TIME_UTC)==TIME_UTC);
    return (uint64_t)t.tv_sec*1000000000u+(uint64_t)t.tv_nsec;
}
int main(void) {
    sf_init(&game,240,123);sf_start_demo(&game);unsigned peak=0,shortened=0;
    uint64_t ns_sum=0,ns_max=0;
    for(unsigned i=0;i<12000;i++) {
        uint64_t start=now_ns();sf_step(&game,0);assert(sf_render(&game,&frame));uint64_t elapsed=now_ns()-start;
        sf_profile_add(&cpu,(uint32_t)((elapsed+999)/1000));ns_sum+=elapsed;if(elapsed>ns_max)ns_max=elapsed;
        if(frame.peak_line>peak)peak=frame.peak_line;
        if(game.beam.active && game.beam.length<64)shortened++;
    }
    printf("HOST_ONLY frames=12000 avg_ns=%llu max_ns=%llu p95_last256_us=%u peak_line=%u shortened_frames=%u state_bytes=%zu frame_bytes=%zu\n",
        (unsigned long long)(ns_sum/12000),(unsigned long long)ns_max,sf_profile_p95(&cpu),peak,shortened,sizeof game,sizeof frame);
    return 0;
}
