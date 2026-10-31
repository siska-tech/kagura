// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
unsigned sf_scene(const SfGame *g) {
    const SfStageDef *def=sf_stage_def(g->stage_index);
    if(g->boss_dead)return SF_DEFEAT;
    if(def->boss_frame && g->stage_frame>=def->boss_frame)return SF_BOSS_BATTLE;
    if(def->warning_frame && g->stage_frame>=def->warning_frame)return SF_WARNING;
    if(g->stage_frame>=2200)return SF_CLIMAX;
    return g->stage_frame>=SF_BASE_APPROACH_TICK?SF_MAIN_AREA:SF_OPENING;
}
typedef SfStageEvent Wave;
static const Wave waves[]={
    {90,SF_SCOUT,128,4,20,SF_FORM_LINE},{310,SF_SCOUT,96,4,0,SF_FORM_V},
    {550,SF_DIVER,128,2,0,SF_FORM_PINCER},{790,SF_WAVE,128,4,22,SF_FORM_ARC},
    {1030,SF_METEOR,80,2,48,SF_FORM_LINE},{1270,SF_WAVE,150,4,22,SF_FORM_CARRIER},
    {1450,SF_TURRET,220,1,1,SF_FORM_LINE},{1550,SF_SCOUT,128,2,22,SF_FORM_REAR},
    {1790,SF_TURRET,30,1,1,SF_FORM_LINE},{1870,SF_WAVE,170,3,22,SF_FORM_WAVE},
    {2130,SF_TURRET,220,1,1,SF_FORM_LINE},{2230,SF_SCOUT,100,3,22,SF_FORM_V},
    {2420,SF_WAVE,150,3,22,SF_FORM_CARRIER},{2600,SF_SCOUT,128,2,20,SF_FORM_LINE},
    {2760,SF_BOSS,128,1,1,SF_FORM_LINE}
};
_Static_assert(sizeof waves/sizeof waves[0]<=16,"formation reward mask capacity");
static const SfStageDef stages[SF_STAGE_COUNT]={
    {"STAR FRONTIER",0,0,0,true,waves,sizeof waves/sizeof waves[0],2640,2760},
    {"FRONTLINE BASE",1,1,1,false,0,0,0,0},{"VOLCANIC BELT",2,2,2,false,0,0,0,0},
    {"ANCIENT RUINS",3,3,3,false,0,0,0,0},{"BIO HIVE",4,4,4,false,0,0,0,0},
    {"CENTRAL FORTRESS",5,5,5,false,0,0,0,0}
};
const SfStageDef *sf_stage_def(unsigned index) { return index<SF_STAGE_COUNT?&stages[index]:0; }
void sf_stage_reset(SfGame *g) {
    const SfStageDef *def=sf_stage_def(g->stage_index);
    for(unsigned i=0;i<def->event_count;i++)g->group_remaining[i]=def->events[i].count;
}
void sf_stage_lost(SfGame *g,unsigned slot) {
    unsigned group=g->enemy_group[slot];if(group)g->group_failed|=(uint16_t)(1u<<(group-1));
}
void sf_stage_defeat(SfGame *g,unsigned slot) {
    unsigned group=g->enemy_group[slot];if(!group)return;
    unsigned index=group-1;if(!g->group_remaining[index])return;
    g->group_remaining[index]--;
    if(!g->group_remaining[index] && !(g->group_failed&(1u<<index)) && sf_enemy_flying(sf_stage_def(g->stage_index)->events[index].type)) {
        g->score+=500;sf_drop_capsule(g,g->enemies[slot].x,g->enemies[slot].y);
    }
}
void sf_terrain(unsigned col,unsigned height,int *top,int *bottom) {
    unsigned play_bottom=SF_HUD_TOP(height);
    if(col<SF_BASE_WORLD_X/8) { *top=0;*bottom=(int)play_bottom;return; }
    if(col>=336) { *top=24;*bottom=(int)play_bottom-8;return; } /* boss hangar */
    unsigned entrance=col-SF_BASE_WORLD_X/8;
    if(entrance<8) {
        unsigned depth=entrance<3?entrance+1:3;
        *top=(int)depth*8;*bottom=(int)play_bottom-(int)depth*8;return;
    }
    unsigned c=col&63u;
    int upper=c>=12 && c<16?1:c>=16 && c<24?2:c>=24 && c<28?1:c>=44 && c<52?1:0;
    int lower=c>=28 && c<32?1:c>=32 && c<40?2:c>=40 && c<44?1:c>=56?1:0;
    *top=(3+upper)*8;*bottom=(int)play_bottom-(3+lower)*8;
}
bool sf_stage_base_visible(const SfGame *g) { return g->stage_tick>=SF_BASE_APPROACH_TICK; }
bool sf_terrain_hit(const SfGame *g,int x,int y,int w,int h) {
    for(int dx=0;dx<w;dx++) {
        int world=(int)g->stage_tick+x+dx;if(world<0)continue;
        int top,bottom;sf_terrain((unsigned)world/8,g->height,&top,&bottom);
        if(y<top || y+h>bottom)return true;
    }return false;
}
void sf_stage_step(SfGame *g) {
    const SfStageDef *def=sf_stage_def(g->stage_index);
    unsigned advance=g->attract?2:1;unsigned before=sf_scene(g);
    g->stage_frame+=advance;
    if(g->stage_frame<=def->warning_frame)g->stage_tick=g->stage_frame;
    g->scroll=(uint16_t)(g->stage_tick&511u);
    if(before!=SF_WARNING && sf_scene(g)==SF_WARNING) { sf_clear_combat(g);sf_sound(g,SF_SOUND_WARN); }
    if(sf_scene(g)==SF_WARNING)return;
    while(g->event_index<def->event_count) {
        const Wave *w=&def->events[g->event_index];
        if(g->stage_frame<(unsigned)w->tick+g->wave_spawned*w->gap)break;
        if(w->type==SF_BOSS)for(unsigned i=0;i<SF_ENEMIES;i++)g->enemies[i].active=false;
        unsigned slot=0;while(slot<SF_ENEMIES && g->enemies[slot].active)slot++;
        if(slot<SF_ENEMIES) {
            int y=40+(int)w->lane*((int)SF_HUD_TOP(g->height)-88)/256;
            int x=w->formation==SF_FORM_REAR?-16:320;
            if(w->formation==SF_FORM_V) {
                y+=((int)g->wave_spawned*2-3)*6;
                x-=g->wave_spawned==1 || g->wave_spawned==2?16:0;
            }
            if(w->formation==SF_FORM_PINCER)y=g->wave_spawned%2?SF_HUD_TOP(g->height)-40:40;
            if(w->type==SF_TURRET) {
                int top,bottom;sf_terrain((g->stage_tick+320)/8,g->height,&top,&bottom);
                y=w->lane<128?top:bottom-16;
            }
            g->enemies[slot]=(SfEnemy){x*256,y*256,(int16_t)y,0,
                w->type==SF_BOSS?100:w->type==SF_TURRET?3:w->type==SF_METEOR?3:1,w->type,
                w->type==SF_TURRET?(w->lane<128?1:0):w->formation,true,
                g->wave_spawned==0 && sf_enemy_flying(w->type)};
            g->enemy_flash[slot]=0;
            g->enemy_group[slot]=(uint8_t)(g->event_index+1);
            if(++g->enemy_serial[slot]==0)g->enemy_serial[slot]++;
            if(w->type==SF_BOSS)sf_boss_begin(g,slot);
        }else g->group_failed|=(uint16_t)(1u<<g->event_index);
        if(++g->wave_spawned>=w->count) { g->wave_spawned=0;g->event_index++; }
    }
}
