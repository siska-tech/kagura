// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
#include <assert.h>
#include <stdio.h>
static SfGame g;
static SfFrame f;
int main(void) {
    for(unsigned height=180;height<=240;height+=60) {
        sf_init(&g,height,1);sf_step(&g,SF_FIRE);assert(g.state==SF_INTRO);
        for(unsigned i=0;i<120;i++)sf_step(&g,0);
        assert(g.state==SF_PLAY && sf_scene(&g)==SF_OPENING);
        while(g.stage_frame<2639) { g.invincible=2;sf_step(&g,0);assert(sf_render(&g,&f)); }
        g.hostile[0]=(SfHostile){g.x,g.y,0,0,true};g.shots[0]=(SfShot){g.x,g.y,true};
        sf_step(&g,SF_FIRE);assert(sf_scene(&g)==SF_WARNING && g.stage_tick==2640);
        assert(!g.hostile[0].active && !g.shots[0].active);
        while(g.stage_frame<2759) {
            sf_step(&g,SF_FIRE);assert(g.stage_tick==2640 && !g.boss.active && sf_render(&g,&f));
        }
        sf_step(&g,0);assert(g.boss.active && !g.boss.phase && g.stage_tick==2640);
        assert(!sf_boss_hit(&g,g.enemies[0].x/256,g.enemies[0].y/256+12,8,8,50));
        for(unsigned i=0;i<80;i++) { g.invincible=2;sf_step(&g,0);assert(sf_render(&g,&f) && f.peak_line<=16); }
        assert(g.boss.phase==1);
        SfGame saved=g;g.boss.age=131;
        for(unsigned i=0;i<SF_HOSTILES;i++)g.hostile[i].active=false;
        int32_t held_y=g.enemies[0].y;
        for(unsigned i=0;i<12;i++) {
            sf_boss_step(&g);assert(g.enemies[0].y==held_y);
            for(unsigned j=0;j<SF_HOSTILES;j++)assert(!g.hostile[j].active);
            assert(sf_render(&g,&f) && f.peak_line<=16);
        }
        sf_boss_step(&g);assert(g.hostile[0].active && g.enemies[0].y==held_y);
        g=saved;
        for(unsigned phase=1;phase<=3;phase++) {
            g=saved;g.boss.hp=phase==1?100:phase==2?66:33;
            unsigned period=phase==1?72:phase==2?56:40;
            g.boss.age=(uint16_t)(period*3+15);
            for(unsigned i=0;i<SF_HOSTILES;i++)g.hostile[i].active=false;
            sf_boss_step(&g);unsigned bullets=0;
            for(unsigned i=0;i<SF_HOSTILES;i++)bullets+=g.hostile[i].active;
            assert(bullets==(phase==1?3:5));assert(sf_render(&g,&f) && f.peak_line<=16);
        }
        g=saved;
        int x=g.enemies[0].x/256,y=g.enemies[0].y/256;
        assert(!sf_boss_hit(&g,x,y,4,4,100));assert(g.boss.hp==100);
        assert(sf_boss_hit(&g,x+36,y+2,8,8,12) && !g.boss.parts[0] && g.boss.parts[1]==12);
        assert(sf_render(&g,&f) && !(f.oam[30*8+3]&4) && (f.oam[31*8+3]&4));
        assert(sf_boss_hit(&g,x+3,y+12,8,8,34));sf_boss_step(&g);assert(g.boss.phase==2);
        x=g.enemies[0].x/256;y=g.enemies[0].y/256;
        assert(sf_boss_hit(&g,x+36,y+24,8,8,12) && !g.boss.parts[1]);
        assert(sf_boss_hit(&g,x+3,y+12,8,8,34));sf_boss_step(&g);assert(g.boss.phase==3);
        x=g.enemies[0].x/256;y=g.enemies[0].y/256;
        assert(sf_boss_hit(&g,x,y+12,8,8,32) && g.boss_dead && g.boss.dying);
        assert(sf_render(&g,&f) && (f.oam[5*8+3]&4)); /* wreck survives initial detonation */
        for(unsigned i=0;i<119;i++) { sf_step(&g,SF_FIRE);assert(g.state==SF_PLAY && sf_render(&g,&f)); }
        sf_step(&g,0);assert(g.state==SF_CLEAR && g.score>=12000 && !g.boss.active);
        for(unsigned i=0;i<300;i++)sf_step(&g,0);
        assert(g.state==SF_TITLE && !g.boss_dead && !g.stage_tick && !g.stage_frame);
        printf("PASS boss height=%u warning/scroll-stop/arrival/armor/parts/phases/explosion/clear/title\n",height);
    }
    return 0;
}
