# KAGURA-UI layout計測とButton描画の呼出し削減

2026-11-02 JST。[部分clipの字形](kagura-ui-glyph-cache.md#部分clipの字形)の後続。

## 段階別の計測

RP2040で`App.step`の各段階を計測した。条件は次のとおり。

- RAMに送ったUIのinstanceのmethodを時間計測用に包んだ（SDKのclassは変更していない）。
- 部分clipの変更まで入れた状態で、32 stepの平均を取った。
- 値には包んだ関数の負荷を含む。

| 段階 | label | button | focus |
| --- | --- | --- | --- |
| step全体 | 18.8 ms | 35.4 ms | 36.0 ms |
| arrange（layout） | 7.0 ms | 7.3 ms | 0.2 ms |
| └ font.measure | 4.7 ms | 4.8 ms | — |
| root._draw | 6.4 ms | 16.1 ms | 23.7 ms |
| └ backend.fill_rect | 0.9 ms | 5.1 ms | 8.8 ms |
| └ font.draw | 2.9 ms | 6.0 ms | 7.8 ms |
| flush | 2.5 ms | 3.5 ms | 6.1 ms |

- relayoutのたびに、全Label/Buttonの文字列（4行の日本語blockを含む）を1文字ずつ`advance()`で測り直していた。
  - 幅と高さが固定のwidgetも、測る必要がないのに測っていた。
- Buttonは、面のfillと1 pxの`rect`（4回のfill）で、SDK `fill_rect`を5回呼んでいた。
  - SDK `fill_rect`は、呼出しあたり約1 msの固定費がある。

## 変更

- `Label`（`Button`を含む）は、測った大きさを、文字列objectとfontが同じ間は保持する。
  - 文字列はimmutableなので、同一性で判定する。直接代入した新しい文字列も、測り直す。
  - 幅・高さが両方とも固定なら、文字列を測らない。
- `Button.paint`は、枠の色で全体を塗ってから、内側を面の色で塗る。
  - 従来のfill＋4辺と同じ画素を、2回の呼出しで描く。
  - 幅・高さが2未満のときは内側が空になり、全体が枠の色になる（従来と同じ）。
- 公開API、描画結果、layoutの結果は変えていない。

## RP2040実測

同じtool版で続けて実行した。

- A: `--ref feat/kagura-ui-clipped-glyph`
- B: この変更
- 条件: cache 64、32 samples × 4 rounds
- toolは`widgets.py`も送る。benchmarkの後に送るので、benchmarkのSceneは送った版のclassを使う。

`damage_limit=1`のframe p50（各roundのp50の範囲）:

| workload | 変更前 | 変更後 | 差 |
| --- | --- | --- | --- |
| label | 16.03〜16.23 ms | 11.70〜11.83 ms | −27% |
| button | 27.92〜27.98 ms | 21.38〜21.41 ms | −23% |
| focus | 26.88〜26.99 ms | 24.69〜24.83 ms | −8% |
| labels | 23.89〜23.96 ms | 19.35〜19.38 ms | −19% |
| glyphcut | 102.9〜103.0 ms | 102.5〜103.0 ms | 0 |
| idle | 0.42 ms | 0.41〜0.43 ms | 0 |

- `damage_limit=4`でも同じ傾向（例: button 30.3 → 23.7 ms）。
- heap/step p50は、80〜560 B少ない。tile数・payloadは同一。
- CRCはすべて一致（incremental＝全画面、limit 1＝4、Viper＝Python 3228843279）。
- `ERROR_CODE 0`。consoleは復帰した。
- log: [paint-rp2040-base.txt](kagura-ui-logs/paint-rp2040-base.txt)、[paint-rp2040-measure.txt](kagura-ui-logs/paint-rp2040-measure.txt)

## mainからの累積（参考）

#53マージ直後（`57b9dea`、[focus記録](kagura-ui-focus.md)のbase）と比べると、`damage_limit=1`のframe p50は次のとおり。

| workload | #53 | 現在 | 差 |
| --- | --- | --- | --- |
| label | 21.5 ms | 11.7 ms | −45% |
| button | 39.0 ms | 21.4 ms | −45% |
| focus | 42.5 ms | 24.8 ms | −42% |
| labels | 45.9 ms | 19.4 ms | −58% |
| glyphcut | 342 ms | 103 ms | −70% |

別sessionの比較を含む。各段階のsession内A/Bは、それぞれの記録を参照。

## PC検証

| 確認 | 結果 |
| --- | --- |
| `test_ui.py` | 44件PASS |
| 新規テスト | Buttonの5種の大きさ×focus×押下で、従来の描き方と画素一致。大きさの保持、文字列・fontの変更時の再計測、固定サイズでの計測省略 |
| `ui_runtime.py`（Buttonを含む） | CPython＝unix MicroPython。CRCはmainと同一 |
| unix MicroPython | widgets.pyを後から送る方式で、classが置き換わることを確認 |

## 残る課題

- focusでは、`root._draw`のうちSDK `fill_rect`が8.8 msを占める。ListViewの行とButtonの面で、呼出し回数が多い。
- SDKの`fill_rect`/`glyph8`の固定費（型検査など）はSDK側の課題（#57）。
- 長時間soak、Pico 2/2 W、UART/HIDは未検証。
