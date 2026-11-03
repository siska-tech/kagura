# SPDX-License-Identifier: Apache-2.0
"""神楽トラッカー: a music tracker on the native desktop, played by the
KAGURA-9 synthesizer (pulse 1-3, noise, wave 1-2) through kagura.music.

On KAGURA-9 (the HDMI console running, firmware with kagura_audio):
    import desktop_tracker; desktop_tracker.main()                 # your keyboard
    desktop_tracker.main(files=desktop_tracker.ram_songs())        # songs in RAM only
    desktop_tracker.main(script=True, files=desktop_tracker.ram_songs())   # scripted demo
On a PC (unix port with kagura_desktop and kagura_audio):
    micropython desktop_tracker.py --host DIR [--dump D]           # demo, files in DIR

Pattern keys (FastTracker II layout):
  z s x d c v g b h n j m , l . ; /   notes from C of the current octave
  q 2 w 3 e r 5 t 6 y 7 u i 9 o 0 p   notes one octave up
  1 or `   note off            Delete   clear the field     0-9 a-f  hex fields
  arrows, Tab / Shift+Tab (track), PgUp/PgDn, Home/End     Insert / Backspace rows
  [ ]  octave    - =  instrument    Space  play/stop song    Enter  play/stop pattern
  Ctrl+Left/Right  order position   Ctrl+Up/Down  pattern at this position
  Ctrl+S save, Ctrl+O open, Ctrl+N new; F10 menus; Esc stops playback.
Ctrl+C stays MicroPython's interrupt: the tracker closes and the sound stops.

Songs are KSNG files (software/audio/README.md), saved as NAME.KSN in one
folder (default /songs) with the same write-then-rename as the editor;
書き出し also writes NAME.H, the song as a C array for standalone games.
"""
import os
import time

import kagura_audio as ka
import kagura_desktop as kd
from kagura.music import (AudioSession, Song, Pattern, instrument, note_name, NOTE_OFF, NONE,
                          KIND_PULSE, KIND_WAVE, KIND_NOISE, triangle_wave, saw_wave)

MENUS = (('ファイル', ('新規', '開く…', '保存', '別名保存…', '書き出し', '-', '終了')),
         ('編集', ('行挿入', '行削除', '新パターン', '複製', '-', '順序+', '順序-')),
         ('再生', ('曲', 'パターン', '停止', '-', 'ミュート', '設定…')),
         ('音色', ('前へ', '次へ', '編集…', '-', 'Oct+', 'Oct-')))   # 242 of 256 bytes
SONG_DIR = '/songs'
FREE_MARGIN = 4096
VOICE_NAMES = ('PULSE1', 'PULSE2', 'PULSE3', 'NOISE', 'WAVE1', 'WAVE2')
KIND_NAMES = ('PLS', 'WAV', 'NOI')
HEX = '0123456789ABCDEF'
HEX2 = tuple('%02X' % i for i in range(256))
NOTES = tuple(note_name(n) for n in range(98))

# Layout in the window's work area (pixels). The grid uses the 4x8 font.
# Work area 318 x 176: status 1..8, rule 10, header 12, 16 rows of 9 from 20, rule 165, message 167.
GRID_X, HEAD_Y, GRID_Y, ROW_H, ROWS = 2, 12, 20, 9, 16
CELL_CH = 13                       # 'C-4 01 F A12 '
VISIBLE_TRACKS = 4
FIELD_CH = (0, 4, 5, 7, 9, 10, 11)  # character of each cursor field in a cell
FIELD_W = (3, 1, 1, 1, 1, 1, 1)
PANEL_X = 228
# Piano keys: offset in semitones from C of the current octave.
PIANO = {}
for _i, _c in enumerate('zsxdcvgbhnjm,l.;/'):
    PIANO[_c] = _i
for _i, _c in enumerate('q2w3er5t6y7ui9o0p'):
    PIANO[_c] = 12 + _i


def cell_text(c, o):
    inst, vol, fx, param = c[o + 1], c[o + 2], c[o + 3], c[o + 4]
    return '%s %s %s %s ' % (NOTES[c[o]], '..' if inst == NONE else HEX2[inst],
                             '.' if vol == NONE else HEX[vol],
                             '...' if not (fx or param) else HEX[fx] + HEX2[param])


class SongFiles:
    """NAME.KSN songs in one folder; plain names only, never paths."""

    def __init__(self, folder=SONG_DIR):
        self.folder = folder
        self.pump = None      # called between chunks of file I/O, so music keeps time

    @staticmethod
    def check_name(name):
        if not 1 <= len(name) <= 8:
            raise ValueError('1..8 文字の名前')
        for c in name:
            if not (c.isalpha() or c.isdigit() or c in '_-') or ord(c) > 127:
                raise ValueError('英数字と _ - だけ')
        return name.upper()

    def path(self, name, ext='.KSN'):
        return '%s/%s%s' % (self.folder, self.check_name(name), ext)

    def names(self):
        try:
            return sorted(n[:-4] for n in os.listdir(self.folder) if n.endswith('.KSN'))
        except OSError:
            return []

    def load(self, name):
        parts = []
        with open(self.path(name), 'rb') as f:
            while sum(len(p) for p in parts) <= ka.MAX_BYTES:
                part = f.read(512)
                if not part:
                    break
                parts.append(part)
                if self.pump is not None:
                    self.pump()
        data = b''.join(parts)
        if len(data) > ka.MAX_BYTES:
            raise ValueError('大きすぎます')
        return data

    def _write(self, path, pieces, size):
        """Writes pieces (bytes-like) to path.tmp, checks the size written,
        renames it over path. size is the expected total, for the free space."""
        try:
            os.mkdir(self.folder)
        except OSError:
            pass
        try:
            st = os.statvfs(self.folder)
            if st[0] * st[4] < size + FREE_MARGIN:
                raise OSError('空き容量が足りません')
        except AttributeError:
            pass
        tmp = path + '.tmp'
        written = 0
        with open(tmp, 'wb') as f:
            for piece in pieces:
                f.write(piece)
                written += len(piece)
                if self.pump is not None:
                    self.pump()
        if os.stat(tmp)[6] != written:
            raise OSError('書き込みを確認できません')
        try:
            os.rename(tmp, path)
        except OSError:      # a filesystem that does not replace on rename
            os.remove(path)
            os.rename(tmp, path)

    def save(self, name, data):
        view = memoryview(data)
        self._write(self.path(name), (view[at:at + 512] for at in range(0, len(data), 512)), len(data))

    def export_h(self, name, data):
        """The song as a C array: #include it and give it to ks_song_parse().
        Written line by line: no copy of the whole text in memory."""
        ident = 'ksng_' + self.check_name(name).lower().replace('-', '_')

        def lines():
            yield ('// %s.KSN, KSNG song exported by 神楽トラッカー\n#include <stdint.h>\n'
                   'static const uint8_t %s[%d] = {\n' % (self.check_name(name), ident, len(data))).encode()
            for i in range(0, len(data), 16):
                yield ('    ' + ''.join('0x%02x,' % b for b in data[i:i + 16]) + '\n').encode()
            yield b'};\n'
        self._write(self.path(name, '.H'), lines(), 6 * len(data) + 200)


def ram_songs(mount='/ramsongs', blocks=32, block_size=512):
    """Songs on a littlefs in RAM (16 KB): nothing is written to flash."""
    import vfs

    class RAMBlocks:
        def __init__(self):
            self.data = bytearray(blocks * block_size)

        def readblocks(self, n, buf, off=0):
            a = n * block_size + off
            buf[:] = self.data[a:a + len(buf)]

        def writeblocks(self, n, buf, off=None):
            a = n * block_size + (off or 0)
            self.data[a:a + len(buf)] = buf

        def ioctl(self, op, arg):
            return {4: blocks, 5: block_size, 6: 0}.get(op)

    try:
        vfs.umount(mount)
    except OSError:
        pass
    dev = RAMBlocks()
    vfs.VfsLfs2.mkfs(dev)
    vfs.mount(vfs.VfsLfs2(dev), mount)
    return SongFiles(mount + '/songs')


class ParamDialog:
    """A list of numbers: Up/Down choose, Left/Right change (Shift: by 16),
    Space previews, Enter or Esc closes."""

    def __init__(self, app, title, params, h):
        self.app, self.params, self.sel = app, params, 0
        w = self.win = app.desk.create_window(title, 70, 34, 180, h, closable=False, movable=False)
        self.bar = w.fill_rect(4, 3, 168, 10, 3)       # under the text: created first
        self.values = []
        for i, p in enumerate(params):
            w.text(8, 4 + i * 11, p[0], 1)
            self.values.append(w.text(112, 4 + i * 11, '', 1))
        w.text(8, h - 24, 'Space:試聴 Enter:閉じる', 4, -1, 1)
        self.refresh()

    def refresh(self):
        for i, p in enumerate(self.params):
            self.win.set_text(self.values[i], p[4](p[1]()))
        self.win.move_item(self.bar, 4, 3 + self.sel * 11)

    def key(self, code, ch, mods):
        p = self.params[self.sel]
        step = 16 if mods & kd.MOD_SHIFT else 1
        if code == kd.KEY_UP:
            self.sel = (self.sel - 1) % len(self.params)
        elif code == kd.KEY_DOWN:
            self.sel = (self.sel + 1) % len(self.params)
        elif code in (kd.KEY_LEFT, kd.KEY_RIGHT):
            v = p[1]() + (step if code == kd.KEY_RIGHT else -step)
            p[2](min(max(v, p[3][0]), p[3][1]))
            self.app.changed()
        elif code == kd.KEY_CHAR and ch == ord(' '):
            self.app.preview(self.app.octave * 12 + 1)
        elif code in (kd.KEY_ENTER, kd.KEY_ESCAPE):
            self.close()
            return
        self.refresh()

    def close(self):
        self.win.close()
        self.app.dialog = None


class NameDialog:
    def __init__(self, app, title, initial, action):
        self.app, self.action = app, action
        w = self.win = app.desk.create_window(title, 60, 60, 200, 58, closable=False, movable=False)
        w.text(6, 4, '名前 (英数字8文字)', 1)
        self.field = w.field(6, 16, 186, initial)
        self.ok = w.button(132, 32, 56, 14, 'OK', kd.BTN_DEFAULT, True)
        w.focus(self.field)

    def key(self, code, ch, mods):
        if code == kd.KEY_ESCAPE:
            self.close()

    def activate(self):
        name = self.win.get_text(self.field)
        self.close()
        self.action(name)

    def close(self):
        self.win.close()
        self.app.dialog = None


class Tracker:
    def __init__(self, desk, audio, files, source='キーボード', frame=(0, 11, 320, 189)):
        self.desk, self.audio, self.files = desk, audio, files
        files.pump = audio.pump      # saves and loads keep the music in time
        self.quit = False
        self.dialog = None
        self.name = None
        self.song = Song.new()
        self.dirty_song = True       # the player's copy is out of date
        self.modified = False
        self.order = 0               # order position being edited
        self.row = self.track = self.field = 0
        self.first_track = 0
        self.octave, self.inst, self.step = 4, 0, 1
        self.mute = 0
        self.confirm = None          # a destructive command asked once: do it on the second time
        self.shown = {}
        w = self.win = desk.create_window('神楽トラッカー', *frame, closable=False, movable=False)
        self.ww, self.wh = w.work()[2:]
        # Status line (8x8), then the grid header and rows (4x8), the panel on the right.
        self.t_state = w.text(2, 2, 'STOP', 6)
        self.t_info = w.text(42, 2, '', 1)
        w.hline(0, 10, self.ww, 1)
        w.vline(PANEL_X - 3, 11, GRID_Y + ROWS * ROW_H - 10, 1)
        self.play_bar = w.fill_rect(GRID_X, -20, PANEL_X - 6, ROW_H, 12)
        self.cur_bar = w.fill_rect(GRID_X, GRID_Y, PANEL_X - 6, ROW_H, 3)
        self.cur_box = w.rect(GRID_X, GRID_Y, 14, ROW_H, 1)
        self.t_head = w.text(GRID_X, HEAD_Y, '', 5, -1, 1)
        self.t_rows = [w.text(GRID_X, GRID_Y + 1 + i * ROW_H, '', 1, -1, 1) for i in range(ROWS)]
        w.text(PANEL_X, HEAD_Y, 'ORDER', 5)
        self.t_orders = [w.text(PANEL_X, GRID_Y + 2 + i * 9, '', 1) for i in range(6)]
        w.text(PANEL_X, 78, 'INSTR', 5)
        self.t_insts = [w.text(PANEL_X, 88 + i * 9, '', 1) for i in range(6)]
        self.t_len = w.text(PANEL_X, 146, '', 4)
        w.hline(0, GRID_Y + ROWS * ROW_H + 1, self.ww, 1)
        self.t_msg = w.text(2, GRID_Y + ROWS * ROW_H + 3, '', 1)
        self.t_source = w.text(self.ww - 52, GRID_Y + ROWS * ROW_H + 3, source, 5)
        self.play_pos = None
        self.message('F10:メニュー Space:再生')
        self.refresh()

    # ---- model ----

    @property
    def pattern(self):
        return self.song.patterns[self.song.orders[self.order]]

    def changed(self):
        self.modified = True
        self.dirty_song = True

    def sync_player(self):
        """Gives the player the current song (keeps the position while playing)."""
        if self.dirty_song:
            ka.load(self.song.to_bytes())
            self.dirty_song = False

    def message(self, text):
        self.set('msg', self.t_msg, text)

    # ---- drawing ----

    def set(self, key, item, text):
        if self.shown.get(key) != text:
            self.win.set_text(item, text)
            self.shown[key] = text

    def refresh(self):
        s, p = self.song, self.pattern
        # Keep the cursor's track and row in view.
        if self.track < self.first_track:
            self.first_track = self.track
        elif self.track >= self.first_track + VISIBLE_TRACKS:
            self.first_track = self.track - VISIBLE_TRACKS + 1
        self.first_track = max(0, min(self.first_track, s.tracks - VISIBLE_TRACKS))
        play = self.play_pos
        top = (self.row // ROWS) * ROWS
        if play is not None and play[0] == self.order:   # follow the playback row
            top = (play[1] // ROWS) * ROWS
        last = min(s.tracks, self.first_track + VISIBLE_TRACKS)
        head = ['   ']
        for t in range(self.first_track, last):
            name = VOICE_NAMES[s.voices[t]] + ('(M)' if self.mute >> t & 1 else '')
            head.append(name + ' ' * (CELL_CH - len(name)))
        self.set('head', self.t_head, ''.join(head))
        c = p.cells
        for i in range(ROWS):
            r = top + i
            if r >= p.rows:
                self.set(('r', i), self.t_rows[i], '')
                continue
            parts = ['%02d ' % r]
            for t in range(self.first_track, last):
                parts.append(cell_text(c, p.offset(r, t)))
            text = ''.join(parts)
            self.set(('r', i), self.t_rows[i], text)
            color = 5 if r % 4 == 0 else 1
            if self.shown.get(('c', i)) != color:
                self.win.set_color(self.t_rows[i], color)
                self.shown[('c', i)] = color
        # Cursor bar, field box and the playback bar.
        y = GRID_Y + (self.row - top) * ROW_H
        self.move('bar', self.cur_bar, GRID_X, y if 0 <= self.row - top < ROWS else -20)
        x = GRID_X + 4 * (3 + (self.track - self.first_track) * CELL_CH + FIELD_CH[self.field]) - 1
        box = (x, y if 0 <= self.row - top < ROWS else -20)
        if self.shown.get('boxw') != FIELD_W[self.field]:
            self.win.remove(self.cur_box)
            self.cur_box = self.win.rect(box[0], box[1], 4 * FIELD_W[self.field] + 2, ROW_H, 1)
            self.shown['boxw'] = FIELD_W[self.field]
            self.shown['box'] = box
        else:
            self.move('box', self.cur_box, *box)
        py = -20
        if play is not None and play[0] == self.order and top <= play[1] < top + ROWS:
            py = GRID_Y + (play[1] - top) * ROW_H
        self.move('play', self.play_bar, GRID_X, py)
        # Panel: orders around the current one, instruments around the current one.
        o0 = max(0, min(self.order - 2, len(s.orders) - 6))
        for i in range(6):
            o = o0 + i
            text = '' if o >= len(s.orders) else '%s%02d:%02d' % ('>' if o == self.order else ' ', o, s.orders[o])
            if play is not None and o == play[0] and text:
                text += '*'
            self.set(('o', i), self.t_orders[i], text)
        i0 = max(0, min(self.inst - 2, len(s.instruments) - 6))
        for i in range(6):
            n = i0 + i
            text = ''
            if n < len(s.instruments):
                ins = s.instruments[n]
                detail = ('%3d%%' % (ins[1] * 100 // 256)) if ins[0] == KIND_PULSE else \
                    (' W%X' % ins[1] if ins[0] == KIND_WAVE else '')
                text = '%s%02X %s%s' % ('>' if n == self.inst else ' ', n, KIND_NAMES[ins[0]], detail)
            self.set(('i', i), self.t_insts[i], text)
        self.set('len', self.t_len, 'LEN %d %s' % (p.rows, 'LOOP' if s.loop else 'ONCE'))
        self.set('info', self.t_info, '%3dBPM SPD%d OCT%d INS%02X%s' % (
            s.tempo, s.speed, self.octave, self.inst, ' *' if self.modified else ''))
        title = '%s%s - 神楽トラッカー' % ('* ' if self.modified else '', self.name or '無題')
        if self.shown.get('title') != title:
            self.win.set_title(title)
            self.shown['title'] = title

    def move(self, key, item, x, y):
        if self.shown.get(key) != (x, y):
            self.win.move_item(item, x, y)
            self.shown[key] = (x, y)

    def update_play(self):
        """Follows the player: called often, redraws only when the row changes."""
        pos = ka.position()
        state = pos >> 24
        playing = state == ka.PLAYING
        new = (pos >> 16 & 255, pos >> 8 & 255) if playing else None
        label = ('STOP', 'PLAY', 'PAUS', 'END ')[state]
        self.set('state', self.t_state, label)
        if new != self.play_pos:
            if new is not None and self.follow and new[0] != self.order:
                self.order = new[0]
            self.play_pos = new
            self.refresh()

    follow = True

    # ---- playback ----

    def play(self, pattern=False):
        if ka.position() >> 24 == ka.PLAYING:
            self.stop()
            return
        self.sync_player()
        ka.mute(self.mute)
        self.audio.play(ka.PATTERN if pattern else ka.SONG, self.order, 0)
        self.audio.pump()
        self.update_play()

    def stop(self):
        ka.stop()
        self.audio.send()
        self.update_play()
        self.refresh()

    def preview(self, note):
        if not 1 <= note <= 96:
            return
        self.sync_player()
        if not self.audio.preview(self.track, note, self.inst, 12):
            self.message('この音色はこのトラックで鳴りません')
        self.audio.pump()

    # ---- editing ----

    def cell(self):
        return self.pattern.offset(self.row, self.track)

    def enter_note(self, note):
        c, o = self.pattern.cells, self.cell()
        c[o] = note
        if note != NOTE_OFF:
            c[o + 1] = self.inst
            self.preview(note)
        self.changed()
        self.move_row(self.step)

    def enter_hex(self, digit):
        c, o, f = self.pattern.cells, self.cell(), self.field
        if f in (1, 2):
            v = c[o + 1] if c[o + 1] != NONE else 0
            v = (digit << 4 | v & 15) if f == 1 else (v & 0xF0 | digit)
            if v >= len(self.song.instruments):
                self.message('音色 %02X はありません' % v)
                return
            c[o + 1] = v
        elif f == 3:
            c[o + 2] = digit
        elif f == 4:
            if not ka.FX_VALID >> digit & 1:
                self.message('エフェクト %X はありません' % digit)
                return
            c[o + 3] = digit
        else:
            v = c[o + 4]
            c[o + 4] = (digit << 4 | v & 15) if f == 5 else (v & 0xF0 | digit)
        if c[o + 3] == 0xF and c[o + 4] == 0:
            c[o + 4] = 1                              # speed 0 would stop time
        self.changed()
        self.move_row(self.step)

    def clear_field(self):
        c, o, f = self.pattern.cells, self.cell(), self.field
        if f == 0:
            c[o], c[o + 1] = 0, NONE
        elif f in (1, 2):
            c[o + 1] = NONE
        elif f == 3:
            c[o + 2] = NONE
        else:
            c[o + 3] = c[o + 4] = 0
        self.changed()
        self.move_row(self.step)

    def shift_rows(self, insert):
        p, t = self.pattern, self.track
        c = p.cells
        rows = range(p.rows - 1, self.row, -1) if insert else range(self.row, p.rows - 1)
        for r in rows:
            src = p.offset(r - 1 if insert else r + 1, t)
            dst = p.offset(r, t)
            c[dst:dst + 5] = c[src:src + 5]
        o = p.offset(self.row if insert else p.rows - 1, t)
        c[o:o + 5] = bytes((0, NONE, NONE, 0, 0))
        self.changed()

    def move_row(self, d):
        self.row = max(0, min(self.pattern.rows - 1, self.row + d))

    def move_field(self, d):
        f = self.field + d
        if f < 0:
            if self.track > 0:
                self.track -= 1
                f = len(FIELD_CH) - 1
            else:
                f = 0
        elif f >= len(FIELD_CH):
            if self.track < self.song.tracks - 1:
                self.track += 1
                f = 0
            else:
                f = len(FIELD_CH) - 1
        self.field = f

    def set_order(self, o):
        self.order = max(0, min(len(self.song.orders) - 1, o))
        self.row = min(self.row, self.pattern.rows - 1)

    def new_pattern(self, copy=False):
        s = self.song
        if len(s.patterns) >= ka.PATTERNS:
            self.message('パターンは %d まで' % ka.PATTERNS)
            return
        p = Pattern(self.pattern.rows, s.tracks)
        if copy:
            p.cells[:] = self.pattern.cells
        s.patterns.append(p)
        s.orders[self.order] = len(s.patterns) - 1
        self.changed()

    def order_insert(self):
        s = self.song
        if len(s.orders) >= ka.ORDERS:
            return
        s.orders.insert(self.order + 1, s.orders[self.order])
        self.set_order(self.order + 1)
        self.changed()

    def order_delete(self):
        s = self.song
        if len(s.orders) <= 1:
            return
        s.orders.pop(self.order)
        s.loop_order = min(s.loop_order, len(s.orders) - 1)
        self.set_order(self.order)
        self.changed()

    def cycle_pattern(self, d):
        s = self.song
        s.orders[self.order] = (s.orders[self.order] + d) % len(s.patterns)
        self.set_order(self.order)
        self.changed()

    # ---- dialogs ----

    def instrument_dialog(self):
        s, i = self.song, self.inst
        ins = s.instruments[i]

        def field(k):
            def put(v):
                ins[k] = v
            return (lambda: ins[k]), put

        def kind_set(v):
            ins[0] = v
            ins[1] = 128 if v == KIND_PULSE else 0
            if v == KIND_WAVE and not s.waves:
                s.waves.append(triangle_wave())

        shape = [0]

        def wave_set(v):
            shape[0] = v
            if ins[0] == KIND_WAVE:
                s.waves[ins[1]][:] = (triangle_wave, saw_wave, square_wave, sine_wave)[v]()

        hexf, dec = (lambda v: '%02X' % v), (lambda v: '%d' % v)
        data_range = (0, 255) if ins[0] == KIND_PULSE else (0, max(0, len(s.waves) - 1))
        params = [('種類', (lambda: ins[0]), kind_set, (0, 2), lambda v: KIND_NAMES[v]),
                  ('デューティ/波形', field(1)[0], field(1)[1], data_range, dec),
                  ('音量', field(2)[0], field(2)[1], (0, 15), hexf),
                  ('パン', field(3)[0], field(3)[1], (0, 255), dec),
                  ('アタック', field(4)[0], field(4)[1], (0, 255), dec),
                  ('ディケイ', field(5)[0], field(5)[1], (0, 255), dec),
                  ('サステイン', field(6)[0], field(6)[1], (0, 15), hexf),
                  ('リリース', field(7)[0], field(7)[1], (0, 255), dec),
                  ('波形の形', (lambda: shape[0]), wave_set, (0, 3), lambda v: ('TRI', 'SAW', 'SQR', 'SIN')[v])]
        self.dialog = ParamDialog(self, '音色 %02X' % i, params, 9 * 11 + 34)

    def song_dialog(self):
        s = self.song

        def rows_set(v):
            self.pattern.resize((16, 32, 64)[v])
            self.row = min(self.row, self.pattern.rows - 1)

        params = [('テンポ BPM', (lambda: s.tempo), (lambda v: setattr(s, 'tempo', v)), (32, 255), lambda v: '%d' % v),
                  ('速度 tick/行', (lambda: s.speed), (lambda v: setattr(s, 'speed', v)), (1, 31), lambda v: '%d' % v),
                  ('ループ', (lambda: int(s.loop)), (lambda v: setattr(s, 'loop', bool(v))), (0, 1),
                   lambda v: ('しない', 'する')[v]),
                  ('ループ先', (lambda: s.loop_order), (lambda v: setattr(s, 'loop_order', v)),
                   (0, len(s.orders) - 1), lambda v: '%02d' % v),
                  ('パターン長', (lambda: (16, 32, 64).index(self.pattern.rows)), rows_set, (0, 2),
                   lambda v: '%d 行' % (16, 32, 64)[v])]
        self.dialog = ParamDialog(self, '曲の設定', params, 5 * 11 + 34)

    def ask_name(self, title, action):
        self.dialog = NameDialog(self, title, self.name or 'SONG', action)

    # ---- files ----

    def guard(self, what, then):
        """Unsaved changes: the command must be given twice."""
        if self.modified and self.confirm != what:
            self.confirm = what
            self.message('未保存です。もう一度で実行')
            return
        self.confirm = None
        then()

    def new(self):
        self.stop()
        self.song, self.name = Song.new(), None
        self.order = self.row = self.track = self.field = 0
        self.dirty_song, self.modified = True, False
        self.message('新しい曲')

    def open_name(self, name):
        try:
            song = Song.from_bytes(self.files.load(name))
        except (OSError, ValueError) as e:
            self.message('開けません: %s' % e)
            return
        self.stop()
        self.song, self.name = song, SongFiles.check_name(name)
        self.order = self.row = self.track = self.field = 0
        self.dirty_song, self.modified = True, False
        self.message('%s を開きました' % self.name)

    def save_name(self, name):
        try:
            name = SongFiles.check_name(name)
            if self.song.title == 'UNTITLED':
                self.song.title = name
            self.files.save(name, self.song.to_bytes())
        except (OSError, ValueError) as e:
            self.message('保存できません: %s' % e)
            return
        self.name, self.modified = name, False
        self.message('%s.KSN を保存しました' % name)

    def export(self):
        if self.name is None:
            self.ask_name('書き出し', lambda n: (self.save_name(n), self.export()))
            return
        try:
            self.files.export_h(self.name, self.song.to_bytes())
            self.message('%s.H を書き出しました' % self.name)
        except (OSError, ValueError) as e:
            self.message('書き出せません: %s' % e)

    # ---- events ----

    def menu(self, m, item):
        if self.dialog is not None:
            return
        actions = (
            {0: lambda: self.guard('new', self.new), 1: lambda: self.guard('open', lambda: self.ask_name('開く', self.open_name)),
             2: lambda: self.save_name(self.name) if self.name else self.ask_name('保存', self.save_name),
             3: lambda: self.ask_name('別名保存', self.save_name), 4: self.export,
             6: lambda: self.guard('quit', self.do_quit)},
            {0: lambda: self.shift_rows(True), 1: lambda: self.shift_rows(False), 2: self.new_pattern,
             3: lambda: self.new_pattern(True), 5: self.order_insert, 6: self.order_delete},
            {0: self.play, 1: lambda: self.play(True), 2: self.stop, 4: self.toggle_mute, 5: self.song_dialog},
            {0: lambda: self.pick_inst(-1), 1: lambda: self.pick_inst(1), 2: self.instrument_dialog,
             4: lambda: self.set_octave(1), 5: lambda: self.set_octave(-1)})[m]
        actions.get(item, lambda: None)()

    def do_quit(self):
        self.quit = True

    def toggle_mute(self):
        self.mute ^= 1 << self.track
        ka.mute(self.mute)

    def pick_inst(self, d):
        self.inst = max(0, min(len(self.song.instruments) - 1, self.inst + d))

    def set_octave(self, d):
        self.octave = max(0, min(7, self.octave + d))

    def key(self, code, ch, mods):
        if self.dialog is not None:
            self.dialog.key(code, ch, mods)
            return
        ctrl, shift = mods & kd.MOD_CTRL, mods & kd.MOD_SHIFT
        c = chr(ch) if code == kd.KEY_CHAR else ''
        if ctrl:
            if code == kd.KEY_LEFT:
                self.set_order(self.order - 1)
            elif code == kd.KEY_RIGHT:
                self.set_order(self.order + 1)
            elif code == kd.KEY_UP:
                self.cycle_pattern(1)
            elif code == kd.KEY_DOWN:
                self.cycle_pattern(-1)
            elif c and c in 'sS':
                self.menu(0, 2)
            elif c and c in 'oO':
                self.menu(0, 1)
            elif c and c in 'nN':
                self.menu(0, 0)
            return
        if code == kd.KEY_UP:
            self.move_row(-1)
        elif code == kd.KEY_DOWN:
            self.move_row(1)
        elif code == kd.KEY_LEFT:
            self.move_field(-1)
        elif code == kd.KEY_RIGHT:
            self.move_field(1)
        elif code == kd.KEY_TAB:
            self.track = (self.track + (-1 if shift else 1)) % self.song.tracks
            self.field = 0
        elif code == kd.KEY_PGUP:
            self.move_row(-ROWS)
        elif code == kd.KEY_PGDN:
            self.move_row(ROWS)
        elif code == kd.KEY_HOME:
            self.row = 0
        elif code == kd.KEY_END:
            self.row = self.pattern.rows - 1
        elif code == kd.KEY_INSERT:
            self.shift_rows(True)
        elif code == kd.KEY_BACKSPACE:
            if self.row > 0:
                self.move_row(-1)
                self.shift_rows(False)
        elif code == kd.KEY_DELETE:
            self.clear_field()
        elif code == kd.KEY_ENTER:
            self.play(True)
        elif code == kd.KEY_ESCAPE:
            self.stop()
        elif not c:
            return
        elif c == ' ':
            self.play()
        elif c in '[]':
            self.set_octave(1 if c == ']' else -1)
        elif c in '-=':
            self.pick_inst(1 if c == '=' else -1)
        elif self.field == 0 and c in '1`':
            self.enter_note(NOTE_OFF)
        elif self.field == 0 and c in PIANO:
            self.enter_note(min(96, self.octave * 12 + PIANO[c] + 1))
        elif self.field > 0 and c.lower() in '0123456789abcdef':
            self.enter_hex(int(c, 16))
        else:
            return
        if self.confirm is not None:
            self.confirm = None

    def handle(self):
        while True:
            ev = self.desk.poll()
            if ev is None:
                break
            kind = ev[0]
            if kind == kd.MENU:
                self.menu(ev[4], ev[5])
            elif kind == kd.ACTIVATE and isinstance(self.dialog, NameDialog):
                self.dialog.activate()
            elif kind == kd.KEY:
                self.key(ev[4], ev[5], ev[6])
        if self.dirty_song and ka.position() >> 24 == ka.PLAYING:
            self.sync_player()        # edits during playback are heard at once
        self.update_play()
        self.refresh()


def square_wave(n=32):
    return bytearray((127 if i < n // 2 else -127) & 255 for i in range(n))


def sine_wave(n=32):
    import math
    return bytearray(int(round(127 * math.sin(2 * math.pi * i / n))) & 255 for i in range(n))


def sleep_ms(ms):
    if ms > 0:
        if hasattr(time, 'sleep_ms'):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000)


def keyboard(app, source=None, idle_ms=2):
    from kagura.keyinput import TerminalKeys, StdinSource
    keys = TerminalKeys(app.desk)
    src = source if source is not None else StdinSource()
    try:
        while not app.quit:
            n = 0
            while n < 32 and not app.quit:
                got = src.pump(keys, 32 - n, True)
                if not got:
                    break
                n += got
                app.handle()
                app.audio.pump()
            app.handle()
            app.desk.present()       # pumps the audio between runs of tiles
            app.audio.pump()
            if not n:
                sleep_ms(idle_ms)
    finally:
        if source is None:
            src.close()


# ---- the scripted demo: a song composed with the tracker's own keys ----

# Rows of 32-row patterns: (row, note key, octave) per track. The keys are the
# tracker's piano keys, typed one by one.
MELODY_A = ((0, 'c', 5), (2, 'g', 4), (4, 'c', 5), (6, 'd', 5), (8, 'e', 5), (12, 'd', 5), (14, 'c', 5),
            (16, 'a', 4), (18, 'c', 5), (20, 'e', 5), (24, 'g', 5), (28, 'e', 5), (30, 'd', 5))
MELODY_B = ((0, 'f', 5), (4, 'e', 5), (6, 'd', 5), (8, 'c', 5), (12, 'a', 4), (16, 'b', 4), (18, 'c', 5),
            (20, 'd', 5), (24, 'g', 4), (28, '1', 0))
BASS_A = ((0, 'c', 2), (4, 'c', 3), (8, 'a', 1), (12, 'a', 2), (16, 'f', 2), (20, 'f', 3), (24, 'g', 2), (28, 'g', 3))
BASS_B = ((0, 'f', 2), (4, 'f', 3), (8, 'c', 2), (12, 'c', 3), (16, 'g', 2), (20, 'g', 3), (24, 'c', 2), (28, 'c', 3))
DRUMS = tuple((r, 'c' if r % 8 == 0 else ('g' if r % 8 == 4 else 'q'), 3) for r in range(0, 32, 2))
NOTE_KEY = {'c': 'z', 'd': 'x', 'e': 'c', 'f': 'v', 'g': 'b', 'a': 'n', 'b': 'm', 'q': 'q', '1': '1'}


def tour(app, step, key_ms=0, step_ms=0, loops=0):
    d = app.desk

    def k(code, ch=0, mods=0):
        d.key(code, ch, mods)
        app.handle()
        d.present()
        app.audio.pump()
        sleep_ms(key_ms)

    def ch(c, mods=0):
        k(kd.KEY_CHAR, c, mods)

    def scene(name):
        app.handle()
        step(name)
        sleep_ms(step_ms)

    def go_track(t):
        while app.track != t:
            k(kd.KEY_TAB)
        while app.field:
            k(kd.KEY_LEFT)

    def write(track, notes, inst):
        go_track(track)
        while app.inst != inst:
            ch('=' if app.inst < inst else '-')
        k(kd.KEY_HOME)
        for row, note, octave in notes:
            while app.row < row:
                k(kd.KEY_DOWN)
            if note != '1':
                while app.octave != octave:
                    ch(']' if app.octave < octave else '[')
            ch(NOTE_KEY[note])

    def listen(loops):
        """Plays whole loops of the song while the desktop keeps presenting, so
        the scene after it is the same on the board as on the host (loops=0)."""
        song = app.song
        target = ka.stats()['ticks'] + loops * song.speed * sum(song.patterns[o].rows for o in song.orders)
        while True:
            app.handle()
            d.present()
            app.audio.pump()
            if ka.stats()['ticks'] >= target:
                break
            sleep_ms(1)

    scene('empty')
    # 曲の設定: 32-row patterns, 140 BPM.
    k(kd.KEY_F10)
    for _ in range(2):
        k(kd.KEY_RIGHT)
    for _ in range(4):
        k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)
    scene('song-settings')
    for _ in range(15):
        k(kd.KEY_RIGHT)
    for _ in range(4):
        k(kd.KEY_DOWN)
    k(kd.KEY_LEFT)
    k(kd.KEY_ENTER)
    write(0, MELODY_A, 0)
    scene('melody')
    write(4, BASS_A, 4)
    write(3, DRUMS, 3)
    scene('bass-drums')
    # Instrument 01 for a quiet echo of the melody on pulse 2, two rows late.
    write(1, tuple((r + 2, n, o) for r, n, o in MELODY_A if r + 2 < 32), 1)
    # A second pattern after the first.
    k(kd.KEY_F10)
    k(kd.KEY_RIGHT)
    for _ in range(4):
        k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)                     # オーダー挿入: order 1 = pattern 0
    k(kd.KEY_F10)
    k(kd.KEY_RIGHT)
    for _ in range(2):
        k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)                     # 新パターン at order 1
    write(0, MELODY_B, 0)
    write(4, BASS_B, 4)
    write(3, DRUMS, 3)
    scene('pattern-1')
    # The instrument editor: a longer release for the lead.
    while app.inst:
        ch('-')
    k(kd.KEY_F10)
    for _ in range(3):
        k(kd.KEY_RIGHT)
    k(kd.KEY_DOWN)
    k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)
    for _ in range(7):
        k(kd.KEY_DOWN)
    for _ in range(4):
        k(kd.KEY_RIGHT)
    scene('instrument')
    k(kd.KEY_ENTER)
    # Play the song from the start while the desktop keeps working.
    k(kd.KEY_LEFT, 0, kd.MOD_CTRL)
    ch(' ')
    listen(loops)
    scene('playing')
    k(kd.KEY_ESCAPE)
    scene('stopped')
    # Save, start anew, open it again, export for games.
    ch('s', kd.MOD_CTRL)
    for _ in range(4):
        k(kd.KEY_BACKSPACE)
    for c in 'DEMO':
        ch(c)
    k(kd.KEY_ENTER)
    scene('saved')
    ch('n', kd.MOD_CTRL)
    scene('new')
    ch('o', kd.MOD_CTRL)
    for _ in range(4):
        k(kd.KEY_BACKSPACE)
    for c in 'DEMO':
        ch(c)
    k(kd.KEY_ENTER)
    scene('reopened')
    k(kd.KEY_F10)
    for _ in range(4):
        k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)                     # 書き出し
    scene('exported')


def main(script=False, desk=None, audio=None, files=None, out=print, key_ms=None, step_ms=None,
         loops=None, dump=None):
    own = desk is None
    if own:
        from kagura.desktop import Desktop
        desk = Desktop(menus=MENUS, cursor=False)
    own_audio = audio is None
    if own_audio:
        audio = AudioSession(desk.device)
    if hasattr(desk, 'audio'):
        desk.audio = audio            # present() pumps it between runs of tiles
    if key_ms is None:
        key_ms = 40 if own else 0
    if step_ms is None:
        step_ms = 1000 if own else 0
    if loops is None:
        loops = 2 if own else 0
    app = Tracker(desk, audio, files or SongFiles(), 'スクリプト' if script else 'キーボード')
    scenes = [0]

    def step(name):
        import binascii
        scenes[0] += 1
        tiles = desk.present()
        mirror = getattr(desk, 'mirror', None)
        out('SCENE %d %s %08x %d%s' % (scenes[0], name, desk.crc(), tiles,
                                       ' tile4 %08x' % binascii.crc32(mirror) if mirror else ''))
        if dump:
            buf = bytearray(32000)
            desk.snapshot(buf)
            with open('%s/%02d-%s.raw' % (dump, scenes[0], name), 'wb') as f:
                f.write(buf)

    try:
        desk.present()
        if script:
            tour(app, step, key_ms, step_ms, loops)
        else:
            keyboard(app)
    finally:
        try:
            app.files.pump = None      # the files outlive the session
            if hasattr(desk, 'audio'):
                desk.audio = None
            if own_audio:
                audio.close()
        finally:
            if own:
                desk.close()
    return app


class HostDesktop:
    """kagura_desktop.Desktop with present() into a TILE4 mirror (no hardware)."""

    def __init__(self, menus):
        self._kd = kd.Desktop(320, 200, menus=menus, cursor=False)
        self.mirror = bytearray(32000)
        self.audio = None

    def present(self):
        if self.audio is not None:
            self.audio.pump()
        return self._kd.present(self.mirror)

    def __getattr__(self, name):
        return getattr(self._kd, name)


class NullAudioDevice:
    """The SDK device's audio surface without hardware: frames are counted."""
    caps, busy, timeout_us = 0x5B, 0, 100000

    def __init__(self):
        self.commits = self.writes = 0

    def _link(self):
        return None

    def write_memory(self, address, data):
        pass

    def audio_write(self, index, value):
        self.writes += 1

    def audio_commit(self):
        self.commits += 1


if __name__ == '__main__':
    import sys
    if '--host' in sys.argv:
        folder = sys.argv[sys.argv.index('--host') + 1]
        dump = sys.argv[sys.argv.index('--dump') + 1] if '--dump' in sys.argv else None
        app = main(script=True, desk=HostDesktop(MENUS), audio=AudioSession(NullAudioDevice()),
                   files=SongFiles(folder), dump=dump)
    else:
        main()
