// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
#include <string.h>
void sf_init(SfGame *g,unsigned height,uint32_t seed) {
    memset(g,0,sizeof *g);g->height=height==180?180:240;g->seed=seed;
    g->x=40*256;g->y=(g->height/2-8)*256;g->lives=3;g->state=SF_TITLE;
}
void sf_start(SfGame *g) {
    unsigned h=g->height;uint32_t seed=g->seed,tick=g->tick;
    sf_init(g,h,seed);g->tick=tick;g->state=SF_PLAY;g->invincible=120;
    sf_stage_reset(g);
    for(unsigned i=0;i<32;i++) { g->history_x[i]=g->x;g->history_y[i]=g->y; }
}
void sf_sound(SfGame *g,unsigned sound) { if(sound>g->sound)g->sound=(uint8_t)sound; }
void sf_explode(SfGame *g,int x,int y) {
    for(unsigned i=0;i<SF_EFFECTS;i++) if(!g->effects[i].ttl) {
        g->effects[i]=(SfEffect){(int16_t)x,(int16_t)y,20};break;
    }
}
void sf_hit_player(SfGame *g) {
    if(g->state!=SF_PLAY || g->invincible)return;
    if(g->shield) { g->shield--;g->invincible=45;sf_sound(g,SF_SOUND_POWER);return; }
    sf_explode(g,g->x/256,g->y/256);sf_sound(g,SF_SOUND_HIT);
    if(g->lives)g->lives--;
    g->power=0;g->options=0;g->invincible=180;
    g->gauge=0;g->weapon=SF_NORMAL;g->missile_enabled=false;
    memset(g->shots,0,sizeof g->shots);g->missile.active=false;g->beam.active=false;
    memset(g->option_beams,0,sizeof g->option_beams);g->muzzle_mask=g->muzzle_timer=0;
    memset(g->hostile,0,sizeof g->hostile);
    g->x=40*256;g->y=(g->height/2-8)*256;
    if(!g->lives) { g->state=SF_OVER;g->state_age=0; }
}
void sf_step(SfGame *g,unsigned input) {
    bool pressed=(input&SF_FIRE) && !g->fire_was_down;
    g->sound=0;g->tick++;if(g->state_age<65535)g->state_age++;
    for(unsigned i=0;i<SF_EFFECTS;i++) if(g->effects[i].ttl) {
        g->effects[i].ttl--;g->effects[i].x--;
    }
    if(g->state!=SF_PLAY) {
        if(pressed && (g->state==SF_TITLE || g->state_age>60))sf_start(g);
        g->fire_was_down=(input&SF_FIRE)!=0;g->equip_was_down=(input&SF_EQUIP)!=0;return;
    }
    if(g->invincible)g->invincible--;
    sf_stage_step(g);sf_player_step(g,input);sf_powerup_step(g);
    if((input&SF_EQUIP) && !g->equip_was_down)sf_equip(g);
    sf_bullet_step(g,input);sf_enemy_step(g);sf_collision_step(g);
    if(g->state==SF_PLAY && g->stage_tick>=SF_STAGE_TICKS && g->boss_dead) {
        g->state=SF_CLEAR;g->state_age=0;g->score+=5000;
    }
    g->fire_was_down=(input&SF_FIRE)!=0;
    g->equip_was_down=(input&SF_EQUIP)!=0;
}
