# SPDX-License-Identifier: Apache-2.0
"""Japanese menu on HDMI. Copy to the Pico, then at the REPL:

    import ja_menu
    ja_menu.run(kagura_console)   # boot console; or run(None, dev) without it

Arrow keys / w s move, Enter selects, q cancels. Returns the chosen index or
None. The console is paused during the menu and resumed afterwards.
"""
import sys
from kagura import regs as R
from kagura.video import Video
from kagura_ja import Font, TextLayer

ITEMS = ("はじめから", "つづきから", "音のテスト", "設定（Settings）", "終了")
PALETTE = 1  # palette 0 belongs to the console


def _key():
    c = sys.stdin.read(1)
    if c != "\x1b":
        return c
    if sys.stdin.read(1) != "[":
        return ""
    return {"A": "w", "B": "s"}.get(sys.stdin.read(1), "")


def run(console=None, dev=None, font_path="/fonts/misaki8.kfnt"):
    if dev is None:
        dev = console.screen.device
    if console is not None:
        console.pause()
    font = Font(font_path)
    try:
        video = Video(dev)
        video.palette(PALETTE * 16 + 1, 0xFFF)
        video.sprite(0, enable=False)  # the console cursor
        dev.write_reg(R.REG_DISPLAY_CTRL, R.DISPLAY_CTRL_DISPLAY_ENABLE
                      | R.DISPLAY_CTRL_BG_ENABLE | R.DISPLAY_CTRL_SPR_ENABLE)
        dev.commit()
        text = TextLayer(dev, font, tile_base=128, tile_count=256, map_x=0, map_y=0,
                         width=40, height=dev.height // 8, palette=PALETTE)
        text.clear()
        text.text("神楽（KAGURA-9）メニュー", col=2, row=1)
        text.text("ー" * 36, col=2, row=2)
        for i, item in enumerate(ITEMS):
            text.text(item, col=4, row=4 + i * 2)
        text.text("↑↓：選択　Enter：決定　q：中止", col=2, row=dev.height // 8 - 2)
        selected = 0
        while True:
            for i in range(len(ITEMS)):
                text.text("→" if i == selected else "　", col=2, row=4 + i * 2)
            text.flush()
            key = _key()
            if key == "w":
                selected = (selected - 1) % len(ITEMS)
            elif key == "s":
                selected = (selected + 1) % len(ITEMS)
            elif key in ("\r", "\n"):
                return selected
            elif key == "q":
                return None
    finally:
        font.close()
        if console is not None:
            console.resume()
