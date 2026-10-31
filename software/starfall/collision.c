// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
static bool overlap(int ax,int ay,int aw,int ah,int bx,int by,int bw,int bh) {
    return ax<bx+bw && ax+aw>bx && ay<by+bh && ay+ah>by;
}
static void damage(SfGame *g,unsigned j,unsigned amount) {
    SfEnemy *e=&g->enemies[j];
    if(e->hp>amount) { e->hp=(uint16_t)(e->hp-amount);g->enemy_flash[j]=6;return; }
    e->active=false;sf_explode(g,e->x/256,e->y/256);sf_sound(g,SF_SOUND_KILL);
    g->score+=e->type==SF_BOSS?5000:e->type==SF_TURRET?300:100;
    if(e->type==SF_BOSS) { g->boss_dead=true;g->boss_defeat_tick=g->stage_tick; }
    if(e->carrier)sf_drop_capsule(g,e->x,e->y);
    sf_stage_defeat(g,j);
}
void sf_collision_step(SfGame *g) {
    int px=g->x/256,py=g->y/256;
    if(sf_terrain_hit(g,px+5,py+5,6,6))sf_hit_player(g);
    for(unsigned i=0;i<SF_SHOTS;i++) {
        SfShot *s=&g->shots[i];if(!s->active)continue;
        int sx=s->x/256,sy=s->y/256;
        if(sf_terrain_hit(g,sx,sy+2,7,4)) { s->active=false;continue; }
        for(unsigned j=0;j<SF_ENEMIES;j++) {
            SfEnemy *e=&g->enemies[j];if(!e->active)continue;int size=e->type==SF_BOSS?32:16;
            if(!overlap(sx,sy,8,8,e->x/256,e->y/256,size,size))continue;
            s->active=false;damage(g,j,1);break;
        }
    }
    for(unsigned ray=0;ray<3;ray++) {
        SfBeam *b=ray?&g->option_beams[ray-1]:&g->beam;if(!b->active)continue;
        int bx=b->x/256,by=b->y/256;
        /* Clip the visible beam and its hitbox at the first terrain pixel. */
        unsigned length=0;
        while(length<b->length && bx+(int)length<320 && !sf_terrain_hit(g,bx+(int)length,by+4,1,4))length++;
        b->length=(uint8_t)length;if(!length)b->active=false;
    }
    sf_laser_fit(g);
    for(unsigned ray=0;ray<3;ray++) {
        SfBeam *b=ray?&g->option_beams[ray-1]:&g->beam;int bx=b->x/256,by=b->y/256;
        uint16_t *serial=ray?g->option_hit_serial[ray-1]:g->beam_hit_serial;
        for(unsigned i=0;i<SF_ENEMIES && b->active;i++) {
            SfEnemy *e=&g->enemies[i];
            if(!e->active || ((b->hit_mask&(1u<<i)) && serial[i]==g->enemy_serial[i]))continue;
            int size=e->type==SF_BOSS?32:16;
            if(overlap(bx,by+4,b->length,4,e->x/256,e->y/256,size,size)) {
                b->hit_mask|=(uint8_t)(1u<<i);serial[i]=g->enemy_serial[i];damage(g,i,3);
            }
        }
    }
    if(g->missile.active)for(unsigned i=0;i<SF_ENEMIES;i++) {
        SfEnemy *e=&g->enemies[i];if(!e->active)continue;
        int size=e->type==SF_BOSS?32:16;
        if(overlap(g->missile.x/256,g->missile.y/256,8,8,e->x/256,e->y/256,size,size)) {
            g->missile.active=false;damage(g,i,2);break;
        }
    }
    for(unsigned i=0;i<SF_HOSTILES;i++) {
        SfHostile *s=&g->hostile[i];if(!s->active)continue;
        if(sf_terrain_hit(g,s->x/256,s->y/256,8,8)) { s->active=false;continue; }
        if(overlap(px+5,py+5,6,6,s->x/256+2,s->y/256+2,4,4)) {
            sf_hit_player(g);if(g->state!=SF_PLAY)return;
        }
    }
    for(unsigned i=0;i<SF_ENEMIES;i++) {
        SfEnemy *e=&g->enemies[i];if(!e->active)continue;int size=e->type==SF_BOSS?32:16;
        if(overlap(px+5,py+5,6,6,e->x/256+2,e->y/256+2,size-4,size-4))sf_hit_player(g);
    }
}
