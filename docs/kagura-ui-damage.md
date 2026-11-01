# KAGURA-UI 複数damage矩形

2026-11-02、main `b02a6ef`から`feat/kagura-ui-damage-rects`で実施。
引き継ぎロードマップ（`docs/claude-handoff`の`docs/KAGURA_ROADMAP.md`）のP1「damage領域最適化」。**PC検証のみで、RP2040実機は未計測**。

## 変更

`App._damage`は単一外接矩形から、最大`damage_limit`個（既定4）の矩形listになった。

- 重なる矩形、または辺を共有する矩形は結合する。角だけ接する矩形は結合しない。
- 上限を超えたら、新しい矩形を面積増加が最小の既存矩形へ結合し、再度重なりを判定する。
- stepは各矩形をclipにして背景fillと木全体の再合成を行い、flushはframe当たり1回のまま。
- 描画用と受付用の二つのlistを交換し、描画中のinvalidateは次frameへ残す。
- 描画・flushで例外が出た場合、そのframeの全矩形をdamageへ戻して伝播する。SDK dirtyも従来どおり保持。
- `damage_limit=1`は従来の単一外接矩形と同じ。比較測定やrollback用に残した。

SDKのdirty tile tracker、Framebuffer、転送、FENCE、RTL、ABIは変更していない。
tile trackerを複製せず、UI側は矩形のclipだけを増やした。

### 代償

- 矩形数だけtree走査が増える。widgetはclip外で打ち切るが、走査自体のCPU時間はRP2040で未計測。
- 矩形境界で字形が部分clipになると、glyph8ではなく従来の行単位描画になる。
- `_add_damage`は矩形tupleを生成する。allocation回数は従来どおり未計測で、allocation-freeとは主張しない。

## 検証（PC）

| 項目 | 結果 |
| --- | --- |
| `test_ui.py` | 37件PASS（既存33＋新規4）。既存の`_damage`参照はlist形式へ更新 |
| 新規: 離れた2 widget | 間のsentinel pixelを描き直さない。`damage_limit=1`では描き直す |
| 新規: 結合規則 | 重なり/辺共有/角接触/上限超過/画面clipの各期待値 |
| 新規: 40操作の乱数列 | 移動/非表示/日本語Label/Tab/List操作とflush失敗再試行で、limit 4とlimit 1の全pixelが毎step一致。最後に全画面再描画しても不変 |
| 新規: SDK dirty | 実TileFramebuffer（register model）で離れた2 Label更新のtile数がlimit 1より少なく、decode結果は一致 |
| mutation確認 | 先頭矩形だけ描画する改変で、新規2件がFAILすることを確認後に復元 |
| `ui_runtime.py` | CPythonとunix MicroPython v1.26（`4ce2dd2`）のCRCが一致。origin/mainの出力とも同一（4231501191/2117273149/26039419） |
| `ui_glyph_runtime.py` | CPython/unix MicroPython一致（288, 2456019654, 1936776583） |
| ARM | `mpy-cross -march=armv6m`でui/*.pyとtest_ui.pyをcompile |
| 他回帰 | framebuffer/frozen_alignment/link、`tools/test-ci-changes.sh` PASS |

### dirty tile比較

`python -I tools/compare-ui-damage.py`。既存`ui_benchmark`のworkload各32 samplesを
register model上で実行し、SDKが転送したtile数とpattern payload byteを比較する。
決定的な数で、時間ではない。CIでも実行し、最終bufferのCRCが異なれば失敗する。

| workload | limit 1 tiles / B | limit 4 tiles / B |
| --- | --- | --- |
| idle | 0 / 0 | 0 / 0 |
| label | 53 / 1696 | 53 / 1696 |
| button | 287 / 9184 | 272 / 8704 |
| focus | 1440 / 46080 | 960 / 30720 |
| move | 620 / 19840 | 620 / 19840 |
| scroll | 786 / 25152 | 774 / 24768 |
| screen | 38400 / 1228800 | 38400 / 1228800 |

最終buffer CRC32は両方2644429476。focusはButton（x=8）とListView（x=200）の間にある
Panelと空白を再描画しなくなり、tile数が約33%減った。
label/move/screenは元々単一矩形なので変化しない。静止の転送ゼロは維持。

## 実機で未確認の事項

- RP2040でのframe/CPU/flush時間。tile減少がframe時間短縮になるかは、tree走査増加との差し引きで未確定。
- 比較は`kagura-ui-standard.py`と同条件（RP2040 125 MHz、QSPI 5 MHz、32 samples）で、
  `app.damage_limit=1`と既定4を交互に測る想定。実施時はheap差分も別に記録する。
- 長時間soak、Pico 2/2 W、UART/HIDは本変更でも未検証。
