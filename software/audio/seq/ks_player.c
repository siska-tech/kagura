// SPDX-License-Identifier: Apache-2.0
#include "ks_player.h"
#include <string.h>

#ifndef KS_FAULT
#define KS_FAULT 0      // tests: build mutants that must fail test_player
#endif

#define ENV_FULL 4096
#define PITCH_MAX (127 * 64 + 63)
#define NONE 0xFF

static int32_t note_pitch(unsigned cell_note) { return (int32_t)(cell_note + 11) * 64; }

static bool kind_fits(unsigned kind, unsigned voice) {
    if (kind == KS_KIND_PULSE) return voice < KA_PULSE_VOICES;
    if (kind == KS_KIND_NOISE) return voice == KA_NOISE_VOICE;
    return voice >= KA_WAVE_FIRST;
}

uint32_t ks_player_tick_us(unsigned tempo) {
    return tempo ? (KS_TICK_UNITS + tempo / 2) / tempo : 0;
}

void ks_player_init(ks_player *p, ka_audio *hal) {
    memset(p, 0, sizeof *p);
    p->hal = hal;
    p->voice_mask = (1u << KA_VOICES) - 1;
    p->jump_order = p->break_row = NONE;
    p->speed = 6;
    p->tempo = 125;
}

static void silence_tracks(ks_player *p) {
    for (unsigned t = 0; t < KS_TRACKS; t++) {
        ks_track *k = &p->track[t];
        k->on = k->releasing = k->preview = false;
        k->env = 0;
        if (p->song && t < p->song->tracks && (p->voice_mask >> p->song->voice[t] & 1u))
            ka_set_enable(p->hal, p->song->voice[t], false);
    }
    p->idle_ticking = false;
}

static void reset_tracks(ks_player *p) {
    for (unsigned t = 0; t < KS_TRACKS; t++) {
        ks_track *k = &p->track[t];
        memset(k, 0, sizeof *k);
        k->volume = 15 * 16;
        k->pan = 128;
        k->duty = 128;
    }
}

void ks_player_load(ks_player *p, const ks_song *song) {
    silence_tracks(p);
    p->song = song;
    p->state = KS_STOPPED;
    reset_tracks(p);
    if (song) {
        p->speed = song->speed;
        p->tempo = song->tempo;
    }
    p->order = p->row = p->tick = 0;
    p->jump_order = p->break_row = NONE;
}

void ks_player_reload(ks_player *p, const ks_song *song) {
    uint8_t state = p->state, order = p->order, row = p->row, tick = p->tick, speed = p->speed;
    uint8_t tempo = p->tempo;
    uint32_t next = p->next_us, rem = p->rem, left = p->pause_left;
    // The voices keep sounding across an edit: only validity is rechecked.
    const ks_song *old = p->song;
    bool same_tracks = old && song && old->tracks == song->tracks &&
                       !memcmp(old->voice, song->voice, song->tracks);
    if (!song || !same_tracks || order >= song->orders) {
        ks_player_load(p, song);
        return;
    }
    p->song = song;
    for (unsigned t = 0; t < song->tracks; t++)
        if (p->track[t].inst >= song->instruments) p->track[t].on = false;
    if (row >= song->rows[song->order[order]]) row = 0;
    p->state = state;
    p->order = order;
    p->row = row;
    p->tick = tick;
    p->speed = speed;
    p->tempo = tempo;
    p->next_us = next;
    p->rem = rem;
    p->pause_left = left;
}

int ks_player_play(ks_player *p, uint32_t now, unsigned mode, unsigned order, unsigned row) {
    const ks_song *s = p->song;
    if (!s || mode > KS_MODE_PATTERN || order >= s->orders || row >= s->rows[s->order[order]]) return KA_EINVAL;
    silence_tracks(p);
    reset_tracks(p);
    p->mode = (uint8_t)mode;
    p->order = (uint8_t)order;
    p->row = (uint8_t)row;
    p->tick = 0;
    p->speed = s->speed;
    p->tempo = s->tempo;
    p->jump_order = p->break_row = NONE;
    p->play_order = (uint8_t)order;
    p->play_row = (uint8_t)row;
    p->next_us = now;
    p->rem = 0;
    p->state = KS_PLAYING;
    return KA_OK;
}

void ks_player_stop(ks_player *p) {
    silence_tracks(p);
    if (p->state != KS_ENDED) p->state = KS_STOPPED;
}

void ks_player_pause(ks_player *p, uint32_t now) {
    if (p->state != KS_PLAYING) return;
    int32_t left = (int32_t)(p->next_us - now);
    p->pause_left = left > 0 ? (uint32_t)left : 0;
    p->state = KS_PAUSED;
    if (p->song)
        for (unsigned t = 0; t < p->song->tracks; t++)
            if (p->voice_mask >> p->song->voice[t] & 1u) ka_set_enable(p->hal, p->song->voice[t], false);
}

static void render(ks_player *p);

void ks_player_resume(ks_player *p, uint32_t now) {
    if (p->state != KS_PAUSED) return;
    p->state = KS_PLAYING;
    p->next_us = now + p->pause_left;
    render(p);   // the held notes sound again at once
}

void ks_player_set_mute(ks_player *p, uint8_t mask) { p->mute = mask; }

void ks_player_set_voice_mask(ks_player *p, uint8_t mask) {
    // Voices given up are silenced first; a game may then use them.
    if (p->song)
        for (unsigned t = 0; t < p->song->tracks; t++) {
            unsigned v = p->song->voice[t];
            if ((p->voice_mask >> v & 1u) && !(mask >> v & 1u)) ka_set_enable(p->hal, v, false);
        }
    p->voice_mask = mask & ((1u << KA_VOICES) - 1);
}

static void instrument(const ks_player *p, unsigned i, ks_instrument *in) {
    ks_song_instrument(p->song, i, in);
}

static void note_on(ks_player *p, unsigned t, unsigned cell_note) {
    ks_track *k = &p->track[t];
    ks_instrument in;
    instrument(p, k->inst, &in);
    unsigned v = p->song->voice[t];
    if (!kind_fits(in.kind, v)) {
        p->stats.mismatched++;
        k->on = false;
        return;
    }
    k->note = (uint8_t)(cell_note + 11);
    k->pitch = k->target = note_pitch(cell_note);
    k->on = true;
    k->releasing = false;
    k->env = 0;
    k->env_stage = 0;
    k->env_step = 0;
    k->vib_pos = 0;
    if (in.kind == KS_KIND_PULSE) k->duty = in.data ? in.data : 128;
    if (p->voice_mask >> v & 1u) {
        if (in.kind == KS_KIND_WAVE)
            ka_set_wave(p->hal, v, p->song->wave[in.data], p->song->wave_len[in.data]);
        ka_retrigger(p->hal, v);
    }
}

static void release(ks_track *k) {
    if (k->on) {
        k->releasing = true;
        k->env_stage = 3;
        k->env_step = 0;
    }
}

static void envelope(ks_player *p, ks_track *k) {
    if (!k->on) return;
    ks_instrument in;
    instrument(p, k->inst, &in);
    uint32_t sustain = (uint32_t)in.sustain * ENV_FULL / 15;
    switch (k->env_stage) {
    case 0:
        if (!in.attack || k->env + (ENV_FULL + in.attack - 1) / in.attack >= ENV_FULL) {
            k->env = ENV_FULL;
            k->env_stage = 1;
        } else {
            k->env = (uint16_t)(k->env + (ENV_FULL + in.attack - 1) / in.attack);
        }
        break;
    case 1: {
        uint32_t step = in.decay ? (ENV_FULL - sustain + in.decay - 1) / in.decay : ENV_FULL;
        if (k->env <= sustain + step) {
            k->env = (uint16_t)sustain;
            k->env_stage = 2;
        } else {
            k->env = (uint16_t)(k->env - step);
        }
        break;
    }
    case 2:
        break;
    default: {
        // A fixed step from the level at the release, so the release lasts its ticks.
        if (!k->env_step) k->env_step = in.release ? (uint16_t)((k->env + in.release - 1) / in.release) : ENV_FULL;
        if (k->env <= k->env_step) {
            k->env = 0;
            k->on = false;
            k->releasing = false;
            k->env_step = 0;
        } else {
            k->env = (uint16_t)(k->env - k->env_step);
        }
        break;
    }
    }
    if (k->env_stage != 3) k->env_step = 0;
    if (k->on && k->env_stage == 2 && k->env == 0) k->on = false;   // decayed to silence
}

static int vibrato(uint8_t pos) {
    int t = pos & 63;
    return t < 16 ? t : t < 48 ? 32 - t : t - 64;   // triangle, -16..16
}

static int32_t clamp_pitch(int32_t x) { return x < 0 ? 0 : x > PITCH_MAX ? PITCH_MAX : x; }

// Effects that act on every tick (tick 0 effects were applied with the row).
static int32_t tick_effects(ks_player *p, ks_track *k, unsigned tick) {
    int32_t offset = 0;
    uint8_t x = k->param >> 4, y = k->param & 15;
    switch (k->fx) {
    case KS_FX_ARPEGGIO:
        if (k->param) offset = (int32_t)(tick % 3 == 1 ? x : tick % 3 == 2 ? y : 0) * 64;
        break;
    case KS_FX_SLIDE_UP:
        if (tick) k->pitch = clamp_pitch(k->pitch + k->param);
        break;
    case KS_FX_SLIDE_DOWN:
        if (tick) k->pitch = clamp_pitch(k->pitch - k->param);
        break;
    case KS_FX_PORTA:
        if (tick) {
            if (k->pitch < k->target) k->pitch = k->pitch + k->param > k->target ? k->target : k->pitch + k->param;
            else if (k->pitch > k->target) k->pitch = k->pitch - k->param < k->target ? k->target : k->pitch - k->param;
        }
        break;
    case KS_FX_VIBRATO:
        offset = vibrato(k->vib_pos) * y / 4;
        k->vib_pos = (uint8_t)(k->vib_pos + x);
        break;
    case KS_FX_VOLSLIDE:
        if (tick) {
            int v = (int)k->volume + x - y;
            k->volume = (uint8_t)(v < 0 ? 0 : v > 240 ? 240 : v);
        }
        break;
    case KS_FX_CUT:
        if (tick == k->param && k->on) {
            k->on = false;
            k->env = 0;
        }
        break;
    default:
        break;
    }
    (void)p;
    return offset;
}

static void render_track(ks_player *p, unsigned t, int32_t offset) {
    ks_track *k = &p->track[t];
    unsigned v = p->song->voice[t];
    if (!(p->voice_mask >> v & 1u)) return;
    if (!k->on || (p->mute >> t & 1u)) {
        ka_set_enable(p->hal, v, false);
        return;
    }
    int32_t pitch = clamp_pitch(k->pitch + offset);
    ka_set_pitch(p->hal, v, (unsigned)(pitch >> 6), (unsigned)(pitch & 63));
    if (v < KA_PULSE_VOICES) ka_set_duty(p->hal, v, k->duty);
    // volume 0..240 (sixteenths), envelope 0..4096, pan 0..255.
    uint32_t g = ((uint32_t)k->volume * 255u / 240u) * k->env / ENV_FULL;
    uint32_t l = (255u - k->pan) * 2u + 2u, r = (uint32_t)k->pan * 2u;
    if (l > 256) l = 256;
    if (r > 256) r = 256;
#if KS_FAULT == 1
    l = r = 256;
#endif
    ka_set_gain(p->hal, v, (uint8_t)(g * l / 256u), (uint8_t)(g * r / 256u));
    ka_set_enable(p->hal, v, true);
}

static void render(ks_player *p) {
    if (!p->song) return;
    for (unsigned t = 0; t < p->song->tracks; t++) render_track(p, t, p->offset[t]);
}

static const uint8_t *row_data(const ks_song *s, unsigned pattern, unsigned row) {
    const uint8_t *q = s->pattern[pattern];
    uint8_t scratch[KS_TRACKS * KS_CELL_BYTES];
    for (unsigned r = 0; r < row; r++) q += ks_unpack_row(q, s->tracks, scratch);
    return q;
}

static void process_row(ks_player *p) {
    const ks_song *s = p->song;
    uint8_t cells[KS_TRACKS * KS_CELL_BYTES];
    p->play_order = p->order;
    p->play_row = p->row;
    ks_unpack_row(row_data(s, s->order[p->order], p->row), s->tracks, cells);
    for (unsigned t = 0; t < s->tracks; t++) {
        const uint8_t *c = cells + t * KS_CELL_BYTES;
        ks_track *k = &p->track[t];
        if (k->preview) {
            // The song takes the track back from a preview at the next row.
            k->preview = false;
            k->hold = 0;
        }
        k->fx = c[3];
        k->param = c[4];
        if (c[1] != KS_NONE) {
            ks_instrument in;
            k->inst = c[1];
            instrument(p, k->inst, &in);
            k->volume = (uint8_t)(in.volume * 16);
            k->pan = in.pan;
        }
        if (c[0] == KS_NOTE_OFF) {
            release(k);
        } else if (c[0]) {
            if (k->fx == KS_FX_PORTA && k->on) k->target = note_pitch(c[0]);
            else note_on(p, t, c[0]);
        }
        if (c[2] != KS_NONE) k->volume = (uint8_t)(c[2] * 16);
        switch (k->fx) {
        case KS_FX_DUTY: k->duty = k->param; break;
        case KS_FX_PAN: k->pan = k->param; break;
        case KS_FX_JUMP: p->jump_order = k->param; break;
        case KS_FX_BREAK: p->break_row = k->param; break;
        case KS_FX_SPEED:
            if (k->param < 32) p->speed = k->param;
            else p->tempo = k->param;
            break;
        default: break;
        }
    }
}

static void end_song(ks_player *p) {
    for (unsigned t = 0; t < p->song->tracks; t++) release(&p->track[t]);
    p->state = KS_ENDED;
    p->idle_ticking = true;   // let the releases finish
}

static void next_row(ks_player *p) {
    const ks_song *s = p->song;
    unsigned order = p->order, row = p->row + 1u;
    bool flow = p->jump_order != NONE || p->break_row != NONE;
    if (flow) {
        if (p->mode == KS_MODE_SONG && p->jump_order != NONE) order = p->jump_order;
        else if (p->mode == KS_MODE_SONG) order = order + 1u;
        row = p->break_row != NONE ? p->break_row : 0;
        p->jump_order = p->break_row = NONE;
    } else if (row >= s->rows[s->order[order]]) {
        row = 0;
        if (p->mode == KS_MODE_SONG) order++;
    }
    if (order >= s->orders) {
        if (!(s->flags & KS_FLAG_LOOP)) {
            end_song(p);
            return;
        }
        order = s->loop_order;
    }
    if (row >= s->rows[s->order[order]]) row = 0;
    p->order = (uint8_t)order;
    p->row = (uint8_t)row;
}

static void run_tick(ks_player *p) {
    const ks_song *s = p->song;
    bool playing = p->state == KS_PLAYING;
    if (playing && p->tick == 0) process_row(p);
    for (unsigned t = 0; t < s->tracks; t++) {
        ks_track *k = &p->track[t];
        p->offset[t] = tick_effects(p, k, playing ? p->tick : 1u);
        envelope(p, k);
        if (k->preview && k->hold && !--k->hold) release(k);
    }
    render(p);
    p->stats.ticks++;
    if (playing && ++p->tick >= p->speed) {
        p->tick = 0;
        next_row(p);
    }
}

static void schedule(ks_player *p) {
    uint32_t tempo = p->tempo;
    p->next_us += KS_TICK_UNITS / tempo;
    p->rem += KS_TICK_UNITS % tempo;
#if KS_FAULT != 2
    if (p->rem >= tempo) {
        p->next_us++;
        p->rem -= tempo;
    }
#endif
}

static bool sounding(const ks_player *p) {
    if (!p->song) return false;
    for (unsigned t = 0; t < p->song->tracks; t++)
        if (p->track[t].on) return true;
    return false;
}

unsigned ks_player_advance(ks_player *p, uint32_t now) {
    if (!p->song || !(p->state == KS_PLAYING || p->idle_ticking)) return 0;
    int32_t late = (int32_t)(now - p->next_us);
    if (late < 0) return 0;
    if ((uint32_t)late > KS_CATCH_UP_US) {
        p->next_us = now;
        p->rem = 0;
        p->stats.resyncs++;
        late = 0;
    }
    unsigned n = 0;
    uint8_t tempo = p->tempo;
    while ((int32_t)(now - p->next_us) >= 0 && (p->state == KS_PLAYING || p->idle_ticking)) {
        run_tick(p);
        if (p->tempo != tempo) {   // Fxx: the new period starts from this tick
            p->rem = 0;
            tempo = p->tempo;
        }
        schedule(p);
        n++;
        if (p->state != KS_PLAYING && p->idle_ticking && !sounding(p)) p->idle_ticking = false;
    }
    p->stats.calls++;
    p->stats.folded += n - 1;
    if ((uint32_t)late > p->stats.late_max_us) p->stats.late_max_us = (uint32_t)late;
    p->stats.late_sum_us += (uint32_t)late;
    return n;
}

int ks_player_preview(ks_player *p, uint32_t now, unsigned track, unsigned note, unsigned inst, unsigned hold) {
    const ks_song *s = p->song;
    if (!s || track >= s->tracks || note < 1 || note > 96 || inst >= s->instruments) return KA_EINVAL;
    ks_track *k = &p->track[track];
    ks_instrument in;
    instrument(p, inst, &in);
    if (!kind_fits(in.kind, s->voice[track])) return KA_EINVAL;   // changes nothing
    k->inst = (uint8_t)inst;
    k->volume = (uint8_t)(in.volume * 16);
    k->pan = in.pan;
    k->fx = k->param = 0;
    note_on(p, track, note);
    k->preview = true;
    k->hold = (uint16_t)(hold ? hold : 1);
    if (p->state != KS_PLAYING && !p->idle_ticking) {
        p->idle_ticking = true;
        p->next_us = now;
        p->rem = 0;
    }
    return KA_OK;
}
