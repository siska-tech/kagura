// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static SfGame a,b;
static SfFrame f;
int main(void) {
    for(unsigned h=180;h<=240;h+=60) {
        sf_init(&a,h,123);a.state=SF_BOOT;sf_step(&a,0);assert(a.state==SF_TITLE);
        for(unsigned i=0;i<SF_TITLE_IDLE_TICKS-1;i++)sf_step(&a,0);
        assert(!a.attract && a.state==SF_TITLE);sf_step(&a,0);assert(a.attract && a.state==SF_INTRO);
        b=a;unsigned features=0;
        for(unsigned t=0;t<SF_DEMO_TICKS;t++) {
            sf_step(&a,0);sf_step(&b,0);assert(!memcmp(&a,&b,sizeof a));
            assert(sf_render(&a,&f) && f.peak_line<=16);
            if(a.power)features|=1;
            if(a.weapon==SF_LASER)features|=2;
            if(a.options)features|=4;
            for(unsigned e=0;e<SF_ENEMIES;e++)if(a.enemies[e].active) {
                if(a.enemies[e].type==SF_TURRET)features|=8;
                if(a.enemies[e].type==SF_BOSS)features|=16;
            }
        }
        printf("DEMO height=%u features=%u\n",h,features);
        assert(a.state==SF_TITLE && !a.attract && (features&31)==31);
        sf_start_demo(&a);for(unsigned i=0;i<1000;i++)sf_step(&a,0);
        sf_step(&a,SF_FIRE);assert(a.state==SF_INTRO && !a.attract && a.lives==3 && !a.power && !a.options);
        assert(!a.beam.active && !a.option_beams[0].active && !a.pickup_active);
        for(unsigned i=0;i<120;i++)sf_step(&a,0);
        assert(a.state==SF_PLAY);
        a.lives=1;a.invincible=0;sf_hit_player(&a);assert(a.state==SF_OVER);
        for(unsigned i=0;i<240;i++)sf_step(&a,0);
        assert(a.state==SF_TITLE);
        sf_init(&a,h,1);uint8_t pal[32];sf_title_palette(&a,pal);
        for(unsigned i=0;i<32;i++)assert(!pal[i]);
        a.state_age=60;sf_title_palette(&a,pal);assert(pal[2] || pal[3]);
        uint8_t map[4096];sf_make_title_map(map,h);
        unsigned logo=0;for(unsigned i=0;i<2048;i++) {
            unsigned word=map[i*2]|((unsigned)map[i*2+1]<<8);assert((word&1023)<SF_PATTERNS);
            if((word&1023)>=320)logo++;
        }assert(logo==320);
        printf("PASS flow height=%u title/intro/40s replay/start/reset/over/logo\n",h);
    }
    for(unsigned i=0;i<SF_STAGE_COUNT;i++)assert(sf_stage_def(i) && sf_stage_def(i)->ready==(i==0));
    assert(!sf_stage_def(6));return 0;
}
