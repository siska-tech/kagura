// SPDX-License-Identifier: Apache-2.0
#ifndef STARFALL_MUSIC_H
#define STARFALL_MUSIC_H
#include "starfall.h"
enum { SF_MUSIC_TITLE, SF_MUSIC_SPACE, SF_MUSIC_ENTRY, SF_MUSIC_BASE,
    SF_MUSIC_WARNING, SF_MUSIC_BOSS, SF_MUSIC_ESCAPE, SF_MUSIC_CLEAR, SF_MUSIC_OVER,
    SF_MUSIC_DEMO,SF_MUSIC_COUNT };
typedef struct {
    uint16_t hz[4],drum_period;
    uint8_t gain[4],duty[2],drum_gain,cue;
    uint32_t tick;
} SfMusic;
unsigned sf_music_cue(const SfGame *g);
const char *sf_music_name(unsigned cue);
void sf_music_render(const SfGame *g,SfMusic *frame);
#endif
