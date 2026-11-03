# SPDX-License-Identifier: Apache-2.0
# 神楽トラッカー (examples/desktop_tracker.py) on the unix port: editing keys,
# the composed demo song, files, guards and playback, without hardware.
#   MICROPYPATH=software/micropython:software/micropython/examples micropython test_tracker.py DIR
import os
import sys

import kagura_audio as ka
import kagura_desktop as kd
import desktop_tracker as T
from kagura.music import AudioSession, Song, NOTE_OFF, NONE

folder = sys.argv[1]
failures = []


def check(cond, what):
    if not cond:
        failures.append(what)
        print('FAIL', what)


class Clock:
    """The player's time, moved by the test."""
    t = 0

    def __call__(self):
        return self.t


def fresh(sub):
    path = folder + '/' + sub
    try:
        os.mkdir(path)
    except OSError:
        pass
    desk = T.HostDesktop(T.MENUS)
    dev = T.NullAudioDevice()
    audio = AudioSession(dev, Clock())
    desk.audio = audio
    app = T.Tracker(desk, audio, T.SongFiles(path), 'テスト')
    return desk, audio, app, dev


def key(app, code, ch=0, mods=0):
    app.desk.key(code, ch, mods)
    app.handle()
    app.desk.present()


def typ(app, s, mods=0):
    for c in s:
        key(app, kd.KEY_CHAR, c, mods)


def cell(app, row=None, track=None):
    p = app.pattern
    o = p.offset(app.row if row is None else row, app.track if track is None else track)
    return tuple(p.cells[o:o + 5])


def test_note_entry():
    desk, audio, app, dev = fresh('notes')
    typ(app, 'z')                                   # C of octave 4: cell note 49
    check(cell(app, 0) == (49, 0, NONE, 0, 0), 'C-4 with instrument 00: %r' % (cell(app, 0),))
    check(app.row == 1, 'the cursor steps down')
    check(dev.commits > 1, 'the note was previewed on the hardware')
    typ(app, 'q')                                   # octave up
    check(cell(app, 1)[0] == 61, 'q is C-5')
    typ(app, ']')
    typ(app, 'm')
    check(cell(app, 2)[0] == 5 * 12 + 11 + 1, 'B-5 after ]')
    typ(app, '1')
    check(cell(app, 3)[0] == NOTE_OFF, 'note off')
    key(app, kd.KEY_UP)
    key(app, kd.KEY_DELETE)
    check(cell(app, 3) == (0, NONE, NONE, 0, 0), 'Delete clears the note and its instrument')
    # Hex fields: instrument, volume, effect, parameter.
    app.row = 0
    key(app, kd.KEY_RIGHT)
    typ(app, '0')
    app.row = 0
    key(app, kd.KEY_RIGHT)
    typ(app, '5')
    check(cell(app, 0)[1] == 5, 'instrument 05')
    app.row = 0
    typ(app, '9')
    check(cell(app, 0)[1] == 5 and 'ありません' in _msg(app), 'instrument 09 does not exist: refused')
    app.row = 0
    key(app, kd.KEY_RIGHT)
    typ(app, 'c')
    check(cell(app, 0)[2] == 12, 'volume C')
    app.row = 0
    key(app, kd.KEY_RIGHT)
    typ(app, '5')
    check(cell(app, 0)[3] == 0, 'effect 5 is refused')
    app.row = 0
    typ(app, 'a')
    app.row = 0
    key(app, kd.KEY_RIGHT)
    typ(app, '3')
    app.row = 0
    key(app, kd.KEY_RIGHT)
    typ(app, '2')
    check(cell(app, 0)[3:] == (10, 0x32), 'volume slide A32: %r' % (cell(app, 0),))
    # Speed F00 would stop time: becomes F01.
    app.row = 4
    app.field = 4
    typ(app, 'f')
    check(cell(app, 4)[3:] == (15, 1), 'F with parameter 00 becomes F01: %r' % (cell(app, 4),))
    app.row = 4
    app.field = 5
    typ(app, '0')
    app.row = 4
    app.field = 6
    typ(app, '0')
    check(cell(app, 4)[3:] == (15, 1), 'F00 refused: %r' % (cell(app, 4),))
    check(app.song.to_bytes(), 'the edited song is valid')
    audio.close()


def test_rows_tracks_orders():
    desk, audio, app, dev = fresh('rows')
    typ(app, 'zxc')                                 # rows 0, 1, 2
    app.row = 1
    key(app, kd.KEY_INSERT)
    check(cell(app, 1)[0] == 0 and cell(app, 2)[0] == 51, 'Insert pushes the track down')
    key(app, kd.KEY_BACKSPACE)
    check(app.row == 0 and cell(app, 0)[0] == 0 and cell(app, 1)[0] == 51, 'Backspace pulls up: %r' % (
        [cell(app, r)[0] for r in range(3)],))
    key(app, kd.KEY_TAB, 0, kd.MOD_SHIFT)
    check(app.track == 5, 'Shift+Tab wraps to the last track')
    check(app.first_track == 2, 'the view pages to show track 5')
    key(app, kd.KEY_TAB)
    check(app.track == 0 and app.first_track == 0, 'Tab wraps back')
    key(app, kd.KEY_END)
    check(app.row == 63, 'End')
    key(app, kd.KEY_PGUP)
    check(app.row == 47, 'PgUp')
    app.menu(1, 5)                                  # 順序+
    check(app.song.orders == [0, 0] and app.order == 1, 'order inserted')
    app.menu(1, 2)                                  # 新パターン
    check(app.song.orders == [0, 1] and len(app.song.patterns) == 2, 'new pattern at the order')
    key(app, kd.KEY_UP, 0, kd.MOD_CTRL)
    check(app.song.orders[1] == 0, 'Ctrl+Up cycles the pattern')
    key(app, kd.KEY_LEFT, 0, kd.MOD_CTRL)
    check(app.order == 0, 'Ctrl+Left')
    app.menu(1, 6)                                  # 順序-
    check(app.song.orders == [0], 'order deleted')
    app.menu(1, 6)
    check(app.song.orders == [0], 'the last order stays')
    audio.close()


def test_playback_and_live_edit():
    desk, audio, app, dev = fresh('play')
    typ(app, 'zxcv')
    clock = audio.clock
    key(app, kd.KEY_CHAR, ' ')                      # play the song from the start
    for _ in range(6 * 8 - 1):
        clock.t += 20000                            # tempo 125: one tick
        audio.pump()
        app.handle()
    check(app.play_pos is not None and app.play_pos[1] == 7, 'the view follows the player: %r' % (app.play_pos,))
    check(app.shown.get('state') == 'PLAY', 'status PLAY')
    # An edit while playing is loaded at once and keeps the position.
    before = ka.position()
    app.row = 20
    typ(app, 'b')
    check(not app.dirty_song, 'reloaded during playback')
    check(ka.position() >> 8 == before >> 8, 'position kept')
    key(app, kd.KEY_ESCAPE)
    check(ka.position() >> 24 == ka.STOPPED and app.shown.get('state') == 'STOP', 'Esc stops')
    key(app, kd.KEY_ENTER)                          # pattern mode
    check(ka.position() >> 24 == ka.PLAYING, 'Enter plays the pattern')
    key(app, kd.KEY_ENTER)
    check(ka.position() >> 24 == ka.STOPPED, 'and stops it')
    app.menu(2, 4)                                  # ミュート
    app.handle()
    check(app.mute == 1 and '(M)' in app.shown.get('head', ''), 'track 0 muted')
    audio.close()


def test_files_and_guards():
    desk, audio, app, dev = fresh('files')
    typ(app, 'zx')
    check(app.modified, 'modified')
    app.menu(0, 0)                                  # 新規 with changes: asks first
    check(app.song.patterns[0].cells[0] == 49, 'not discarded on the first time')
    app.menu(0, 0)
    check(app.song.patterns[0].cells[0] == 0 and not app.modified, 'discarded on the second time')
    typ(app, 'c')
    for bad in ('../X', 'A/B', '', 'TOOLONGNAME', '.HID', 'ﾃｽﾄ'):
        app.message('')
        app.save_name(bad)
        check('保存できません' in _msg(app) and app.name is None, 'refused name %r' % bad)
    check(os.listdir(app.files.folder) == [], 'nothing written for refused names')
    app.save_name('tune1')
    check(app.name == 'TUNE1' and not app.modified, 'saved as TUNE1')
    data = open(app.files.path('TUNE1'), 'rb').read()
    check(Song.from_bytes(data).patterns[0].cells[0] == 53, 'the file holds the song (c is E-4)')
    check(not _exists(app.files.path('TUNE1') + '.tmp'), 'no .tmp left')
    app.export()
    h = open(app.files.path('TUNE1', '.H')).read()
    check('static const uint8_t ksng_tune1[%d]' % len(data) in h, 'C header')
    app.new()
    app.open_name('TUNE1')
    check(app.name == 'TUNE1' and app.song.to_bytes() == data, 'reopened')
    app.open_name('NOPE')
    check('開けません' in _msg(app), 'missing file: %r' % _msg(app))
    with open(app.files.folder + '/BAD.KSN', 'wb') as f:
        f.write(data[:-3])
    app.open_name('BAD')
    check('開けません' in _msg(app) and app.name == 'TUNE1', 'a truncated file is refused, the song kept')
    audio.close()


def _msg(app):
    return app.shown.get('msg', '') or ''


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def open_wave_editor(app):
    app.inst = 4                                    # 04: wave instrument, wave 0
    app.track = 4                                   # WAVE1
    app.menu(3, 2)                                  # 音色 > 編集…
    for _ in range(8):
        key(app, kd.KEY_DOWN)                       # to 波形を編集…
    key(app, kd.KEY_ENTER)
    return app.dialog


def signed(b):
    return b - 256 if b > 127 else b


def test_wave_editor_keyboard():
    desk, audio, app, dev = fresh('wave-keys')
    d = open_wave_editor(app)
    check(isinstance(d, T.WaveDialog) and d.index == 0 and d.n == 32, 'the editor opened on wave 0')
    w = d.wave
    for _ in range(3):
        key(app, kd.KEY_RIGHT)
    before = signed(w[3])
    key(app, kd.KEY_UP)
    check(signed(w[3]) == before + 1, 'Up: +1')
    key(app, kd.KEY_UP, 0, kd.MOD_SHIFT)
    check(signed(w[3]) == before + 17, 'Shift+Up: +16')
    key(app, kd.KEY_HOME)
    check(signed(w[3]) == 127, 'Home: top')
    key(app, kd.KEY_UP)
    check(signed(w[3]) == 127, 'clamped at 127')
    key(app, kd.KEY_END)
    check(signed(w[3]) == -128, 'End: bottom')
    for _ in range(4):
        key(app, kd.KEY_RIGHT, 0, kd.MOD_SHIFT)     # draw: carry -128 along
    check([signed(w[k]) for k in range(3, 8)] == [-128] * 5 and d.sel == 7, 'Shift+Right draws')
    key(app, kd.KEY_DELETE)
    check(w[7] == 0, 'Delete: 0')
    # What the hardware would play: the HAL holds the edited wave.
    check(bytes(ka.wave(4)[:32]) == bytes(w), 'the HAL has the edited wave')
    check(app.modified and app.dirty_song, 'the song is modified')
    # A single edit redraws one group of the canvas, not all of it.
    def tiles_after(code, ch=0):
        desk.key(code, ch, 0)
        app.handle()
        return desk.present()
    desk.present()
    tiles = tiles_after(kd.KEY_UP)
    whole = tiles_after(kd.KEY_CHAR, '4')
    check(0 <= tiles <= 40, 'one edit redraws a few tiles: %d' % tiles)
    check(whole > 200, 'a preset redraws the canvas: %d' % whole)
    # Presets.
    for c, name in (('1', 'sine'), ('2', 'triangle'), ('3', 'saw'), ('4', 'square'), ('0', 'flat')):
        key(app, kd.KEY_CHAR, c)
        check(bytes(w) == bytes(T.wave_shape(c, 32)), 'preset %s' % name)
    check(bytes(T.wave_shape('0', 32)) == bytes(32), 'flat is zero')
    sq = T.wave_shape('4', 32)
    check(signed(sq[0]) == 127 and signed(sq[31]) == -127, 'square')
    # Length: 32 -> 64 -> 128 -> 256 -> 32, resampled.
    key(app, kd.KEY_CHAR, '3')
    saw = bytes(w)
    key(app, kd.KEY_CHAR, 'l')
    check(d.n == 64 and bytes(d.wave[k] for k in range(0, 64, 2)) == saw, 'L: 64 samples, the same saw')
    for _ in range(3):
        key(app, kd.KEY_CHAR, 'l')
    check(d.n == 32 and bytes(d.wave) == saw, 'back to 32')
    # Space plays a note with the wave on the wave track.
    commits = dev.commits
    key(app, kd.KEY_CHAR, ' ')
    check(dev.commits > commits, 'Space previews on the hardware')
    # N: a copy as a new wave for this instrument.
    key(app, kd.KEY_CHAR, 'n')
    check(len(app.song.waves) == 3 and app.song.instruments[4][1] == 2 and d.index == 2, 'new wave W2')
    key(app, kd.KEY_ESCAPE)
    check(app.dialog is None, 'Esc closes')
    # A pulse instrument has no wave to edit.
    app.inst = 0
    app.menu(3, 2)
    for _ in range(8):
        key(app, kd.KEY_DOWN)
    key(app, kd.KEY_ENTER)
    check(app.dialog is None and 'だけ' in _msg(app), 'no editor for a pulse instrument')
    audio.close()


def test_wave_editor_pointer_and_files():
    desk, audio, app, dev = fresh('wave-files')
    d = open_wave_editor(app)
    key(app, kd.KEY_CHAR, '0')                      # flat, then draw on it
    ox, oy = d.win.work()[:2]                       # screen origin of the work area
    X, Y = T.WAVE_X, T.WAVE_Y
    desk.pointer(kd.POINTER_DOWN, ox + X + 2, oy + Y + 64 - 40)      # sample 0 to +80
    app.handle()
    desk.pointer(kd.POINTER_MOVE, ox + X + 8 * 8 + 2, oy + Y + 64 + 20)   # sample 8 to -40: a line
    app.handle()
    desk.pointer(kd.POINTER_UP, ox + X + 8 * 8 + 2, oy + Y + 64 + 20)
    app.handle()
    vals = [signed(b) for b in d.wave[:10]]
    check(vals[0] == 80 and vals[8] == -40 and vals[9] == 0, 'pointer press and drag: %r' % (vals,))
    check(all(vals[k] >= vals[k + 1] for k in range(8)), 'a falling line between the points')
    desk.pointer(kd.POINTER_MOVE, ox + X + 200, oy + Y + 10)           # no button: nothing
    app.handle()
    check(signed(d.wave[25]) == 0, 'moves without a press do not draw')
    desk.pointer(kd.POINTER_DOWN, ox + 2, oy + Y + 200)                # outside the canvas
    app.handle()
    check(d.drag is None, 'a press outside the canvas does not draw')
    key(app, kd.KEY_CHAR, 'l')                      # 64 samples
    edited = bytes(d.wave)
    key(app, kd.KEY_ENTER)
    app.save_name('WAVES')
    data = open(app.files.path('WAVES'), 'rb').read()
    t = Song.from_bytes(data)
    check(bytes(t.waves[0]) == edited and len(t.waves[0]) == 64, 'the wave reloads without loss')
    check(t.to_bytes() == data, 'and the song round-trips')
    app.new()
    app.open_name('WAVES')
    check(bytes(app.song.waves[0]) == edited, 'reopened in the tracker')
    audio.close()


def test_grid_while_playing():
    desk, audio, app, dev = fresh('grid')
    clock = audio.clock
    for r in range(20):
        app.row = r
        typ(app, 'z')                               # a note on every row 0..19
    app.row = 0
    key(app, kd.KEY_CHAR, ' ')
    handles = []
    while app.play_pos is None or app.play_pos[1] < 16:
        clock.t += 20000
        audio.pump()
        app.handle()
    # The page turned to rows 16..31: while playing, 4 rows per loop.
    check(app.grid_todo == T.GRID_ROWS_PLAYING, 'first loop after the page turn: %d rows' % app.grid_todo)
    for _ in range(3):
        app.handle()
    check(app.grid_todo == T.ROWS, 'the page is complete after 4 loops')
    text = [app.shown.get(('r', i)) for i in range(4)]
    check(text[0].startswith('16 C-4') and text[3].startswith('19 C-4'), 'rows 16..19: %r' % (text,))
    check(app.shown.get(('r', 4)).startswith('20 ---'), 'row 20 empty')
    key(app, kd.KEY_ESCAPE)                         # stopped: a page is drawn at once
    app.row = 40
    app.handle()
    check(app.grid_todo == T.ROWS and app.shown.get(('r', 0)).startswith('32 '), 'stopped: whole page at once')
    audio.close()


def test_scope():
    desk, audio, app, dev = fresh('scope')
    app.now_ms = lambda: 0          # handle() keeps the scope at time 0; the test drives it
    sc = app.scope
    sc.update(0)
    check(app.shown.get('scope') == 'SYNTH MIX 15Hz', 'label: %r' % app.shown.get('scope'))
    mid = T.SCOPE_Y + T.SCOPE_H // 2
    check(sc.rects == ((T.SCOPE_X, mid, T.SCOPE_W, 1),), 'silence: one flat record at the centre: %r' % (sc.rects,))
    check(len(sc.ids) == 1, 'one record for silence')
    # A sounding note shows a waveform.
    typ(app, 'z')                                   # previews C-4 on PULSE1
    audio.pump()
    sc.update(1000)
    check(any(r[3] > 1 for r in sc.rects), 'a pulse wave is drawn')
    check(len(sc.ids) == len(sc.rects) <= T.SCOPE_POINTS, 'at most one record per column')
    check(all(T.SCOPE_X <= r[0] and r[0] + r[2] <= T.SCOPE_X + T.SCOPE_W and
              T.SCOPE_Y <= r[1] and r[1] + r[3] <= T.SCOPE_Y + T.SCOPE_H for r in sc.rects), 'inside the box')
    check(sc.updates == 2, 'updates %d' % sc.updates)
    sc.update(1010)                                 # within 66 ms: no update
    check(sc.updates == 2, 'at most about 15 updates a second')
    sc.update(1070)
    check(sc.updates == 3, 'and again after 66 ms')
    # Views: the mix, each track, off.
    names = []
    for _ in range(app.song.tracks + 2):
        app.menu(2, 6)                              # 再生 > スコープ
        names.append(app.shown.get('scope'))
    check(names[:2] == ['SYNTH P1 15Hz', 'SYNTH P2 15Hz'] and names[4] == 'SYNTH W1 15Hz', 'views %r' % (names,))
    check(names[6] == 'SYNTH OFF' and not sc.ids, 'off frees the records')
    check(names[7] == 'SYNTH MIX 15Hz', 'back to the mix')
    # Hidden under a dialog: records freed for it, shown again afterwards.
    sc.update(5000)
    app.menu(2, 5)                                  # 設定… (song dialog)
    app.handle()
    check(sc.hidden and not sc.ids, 'hidden while a dialog is open')
    key(app, kd.KEY_ESCAPE)
    check(not sc.hidden and sc.ids, 'shown again after the dialog')
    # Throttle: one slow update is tolerated; a costly average halves the rate
    # down to off; cheap updates bring it back.
    t = 10000
    sc.cost_avg = 0
    sc.measured(t, 3 * T.SCOPE_BUDGET_US)
    check(app.shown.get('scope').endswith('15Hz'), 'a single slow update does not slow the scope')
    seen = []
    for _ in range(40):
        sc.measured(t, 3 * T.SCOPE_BUDGET_US)
        t += 1000
        label = app.shown.get('scope').split()[-1]
        if not seen or seen[-1] != label:
            seen.append(label)
        if label == 'OFF(auto)':
            break
    check(seen == ['15Hz', '7Hz', '3Hz', '1Hz', 'OFF(auto)'][-len(seen):] and seen[-1] == 'OFF(auto)',
          'throttled step by step to off: %r' % (seen,))
    check(not sc.ids, 'auto-off frees the records')
    n = sc.updates
    sc.update(t + 5000)
    check(sc.updates == n, 'no updates when off')
    app.menu(2, 6)                                  # cycling restores a rate
    app.menu(2, 6)
    sc.level, sc.cost_avg = 1, 0
    for _ in range(10):
        sc.measured(t, 100)
    check(sc.level == 0, 'cheap updates speed it up again')
    audio.close()


def test_demo_song():
    """The scripted tour composes the demo; check what it wrote."""
    path = folder + '/demo'
    try:
        os.mkdir(path)
    except OSError:
        pass
    lines = []
    T.main(script=True, desk=T.HostDesktop(T.MENUS), audio=AudioSession(T.NullAudioDevice()),
           files=T.SongFiles(path), out=lines.append)
    check(len(lines) == 12 and all(l.startswith('SCENE') for l in lines), 'twelve scenes')
    s = Song.from_bytes(open(path + '/DEMO.KSN', 'rb').read())
    check(s.tempo == 140 and s.speed == 6 and s.loop, 'tempo 140, speed 6, looping')
    check(s.orders == [0, 1] and len(s.patterns) == 2, 'two patterns in order: %r' % (s.orders,))
    check(all(p.rows == 32 for p in s.patterns), '32-row patterns')
    p0 = s.patterns[0]
    melody = [p0.cells[p0.offset(r, 0)] for r in range(32)]
    check(melody[0] == 61 and melody[2] == 56 and melody[8] == 65, 'melody C-5 G-4 .. E-5: %r' % (melody[:9],))
    check(p0.cells[p0.offset(0, 4)] == 25 and p0.cells[p0.offset(0, 4) + 1] == 4, 'bass C-2 on the triangle')
    check(p0.cells[p0.offset(2, 1)] == 61 and p0.cells[p0.offset(2, 1) + 1] == 1, 'echo on pulse 2')
    check(sum(1 for r in range(32) if p0.cells[p0.offset(r, 3)]) == 16, 'sixteen drum hits')
    check(s.instruments[0][7] == 8, 'lead release 8 from the instrument editor')
    check(s.patterns[1].cells[s.patterns[1].offset(28, 0)] == NOTE_OFF, 'note off in pattern 1')
    check(_exists(path + '/DEMO.H'), 'exported')
    print('DEMO bytes', len(open(path + '/DEMO.KSN', 'rb').read()))


for name in ('test_note_entry', 'test_rows_tracks_orders', 'test_playback_and_live_edit',
             'test_files_and_guards', 'test_wave_editor_keyboard', 'test_wave_editor_pointer_and_files',
             'test_grid_while_playing', 'test_scope', 'test_demo_song'):
    globals()[name]()
print('desktop_tracker: %d failures' % len(failures))
if failures:
    raise SystemExit(1)
