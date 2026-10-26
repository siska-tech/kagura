# ホストインターフェース: SPI / QSPI

W65C02Sのパラレルバスの代わりに、32 byteのレジスタ窓をSPI（1bit）またはQSPI（4bit）で操作する。ホストはRP2040/RP2350などのMCUを想定し、QSPIはPIOでの駆動を前提にする。`kagura_spi_adapter`（`LANES=1`/`4`）が[CPU非依存の`req/rsp`](architecture.md#cpu非依存インターフェース)へ変換するので、レジスタABI・queue・VRAM以降はW65C02S版と同じである。

- 構成`spi`・`qspi`・`spipsram`・`qspipsram`（とその`720`版）で使う。W65C02S adapterとは同じピンを共有するため、bitstreamで選ぶ。
- 参照実装はRaspberry Pi Pico用の[host firmware](../software/pico/README.md)。

## ピン

| 信号 | pin | 方向 | 備考 |
|---|---:|---|---|
| SCK | 35 | in | pull-down |
| /CS | 42 | in | pull-up（ホストなしで非選択） |
| IO0 (MOSI) | 28 | in、QSPIはinout | |
| IO1 (MISO) | 29 | out、QSPIはinout | SPIでは/CS lowの間だけ駆動 |
| IO2 | 30 | QSPIのみinout | SPIでは使わない（Hi-Z） |
| IO3 | 33 | QSPIのみinout | SPIでは使わない（Hi-Z） |
| /IRQ | 49 | open drain | 外部に3.3Vのpull-upが要る |
| BUSY | 26 | out | queueの空きが少ない（下記） |
| READY | 27 | out | VRAM・line bankの初期化と最初のline 0の準備が終わると1 |

すべて3.3VのBank 1/2。pin 36〜39（J5-1〜4、TFカードのSCLK/MOSI/CS/MISO）はFPGAから駆動せずpullなしのHi-Zにしてあり、ホストがTFカードを直接使える。pin 49はSPI LCDのRSと共有するので、SPI LCDは接続しない。READYはCPUのRESBを駆動しない。ホストはREADY=1を待つか、ID0/ID1とSTATUS.INIT_DONEをpollしてから操作する。

## 電気・タイミング

SCK・/CS・IOはsystem 54MHzで2FF同期してオーバーサンプリングする。SPI mode 0（CPOL=0、CPHA=0）、MSB first。

| 記号 | 規定 | 根拠 |
|---|---|---|
| f_SCK | 設計上 ≤ 10MHz、duty 45–55% | 半周期 ≥ 2.7 system cycle |
| t_CSS | /CS立下り→最初のSCK立上り ≥ 200ns | SPIはこの間にFIFO_STATUSを取得する |
| t_CSH | 最後のSCK立下り→/CS立上り ≥ 20ns | |
| t_CSW | /CS high ≥ 200ns | 直前のwrite要求の受付を完了させる |
| t_DIS | /CS立上り→FPGA出力Hi-Z ≤ 100ns | ホストはこの後にIOを駆動する |

FPGAは各SCK立上りを検出した直後に次のbitを出す（立下りではない）。立上りから出力の変化までは37〜55.6ns＋出力遅延で、10MHzでは次の立上りまで約34ns以上のsetup、ホスト側hold ≥ 37nsが残る。入力は立上り後に最初に見えた同期sampleを使うので、ホストは前の立下りから次の立下りまでデータを保持する。

【実測】ブレッドボード配線のPicoでは、SPI/QSPIとも5MHzで全診断に合格し、10MHzでは読戻しにbit化けが出た。この配線での運用値は5MHzとする。simulation（`tb_spi_bus`/`tb_qspi_bus`）では12.5MHzまで合格し、約15MHzで失敗する。

## トランザクション

/CS lowの1区間が1トランザクション。1 byteはSPIで8 SCK、QSPIで2 SCK（上位nibbleが先、IO3がMSB）。

**byte 0（header）**

| bit | 意味 |
|---|---|
| 7 | 1=read、0=write |
| 6 | INC: 1=data byteごとにoffsetを+1（32でwrap）、0=同じoffsetを繰り返す |
| 5 | 予約。1ならトランザクション全体を無視する（要求を出さず、QSPIは駆動しない） |
| 4:0 | レジスタoffset（$9F00窓と同じ） |

SPIではheaderの送信中、MISOに/CS立下り時点の**FIFO_STATUS**（b5:0 空きentry、b7 FULL）を返す。QSPIは返さない（必要ならoffset 0Fをreadする）。

**write**: header後の各byteがそれぞれ1回のwrite要求になる。`header=0x07`（VRAM_WRITE、INC=0）でVRAMへ連続転送できる。最後まで受け取ったbyteだけが要求になる。

**read**: header、**count N**（1..255、0は256）、**dummy 1 byte**、続いてdata N byte。countとdummyはホストが送る（dummyの値は無視）。

- data byte kのレジスタ読出しは、直前のbyte（dummyまたはdata k−1）の最後から2番目のchunkの立上りで発行する（SPIはbit 1、QSPIは上位nibble）。その後に/CSを上げても、READ_RESULTのような副作用のあるレジスタは消費済みになる。
- 読出し要求はちょうどN回。N byteを超えてclockしたbyteは0を返し、要求を出さない（countがないと最終byteの先読みでREAD_RESULTを1回余分に消費するため）。
- QSPI: ホストはcountの最後の立上りの直後の立下りでIOを解放する。FPGAはdummyの最初の立上りを検出してからIOを駆動し、/CS highの検出で解放する。

**中断**: byteの途中で/CSを上げると、そのbyteを捨てて要求を出さない。headerの途中も同じ。

## フロー制御

queue（32 entry）は描画の空き時間にしか消費されない。SPI 10MHzの1 byteは約43 system cycle、QSPI 10MHzは約10.8 cycleで、VRAM_WRITEやFILLを連続投入するとqueueが埋まる。満杯のときの要求はFIFO_FULLとして拒否され、addressは進まない（[レジスタ仕様](register-map.md)）。拒否を避ける手段を2つ用意する。

1. **headerのFIFO_STATUS（SPI）**: 空きentry数以下のqueue消費byte（VRAM_WRITE、READ_REQUEST、COMMAND）だけをそのトランザクションで送る。値は/CS立下り時点の下限。
2. **BUSYピン**: queueの空きが3未満でhigh。ホストはqueueを消費する各data byteの最初のSCK立上りより前にBUSY=0を確認する（PIOでは`wait 0 pin`）。余裕は「直前のbyteが未反映」と「送信中のbyte」の2個に1個のガードを加えた値。

adapter内の要求は1件だけ保持する。前の要求が受理される前に次のbyteが完了した場合と、readのデータが期限に間に合わなかった場合は、adapterのsticky `late`を立てる（LED2に出す。ABIには載せない）。

## ホスト側の注意

- write要求の間隔は、command投入後にレジスタブロックが止まる約7 system cycleより長い必要がある。QSPI 10MHzの10.8 cycleは満たすが余裕は小さい。
- INC=1のreadでREAD_RESULT（09）を跨ぐと結果を消費する。
- VRAMの読出しはREAD_REQUEST→STATUS.READ_READY→READ_RESULTの順。block readはない。
- 転送速度の実測（Pico、5MHz、32KiBのupload＋全域読戻し照合）はSPIで570.2KB/s、QSPIで1,023.1KB/s。PSRAMへのupload＋FENCEはQSPI 2.5MHzで約870KB/s。

## 検証

`tb_spi_bus`/`tb_qspi_bus`（`sim/tests/tb_host_bus.sv`）は実コアとadapterを結合し、ホストモデルからf_SCK=10MHz、最小のt_CSS/t_CSWで次を確認する。

- ID/ABI/CAPSのINC read、レジスタのwrite/read、ランダムな混在とモデル比較
- SPI headerのFIFO_STATUS、count超過分が0で要求を出さないこと
- VRAM連続書込み64 byteの読戻し、長いFILL中のBUSY待ち、短いFILLの連続投入（BUSYの繰返し）でFIFO_FULLなし
- byte途中・header途中の中断、予約bitのheader、要求数の一致
- ホスト側のsetup/hold（5ns/5ns）、QSPIのIO駆動の競合なし、/IRQ、`late`なし

## 今後の候補

- **SCKの直接clock化**: SCKをGCLK（pin 35）からclockとして受けてasync FIFOでsystemへ渡せば、25MHz以上を狙える。CDCとSTA制約が増える。
- **8080型8bitパラレル**: /WR・/RD strobeをオーバーサンプリングする同種のadapterで実現できる。
- **block read・burst write**: 1 byte=1 descriptorの効率はSPIの帯域より低い。必要になればABIの拡張として検討する。
