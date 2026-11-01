# KAGURA-UI検証記録 — 2026-11-01

**RP2040 / USB CDCで最小UIの主要受入試験に合格。**
main `45e490b`を基準に、専用ブランチ`feat/kagura-ui-phase1`で実装した。
既存driver/transport/RTL/ABIの処理は変更していない。
UARTキーボード、Pico 2系、1時間以上の連続運転は未検証。PRはレビュー用Draftとしている。

## 確認済み

| 試験 | 結果・範囲 |
| --- | --- |
| UI PC tests | [26件PASS](kagura-ui-logs/ui-tests.txt)。tree、layout、clip、表示/有効、focus、callback、overflow、重なり復元、日本語glyph golden、無更新の転送ゼロ、fault recovery、MemoryError時lease非取得、SDK ASCII高速経路、USBバイト入力、旧SDK混在/CAPS不足のI/O前拒否、console pause中断時の復帰、デモ3種 |
| 既存SDK・デモ | [279件PASS](kagura-ui-logs/regressions.txt)。driver 62、framebuffer 85、日本語34、link 15、sakura 32、shooter 28、showcase 10、starfall 9、tile1200 2、transport benchmark 2。UIと合計305件 |
| PIO | driver試験に公式v1.26の`rp2.py`を渡し、既存FPGAタイミングモデルと照合 |
| Viper | SDK UI画面と独立linear surface、bounds-checked PCエミュレーションの一致。さらにRP2040 native/Python/PCでGallery CRC一致 |
| 公式MicroPython v1.26.0 VM | ソース`4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`からunix standardを構築。VM改変なし。CPythonと同一の日本語/入力/再試行シナリオを実行 |
| ARM compilation | SDK/UI/既存・新デモ69モジュールを公式v1.26 mpy-cross、`-march=armv6m`でPASS |
| Pico firmware build | KAGURA_PICO、公式v1.26、Pico SDK 2.1.1、Arm GNU 14.2。UIを含む凍結manifestでリンク成功。[サイズログ](kagura-ui-logs/pico-build.txt)。実機へ書込みなし。Pico/Pico WはCIでもビルド確認 |
| 生成定義 | `tools/gen-registers.ps1 -Check` PASS。32 direct/23 EXT/10+3 audio/5 commands |
| C回帰 | 既存STARFALL hostの6 CTestがPASS。C header compile PASS。ca65は環境にないためSKIP |
| CI変更選択 | `tools/test-ci-changes.sh` PASS。UI runtime比較、UI tests、ARM対象、配布artifact、凍結manifestをCIへ追加 |
| 見た目 | PC描画と、Gallery/Monitor/Studioの実機HDMIキャプチャを確認。日本語字形と元のHDMI REPL復帰も確認 |

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
| widget無しの直接Label描画 | 121 / 160 / 172 | 58 / 82 / 88 | 274 | 8768 |
| 静止UI | 1 / 1 / 1 | 0 / 0 / 0 | 0 | 0 |
| Label数値変更 | 172 / 225 / 234 | 61 / 91 / 93 | 273 | 8736 |
| Button押下 | 860 / 958 / 1167 | 245 / 270 / 299 | 1085 | 34720 |
| focus枠移動 | 2649 / 2786 / 3036 | 1240 / 1302 / 1429 | 5760 | 184320 |
| Panel領域移動 | 881 / 952 / 1328 | 562 / 592 / 883 | 2540 | 81280 |
| ListView scroll | 1157 / 1393 / 1638 | 638 / 737 / 1085 | 3090 | 98880 |
| 画面切替 | 46848 / 88239 / 103228 | 32665 / 61684 / 71186 | 153600 | 4915200 |

synthetic Event生成から最初のinvalidateまで: Button 7/8/12 µs、focus 10/13/19 µs、
scroll 7/11/16 µs（各p50/p95/p99）。物理キーボードの遅延を含まない。
直接描画は毎回描画、UIは同一値set_textを省略するため、初回sampleの転送数も完全には同じでない。
これらを根拠にRP2040のfps目標を設定しない。

```text
python tools/measure-kagura-ui.py
```

## heap観測

[公式MicroPython unixログ](kagura-ui-logs/unix-heap.txt)。64×48のMockBackend、固定Label、
GC有効で1024更新×3 window。各window後の明示GC後は:

- mem_alloc: 79296 B
- mem_free: 1993536 B
- App/Mock surface構築前からの増分: 5280 B
- window 0→1→2のGC後正味heap増加: 0 B

これは64bit unix VMの小さなモック画面であり、RP2040の38400 B framebufferを含むUIの使用量ではない。
module import/font openは構築前測定より先に行う。
allocation回数、実際のGC回数は未取得。明示GC以外にもVMがGCし得る。
3072更新の短い観測であり、長時間安定性試験ではない。

## 初回の接続中断とSDK混在

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
その後ユーザーがUSBを再接続し、通常のHDMI REPL復帰を確認して以下の受入試験を実施した。
旧Kaguraと新Framebufferの混在は`_link`不足として検出されたため、現在のUIでは既知の混在を
graphics I/O前に拒否する。CAPS_RSCROLLのSDK依存も同様に事前検査する。

## RP2040実機の受入・性能

Raspberry Pi Pico / RP2040 125 MHz、MicroPython表示バージョン1.26.0、
QSPI 5 MHz・4 lanes、ABI 0.6、CAPS 0x5B、320×240、pattern count 1200。
既存firmware/bitstreamの全binary hashは未取得。
既存console/transportを保持し、現行Device/Video/Framebuffer/Viper/UIを**読み取り専用RAM VFS**へロードした。
試験用のSDK aliasとscreen.device参照は終了時に戻し、通常bootも再確認した。
既存SDK、boot.py、UF2、保存済みファイルへの上書きは行っていない。

| 受入項目 | 観測結果 |
| --- | --- |
| Gallery/日本語 | [HDMI画像](images/kagura-ui-gallery-hdmi.png)を確認。PC参照・実機Python・実機Viperのtile CRC32はすべて2036752175 |
| USB入力 | StdinInputへ実USB CDCからEnter/Tab/Shift+Tab/Enter/Escapeを送信。Count: 2、queue dropped 0、正常終了。UARTではなくUSBをユーザーが選択 |
| 画面切替 | 第二画面の日本語Label確認、BACKで元rootへ戻ることをassert |
| 静止 | stepがFalse、全24巡でdirty tiles / payload B / flush時間が0 |
| Studio/Monitor | [Studio](images/kagura-ui-studio-hdmi.png)、[Monitor](images/kagura-ui-monitor-hdmi.png)を確認。未取得GC回数はn/a |
| console復帰 | paused=False、attached=True、FPGA ERROR_CODE=0。[通常HDMI REPLの画像](images/kagura-ui-console-restored.png)も確認 |
| heap | App/Theme/Gallery tree: 3984 B、Framebuffer constructor: 40544 B（GC後差分）。font open/module import/RAM試験環境は除く。5376-step計測時のGalleryはRESET改良前で3968 B |

全測定ログ: [24巡の基準構成](kagura-ui-logs/rp2040-stability.txt)、
[既存transport.accelerate()適用](kagura-ui-logs/rp2040-accelerated.txt)。
既存transportはlegacy FIFO pump APIで、bulk `kagura.link`はNoneだった。
これを現行bulk linkの性能と混同しない。graphicsのViperは両構成で有効。

各32 samples。基準構成の最終window（cycle 23）の値:

| workload | frame µs p50 / p95 / p99 | flush µs p50 / p95 / p99 | dirty tiles / payload B（32回合計） |
| --- | --- | --- | --- |
| 静止 | 413 / 431 / 446 | 0 / 0 / 0 | 0 / 0 |
| Label数値変更 | 43037 / 65919 / 71553 | 21613 / 24123 / 47450 | 56 / 1792 |
| Button押下 | 124890 / 153030 / 154484 | 64058 / 91548 / 91552 | 324 / 10368 |
| focus移動 | 260108 / 281978 / 283314 | 194283 / 196354 / 197126 | 1344 / 43008 |
| Panel移動 | 95359 / 125873 / 125939 | 84594 / 112481 / 113042 | 640 / 20480 |
| ListView scroll | 104664 / 139393 / 143933 | 64670 / 92377 / 92645 | 738 / 23616 |
| 画面切替 | 172695 / 265999 / 266453 | 125418 / 151484 / 153375 | 38400 / 1228800 |

直接Label描画の基準は37394/63554/68782 µs、flushは21700/47510/47606 µs。
synthetic Event→最初のinvalidateはButton 6226/7694/7826 µs、focus 5450/8803/8960 µs、
scroll 4537/6491/6635 µs（scrollのみ30有効samples）。USBパケット到着以前の遅延は含まない。
ここでは入力adapterを止め、queueへsynthetic Eventを入れている。

legacy transport.accelerate()適用後のcycle 1では、Labelは34935/42607/49907 µs、
Buttonは93013/122531/124942 µs、focusは177619/211398/212205 µs。
payload数は同じ。静止中央値は378 µsだった。
初回Gallery stepは初期化込み1711124 µs、描画＋flushのみ1270244 µs。
未高速化構成はそれぞれ2111415 µs / 1474518 µs。
FrameBuffer constructorの確保時間はこれらに含まない。

初回測定で静止時のfocus tree再走査が約10.5 msかかっていたため、候補が変わったときだけ再検証するよう修正。
静止中央値を約0.4 msへ削減した。scopeはstep処理であり、runのsleep_ms(10)は含めない。
複数damage rectangle、font cache、dirty run gap統合、現行bulk linkでの測定はPhase 2の候補。

24巡×7 workload×32回 = **5376 step**を完走。
各巡のGC後freeは63120 Bで一定。開始63680 B→終了63696 B（freeが16 B増加）だった。
ホストログ作成06:47:43 UTC→最終書込06:59:33 UTC（setup/teardownを含むファイル時刻）。
benchmark区間だけの経過時間は別計測していない。
allocation回数/自動GC回数は未取得であり、allocation-freeとは主張しない。
1時間以上の安定性試験、実USB HID、UARTキーボード、Pico 2/2 Wは未実施。

## 再現・追加受入の手順

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

今回のRAM試験は`tools/kagura-ui-device.py`と`tests/ui_ramfs.py`で再現する。
mpremote 1.29.0を使用した。先に公式v1.26 mpy-crossでSDK/UI/デモを`build/ui-live`へコンパイルする。
PicoのUSB serialを照合し、他機器は操作しない。

Linux/WSLでリポジトリrootから（mpy-crossの構築は既存SDK手順を使用）:

```sh
cross=build/micropython-src/mpy-cross/build/mpy-cross
mkdir -p build/ui-live/kagura/ui
for src in software/micropython/kagura/*.py software/micropython/kagura/ui/*.py; do
    out=build/ui-live/${src#software/micropython/}
    "$cross" -march=armv6m -o "${out%.py}.mpy" "$src"
done
for src in software/micropython/examples/ui_*.py; do
    "$cross" -march=armv6m -o "build/ui-live/$(basename "$src" .py).mpy" "$src"
done
```

```text
python tools/kagura-ui-device.py --port COM7 --expected-serial E663A837CB73512D --bench --cycles 24 --hold-seconds 0
python tools/kagura-ui-device.py --port COM7 --expected-serial E663A837CB73512D --accelerate --interactive
```

interactiveはUSB GUIを実行したままCOMポートを解放する。
別のUSB端末、または`mpremote connect COM7 resume repl`で接続して操作する。
EscapeでGUI終了、必要ならCtrl+Bでraw REPLから通常REPLへ戻る。
試験モジュールはRAMだけにあり、再起動すれば既存環境へ戻る。
長時間試験・標準配置の追加確認を残すためPRはDraft。Phase 3の保存・編集機能には進んでいない。
