// SPDX-License-Identifier: Apache-2.0
#include "backend.h"
#include "music.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint8_t shadow[256],active[256],waves[2][512];
static unsigned bank,commits,writes,wave_writes;
static unsigned max_frame_writes;
static bool fail;
kh_status kh_audio_write(uint8_t reg,uint8_t value) {
    if(fail)return KH_TIMEOUT_BUSY;
    shadow[reg]=value;writes++;return KH_OK;
}
kh_status kh_audio_commit(uint32_t timeout) {
    (void)timeout;memcpy(active,shadow,sizeof active);bank^=1;commits++;
    for(unsigned ch=0;ch<6;ch++)assert(!(active[KAGURA_AUDIO_INDEX(ch,KAGURA_AUDIO_STEP_H)]&128));
    return KH_OK;
}
kh_status kh_vram_write(uint32_t addr,const uint8_t *data,size_t n) {
    assert(addr==KAGURA_VRAM_WAVE_BASE && n==512);memcpy(waves[bank],data,n);wave_writes++;return KH_OK;
}
static void scene(SfGame *g,unsigned cue,unsigned local) {
    sf_init(g,240,123);g->state=SF_PLAY;
    switch(cue) {
    case SF_MUSIC_TITLE:g->state=SF_TITLE;g->state_age=(uint16_t)local;break;
    case SF_MUSIC_SPACE:g->stage_tick=local;break;
    case SF_MUSIC_ENTRY:g->stage_tick=SF_BASE_APPROACH_TICK+local;break;
    case SF_MUSIC_BASE:g->stage_tick=SF_BASE_WORLD_X+local;break;
    case SF_MUSIC_WARNING:g->stage_tick=2640+local;break;
    case SF_MUSIC_BOSS:g->stage_tick=2760+local;break;
    case SF_MUSIC_ESCAPE:g->boss_dead=true;g->boss_defeat_tick=3000;g->stage_tick=3000+local;break;
    case SF_MUSIC_CLEAR:g->state=SF_CLEAR;g->state_age=(uint16_t)local;break;
    case SF_MUSIC_OVER:g->state=SF_OVER;g->state_age=(uint16_t)local;break;
    case SF_MUSIC_DEMO:g->attract=true;g->demo_frame=local;break;
    default:assert(false);
    }
    g->stage_frame=g->stage_tick;
}
static void match(const SfGame *g) {
    static const unsigned channels[4]={0,1,4,5};SfMusic m;sf_music_render(g,&m);
    unsigned before=writes;
    assert(sf_audio_update(g)==KH_OK);
    if(writes-before>max_frame_writes)max_frame_writes=writes-before;
    for(unsigned i=0;i<4;i++) {
        unsigned base=KAGURA_AUDIO_INDEX(channels[i],0);
        uint32_t step=active[base+KAGURA_AUDIO_STEP_L]|((uint32_t)active[base+KAGURA_AUDIO_STEP_M]<<8)|
            ((uint32_t)active[base+KAGURA_AUDIO_STEP_H]<<16);
        assert(step==((uint64_t)m.hz[i]*16777216u+24000)/48000);
        assert(active[base+KAGURA_AUDIO_GAIN_L]==m.gain[i] && active[base+KAGURA_AUDIO_GAIN_R]==m.gain[i]);
        assert(active[base+KAGURA_AUDIO_CONTROL]==(m.gain[i]?KAGURA_AUDIO_CONTROL_ENABLE:0));
    }
    assert(!memcmp(waves[0],waves[1],512));
}
int main(void) {
    SfGame g;SfMusic a,b;uint32_t signatures[SF_MUSIC_COUNT];
    assert(sf_audio_init(KAGURA_CAPS_VALUE_FULL)==KH_OK && wave_writes==2 && commits==2);
    for(unsigned cue=0;cue<SF_MUSIC_COUNT;cue++) {
        uint32_t hash=2166136261u;
        for(unsigned t=0;t<96;t++) {
            scene(&g,cue,t);sf_music_render(&g,&a);sf_music_render(&g,&b);
            assert(a.cue==cue && !memcmp(&a,&b,sizeof a));match(&g);
            for(unsigned v=0;v<4;v++) {
                assert(a.hz[v]<24000 && a.gain[v]<=18);
                hash=(hash^a.hz[v])*16777619u;hash=(hash^a.gain[v])*16777619u;
            }
            hash=(hash^a.duty[0]^a.drum_gain^a.drum_period)*16777619u;
        }
        signatures[cue]=hash;
        for(unsigned old=0;old<cue;old++)assert(signatures[old]!=hash);
        printf("PASS score=%s signature=%08x\n",sf_music_name(cue),(unsigned)hash);
    }
    const unsigned boundaries[]={0,1119,1120,1439,1440,2639,2640,2759,2760};
    const unsigned expected[]={SF_MUSIC_SPACE,SF_MUSIC_SPACE,SF_MUSIC_ENTRY,SF_MUSIC_ENTRY,
        SF_MUSIC_BASE,SF_MUSIC_BASE,SF_MUSIC_WARNING,SF_MUSIC_WARNING,SF_MUSIC_BOSS};
    for(unsigned i=0;i<sizeof boundaries/sizeof boundaries[0];i++) {
        sf_init(&g,240,1);g.state=SF_PLAY;g.stage_frame=g.stage_tick=boundaries[i];assert(sf_music_cue(&g)==expected[i]);match(&g);
    }
    for(unsigned cue=SF_MUSIC_CLEAR;cue<=SF_MUSIC_OVER;cue++) {
        scene(&g,cue,200);match(&g);sf_music_render(&g,&a);
        for(unsigned v=0;v<4;v++)assert(a.gain[v]==0 && a.hz[v]==0);
        assert(a.drum_gain==0 && active[KAGURA_AUDIO_INDEX(3,KAGURA_AUDIO_CONTROL)]==0);
    }
    scene(&g,SF_MUSIC_BASE,40);g.sound=SF_SOUND_HIT;match(&g);
    assert(active[KAGURA_AUDIO_INDEX(3,KAGURA_AUDIO_GAIN_L)]==24);
    g.stage_tick++;g.sound=SF_SOUND_SHOT;match(&g);
    assert(active[KAGURA_AUDIO_INDEX(3,KAGURA_AUDIO_GAIN_L)]==23);
    assert(active[KAGURA_AUDIO_INDEX(2,KAGURA_AUDIO_CONTROL)]==0); /* lower priority rejected */
    g.sound=0;for(unsigned i=0;i<30;i++) { g.stage_tick++;match(&g); }
    assert(wave_writes==2); /* all music changes are registers, never VRAM */
    scene(&g,SF_MUSIC_SPACE,0);match(&g);
    unsigned clean=commits;match(&g);assert(commits==clean);
    unsigned before=commits;scene(&g,SF_MUSIC_BOSS,40);fail=true;
    assert(sf_audio_update(&g)==KH_TIMEOUT_BUSY && commits==before);fail=false;
    assert(sf_audio_init(0)==KH_OK);before=writes;
    assert(sf_audio_update(&g)==KH_OK && writes==before);
    printf("PASS music boundaries/one-shot silence/SFX priority/stable wave banks/failure/no-audio fallback max_audio_writes=%u\n",max_frame_writes);
    return 0;
}
