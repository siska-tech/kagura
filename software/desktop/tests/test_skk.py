# SPDX-License-Identifier: Apache-2.0
"""Tests of kagura.skk (SKK input) on the unix port, without the desktop.

A tiny editor model receives what the engine commits and the keys it passes
on, so each test states the document the user would see.

  MICROPYPATH=software/micropython micropython tests/test_skk.py
"""
import sys

from kagura import skk

failed = 0
run = 0


def check(cond, what=''):
    if not cond:
        raise AssertionError(what)


class Doc:
    """The editor as the IME's user sees it: committed text plus passed keys."""
    def __init__(self, mode=skk.HIRAGANA, dic=None):
        self.e = skk.SkkEngine(dic or skk.test_dictionary(), mode=mode)
        self.text = ''

    def keys(self, *seq):
        """Strings are typed character by character; tuples are named keys."""
        for item in seq:
            if isinstance(item, tuple):
                used = self.e.feed_key(item[0])
                self.text += self.e.take()
                if not used:
                    if item[0] == 'enter':
                        self.text += '\n'
                    elif item[0] == 'backspace':
                        self.text = self.text[:-1]
            else:
                for c in item:
                    used = self.e.feed_char(c)
                    self.text += self.e.take()
                    if not used:
                        self.text += c
        return self

    def pre(self):
        return self.e.preedit()[0]


ENTER, ESC, BS, CJ, CG, OTHER = ('enter',), ('escape',), ('backspace',), ('ctrl-j',), ('ctrl-g',), ('other',)


def test_romaji_table():
    cases = (('aiueo', 'あいうえお'), ('kakikukeko', 'かきくけこ'), ('shichitsufu', 'しちつふ'),
             ('kyakyukyo', 'きゃきゅきょ'), ('jajujo', 'じゃじゅじょ'), ('chacha', 'ちゃちゃ'),
             ('fafifefo', 'ふぁふぃふぇふぉ'), ('vu', 'ゔ'), ('wo', 'を'), ('xtuxya', 'っゃ'),
             ('nanninunn', 'なんいぬん'), ("kan'i", 'かんい'), ('kanji', 'かんじ'), ('sanpo', 'さんぽ'),
             ('nyan', 'にゃ'), ('kitte', 'きって'), ('zassi', 'ざっし'), ('matcha', 'まちゃ'),
             ('-,.[]', 'ー、。「」'), ('z/z-z.z,', '・〜…‥'))
    for romaji, kana in cases:
        d = Doc().keys(romaji)
        check(d.text == kana, (romaji, d.text))
    d = Doc().keys('nyan', ENTER)                 # a trailing n becomes ん when the input ends
    check(d.text == 'にゃん\n', d.text)
    d = Doc().keys('kq')                          # q after a pending k: k dropped, q toggles nothing here
    check(d.text == '', d.text)


def test_modes():
    d = Doc(mode=skk.ASCII).keys('abc', CJ, 'ka', 'l', 'ka', CJ, 'q', 'ka', 'q', 'ka')
    check(d.text == 'abcかkaカか', d.text)
    check(d.e.mode == skk.HIRAGANA)
    d = Doc().keys('Katakana', 'q')               # q in ▽: the reading in katakana
    check(d.text == 'カタカナ', d.text)
    d = Doc().keys('Nihon', 'l', 'go')            # l in ▽: commit, then ASCII
    check(d.text == 'にほんgo' and d.e.mode == skk.ASCII, d.text)


def test_conversion():
    d = Doc().keys('Nihongo')
    check(d.pre() == '▽にほんご', d.pre())
    d.keys(' ')
    check(d.pre() == '▼日本語' and d.e.preedit()[1] == (1, 4), d.e.preedit())
    d.keys(ENTER)                                 # Enter commits, no new line
    check(d.text == '日本語' and d.pre() == '', d.text)
    d = Doc().keys('Nihon ', 'wo')                # typing on commits the candidate
    check(d.text == '日本を', d.text)
    d = Doc().keys('Kana', ENTER)                 # Enter in ▽ commits the reading
    check(d.text == 'かな', d.text)
    d = Doc().keys('KA')                          # uppercase inside a syllable is just romaji
    check(d.pre() == '▽か', d.pre())
    d = Doc().keys('Nihon', CJ)                   # Ctrl+J also commits
    check(d.text == 'にほん', d.text)


def test_candidates_and_list():
    d = Doc().keys('Kou ')
    seen = [d.pre()]
    for _ in range(3):
        d.keys(' ')
        seen.append(d.pre())
    check(seen == ['▼行', '▼高', '▼工', '▼公'], seen)
    check(d.e.candidates() is None)
    d.keys(' ')                                   # the 5th: the list, 7 at a time
    items, page, pages = d.e.candidates()
    check([c for _, c in items] == ['効', '校', '考', '甲', '港', '光', '好'] and (page, pages) == (1, 2), items)
    check(items[0][0] == 'a' and items[6][0] == 'l')
    d.keys(' ')
    items, page, pages = d.e.candidates()
    check([c for _, c in items] == ['後', '口', '交', '候'] and page == 2, items)
    d.keys(' ')
    check(d.e.message == '最後の候補')
    d.keys('x')                                   # back a page
    check(d.e.candidates()[1] == 1)
    d.keys('s')                                   # pick the 2nd of the page
    check(d.text == '校' and not d.e.active(), d.text)
    d = Doc().keys('Kou ', ' ', 'x', 'x')         # x back to the first, then to ▽
    check(d.pre() == '▽こう', d.pre())
    d = Doc().keys('Kanji', ' ' * 5)              # the list: 4 of 8 candidates left
    check(len(d.e.candidates()[0]) == 4)
    d.keys('k')                                   # k (6th key) has no candidate on this page
    check(d.e.candidates() is not None and d.text == '', d.text)
    d = Doc().keys('Kanji', ' ', ' ', ' ', ' ', ' ', 'd')
    check(d.text == '莞爾', d.text)


def test_okurigana():
    for romaji, want in (('KaKu', '書く'), ('OkuRu', '送る'), ('YoMu', '読む'), ('TukaU', '使う'),
                         ('OkoTta', '怒った'), ('TabeRu', '食べる'), ('MiRu', '見る')):
        d = Doc().keys(romaji)
        check(d.pre() == '▼' + want, (romaji, d.pre()))
        d.keys(ENTER)
        check(d.text == want, (romaji, d.text))
    d = Doc().keys('KaKu', ' ', ENTER)            # second candidate keeps the okurigana
    check(d.text == '描く', d.text)
    d = Doc().keys('Ka')
    d.keys('K')
    check(d.pre() == '▽か*k', d.pre())
    d = Doc().keys('KaKu', ESC)                   # cancel: okurigana back into the reading
    check(d.pre() == '▽かく', d.pre())


def test_cancel_and_backspace():
    d = Doc().keys('Kanji ', ESC)
    check(d.pre() == '▽かんじ', d.pre())
    d.keys(ESC)
    check(d.pre() == '' and d.text == '', d.text)
    d = Doc().keys('Kanji ', CG, CG)
    check(d.pre() == '' and d.text == '')
    d = Doc().keys('k', ESC)                      # pending romaji is dropped
    check(d.pre() == '' and not d.e.active())
    check(not Doc().e.feed_key('escape'))         # nothing to cancel: the app gets Escape
    d = Doc().keys('Kank')
    check(d.pre() == '▽かんk', d.pre())
    d.keys(BS)
    check(d.pre() == '▽かん', d.pre())           # romaji first
    d.keys(BS, BS)
    check(d.pre() == '▽', d.pre())               # then the reading
    d.keys(BS)
    check(d.pre() == '' and not d.e.active())     # then the ▽ itself
    d = Doc().keys('ab', BS)                      # pending b removed, then nothing pending:
    check(d.text == 'あ', d.text)
    d.keys(BS)                                    # the editor's own Backspace
    check(d.text == '', d.text)
    d = Doc().keys('KaKu', BS)                    # ▼: back to ▽
    check(d.pre() == '▽かく', d.pre())
    d = Doc().keys('Ka', 'K', BS)                 # the okurigana's romaji, its marker, the reading
    check(d.pre() == '▽か*', d.pre())
    d.keys(BS)
    check(d.pre() == '▽か', d.pre())
    d.keys(BS)
    check(d.pre() == '▽', d.pre())


def test_no_candidates_and_other_keys():
    d = Doc().keys('Zuzuzu ')
    check(d.pre() == '▽ずずず' and d.e.message.startswith('候補なし'), d.e.message)
    d.keys(OTHER)                                 # e.g. an arrow key: commit, then the key
    check(d.text == 'ずずず' and not d.e.active(), d.text)
    d = Doc().keys('Kanji ', OTHER)
    check(d.text == '漢字', d.text)
    d = Doc().keys('a', '1', '!', ' ')            # digits and symbols pass as ASCII
    check(d.text == 'あ1! ', d.text)
    d = Doc().keys('k ')                          # pending romaji then a space
    check(d.text == ' ', d.text)


def test_utf8_and_katakana():
    check(skk.katakana('ゔぁっぴー、かな') == 'ヴァッピー、カナ')
    d = Doc().keys('q', 'Kanji ', ENTER, 'kana')  # katakana mode: candidates unchanged
    check(d.text == '漢字カナ', d.text)
    for s in (d.text, '日本語の文章'):
        check(s.encode().decode() == s)
    check(len('▼日本語') == 4 and len('▼日本語'.encode()) == 12)


def test_dictionary_parsing_and_files():
    dic = skk.SkkDict(('かんじ /漢字;注釈/感じ/', 'かんじ /漢字/幹事/', '; comment', ''))
    check(dic.lookup('かんじ') == ['漢字', '感じ', '幹事'], dic.lookup('かんじ'))
    check(dic.lookup('ない') == [])
    path = '/tmp/kagura-skk-test-dict.txt'
    entries = sorted(skk.TEST_DICTIONARY.splitlines()[1:], key=lambda l: l.split(' ')[0].encode())
    with open(path, 'w') as f:
        for line in entries:
            f.write(line + '\n')
    fd = skk.SortedFileDict(path)
    mem = skk.test_dictionary()
    for line in entries:
        key = line.split(' ')[0]
        check(fd.lookup(key) == mem.lookup(key), key)
    for missing in ('あ', 'ん', 'かんじx', 'こ', 'zzz'):
        check(fd.lookup(missing) == [], missing)
    fd.close()
    d = Doc(dic=skk.SortedFileDict(path)).keys('Kanji ', ENTER)
    check(d.text == '漢字', d.text)


def test_long_typing_is_stable():
    d = Doc()
    for i in range(300):
        d.keys('Kanji ', ' ' * (i % 6), ENTER, 'no', 'KaKu', ENTER, ' ')
    check(not d.e.active() and len(d.text) > 1000)
    check(d.text.count('く') == 300, d.text.count('く'))


class PopupDoc(Doc):
    def __init__(self, style, mode=skk.HIRAGANA):
        Doc.__init__(self, mode)
        self.e = skk.SkkEngine(skk.test_dictionary(), mode=mode, style=style)


DOWN, UP = ('down',), ('up',)
KOU = ('行', '高', '工', '公', '効', '校', '考', '甲', '港', '光', '好', '後', '口', '交', '候')


def test_popup_modern():
    d = PopupDoc(skk.MODERN).keys('Kou ')
    check(d.e.popup() == (list(KOU[:5]), 0, '1/3'), d.e.popup())   # the list at once
    check(d.e.indicator() == '▼ 変換')
    d.keys(' ', DOWN)
    check(d.e.popup() == (list(KOU[:5]), 2, '1/3') and d.pre() == '▼工')
    d.keys(DOWN, DOWN, DOWN)
    check(d.e.popup() == (list(KOU[5:10]), 0, '2/3') and d.pre() == '▼校')
    d.keys(UP)
    check(d.e.popup() == (list(KOU[:5]), 4, '1/3'))
    d.keys('x', ENTER)                                # x: back one, Enter: the highlighted one
    check(d.text == '公' and d.e.popup() is None and d.e.indicator() == 'あ かな', d.text)
    d.keys('Kou ', ' ' * 5, '3')            # page 2, the 3rd: 甲
    check(d.text == '公甲', d.text)
    d.keys('Kou ', UP)                                # Up on the first stays
    check(d.pre() == '▼行')
    d.keys(ESC)
    check(d.pre() == '▽こう' and d.e.popup() is None and d.e.indicator() == '▽ 読み')
    d.keys(ESC)
    d.keys('Kou ', ' ' * 14)                          # the last, then 最後の候補
    check(d.e.popup() == (list(KOU[10:]), 4, '3/3'))
    d.keys(' ')
    check(d.e.popup() == (list(KOU[10:]), 4, '最後の候補'), d.e.popup())
    d.keys(ESC, ESC, 'Mogu ')
    check(d.e.popup() == ([], -1, '候補なし: もぐ'), d.e.popup())
    d.keys(ESC, 'Nihon ')
    check(d.e.popup() == (['日本', '二本'], 0, ''))  # one page: no page number
    d.keys('9')                                       # not a candidate key: commits, then 9
    check(d.text.endswith('日本9'), d.text)


def test_popup_classic():
    d = PopupDoc(skk.CLASSIC).keys('Kou ')
    check(d.pre() == '▼行' and d.e.popup() is None)   # the first candidate inline
    d.keys(' ')
    check(d.e.popup() == (list(KOU[1:6]), 0, '1/3') and d.pre() == '▼高')
    d.keys(DOWN, '2')
    check(d.text == '工', d.text)
    d.keys('Kou  ', 'x', 'x')
    check(d.pre() == '▽こう')


def test_popup_skk_style_unchanged():
    d = Doc().keys('Kou ')
    check(d.e.popup() is None and d.e.indicator() == '▼ 変換')
    check(d.e.feed_key('down') is False)              # an other key: commits
    d.text += d.e.take()
    check(d.text == '行')
    d.keys('Mogu ')
    check(d.e.popup() == ([], -1, '候補なし: もぐ'))
    for mode, label in ((skk.ASCII, 'A 直接'), (skk.HIRAGANA, 'あ かな'), (skk.KATAKANA, 'ア カナ')):
        check(skk.SkkEngine(skk.test_dictionary(), mode=mode).indicator() == label)


def main():
    global failed, run
    tests = sorted((k, v) for k, v in globals().items() if k.startswith('test_'))
    for name, fn in tests:
        run += 1
        try:
            fn()
            print('ok   ' + name[5:])
        except Exception as e:  # noqa: BLE001
            failed += 1
            print('FAIL %s: %r' % (name[5:], e))
            sys.print_exception(e)
    print('%d tests, %d failed' % (run, failed))
    sys.exit(1 if failed else 0)


main()
