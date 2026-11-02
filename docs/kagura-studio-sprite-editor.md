# KAGURA Studio sprite editor

2026-11-02 JST。[Canvas/SpriteCanvas](kagura-ui-canvas.md)を使う、最初のKAGURA Studioの機能。
`examples/ui_sprite_editor.py`の例であり、汎用のCanvas APIは変えていない。

## 画面

| 部品 | 位置 | 内容 |
| --- | --- | --- |
| 編集格子 | (8,20)、128×128 | 16×16、zoom 8。`SpriteCanvas`のsubclass |
| 1:1 preview | (152,20)、16×16 | zoom 1の`SpriteCanvas`。格子と同じ`Sprite4`を共有し、focusしない |
| palette | (152,48)、64×64 | 16色の4×4 `Canvas`のsubclass |
| 選択色 | (224,48)のswatchと`Color N` | 色0は`(clear)`と表示する |
| cursor座標 | (152,120) | `X n Y n` |
| 状態行 | (8,196) | Undo、import、hexの出力の結果 |

画素値0は透明で、UIの色0で表示する。

## 操作

| key | 動作 |
| --- | --- |
| 矢印 | 格子またはpaletteのcursorを移動 |
| Enter/Space | 格子: 選択色で塗る。palette: その色を選ぶ |
| Delete/Backspace | 消す（0、透明） |
| `0`〜`9`、`A`〜`F` | 色の選択（paletteのcursorも追従） |
| Tab | 格子とpaletteの間でfocusを移す |
| `U` | 1段のUndo。もう一度押すとRedo |
| `P` | `SPRITE_HEX <256桁>`をREPL（USB）へ出力 |
| Escape | 終了 |

- **Undo:** 直前の変更（塗る、消す、import）の前のdataを1つだけ保持する。変化のない操作では、記録を更新しない。

## hexの読込みと書出し

128 Bの`Sprite4`（[TILE4配置](kagura-ui.md#sprite4の配置tile4)）を、256桁のhexで受け渡す。

```python
import ui_sprite_editor
from kagura.ui import StdinInput
ui_sprite_editor.run(console=kagura_console, input_adapter=StdinInput())
text = ui_sprite_editor.editor.export_hex()     # Escapeで終了した後
ui_sprite_editor.run(data_hex=text, console=kagura_console, input_adapter=StdinInput())
```

- `export_hex()`は、小文字256桁のhexを返す。
- `import_hex(text)`は、空白と改行を無視し、大文字も受け付ける。Undoできる。
- 不正なhex（長さ、文字）は`ValueError`になり、spriteは変わらない。
- 16×16の128 Bは、16×16 hardware spriteの4 pattern（左上、右上、左下、右下）と同じ並びである。

## 再描画

- 塗る・消す・Undo・importでは、値が変わった画素についてだけ、格子のcellとpreviewの1画素を再描画する。
  - 同じbyteにある隣の画素でも、値が変わっていなければ描かない。
- Appの`damage_limit`を4にする。
  - 格子のcell、previewの画素、labelは、離れた小さい矩形のまま描かれる。
  - 1矩形に結合すると、画面の大半を描き直すことになる。
- 通常の編集では、画面全体を描き直さない。

## PC検証

| 確認 | 結果 |
| --- | --- |
| `test_ui.py` | 58件PASS（sprite editor 5件） |
| 配置・初期表示 | 格子とpreviewの画素がTILE4 dataと一致。paletteの16色、swatch、label |
| key操作 | 塗る、消す、色0、hexとpaletteでの選択、cursor座標 |
| Undo | 1段のUndo/Redo。変化のない消去で記録を上書きしない |
| hex | 長さ・文字の誤りを拒否。空白・大文字を受け付ける。Undoできる。`P`の出力。`run(data_hex=...)`相当の読込み |
| 再描画の範囲 | 塗る・消す・移動・色選択・Undo・1画素のimportで、1 stepに塗る面積が4000 px未満。同じbyteの隣の画素は描かない。逐次の描画は全体の再描画と一致 |
| mutation | 10件中9件を検出。残る1件（hexの長さ検査）は、`Sprite4.load`が同じ入力を拒否する等価な変更 |
| `ui_sprite_editor_runtime.py` | 300 eventの操作列で、CPythonとunix MicroPython v1.26の出力が一致（sprite CRC 2883309786） |
| ARM `mpy-cross` | PASS |
