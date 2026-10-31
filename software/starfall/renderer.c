// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
#include <string.h>
#include <stdio.h>
static void sprite(uint8_t *o, int x, int y, unsigned tile, bool large) {
    unsigned ux=(unsigned)x&1023u, uy=(unsigned)y&1023u;
    o[0]=(uint8_t)ux; o[1]=(uint8_t)(ux>>8);
    o[2]=(uint8_t)uy; o[3]=(uint8_t)((uy>>8)|4u|(large?8u:0));
    o[4]=(uint8_t)tile; o[5]=(uint8_t)(((tile>>8)&3u)|((tile>>4)&64u));
}
static void text(SfFrame *f,unsigned slot,int y,const char *s) {
    unsigned len=(unsigned)strlen(s);if(len>16)len=16;
    int x=(320-(int)len*8)/2;
    for(unsigned i=0;i<len;i++)if(s[i]!=' ')
        sprite(f->oam+(slot+i)*8,x+(int)i*8,y,64+(unsigned char)s[i]-32,false);
}
static bool count(SfFrame *f,unsigned slot,unsigned height,uint8_t *lines,bool optional) {
    uint8_t *o=f->oam+slot*8;if(!(o[3]&4))return true;
    int y=o[2]|((o[3]&3)<<8);if(y&512)y-=1024;
    int size=(o[3]&8)?16:8;
    for(int j=0;j<size;j++)if(y+j>=0 && y+j<(int)height && lines[y+j]>=16) {
        if(optional) { memset(o,0,8);f->dropped_effects++;return true; }return false;
    }
    for(int j=0;j<size;j++)if(y+j>=0 && y+j<(int)height) {
        unsigned n=++lines[y+j];if(n>f->peak_line)f->peak_line=n;
    }return true;
}
static void beam(SfFrame *f,const SfBeam *b,unsigned slot,unsigned palette) {
    if(!b->active)return;
    for(unsigned i=0;i<4 && i*16<b->length;i++) {
        unsigned length=b->length-i*16;if(length>16)length=16;
        sprite(f->oam+(slot+i)*8,b->x/256+(int)i*16,b->y/256,192+(length-1)*4,true);
        f->oam[(slot+i)*8+5]|=(uint8_t)(palette<<2);
    }
}
static bool decorative(unsigned slot) { return (slot>=16 && slot<16+SF_EFFECTS) || (slot>=54 && slot<57); }
static void build(const SfGame *g,SfFrame *f,bool rays) {
    memset(f,0,sizeof *f);
    char hud[24];
    const char *label=g->gauge?sf_gauge_name(g->gauge):g->stage_tick<SF_BASE_APPROACH_TICK?"SPACE":g->stage_tick<SF_BASE_WORLD_X?"ENTRY":"BASE";
    if(g->state==SF_PLAY && g->stage_tick>=2640 && g->stage_tick<2760 && g->tick%30<20)label="WARNING";
    snprintf(hud,sizeof hud,"%06luL%u %s",(unsigned long)(g->score%1000000),g->lives,label);
    text(f,32,8,hud);
    if(g->state==SF_PLAY && ((g->stage_tick>=1120 && g->stage_tick<1440) || (g->stage_tick>=2640 && g->stage_tick<2760)) && (g->tick/12)%2)
        for(unsigned i=32;i<48;i++)f->oam[i*8+5]|=1<<2;
    if(g->state!=SF_PLAY) {
        text(f,0,g->height/2-16,g->state==SF_TITLE?"PROJECT STARFALL":g->state==SF_OVER?"GAME OVER":"SECTOR CLEAR");
        if((g->tick/30)%2==0)text(f,16,g->height/2+8,"PUSH FIRE");
    } else {
        for(unsigned i=0;i<6;i++) {
            bool owned=i==0?g->power>0:i==1?g->missile_enabled:i==2?g->weapon==SF_DOUBLE:
                i==3?g->weapon==SF_LASER:i==4?g->options>0:g->shield>0;
            sprite(f->oam+(48+i)*8,88+(int)i*24,(int)SF_HUD_TOP(g->height)+4,144+i*4,true);
            f->oam[(48+i)*8+5]|=(uint8_t)((g->gauge==i+1?1:owned?2:0)<<2);
        }
        if(!g->invincible || (g->tick/5)%2==0)sprite(f->oam,g->x/256,g->y/256,(g->tick/4)%2?300:4,true);
        if(g->shield)f->oam[5]|=2<<2;
        if(rays) {
            beam(f,&g->beam,1,0);beam(f,&g->option_beams[0],22,1);beam(f,&g->option_beams[1],26,1);
        }
        if(!g->beam.active && !g->option_beams[0].active && !g->option_beams[1].active)
            for(unsigned i=0;i<SF_SHOTS;i++)if(g->shots[i].active)
            sprite(f->oam+(i+1)*8,g->shots[i].x/256,g->shots[i].y/256,8,false);
        for(unsigned i=0;i<SF_ENEMIES;i++) {
            const SfEnemy *e=&g->enemies[i];if(!e->active)continue;
            if(e->type==SF_BOSS) {
                for(unsigned part=0;part<4;part++)sprite(f->oam+(5+part)*8,
                    e->x/256+(int)(part%2)*16,e->y/256+(int)(part/2)*16,
                    (e->age%72>=56?272:48)+part*4,true);
            }else {
                bool alternate=(e->age/8)%2;
                unsigned tile=e->type==SF_TURRET?20:e->type==SF_WAVE?(alternate?260:16):
                    e->type==SF_DIVER?(alternate?268:264):(alternate?256:12);
                sprite(f->oam+(5+i)*8,e->x/256,e->y/256,tile,true);
                if(e->type==SF_TURRET && e->phase)f->oam[(5+i)*8+3]|=32;
                if(e->carrier)f->oam[(5+i)*8+5]|=1<<2;
            }
            if(g->enemy_flash[i]) {
                if(e->type==SF_BOSS)for(unsigned p=0;p<4;p++)f->oam[(5+p)*8+5]=(uint8_t)((f->oam[(5+p)*8+5]&0xc3)|12);
                else f->oam[(5+i)*8+5]=(uint8_t)((f->oam[(5+i)*8+5]&0xc3)|12);
            }
        }
        for(unsigned i=0;i<SF_HOSTILES;i++)if(g->hostile[i].active)
            sprite(f->oam+(9+i)*8,g->hostile[i].x/256,g->hostile[i].y/256,10,false);
        if(g->missile.active)sprite(f->oam+12*8,g->missile.x/256,g->missile.y/256,g->missile_grounded?11:176,false);
        if(g->pickup_active)sprite(f->oam+13*8,g->pickup_x/256,g->pickup_y/256,36,true);
        for(unsigned i=0;i<g->options;i++) {
            int32_t x,y;sf_option_position(g,i,&x,&y);
            sprite(f->oam+(14+i)*8,x/256,y/256,(g->tick/6)%2?304:28,true);
        }
        for(unsigned i=0;i<SF_EFFECTS;i++)if(g->effects[i].ttl && g->effects[i].y+16<=(int)SF_HUD_TOP(g->height))
            sprite(f->oam+(16+i)*8,g->effects[i].x,g->effects[i].y,g->effects[i].ttl>14?288:g->effects[i].ttl>7?32:44,true);
        if(g->muzzle_timer)for(unsigned source=0;source<=g->options;source++)if(g->muzzle_mask&(1u<<source)) {
            int32_t x=g->x,y=g->y;if(source)sf_option_position(g,source-1,&x,&y);
            sprite(f->oam+(54+source)*8,x/256+13,y/256+3,292,false);
        }
    }
}
void sf_laser_fit(SfGame *g) {
    if(!g->beam.active && !g->option_beams[0].active && !g->option_beams[1].active)return;
    SfFrame base;uint8_t lines[240]={0};unsigned segments[3]={0};
    build(g,&base,false);
    for(unsigned slot=0;slot<SF_SPRITES;slot++)if(!decorative(slot))count(&base,slot,g->height,lines,false);
    /* Reserve a visible head for every emitter before extending any ray.
     * All dangerous objects remain reserved; rays shorten to their real hitbox. */
    for(unsigned pass=0;pass<4;pass++)for(unsigned ray=0;ray<3;ray++) {
        SfBeam *b=ray?&g->option_beams[ray-1]:&g->beam;
        if(!b->active || segments[ray]!=pass || b->length<=pass*16)continue;
        uint8_t *o=base.oam+30*8;sprite(o,b->x/256+(int)pass*16,b->y/256,192,true);
        if(count(&base,30,g->height,lines,false))segments[ray]++;
    }
    for(unsigned ray=0;ray<3;ray++) {
        SfBeam *b=ray?&g->option_beams[ray-1]:&g->beam;
        if(b->length>segments[ray]*16)b->length=(uint8_t)(segments[ray]*16);
        if(!b->length)b->active=false;
    }
}
bool sf_render(const SfGame *g,SfFrame *f) {
    uint8_t lines[240]={0};build(g,f,true);
    /* Reserve every gameplay object and HUD first. Only decorative explosions
     * may be omitted, so a damaging object can never silently disappear. */
    for(unsigned i=0;i<SF_SPRITES;i++) {
        if(g->state==SF_PLAY && decorative(i))continue;
        if(!count(f,i,g->height,lines,false))return false;
    }
    if(g->state==SF_PLAY)for(unsigned i=0;i<SF_SPRITES;i++)if(decorative(i))count(f,i,g->height,lines,true);
    return true;
}
