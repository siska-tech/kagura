// SPDX-License-Identifier: Apache-2.0
// kagura_audio: MicroPython binding of the audio HAL and the KSNG player
// (software/audio/README.md). One audio owner, so the state is static and
// module-level. It never touches the hardware: flush() returns a frame that
// the transport owner sends (kagura.music.AudioSession does).
//
// Songs are copied into a private GC block reachable from a root pointer, so
// the caller may change or drop its buffer. A soft reset drops everything
// (kagura_audio_soft_reset, the board's MICROPY_BOARD_START_SOFT_RESET), and
// every call but init() then raises until init() is called again.
#include <string.h>

#include "py/mperrno.h"
#include "py/mphal.h"
#include "py/runtime.h"

#include "ka_audio.h"
#include "ka_render.h"
#include "ks_player.h"
#include "ks_song.h"

static struct {
    bool ready;
    uint8_t current;            // which song[] the player uses
    ka_audio hal;
    ka_frame frame;
    ks_player player;
    ks_song song[2];
} state;

MP_REGISTER_ROOT_POINTER(void *kagura_audio_song[2]);

void kagura_audio_soft_reset(void) {
    state.ready = false;
    state.player.song = NULL;
    MP_STATE_VM(kagura_audio_song)[0] = MP_STATE_VM(kagura_audio_song)[1] = NULL;
}

static void need_ready(void) {
    if (!state.ready) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("kagura_audio: call init(caps) first"));
}

static void check(int rc) {
    if (rc < 0) mp_raise_ValueError(MP_ERROR_TEXT("invalid argument"));
}

static uint32_t now_arg(size_t n_args, const mp_obj_t *args, size_t i) {
    if (n_args > i && args[i] != mp_const_none) return (uint32_t)mp_obj_get_int_truncated(args[i]);
    return (uint32_t)mp_hal_ticks_us();
}

static unsigned uint_arg(mp_obj_t o, unsigned max) {
    mp_int_t v = mp_obj_get_int(o);
    if (v < 0 || (mp_uint_t)v > max) mp_raise_ValueError(MP_ERROR_TEXT("value out of range"));
    return (unsigned)v;
}

// --- session ------------------------------------------------------------

static mp_obj_t mod_init(mp_obj_t caps_in) {
    unsigned caps = uint_arg(caps_in, 255);
    kagura_audio_soft_reset();
    memset(&state, 0, sizeof state);
    if (ka_init(&state.hal, (uint8_t)caps) != KA_OK) mp_raise_OSError(MP_ENODEV);
    ks_player_init(&state.player, &state.hal);
    state.ready = true;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_init_obj, mod_init);

// Wants silence (every voice off, PCM stopped) and drops the song; the
// caller flushes and sends once more. The session ends with deinit().
static mp_obj_t mod_close(void) {
    need_ready();
    ks_player_load(&state.player, NULL);
    ka_silence(&state.hal, true);
    MP_STATE_VM(kagura_audio_song)[0] = MP_STATE_VM(kagura_audio_song)[1] = NULL;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_close_obj, mod_close);

static mp_obj_t mod_deinit(void) {
    kagura_audio_soft_reset();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_deinit_obj, mod_deinit);

// flush(pairs) -> int: writes the frame's (index, value) pairs into pairs (a
// writable buffer of at least 2 * FRAME_PAIRS bytes) and returns
//   bits 0..5 npairs, bit 6 commit, bits 8..9 wave_mask,
//   bits 10..11 and 12..13: LEN_LOG2 - 5 of wave 4 and 5.
// 0 means nothing to send. Allocates nothing.
static mp_obj_t mod_flush(mp_obj_t pairs_in) {
    need_ready();
    mp_buffer_info_t bi;
    mp_get_buffer_raise(pairs_in, &bi, MP_BUFFER_WRITE);
    if (bi.len < sizeof state.frame.pairs) mp_raise_ValueError(MP_ERROR_TEXT("pairs buffer too small"));
    ka_frame *f = &state.frame;
    ka_flush(&state.hal, f);
    memcpy(bi.buf, f->pairs, 2u * f->npairs);
    mp_int_t r = f->npairs | (f->commit ? 0x40 : 0) | f->wave_mask << 8;
    for (unsigned w = 0; w < 2; w++)
        if (f->wave_mask >> w & 1u) r |= (mp_int_t)(__builtin_ctz(f->wave_bytes[w]) - 5) << (10 + 2 * w);
    return MP_OBJ_NEW_SMALL_INT(r);
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_flush_obj, mod_flush);

static mp_obj_t mod_invalidate(void) {
    need_ready();
    ka_invalidate(&state.hal);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_invalidate_obj, mod_invalidate);

// wave(voice) -> memoryview of the HAL's 256-byte wave of voice 4 or 5 (the
// bytes a frame uploads). Valid until the next init().
static mp_obj_t mod_wave(mp_obj_t voice_in) {
    need_ready();
    unsigned v = uint_arg(voice_in, KA_VOICES - 1);
    if (v < KA_WAVE_FIRST) mp_raise_ValueError(MP_ERROR_TEXT("wave voices are 4 and 5"));
    return mp_obj_new_memoryview('B', KA_WAVE_MAX, state.hal.wave[v - KA_WAVE_FIRST]);
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_wave_obj, mod_wave);

// --- HAL ------------------------------------------------------------------

static mp_obj_t mod_pitch(size_t n_args, const mp_obj_t *args) {
    need_ready();
    unsigned fine = n_args > 2 ? uint_arg(args[2], KA_FINE - 1) : 0;
    check(ka_set_pitch(&state.hal, uint_arg(args[0], KA_VOICES - 1), uint_arg(args[1], KA_NOTES - 1), fine));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_pitch_obj, 2, 3, mod_pitch);

static mp_obj_t mod_step(mp_obj_t voice, mp_obj_t step) {
    need_ready();
    check(ka_set_step(&state.hal, uint_arg(voice, KA_VOICES - 1), uint_arg(step, KA_STEP_MAX)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(mod_step_obj, mod_step);

static mp_obj_t mod_noise(mp_obj_t period) {
    need_ready();
    check(ka_set_noise_period(&state.hal, (uint16_t)uint_arg(period, 65535)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_noise_obj, mod_noise);

static mp_obj_t mod_duty(mp_obj_t voice, mp_obj_t duty) {
    need_ready();
    check(ka_set_duty(&state.hal, uint_arg(voice, KA_VOICES - 1), (uint8_t)uint_arg(duty, 255)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(mod_duty_obj, mod_duty);

static mp_obj_t mod_gain(mp_obj_t voice, mp_obj_t left, mp_obj_t right) {
    need_ready();
    check(ka_set_gain(&state.hal, uint_arg(voice, KA_VOICES - 1), (uint8_t)uint_arg(left, 255),
                      (uint8_t)uint_arg(right, 255)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(mod_gain_obj, mod_gain);

static mp_obj_t mod_enable(mp_obj_t voice, mp_obj_t on) {
    need_ready();
    check(ka_set_enable(&state.hal, uint_arg(voice, KA_VOICES - 1), mp_obj_is_true(on)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(mod_enable_obj, mod_enable);

static mp_obj_t mod_retrigger(mp_obj_t voice) {
    need_ready();
    check(ka_retrigger(&state.hal, uint_arg(voice, KA_VOICES - 1)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_retrigger_obj, mod_retrigger);

static mp_obj_t mod_set_wave(mp_obj_t voice, mp_obj_t data) {
    need_ready();
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    check(ka_set_wave(&state.hal, uint_arg(voice, KA_VOICES - 1), bi.buf, bi.len));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(mod_set_wave_obj, mod_set_wave);

static mp_obj_t mod_master(mp_obj_t gain) {
    need_ready();
    ka_set_master(&state.hal, (uint8_t)uint_arg(gain, 255));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_master_obj, mod_master);

static mp_obj_t mod_silence(size_t n_args, const mp_obj_t *args) {
    need_ready();
    ka_silence(&state.hal, n_args ? mp_obj_is_true(args[0]) : true);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_silence_obj, 0, 1, mod_silence);

// render(voices, buf, span): a synthesized picture of what the HAL wants the
// voices (bit mask) to play: len(buf) signed points over span 48 kHz
// samples, each voice from phase 0. An estimate for display, not the
// hardware's output. Returns the mask of voices drawn. Allocates nothing.
static mp_obj_t mod_render(mp_obj_t voices, mp_obj_t buf, mp_obj_t span) {
    need_ready();
    mp_buffer_info_t bi;
    mp_get_buffer_raise(buf, &bi, MP_BUFFER_WRITE);
    unsigned drawn = ka_render(&state.hal, (uint8_t)uint_arg(voices, 63), bi.buf, (unsigned)bi.len,
                               uint_arg(span, 48000));
    return MP_OBJ_NEW_SMALL_INT(drawn);
}
static MP_DEFINE_CONST_FUN_OBJ_3(mod_render_obj, mod_render);

static mp_obj_t mod_note_step(size_t n_args, const mp_obj_t *args) {
    unsigned fine = n_args > 1 ? uint_arg(args[1], KA_FINE - 1) : 0;
    return mp_obj_new_int_from_uint(ka_note_step(uint_arg(args[0], KA_NOTES - 1), fine));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_note_step_obj, 1, 2, mod_note_step);

// --- songs ----------------------------------------------------------------

static MP_NORETURN void raise_song(int err) {
    mp_raise_msg_varg(&mp_type_ValueError, MP_ERROR_TEXT("KSNG: %s"), ks_strerror(err));
}

// validate(data): raises ValueError('KSNG: <reason>') unless data is a valid song.
static mp_obj_t mod_validate(mp_obj_t data) {
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    ks_song s;
    int err = ks_song_parse(&s, bi.buf, bi.len);
    if (err) raise_song(err);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_validate_obj, mod_validate);

// load(data): validates and copies the song. While playing, the position and
// timing are kept if the new song has the same tracks (edits during playback).
static mp_obj_t mod_load(mp_obj_t data) {
    need_ready();
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    ks_song check_song;
    int err = ks_song_parse(&check_song, bi.buf, bi.len);
    if (err) raise_song(err);
    uint8_t *copy = m_new(uint8_t, bi.len);   // may raise: nothing changed yet
    memcpy(copy, bi.buf, bi.len);
    unsigned next = state.current ^ 1u;
    ks_song_parse(&state.song[next], copy, bi.len);
    MP_STATE_VM(kagura_audio_song)[next] = copy;
    ks_player_reload(&state.player, &state.song[next]);
    state.current = (uint8_t)next;
    MP_STATE_VM(kagura_audio_song)[next ^ 1u] = NULL;   // the old copy is garbage now
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_load_obj, mod_load);

static const ks_song *loaded(void) {
    need_ready();
    if (!state.player.song) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("kagura_audio: no song loaded"));
    return state.player.song;
}

// play(mode=SONG, order=0, row=0, now=None)
static mp_obj_t mod_play(size_t n_args, const mp_obj_t *args) {
    loaded();
    unsigned mode = n_args > 0 ? uint_arg(args[0], KS_MODE_PATTERN) : KS_MODE_SONG;
    unsigned order = n_args > 1 ? uint_arg(args[1], KS_ORDERS - 1) : 0;
    unsigned row = n_args > 2 ? uint_arg(args[2], 63) : 0;
    check(ks_player_play(&state.player, now_arg(n_args, args, 3), mode, order, row));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_play_obj, 0, 4, mod_play);

static mp_obj_t mod_stop(void) {
    need_ready();
    ks_player_stop(&state.player);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_stop_obj, mod_stop);

static mp_obj_t mod_pause(size_t n_args, const mp_obj_t *args) {
    need_ready();
    ks_player_pause(&state.player, now_arg(n_args, args, 0));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_pause_obj, 0, 1, mod_pause);

static mp_obj_t mod_resume(size_t n_args, const mp_obj_t *args) {
    need_ready();
    ks_player_resume(&state.player, now_arg(n_args, args, 0));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_resume_obj, 0, 1, mod_resume);

// advance(now=None) -> ticks run. Allocates nothing.
static mp_obj_t mod_advance(size_t n_args, const mp_obj_t *args) {
    need_ready();
    return MP_OBJ_NEW_SMALL_INT(ks_player_advance(&state.player, now_arg(n_args, args, 0)));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_advance_obj, 0, 1, mod_advance);

// preview(track, note, inst, hold=24, now=None): note 1..96, hold in ticks.
static mp_obj_t mod_preview(size_t n_args, const mp_obj_t *args) {
    loaded();
    unsigned hold = n_args > 3 ? uint_arg(args[3], 65535) : 24;
    int rc = ks_player_preview(&state.player, now_arg(n_args, args, 4), uint_arg(args[0], KS_TRACKS - 1),
                               uint_arg(args[1], 255), uint_arg(args[2], 255), hold);
    return mp_obj_new_bool(rc == KA_OK);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_preview_obj, 3, 5, mod_preview);

static mp_obj_t mod_mute(mp_obj_t mask) {
    need_ready();
    ks_player_set_mute(&state.player, (uint8_t)uint_arg(mask, 63));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_mute_obj, mod_mute);

static mp_obj_t mod_voices(mp_obj_t mask) {
    need_ready();
    ks_player_set_voice_mask(&state.player, (uint8_t)uint_arg(mask, 63));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_voices_obj, mod_voices);

// position() -> state << 24 | order << 16 | row << 8 | tick: the row sounding
// now and the next tick to run. Allocates nothing.
static mp_obj_t mod_position(void) {
    need_ready();
    const ks_player *p = &state.player;
    return MP_OBJ_NEW_SMALL_INT((mp_int_t)p->state << 24 | p->play_order << 16 | p->play_row << 8 | p->tick);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_position_obj, mod_position);

static mp_obj_t mod_stats(void) {
    need_ready();
    const ks_stats *s = &state.player.stats;
    const ka_audio *a = &state.hal;
    mp_obj_t d = mp_obj_new_dict(12);
#define ITEM(name, value) mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_##name), mp_obj_new_int_from_ull(value))
    ITEM(ticks, s->ticks);
    ITEM(calls, s->calls);
    ITEM(late_max_us, s->late_max_us);
    ITEM(late_sum_us, s->late_sum_us);
    ITEM(folded, s->folded);
    ITEM(resyncs, s->resyncs);
    ITEM(mismatched, s->mismatched);
    ITEM(frames, a->frames);
    ITEM(commits, a->commits);
    ITEM(pairs, a->pairs_sent);
    ITEM(wave_uploads, a->wave_uploads);
    ITEM(tempo, state.player.tempo);
#undef ITEM
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_stats_obj, mod_stats);

static mp_obj_t mod_reset_stats(void) {
    need_ready();
    memset(&state.player.stats, 0, sizeof state.player.stats);
    state.hal.frames = state.hal.commits = state.hal.pairs_sent = state.hal.wave_uploads = 0;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_reset_stats_obj, mod_reset_stats);

// pack(cells, rows, tracks, instruments) -> bytes: unpacked cells (5 bytes:
// note, inst, vol, fx, param) to KSNG packed rows. ValueError if a cell is invalid.
static mp_obj_t mod_pack(size_t n_args, const mp_obj_t *args) {
    (void)n_args;
    mp_buffer_info_t bi;
    mp_get_buffer_raise(args[0], &bi, MP_BUFFER_READ);
    unsigned rows = uint_arg(args[1], 64), tracks = uint_arg(args[2], KS_TRACKS);
    unsigned instruments = uint_arg(args[3], KS_INSTRUMENTS);
    if (!rows || !tracks || bi.len < (size_t)rows * tracks * KS_CELL_BYTES)
        mp_raise_ValueError(MP_ERROR_TEXT("cells too short"));
    // A cell packs to at most 6 bytes.
    size_t cap = (size_t)rows * tracks * 6;
    vstr_t v;
    vstr_init_len(&v, cap);
    size_t n = ks_pack(bi.buf, rows, tracks, instruments, (uint8_t *)v.buf, cap);
    if (!n) {
        vstr_clear(&v);
        mp_raise_ValueError(MP_ERROR_TEXT("invalid cell"));
    }
    v.len = n;
    return mp_obj_new_bytes_from_vstr(&v);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_pack_obj, 4, 4, mod_pack);

// unpack_into(data, offset, rows, tracks, instruments, cells) -> bytes consumed.
// Checked: ValueError if the packed rows are invalid or run past data.
static mp_obj_t mod_unpack_into(size_t n_args, const mp_obj_t *args) {
    (void)n_args;
    mp_buffer_info_t src, dst;
    mp_get_buffer_raise(args[0], &src, MP_BUFFER_READ);
    size_t offset = uint_arg(args[1], src.len);
    unsigned rows = uint_arg(args[2], 64), tracks = uint_arg(args[3], KS_TRACKS);
    unsigned instruments = uint_arg(args[4], KS_INSTRUMENTS);
    mp_get_buffer_raise(args[5], &dst, MP_BUFFER_WRITE);
    if (dst.len < (size_t)rows * tracks * KS_CELL_BYTES) mp_raise_ValueError(MP_ERROR_TEXT("cells too short"));
    size_t n = ks_unpack((const uint8_t *)src.buf + offset, src.len - offset, rows, tracks, instruments, dst.buf);
    if (!n) mp_raise_ValueError(MP_ERROR_TEXT("KSNG: pattern"));
    return MP_OBJ_NEW_SMALL_INT((mp_int_t)n);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_unpack_into_obj, 6, 6, mod_unpack_into);

static mp_obj_t mod_sizes(void) {
    mp_obj_t d = mp_obj_new_dict(4);
    mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_state), MP_OBJ_NEW_SMALL_INT(sizeof state));
    mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_hal), MP_OBJ_NEW_SMALL_INT(sizeof(ka_audio)));
    mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_player), MP_OBJ_NEW_SMALL_INT(sizeof(ks_player)));
    mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_frame), MP_OBJ_NEW_SMALL_INT(sizeof(ka_frame)));
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_sizes_obj, mod_sizes);

#define FUN(name) {MP_ROM_QSTR(MP_QSTR_##name), MP_ROM_PTR(&mod_##name##_obj)}
#define CONST(name, value) {MP_ROM_QSTR(MP_QSTR_##name), MP_ROM_INT(value)}

static const mp_rom_map_elem_t module_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_kagura_audio)},
    FUN(init), FUN(close), FUN(deinit), FUN(flush), FUN(invalidate), FUN(wave),
    FUN(pitch), FUN(step), FUN(noise), FUN(duty), FUN(gain), FUN(enable), FUN(retrigger),
    FUN(set_wave), FUN(master), FUN(silence), FUN(note_step), FUN(render),
    FUN(validate), FUN(load), FUN(play), FUN(stop), FUN(pause), FUN(resume), FUN(advance),
    FUN(preview), FUN(mute), FUN(voices), FUN(position), FUN(stats), FUN(reset_stats),
    FUN(pack), FUN(unpack_into), FUN(sizes),
    CONST(FRAME_PAIRS, KA_FRAME_PAIRS), CONST(WAVE_SHADOW, KA_WAVE_SHADOW), CONST(VOICES, KA_VOICES),
    CONST(SONG, KS_MODE_SONG), CONST(PATTERN, KS_MODE_PATTERN),
    CONST(STOPPED, KS_STOPPED), CONST(PLAYING, KS_PLAYING), CONST(PAUSED, KS_PAUSED), CONST(ENDED, KS_ENDED),
    CONST(NOTE_OFF, KS_NOTE_OFF), CONST(NONE, KS_NONE), CONST(CELL_BYTES, KS_CELL_BYTES),
    CONST(TRACKS, KS_TRACKS), CONST(INSTRUMENTS, KS_INSTRUMENTS), CONST(WAVES, KS_WAVES),
    CONST(PATTERNS, KS_PATTERNS), CONST(ORDERS, KS_ORDERS), CONST(MAX_BYTES, KS_MAX_BYTES),
    CONST(FX_VALID, KS_FX_VALID),
};
static MP_DEFINE_CONST_DICT(module_globals, module_table);

const mp_obj_module_t kagura_audio_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_kagura_audio, kagura_audio_module);
