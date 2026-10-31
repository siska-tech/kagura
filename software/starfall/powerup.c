// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
const char *sf_gauge_name(unsigned gauge) {
    static const char *names[]={"NORMAL","SPEED","MISSILE","DOUBLE","LASER","OPTION","SHIELD"};
    return names[gauge<=6?gauge:0];
}
void sf_drop_capsule(SfGame *g,int32_t x,int32_t y) {
    if(!g->pickup_active) { g->pickup_active=true;g->pickup_x=x;g->pickup_y=y; }
    else if(g->capsule_queue<8)g->capsule_queue++;
}
bool sf_equip(SfGame *g) {
    switch(g->gauge) {
    case SF_SPEED:if(g->power>=3)return false;g->power++;break;
    case SF_MISSILE:if(g->missile_enabled)return false;g->missile_enabled=true;break;
    case SF_G_DOUBLE:if(g->weapon==SF_DOUBLE)return false;g->weapon=SF_DOUBLE;break;
    case SF_G_LASER:if(g->weapon==SF_LASER)return false;g->weapon=SF_LASER;break;
    case SF_OPTION:if(g->options>=2)return false;g->options++;break;
    case SF_SHIELD:if(g->shield==3)return false;g->shield=3;break;
    default:return false;
    }
    g->gauge=0;g->beam.active=false;g->cooldown=0;
    for(unsigned i=0;i<2;i++)g->option_beams[i].active=false;
    for(unsigned i=0;i<SF_SHOTS;i++)g->shots[i].active=false;
    sf_sound(g,SF_SOUND_POWER);return true;
}
void sf_powerup_step(SfGame *g) {
    if(!g->pickup_active && g->capsule_queue) {
        g->capsule_queue--;g->pickup_active=true;g->pickup_x=280*256;g->pickup_y=g->height/2*256;
    }
    if(!g->pickup_active)return;
    g->pickup_x-=256;
    if(g->pickup_y>(int32_t)(SF_HUD_TOP(g->height)-16)*256)g->pickup_y=(int32_t)(SF_HUD_TOP(g->height)-16)*256;
    if(g->pickup_x< -16*256)g->pickup_active=false;
    int dx=(g->x-g->pickup_x)/256,dy=(g->y-g->pickup_y)/256;
    if(dx> -14 && dx<14 && dy> -14 && dy<14) {
        g->pickup_active=false;g->gauge=(uint8_t)(g->gauge%6+1);
        g->score+=500;sf_sound(g,SF_SOUND_POWER);
    }
}
