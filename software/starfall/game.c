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
    g->state=SF_INTRO;g->state_age=0;
}
void sf_begin_play(SfGame *g) { g->state=SF_PLAY;g->state_age=0; }
void sf_to_title(SfGame *g) { unsigned h=g->height;uint32_t seed=g->seed,tick=g->tick;sf_init(g,h,seed);g->tick=tick; }
void sf_clear_combat(SfGame *g) {
    memset(g->enemies,0,sizeof g->enemies);memset(g->hostile,0,sizeof g->hostile);
    memset(g->shots,0,sizeof g->shots);memset(g->effects,0,sizeof g->effects);
    memset(g->option_beams,0,sizeof g->option_beams);memset(&g->beam,0,sizeof g->beam);
    g->missile.active=false;g->pickup_active=false;g->capsule_queue=0;g->muzzle_mask=g->muzzle_timer=0;
    g->cooldown=g->missile_cooldown=0;
    memset(&g->boss,0,sizeof g->boss);
}
void sf_sound(SfGame *g,unsigned sound) { if(sound>g->sound)g->sound=(uint8_t)sound; }
void sf_explode(SfGame *g,int x,int y) {
    for(unsigned i=0;i<SF_EFFECTS;i++) if(!g->effects[i].ttl) {
        g->effects[i]=(SfEffect){(int16_t)x,(int16_t)y,20};break;
    }
}
void sf_hit_player(SfGame *g) {
    if(g->state!=SF_PLAY || g->invincible || g->attract)return;
    if(g->shield) { g->shield--;g->invincible=45;sf_sound(g,SF_SOUND_POWER);return; }
    sf_explode(g,g->x/256,g->y/256);sf_sound(g,SF_SOUND_HIT);
    if(g->lives)g->lives--;
    g->power=0;g->options=0;g->invincible=180;
    g->gauge=0;g->weapon=SF_NORMAL;g->missile_enabled=false;
    memset(g->shots,0,sizeof g->shots);g->missile.active=false;g->beam.active=false;
    memset(g->option_beams,0,sizeof g->option_beams);g->muzzle_mask=g->muzzle_timer=0;
    memset(g->hostile,0,sizeof g->hostile);
    g->x=40*256;g->y=(g->height/2-8)*256;
    if(!g->lives) { sf_clear_combat(g);g->state=SF_OVER;g->state_age=0; }
}
void sf_step(SfGame *g,unsigned input) {
    unsigned real=input;bool pressed=(real&SF_FIRE) && !g->start_was_down;
    g->sound=0;g->tick++;if(g->state_age<65535)g->state_age++;
    if(g->attract) {
        if(pressed) { sf_start(g);goto done; }
        if(++g->demo_frame>=SF_DEMO_TICKS) { sf_to_title(g);goto done; }
        input=sf_demo_input(g);
    }
    for(unsigned i=0;i<SF_EFFECTS;i++) if(g->effects[i].ttl) {
        g->effects[i].ttl--;g->effects[i].x--;
    }
    if(g->state==SF_BOOT) { sf_to_title(g);goto done; }
    if(g->state==SF_TITLE) {
        if(pressed)sf_start(g);
        else if(real)g->idle_ticks=0;
        else if(++g->idle_ticks>=SF_TITLE_IDLE_TICKS)sf_start_demo(g);
        goto done;
    }
    if(g->state==SF_INTRO) { if(g->state_age>=(g->attract?60:120))sf_begin_play(g);goto done; }
    if(g->state==SF_OVER) { if(g->state_age>=240 || (pressed && g->state_age>60))sf_to_title(g);goto done; }
    if(g->state==SF_CLEAR || g->state==SF_ENDING) {
        if(!g->attract && (g->state_age>=300 || (pressed && g->state_age>60)))sf_to_title(g);
        goto done;
    }
    if(g->invincible)g->invincible--;
    if(sf_scene(g)==SF_DEFEAT) { g->stage_frame+=g->attract?2:1;sf_boss_death_step(g);goto done; }
    sf_stage_step(g);sf_player_step(g,input);sf_powerup_step(g);
    if(sf_scene(g)==SF_WARNING)goto done;
    if(g->attract)sf_demo_events(g);
    if((input&SF_EQUIP) && !g->equip_was_down)sf_equip(g);
    sf_bullet_step(g,input);sf_enemy_step(g);sf_collision_step(g);
done:
    g->start_was_down=(real&SF_FIRE)!=0;
    g->fire_was_down=(input&SF_FIRE)!=0;
    g->equip_was_down=(input&SF_EQUIP)!=0;
}
