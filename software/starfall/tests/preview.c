// SPDX-License-Identifier: Apache-2.0
// Software reference compositor for visual inspection, never used on the Pico.
#include "starfall.h"
#include <assert.h>
#include <stdio.h>
static uint8_t patterns[SF_PATTERNS*32],map[4096],palette[SF_PALETTE_BYTES],canvas[320*240];
static unsigned dot(unsigned tile,unsigned x,unsigned y) {
    unsigned b=patterns[tile*32+y*4+x/2];return x&1?b&15:b>>4;
}
static void save(const char *prefix,const char *name,SfGame *g) {
    SfFrame f;sf_laser_fit(g);assert(sf_render(g,&f));
    if(g->state==SF_TITLE) { sf_make_title_map(map,g->height);sf_title_palette(g,palette+128); }
    else sf_make_map_at(map,g->height,g->stage_tick/8);
    for(unsigned y=0;y<g->height;y++)for(unsigned x=0;x<320;x++) {
        unsigned scroll=g->state==SF_TITLE?(y>=40 && y<104?0:g->state_age/8):
            !sf_stage_base_visible(g) && y>=48 && y<SF_SKY_BOTTOM(g->height)?g->stage_tick/3:g->scroll;
        unsigned bx=(x+scroll)&511u,index=((y/8)*64+bx/8)*2;
        unsigned word=map[index]|((unsigned)map[index+1]<<8),c=dot(word&1023,bx%8,y%8);
        canvas[y*320+x]=(uint8_t)(c?c+((word>>10)&15)*16:0);
    }
    for(int i=SF_SPRITES-1;i>=0;i--) {
        uint8_t *o=f.oam+i*8;if(!(o[3]&4))continue;
        int sx=o[0]|((o[1]&3)<<8),sy=o[2]|((o[3]&3)<<8);
        if(sx&512)sx-=1024;
        if(sy&512)sy-=1024;
        unsigned tile=o[4]|((o[5]&3)<<8),size=o[3]&8?16:8;
        for(unsigned y=0;y<size;y++)for(unsigned x=0;x<size;x++) {
            if(sx+(int)x<0 || sx+(int)x>=320 || sy+(int)y<0 || sy+(int)y>=g->height)continue;
            unsigned tx=o[3]&16?size-1-x:x,ty=o[3]&32?size-1-y:y;
            unsigned c=dot(tile+(size==16?(ty/8)*2+tx/8:0),tx%8,ty%8);
            if(c)canvas[(sy+y)*320+sx+x]=(uint8_t)(c+((o[5]>>2)&15)*16);
        }
    }
    char path[512];snprintf(path,sizeof path,"%s-%s.ppm",prefix,name);
    FILE *out=fopen(path,"wb");assert(out);fprintf(out,"P6\n320 %u\n255\n",g->height);
    for(unsigned i=0;i<320*g->height;i++) {
        unsigned c=palette[canvas[i]*2]|(palette[canvas[i]*2+1]<<8);
        uint8_t rgb[3]={(uint8_t)(((c>>8)&15)*17),(uint8_t)(((c>>4)&15)*17),(uint8_t)((c&15)*17)};
        assert(fwrite(rgb,1,3,out)==3);
    }fclose(out);printf("PREVIEW %s peak=%u\n",path,f.peak_line);
}
int main(int argc,char **argv) {
    const char *prefix=argc>1?argv[1]:"starfall";SfGame g;
    sf_make_patterns(patterns);sf_make_palette(palette);sf_make_map(map,240);
    sf_init(&g,240,1);g.state_age=100;save(prefix,"title",&g);sf_start(&g);sf_begin_play(&g);g.invincible=0;
    g.stage_tick=600;g.scroll=600&511;g.score=12700;g.power=2;g.options=2;g.y=105*256;
    g.gauge=SF_G_LASER;g.missile_enabled=true;
    for(unsigned i=0;i<32;i++) { g.history_x[i]=(20+(int)i/2)*256;g.history_y[i]=105*256; }
    for(unsigned i=0;i<3;i++)g.enemies[i]=(SfEnemy){(260-(int)i*26)*256,(92+(int)i*22)*256,100,20,2,
        i==0?SF_SCOUT:i==1?SF_WAVE:SF_DIVER,0,true,i==0};
    for(unsigned i=0;i<SF_SHOTS;i++)g.shots[i]=(SfShot){(82+(int)i*35)*256,110*256,true};
    g.hostile[0]=(SfHostile){170*256,126*256,0,0,true};
    g.pickup_active=true;g.pickup_x=144*256;g.pickup_y=82*256;sf_explode(&g,220,72);
    save(prefix,"space",&g);
    g.missile=(SfShot){50*256,160*256,true};g.missile_grounded=false;save(prefix,"drop",&g);
    g.stage_tick=1008;g.scroll=1008&511;save(prefix,"approach-clean",&g);
    g.stage_tick=1240;g.scroll=1240&511;save(prefix,"entry",&g);
    g.stage_tick=1900;g.scroll=1900&511;
    int top,bottom;sf_terrain((g.stage_tick+230)/8,g.height,&top,&bottom);
    g.enemies[3]=(SfEnemy){230*256,(bottom-16)*256,(int16_t)(bottom-16),0,3,SF_TURRET,0,true,false};
    save(prefix,"base",&g);
    for(unsigned i=0;i<SF_SHOTS;i++)g.shots[i].active=false;
    g.weapon=SF_LASER;g.gauge=SF_OPTION;g.cooldown=0;sf_bullet_step(&g,SF_FIRE);
    sf_terrain((g.stage_tick+180)/8,g.height,&top,&bottom);
    g.missile=(SfShot){180*256,(bottom-8)*256,true};g.missile_grounded=true;save(prefix,"laser",&g);
    for(unsigned i=0;i<SF_ENEMIES;i++)g.enemies[i].active=false;
    g.stage_tick=3000;g.scroll=3000&511;g.enemies[0]=(SfEnemy){260*256,96*256,96,0,80,SF_BOSS,0,true,false};
    save(prefix,"boss",&g);return 0;
}
