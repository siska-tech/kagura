# ROM-less boot（`phase2boot`）

W65C02S構成で外付けROMを使わず、Tang Nano 9K基板上のSPI Flash（P25Q32U、U3）に置いたプログラムをCPUのSRAMへ読み込んで起動する。構成`phase2boot`/`phase2boot720`だけが持つ機能で、通常のレジスタABIは変えない。

【状態】RTLはsimulationで縦通し済み。実機ではFPGAからのFlash読出しとimage検査（`bootprobe`）まで確認した。外部decode・RESB保持回路とW65C02S実機での起動は未確認で、実用構成としては扱わない。

## 方式（32 byte窓ブート）

ブートの間だけ、外部decodeが`$FFE0–$FFFF`の**読出し**をKAGURAの32 byte窓へ割り当てる。KAGURAはそこに26 byteのブートスタブ（6502コード）とベクタを返し、スタブがデータポートからFlashの内容を1 byteずつ読んで、**CPU自身が**SRAMへ書き込む。完了するとFPGAが割当てを解除する。

- CPUアダプタのピン（A0〜A4、/CS、RWB、D0〜D7）をそのまま使う。追加はヘッダの`BOOT_MAP`出力1本と、基板上のFlashの4本だけ。
- バスの所有権は常にCPUにある。BE・address・RWBをFPGAが駆動することはない。
- BSRAMは使わない（Flashから流すだけ）。

## 起動の流れ

1. 電源投入。RESBはlow（外部回路）、PHI2はlow、`BOOT_MAP`はlow（外付けpull-down）。FPGAが内蔵Flashから設定される。
2. PLLがlockしresetが解除されると、PHI2が出始め、`BOOT_MAP`を1にする。CPUはresetのまま。
3. FlashのJEDEC IDを読む（000000・FFFFFFや読出し失敗はerror 8）。
4. `0x100000`から32 byteのheaderを読んで検査し、続けてpayload全体を読んでCRC32を確かめる（1回目の読出し）。
5. VDPの初期化・line 0の準備・検査の合格がそろうと、PHI2を8周期出してからRESBを解除する。
6. CPUがresetベクタ`$FFFC/$FFFD`を読む。KAGURAは`$E0 $FF`を返し、スタブ`$FFE0`へ飛ぶ。ベクタの上位byteを読むまでは、データポートを読んでも内容を消費しない。
7. スタブがデータポート`$FFFA`から転送先のページ番号とページ数を読み、ページ単位でSRAMへコピーする（2回目の読出しをそのまま流す）。全byteを渡した後のポートは0を返す。
8. スタブは`BRK`を実行する。KAGURAはBRK/IRQベクタ`$FFFE/$FFFF`としてheaderのentry addressを返す。
9. `$FFFF`の読出し後、最初のPHI2 lowで`BOOT_MAP=0`にし、窓をVDPへ戻す。CPUはentryから実行する（I=1、D=0、SPはBRKで3減っている）。

### ブートスタブ

`$FFE0–$FFFF`（窓のoffset `$00–$1F`）の内容。

```text
FFE0  64 00      STZ $00        ; 転送先ポインタ low = 0
FFE2  AD FA FF   LDA $FFFA      ; ポート: 転送先ページ
FFE5  85 01      STA $01
FFE7  AE FA FF   LDX $FFFA      ; ポート: ページ数
FFEA  A0 00      LDY #$00
FFEC  AD FA FF   LDA $FFFA      ; ポート: データ
FFEF  91 00      STA ($00),Y
FFF1  C8         INY
FFF2  D0 F8      BNE $FFEC
FFF4  E6 01      INC $01
FFF6  CA         DEX
FFF7  D0 F3      BNE $FFEC
FFF9  00         BRK            ; $FFFE/$FFFF → entry
FFFA  (port)     データポート（NMIベクタの位置。ブート中のNMIは禁止）
FFFC  E0 FF      RESETベクタ → $FFE0
FFFE  (entry)    BRKベクタ。headerのentry_addr
```

1 byteあたり15 cycle（約4.4µs）。FlashのSCLKは6.75MHzで、次の読出しまでに次のbyteを先読みできる。最大のimage（0x9D00 byte）でも約0.18秒。使うRAMは`$0000–$0001`とstackの3 byteだけ。

## imageの形式

Flashの`0x100000`に32 byteのheader、`0x100020`からpayload。値はlittle endian。

| offset | 型 | 名前 | 規則 |
|---:|---|---|---|
| 0 | u8[4] | magic | `"K9BT"`（4B 39 42 54） |
| 4 | u8 | format_version | 1 |
| 5 | u8 | header_size | 32 |
| 6 | u8 | flags | 0 |
| 7 | u8 | segment_count | 1 |
| 8 | u16 | load_addr | 下位byteが0（ページ境界） |
| 10 | u16 | entry_addr | `load_addr ≤ entry < load_addr+length` |
| 12 | u32 | length | 256の倍数、256以上0x9D00以下 |
| 16 | u32 | payload_crc32 | payload length byteのCRC |
| 20 | u8[8] | reserved | すべて0 |
| 28 | u32 | header_crc32 | offset 0〜27のCRC |

CRCはCRC-32/ISO-HDLC（zlibの`crc32`と同じ）。load範囲は次のどちらか一方に完全に収める。

| CPU address | 用途 |
|---|---|
| `$0000–$01FF` | zero page・stack。load対象外 |
| `$0200–$9EFF` | load範囲 Lo（最大157ページ） |
| `$9F00–$9F1F` | KAGURAの窓（通常時） |
| `$A000–$FEFF` | load範囲 Hi（最大95ページ） |
| `$FF00–$FFFF` | load対象外。ベクタはアプリケーションの初期化コードが書く |

アプリケーションの初期化コードは、`LDX #$FF / TXS`、`$FFFA–$FFFF`へのベクタ書込み、`CLI`の前のSTATUS.INIT_DONE確認を行う。

検査に1つでも外れると、CPUを起動せずboot errorにする。

| error code | 原因 |
|---:|---|
| 1 | magic不一致 |
| 2 | version・header_size・flags・segment_countの不正 |
| 3 | reserved≠0 |
| 4 | header CRC不一致 |
| 5 | load範囲・lengthの不正 |
| 6 | entryが範囲外 |
| 7 | payload CRC不一致 |
| 8 | Flashの読出し失敗・JEDEC ID異常 |

CRCは転送前の1回目の読出しで検査する。2回目（転送中）の読出し誤りは検出できない。

### imageの作成

```sh
python3 tools/make-boot-image.py program.bin program.k9bt --load 0x0200 --entry 0x0200 --pad
python3 tools/make-boot-image.py build/romless-smoke.k9bt --smoke-loop --load 0x0200 --entry 0x0200
```

`--pad`は最終ページを埋める。`--smoke-loop`は`EA 4C 00 02`（NOP、`JMP $0200`）で始まる256 byteの確認用payloadを作る。`python3 sim/tests/test_boot_image.py`で生成器を検査できる。

### Flashへの書込み

Gowin programmerの操作37（`exFlash Erase,Program,Verify thru GAO-Bridge`）で、通常の`.bin`を`--spiaddr 0x100000`へ書く。照合は操作15（`exFlash Verify in bscan`）で行う（照合範囲はファイル長）。操作39は消去が実行されないため使わない。

## 外部回路（案）

`SEL_FFE0 = (A15..A5 == 11111111111)`、`SEL_9F00 = (A15..A5 == 10011111000)`として:

```text
KAGURA_SEL  = BOOT_MAP ? (SEL_FFE0 & RWB) : SEL_9F00
KAGURA_CS_N = !KAGURA_SEL
SRAM_CS_N   = KAGURA_SEL            // KAGURA選択時はSRAMを選ばない
SRAM_OE_N   = !(PHI2 & RWB)
SRAM_WE_N   = !(PHI2 & !RWB)
```

- KAGURAとSRAMの選択を同じ式の否定にし、1個のPLDで実装して両者が同時にバスを駆動しないようにする。
- 書込みは`BOOT_MAP`に関係なくSRAMへ行く（`$9F00`窓への書込みは通常時だけKAGURA）。
- `BOOT_MAP`はFPGA設定前にlowとなる外付けpull-downを前提にする。RESBの保持回路は[CPUバス](timing.md#irqとcpu-reset)と同じ。

## ピン

| 信号 | pin | 備考 |
|---|---:|---|
| BOOT_MAP | 26 | 出力。外付けpull-down |
| Flash SCLK | 59 | MSPI兼用。`-use_mspi_as_gpio 1`（この構成だけ） |
| Flash CS# | 60 | |
| Flash MOSI | 61 | |
| Flash MISO | 62 | |

FlashのWP/IO2とRESET/IO3はFPGAへ配線されていないので、単線SPIだけを使う。CPUバスのピンは`phase2`と同じ。

## bootprobe

`bootprobe`はCPU・HDMIなしでFlashの読出しとimage検査だけを行い、LEDに結果を出す（点灯=1）。

| LED | 意味 |
|---|---|
| 6 | JEDEC ID = `85 60 16` |
| 5 | imageが有効 |
| 4..1 | error code bit 3..0 |

`magicprobe`はJEDEC IDと`0x100000`の`K9BT`を1文字ずつLEDに出す（LED1..4がK・9・B・T、LED5がJEDEC一致、LED6が読出し完了）。

## 検証

| 試験 | 内容 |
|---|---|
| `tb_flash_reader` | JEDEC ID、`03h`の連続読出し、byte境界でのbackpressure、長さ0の拒否 |
| `tb_flash_reader_timing` | ボードのCLK_DIV=4、MISO応答0/55ns、取込み前後4周期、byte間停止、Low/High/待機中resetからの復帰 |
| `tb_boot_image_check` | header・範囲・entry・CRCの各拒否理由 |
| `tb_boot_window` | スタブ、RESET/BRKベクタ、保護されたデータポートとbackpressure |
| `tb_boot_controller` | JEDEC確認、二重読出し、CRC検査、先読み、ブート窓までの統合 |
| `tb_romless_boot_system` | W65C02Sのスタブ命令モデル、SRAM/decodeモデル、Flashモデルで、全payloadのコピー、entry到達、ポートの消費数、KAGURA/SRAMの排他選択 |
| `test_boot_image.py` | 生成器のCRC、padding、範囲の拒否 |

【実測】`bootprobe`でJEDEC ID `0x856016`、操作37で書いたimageの検査合格、payloadを1 byte壊したimageでerror 7、電源再投入後の再合格を確認した。
