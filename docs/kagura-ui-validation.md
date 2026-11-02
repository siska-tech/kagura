# KAGURA-UI検証記録 — 2026-11-01

**RP2040 / USB CDCで最小UIの主要受入試験に合格。**
main `45e490b`を基準に、専用ブランチ`feat/kagura-ui-phase1`で実装した。
既存driver/transport/RTL/ABIの処理は変更していない。
UARTキーボード、Pico 2系は未検証。通常配置の追加受入は下記に記録。
1時間のbitmap UI連続試験は、その後の[Phase 2記録](kagura-ui-phase2.md)を参照。

## 確認済み

| 試験 | 結果・範囲 |
| --- | --- |
| UI PC tests | [26件PASS](kagura-ui-logs/ui-tests.txt)。tree、layout、clip、表示/有効、focus、callback、overflow、重なり復元、日本語glyph golden、無更新の転送ゼロ、fault recovery、MemoryError時lease非取得、SDK ASCII高速経路、USBバイト入力、旧SDK混在/CAPS不足のI/O前拒否、console pause中断時の復帰、デモ3種 |
| 既存SDK・デモ | [279件PASS](kagura-ui-logs/regressions.txt)。driver 62、framebuffer 85、日本語34、link 15、sakura 32、shooter 28、showcase 10、starfall 9、tile1200 2、transport benchmark 2。UIと合計305件 |
| PIO | driver試験に公式v1.26の`rp2.py`を渡し、既存FPGAタイミングモデルと照合 |
| Viper | SDK UI画面と独立linear surface、bounds-checked PCエミュレーションの一致。さらにRP2040 native/Python/PCでGallery CRC一致 |
| 公式MicroPython v1.26.0 VM | ソース`4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`からunix standardを構築。VM改変なし。CPythonと同一の日本語/入力/再試行シナリオを実行 |
| ARM compilation | SDK/UI/既存・新デモ69モジュールを公式v1.26 mpy-cross、`-march=armv6m`でPASS |
| Pico firmware build | KAGURA_PICO、公式v1.26、Pico SDK 2.1.1、Arm GNU 14.2。UIを含む凍結manifestでリンク成功。[初期サイズログ](kagura-ui-logs/pico-build.txt)。後述の通常配置試験で実機へ導入。Pico WはCIのビルド対象 |
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

COM7の既存Pico（USB serialは照合済み。値は記録しない）を読み取り確認:

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

**この初回試行ではFlash/UF2/boot.py/既存SDK/保存済みファイルは書き換えていない。**
その後ユーザーがUSBを再接続し、通常のHDMI REPL復帰を確認して以下の受入試験を実施した。
旧Kaguraと新Framebufferの混在は`_link`不足として検出されたため、現在のUIでは既知の混在を
graphics I/O前に拒否する。CAPS_RSCROLLのSDK依存も同様に事前検査する。

## RP2040実機の受入・性能（先行RAM試験）

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
   UIを含む新manifestのfirmwareをデータ保全のうえ導入する。下記の通常配置試験ではこの方法を使用。
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
python tools/kagura-ui-device.py --port <PORT> --expected-serial <USB_SERIAL> --bench --cycles 24 --hold-seconds 0
python tools/kagura-ui-device.py --port <PORT> --expected-serial <USB_SERIAL> --accelerate --interactive
```

interactiveはUSB GUIを実行したままCOMポートを解放する。
別のUSB端末、または`mpremote connect COM7 resume repl`で接続して操作する。
EscapeでGUI終了、必要ならCtrl+Bでraw REPLから通常REPLへ戻る。
試験モジュールはRAMだけにあり、再起動すれば既存環境へ戻る。
このRAM試験に続き、下記の通常配置試験を実施した。Phase 3の保存・編集機能には進んでいない。

## 通常配置の追加受入（2026-11-01）

同じRP2040へ、公式MicroPython v1.26.0、Pico SDK 2.1.1、現行manifestのSDK/UIを
凍結したUF2を導入。`kagura.__path__ == '.frozen/kagura'`、
`kagura.ui.__path__ == '.frozen/kagura/ui'`。通常のUSB raw REPLでアプリのソースを実行した。
RAM VFS、SDK alias、package path変更、Framebuffer用の事前メモリ予約は使っていない。
日本語fontは既存`/fonts/misaki8.kfnt`を使用。

導入前に全2 MiBのFlashを取得し、実機SHA256と照合。
バックアップはローカル`build/ui-normal-install/backup-20261101T103750Z/`に保持した。
全Flash SHA256は`8e0644d88b638829decb9e6819dbf7d242c54e4c174ac9540c9ec65c181be73a`。
最初のUF2更新直後は保存領域1408 KiBのSHA256が完全一致した。
通常起動へ移行するため、`/boot.py`だけを`kagura1200.console`から`kagura.console`へ変更し、
容量不足を避けるため説明コメント1行を削除した（198 B、改行LF）。保存済みの旧SDK等は削除していない。

### 凍結native配置で発見した問題と修正

最初の通常配置では塗りつぶしに縦筋が出た。凍結Viperの8×8色3の出力が
`03a03533...`となり、Gallery CRCは3228509582。Python backendでは2036752175となった。
ELF内のfill関数は`0x100349c6`で、生成native配列の属性は`aligned(2)`だった。
ThumbのPC相対literal読出しに必要な4バイト境界とのずれを確認した。

両KAGURAボードのCMakeに、生成後・コンパイル前の`align_frozen.py`を追加した。
native配列のalignment属性を4へ変更するだけで、公式VM、mpy-cross、SDK描画処理は変更しない。
補正後のfill関数は`0x100349c8`、出力は`33333333...`。
Galleryは**凍結Viper / Python / PCでCRC32 2036752175が一致**した。
`framebuffer_viper_cases.run_cases(fb,count=48)`でも162操作のbuffer/dirtyを逐次CRCへ含め、
Pythonと凍結nativeが一致した（rolling 1771536395、buffer 2635498818、dirty 206457449）。
これらはSDKのRAMロード試験だけでは検出できなかった配置依存の問題である。

修正UF2 SHA256は`9a013426be5b699a667e626701ad2fa00216dd3b1010cf45d19077468eb21b58`。
1665 payload blocksの書込み範囲は`0x10000000 <= address < 0x10068100`。
保存領域開始`0x100a0000`へ書き込むpayloadがないことを全ブロック検証した。
ビルドサイズはtext 425996 B、data 0 B、bss 5128 B。

### 通常配置の結果

[HDMI Gallery画像](images/kagura-ui-normal-gallery.png)、
[USB操作とbenchmarkログ](kagura-ui-logs/normal-install.txt)、
[凍結kernel比較](kagura-ui-logs/frozen-kernels.txt)。
USB Enter→Tab→Shift+Tab→EnterでCount 2、drop 0。
Second screen→BACK→Escapeも操作し、終了後はconsole paused=False、attached=True、
FPGA ERROR_CODE=0。`machine.reset()`によるハードリセット後も凍結UI、現行console、
bulk Link、acceleration=True、last_error=Noneを確認した。
その後98ファイルを再列挙してSHA256とサイズを照合し、変更は既知の`/boot.py`だけ、
残り97ファイルとファイル一覧は不変だった。

通常配置では新しいbulk Linkを使用。初回Gallery stepは約1.208 s（初期化込み）、
最後の描画flushは333 tiles / 10656 payload B、約17 ms。
Gallery起動後GCでfree 143488 B。App構築前からのheap差分5328 Bは
App/Theme/treeと、ホストから通常実行したGallery関数定義を含む。font/module読込みは含まない。

各32 samples、2巡、計448 stepの通常配置benchmark（cycle 0）:

| workload | frame µs p50 / p95 / p99 | flush µs p50 / p95 / p99 | 合計dirty tiles / payload B |
| --- | --- | --- | --- |
| 静止 | 437 / 448 / 459 | 0 / 0 / 0 | 0 / 0 |
| Label変更 | 25271 / 28000 / 29116 | 1862 / 1900 / 2026 | 53 / 1696 |
| Button | 57844 / 81092 / 88144 | 2723 / 2757 / 2789 | 287 / 9184 |
| focus | 81770 / 97604 / 99276 | 5202 / 5293 / 5393 | 1440 / 46080 |
| Panel移動 | 12885 / 15452 / 17669 | 3141 / 3273 / 3304 | 620 / 19840 |
| List scroll | 44652 / 51897 / 61887 | 3135 / 3170 / 3231 | 786 / 25152 |
| 画面切替 | 64245 / 149964 / 151348 | 29804 / 29885 / 29886 | 38400 / 1228800 |

各巡GC後のfreeは96000 Bで一定。開始137328 Bは最初のstep前なので、
遅延確保されたFramebuffer等の常駐分を含まず、終了96560 Bとの差をheap leakと扱わない。
allocation回数とGC回数は未取得。短時間試験のため長時間安定性の証明には使わない。
UI 26件、配置補正1件、Framebuffer既存85件を再実行しPASS。
Framebufferの最初の再実行はWindows sandbox TEMP権限で4エラーとなったため、
workspace内TEMPを指定して再実行した。描画のassert失敗ではない。

通常配置の阻害要因は解消した。このPhase 1記録以降、PR #50はユーザーにより
main `41669a2`へmergeされた。追加開発は[Phase 2記録](kagura-ui-phase2.md)を参照。

Phase 1時点では長時間試験、UART/HID、Pico 2/2 W、物理電源断による再投入は未実施だった。
