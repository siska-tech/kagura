// SPDX-License-Identifier: Apache-2.0
// Original scores, four music voices plus percussion. No external music data.
#include "music.h"
#include <string.h>
typedef struct {
    uint8_t frames,length,third,duty,lead_gain,pad_gain;
    bool once;
    uint8_t melody[32],bass[8];
    uint16_t kicks,snares,hats;
} Score;
static const Score scores[SF_MUSIC_COUNT]={
    /* Dock lights: sparse title arpeggio, 75 BPM. */
    {12,32,4,128,13,5,false,
     {72,0,76,79,0,76,74,0,72,0,67,71,74,0,71,0,69,0,72,76,0,72,71,0,67,0,71,74,79,0,0,0},
     {48,48,43,43,45,45,43,43},0x0101,0,0},
    /* Blue orbit: bright major melody and a buoyant bass, 112.5 BPM. */
    {8,32,4,64,17,6,false,
     {72,76,79,81,84,81,79,76,74,76,79,83,86,83,79,76,
      72,74,76,81,79,76,74,72,74,77,81,84,81,77,76,74},
     {48,48,55,55,45,45,53,55},0x0101,0x1010,0x4444},
    /* Approach vector: descending minor answer, 100 BPM. */
    {9,32,3,96,15,8,false,
     {76,0,75,72,71,0,67,0,74,0,72,71,67,0,63,0,
      72,75,79,75,71,74,77,74,67,70,74,70,66,0,67,0},
     {40,40,43,43,36,36,38,39},0x1111,0x4040,0x2222},
    /* Iron lattice: clipped syncopation and minor ostinato, 150 BPM. */
    {6,32,3,32,16,9,false,
     {64,0,67,71,64,67,0,74,71,0,67,64,63,0,66,70,
      64,67,71,76,74,71,67,0,65,68,72,75,70,66,63,0},
     {40,40,43,43,41,41,39,39},0x1111,0x1010,0xaaaa},
    /* Lock-on warning: two-note siren with low pedal, 75 BPM. */
    {12,8,3,128,14,3,false,
     {64,0,70,0,64,0,70,0}, {28,28,28,28,28,28,28,28},0x0011,0,0},
    /* Siege engine: fast diminished figures, 180 BPM. */
    {5,32,3,96,18,8,false,
     {64,67,70,76,70,67,64,63,66,69,72,78,72,69,66,63,
      65,68,71,77,71,68,65,64,67,70,73,79,76,73,70,67},
     {40,40,39,39,41,41,43,42},0x5555,0x1010,0xaaaa},
    /* Exit burn: short rising major loop after the boss falls. */
    {6,16,4,64,16,7,false,
     {72,76,79,84,83,79,76,74,76,79,84,88,86,84,79,0},
     {48,48,53,55,48,48,53,55},0x1111,0x1010,0x4444},
    /* Sector secured: one-shot fanfare, then true silence. */
    {8,16,4,128,18,8,true,
     {72,76,79,0,79,81,83,84,0,79,84,88,91,0,84,0},
     {48,53,55,48,48,48,48,48},0x0101,0,0},
    /* Lost signal: descending one-shot cadence. */
    {12,8,3,128,13,6,true,
     {72,71,67,66,64,63,60,0}, {48,47,43,42,40,39,36,36},0,0,0},
    /* Flight display: a dedicated attract loop at 112.5 BPM. */
    {8,32,4,96,15,7,false,
     {67,71,74,79,78,74,71,69,71,74,79,83,81,79,74,0,
      69,72,76,81,79,76,72,71,67,71,74,79,81,78,74,71},
     {43,43,50,50,45,45,48,50},0x1111,0x1010,0x4444}
};
static unsigned frequency(unsigned note) {
    static const uint16_t octave[12]={262,277,294,311,330,349,370,392,415,440,466,494};
    if(!note)return 0;
    unsigned f=octave[note%12];int oct=(int)(note/12)-5;
    return oct>=0?f<<(unsigned)oct:f>>(unsigned)-oct;
}
unsigned sf_music_cue(const SfGame *g) {
    if(g->state==SF_TITLE || g->state==SF_BOOT || g->state==SF_INTRO)return SF_MUSIC_TITLE;
    if(g->state==SF_OVER)return SF_MUSIC_OVER;
    if(g->state==SF_CLEAR || g->state==SF_ENDING)return SF_MUSIC_CLEAR;
    if(g->boss_dead)return SF_MUSIC_ESCAPE;
    if(g->stage_frame>=2760)return SF_MUSIC_BOSS;
    if(g->stage_frame>=2640)return SF_MUSIC_WARNING;
    if(g->attract)return SF_MUSIC_DEMO;
    if(g->stage_frame>=SF_BASE_WORLD_X)return SF_MUSIC_BASE;
    if(g->stage_frame>=SF_BASE_APPROACH_TICK)return SF_MUSIC_ENTRY;
    return SF_MUSIC_SPACE;
}
const char *sf_music_name(unsigned cue) {
    static const char *names[]={"TITLE","SPACE","ENTRY","BASE","WARNING","BOSS","ESCAPE","CLEAR","OVER","DEMO"};
    return cue<SF_MUSIC_COUNT?names[cue]:"NONE";
}
void sf_music_render(const SfGame *g,SfMusic *m) {
    unsigned cue=sf_music_cue(g);const Score *s=&scores[cue];
    uint32_t tick=g->stage_frame;
    if(cue==SF_MUSIC_TITLE || cue==SF_MUSIC_CLEAR || cue==SF_MUSIC_OVER)tick=g->state_age;
    else if(cue==SF_MUSIC_ENTRY)tick-=SF_BASE_APPROACH_TICK;
    else if(cue==SF_MUSIC_BASE)tick-=SF_BASE_WORLD_X;
    else if(cue==SF_MUSIC_WARNING)tick-=2640;
    else if(cue==SF_MUSIC_BOSS)tick-=2760;
    else if(cue==SF_MUSIC_ESCAPE)tick-=g->boss_defeat_tick;
    else if(cue==SF_MUSIC_DEMO)tick=g->demo_frame;
    if(g->attract && g->state==SF_PLAY && cue!=SF_MUSIC_DEMO)tick/=2;
    memset(m,0,sizeof *m);m->cue=(uint8_t)cue;m->tick=tick;m->duty[0]=s->duty;m->duty[1]=128;
    unsigned step=tick/s->frames,phase=tick%s->frames;
    if(s->once && step>=s->length)return;
    step%=s->length;
    unsigned root=s->bass[s->length<=8?step%8:(step/4)%8];
    unsigned arp=step%4==0?0:step%4==1?s->third:step%4==2?7:12;
    unsigned notes[4]={s->melody[step],root+12+arp,root,root+19};
    unsigned gains[4]={s->lead_gain,8,14,s->pad_gain};
    unsigned fade=tick/3;if(fade>4)fade=4;
    for(unsigned ch=0;ch<4;ch++) {
        m->hz[ch]=(uint16_t)frequency(notes[ch]);
        unsigned gain=notes[ch]?gains[ch]:0;
        if((ch==0 || ch==1) && phase>=(unsigned)s->frames-2u)gain=0; /* articulated releases */
        if(ch==3 && !s->melody[step])gain=0;
        m->gain[ch]=(uint8_t)(gain*fade/4);
    }
    unsigned bit=1u<<(step%16);
    if(phase<2 && fade) {
        if(s->kicks&bit) { m->drum_period=80;m->drum_gain=11; }
        else if(s->snares&bit) { m->drum_period=26;m->drum_gain=9; }
        else if(s->hats&bit) { m->drum_period=5;m->drum_gain=5; }
    }
}
