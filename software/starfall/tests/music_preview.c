// SPDX-License-Identifier: Apache-2.0
// Host-only score audition. Reference synth, not a bit-exact RTL replacement.
#include "music.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static void word(FILE *out,unsigned n) { fputc(n&255,out);fputc((n>>8)&255,out); }
static void dword(FILE *out,unsigned n) { word(out,n&65535);word(out,n>>16); }
static void scene(SfGame *g,unsigned cue,unsigned t) {
    sf_init(g,240,1);g->state=SF_PLAY;
    switch(cue) {
    case SF_MUSIC_TITLE:g->state=SF_TITLE;g->state_age=(uint16_t)t;break;
    case SF_MUSIC_SPACE:g->stage_tick=t;break;
    case SF_MUSIC_ENTRY:g->stage_tick=SF_BASE_APPROACH_TICK+t;break;
    case SF_MUSIC_BASE:g->stage_tick=SF_BASE_WORLD_X+t;break;
    case SF_MUSIC_WARNING:g->stage_tick=2640+t;break;
    case SF_MUSIC_BOSS:g->stage_tick=2760+t;break;
    case SF_MUSIC_ESCAPE:g->boss_dead=true;g->boss_defeat_tick=3000;g->stage_tick=3000+t;break;
    case SF_MUSIC_CLEAR:g->state=SF_CLEAR;g->state_age=(uint16_t)t;break;
    case SF_MUSIC_OVER:g->state=SF_OVER;g->state_age=(uint16_t)t;break;
    case SF_MUSIC_DEMO:g->attract=true;g->demo_frame=t;break;
    }
    g->stage_frame=g->stage_tick;
}
int main(int argc,char **argv) {
    static const unsigned segments[][2]={
        {SF_MUSIC_TITLE,180},{SF_MUSIC_DEMO,180},{SF_MUSIC_SPACE,240},{SF_MUSIC_ENTRY,180},
        {SF_MUSIC_BASE,240},{SF_MUSIC_WARNING,120},{SF_MUSIC_BOSS,240},
        {SF_MUSIC_ESCAPE,120},{SF_MUSIC_CLEAR,180},{SF_MUSIC_OVER,120}};
    unsigned frames=0;for(unsigned i=0;i<sizeof segments/sizeof segments[0];i++)frames+=segments[i][1];
    unsigned bytes=frames*800*4;const char *path=argc>1?argv[1]:"starfall-music.wav";
    FILE *out=fopen(path,"wb");assert(out);
    fwrite("RIFF",1,4,out);dword(out,36+bytes);fwrite("WAVEfmt ",1,8,out);dword(out,16);
    word(out,1);word(out,2);dword(out,48000);dword(out,48000*4);word(out,4);word(out,16);
    fwrite("data",1,4,out);dword(out,bytes);
    uint32_t phase[4]={0};unsigned lfsr=1,noise_count=0,peak=0,elapsed=0;
    for(unsigned segment=0;segment<sizeof segments/sizeof segments[0];segment++) {
        unsigned cue=segments[segment][0];printf("MUSIC %us %s\n",elapsed/60,sf_music_name(cue));
        for(unsigned t=0;t<segments[segment][1];t++) {
            SfGame g;SfMusic m;scene(&g,cue,t);sf_music_render(&g,&m);
            uint32_t step[4];for(unsigned v=0;v<4;v++)step[v]=(uint32_t)(((uint64_t)m.hz[v]*16777216u+24000)/48000);
            for(unsigned sample=0;sample<800;sample++) {
                int mix=0;
                for(unsigned v=0;v<4;v++)if(m.gain[v]) {
                    int value;
                    if(v<2)value=(phase[v]>>16)<m.duty[v]?127:-127;
                    else { unsigned index=phase[v]>>19;value=index<16?-96+(int)index*12:96-((int)index-16)*12; }
                    mix+=value*m.gain[v];phase[v]=(phase[v]+step[v])&0xffffffu;
                }
                if(m.drum_gain) {
                    mix+=(lfsr&0x4000?127:-127)*m.drum_gain;
                    if(noise_count)noise_count--;
                    else { lfsr=((lfsr<<1)|(((lfsr>>14)^(lfsr>>13))&1))&32767;noise_count=m.drum_period; }
                }
                int value=mix*24/256;unsigned magnitude=(unsigned)abs(value);if(magnitude>peak)peak=magnitude;
                assert(magnitude<32768);word(out,(uint16_t)value);word(out,(uint16_t)value);
            }
        }
        elapsed+=segments[segment][1];
    }
    assert(fclose(out)==0);printf("PASS music preview=%s seconds=%u peak=%u/32767\n",path,frames/60,peak);return 0;
}
