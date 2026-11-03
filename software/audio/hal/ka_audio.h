// SPDX-License-Identifier: Apache-2.0
// KAGURA-9 audio HAL (docs/audio-spec.md): the six-voice synthesizer
// (pulse 0..2, noise 3, wave 4..5) behind a write cache.
//
// The HAL never touches the hardware. Calls change the wanted state;
// ka_flush() turns the difference against what the hardware holds into a
// frame: wave uploads, (index, value) register pairs and an AUDIO_COMMIT.
// The owner of the FPGA transport sends the frame in that order (the C host
// driver: ka_kagura_host.c; MicroPython: kagura.music). One owner at a
// time: anything else that writes audio registers must be followed by
// ka_invalidate(). Nothing allocates; a ka_audio is plain memory.
#ifndef KA_AUDIO_H
#define KA_AUDIO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define KA_VOICES 6
#define KA_PULSE_VOICES 3              // voices 0..2
#define KA_NOISE_VOICE 3
#define KA_WAVE_FIRST 4                // voices 4..5
#define KA_WAVE_MAX 256                // samples per wave (LEN_LOG2 5..8)
#define KA_STEP_MAX 0x7FFFFFu          // larger steps make AUDIO_COMMIT fail
#define KA_NOTES 128                   // MIDI note numbers; 69 = A4 = 440 Hz
#define KA_FINE 64                     // pitch units per semitone
#define KA_WAVE_SHADOW 0x009800u       // VRAM: wave shadow bank, voice 4 then 5
#define KA_FRAME_PAIRS 45              // a full rewrite: 3x7 pulse, 5 noise, 2x7 wave, master, 2x2 PCM stop

enum { KA_OK = 0, KA_EINVAL = -1, KA_ENOTSUP = -2 };

// One flush: the transport owner sends, in order,
//   1. for each bit of wave_mask: ka_wave_data(voice 4+bit) to
//      KA_WAVE_SHADOW + 256*bit (wave_bytes[bit] bytes);
//   2. the npairs register writes: AUDIO_REG_INDEX = pairs[2i],
//      AUDIO_REG_DATA = pairs[2i+1];
//   3. AUDIO_COMMIT if commit.
// If sending fails part way, call ka_invalidate(): the next flush rewrites
// every register and both wave banks.
typedef struct {
    uint8_t pairs[2 * KA_FRAME_PAIRS];
    uint16_t npairs;
    uint8_t wave_mask;
    uint16_t wave_bytes[2];
    bool commit;
} ka_frame;

typedef struct {
    uint8_t caps;
    uint8_t want[KA_VOICES][10];       // register offsets 0..9 per voice
    uint8_t have[KA_VOICES][10];
    uint16_t known[KA_VOICES];         // bit per offset: have[] is what the hardware holds
    uint8_t want_master, have_master;
    bool master_known;
    uint8_t retrigger;                 // voices whose next commit resets the phase
    uint8_t wave[2][KA_WAVE_MAX];
    uint8_t wave_pending[2];           // commits that still need the wave uploaded first
    bool pcm_stop;                     // next frame stops both PCM channels
    bool wave_changed;                 // a wave changed: the next frame commits even without pairs
    // Totals for measurements.
    uint32_t frames, commits, pairs_sent, wave_uploads;
} ka_audio;

// caps is the CAPS register. Without HDMI_AUDIO and WAVE the HAL refuses
// (KA_ENOTSUP). Wants silence: every voice disabled, gains 0, duty 128,
// waves zero at 32 samples, MASTER_GAIN 32; nothing is known, so the first
// flush writes everything (the recovery path after another owner or reset).
int ka_init(ka_audio *a, uint8_t caps);
void ka_invalidate(ka_audio *a);

int ka_flush(ka_audio *a, ka_frame *f);
const uint8_t *ka_wave_data(const ka_audio *a, unsigned voice);

// Voice state. Each returns KA_OK or KA_EINVAL and changes nothing on error.
int ka_set_step(ka_audio *a, unsigned voice, uint32_t step);          // pulse, wave
int ka_set_noise_period(ka_audio *a, uint16_t period);
int ka_set_duty(ka_audio *a, unsigned voice, uint8_t duty);           // pulse
int ka_set_gain(ka_audio *a, unsigned voice, uint8_t left, uint8_t right);
int ka_set_enable(ka_audio *a, unsigned voice, bool on);
int ka_retrigger(ka_audio *a, unsigned voice);   // phase / LFSR reset with the next commit
int ka_set_wave(ka_audio *a, unsigned voice, const uint8_t *samples, size_t n);   // n = 32..256, power of 2
int ka_set_master(ka_audio *a, uint8_t gain);
// Pitch: note 0..127 plus fine 0..63 sixty-fourths of a semitone.
int ka_set_pitch(ka_audio *a, unsigned voice, unsigned note, unsigned fine);
// Every voice off (gains kept); with pcm, both PCM channels STOPped too.
void ka_silence(ka_audio *a, bool pcm);

// Pure helpers.
uint32_t ka_note_step(unsigned note, unsigned fine);   // STEP; 0 if out of range
uint16_t ka_note_noise(unsigned note);                 // NOISE_PERIOD for a note
uint32_t ka_hz_step(uint32_t millihertz);               // STEP, rounded; clamped to KA_STEP_MAX

#endif
