# Pico host firmware（SPI / QSPI）

Raspberry Pi Pico（RP2040、機材H1）からTang Nano 9KのSPI/QSPI bitstreamを操作する診断firmwareとVRAM uploader。[ホスト仕様](../../docs/host-interface.md)のトランザクションを、PIOで10MHz以下のmode 0として実装する。レジスタ定数は生成ヘッダ[`kagura_regs.h`](../include/kagura_regs.h)を使う。既定のboardは`pico`。Pico Wでも`-DPICO_BOARD=pico_w`で同じ配線のまま使える（無線機能とGP23〜25・29は使わない）。

【未検証】実機での動作は未確認。下の手順で確認した結果を記録してから合格とする。

## 配線

両基板とも3.3V I/O。電源は各自のUSBから取り、**GNDだけを共通**にする（3V3/5V同士は接続しない）。配線は短く（目安15cm以内）、GNDを2本以上つなぐ。FPGAピンは[ピン一覧](../../boards/tang-nano-9k/pin-inventory.csv)のSPI/QSPI割当て。TFカードは挿さず、RGB/SPI LCDは接続しない。

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
| /IRQ | GP10 | 14 | 39 | J5-4 | open drain。4.7kΩでPico 3V3(OUT)（pin 36）へpull-up |
| GND | GND | 3, 8, 13 | GND | J6-23 | 2本以上 |

SPI/QSPIで配線は同じ。bitstreamは`tools/build-nano9k.tcl spi`または`qspi`（[ビルドガイド](../../docs/build-and-test.md)）で作り、firmwareの`mode`を一致させる。

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
| `mode spi` / `mode qspi` | bitstreamに合わせる |
| `div n` | SCK = 10MHz / n |
| `rd <off> [n]` / `wr <off> <val>` | レジスタの読み書き（16進） |
| `w <addr> <len>` / `c <addr> <len>` | VRAMへのupload、読戻しCRC（uploader用） |
| `clear` | ERROR_CODEとIRQ.ERRORをclear |

`diag`の内容: READY待ち → ID/ABI/CAPSのINC read（SPIはheaderのFIFO_STATUSも確認）→ SCREEN_HEIGHT → レジスタ書込み・読戻し → VRAM 2048byte書込みと読戻し照合 → FILL＋FENCE → 背景色と16×16 spriteをCOMMITで120frame移動 → ch0 440Hzを1秒 → VBLANKで/IRQが下がりW1Cで戻る → 64回のFILLと4096byte連続書込み（BUSY待ち、FIFO_FULLなし）→ ERROR_CODE=0。転送量・時間・BUSY待ち回数も表示する。画面の動き・音・基板のLED1（adapterの`late`）が消灯のままであることは目視で確認する。

VRAM uploader（Windows PowerShell 5.1）:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/kagura-upload.ps1 -Port COM5 -File tiles.bin -Address 0x0000 -Verify
```

4096byteごとに送り、Picoが受け取ったデータのCRC32を照合する。`-Verify`はFPGAから読み戻したVRAMのCRC32も照合する（READ_REQUESTを1byteずつ使うため遅い）。`-Mode qspi`・`-Div 1`で接続設定も変えられる。

## 実機確認の手順

[ロードマップ](../../docs/implementation-roadmap.md)M2の完了条件に対応する。各段階でオシロ（M1、2ch）を使い、SCKと対象信号の波形を確認する。

1. SPI bitstreamで`div 10`（1MHz）→`diag`。合格したら`div 4`、`div 2`、`div 1`（10MHz）と上げ、合格した最大値を記録する。
2. QSPI bitstreamで`mode qspi`にして同じ手順。
3. 復帰: `diag`合格後にTang Nano 9KのS2（reset）を押し、READYが一度下がって戻ることを`info`で確認してから再度`diag`。Pico側のUSB再接続後も同様。
4. uploader: 32KBのpattern全域を`-Verify`付きで転送し、CRC一致と転送速度を記録する。
5. 10MHzでオシロにより、SCK立上りに対するMISO（QSPIはIO）の変化時刻とt_CSSを測る（[ホスト仕様](../../docs/host-interface.md)の算定: FPGA出力は立上りから37〜56ns＋出力遅延）。

| 日付 | bitstream（commit） | mode | 最大合格SCK | diag | 復帰 | uploader（KB/s） | 波形・備考 |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## 実装メモ

- PIOは120MHz（`set_sys_clock_khz(120000)`）で12cycle/SCK。データはSCK立下りと同時に変え、立上りの6cycle前から保持する。取込みは立上り後1cycle（＋入力同期）で、FPGA出力のhold（≥37ns）の内側に置く。Pico側のSCK端基準で取込みは約8ns後、FPGA出力の変化は配線遅延込みで約48〜67ns後と見積もり、setup・holdとも約40nsの余裕。
- `tests/test_pio_timing.py`はpioasmの生成ヘッダを1cycleずつ実行し、仕様どおりのadapterモデル（立上りから37〜56ns＋出力・配線遅延で変化）と組み合わせて、SCKのhigh/low時間、MOSIのsetup、50通りの出力遅延での読出し値、BUSYによる待ち、QSPIのIO解放がFPGAの駆動より前であることを検査する（CIで実行）。RP2040の電気特性や実配線は含まない。
- キューを消費するbyte（VRAM_WRITE、VRAM_READ_REQUEST、COMMAND）は、PIOがbyteの直前に`wait 0 gpio BUSY`する。ソフトのBUSY待ち回数は統計用の標本値。
- QSPIはcount byteの最後の立下り直後にPIOがIOを解放し、/CS high中に次のトランザクション用に駆動へ戻す。
- 待ちはすべてtimeout付き。BUSYで止まったbyteはSMを再起動して/CSを上げる（adapterは途中のbyteを捨てる）。結果が不明な操作を自動で再送しない。
- `pico_sdk_import.cmake`はPico SDK 2.2.0の`external/`からの写し（BSD-3-Clause、[第三者IP方針](../../THIRD_PARTY.md)）。
