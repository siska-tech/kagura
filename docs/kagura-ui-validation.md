# KAGURA-UI検証記録 — 2026-11-01

**Phase 1は実機受入待ち。完了扱いにしない。**
main `45e490b`を基準に、専用ブランチ`feat/kagura-ui-phase1`で実装した。
既存driver/transport/RTL/ABIの処理は変更していない。

## 確認済み

| 試験 | 結果・範囲 |
| --- | --- |
| UI PC tests | [22件PASS](kagura-ui-logs/ui-tests.txt)。tree、layout、clip、表示/有効、focus、callback、overflow、重なり復元、日本語glyph golden、無更新の転送ゼロ、fault recovery、MemoryError時lease非取得、SDK ASCII高速経路、デモ3種 |
| 既存SDK・デモ | [279件PASS](kagura-ui-logs/regressions.txt)。driver 62、framebuffer 85、日本語34、link 15、sakura 32、shooter 28、showcase 10、starfall 9、tile1200 2、transport benchmark 2。UIと合計301件 |
| PIO | driver試験に公式v1.26の`rp2.py`を渡し、既存FPGAタイミングモデルと照合 |
| Viper | SDK UI画面と独立linear surfaceの一致、Viper kernelソースのbounds-checked PCエミュレーションとの一致。RP2040 native UI実行は未確認 |
| 公式MicroPython v1.26.0 VM | ソース`4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`からunix standardを構築。VM改変なし。CPythonと同一の日本語/入力/再試行シナリオを実行 |
| ARM compilation | SDK/UI/既存・新デモ69モジュールを公式v1.26 mpy-cross、`-march=armv6m`でPASS |
| Pico firmware build | KAGURA_PICO、公式v1.26、Pico SDK 2.1.1、Arm GNU 14.2。UIを含む凍結manifestでリンク成功。text 425308 B / data 0 / bss 5128 B。実機へ書込みなし |
| 生成定義 | `tools/gen-registers.ps1 -Check` PASS。32 direct/23 EXT/10+3 audio/5 commands |
| C回帰 | 既存STARFALL hostの6 CTestがPASS。C header compile PASS。ca65は環境にないためSKIP |
| CI変更選択 | `tools/test-ci-changes.sh` PASS。UI runtime比較、UI tests、ARM対象、配布artifact、凍結manifestをCIへ追加 |
| 見た目 | PC描画のGallery/Monitor/StudioをPNGで確認。実機HDMI画質を確認したものではない |

同一シナリオのCRC32:

| 画面状態 | CPython | 公式MicroPython v1.26 unix |
| --- | --- | --- |
| 初期表示 | 4231501191 | 4231501191 |
| 日本語変更＋Enter | 2117273149 | 2117273149 |
| flush例外→再試行 | 26039419 | 26039419 |

[CPythonログ](kagura-ui-logs/cpython-runtime.txt)、[MicroPythonログ](kagura-ui-logs/micropython-runtime.txt)。

## PCベースラインと計測

[計測ログ](kagura-ui-logs/pc-benchmark.txt)はCPython 3.14 / Windows / RegisterModel /
Python rasterの**PC測定**。FENCE/SPI/QSPIは模擬動作なので、flush時間をRP2040/FPGAの通信性能として使わない。
画面描画・転送量の挙動と、今後比較するベースラインを残す目的。
各128 samples、percentileはsort後の`floor((N-1)*p/100)`位置。

| workload | frame µs p50 / p95 / p99 | flush µs p50 / p95 / p99 | 合計dirty tiles | 合計pattern payload B |
| --- | --- | --- | --- | --- |
| widget無しの直接Label描画 | 152 / 199 / 237 | 74 / 105 / 107 | 274 | 8768 |
| 静止UI | 6 / 6 / 7 | 0 / 0 / 0 | 0 | 0 |
| Label数値変更 | 231 / 287 / 291 | 83 / 117 / 121 | 273 | 8736 |
| Button押下 | 1030 / 1201 / 1420 | 293 / 367 / 447 | 1085 | 34720 |
| focus枠移動 | 3203 / 3488 / 3679 | 1506 / 1695 / 1814 | 5760 | 184320 |
| Panel領域移動 | 1066 / 1165 / 1214 | 684 / 758 / 808 | 2540 | 81280 |
| ListView scroll | 1475 / 1572 / 1769 | 821 / 878 / 949 | 3090 | 98880 |
| 画面切替 | 56350 / 61728 / 64183 | 39682 / 42848 / 45542 | 153600 | 4915200 |

synthetic Event生成から最初のinvalidateまで: Button 11/16/21 µs、focus 15/22/30 µs、
scroll 11/16/21 µs（各p50/p95/p99）。物理キーボードの遅延を含まない。
直接描画は毎回描画、UIは同一値set_textを省略するため、初回sampleの転送数も完全には同じでない。
これらを根拠にRP2040のfps目標を設定しない。

```text
python tools/measure-kagura-ui.py
```

## heap観測

[公式MicroPython unixログ](kagura-ui-logs/unix-heap.txt)。64×48のMockBackend、固定Label、
GC有効で1024更新×3 window。各window後の明示GC後は:

- mem_alloc: 78304 B
- mem_free: 1994528 B
- App/Mock surface構築前からの増分: 5248 B
- window 0→1→2のGC後正味heap増加: 0 B

これは64bit unix VMの小さなモック画面であり、RP2040の38400 B framebufferを含むUIの使用量ではない。
module import/font openは構築前測定より先に行う。
allocation回数、実際のGC回数は未取得。明示GC以外にもVMがGCし得る。
3072更新の短い観測であり、長時間安定性試験ではない。

## 実機試験の経過と保留理由

COM7、USB serial `E663A837CB73512D`の既存Picoを読み取り確認:

```text
MicroPython 1.26.0 / KAGURA Raspberry Pi Pico with RP2040 / _build KAGURA_PICO
heap_free: 64080 B（UI import前、既存consoleあり）
ABI: (0, 6)
height: 240
/fonts/misaki8.kfnt: 71718 B
```

既存凍結`kagura`の`__path__`は`.frozen/kagura`なので、mountしたUIは最初
`ImportError: no module named 'kagura.ui'`になった。
一時的にpackage pathをmount先へ向けた試行では、`import ui_gallery`から戻らず、
`BEFORE` heap出力や`run()`には到達しなかった。
原因は未特定。UI画面の初期化成功・失敗を観測した結果ではない。

今回のmpremoteプロセスだけを停止したが、COM7はPermissionErrorのままだった。
特定したPico USB複合deviceだけの`pnputil /restart-device`はWindowsの
`Access is denied`で実行されなかった。ハブ全体や他のUSB deviceは操作していない。
これはOS権限の拒否であり、承認reviewerの拒否ではない。
ユーザーは外出中のため、USBの抜き差しは帰宅後となった。

**Flash/UF2/boot.py/既存SDK/保存済みファイルは一切書き換えていない。**
実機でのGallery表示、物理キー操作、日本語字形、console復帰、UIのheap/描画/転送時間、
長時間安定性、Pico 2/2 Wは未検証。

## 再開時の受入手順

1. PicoのUSBを抜き差しし、COM番号とUSB serialを再確認。通常のREPLとHDMI consoleを先に確認。
   同じ停止中mountの無条件再試行や、自動的なfirmware書換えは行わない。
2. 実機の既存ファイルを保全し、配布方法を決める。通常のfilesystem SDKなら`kagura/ui`を含む
   SDK一式を既存手順で配置する。古い凍結SDKでは追加packageの探索を別途検証するか、
   UIを含む新manifestのfirmwareをデータ保全のうえ導入する。今回作ったUF2は未書込み。
3. Fontを開き、App構築前後・start前後の`gc.mem_free()`を記録する。確保失敗時にconsoleが維持されることを確認。
4. `ui_gallery.run(console=kagura_console)`で日本語Label、Tab/Shift+Tab、上下左右、Enter、Escape、
   ボタン押下/解除、画面切替を確認。終了後HDMI REPLへ戻り`print('UI restored')`が表示されることを確認。
5. Monitor/Studio mockを操作する。長いcallbackの制約と、独立sprite/TextLayerとの同時使用不可を確認。
6. `ui_benchmark.make(device,font,console=console)`でAppとworkloadを作り、
   `baseline(app)`→`run(app,widgets,samples=128)`をtry/finally app.close内で実行。
   Viper有/無をそれぞれ測定し、同じ画素CRCを確認。実機固有のABI/CAPS、CPU/SCK、firmware/source hashを記録。
7. 長時間は`run(...,cycles=N)`で標本数固定のまま繰り返す。結果は逐次出力し、RAMへ全履歴を保存しない。
   GC後heap推移を確認。GC回数が取得できない場合はn/aを維持する。

実機受入完了までPRはDraft。Phase 3の保存・編集機能には進まない。
