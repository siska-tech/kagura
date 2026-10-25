# Tang Nano 9K platform notes

Phase 1の試験top/CST/SDCを追加し、配置配線とbitstream生成を実行済み。STA数値違反0、I/O・CDC制約監査済み。カラーバー版を内蔵Flashへ書込み、電源投入起動でPCディスプレイ1台の映像・音声を確認。**P1-07実機互換性試験は未完了**（[手順と記録表](../../docs/p1-07-hardware-test.md)）。結果は[検証状況](../../docs/validation-status.md)、再現手順とLEDの参照先は[ビルドガイド](../../docs/build-and-test.md)に記載。

【資料確認】公式CSTと回路図の調査値。実基板との照合前なので、このファイルは配線承認済みCSTではない。

CPU不要の`demo` topは背景・スプライトに6ch音源を追加し、HDMIへ出力する。音源の初期設定と512byteの波形転送（両bank）はsequencerが行い、以後は縦スクロールシューティング風の画面を毎フレーム動かしながら、内蔵の約15秒ループ曲をAUDIO_COMMITで演奏する（最初の1周目前半はリードなし）。S2で全体をresetし、映像と音声の初期化から曲頭へ戻る。左1kHz／右500Hzの固定テスト音を出すPhase 1試験topとは異なる音になる。ビルド・検証結果は[検証状況](../../docs/validation-status.md)を参照。

| 機能 | FPGA package pin |
|---|---|
| 27MHz reference | 52 |
| TMDS CLK P/N | 69/68 |
| TMDS D0 P/N | 71/70 |
| TMDS D1 P/N | 73/72 |
| TMDS D2 P/N | 75/74 |
| onboard button S2 | 4（1.8V側、10kΩ pull-up、押下でLow。CPU resetへ直結しない）。S1はpin 3 |

出典: [公式CST](https://github.com/sipeed/TangNano-9K-example/blob/c3b795799f23de91982be52db4273a8eea100cdb/hdmi/src/hdmi.cst)、[公式回路図](https://dl.sipeed.com/fileList/TANG/Nano%209K/2_Schematic/Tang_Nano_9k_3672_Schematic.pdf)。差動出力の実部品・電源・DDC/HPDは回路図と実物で照合し、任意のLVDS pinへ移さない。

## CPU接続候補（設計、未配線）

| 論理信号 | package pin候補 |
|---|---|
| D0..D7 | 28,29,30,33,34,40,35,41 |
| A0..A4 | 31,32,36,37,38 |
| /CS | 42 |
| RWB | 48 |
| PHI2 output | 25 |
| CPU reset release制御 | 27 |
| /IRQ open drain | 39 |

計18本。既存tn_vdpの3.3V使用例と公式net名を照合した候補で、ヘッダの物理位置は別途ピン図で照合する。RDY追加なら1本追加。/RESET線はFPGA出力を直接CPUへつなぐだけで設定前保証ができるわけではなく、[reset設計](../../docs/timing.md)の外部回路を通す。

### ROM-less boot構成

`phase2boot`/`phase2boot720`は上記CPU信号に加え、pin 26を`BOOT_MAP`出力として使い、オンボードP25Q32Uをpin 59（SCLK）、60（CS#）、61（MOSI）、62（MISO）から読み出す。対象構成だけ`-use_mspi_as_gpio 1`を有効にする。`BOOT_MAP`はFPGA設定前にlowとなる外付けpull-downを前提とし、設定後はブート窓を有効にするためhigh、`$FFFF`読出し後のPHI2 low期間にlowへ戻る。

Flash読出しとCPU起動はRTL simulation済みだが、MSPI兼用ピンからの実Flash読出し、Flashへの安全な書込み、外部decode/RESB保持回路、W65C02S実機起動は未検証である。[ROM-less boot実現可能性](../../docs/romless-boot-feasibility.md)のStage 1・3・5を完了するまで実用構成として扱わない。

CPU/HDMI不要の`bootprobe`構成はStage 1用で、LED 6本を順にJEDEC ID=`85 60 16`、有効なK9BT image、error code bit 3〜0として表示する。`BOOT_MAP`はlow固定。期待IDは実機で未確認のため、ID LEDが消灯しても読出し自体が失敗したとは限らず、最初の実測後に値を確定する。

36..39はTFカード系、31/32/33/34等はLCD系と共有するため、初版はTFカード未挿入・LCD未接続。HDMIとRGB LCDも共有するので同時使用しない。BL702/JTAG/Flash/MODE/DONEは転用しない。1.8V側のLED/button/header pinを3.3V CPUへ混ぜない。

## Pin inventory（回路図照合、2026-10-23）

[pin-inventory.csv](pin-inventory.csv)に、ヘッダJ5/J6の全48ピンについてpackage pin、site、bank、VCCIO、回路図net、共有負荷、KAGURAでの用途を記録した。出典は手元の基板（シルク「3674」）に対応するSipeed公式回路図`Tang_nano_9K_3674_schematics.pdf`（2024-03-11、取得時SHA256 `5e720b0d128dab277896290ca41bb290c5a533adf04b4c4baa4546844be8f3d8`）。比較として3672版回路図（2021-09-22、SHA256 `71ccf1b7731589c8bc5b4c1dcf0c8906f52831785c703732d43a70f01ec574ec`）と外形図`Tang_Nano_9K_3672_size.pdf`（2×24ピン、2.54mmピッチ、列間22.82mm）も参照した。

- 基板版: 実基板のシルクは「3674」でRev表記なし。3674回路図の改版履歴表は3672版と同じ6200〜6202（名称・シルクのみの変更）。3672版との違いはBL702側で、JTAGのI/O電源がVCCO3（1.8V）になり、TCKは3.6kΩ/4.7kΩ分圧でFPGAへ入る。FPGAのピン割当て、ヘッダJ5/J6、HDMI回路は両版で同じ。チップIDは`0x1100481B`（GW1NR-9C）を読出しで確認済み。
- CPU候補18本はすべてJ5/J6に出ており、3.3VのBank 1/2。上表の割当てと一致した。共有負荷はRGB LCD（31〜35、40〜42）、TF card（36〜39）、SPI LCD（48）で、初版はTF card未挿入・LCD未接続を条件とする。
- **J5-23/24とJ6-12〜17はHDMIのTMDS信号**がそのまま出ている。何も接続しない（stubになり信号品質を損なう）。
- J6-2〜9はBank 3の1.8V。3.3VのCPUへ接続しない。
- J6-18は+5V（USB VBUS）、J6-23はGND、J6-24は+3V3。J6-19〜22はPIN48/49/31/32（当初の読み取りで1つずれていたものを、3674回路図と実基板の確認で訂正）。
- ヘッダの向き: 実基板のシルクで、USB側の端がJ5=38・J6=63、HDMI側の端がJ5=69・J6=3V3。両ヘッダともUSB側が1番、HDMI側が24番で、回路図の割当てと一致した。
- HDMI出力はAC結合（100nF）＋送信側の49.9Ω pull-up（3.3V）の構成で、HDMI connectorの+5V（pin 18）はダイオード経由で供給、HPDはFPGAに接続されていない。

型番・基板版が異なる場合はCST生成前に停止する。未確認のpinを推測でCSTへ追加しない。

## PSRAMとHDMIのPLL共用評価

`kagura_hyperram_hdmi_top.sv`はsystem PLLの54MHz CLKOUT/67.5° CLKOUTPを使い、die 0全4MiBのUART memtestとHDMIカラーバー・48kHzテスト音を同時実行する。`tools/build-gowin-hyperram-hdmi.tcl 480|720`でビルドする（作業ディレクトリはモード別に分ける）。UART TXはpin 17、115200 8N1。LED下位4本はmemtestのinit/clean/ever-fail/pass、上位2本はHDMI underflow/overflowを示す。

2026-10-25に両モードでPLL 2個・STA setup/hold違反0、各64連続passエラー0、ユーザーによる映像・音声正常を確認した。720pの既存OSER10 reset例外と、外部PSRAM端子タイミングのSTA範囲には注意する。数値・制約・再現手順は[PSRAM/PCM記録](../../docs/psram-pcm.md)を参照。本体rendererやPCM再生を統合した構成ではない。
