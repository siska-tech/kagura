// SPDX-License-Identifier: Apache-2.0
// Independent reference: link the unchanged original C implementation.
#include "starfall.h"
#include "music.h"
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv) {
    unsigned height=atoi(argv[1]),demo=atoi(argv[2]);
    SfGame g;SfFrame f;sf_init(&g,height,0x53544152);if(demo)sf_start_demo(&g);else sf_start(&g);
    for(unsigned t=0;t<4000;t++) {
        unsigned input=demo?0:SF_FIRE|((t/90)%4==0?SF_RIGHT:(t/90)%4==1?SF_DOWN:(t/90)%4==2?SF_LEFT:SF_UP);
        if(!demo) {
            g.invincible=60000;
            if(t==400 || t==600 || t==800 || t==1000 || t==1100 || t==1200) {
                g.gauge=t==400?1:t==600?2:t==800?3:t==1000?4:t==1100?5:6;
                sf_equip(&g);
            }
        }
        sf_step(&g,input);if(!sf_render(&g,&f))return 2;
        uint32_t v[]={g.tick,g.state,g.state_age,g.stage_frame,g.stage_tick,g.x,g.y,g.score,
            g.lives,g.gauge,g.weapon,g.options,g.shield,g.power,g.invincible,g.event_index,
            g.wave_spawned,g.group_failed,g.group_rewarded,g.demo_frame,g.boss.hp,g.boss.age,
            g.boss.phase,g.boss_dead,g.sound,g.pickup_active,g.pickup_x,g.pickup_y};
        fwrite(v,1,sizeof v,stdout);fwrite(f.oam,1,sizeof f.oam,stdout);
    }
    for(unsigned c=0;c<400;c++) { uint8_t col[32];sf_make_column(col,height,c);fwrite(col,1,32,stdout); }
    // All ten scores, including their one-shot tails and scene offsets.
    for(unsigned cue=0;cue<10;cue++)for(unsigned t=0;t<420;t++) {
        sf_init(&g,height,0);g.state=SF_PLAY;g.stage_frame=t;
        if(cue==0) { g.state=SF_TITLE;g.state_age=t; }
        if(cue==2)g.stage_frame+=SF_BASE_APPROACH_TICK;
        if(cue==3)g.stage_frame+=SF_BASE_WORLD_X;
        if(cue==4)g.stage_frame+=2640;
        if(cue==5)g.stage_frame+=2760;
        if(cue==6)g.boss_dead=true;
        if(cue==7) { g.state=SF_CLEAR;g.state_age=t; }
        if(cue==8) { g.state=SF_OVER;g.state_age=t; }
        if(cue==9) { g.attract=true;g.demo_frame=t; }
        SfMusic m;sf_music_render(&g,&m);
        uint32_t v[]={m.cue,m.tick,m.hz[0],m.hz[1],m.hz[2],m.hz[3],m.gain[0],m.gain[1],m.gain[2],m.gain[3],m.duty[0],m.duty[1],m.drum_period,m.drum_gain};
        fwrite(v,1,sizeof v,stdout);
    }
    return argc<3;
}
