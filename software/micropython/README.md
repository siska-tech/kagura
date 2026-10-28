# MicroPython host driver / UART keyboard / HDMI REPL

KAGURA-9 ABI **0.5**向けのRP2040用ドライバ。Pico/Pico Wから既存と同じ配線でSPI/QSPIを使い、起動時にKAGURAを検出するとHDMIへREPL・`print()`・例外を表示する。入力はUART0（GP1 RX）、115200bps・8N1、3.3V TTL。USB REPLも利用できる。

**検証範囲（2026-10-28）**: PC上のABI/端末/通信モック等46テストと、MicroPython公式PIOアセンブラ＋既存FPGAタイミングモデルに合格。MicroPython v1.26.0・Pico SDK 2.1.1・Arm GNU 14.2.rel1でPico/Pico W両方のドライバ組込みUF2をビルドし、UF2ブロック構造とRP2040 family IDを確認済み。CI定義も追加したが、GitHub上での実行は未確認。実機（Pico、QSPI 1MHz、PSRAM付き720p bitstream）ではHDMIコンソールの表示・スクロール・USBからのCtrl-C（約130msで中断）・Ctrl-Dを確認し、100行の出力がHDMIへ描き終わるまで約3.8秒だった。UART入力・SPI・480p・2.5MHz以上・描画/音源APIは実機未検証。C版の5MHz合格実績をこのドライバの実績とは扱わない。

## 導入（通常のMicroPythonへの追加）

1. FPGAへ`spi`/`spipsram`、または`qspi`/`qspipsram`のABI 0.5 bitstreamを書き込む。720版も対応。
2. Pico/Pico Wには公式MicroPython **v1.26.0**を使う。標準のRP2ビルドでは`os.dupterm`と`os.dupterm_notify`が有効で、通常のUF2へモジュールを追加してドライバ・UART入力・HDMI REPLを利用できる。専用UF2への書換えは不要。
3. `kagura/`をPicoの`/lib/kagura/`へコピーする。自動コンソールを使う場合は`examples/boot.py`も`/boot.py`へコピーし、既存のboot.pyがあれば起動処理を組み込む。boot.pyの`mode`をbitstreamと一致させる。SCK既定値は1MHz。ドライバだけを手動で使う場合はboot.pyの変更は不要。
4. UART送信元のTXをPico GP1（物理pin 2）、GNDを共通GNDへ接続する。GP0（pin 1）はUART TXとして予約するが、初期版はUARTへ出力しない。KAGURAの配線・電源は[Pico資料](../pico/README.md#配線)を参照。
5. リセット後、HDMIに起動メッセージと`>>>`が出る。UARTから`print(1 + 1)`とEnterを送る。入力のローカルエコーはOFFにする。

mpremoteを使う場合のコピー例（`software/micropython`で実行）:

```sh
mpremote connect COM5 fs mkdir :lib
mpremote connect COM5 fs cp -r kagura :lib/
mpremote connect COM5 fs cp examples/boot.py :boot.py
mpremote connect COM5 reset
```

`lib`が既にあればmkdirは不要。初期化前のログはUSBにだけ出る。同時に電源を入れる場合を考慮し、起動時はREADYを最大2秒待つ（`start(ready_timeout_us=...)`で変更可能）。KAGURAが未接続・ABI不一致ならHDMIを有効にせず、UART入力＋USB出力でREPLを利用できる。検出は起動時の1回で、ホットプラグ検出は行わない。

他のバージョンや独自ビルドでは、REPLで次を実行してコンソール用APIの有無を確認する。両方`True`ならコンソールを接続できる。ドライバ単体はこれらのAPIに依存しない。通常版への後付け構成も実機では未検証。

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

dev = connect(mode="spi", baudrate=1_000_000, sm_id=0)
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

## 検証

PCで:

```sh
powershell -NoProfile -File tools/gen-registers.ps1 -Check
python -I software/micropython/tests/test_driver.py
python -I software/micropython/tests/test_driver.py \
  --rp2 path/to/micropython/ports/rp2/modules/rp2.py
```

2番目は通信/ABI/端末テスト、3番目は公式PIOアセンブラの出力で既存`software/pico/tests/test_pio_timing.py`も実行する。タイミングモデルの10MHz試験合格は実機の10MHz対応を意味しない。ドライバの設定上限は5MHz。

実機の受入手順:

1. 1MHzでprobe、32KiB全域照合、FILL/FENCE。`examples/diag.py`をPicoへコピーし、コンソールをpauseして`diag.run(dev)`を実行する。パターンRAMを上書きする。
2. SPI/QSPIの各bitstreamで1→2.5→5MHzを試し、速度・ERROR_CODE・LED2（late）・読戻しを記録。
3. UARTで式評価・行編集・複数行入力・例外・長文スクロールを確認。`while True: pass`をCtrl-Cで中断し、Ctrl-Dで再起動後もHDMIへpromptが戻ることを確認。
4. FPGA未接続、READY固定low、BUSY固定high、転送中Ctrl-C、FPGA resetからUSB REPLへ戻れることを確認。
5. 描画へ切替→console復帰、480p/720p、PSG/wave/PCMの動作を確認。実際のFPSと転送速度を記録する。

レジスタ定数`kagura/regs.py`は`spec/registers.json`から生成する。手動編集しない。
