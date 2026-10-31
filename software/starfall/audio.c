// SPDX-License-Identifier: Apache-2.0
// Scene scores and SFX share the existing six-channel hardware synthesizer.
#include "backend.h"
#include "music.h"
#include <string.h>
#define TRY(x) do { kh_status s_=(x);if(s_!=KH_OK)return s_; } while(0)
static uint8_t cache[6][10],priority,remaining,last_state;
static bool enabled,dirty;
static kh_status field(unsigned ch,unsigned off,uint8_t value) {
    if(cache[ch][off]==value)return KH_OK;
    TRY(kh_audio_write((uint8_t)KAGURA_AUDIO_INDEX(ch,off),value));
    cache[ch][off]=value;dirty=true;return KH_OK;
}
static kh_status voice(unsigned ch,unsigned hz,unsigned gain) {
    uint32_t step=(uint32_t)(((uint64_t)hz*16777216u+24000)/48000);
    TRY(field(ch,KAGURA_AUDIO_STEP_L,(uint8_t)step));
    TRY(field(ch,KAGURA_AUDIO_STEP_M,(uint8_t)(step>>8)));
    TRY(field(ch,KAGURA_AUDIO_STEP_H,(uint8_t)(step>>16)));
    TRY(field(ch,KAGURA_AUDIO_GAIN_L,(uint8_t)gain));
    TRY(field(ch,KAGURA_AUDIO_GAIN_R,(uint8_t)gain));
    return field(ch,KAGURA_AUDIO_CONTROL,gain?KAGURA_AUDIO_CONTROL_ENABLE:0);
}
kh_status sf_audio_init(uint8_t caps) {
    enabled=(caps&(KAGURA_CAPS_HDMI_AUDIO|KAGURA_CAPS_WAVE))==(KAGURA_CAPS_HDMI_AUDIO|KAGURA_CAPS_WAVE);
    if(!enabled)return KH_OK;
    memset(cache,255,sizeof cache);priority=0;remaining=0;last_state=255;dirty=false;
    for(unsigned ch=0;ch<6;ch++)TRY(field(ch,KAGURA_AUDIO_CONTROL,0));
    if(caps&KAGURA_CAPS_PSRAM)for(unsigned p=0;p<2;p++)
        TRY(kh_audio_write((uint8_t)KAGURA_AUDIO_PCM_INDEX(p,KAGURA_AUDIO_PCM_CONTROL),0));
    TRY(kh_audio_write(KAGURA_AUDIO_MASTER_GAIN,24));
    for(unsigned ch=0;ch<3;ch++)TRY(field(ch,KAGURA_AUDIO_DUTY,ch==2?64:128));
    TRY(field(4,KAGURA_AUDIO_LEN_LOG2,5));TRY(field(5,KAGURA_AUDIO_LEN_LOG2,5));
    uint8_t wave[512];memset(wave,0,sizeof wave);
    for(unsigned ch=0;ch<2;ch++)for(int i=0;i<32;i++)wave[ch*256+i]=(uint8_t)(int8_t)(i<16?-96+i*12:96-(i-16)*12);
    for(unsigned bank=0;bank<2;bank++) {
        TRY(kh_vram_write(KAGURA_VRAM_WAVE_BASE,wave,sizeof wave));
        TRY(kh_audio_commit(KH_DEFAULT_TIMEOUT_US));
    }return KH_OK;
}
kh_status sf_audio_update(const SfGame *g) {
    if(!enabled)return KH_OK;
    dirty=false;
    if(last_state!=g->state) { priority=remaining=0;last_state=g->state; }
    SfMusic music;sf_music_render(g,&music);
    static const uint8_t channels[4]={0,1,4,5};
    for(unsigned v=0;v<4;v++)TRY(voice(channels[v],music.hz[v],music.gain[v]));
    TRY(field(0,KAGURA_AUDIO_DUTY,music.duty[0]));TRY(field(1,KAGURA_AUDIO_DUTY,music.duty[1]));
    if(g->sound && g->sound>=priority) {
        priority=g->sound;remaining=priority==SF_SOUND_SHOT?3:priority==SF_SOUND_HIT?24:14;
    }
    bool noise=remaining && (priority==SF_SOUND_KILL || priority==SF_SOUND_HIT);
    if(remaining) {
        if(noise) {
            TRY(voice(2,0,0));
            TRY(field(3,KAGURA_AUDIO_NOISE_PERIOD_L,(uint8_t)(32+(24-remaining)*3)));
            TRY(field(3,KAGURA_AUDIO_NOISE_PERIOD_H,0));
            TRY(field(3,KAGURA_AUDIO_GAIN_L,remaining));TRY(field(3,KAGURA_AUDIO_GAIN_R,remaining));
            TRY(field(3,KAGURA_AUDIO_CONTROL,KAGURA_AUDIO_CONTROL_ENABLE));
        }else {
            TRY(voice(2,priority==SF_SOUND_SHOT?1400-remaining*160:
                priority==SF_SOUND_WARN?330+(remaining%4)*110:600+(14-remaining)*60,12));
        }
        remaining--;
    } else {
        priority=0;TRY(voice(2,0,0));
    }
    if(!noise) {
        TRY(field(3,KAGURA_AUDIO_NOISE_PERIOD_L,(uint8_t)music.drum_period));
        TRY(field(3,KAGURA_AUDIO_NOISE_PERIOD_H,(uint8_t)(music.drum_period>>8)));
        TRY(field(3,KAGURA_AUDIO_GAIN_L,music.drum_gain));TRY(field(3,KAGURA_AUDIO_GAIN_R,music.drum_gain));
        TRY(field(3,KAGURA_AUDIO_CONTROL,music.drum_gain?KAGURA_AUDIO_CONTROL_ENABLE:0));
    }
    if(dirty)return kh_audio_commit(KH_DEFAULT_TIMEOUT_US);
    return KH_OK;
}
