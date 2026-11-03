// SPDX-License-Identifier: Apache-2.0
// Deterministic KSNG player on top of the audio HAL.
//
// Time is the caller's microsecond clock (uint32, wrapping). Ticks fall at
// exact times: tick k of a run at tempo T is due at start + floor(k *
// 2,500,000 / T) us, kept with an integer remainder, so tempo does not drift
// however late or often ks_player_advance() is called. A late call runs
// every due tick in order (the music state is exact) and the HAL sends the
// final state once; the lateness is recorded in ks_stats.
//
// The player only changes the HAL's wanted state for its tracks' voices;
// the caller flushes the HAL and sends the frame after advancing.
#ifndef KS_PLAYER_H
#define KS_PLAYER_H

#include <stdbool.h>
#include <stdint.h>
#include "ka_audio.h"
#include "ks_song.h"

#define KS_CATCH_UP_US 250000u         // further behind than this: resynchronise
#define KS_TICK_UNITS 2500000u         // tick period = KS_TICK_UNITS / tempo us

enum { KS_STOPPED = 0, KS_PLAYING = 1, KS_PAUSED = 2, KS_ENDED = 3 };
enum { KS_MODE_SONG = 0, KS_MODE_PATTERN = 1 };

typedef struct {
    bool on;               // voice is sounding (attack .. release)
    bool releasing;
    bool preview;          // started by ks_player_preview
    uint8_t inst;          // current instrument
    uint8_t note;          // MIDI note of the last note-on
    uint8_t volume;        // 0..15
    uint8_t pan;           // 0 left, 128 centre, 255 right
    uint8_t duty;
    uint16_t env;          // envelope level, 0..4096
    uint16_t env_step;     // per tick in the current stage
    uint8_t env_stage;     // 0 attack, 1 decay, 2 sustain, 3 release
    int32_t pitch;         // note * 64 + fine
    int32_t target;        // tone portamento target
    uint8_t fx, param;     // effect of the current row
    uint8_t vib_pos;
    uint8_t vol_frac;      // volume slide, sixteenths of a step
    uint16_t hold;         // preview: ticks before release
} ks_track;

typedef struct {
    uint32_t ticks;        // ticks run
    uint32_t calls;        // advance calls that ran at least one tick
    uint32_t late_max_us;  // largest lateness of the first due tick in a call
    uint64_t late_sum_us;
    uint32_t folded;       // ticks run as the second or later in one call
    uint32_t resyncs;      // KS_CATCH_UP_US exceeded: ticks skipped forward
    uint32_t mismatched;   // notes whose instrument kind does not fit the voice
} ks_stats;

typedef struct {
    ka_audio *hal;
    const ks_song *song;   // NULL: none loaded (preview still works with ks_player_bind)
    uint8_t state, mode;
    uint8_t speed, tempo;
    uint8_t order, row, tick;        // the next tick to run
    uint8_t play_order, play_row;    // the row sounding now (for display)
    uint8_t jump_order, break_row;   // pending flow from the row: 0xFF none
    uint8_t mute;          // bit per track
    uint8_t voice_mask;    // HAL voices the player may write
    uint32_t next_us;      // when the next tick is due
    uint32_t rem;          // remainder of the tick period, in 1/tempo us
    uint32_t pause_left;   // us to the next tick when paused
    bool idle_ticking;     // ticking for previews while stopped
    ks_track track[KS_TRACKS];
    int32_t offset[KS_TRACKS];   // pitch offset of the last tick (arpeggio, vibrato)
    ks_stats stats;
} ks_player;

void ks_player_init(ks_player *p, ka_audio *hal);
// Song (validated by ks_song_parse) or NULL. Stops playback.
void ks_player_load(ks_player *p, const ks_song *song);
// Replaces the song while keeping the position (order, row, tick) and the
// timing if it is still valid in the new song: edits during playback.
void ks_player_reload(ks_player *p, const ks_song *song);
int ks_player_play(ks_player *p, uint32_t now, unsigned mode, unsigned order, unsigned row);
void ks_player_stop(ks_player *p);       // releases nothing: silences the player's voices
void ks_player_pause(ks_player *p, uint32_t now);
void ks_player_resume(ks_player *p, uint32_t now);
// Runs the ticks due at now; returns how many ran.
unsigned ks_player_advance(ks_player *p, uint32_t now);
// A note on a track outside the song's flow (instrument preview). note is a
// cell note (1..96); hold is in ticks. Works while stopped or playing.
int ks_player_preview(ks_player *p, uint32_t now, unsigned track, unsigned note, unsigned inst, unsigned hold);
void ks_player_set_mute(ks_player *p, uint8_t mask);
void ks_player_set_voice_mask(ks_player *p, uint8_t mask);
uint32_t ks_player_tick_us(unsigned tempo);   // rounded, for display

#endif
