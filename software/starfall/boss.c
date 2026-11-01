// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
static bool overlap(int x,int y,int w,int h,int bx,int by,int bw,int bh) {
    return x<bx+bw && x+w>bx && y<by+bh && y+h>by;
}
static void fan(SfGame *g,int32_t x,int32_t y,unsigned phase) {
    /* Symmetric gaps remain between a slow five-way fan; no homing after launch. */
    for(int n=-2;n<=2;n++) {
        if(phase==1 && (n==-1 || n==1))continue;
        for(unsigned i=0;i<SF_HOSTILES;i++)if(!g->hostile[i].active) {
            g->hostile[i]=(SfHostile){x,y,-512,(int16_t)(n*224),true};
            SfFrame budget;if(!sf_render(g,&budget))g->hostile[i].active=false;
            break;
        }
    }
}
void sf_boss_begin(SfGame *g,unsigned slot) {
    g->boss=(SfBoss){.hp=100,.max_hp=100,.parts={12,12},.slot=(uint8_t)slot,.active=true};
}
void sf_boss_step(SfGame *g) {
    SfBoss *b=&g->boss;if(!b->active)return;
    SfEnemy *e=&g->enemies[b->slot];b->age++;
    if(e->x>240*256)e->x-=256;
    unsigned t=(b->age/2)%128;int dy=t<64?(int)t-32:96-(int)t;
    /* Hold position during the telegraph and salvo, then reposition during
     * recovery. The player can read a stable firing lane before committing. */
    unsigned period=b->hp>66?72:b->hp>33?56:40;
    unsigned cycle=b->age%period;
    if(b->age<=80 || (cycle>=24 && cycle<period-12))
        e->y=(g->height/2-16+dy*3/4)*256;
    b->x=e->x;b->y=e->y;
    b->phase=b->age<=80?0:b->hp>66?1:b->hp>33?2:3;
    if(!b->phase)return;
    if(b->age%period==0 && b->parts[0])sf_enemy_fire(g,e->x+32*256,e->y+6*256);
    if(b->age%period==8 && b->parts[1])sf_enemy_fire(g,e->x+32*256,e->y+24*256);
    if(b->age%period==16 || (!b->parts[0] && !b->parts[1] && b->age%period==0))
        fan(g,e->x,e->y+16*256,b->phase);
}
bool sf_boss_hit(SfGame *g,int x,int y,int w,int h,unsigned damage) {
    SfBoss *b=&g->boss;if(!b->active || !b->phase)return false;
    SfEnemy *e=&g->enemies[b->slot];int bx=e->x/256,by=e->y/256;
    for(unsigned part=0;part<2;part++)if(b->parts[part] && overlap(x,y,w,h,bx+32,by+(part?20:0),16,12)) {
        b->parts[part]=(uint8_t)(b->parts[part]>damage?b->parts[part]-damage:0);
        g->enemy_flash[b->slot]=6;
        if(!b->parts[part]) { g->score+=1000;sf_explode(g,bx+32,by+(int)part*16);sf_sound(g,SF_SOUND_KILL); }
        return true;
    }
    if(!overlap(x,y,w,h,bx,by+10,24,12))return false;
    b->hp=(uint16_t)(b->hp>damage?b->hp-damage:0);e->hp=b->hp;g->enemy_flash[b->slot]=6;
    if(!b->hp) {
        int32_t px=e->x,py=e->y;sf_clear_combat(g);
        g->boss=(SfBoss){.x=px,.y=py,.dying=true};
        g->boss_dead=true;g->boss_defeat_tick=g->stage_frame;g->score+=5000;
        sf_explode(g,px/256,py/256);sf_sound(g,SF_SOUND_KILL);
    }
    return true;
}
void sf_boss_death_step(SfGame *g) {
    SfBoss *b=&g->boss;b->death_age++;
    if(b->death_age%8==0) {
        unsigned n=b->death_age/8;sf_explode(g,b->x/256+(n*17)%48,b->y/256+(n*11)%32);
        sf_sound(g,SF_SOUND_KILL);
    }
    if(b->death_age>=120) { sf_clear_combat(g);g->state=SF_CLEAR;g->state_age=0;g->score+=5000; }
}
