# Tang Nano 9K

KAGURA-9の対象ボード。board top（`kagura_*_top.sv`）、ピン制約（`*.cst`）、タイミング制約（`*.sdc`）、ピン一覧（[pin-inventory.csv](pin-inventory.csv)）を置く。CST/SDCは`tools/build-nano9k.tcl`が構成ごとに連結してbuildディレクトリへ書き出す。ビルドと書込みは[ビルド・テスト](../../docs/build-and-test.md)、構成とLEDは[アーキテクチャ](../../docs/architecture.md#ビルド構成とcaps)を参照。

## 基本のピン

| 機能 | FPGA package pin |
|---|---|
| 27MHz reference | 52 |
| TMDS CLK P/N | 69/68 |
| TMDS D0 P/N | 71/70 |
| TMDS D1 P/N | 73/72 |
| TMDS D2 P/N | 75/74 |
| reset（S2） | 4（1.8V側、10kΩ pull-up、押下でlow）。S1はpin 3（未使用） |
| LED1..6（active low） | 10、11、13、14、15、16 |

## board top

| top | 構成 | CST |
|---|---|---|
| `kagura_phase1_top` | `hdmi`（カラーバー＋固定テスト音） | `phase1.cst` |
| `kagura_phase1_dvi_top` | `dvi` | `phase1.cst` |
| `kagura_demo_top`（deprecated） | `demo` | `phase1.cst` |
| `kagura_phase2_top` | `phase2`（W65C02S） | `phase1.cst`＋`phase2-cpu.cst` |
| `kagura_phase2_boot_top` | `phase2boot` | 上記＋`boot.cst` |
| `kagura_host_top` | `spi`・`qspi`・`spipsram`・`qspipsram` | `phase1.cst`＋`host.cst` |
| `kagura_boot_probe_top`、`kagura_flash_magic_probe_top` | `bootprobe`、`magicprobe` | `boot-probe.cst` |

HDMI streamのinstance名は全topで`kagura_phase1_top`と揃えてあり、`phase1.cst`・`phase1*.sdc`を共有する。他に、BSRAM・PSRAM・HyperRAMの評価用top（`kagura_bsram_eval_top`、`kagura_psram_eval_top`、`kagura_hyperram_*_top`）がある（[PSRAM](../../docs/psram.md#評価用top)）。

## SPI/QSPIホスト（`host.cst`）

| 信号 | pin | ヘッダ |
|---|---:|---|
| IO0 (MOSI) | 28 | J5-8 |
| IO1 (MISO) | 29 | J5-9 |
| IO2 | 30 | J5-10 |
| IO3 | 33 | J5-11 |
| SCK | 35 | J5-14 |
| /CS | 42 | J5-16 |
| BUSY | 26 | J5-6 |
| READY | 27 | J5-7 |
| /IRQ | 49 | J6-20 |

pin 36〜39（TFカード）はHi-Z・pullなし。詳細は[ホストインターフェース](../../docs/host-interface.md)、Picoとの配線は[Pico firmware](../../software/pico/README.md#配線)。

## CPU接続

`phase2`・`phase2boot`のW65C02Sバス（`phase2-cpu.cst`）。すべて3.3VのBank 1/2。

| 論理信号 | package pin |
|---|---|
| D0..D7 | 28, 29, 30, 33, 34, 40, 35, 41 |
| A0..A4 | 31, 32, 36, 37, 38 |
| /CS | 42 |
| RWB | 48 |
| PHI2出力 | 25 |
| CPU reset release | 27（pull-down） |
| /IRQ（open drain） | 39 |

計18本。/RESETはFPGA出力を直接CPUへつながず、[外部のreset保持回路](../../docs/timing.md#irqとcpu-reset)を通す。`phase2boot`はさらにpin 26を`BOOT_MAP`出力、pin 59〜62をオンボードSPI Flashに使う（[ROM-less boot](../../docs/romless-boot.md#ピン)）。

## 共有と禁止事項

- pin 31〜35・40〜42はRGB LCD、36〜39はTFカード、48・49はSPI LCDと共有する。CPU版はTFカード未挿入・LCD未接続を条件とする。HDMIとRGB LCDは同時に使わない。
- **J5-23/24とJ6-12〜17にはHDMIのTMDS信号がそのまま出ている**。何も接続しない（stubになり信号品質を損なう）。ブレッドボードに基板ごと挿さない。
- J6-2〜9はBank 3の1.8V。3.3Vの信号へ接続しない。1.8V側のLED・buttonのピンを3.3Vのバスへ混ぜない。
- BL702、JTAG、MODE、DONEのピンは転用しない。

## 回路図との照合（2026-10-23）

[pin-inventory.csv](pin-inventory.csv)は、ヘッダJ5/J6の全48ピンについてpackage pin、site、bank、VCCIO、回路図net、共有負荷、KAGURAでの用途を記録している。出典は手元の基板（シルク「3674」）に対応するSipeed公式回路図`Tang_nano_9K_3674_schematics.pdf`（2024-03-11、SHA256 `5e720b0d128dab277896290ca41bb290c5a533adf04b4c4baa4546844be8f3d8`）。比較に3672版回路図（SHA256 `71ccf1b7731589c8bc5b4c1dcf0c8906f52831785c703732d43a70f01ec574ec`）と外形図（2×24ピン、2.54mmピッチ、列間22.82mm）も参照した。

- 基板版: シルク「3674」、Rev表記なし。3672版との違いはBL702側（JTAGのI/O電源が1.8V、TCKは分圧）で、FPGAのピン割当て、J5/J6、HDMI回路は同じ。chip IDは`0x1100481B`（GW1NR-9C）。
- J6-18は+5V（USB VBUS）、J6-23はGND、J6-24は+3V3。J6-19〜22はPIN48/49/31/32。
- ヘッダの向き: 両ヘッダともUSB側が1番、HDMI側が24番（USB側の端がJ5=38・J6=63、HDMI側の端がJ5=69・J6=3V3）。
- HDMI出力はAC結合（100nF）＋送信側の49.9Ω pull-up（3.3V）。HDMI connectorの+5V（pin 18）はダイオード経由で供給し、HPDはFPGAに接続されていない。
- オンボードSPI Flash（U3、PUYA P25Q32U、32Mbit）: CS=60、SCLK=59、SI=61、SO=62（bank 1、3.3V）。WP/IO2とRESET/IO3はFPGAへ配線されず4.7kΩでpull-up。

型番・基板版が異なる場合はCSTを使う前に照合する。未確認のピンを推測でCSTへ追加しない。
