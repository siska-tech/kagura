// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
static const SfStageDef stages[SF_STAGE_COUNT]={
    {"STAR FRONTIER",0,0,0,true},{"FRONTLINE BASE",1,1,1,false},
    {"VOLCANIC BELT",2,2,2,false},{"ANCIENT RUINS",3,3,3,false},
    {"BIO HIVE",4,4,4,false},{"CENTRAL FORTRESS",5,5,5,false}
};
const SfStageDef *sf_stage_def(unsigned index) { return index<SF_STAGE_COUNT?&stages[index]:0; }
unsigned sf_scene(const SfGame *g) {
    if(g->boss_dead)return SF_DEFEAT;
    if(g->stage_frame>=2760)return SF_BOSS_BATTLE;
    if(g->stage_frame>=2640)return SF_WARNING;
    if(g->stage_frame>=2200)return SF_CLIMAX;
    return g->stage_frame>=SF_BASE_APPROACH_TICK?SF_MAIN_AREA:SF_OPENING;
}
typedef struct { uint16_t tick;uint8_t type,lane,count,gap; } Wave;
static const Wave waves[]={
    {90,SF_SCOUT,128,4,20},{310,SF_WAVE,96,4,22},
    {550,SF_DIVER,180,4,20},{790,SF_WAVE,128,4,22},
    {1030,SF_DIVER,80,4,20},{1270,SF_WAVE,150,4,22},
    {1450,SF_TURRET,220,1,1},{1550,SF_SCOUT,128,3,22},
    {1790,SF_TURRET,30,1,1},{1870,SF_WAVE,170,3,22},
    {2130,SF_TURRET,220,1,1},{2230,SF_SCOUT,100,3,22},
    {2420,SF_WAVE,150,3,22},{2600,SF_SCOUT,128,3,22},{2760,SF_BOSS,128,1,1}
};
void sf_stage_reset(SfGame *g) {
    for(unsigned i=0;i<sizeof waves/sizeof waves[0];i++)g->group_remaining[i]=waves[i].count;
}
void sf_stage_lost(SfGame *g,unsigned slot) {
    unsigned group=g->enemy_group[slot];if(group)g->group_failed|=(uint16_t)(1u<<(group-1));
}
void sf_stage_defeat(SfGame *g,unsigned slot) {
    unsigned group=g->enemy_group[slot];if(!group)return;
    unsigned index=group-1;if(!g->group_remaining[index])return;
    g->group_remaining[index]--;
    if(!g->group_remaining[index] && !(g->group_failed&(1u<<index)) && sf_enemy_flying(waves[index].type)) {
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
    unsigned advance=g->attract?2:1;unsigned before=sf_scene(g);
    g->stage_frame+=advance;
    if(g->stage_frame<=2640)g->stage_tick=g->stage_frame;
    g->scroll=(uint16_t)(g->stage_tick&511u);
    if(before!=SF_WARNING && sf_scene(g)==SF_WARNING) { sf_clear_combat(g);sf_sound(g,SF_SOUND_WARN); }
    if(sf_scene(g)==SF_WARNING)return;
    while(g->event_index<sizeof waves/sizeof waves[0]) {
        const Wave *w=&waves[g->event_index];
        if(g->stage_frame<(unsigned)w->tick+g->wave_spawned*w->gap)break;
        if(w->type==SF_BOSS)for(unsigned i=0;i<SF_ENEMIES;i++)g->enemies[i].active=false;
        unsigned slot=0;while(slot<SF_ENEMIES && g->enemies[slot].active)slot++;
        if(slot<SF_ENEMIES) {
            int y=40+(int)w->lane*((int)SF_HUD_TOP(g->height)-88)/256;
            if(w->type==SF_TURRET) {
                int top,bottom;sf_terrain((g->stage_tick+320)/8,g->height,&top,&bottom);
                y=w->lane<128?top:bottom-16;
            }
            g->enemies[slot]=(SfEnemy){320*256,y*256,(int16_t)y,0,
                w->type==SF_BOSS?100:w->type==SF_TURRET?3:1,w->type,
                w->type==SF_TURRET && w->lane<128?1:0,true,
                g->wave_spawned==0 && sf_enemy_flying(w->type)};
            g->enemy_flash[slot]=0;
            g->enemy_group[slot]=(uint8_t)(g->event_index+1);
            if(++g->enemy_serial[slot]==0)g->enemy_serial[slot]++;
        }else g->group_failed|=(uint16_t)(1u<<g->event_index);
        if(++g->wave_spawned>=w->count) { g->wave_spawned=0;g->event_index++; }
    }
}
