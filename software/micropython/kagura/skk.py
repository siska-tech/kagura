# SPDX-License-Identifier: Apache-2.0
"""SKK-style Japanese input for the native desktop.

SkkEngine is the input method, independent of the desktop: it takes typed
characters and a few named keys, and produces committed text, a preedit
(with ▽ or ▼ marker) and a candidate list. SkkInput connects it to a
kagura_desktop.Desktop as the sink of kagura.keyinput.TerminalKeys: keys the
IME does not use go on to the desktop unchanged, committed text enters the
focused field or editor through Desktop.text, and the preedit is drawn by
the native control at its caret (Window.set_preedit), never stored in the
document.

Supported (SKK conventions):
  Ctrl+J          ASCII mode -> かな mode; in かな mode, commits the preedit
  l               かな mode -> ASCII mode
  q               ひらがな <-> カタカナ mode; in ▽, commits the reading in the other kana
  romaji          a ka kya shi chi tsu fu ja ... nn n' (n before a consonant),
                  doubled consonant -> っ, x- small kana (xtu xya ...),
                  - ー , 、 . 。 [ 「 ] 」 z/ ・ z- 〜 z. … z, ‥
  Uppercase       starts a conversion (▽ reading); an uppercase letter inside
                  ▽ starts the okurigana (KaKu -> key かk, 書く)
  Space           converts (▼ first candidate); again: next candidate; after
                  the 4th, a list of 7 at a time, chosen with a s d f j k l
  x               previous candidate (or page)
  Enter           commits the candidate (▼) or the reading (▽), no new line
  Escape, Ctrl+G  ▼ -> back to ▽; ▽ -> preedit discarded; pending romaji dropped
  Backspace       pending romaji, then okurigana, then the reading; in ▼, back to ▽
  other keys      commit the preedit, then act as usual (arrows, Tab, ...)
Not supported: dictionary registration (a word without candidates stays in
▽ with a message), abbrev mode (/), zenkaku ASCII (L), the kana-input
table, completion, numeric conversion (#), annotations' display (they are
stripped), learning (candidate order is the dictionary's).
"""

NORMAL, PREEDIT, CONVERT = 0, 1, 2
ASCII, HIRAGANA, KATAKANA = 'ascii', 'hira', 'kata'
LIST_KEYS = 'asdfjkl'

_ROMAJI = {
    'a': 'あ', 'i': 'い', 'u': 'う', 'e': 'え', 'o': 'お',
    'ka': 'か', 'ki': 'き', 'ku': 'く', 'ke': 'け', 'ko': 'こ', 'kya': 'きゃ', 'kyu': 'きゅ', 'kyo': 'きょ',
    'ga': 'が', 'gi': 'ぎ', 'gu': 'ぐ', 'ge': 'げ', 'go': 'ご', 'gya': 'ぎゃ', 'gyu': 'ぎゅ', 'gyo': 'ぎょ',
    'sa': 'さ', 'si': 'し', 'su': 'す', 'se': 'せ', 'so': 'そ', 'shi': 'し',
    'sha': 'しゃ', 'shu': 'しゅ', 'she': 'しぇ', 'sho': 'しょ', 'sya': 'しゃ', 'syu': 'しゅ', 'syo': 'しょ',
    'za': 'ざ', 'zi': 'じ', 'zu': 'ず', 'ze': 'ぜ', 'zo': 'ぞ', 'zya': 'じゃ', 'zyu': 'じゅ', 'zyo': 'じょ',
    'ja': 'じゃ', 'ji': 'じ', 'ju': 'じゅ', 'je': 'じぇ', 'jo': 'じょ', 'jya': 'じゃ', 'jyu': 'じゅ', 'jyo': 'じょ',
    'ta': 'た', 'ti': 'ち', 'tu': 'つ', 'te': 'て', 'to': 'と', 'tsu': 'つ', 'thi': 'てぃ',
    'tya': 'ちゃ', 'tyu': 'ちゅ', 'tyo': 'ちょ',
    'cha': 'ちゃ', 'chi': 'ち', 'chu': 'ちゅ', 'che': 'ちぇ', 'cho': 'ちょ',
    'da': 'だ', 'di': 'ぢ', 'du': 'づ', 'de': 'で', 'do': 'ど', 'dhi': 'でぃ',
    'dya': 'ぢゃ', 'dyu': 'ぢゅ', 'dyo': 'ぢょ',
    'na': 'な', 'ni': 'に', 'nu': 'ぬ', 'ne': 'ね', 'no': 'の', 'nya': 'にゃ', 'nyu': 'にゅ', 'nyo': 'にょ',
    'nn': 'ん', "n'": 'ん',
    'ha': 'は', 'hi': 'ひ', 'hu': 'ふ', 'he': 'へ', 'ho': 'ほ', 'hya': 'ひゃ', 'hyu': 'ひゅ', 'hyo': 'ひょ',
    'fa': 'ふぁ', 'fi': 'ふぃ', 'fu': 'ふ', 'fe': 'ふぇ', 'fo': 'ふぉ',
    'ba': 'ば', 'bi': 'び', 'bu': 'ぶ', 'be': 'べ', 'bo': 'ぼ', 'bya': 'びゃ', 'byu': 'びゅ', 'byo': 'びょ',
    'pa': 'ぱ', 'pi': 'ぴ', 'pu': 'ぷ', 'pe': 'ぺ', 'po': 'ぽ', 'pya': 'ぴゃ', 'pyu': 'ぴゅ', 'pyo': 'ぴょ',
    'ma': 'ま', 'mi': 'み', 'mu': 'む', 'me': 'め', 'mo': 'も', 'mya': 'みゃ', 'myu': 'みゅ', 'myo': 'みょ',
    'ya': 'や', 'yu': 'ゆ', 'yo': 'よ',
    'ra': 'ら', 'ri': 'り', 'ru': 'る', 're': 'れ', 'ro': 'ろ', 'rya': 'りゃ', 'ryu': 'りゅ', 'ryo': 'りょ',
    'wa': 'わ', 'wi': 'うぃ', 'we': 'うぇ', 'wo': 'を',
    'va': 'ゔぁ', 'vi': 'ゔぃ', 'vu': 'ゔ', 've': 'ゔぇ', 'vo': 'ゔぉ',
    'xa': 'ぁ', 'xi': 'ぃ', 'xu': 'ぅ', 'xe': 'ぇ', 'xo': 'ぉ', 'xya': 'ゃ', 'xyu': 'ゅ', 'xyo': 'ょ',
    'xtu': 'っ', 'xtsu': 'っ', 'xwa': 'ゎ',
    '-': 'ー', ',': '、', '.': '。', '[': '「', ']': '」',
    'z/': '・', 'z-': '〜', 'z.': '…', 'z,': '‥',
}
_PREFIXES = set()
for _k in _ROMAJI:
    for _i in range(1, len(_k)):
        _PREFIXES.add(_k[:_i])
_VOWELS = 'aiueo'


def katakana(s):
    """Hiragana (U+3041..U+3096) to katakana; everything else unchanged."""
    out = []
    for c in s:
        o = ord(c)
        out.append(chr(o + 0x60) if 0x3041 <= o <= 0x3096 else c)
    return ''.join(out)


def _is_romaji_char(c):
    return 'a' <= c <= 'z' or c in "-,.[]/'"


class Romaji:
    """Incremental romaji -> hiragana. feed() returns the kana produced."""
    def __init__(self):
        self.pending = ''

    def feed(self, c):
        out = ''
        s = self.pending + c
        while True:
            if s in _ROMAJI:
                self.pending = ''
                return out + _ROMAJI[s]
            if s in _PREFIXES:
                self.pending = s
                return out
            p = self.pending
            if p == 'n':                                     # n before anything else: ん
                out += 'ん'
            elif len(p) == 1 and p == c and p not in _VOWELS and 'a' <= c <= 'z':
                self.pending = c                             # doubled consonant: っ
                return out + 'っ'
            if p == '':                                      # c alone is not romaji
                self.pending = ''
                return out
            self.pending = ''                                # drop the invalid prefix, retry c
            s = c

    def flush(self):
        """Ends the romaji: a trailing n becomes ん, anything else is dropped."""
        p, self.pending = self.pending, ''
        return 'ん' if p == 'n' else ''

    def backspace(self):
        if self.pending:
            self.pending = self.pending[:-1]
            return True
        return False


class SkkDict:
    """In-memory dictionary: reading (with okurigana consonant) -> candidates.

    Lines in SKK-JISYO form, UTF-8: `かんじ /漢字/感じ/幹事;annotation/`.
    A reading ending in an ASCII letter is okuri-ari (`かk /書/描/`)."""
    def __init__(self, lines=()):
        self.entries = {}
        for line in lines:
            self.add_line(line)

    def add_line(self, line):
        line = line.strip()
        if not line or line[0] == ';':
            return
        key, _, rest = line.partition(' ')
        old = self.entries.setdefault(key, [])
        for c in rest.strip().strip('/').split('/'):
            c = c.split(';', 1)[0]
            if c and c not in old:
                old.append(c)

    def lookup(self, key):
        return list(self.entries.get(key, ()))


class SortedFileDict:
    """A larger dictionary read from a file instead of memory: UTF-8 lines in
    SKK-JISYO form, sorted by the UTF-8 bytes of their reading, one reading
    per line. lookup() binary-searches by seeking, so only a few lines are
    read per conversion and the file can be far larger than the heap."""
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.f.seek(0, 2)
        self.size = self.f.tell()

    def _line_at(self, pos):
        """The first whole line starting at or after pos, and where it starts."""
        f = self.f
        if pos > 0:
            f.seek(pos - 1)
            if f.read(1) != b'\n':
                f.readline()
        else:
            f.seek(0)
        start = f.tell()
        return f.readline(), start

    def lookup(self, key):
        k = key.encode() + b' '
        lo, hi = 0, self.size
        while lo < hi:
            mid = (lo + hi) // 2
            line, start = self._line_at(mid)
            if not line or line[:len(k)] >= k:
                hi = mid
            else:
                lo = start + len(line)
        line, _ = self._line_at(lo)
        if line[:len(k)] != k:
            return []
        d = SkkDict((line.decode(),))
        return d.lookup(key)

    def close(self):
        self.f.close()


class SkkEngine:
    def __init__(self, dictionary, inline=4, page=7, mode=ASCII):
        self.dic = dictionary
        self.inline, self.page = inline, page
        self.mode = mode
        self.romaji = Romaji()
        self.out = ''
        self.message = ''
        self._clear()

    def _clear(self):
        self.state = NORMAL
        self.reading = ''
        self.okuri_char = ''
        self.okuri = ''
        self.in_okuri = False
        self.cands = []
        self.index = 0
        self.romaji.pending = ''

    # ---- what the desktop shows ----

    def active(self):
        """True while a preedit (or pending romaji) exists."""
        return self.state != NORMAL or self.romaji.pending != ''

    def _kana(self, s):
        return katakana(s) if self.mode == KATAKANA else s

    def preedit(self):
        """(text, highlight): highlight is (start, end) in characters or None."""
        if self.state == CONVERT:
            c = self.cands[self.index] + self._kana(self.okuri)
            return '▼' + c, (1, 1 + len(c))
        if self.state == PREEDIT:
            s = '▽' + self._kana(self.reading)
            if self.in_okuri:
                s += '*' + self._kana(self.okuri)
            return s + self.romaji.pending, None
        return self.romaji.pending, None

    def candidates(self):
        """(page items [(key, candidate)], page number, pages) once the list is shown, else None."""
        if self.state != CONVERT or self.index < self.inline:
            return None
        first = self.inline + (self.index - self.inline) // self.page * self.page
        items = [(LIST_KEYS[i], self.cands[first + i]) for i in range(min(self.page, len(self.cands) - first))]
        pages = (len(self.cands) - self.inline + self.page - 1) // self.page
        return items, (first - self.inline) // self.page + 1, pages

    def take(self):
        """Text committed since the last call."""
        out, self.out = self.out, ''
        return out

    # ---- input ----

    def _commit(self, s):
        self.out += s

    def _commit_preedit(self):
        """Commits what is shown (candidate or reading), ends the conversion."""
        if self.state == CONVERT:
            self._commit(self.cands[self.index] + self._kana(self.okuri))
        elif self.state == PREEDIT:
            self._commit(self._kana(self.reading + self.okuri + self.romaji.flush()))
        else:
            self._commit(self._kana(self.romaji.flush()))
        self._clear()

    def _add_kana(self, kana):
        if not kana:
            return
        if self.state == PREEDIT and self.in_okuri:
            self.okuri += kana
        elif self.state == PREEDIT:
            self.reading += kana
        else:
            self._commit(self._kana(kana))

    def _convert(self):
        """▽ -> ▼ with the first candidate, or a message if there is none."""
        if self.in_okuri:
            key = self.reading + self.okuri_char
        else:
            self.reading += self.romaji.flush()
            key = self.reading
        cands = self.dic.lookup(key) if key and key != self.okuri_char else []
        if not cands:
            self.message = '候補なし: ' + key
            if self.in_okuri:                                # keep the okurigana as plain reading
                self.reading += self.okuri
                self.okuri, self.okuri_char, self.in_okuri = '', '', False
            return
        self.cands = cands
        self.index = 0
        self.state = CONVERT

    def _okuri_done(self):
        """The okurigana is complete once its romaji is (and it is not just っ)."""
        return self.in_okuri and self.okuri and not self.romaji.pending and self.okuri[-1] != 'っ'

    def feed_char(self, c):
        """A printable ASCII character. True when the IME used it."""
        self.message = ''
        if self.mode == ASCII:
            return False
        if self.state == CONVERT:
            return self._convert_char(c)
        if c == ' ':
            if self.state == PREEDIT:
                self._convert()
                return True
            self._commit_preedit()                           # pending romaji, then the space itself
            return False
        if c in 'lq' and self.romaji.pending == 'n':         # "Nihon" then l or q: the n is ん
            self._add_kana(self.romaji.flush())
        if self.state == NORMAL and not self.romaji.pending:
            if c == 'q':
                self.mode = KATAKANA if self.mode == HIRAGANA else HIRAGANA
                return True
            if c == 'l':
                self.mode = ASCII
                return True
        if self.state == PREEDIT and not self.romaji.pending and c == 'l':
            self._commit_preedit()
            self.mode = ASCII
            return True
        if self.state == PREEDIT and not self.romaji.pending and c == 'q':
            self._commit(katakana(self.reading) if self.mode == HIRAGANA else self.reading)
            self._clear()
            return True
        if 'A' <= c <= 'Z':
            low = chr(ord(c) + 32)
            if self.state == NORMAL:
                self._commit_preedit()
                self.state = PREEDIT
            elif not self.in_okuri and self.reading and self.romaji.pending in ('', 'n'):
                self.reading += self.romaji.flush()             # a complete reading: okurigana
                self.in_okuri, self.okuri_char = True, low
            self._add_kana(self.romaji.feed(low))
            if self._okuri_done():
                self._convert()
            return True
        if not _is_romaji_char(c):
            if self.state == PREEDIT:
                self._commit_preedit()
            else:
                self._commit(self._kana(self.romaji.flush()))
            return False
        self._add_kana(self.romaji.feed(c))
        if self._okuri_done():
            self._convert()
        return True

    def _convert_char(self, c):
        if c == ' ':
            if self.index < self.inline:                     # inline candidates, one by one
                nxt = self.index + 1
            else:                                            # then pages: index is a page's first
                nxt = self.inline + ((self.index - self.inline) // self.page + 1) * self.page
            if nxt < len(self.cands):
                self.index = nxt
            else:
                self.message = '最後の候補'
            return True
        if c == 'x':
            if self.index == 0:
                self._back_to_preedit()
            elif self.index <= self.inline:
                self.index -= 1
            else:
                self.index -= self.page
            return True
        page = self.candidates()
        if page is not None and c in LIST_KEYS:
            i = LIST_KEYS.index(c)
            if i < len(page[0]):
                self._commit(page[0][i][1] + self._kana(self.okuri))
                self._clear()
            return True
        self._commit_preedit()                               # typing on: commit, then the key
        return self.feed_char(c)

    def _back_to_preedit(self):
        self.state = PREEDIT
        if self.in_okuri:                                    # the okurigana becomes reading again
            self.reading += self.okuri
            self.okuri, self.okuri_char, self.in_okuri = '', '', False
        self.cands, self.index = [], 0

    def feed_key(self, name):
        """A named key: 'enter', 'escape', 'ctrl-g', 'ctrl-j', 'backspace' or
        'other'. True when the IME used it; otherwise the key goes on."""
        self.message = ''
        if name == 'ctrl-j':
            if self.mode == ASCII:
                self.mode = HIRAGANA
            else:
                self._commit_preedit()
            return True
        if self.mode == ASCII:
            return False
        if name == 'enter':
            if self.state == NORMAL:
                self._commit_preedit()
                return False
            self._commit_preedit()
            return True
        if name in ('escape', 'ctrl-g'):
            if self.state == CONVERT:
                self._back_to_preedit()
                return True
            if self.state == PREEDIT or self.romaji.pending:
                self._clear()
                return True
            return False
        if name == 'backspace':
            if self.state == CONVERT:
                self._back_to_preedit()
                return True
            if self.romaji.backspace():
                return True
            if self.state != PREEDIT:
                return False
            if self.in_okuri:
                if self.okuri:
                    self.okuri = self.okuri[:-1]
                else:
                    self.in_okuri, self.okuri_char = False, ''
            elif self.reading:
                self.reading = self.reading[:-1]
            else:
                self._clear()                                # ▽ alone: leave the preedit
            return True
        # Any other key: the preedit is committed and the key acts as usual.
        if self.active():
            self._commit_preedit()
        return False


TEST_DICTIONARY = """\
; A small deterministic dictionary for tests and demos (SKK-JISYO form, UTF-8).
かんじ /漢字/感じ/幹事/監事/完治/換字/莞爾/寛治/
こう /行/高/工/公/効/校/考/甲/港/光/好/後/口/交/候/
にほん /日本/二本/
にほんご /日本語/
かな /仮名/かな/
かぐら /神楽/
めも /メモ/
へんかん /変換/返還/
にゅうりょく /入力/
こうほ /候補/
せんたく /選択/洗濯/
ぶんしょう /文章/
へんしゅう /編集/
きょう /今日/京/強/教/
わたし /私/渡し/
さくら /桜/
はな /花/鼻/華/
にっき /日記/
いちご /苺/一語/
しょうせつ /小説/
きかい /機械/機会/
ごはん /ご飯/御飯/
おくr /送/贈/
かk /書/描/
よm /読/詠/
つかu /使/遣/
はしr /走/
みr /見/観/
たべr /食べ/
おこt /怒/
かえr /帰/返/
えらb /選/
"""


def test_dictionary():
    return SkkDict(TEST_DICTIONARY.splitlines())


class SkkInput:
    """SKK in front of a kagura_desktop.Desktop, as the sink of TerminalKeys.

    Keys reach the engine while the active window's focused control is an
    editable field or editor; otherwise (menus open, a button focused, no
    window) they go to the desktop as before. changed(engine) is called after
    every key, for a mode and candidate display."""
    def __init__(self, desk, engine, changed=None):
        import kagura_desktop as kd
        self.kd, self.desk, self.engine, self.changed = kd, desk, engine, changed
        self.target = None          # (window, id) holding the preedit

    def _show(self, target):
        e, kd = self.engine, self.kd
        text, hl = e.preedit()
        if self.target is not None and self.target != target:
            try:
                self.target[0].set_preedit(self.target[1], '')
            except ValueError:                               # closed meanwhile
                pass
        if target is not None:
            a, b = hl if hl else (-1, -1)
            target[0].set_preedit(target[1], text, a, b)
        self.target = target if text else None

    def _flush(self, target):
        out = self.engine.take()
        if out:
            if target is not None:
                target[0].set_preedit(target[1], '')         # the text replaces the preedit
            self.desk.text(out)

    def key(self, k, ch=0, mods=0):
        kd, e = self.kd, self.engine
        target = self.desk.input_target()
        if target is None and not e.active():
            self.desk.key(k, ch, mods)
            return
        if isinstance(ch, str):
            ch = ord(ch) if ch else 0
        ctrl = mods & kd.MOD_CTRL
        if k == kd.KEY_CHAR and ctrl and ch in (ord('j'), ord('g')):
            used = e.feed_key('ctrl-j' if ch == ord('j') else 'ctrl-g')
        elif k == kd.KEY_CHAR and not (mods & (kd.MOD_CTRL | kd.MOD_ALT)) and 0x20 <= ch <= 0x7E:
            used = e.feed_char(chr(ch))
        elif k == kd.KEY_ENTER and not mods:
            used = e.feed_key('enter')
        elif k == kd.KEY_ESCAPE:
            used = e.feed_key('escape')
        elif k == kd.KEY_BACKSPACE and not mods:
            used = e.feed_key('backspace')
        else:
            used = e.feed_key('other')
        self._flush(target)
        self._show(target)
        if not used:
            self.desk.key(k, ch, mods)
        if self.changed:
            self.changed(e)

    def text(self, buf):
        """UTF-8 already composed (e.g. by the terminal's own IME): commits the
        preedit first, then the text goes in as typed."""
        target = self.desk.input_target()
        if self.engine.active():
            self.engine.feed_key('other')
            self._flush(target)
            self._show(target)
        self.desk.text(buf)
        if self.changed:
            self.changed(self.engine)
