// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
static void origin(SfGame *g,int32_t *x,int32_t *y) {
    unsigned source=g->emitter++%(g->options+1);
    if(source)sf_option_position(g,source-1,x,y);else { *x=g->x;*y=g->y; }
    *x+=14*256;*y+=4*256;g->muzzle_mask=(uint8_t)(1u<<source);g->muzzle_timer=3;
}
void sf_bullet_step(SfGame *g,unsigned input) {
    if(g->muzzle_timer && --g->muzzle_timer==0)g->muzzle_mask=0;
    for(unsigned i=0;i<SF_SHOTS;i++) {
        SfShot *s=&g->shots[i];if(!s->active)continue;
        s->x+=8*256;s->y+=g->shot_vy[i];
        if(s->x>=320*256 || s->y<24*256)s->active=false;
    }
    for(unsigned ray=0;ray<3;ray++) {
        SfBeam *beam=ray?&g->option_beams[ray-1]:&g->beam;
        if(!beam->active)continue;
        beam->x+=12*256;beam->age++;
        if(beam->x>=320*256 || beam->age>28)beam->active=false;
    }
    if(g->cooldown)g->cooldown--;
    if((input&SF_FIRE) && !g->cooldown) {
        if(g->weapon==SF_LASER) {
            if(!g->beam.active && !g->option_beams[0].active && !g->option_beams[1].active) {
                for(unsigned source=0;source<=g->options;source++) {
                    SfBeam *beam=source?&g->option_beams[source-1]:&g->beam;
                    int32_t x=g->x,y=g->y;if(source)sf_option_position(g,source-1,&x,&y);
                    *beam=(SfBeam){x+14*256,y+4*256,0,0,64,true};
                }
                g->muzzle_mask=(uint8_t)((1u<<(g->options+1))-1);g->muzzle_timer=3;
                g->cooldown=6;sf_sound(g,SF_SOUND_SHOT);
            }
        }else for(unsigned i=0;i<SF_SHOTS;i++)if(!g->shots[i].active) {
            origin(g,&g->shots[i].x,&g->shots[i].y);g->shots[i].active=true;
            g->shot_vy[i]=g->weapon==SF_DOUBLE && g->emitter%2==0?-512:0;
            g->cooldown=6;sf_sound(g,SF_SOUND_SHOT);break;
        }
    }
    if(g->missile_cooldown)g->missile_cooldown--;
    if(g->missile.active) {
        SfShot *s=&g->missile;
        /* Drop almost vertically first; accelerate forward only after landing. */
        s->x+=g->missile_grounded?5*256:128;
        if(!g->missile_grounded) {
            if(g->missile_vy<1024)g->missile_vy+=64;
            s->y+=g->missile_vy;
        }
        unsigned world=g->stage_tick+(unsigned)(s->x/256);
        int top,bottom;sf_terrain(world/8,g->height,&top,&bottom);
        if(world<SF_BASE_WORLD_X) {
            g->missile_grounded=false;
            if(s->y>(int32_t)(SF_HUD_TOP(g->height)-8)*256)s->active=false;
        } else if(s->y>=(bottom-8)*256 || g->missile_grounded) {
            s->y=(bottom-8)*256;g->missile_grounded=true;g->missile_vy=0;
        }
        if(s->x>=320*256 || s->y<top*256)s->active=false;
    }
    if((input&SF_FIRE) && g->missile_enabled && !g->missile.active && !g->missile_cooldown) {
        g->missile=(SfShot){g->x+6*256,g->y+12*256,true};g->missile_cooldown=24;
        g->missile_vy=256;g->missile_grounded=false;
    }
    for(unsigned i=0;i<SF_HOSTILES;i++) {
        SfHostile *s=&g->hostile[i];if(!s->active)continue;
        s->x+=s->vx;s->y+=s->vy;
        if(s->x< -8*256 || s->x>=320*256 || s->y<24*256 || s->y>(int32_t)(SF_HUD_TOP(g->height)-8)*256)s->active=false;
    }
}
