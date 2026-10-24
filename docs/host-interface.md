# Host Interface: SPI / QSPI(PIO) mode

【設計】W65C02Sパラレルバスの代替として、32byteレジスタ窓をSPI（1bit）またはQSPI（4bit）で操作するホストインターフェース。ホストはRP2040/RP2350等のMCUを想定し、QSPIはPIOでの駆動を前提とする。[architecture.md](architecture.md)のCPU非依存`req/rsp`契約へ変換する別のフロントエンドであり、レジスタABI・コマンドキュー・VRAM以降は変更しない。

## 位置づけ

- 1本の`kagura_spi_adapter`を`LANES=1`（SPI）/`LANES=4`（QSPI）でparameter化する。別ブロックにしない。
- W65C02S adapterとは同じピンを共有するためbitstream単位で選択する。実行時の切替はしない。
- W65C02S実機がなくても、Raspberry Pi Pico等からレジスタ・VRAM・音源を実機試験できることを第一の目的とする。CPU接続試験（Phase 2）の代わりにはならない。

## ピン

W65C02S用の3.3Vピン（[pin-inventory.csv](../boards/tang-nano-9k/pin-inventory.csv)）を流用する。

| 信号 | pin | 旧用途 | 方向 | 備考 |
|---|---:|---|---|---|
| SCK | 35 | D6 | in | GCLKT_4。後続の直接クロック化（後述）の余地を残す |
| /CS | 42 | /CS | in | pull-up |
| IO0 (MOSI) | 28 | D0 | in / QSPIはinout | |
| IO1 (MISO) | 29 | D1 | out / QSPIはinout | SPIでは/CS low中だけ駆動 |
| IO2 | 30 | D2 | QSPIのみinout | SPIでは未使用（Hi-Z） |
| IO3 | 33 | D3 | QSPIのみinout | SPIでは未使用（Hi-Z） |
| /IRQ | 39 | /IRQ | open-drain | 外部3.3V pull-up |
| BUSY | 26 | RDY候補 | out | キュー空き不足（後述） |
| READY | 27 | reset release | out | VRAM/line初期化と最初のline0完了で1 |

READYはCPUのRESBを駆動しない。ホストはREADY=1を待つか、ID0/ID1とSTATUS.INIT_DONEをpollしてから操作する。

## 電気・タイミング

【設計】SCK/CS/IOはsystem 54MHzで2FF同期してオーバーサンプリングする。SPI mode 0（CPOL=0, CPHA=0）、MSB first。

| 記号 | 規定 | 根拠 |
|---|---|---|
| f_SCK | ≤ 10MHz、duty 45–55% | 半周期 ≥ 2.7 system cycles |
| t_CSS | /CS立下り→最初のSCK立上り ≥ 200ns | SPIはこの間にFIFO_STATUSを取得してMISOへ出す |
| t_CSH | 最後のSCK立下り→/CS立上り ≥ 20ns | |
| t_CSW | /CS high時間 ≥ 200ns | 直前の書込み要求の受付を完了させる |
| t_DIS | /CS立上り→FPGA出力Hi-Z ≤ 100ns | ホストはこの後にIOを駆動する |

【算定】FPGAは各SCK立上りを検出した直後に次のbitを出力する（立下りではない）。立上りRからFPGA出力の変化まではR+37〜55.6ns＋出力遅延。10MHzでは次の立上りまで約34ns以上のsetup、ホスト側hold ≥ 37nsが残る。入力は立上り後最初に見えた同期サンプルを採用し、ホストのデータは前の立下りから次の立下りまで安定している必要がある。

【未検証】実機のpad遅延・配線・ホストの入力setupを含む10MHz動作はオシロとPico実機で確認する。不足時はf_SCKを下げる。

## トランザクション

/CS lowの1区間が1トランザクション。1byte = SPIでは8 SCK、QSPIでは2 SCK（上位nibbleが先、IO3=MSB）。

**byte0（header）**

| bit | 意味 |
|---|---|
| 7 | 1=read、0=write |
| 6 | INC: 1=dataごとにoffsetを+1（32でwrap）、0=同じoffsetを繰り返す |
| 5 | 予約。1ならトランザクション全体を無視（要求を出さない、QSPIは駆動しない） |
| 4:0 | レジスタoffset（$9F00窓と同じ） |

SPIではheader送信中のMISOに、/CS立下り時点の**FIFO_STATUS**（b5:0空きentries、b7 FULL）を返す。QSPIでは返さない（必要ならoffset 0Fをreadする）。

**write**: header後の各byteがそれぞれ1回の書込み要求になる。`header=0x07`（VRAM_WRITE、INC=0）でVRAMへ連続転送できる。完了したbyteだけが要求になる。

**read**: header、**count N**（1..255、0は256）、**dummy 1byte**、続いてdata N byte。countとdummyはホストが送る（dummyの値は無視）。

- data byte kのレジスタ読出しは、**直前のbyte（dummyまたはdata k−1）の最後から2番目のchunkの立上り**で発行する。SPIではbit1、QSPIでは上位nibbleの立上り。以後に/CSを上げても、READ_RESULTのように副作用のあるレジスタは消費済みとなる。
- 読出し要求はちょうどN回。N byte目以降に追加でclockしたbyteは0を返し、要求を出さない。countがないと最終byteの先読みでREAD_RESULTを1回余分に消費してしまうため、headerとdataの間にcountを置く。
- QSPI: ホストはcount最後の立上り直後の立下りでIOを解放する。FPGAはdummyの最初の立上りを検出してからIOを駆動し、/CS high検出で解放する。

**中断**: byteの途中で/CSを上げると、そのbyteは捨てて要求を出さない。header途中の中断も同じ。

## フロー制御

コマンドキュー（32 entries）はVRAM描画の空き枠でしか消費されない。SPI 10MHzは1byte=約43 system cycles、QSPI 10MHzは約10.8 cyclesで、VRAM_WRITEやFILLを連続投入するとキューが埋まる。満杯時の受付拒否は従来通りFIFO_FULLのsticky error/IRQ（[register-map.md](register-map.md)）で、addressは進まない。拒否を避ける手段を2つ用意する。

1. **headerのFIFO_STATUS（SPI）**: 空きentries数以下のキュー消費byte（VRAM_WRITE、READ_REQUEST、COMMAND）だけをそのトランザクションで送る。値は/CS立下り時点の下限。
2. **BUSYピン**: `queue_free < 3`でhigh。ホストはキューを消費する各data byteの最初のSCK立上りより前にBUSY=0を確認する。PIOでは`wait 0 pin`で表現できる。マージンは「直前のbyteが未反映」と「送信中のbyte」の2個分に1個のガードを加えた値。【実測】試験ではマージン2で合格、1でFIFO_FULLが発生した。

adapter内部の要求は1件だけ保持する。前の要求が受け付けられないうちに次のbyteが完了した場合と、readデータが期限に間に合わなかった場合は、adapterのsticky `late`を立てる（LEDへ出す。レジスタABIには載せない）。

## 規約上の注意

- 書込み要求の間隔はレジスタブロックの停止（コマンド投入後の約7 system cycles）より長い必要がある。QSPI 10MHzの10.8 cyclesはこれを満たすが余裕は小さい。f_SCKを上げる場合は再評価する。
- RMW命令やindexed dummy readの問題はない。ただしINC=1のreadでREAD_RESULT(09)を跨ぐと結果を消費する。
- VRAMの読出しは従来通りREAD_REQUEST→STATUS.READ_READY→READ_RESULT。ブロックreadは後続。

## 検証

`tb_spi_bus`/`tb_qspi_bus`（[sim/tests/tb_host_bus.sv](../sim/tests/tb_host_bus.sv)）は実コアとadapterを結合し、ホストモデルからf_SCK=10MHz・上記の最小t_CSS/t_CSWで以下を確認する。

- ID/ABI/CAPSのINC read、レジスタwrite/read、ランダム混在とモデル比較
- SPI headerのFIFO_STATUS
- count超過分が0で要求を出さないこと
- VRAM連続書込み64byteの読出し照合、長いFILL中のBUSY待ち、短いFILLの連続投入でBUSYが繰り返し切り替わる状態（約25回待機）でFIFO_FULLなし
- byte途中/header途中の中断、予約bit header、要求数の一致
- ホスト側のsetup/hold（5ns/5ns）、QSPIのIO駆動競合なし、/IRQ、`late`なし

【実測】2026-10-23、Verilator 5.032でSPI/QSPIとも合格。感度確認として、BUSYマージン1ではFIFO_FULL、SCK周期66ns（約15MHz）では読出し値の誤りで失敗し、80ns（12.5MHz）では合格した。10MHz規定に対するシミュレーション上の余裕であり、pad遅延を含む実機の余裕ではない。

```sh
bash tools/test-verilator.sh
```

【実測】Gowin 1.9.11.03 EducationでSPI/QSPI両topのbitstream生成に成功。setup/hold違反0。

| top | Logic | Register | BSRAM | 最小setup slack |
|---|---:|---:|---:|---:|
| SPI | 4376 | 3100 | 24/26 | +0.172ns（register decode） |
| QSPI | 4358 | 3102 | 24/26 | +0.049ns（audio register） |
| 参考: W65C02S top | 4327 | 3067 | 24/26 | — |

上表はadapter導入時の測定。現行値は[M0基準記録](baseline.md)を参照。最小slackの経路はどちらも既存のコア内で、adapterではない。SCK/CS/IOは同期器入口までfalse path、出力のclock-to-outはP&Rのport timingで確認する。Pico W用の診断firmwareとVRAM uploaderは[software/pico](../software/pico/README.md)。実機（Pico接続）試験は未実施。

ボード用topは`boards/tang-nano-9k/kagura_host_top.sv`。`tools/build-nano9k.tcl spi`または`qspi`でビルドする。LANESはビルドディレクトリに生成するpackage `kagura_build_config`で与え（16:9版は`spi720`/`qspi720`）、stream部のinstance名を`kagura_phase1_top`と揃えてphase1.cstの配置制約を共有する。

## 後続

- **SCK直接クロック**: SCKをpin35（GCLK）からクロックとしてIOB FFで受け、async FIFOでsystemへ渡せば25MHz以上が狙える。CDCとSTA制約が増えるため、オーバーサンプリング版の実機合格後に評価する。
- **8080型8bitパラレル**: /WR /RD strobeをオーバーサンプリングする同種のフロントエンドで実現できる。必要になった時点で別parameterまたは別moduleとして追加する。
- **ブロックread / burst VRAM write**: 1byte=1 descriptorの効率はSPI帯域より低い。実測後にコマンド追加を検討する。追加する場合のABI版番号は互換性評価後に決める。
