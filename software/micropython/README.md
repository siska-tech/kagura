# MicroPython host driver / UART keyboard / HDMI REPL

KAGURA-9 ABI **0.5**向けのRP2040用ドライバ。Pico/Pico Wから既存と同じ配線でSPI/QSPIを使い、起動時にKAGURAを検出するとHDMIへREPL・`print()`・例外を表示する。入力はUART0（GP1 RX）、115200bps・8N1、3.3V TTL。USB REPLも利用できる。

**検証範囲（2026-10-29）**: PC上のABI/端末/通信モック・速度選択・電源投入時の待機等56テストと、MicroPython公式PIOアセンブラ＋既存FPGAタイミングモデルに合格。MicroPython v1.26.0・Pico SDK 2.1.1・Arm GNU 14.2.rel1でPico/Pico W両方のドライバ組込みUF2をビルドし、UF2ブロック構造とRP2040 family IDを確認済み。GitHub ActionsのCIも合格。実機では公式v1.26.0 UF2へ`kagura/`を追加した構成で、SPI/QSPIの1〜5MHz、480p/720p、HDMIコンソール、描画・音源・PCM、異常系を確認した（[実機の受入結果](#実機の受入結果)）。UART入力は内部ループバックでの確認で、GP1への実配線は未確認。

## 導入（通常のMicroPythonへの追加）

1. FPGAへ`spi`/`spipsram`、または`qspi`/`qspipsram`のABI 0.5 bitstreamを書き込む。720版も対応。
2. Pico/Pico Wには公式MicroPython **v1.26.0**を使う。標準のRP2ビルドでは`os.dupterm`と`os.dupterm_notify`が有効で、通常のUF2へモジュールを追加してドライバ・UART入力・HDMI REPLを利用できる。専用UF2への書換えは不要。
3. `kagura/`をPicoの`/lib/kagura/`へコピーする。自動コンソールを使う場合は`examples/boot.py`も`/boot.py`へコピーし、既存のboot.pyがあれば起動処理を組み込む。boot.pyの`mode`をbitstreamと一致させる。SCKは自動で選ぶ（[通信速度](#通信速度)）。ドライバだけを手動で使う場合はboot.pyの変更は不要。
4. UART送信元のTXをPico GP1（物理pin 2）、GNDを共通GNDへ接続する。GP0（pin 1）はUART TXとして予約するが、初期版はUARTへ出力しない。KAGURAの配線・電源は[Pico資料](../pico/README.md#配線)を参照。
5. リセット後、HDMIに起動メッセージと`>>>`が出る。UARTから`print(1 + 1)`とEnterを送る。入力のローカルエコーはOFFにする。

mpremoteを使う場合のコピー例（`software/micropython`で実行）:

```sh
mpremote connect COM5 fs mkdir :lib
mpremote connect COM5 fs cp -r kagura :lib/
mpremote connect COM5 fs cp examples/boot.py :boot.py
mpremote connect COM5 reset
```

`lib`が既にあればmkdirは不要。初期化前のログはUSBにだけ出る。FPGAは電源投入から約170msかけて内蔵Flashからbitstreamを読み、その間は全ピンがpull-upでhighになる（READYもhighに見える）。PicoはFPGAより先に（約70msで）boot.pyへ達するので、ドライバはREADY=highかつBUSY=lowになるまで待ってからIDを読む。起動時の待ちは最大2秒（`start(ready_timeout_us=...)`で変更可能）。KAGURAが未接続・ABI不一致ならHDMIを有効にせず、UART入力＋USB出力でREPLを利用できる。検出は起動時の1回で、ホットプラグ検出は行わない。

他のバージョンや独自ビルドでは、REPLで次を実行してコンソール用APIの有無を確認する。両方`True`ならコンソールを接続できる。ドライバ単体はこれらのAPIに依存しない。公式v1.26.0（RPI_PICO-20250809-v1.26.0.uf2）では両方`True`で、後付け構成での自動検出・HDMI表示を実機で確認した。

```python
import os
print(hasattr(os, "dupterm"), hasattr(os, "dupterm_notify"))
```

## 任意: ドライバ組込み済みUF2のビルド

対象ソースはMicroPython **v1.26.0 / 4ce2dd2cdab6e57f3982fc899f15a2103d71b0be**、SDKはそのsubmoduleの**Pico SDK 2.1.1**。専用ボード設定はドライバをfrozen moduleとして組み込み、USB CDCと標準の`os.dupterm`・`os.dupterm_notify`を維持する。Pythonモジュールをあらかじめ同梱したい場合の配布方法であり、通常版への追加にこのビルドは必要ない。

Linux/WSLでArm GNU Toolchain・CMake・make・Pythonを用意して実行する。`KAGURA_ROOT`はこのリポジトリの絶対パス:

```sh
git clone --depth 1 --branch v1.26.0 https://github.com/micropython/micropython.git
cd micropython
make -C ports/rp2 BOARD=KAGURA_PICO \
  BOARD_DIR="$KAGURA_ROOT/software/micropython/boards/KAGURA_PICO" submodules
make -C mpy-cross -j4
make -C ports/rp2 BOARD=KAGURA_PICO \
  BOARD_DIR="$KAGURA_ROOT/software/micropython/boards/KAGURA_PICO" -j4
```

`ports/rp2/build-KAGURA_PICO/firmware.uf2`をBOOTSELで書き込む。Pico WはBOARDとBOARD_DIR末尾を`KAGURA_PICO_W`へ変更する。UF2への書換えは既存のPico用Cホストfirmwareを置き換える。`kagura/`は組込み済みなので、自動コンソール用のboot.pyだけを上の手順で配置する。

参照: [MicroPython dupterm](https://docs.micropython.org/en/v1.26.0/library/os.html#os.dupterm)、[RP2 PIO](https://docs.micropython.org/en/v1.26.0/library/rp2.StateMachine.html)。

## コンソール操作

REPLで`kagura_console`が起動中のコンソール。`kagura_console.screen.device`がドライバ。

```python
dev = kagura_console.screen.device
print(dev.abi, dev.caps, dev.height)
```

- ASCII 8×8、40桁×30行（480p）/22行（720p）。下端4pxは720pで未使用。
- 改行・折返し・スクロール・BS/DEL・タブ、CSIのカーソル移動と行/画面消去に対応。ANSI色指定は無視。日本語などASCII外のUTF-8は1文字を`?`で表示。
- Enter、矢印、Backspace、Ctrl-C、Ctrl-Dの入力byteをMicroPython本来のREPLへ渡す。入力装置は改行にCR、編集キーにはVT100形式を送る。
- 20msのsoft timerがUARTを通知し、実行中のPythonプログラムにもCtrl-Cを届ける。USBからのCtrl-Cが表示更新やコンソールの処理中に起きた場合も、入力byteとして戻してプログラム側で中断させる。割込み禁止区間やネイティブ処理中の応答はMicroPythonの制約を受ける。
- 改行はSCROLL_Yのハードウェアスクロールで行い、新しい行だけを書く。カーソルとスクロールは1回のCOMMITでそろえて反映し、フレーム待ちはしない。16byte以上の同じregisterへの書込み（VRAM_WRITEなど）はDMAでPIOへ送る。
- HDMI出力は8192byteの固定リングバッファ。表示が追いつかない大量出力は超過分を破棄し、`kagura_console.dropped`へ累積する。全ログが必要ならUSBで取得する。
- 表示中に通信エラーが出た場合はHDMIの更新を止め、`kagura_console.last_error`へ保存する。UART入力通知は継続する。

アプリ描画へ切り替える場合:

```python
kagura_console.pause()
try:
    # Video(dev)などで描画・COMMITする
    pass
finally:
    kagura_console.resume()
```

`resume()`はフォント・背景map・palette 0/1・OAM・scrollをコンソール用に再初期化する。アプリの画面は再構築が必要。`detach()`は以前のdupterm streamへ戻す。`close()`はUART/PIOも解放する。既に別のstreamをdupterm slot 0へ接続している場合、attach中はそれを置き換える。

## ドライバAPI

```python
from kagura import connect
from kagura.video import Video
from kagura.audio import Audio

dev = connect(mode="spi", sm_id=0)  # SCKは5→2.5→1MHzから自動選択
dev.write_memory(0, bytes(32))
dev.fill(0x8000, 4096, 0)
dev.fence()
video = Video(dev)
video.palette(1, 0xFFF)
video.sprite(0, 100, 80, tile=0)
dev.commit()
audio = Audio(dev)
audio.tone(0, 440)
dev.audio_commit()
# audio.stop(0); dev.audio_commit()
# dev.deinit()
```

起動コンソールがある場合は`connect()`で同じSMを再取得せず、その`device`を使う。

| API | 内容 |
|---|---|
| `read_reg` / `write_reg` | 直接レジスタ |
| `ext_read/write` / `audio_read/write` | INDEX/DATAの一組を保護して操作 |
| `write_memory` / `read_memory_into` | VRAM・CAPS対応PSRAM。読出しは1byteずつREAD_REQUEST |
| `fill` / `copy` / `fence` | queue順序付き操作。書込み・FILL・COPYの完了確認はfence |
| `commit` / `audio_commit` | 反映完了まで待機 |
| `Video.palette/tile/map_entry/sprite/scroll/raster_scroll` | 映像データの設定。反映は呼出し側でcommit |
| `Audio.tone/noise/wave/stop` | PSG/wave設定。反映はaudio_commit |
| `Audio.prepare_pcm/play_pcm/pcm_status` | PSRAM上のsigned 8bit/48kHz PCM。prepare前にuploadする |

waveのbankはAUDIO_COMMITごとに交換される。初期波形は`wave()`→`audio_commit()`を2回行い、両bankをそろえる。PCM再生中/準備済みのsample領域へ書き込まない。

全待機はtimeout付き。通信例外時はCSをhighにし、PIOを初期化してQSPIを解放する。途中までの書込みや副作用付きreadは取り消せず、**自動再送しない**。`TransferTimeout.completed`は失敗した内部転送での保守的な完了byte数であり、API全体の書込み済みbyte数ではない。失敗後はエラー・reset状態を確認してアプリ側で復旧する。

1つのdeviceを1つの実行主体が所有する。consoleのsoft timerは`device.busy`を確認する。独自IRQ・別スレッドからの通信は非対応。PIO SMは指定番号を専有するため、他のPIO利用者とも割当てを調整する。実行中に`machine.freq()`を変更するとSCKが変わるので、変更前にdeinitし再接続する。

### 通信速度

`connect()`と`start()`は既定（`baudrate=None`）でSCKを5MHz→2.5MHz→1MHzの順に試し、最初に合格した速度を使う。各速度でprobe（ID・ABI）に続けて`check_link()`を行う。IDブロックの読出しと、LENGTH_L〜FENCE_TAG（FILL・COPY・FENCEが毎回書き直すので状態を変えない）への4byteパターンの書込み・読戻しを8回照合し、最後にERROR_CODE=0を確認する。所要時間は約40ms。READY=high・BUSY=lowにならない場合（未接続、FPGA未構成）は速度に関係しないので、低速では再試行せずに失敗する。`machine.freq()`がSCKの12倍に満たない速度は飛ばす。

選ばれた速度は`device.transport.baudrate`で分かり、起動コンソールのメッセージにも`(QSPI 5MHz)`のように出る。`baudrate=`に数値を渡すとその速度だけを使い、照合とfallbackは行わない。照合は接続時の1回だけで、合格した速度で運用中にエラーが出る配線では、低い速度を明示する。

失敗した速度での転送は、ヘッダのbit化けで別のレジスタへの書込みになり得る。各速度の照合の最初にERROR_CODEはclearするが、それ以外のレジスタは起動時の初期化（コンソールは`initialize()`）で設定し直す前提とする。

## 日本語表示（kagura_ja）

アプリ画面の背景mapへ、[美咲ゴシック](fonts/README.md)で8×8ドットの日本語を描く独立モジュール。REPL・コンソールの日本語化、日本語入力、漢字変換は含まない。通常のMicroPythonへファイルを追加するだけで使え、SDや専用UF2は不要。

**検証範囲（2026-10-29）**: PC上で変換ツール・フォントファイル・描画のモックテスト20件（`MISAKI_ZIP`指定時の再生成一致を含む）とmpy-crossのbytecodeコンパイルに合格。実機（公式v1.26.0 UF2、QSPI 5MHz、720p）で字形・配置・速度・メモリ消費とメニュー例を確認した（[実機の受入結果](#実機の受入結果)）。

### 導入

`kagura/`（上記）に加えて、`kagura_ja/`を`/lib/kagura_ja/`、`fonts/misaki8.kfnt`を`/fonts/misaki8.kfnt`へコピーする。フォントはFlash上のファイルとして約70KiBを使う。

```sh
mpremote connect COM5 fs cp -r kagura_ja :lib/
mpremote connect COM5 fs mkdir :fonts
mpremote connect COM5 fs cp fonts/misaki8.kfnt :fonts/misaki8.kfnt
mpremote connect COM5 fs cp examples/ja_menu.py :ja_menu.py
```

### 使い方

```python
from kagura_ja import Font, TextLayer

font = Font("/fonts/misaki8.kfnt")
text = TextLayer(dev, font, tile_base=128, tile_count=256,
                 map_x=0, map_y=0, width=40,
                 height=dev.height // 8, palette=0)

text.clear()
text.text("こんにちは、神楽！", col=0, row=0)
text.flush()
```

| API | 内容 |
|---|---|
| `Font(path)` / `Font.close()` | KJ8Fファイルを開く／閉じる。`with`も可。形式不正は`ValueError`、ファイルがなければ`OSError` |
| `Font.glyph(code)` | 8byteの字形、未収録なら`None`。ファイルを二分探索し、その1字だけ読む |
| `TextLayer(...)` | 描画先の設定だけで、通信はしない。`height`省略時は`dev.height // 8 - map_y` |
| `clear()` | 空白タイルを書き、矩形全体を空白にし、FENCE完了後に字形登録をリセットする |
| `text(s, col=0, row=0)` | `str`を描き、続きの位置`(col, row)`を返す。字形タイルとmapを転送する（完了待ちはしない） |
| `flush()` | FENCEで転送完了を待つ |
| `glyphs` | `clear()`以降に登録した字形タイル数 |

- 全文字を8×8の固定セルで扱う。ASCII・半角カナもセル1つを使い、字形はセル内で中央寄せされる。
- `\n`で次の行の先頭、`\r`で行頭へ戻る。右端を越える文字は次の行へ折り返す。矩形外（負の位置を含む）のセルは描かず、タイルも使わない。
- 未収録文字・BMP外の文字・その他の制御文字（タブを含む）は`?`で表示する。
- 画素値1が指定paletteの色1、画素値0は透明でBACKDROPの色が見える（[映像仕様](../../docs/video.md)）。palette RAMの設定とそのCOMMITは呼出し側で行う。表示・BGの有効化もアプリ側の責任。
- 最初の`text()`の前に`clear()`が必要。転送エラーが起きた後も、`clear()`をやり直すまで`text()`は`RuntimeError`になる。

### 資源制約

- タイル`tile_base`〜`tile_base + tile_count - 1`（既定128〜383）と背景mapの指定矩形はアプリが専有する。先頭1枚は空白用で、残り（既定255）が字形用。同じ文字は登録済みタイルを再利用し、空白（U+0020・U+3000）はタイルを使わない。
- 自動追い出しはしない。新しい字形が残りを超える`text()`は、何も書き込まずに`MemoryError`になる（既存の表示は変わらない）。画面を切り替える時に`clear()`で登録を空にする。
- RAMはmapの写し（`width × height × 2`byte、既定40×30で2400byte）と登録表（最大255項目のdict）を使う。フォント全体は読み込まない。
- 新しい字形1つにつきファイルを最大13回seek/readする（7171字の二分探索）。既出の字形は読まない。
- 実機（QSPI 5MHz）で、新しい字形1つにつき約1.8msのファイル検索がかかる。新しい字形255個を含む`text()`＋`flush()`は約0.97秒、登録済みの字形だけなら同じ255セルで約0.14秒（[実機の受入結果](#実機の受入結果)）。字形の多い画面は切替え前に描いておく。

### コンソールとの切替え

起動コンソールのタイル0〜127・map全体・palette 0・sprite 0（カーソル）と重なる。`kagura_console.pause()`で止めてから描画し、終わったら`resume()`する。`resume()`がmap全体を初期化するので、日本語画面に戻る時は`clear()`から描き直す。pause中もsprite 0のカーソルは残るため、隠す場合は`Video(dev).sprite(0, enable=False)`の後にCOMMITする。

`examples/ja_menu.py`は、コンソールを止めてpalette 1で日本語メニューを表示し、↑↓（またはw/s）とEnterで項目を選ぶサンプル。

```python
import ja_menu
print(ja_menu.run(kagura_console))
```

## 検証

PCで:

```sh
powershell -NoProfile -File tools/gen-registers.ps1 -Check
python -I software/micropython/tests/test_driver.py
python -I software/micropython/tests/test_driver.py \
  --rp2 path/to/micropython/ports/rp2/modules/rp2.py
MISAKI_ZIP=path/to/misaki_bdf_2021-05-05.zip \
  python -I software/micropython/tests/test_kagura_ja.py
```

2番目は通信/ABI/端末テスト、3番目は公式PIOアセンブラの出力で既存`software/pico/tests/test_pio_timing.py`も実行する。4番目は`kagura_ja`と変換ツールのテストで、`MISAKI_ZIP`を省くとフォント再生成の一致検査だけを飛ばす。タイミングモデルの10MHz試験合格は実機の10MHz対応を意味しない。ドライバの設定上限は5MHz。

実機の受入手順:

1. 1MHzでprobe、32KiB全域照合、FILL/FENCE。`examples/diag.py`をPicoへコピーし、コンソールをpauseして`diag.run(dev)`を実行する。パターンRAMを上書きする。
2. SPI/QSPIの各bitstreamで`baudrate=`を指定して1→2.5→5MHzを試し、自動選択の結果も確認する。速度・ERROR_CODE・LED2（late）・読戻しを記録。
3. UARTで式評価・行編集・複数行入力・例外・長文スクロールを確認。`while True: pass`をCtrl-Cで中断し、Ctrl-Dで再起動後もHDMIへpromptが戻ることを確認。
4. FPGA未接続、READY固定low、BUSY固定high、転送中Ctrl-C、FPGA resetからUSB REPLへ戻れることを確認。
5. 描画へ切替→console復帰、480p/720p、PSG/wave/PCMの動作を確認。実際のFPSと転送速度を記録する。
6. `ja_menu.run(kagura_console)`で、かな・漢字・半角の字形と中央寄せ、配置、カーソル移動、console復帰を確認。新しい字形を多く含む画面の描画時間と、`gc.mem_free()`の変化を記録する。

### 実機の受入結果

2026-10-29、Pico（公式MicroPython v1.26.0 UF2＋`/lib/kagura/`、frozenなし）、Tang Nano 9K。bitstreamは`8aee28e`から作った[標準版release](https://github.com/siska-tech/kagura/releases/tag/bitstreams-2026-10-27)の`spi`・`spipsram`・`qspipsram`・`qspipsram720`をSRAMへ書いた。

| 項目 | 結果 |
|---|---|
| 自動検出 | 4構成ともboot.pyでHDMIコンソールが起動。ABI 0.5、CAPS 0x53/0x5B/0x5B/0x7B、480pは30行・720pは22行 |
| 速度の自動選択 | `spipsram`・`qspipsram720`とも5MHzを選択し、`connect()`は約110ms（照合約40ms）。SM clockを上げた試験では、照合がSCK 7.5MHzまで10回とも合格し、10MHzで10回とも失敗（bit化けを検出）。HDMIコンソールの100行出力は1MHzで4.15秒、5MHzで4.21秒（Python律速で差なし） |
| 32KiB書込み＋全域読戻し | SPI 5MHz（`spi`・`spipsram`）とQSPI 1/2.5/5MHzで不一致0。32KiB書込み＋FENCEは1MHzで0.5〜0.7秒、5MHzで0.45〜0.49秒。読出しは1byteごとにREAD_REQUESTを使うため約158byte/秒で、SCKによらない |
| FILL/FENCE・BUSY | 2KiB×16のFILL＋FENCE、FILL 30000byte＋2KiB書込みを200回FENCEなしで連続投入し、内容一致・ERROR_CODE=0（SPI/QSPIの1/2.5/5MHz） |
| PSRAM・COPY | 4KiBの書込み→COPY→読戻しが一致（`spipsram` 2.5/5MHz、`qspipsram720` 1/2.5/5MHz） |
| UART入力 | UART0の内部ループバック（UARTCR.LBE）でGP1以降の経路へ打鍵列を入れ、式評価、左移動と挿入、BS、履歴、複数行、例外、30行のスクロール、`while True: pass`のCtrl-C、Ctrl-Dの再起動後のprompt復帰を確認。HDMIのmapもUSBと同じ内容。GP1への実配線は未確認 |
| 描画⇔コンソール | `pause()`→描画→`resume()`で`spi`・`qspipsram`・`qspipsram720`ともコンソールへ戻り、mapの読戻しで全行を確認。`qspipsram720`では描画とコンソールの切替を目視でも確認 |
| フレーム更新 | COMMITのみ約60fps、scroll＋COMMIT 58〜59fps、64 spriteのOAM 512byte書込み＋COMMIT 約29fps、`Video.sprite`8回＋COMMIT 約15fps（QSPI/SPIとも1MHz、Pythonの処理で律速） |
| 音源・PCM | PSG 3ch＋noise＋wave 2chでAUDIO_STATUS=0（`spi`・`spipsram`・`qspipsram720`）。PCM 48000byte（1秒）のuploadはSPI 1.0秒・QSPI 0.74秒、one-shotは約1020msでDONE、loopは2.5秒後もACTIVE（`spipsram`・`qspipsram720`）。`qspipsram720`では聴感でも正常で、最後の書込み以降LED2（`late`）は消灯 |
| 転送中断 | 読出し・DMA書込み・FILLの実行中にUSBからCtrl-Cを21回送り（QSPI 18回・SPI 3回、5MHz）、毎回CS high・ERROR_CODE=0で次の操作が成功。修正前は、READ_READY待ちでの中断後の最初の読出しがREAD_COLLISION（0x08）になっていた |
| FPGA reset | HDMIコンソールの表示中にFPGAを再構成すると`last_error`に`TransferTimeout`が入り、USB REPLは継続。`resume()`で復帰 |
| 未接続・READY・BUSY | FPGA未構成（SRAM Erase）で起動するとUART＋USB REPLへフォールバック（この試験時は`KAGURA ID mismatch`、下記の修正後は2秒で`KAGURA timeout: READY`）。BUSY固定high（未構成時のpull-up）ではqueue対象の書込みが約100msで`TransferTimeout`。READY固定low（未配線GPIOをREADYに指定）では2秒で`KAGURA timeout: READY` |
| 日本語表示（kagura_ja） | 2026-10-29、QSPI 5MHz・720p（40×22セル）。かな（濁点・半濁点・小書き）、漢字、全角記号、ASCII・半角カナの中央寄せ、未収録文字の`?`、折返し、右端と下端の切捨てをHDMIで目視確認。map 1760byte全体と字形タイル32個の読戻しが一致。`Font()` 3.4ms・RAM 1.2KiB、`glyph()`平均1.8ms、`TextLayer`のRAM 2.0KiB、字形255個の登録で+2.3KiB。`clear()` 186ms、新しい字形255個の`text()`＋`flush()` 0.97秒、登録済み255セルの再描画0.14秒、256個目で`MemoryError`。`ja_menu.run(kagura_console)`はUSBから送った↑↓・Enterで選択でき、戻り値は選んだ項目、終了後にコンソールへ復帰し、呼出し前後の`gc.mem_free()`の差は128byte。開始から最初の描画まで約0.59秒、終了時の`resume()`は約1.1秒 |

#### 電源投入時の検出失敗（修正済み）

以前の版では、PicoとFPGAに同時に電源が入るとHDMIコンソールが起動しないことがあった（Ctrl-Dで再試行すると起動）。READYの待ち時間不足ではなく、構成中のFPGAを準備完了と誤認していた。

- boot.pyの先頭で、ピンを駆動せずにREADY/BUSY/IRQを記録した。両基板の電源を同時に入れた3回とも、boot.pyの開始はPicoのリセットから65〜76msで、そのときFPGAは構成中（READY=BUSY=high）だった。真のREADY（READY=high・BUSY=low）はさらに36〜90ms後。Tang Nanoだけを入れ直した場合、電源投入からREADYまで約188ms（うち構成約171ms）。
- 以前のprobeはREADYだけを見ていたため、構成中にIDを読んで`KAGURA ID mismatch`になり得た。`/lib`の.pyではimportとcompileの時間で間に合う場合が多く（5回とも成功）、以前に起きたfrozen moduleの専用UF2ではimportが速いため起きやすかったと考えられる（専用UF2での再試験は未実施）。
- PCからFPGAを再構成している間に`connect()`を呼ぶと確実に再現した（修正前2/2回`ID mismatch`、修正後3/3回が構成完了を待って5MHzで接続）。
- Picoが/CSをhighに駆動したままTang Nanoの電源だけを切ると、信号ピン経由で電源が回り込み、再投入後も構成の失敗と再試行（約172ms周期）が続いてREADYまで約6.5秒かかった。ピンを入力にした場合は1回で構成した。電源はPicoと同時か先にFPGAへ入れ、Pico動作中にFPGAだけを切らない。

レジスタ定数`kagura/regs.py`は`spec/registers.json`から生成する。手動編集しない。
