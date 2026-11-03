# SPDX-License-Identifier: Apache-2.0
"""SKK Japanese input in 神楽メモ帳: a scripted, reproducible demonstration.

The editor (desktop_editor.Editor) runs with the SKK input method
(kagura.skk) in front of it. The script is the bytes a terminal sends for
each key - romaji, spaces, Enter (CR), Escape, Ctrl+J (LF) - fed through the
same decoder as real typing, so the whole input path is exercised. Scene
CRCs are equal on the host and the board.

On KAGURA-9 (firmware with SKK support):
    import desktop_skk; desktop_skk.main()                   # paced for watching
On a PC (unix port):
    micropython desktop_skk.py --host [--dump DIR]           # a CRC per scene

It shows: かな mode (Ctrl+J), a reading (▽) and its conversion (▼), typing
on to confirm, the candidate list with pages and choosing by key, okurigana
(EraBu -> 選ぶ), cancelling with Escape, Enter to confirm without a new line,
katakana (q) and ASCII (l). Nothing is saved.
"""
import time

import kagura_desktop as kd

import desktop_editor as de
from kagura import skk

# (bytes as a terminal sends them, scene name or None)
SCRIPT = (
    (b'\n', 'hiragana'),             # Ctrl+J: かな mode
    (b'Kagura', 'reading'),          # ▽かぐら
    (b' ', 'converted'),             # ▼神楽
    (b'de', None),                   # typing on confirms 神楽
    (b'Nihongo wo', None),
    (b'Nyuuryoku suru.', 'sentence'),
    (b'\r', None),                   # Enter with nothing pending: a new line
    (b'Kouho kara', None),
    (b'Kou     ', 'list'),           # convert, 3 more inline candidates, then the list
    (b' ', 'list-page-2'),
    (b'x', None),
    (b's', 'chosen'),                # s: the 2nd of the page (校)
    (b'wo', None),
    (b'EraBu', 'okurigana'),         # ▼選ぶ
    (b'.\r', None),
    (b'Henkan ', None),              # ▼変換
    (b'\x1b', 'cancel'),             # Escape: back to ▽へんかん
    (b'\x1b', None),                 # Escape: the preedit is gone
    (b'KaKu', None),
    (b'\r', 'enter-confirms'),       # Enter confirms 書く, no new line
    (b'.qmemoq', 'katakana'),        # q: カタカナ, q: back
    (b'l KAGURA-9', 'final'),        # l: ASCII
)

FINAL_TEXT = '神楽で日本語を入力する。\n候補から校を選ぶ。\n書く。メモ KAGURA-9'


def sleep_ms(ms):
    if ms > 0:
        if hasattr(time, 'sleep_ms'):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000)


class FakeClock:
    """Each call is 100 ms later: a lone Escape always times out at once."""
    t = 0

    def __call__(self):
        FakeClock.t += 100
        return FakeClock.t


def tour(app, step, key_ms=0, step_ms=0):
    keys = de.input_chain(app, clock=FakeClock())
    for data, scene in SCRIPT:
        for b in data:
            keys.feed(bytes((b,)))
            keys.expire()
            app.handle()
            app.desk.present()
            sleep_ms(key_ms)
        if scene:
            app.handle()
            step(scene)
            sleep_ms(step_ms)
    return app.win.get_text(app.ed)


def vram_crc(desk):
    """CRC32 of the 32,000 pattern bytes read back from the FPGA (board only)."""
    import binascii
    buf = bytearray(1000)
    crc = 0
    for off in range(0, 32000, 1000):
        desk.device.read_memory_into(off, buf)
        crc = binascii.crc32(buf, crc)
    return crc


def main(desk=None, out=print, key_ms=None, step_ms=None, dump=None):
    own = desk is None
    if own:
        from kagura.desktop import Desktop
        desk = Desktop(menus=de.MENUS, cursor=False)
    if key_ms is None:
        key_ms = 70 if own else 0
    if step_ms is None:
        step_ms = 1500 if own else 0
    app = de.Editor(desk, de.Documents('/docs'), 'スクリプト', ime=skk.SkkEngine(skk.test_dictionary()))
    scenes = [0]

    def step(name):
        import binascii
        scenes[0] += 1
        tiles = desk.present()
        mirror = getattr(desk, 'mirror', None)
        extra = ' tile4 %08x' % binascii.crc32(mirror) if mirror else ''
        if own:
            from kagura import regs as R
            extra = ' vram %08x error %d' % (vram_crc(desk), desk.device.read_reg(R.REG_ERROR_CODE))
        out('SCENE %d %s %08x %d%s' % (scenes[0], name, desk.crc(), tiles, extra))
        if dump:
            buf = bytearray(32000)
            desk.snapshot(buf)
            with open('%s/%02d-%s.raw' % (dump, scenes[0], name), 'wb') as f:
                f.write(buf)

    try:
        desk.present()
        text = tour(app, step, key_ms, step_ms)
        out('TEXT %s %s' % ('ok' if text == FINAL_TEXT else 'MISMATCH', repr(text)))
    finally:
        if own:
            desk.close()
    return text


if __name__ == '__main__':
    import sys
    if '--host' in sys.argv:
        dump = sys.argv[sys.argv.index('--dump') + 1] if '--dump' in sys.argv else None
        main(desk=de.HostDesktop(de.MENUS), dump=dump)
    else:
        main()
