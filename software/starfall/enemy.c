// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
bool sf_enemy_flying(unsigned type) { return type==SF_SCOUT || type==SF_WAVE || type==SF_DIVER; }
static int wave(unsigned p) {
    static const int8_t table[32]={0,6,12,18,23,27,30,31,32,31,30,27,23,18,12,6,
        0,-6,-12,-18,-23,-27,-30,-31,-32,-31,-30,-27,-23,-18,-12,-6};
    return table[p&31u];
}
void sf_enemy_fire(SfGame *g,int32_t x,int32_t y) {
    for(unsigned i=0;i<SF_HOSTILES;i++)if(!g->hostile[i].active) {
        int dx=(g->x-x)/256,dy=(g->y-y)/256;
        int ax=dx<0?-dx:dx,ay=dy<0?-dy:dy,scale=ax>ay?ax:ay;
        if(scale<1)scale=1;
            g->hostile[i]=(SfHostile){x,y,(int16_t)(dx*640/scale),(int16_t)(dy*640/scale),true};
            break;
    }
}
static void fire(SfGame *g,const SfEnemy *e) { sf_enemy_fire(g,e->x,e->y+8*256); }
void sf_enemy_step(SfGame *g) {
    for(unsigned i=0;i<SF_ENEMIES;i++) {
        if(g->enemy_flash[i])g->enemy_flash[i]--;
        SfEnemy *e=&g->enemies[i];if(!e->active)continue;e->age++;
        switch(e->type) {
        case SF_SCOUT:
            if((e->phase&7)==SF_FORM_REAR)e->x+=640;else e->x-=e->age<48?640:768;
            if(e->age>=48)e->y=(e->origin_y+wave((e->age-48)/4)/2)*256;
            break;
        case SF_WAVE:e->x-=512;e->y=(e->origin_y+wave((e->phase&7)==SF_FORM_ARC?e->age/2:e->age/3))*256;break;
        case SF_METEOR:e->x-=384;e->y=(e->origin_y+wave(e->age/5)/4)*256;break;
        case SF_TURRET:
            e->x=((int32_t)g->enemy_world_x[i]-(int32_t)g->stage_tick)*256;
            if(e->age%80==40)fire(g,e);
            break;
        case SF_DIVER:
            e->x-=e->age<32?512:896;
            if(e->age==32)e->origin_y=(int16_t)(g->y/256);
            if(e->age>=32 && e->age<96) {
                int32_t target=e->origin_y*256;
                int32_t delta=target-e->y;if(delta>384)delta=384;if(delta< -384)delta=-384;
                e->y+=delta;
            }
            break;
        case SF_BOSS:
            sf_boss_step(g);
            break;
        }
        if(e->type!=SF_TURRET) {
            int world=(int)g->stage_tick+e->x/256,top,bottom;
            sf_terrain(world>0?(unsigned)world/8:0,g->height,&top,&bottom);
            int size=e->type==SF_BOSS?32:16;
            for(int dx=7;dx<(e->type==SF_BOSS?48:16);dx+=8) {
                int t,b;sf_terrain(world+dx>0?(unsigned)(world+dx)/8:0,g->height,&t,&b);
                if(t>top)top=t;
                if(b<bottom)bottom=b;
            }
            if(top<24)top=24;
            if(e->y<top*256)e->y=top*256;
            if(e->y>(bottom-size)*256)e->y=(bottom-size)*256;
        }
        if(sf_enemy_flying(e->type) && e->age%120==90)fire(g,e);
        if(e->x< -32*256 || e->x>336*256) { sf_stage_lost(g,i);e->active=false; }
    }
}
