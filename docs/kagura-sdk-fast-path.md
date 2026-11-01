# TileFramebuffer fill_rect/glyph8 の高速経路

2026-11-02 JST。[layout計測](kagura-ui-layout-paint.md)の「残る課題」（SDK `fill_rect`の固定費）の後続。

## 呼出しの固定費

RP2040で、RAMのframebufferだけを使って計測した（FPGAへのI/Oなし）。
`fill_rect` 1×1は約600 µsで、その内訳は次のとおり。

| 部分 | 時間 |
| --- | --- |
| `_ints`（座標4個の型検査） | 約180 µs |
| `_range`（色の検査） | 47 µs |
| `_native_rect`（`min`/`max`での切り詰め、parameter設定、kernel） | 251 µs |
| └ Viper kernel本体 | 41 µs |
| └ Viper関数の呼出し | 9 µs |

- 小さい矩形では、実際の描画は全体の1割に満たない。
- KAGURA-UIの1 frameあたりの呼出し回数（PC model、`damage_limit=1`）:

| workload | `fill_rect` | `glyph8` |
| --- | --- | --- |
| label | 1 | 1.7 |
| button | 3 | 3.7 |
| focus | 6 | 5 |
| labels | 1 | 8.2 |
| glyphcut | 3 | 45 |

## 変更

`fill_rect`と`glyph8`の先頭に、検査済みの値だけが通る経路を追加した。

- 条件: Viper kernelが有効で、座標と色が厳密に`int`（`type(v) is int`）、色が0〜15。
  `glyph8`では、さらに`rows`が厳密に`bytes`/`bytearray`で長さ8。
- この経路では、`_ints`・`_range`・`_native_rect`の呼出しと`min`/`max`を通らない。
- 切り詰めは、`array('i')`に格納する前に行う。
  - `array('i')`への格納は、範囲外の整数を黙って折り返す（`2**40`は0になる）ため。
- 条件を満たさない引数は、すべて従来の検査経路を通る。
  - 対象: bool、intのsubclass、float、範囲外の色、Python backend。
  - 例外の型、メッセージ、検査の順序は変わらない。
  - RP2040のMicroPythonでは`isinstance(True, int)`がFalseである。このためboolの座標は`TypeError`、boolの色は`ValueError`になる。この挙動もそのまま残る。
- 例外は、`_params`、buffer、dirtyを書き換える前に起きる。

公開API、ABI、Viper kernel、firmwareは変えていない。

## PC検証

| 確認 | 結果 |
| --- | --- |
| `test_framebuffer.py` | 90件PASS（新規1件） |
| 新規テスト | Viper（emulator）と従来のPython経路で、23通りの`fill_rect`と17通りの`glyph8`の画素・dirty・例外が一致。例外後に`_params`・buffer・dirtyが不変 |
| mutation | 色の範囲検査、x・右端の切り詰め、glyphの画面外判定、`rows`の型・長さの検査を外すと、新規テストが失敗する（7件中6件）。残る1件（幅・高さの正の判定）は、切り詰め後の`x < right`で同じ結果になる等価な変更 |
| `test_ui.py` | 44件PASS。benchmarkの試験で、`--framebuffer`と同じく別のglobalsで実行したclassをUIに渡し、CRCの一致を確認 |

## RP2040実測

firmwareは変更していない（最終Phase 2 UF2）。

- 比較対象:
  - A: mainの`framebuffer.py`
  - B: この変更
- 方法:
  - どちらもRAMにsourceとして送った。Viper kernelはfrozenのものを共用した。
  - frozenのSDK classは置き換えていない。
  - FPGAへのI/Oは、UI benchmarkのflushだけである。

### 関数単体

1つのframebufferに対して、A・Bの関数を交互に呼んだ。各101回の中央値を4 round取り、順序はABBAとした。

| 呼出し | A | B | 差 |
| --- | --- | --- | --- |
| fill 1×1 | 902〜919 µs | 509〜527 µs | −399 µs |
| fill 8×8 | 884〜966 µs | 517〜522 µs | −443 µs |
| fill 72×10 | 1118〜1140 µs | 662〜680 µs | −460 µs |
| fill 96×16 | 1403〜1516 µs | 1036〜1037 µs | −452 µs |
| fill 320×240 | 7172〜7281 µs | 6898〜6904 µs | −374 µs |
| fill 画面外 | 556〜622 µs | 309〜310 µs | −295 µs |
| glyph8 内側 | 504〜549 µs | 410〜426 µs | −108 µs |
| glyph8 部分clip | 486〜505 µs | 409〜411 µs | −90 µs |
| glyph8 画面外 | 350〜390 µs | 277〜295 µs | −78 µs |

- 計測にはclosure経由の呼出しを含むため、絶対値はUIの経路より大きい。差を比較に使う。
- 同じ乱数列で2000回の`fill_rect`/`glyph8`を実行し、100回ごとのbuffer・dirtyのCRC（20点）がA・Bで完全一致した。kernelの呼出し回数も同じ（fill 656、glyph 890）。
- 19通りの不正な引数・境界値で、例外の型・メッセージがA・Bで一致した。13件が例外になり、その後のstateは不変だった。
- heap（GCを止めて200回の平均）:
  - `fill_rect`: 66.6 → 32.6 B/呼出し
  - `glyph8`: 32.4 → 0.4 B/呼出し
- log: [sdk-fastpath-micro.txt](kagura-ui-logs/sdk-fastpath-micro.txt)

### UI frame

`tools/kagura-ui-damage.py run --framebuffer`を使った。

- A: `--ref origin/main`
- B: 作業tree（UIのsourceはmainと同一）
- 順序: A1・B1・B2・A2の4 session
- 条件: 32 samples × 4 rounds

`damage_limit=1`のframe p50（各sessionの値は、round p50の中央値）:

| workload | A1 / A2 | B1 / B2 | 差 | heap/step |
| --- | --- | --- | --- | --- |
| idle | 430 / 429 µs | 429 / 428 µs | 0 | 0 → 0 B |
| label | 11388 / 11383 µs | 11122 / 11111 µs | −2.4% | 1120 → 1024 B |
| button | 20800 / 20795 µs | 20177 / 20180 µs | −3.0% | 1728 → 1504 B |
| focus | 24204 / 24213 µs | 22879 / 22898 µs | −5.5% | 1408 → 1056 B |
| labels | 19612 / 19627 µs | 17981 / 17987 µs | −8.3% | 1680 → 1360 B |
| glyphcut | 96148 / 96336 µs | 92576 / 92510 µs | −3.8% | 5312 → 3776 B |

- `damage_limit=4`でも同じ傾向（label −2.3%、button −3.4%、focus −5.3%、labels −1.2%、glyphcut −2.8%）。
- 4 sessionすべてで、workloadごとのCRC、tile数、payloadが一致した。
- `DAMAGE_VIPER_PYTHON_CRC 3228843279`。`ERROR_CODE 0`。consoleは復帰した。HDMIで描画崩れはなかった。
- Bの`HOST_SOURCE`にある`+dirty`は、commit前の作業treeを送ったことを示す。
  送った`framebuffer.py`のsha256（`6897b8b5…`）は、このbranchのファイルを同じ方法で変換した値と一致する。
- log: [A1](kagura-ui-logs/sdk-fastpath-frame-A1.txt)、[B1](kagura-ui-logs/sdk-fastpath-frame-B1.txt)、
  [B2](kagura-ui-logs/sdk-fastpath-frame-B2.txt)、[A2](kagura-ui-logs/sdk-fastpath-frame-A2.txt)

## 評価と`fill_rects()`

- 1回あたりの固定費は約0.4 ms減った。frame全体の改善は、呼出し回数に比例して2〜8%である。
- 残る固定費は、UI側の`Renderer.fill_rect`→`FramebufferBackend.fill_rect`→SDKの呼出し段数と、Viper kernel本体である。
- `fill_rects()`（複数の矩形をまとめて1回で描くAPI）は、この計測の後に改めて判断する。
  - 現在の1回あたりの費用を前提にすると、focusで1 frameあたり約1〜1.5 msの削減と見積もる。未計測。
  - 呼出し回数が多いのは`glyph8`のほう（glyphcutで45回/frame）である。

## 実機へ反映するには

SDKはUF2のfrozen moduleである。この変更を実機で常に使うには、UF2を作り直して書き込む必要があり、それには許可が必要である。
