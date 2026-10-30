# Pico host firmware（SPI / QSPI）

Raspberry Pi Pico（RP2040、機材H1）からTang Nano 9KのSPI/QSPI bitstreamを操作する診断firmwareとVRAM uploader。[ホスト仕様](../../docs/host-interface.md)のトランザクションを、PIOで10MHz以下のmode 0として実装する。レジスタ定数は生成ヘッダ[`kagura_regs.h`](../include/kagura_regs.h)を使う。既定のboardは`pico`。Pico Wでも`-DPICO_BOARD=pico_w`で同じ配線のまま使える（無線機能とGP23〜25・29は使わない）。

SPI/QSPIとも5MHzで全診断に合格している（記録は「実機確認の手順」）。PSRAM版のbitstreamでは`psram`・`copy`・`pcm`・`stress`も使える。

## 配線

両基板とも3.3V I/O。電源は各自のUSBから取り、**GNDだけを共通**にする（3V3/5V同士は接続しない）。配線は短く（目安15cm以内）、GNDを2本以上つなぐ。FPGAピンは[ピン一覧](../../boards/tang-nano-9k/pin-inventory.csv)のSPI/QSPI割当て。RGB/SPI LCDは接続しない。TFカードの4本（pin 36〜39、J5-1〜4）はSPI/QSPI bitstreamではHi-Z（pull無し）で、Picoから直接アクセスするために空けてある（この診断firmwareはTFカードを使わない）。

| 信号 | Pico | Pico物理pin | Tang Nano 9K | ヘッダ | 備考 |
|---|---|---:|---:|---|---|
| IO0 (MOSI) | GP2 | 4 | 28 | J5-8 | |
| IO1 (MISO) | GP3 | 5 | 29 | J5-9 | |
| IO2 | GP4 | 6 | 30 | J5-10 | QSPIのみ使用（SPIでは両側Hi-Z） |
| IO3 | GP5 | 7 | 33 | J5-11 | QSPIのみ使用 |
| SCK | GP6 | 9 | 35 | J5-14 | |
| /CS | GP7 | 10 | 42 | J5-16 | |
| BUSY | GP8 | 11 | 26 | J5-6 | |
| READY | GP9 | 12 | 27 | J5-7 | Pico側pull-down（FPGA未設定時は未準備） |
| /IRQ | GP10 | 14 | 49 | J6-20 | open drain。4.7kΩでPico 3V3(OUT)（pin 36）へpull-up |
| GND | GND | 3, 8, 13 | GND | J6-23 | 2本以上 |

SPI/QSPIで配線は同じ。bitstreamは`tools/build-nano9k.tcl spi`・`qspi`・`spipsram`・`qspipsram`（[ビルドガイド](../../docs/build-and-test.md)）で作り、firmwareの`mode`を一致させる。

### ブレッドボードで組む場合

- ブレッドボードに挿すのはPicoだけにし、Tang Nano 9Kはオス-メスのジャンパ線でヘッダへつなぐ。基板ごと挿すとTMDSのヘッダpin（J5-23/24、J6-12〜17）が接点列に触れて容量の付いたstubになり、HDMI出力を乱すおそれがある（[ピン一覧](../../boards/tang-nano-9k/pin-inventory.csv)は開放を指定）。
- 接点容量とジャンパ線の長さで10MHzの成否が変わる。`div 10`（1MHz）から上げ、ブレッドボード構成で合格した最大値として記録する。
- SCKはほかの信号線と束ねない。高い速度で失敗したら、まずオシロでSCKのリンギングを見る。改善しなければPico側のSCKに33Ω程度の直列抵抗を入れて比較する。
- 電源レールにはPicoの3V3(OUT)だけを出し、/IRQのpull-upに使う。Tang Nano 9Kの3V3・5Vはレールへつながない。

## ビルドと書込み

Pico SDK 2.2.0、Arm GNU Toolchain 14.2.rel1、CMake 3.13以上。WSL/Linuxで:

```sh
export PICO_SDK_PATH=~/opt/pico-sdk-2.2.0
export PATH=~/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:~/opt/cmake-3.31.6-linux-x86_64/bin:$PATH
cmake -S software/pico -B build/pico -DCMAKE_BUILD_TYPE=Release
cmake --build build/pico -j8
```

BOOTSELを押しながらPicoをUSB接続し、現れたドライブへ`build/pico/kagura_host.uf2`をコピーする。CIでもビルドし、`pico-firmware` artifactにUF2を保存する。

## 使い方

USBシリアル（COMポート）を端末で開く（改行はLFまたはCR）。起動時はSPI・SCK 2.5MHz（`div 4`）。

| コマンド | 内容 |
|---|---|
| `info` | ID/ABI/CAPS/STATUS/FIFO_STATUS/ERROR_CODE、READY・/IRQの状態 |
| `diag` | 縦通し試験。各項目を`PASS`/`FAIL`で表示し、最後に`DIAG PASS`または`DIAG FAIL n` |
| `abort` | write header途中・data byte途中で/CSを上げ、副作用がなく直後のID読出しが成功することを確認 |
| `show [seconds]` | 月夜の砂漠都市、多重scroll、走る・跳ぶ旅人、magic sprite、6ch音楽を同期再生。既定30秒、`0`はキー入力まで継続 |
| `mode spi` / `mode qspi` | bitstreamに合わせる |
| `div n` | SCK = 10MHz / n |
| `rd <off> [n]` / `wr <off> <val>` | レジスタの読み書き（16進） |
| `w <addr> <len>` / `c <addr> <len>` | VRAMへのupload、読戻しCRC（uploader用） |
| `psram [len]` | PSRAM版（`spipsram`/`qspipsram`、CAPS b3）でPSRAM領域の乱数位置へlen byte（既定2048、最大2048）をupload→FENCE→READ_REQUESTで読戻して照合し、速度を表示 |
| `copy [len]` | PSRAM版でlen byte（既定2048）の乱数をPSRAMへ置き、COMMAND COPYでpattern領域の乱数位置へ複写してVRAMから読戻し照合する。続いて32767 byteの複写時間（FENCE込み）を表示 |
| `pcm [seconds] [swap] [move] [solo] [mute] [mutep] [nonote] [zero] [m=<n>]` / `piano ...` | PSRAM版で2秒のメロディ（PCM 0、loop）とCC0の実録ピアノC4（PCM 1、one-shot）をuploadし、ピアノ72000 byteを全量読戻し照合したうえで、2秒ごとにPREPARE＋AUDIO_COMMITで単音を再発音。UNDERRUN・CONFIG_ERROR・MEMORY_ERROR・ERROR_CODE・メロディの停止がなければ`PASS pcm`。`swap`でピアノをPCM 0、メロディをPCM 1へ、`move`で両者のPSRAM配置（0x400000/0x480000）を入れ替え、`solo`でメロディを鳴らさない、`mute`/`mutep`でメロディ/ピアノをゲイン0のまま再生（PSRAM読出しだけ行う）、`nonote`でピアノのチャンネルを動かさず、`zero`でピアノの代わりに無音を再生、`m=<n>`で開始前にMASTER_GAINを設定する（使用値を表示）。既定10秒、`0`はキー入力まで |
| `fbbench [reps] [seconds] [full] [pcm] [psg]` | C版TileFramebuffer（320×240・4bpp疑似フレームバッファ）のベンチマーク。480p・ABI 0.6・1200パターンのbitstream専用で、画面全体を専有する。既定10回・10秒。`full`で全38400 byteを読み戻す。`pcm`はMicroPythonの`Session.pcm_start()`と同じPCM 2ch（PSRAMの三角波ループ、MASTER_GAIN 64）、`psg`はpulse 3声・noise・wavetable 2声の和音を全区間鳴らし、終了時に止める（下記） |
| `fbdemo [seconds]` | C版TileFramebufferのデモ。プラズマ・トンネル（1回描いてパレット回転）、星空の上で回る4D超立方体、虹色の線リボン（毎フレーム描き直し、変わったタイルだけ転送）を約12秒ずつフェードで切り替え、PSGのBGMを流す。毎フレーム末尾のパレットCOMMITでVBlankに同期する。fbbenchとフレームバッファを共有し、条件も同じ。既定60秒、`0`はキー入力まで継続 |
| `imgdemo [gen\|recv]` | 疑似256色の画像デモ（480p・ABI 0.6）。16色×16パレットを8×8セルごとに選び、フェードインで表示して残す。`gen`（既定）はPico上で夕景を計算して減色（約18秒）、`recv`はPCの`send_image.py`から受け取る（下記） |
| `clear` | ERROR_CODEとIRQ.ERRORをclear |
| `reboot` | watchdogでチップをリセットし、Flashから起動し直す（RAMに読み込んだビルドから元のfirmwareへ戻る） |

`diag`の内容: READY待ち → ID/ABI/CAPSのINC read（SPIはheaderのFIFO_STATUSも確認）→ SCREEN_HEIGHT → レジスタ書込み・読戻し → VRAM 2048byte書込みと読戻し照合 → FILL＋FENCE → 背景色と16×16 spriteをCOMMITで120frame移動 → 全6音源を1秒鳴動しwave bank交換を読戻し → VBLANKで/IRQが下がりW1Cで戻る → 64回のFILLと4096byte連続書込み（BUSY待ち、FIFO_FULLなし）→ ERROR_CODE=0。転送量・時間・BUSY待ち回数も表示する。画面の動き・音、および基板LED2（adapterの`late`）が消灯のままであることを目視確認する。LED1はreset解除表示なので正常動作中は点灯する。

VRAM uploader（Windows PowerShell 5.1）:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/kagura-upload.ps1 -Port COM5 -File tiles.bin -Address 0x0000 -Verify
```

4096byteごとに送り、Picoが受け取ったデータのCRC32を照合する。`-Verify`はFPGAから読み戻したVRAMのCRC32も照合する（READ_REQUESTを1byteずつ使うため遅い）。`-Mode qspi`・`-Div 1`で接続設定も変えられる。

## Picoショーケース

`show 30`は外部データを使わず、Pico上で4bpp pattern・64×32 map・palette・OAM・wave tableを生成してKAGURA-9へ転送する。月夜の空、雲・砂丘、遠景と近景の都市、屋上、前景を8 bandのraster scrollで異なる速度に動かす。32×32のオリジナル旅人は4個の16×16 spriteで構成し、走行2 poseとjump 2 poseを周期的に切り替える。pulse 3声の和音、noise percussion、wavetable melody/bassを同時演奏する。`show 0`はUSBシリアルへ任意のキーを入力するまで継続する。

QSPI 5MHz推奨。ABI 0.3の`RSCROLL`がないbitstreamでも動作するが、bandごとの横揺れは無効になる。終了時は音源を停止し、映像は最終frameを保持する。診断へ戻す場合はそのまま`diag`を実行できる。

## C版疑似フレームバッファのベンチマーク

`tile_fb.c`（描画、I/Oなし）と`tile_fb_io.c`（初期化・flush）は、MicroPython SDKの[TileFramebuffer](../../docs/framebuffer.md)のC移植。タイル配置、dirty管理、Bresenham線・midpoint円、`flush(max_gap)`のrun分割・1023/1024分割・FENCE確定・失敗時にdirtyを残す規則まで同じ。色が0〜15以外の呼出しは例外の代わりにno-op。`line`／`circle`の座標はint16。

`fb_bench.c`は[`framebuffer_benchmark.py`](../micropython/examples/framebuffer_benchmark.py)と同じ負荷を測り、`FB `で始まる1行1結果で出力する。

| 行 | 内容 |
|---|---|
| `FB initialize` | 表示停止・map・上位表・全1200パターン転送・表示再開までの時間 |
| `FB draw` | CPU描画のみ（SysTickのcycle計測）。pixel_1024・hline・vline・line・fill_rect・fill・circle・rect、clean時のdirty走査。各回0番色・dirty clearから開始 |
| `FB flush` | dirty 1/10/100/1200 tileのflush。transfer（VRAM書込み＋error確認）、fence_wait（DONE_TAG読出し・FENCE・完了待ち・error確認）、全体。トランザクション数とwire byte数（header・dummy込み）。dirty 0ではI/O 0件を検査 |
| `FB gap` | 1つおき・8つおきのdirty tileを`max_gap` 0と1／7で比較 |
| `FB telemetry` | 各区間の後にERROR_CODE、AUDIO_STATUS（FIFO underflow/overflow）、PCM時は両chのstatus（error bitやACTIVE落ち）を検査。loopでは毎回同じ検査を行い、異常で中断する |
| `FB loop` | 移動window・title bar・cursor点滅を描きflush、毎loop telemetryとFRAME_COUNTを読む。application Hz、HDMI counter Hz、draw／flush／iterationの平均・最小・p95（直近256）・最大 |
| `FB scene` / `FB readback` | 固定sceneのbuffer CRC32をPC参照値（`SCENE_CRC`）と照合し、flush後にtile 0/1023/1024/1199をVRAMから読戻し照合。`full`は全1200 tile（READ_REQUESTを1 byteずつ使うため遅い） |

最後に`FBBENCH PASS`または`FBBENCH FAIL n`。CPUは120MHz（PIOの都合、MicroPython記録は125MHz）、転送はCPU供給のPIOでDMAは使わない。音源は鳴らさない。終了時はsceneを表示したまま残る。

`tests/test_tile_fb.py`は`tests/tile_fb_host.c`をPCのgcc（ASan/UBSan）でビルドし、Python実装とbuffer・dirty・flush統計・VRAM書込み列・注入した書込み/FENCE失敗後の状態が完全一致することと、`SCENE_CRC`がPythonの結果であることを検査する（CIで実行）。

```sh
python3 -I software/pico/tests/test_tile_fb.py
```

PicoのFlash（MicroPythonとboot.py）を書き換えずに測るには、RAM専用ビルドを使う。`-DPICO_DEFAULT_BINARY_TYPE=no_flash`でビルドし（約253KBがSRAMに収まる。piano sampleを含むため余裕は約4KB）、MicroPythonの`machine.bootloader()`で出たRPI-RP2ドライブへUF2をコピーする。`mode qspi`・`div 2`・`fbbench`の後、`reboot`でチップをリセットするとFlashのMicroPythonへ戻る。

## 疑似256色の画像デモ

map の各セルは16本のパレットから1本を選べる（palette番号×16＋画素値）。TileFramebufferは全セル同じパレットを使うが、`imgdemo`は全1200パターンを書いた後、mapをセルごとのパレット番号で書き直し、画面全体で最大256色（RGB444）を出す。手順は`img_quant.c`（I/Oなし）:

1. セルごとの平均色をk-meansで16グループに分ける（farthest-point初期値で決定的）。
2. グループごとに、その画素から16色をk-meansで求める。
3. 各セルを、自分の画素を最もよく再現するパレットへ付け替えて、16色を求め直す（`rounds`回）。
4. RGB444へ丸め、4×4 Bayerのordered ditherで各画素の色番号を決める。

画素値0は透明でBACKDROP（palette 0の0番）になるため、全パレットの0番は同じ色（最も暗いセルの平均色）とし、パレットごとに選ぶのは1〜15番。

色差は`2ΔR²+4ΔG²+3ΔB²`。元画像は保持せず、必要な度に計算し直す（RGB 76800画素はSRAMに入らない）。作業領域は画素出力の先頭3600 Bを借り、heapを使わない。no_flashビルドに収めるため`img_*.c`は`-Os`。

- `imgdemo gen`: `img_scene.c`の夕焼け・星・3層の山・湖面の映り込みと揺らぐ光の道をPico上で計算・減色する（QSPI 5 MHz、120 MHzで計算約18秒、表示0.46秒）。PCでの参照はPSNR約32 dB。
- `imgdemo recv`: `IMG READY`の後、`KIMG`、パレット512 B、セルのパレット番号1200 B、画素38400 B（tile-native 4bpp）、その3つのCRC-32（4 B）を受け取る（`img_demo.h`）。長さ・CRC・値の範囲がすべて正しいときだけ表示する。約40 KBの受信は約0.6秒。

`send_image.py`は任意の画像を320×240に縮小・中央切り出しし、同じ手順（反復は多め）で変換して送る。Pillow・NumPy・pyserialが必要:

```sh
uv run --with pillow --with numpy --with pyserial software/pico/send_image.py --port COM9 photo.jpg
uv run --with pillow --with numpy software/pico/send_image.py --preview out.png photo.jpg   # 送らずに確認
```

`mode qspi`・`div 2`を先に送る（`--no-setup`で省略）。`tests/test_img_demo.py`は`tests/img_quant_host.c`をgcc（ASan/UBSan）でビルドし、出力の範囲・16パレットの使用・PSNR・決定性と、`send_image.py`の画素配置・送信形式が`img_demo.h`と一致することを検査する（CIで実行、NumPy不要）。

## 実機確認の手順

外部ホスト接続の受入手順。各段階でオシロ（M1、2ch）を使い、SCKと対象信号の波形を確認する。

1. SPI bitstreamで`div 10`（1MHz）→`diag`。合格したら`div 4`、`div 2`、`div 1`（10MHz）と上げ、合格した最大値を記録する。
2. QSPI bitstreamで`mode qspi`にして同じ手順。
3. 復帰: `diag`合格後にTang Nano 9KのS2（reset）を押し、READYが一度下がって戻ることを`info`で確認してから再度`diag`。Pico側のUSB再接続後も同様。
4. uploader: 32KBのpattern全域を`-Verify`付きで転送し、CRC一致と転送速度を記録する。
5. `abort`を実行し、header途中・data byte途中の両方が副作用なしで、その直後のID読出しまで合格することを確認する。
6. 10MHzでオシロにより、SCK立上りに対するMISO（QSPIはIO）の変化時刻とt_CSSを測る（[ホスト仕様](../../docs/host-interface.md)の算定: FPGA出力は立上りから37〜56ns＋出力遅延）。

| 日付 | bitstream（commit） | mode | 最大合格SCK | diag | 復帰 | uploader（KB/s） | 波形・備考 |
|---|---|---|---|---|---|---|---|
| 2026-10-25 | `kagura_spi.fs`（`ea8500b`） | SPI | 5MHz | 反復PASS | S2 reset・Pico USB再接続後PASS | 570.2 | 32KiB全域verify、BUSY 41〜50回、6ch音源・wave bank交換、header/data途中中断PASS。10MHzはVRAM読戻し不一致 |
| 2026-10-25 | `kagura_qspi.fs`（`ea8500b`、SHA256 `DF739BBC…EC63`） | QSPI | 5MHz | 反復PASS | S2 reset・Pico USB再接続後PASS | 1,023.1 | 32KiB全域verify、BUSY 56〜59回、6ch音源・wave bank交換、header/data途中中断PASS。LED1点灯・LED2（`late`）消灯。10MHzはbit化け。ブレッドボード評価のためオシロ測定は対象外 |

32KiB uploaderは4096byte×8 blockを全域読戻し照合し、QSPIは2.06秒・1,023.1KB/s、SPIは2.19秒・570.2KB/sだった。使用したPico firmware（`abort`追加前）のUF2 SHA256は`01E151B3…306C`。`abort`追加後のUF2（SHA256 `4C9942F1…C7E5`）ではSPI/QSPI 5MHzでheader/data途中中断と直後のID読出し、その後の全診断に合格した。Tang内蔵FlashへのQSPI bitstream書込み後、Flash bootから同じ診断に合格したが、Gowin Programmerの書込み時照合は`Verify Failed at 0`のため、Flash内容のreadback照合済みとは扱わない。

今回のブレッドボード配線ではオシロ測定を完了条件から除外した。5MHz合格・10MHz不合格はこの配線個体での機能試験結果であり、信号品質や量産配線のタイミング余裕を保証しない。

## 実装メモ

- PIOは120MHz（`set_sys_clock_khz(120000)`）で12cycle/SCK。データはSCK立下りと同時に変え、立上りの6cycle前から保持する。MISO/IOはlow期間の末尾（SCK立上り直前）に取り込む。FPGAは検出した立上りの後で次のbitへ更新するため、更新遅延とRP2040入力同期器の位相に依存せず現在のbitを読める。
- PicoのSCK・CS・IO0..3は2mA drive・slow slew、IO0..3の入力hysteresis有効に固定する。ブレッドボード配線でのovershoot・crosstalkを抑えるためで、外付け直列抵抗や実波形確認の代わりにはしない。
- `tests/test_pio_timing.py`はpioasmの生成ヘッダを1cycleずつ実行し、仕様どおりのadapterモデル（立上りから37〜56ns＋出力・配線遅延で変化）と組み合わせて、SCKのhigh/low時間、MOSIのsetup、50通りの出力遅延での読出し値、BUSYによる待ち、QSPIのIO解放がFPGAの駆動より前であることを検査する（CIで実行）。RP2040の電気特性や実配線は含まない。
- キューを消費するbyte（VRAM_WRITE、VRAM_READ_REQUEST、COMMAND）は、PIOがbyteの直前に`wait 0 gpio BUSY`する。BUSYの立上り・立下りをGPIO edge IRQで記録し、pulse回数とhigh時間を統計表示する。
- QSPIはcount byteの最後の立下り直後にPIOがIOを解放し、/CS high中に次のトランザクション用に駆動へ戻す。
- 待ちはすべてtimeout付き。BUSYで止まったbyteはSMを再起動して/CSを上げる（adapterは途中のbyteを捨てる）。結果が不明な操作を自動で再送しない。
- `pico_sdk_import.cmake`はPico SDK 2.2.0の`external/`からの写し（BSD-3-Clause、[第三者IP方針](../../THIRD_PARTY.md)）。
