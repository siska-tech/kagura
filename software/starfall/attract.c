// SPDX-License-Identifier: Apache-2.0
// The real engine consumes deterministic inputs; only setup capsules are staged.
#include "starfall.h"
void sf_start_demo(SfGame *g) { sf_start(g);g->attract=true; }
void sf_demo_events(SfGame *g) {
    // Showcase SPEED, LASER and one OPTION without stockpiling setup drops.
    // Real carrier/formation rewards take precedence over demonstration drops.
    if(g->demo_frame>=180 && g->demo_frame<=1800 && (g->demo_frame-180)%90==0 &&
       !g->options && !g->pickup_active && !g->capsule_queue)
        sf_drop_capsule(g,g->x+20*256,g->y);
}
unsigned sf_demo_input(const SfGame *g) {
    static const uint8_t movement[8]={SF_RIGHT,SF_RIGHT|SF_UP,SF_UP,SF_LEFT|SF_UP,
        SF_LEFT,SF_LEFT|SF_DOWN,SF_DOWN,SF_RIGHT|SF_DOWN};
    unsigned input=SF_FIRE;
    if(g->demo_frame<300)input|=movement[(g->demo_frame/24)%8];
    else {
        int32_t x=72*256,y=(g->height/2-8)*256;
        if(g->pickup_active) { x=g->pickup_x;y=g->pickup_y; }
        else for(unsigned i=0;i<SF_ENEMIES;i++)if(g->enemies[i].active) {
            y=g->enemies[i].y;if(g->enemies[i].type==SF_BOSS)x=220*256;break;
        }
        if(x>248*256)x=248*256;
        int top,bottom;sf_terrain((g->stage_tick+(unsigned)(g->x/256)+8)/8,g->height,&top,&bottom);
        if(y<(top+8)*256)y=(top+8)*256;
        if(y>(bottom-24)*256)y=(bottom-24)*256;
        if(g->x<x-2*256)input|=SF_RIGHT;
        if(g->x>x+2*256)input|=SF_LEFT;
        if(g->y<y-2*256)input|=SF_DOWN;
        if(g->y>y+2*256)input|=SF_UP;
    }
    bool equip=!g->power?g->gauge==SF_SPEED:g->weapon!=SF_LASER?g->gauge==SF_G_LASER:
        !g->options && g->gauge==SF_OPTION;
    if(equip && g->demo_frame%2==0)input|=SF_EQUIP;
    return input;
}
