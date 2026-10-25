# RTL module boundaries

背景VDP・VRAM・sprite・6ch音源をHDMIへ統合し、CPU不要のシューティングデモを実機確認済み。`vdp/kagura_sprite_selector.sv`・`kagura_sprite_row.sv`・`kagura_sprite_renderer.sv`を含む全画素試験にも合格。[検証状況](../docs/validation-status.md)を参照。

`hdmi/kagura_hdmi_stream_eval.sv`に音声FIFO/packet経路を接続し、Gowin用`platform/kagura_gowin_serializer.sv`で出力する。[合成評価条件](../docs/hdmi-synthesis-evaluation.md)を参照。

`audio/kagura_audio_registers.sv`がindexed shadowとAUDIO_COMMIT snapshotを保持し、command engineが先行VRAM操作の完了後に`audio/kagura_audio_synth.sv`へ渡す。次sample境界でwaveのactive/shadow bankと設定を同時に切り替える。demo/CPU topは6ch音源をHDMI FIFOへ接続し、Phase 1 topは固定テスト音を維持する。

`core/kagura_core.sv`はCAPS b3（ABI 0.4、[register-map.md](../docs/register-map.md)）のとき、PSRAM controller、host/PCM arbiter、PCM read path、prefetch、PCM controlを生成し、PHY境界（`psram_*`のbyte組）だけを外へ出す。b3がない構成ではこれらを生成せず、出力は定数、入力は未使用で、6音源・23cycles/sampleの従来動作のままである。command engine（`core/kagura_vram_engine.sv`）は400000–7FFFFFのbyte操作をPSRAM portへ回し、coreはそれを32bit wordの1 byte lane（RWDS mask）へ変換してarbiterのhost側へ渡す。
`audio/kagura_pcm_prefetch.sv`は可変レイテンシreadを各chの先読みbuffer（coreでは32 byte）へ格納する。設定、prefetch完了、再生開始を分離し、one-shot・loop・underrun・容量境界・応答timeoutを扱う。timeout後は遅延応答を破棄してから再設定を許可する。停止と同じsample tickでは消費しないので、一時停止後は途切れなく続きから再生する。
`audio/kagura_pcm_control.sv`は公開PCM_CMD（PREPARE/STOP/CLEAR）とAUDIO_COMMIT境界を、prefetchの設定受付・開始・停止へ変換し、READYとstickyなDONE/UNDERRUN/CONFIG_ERROR/MEMORY_ERRORを保持する。PREPAREの受付でPCM read pathの1-word cacheを捨てる。PCM register（audio index 60..9F）は`audio/kagura_audio_registers.sv`の`PCM`版が持ち、PCM_CMDのwrite後はSTATUSが反映されるまで次のregister要求を止める。
`audio/kagura_audio_synth.sv`は`PCM_ENABLE`時にsigned 8bit PCM 2chを既存6音源の後段で同じ共有乗算器へ通す。PCM gain/enableはAUDIO_COMMIT snapshot、sample値は各48kHz境界の入力を使い、全8音源を29cyclesで処理する。
`memory/kagura_psram_byte_bridge.sv`はPCM側のbyte readを`PSRAM_HS`型の32bit command/responseへ変換する。1-word cacheにより連続readは通常4 byteあたり1 commandとする。controllerのaddress単位は実機確認前のためparameter化し、byte-address時もword境界へ整列する。calibration喪失中は新規要求を止め、処理中の要求をerrorで完了する。
`memory/kagura_psram_read_cdc.sv`はsystem clockとPSRAM user clock間の1-outstanding read mailboxである。要求・応答ごとのtoggleを2段同期し、複数bitのaddress/data/errorはtoggleが渡るまで保持する。board統合時は実階層に対するCDC制約を追加する。
`memory/kagura_psram_read_path.sv`はbyte cacheとCDCをまとめ、system側のbyte request/responseと生成`PSRAM_HS` channel側の32bit command/responseを接続する。物理PSRAM端子、clock生成、calibrationは生成IP側に残す。
`memory/kagura_psram_arbiter.sv`はPCM read path(p側)とhost upload/readback(h側、valid/ready)を1-outstanding controllerへ仲裁する。通常はPCM優先で、直前がPCMへのgrantかつhostが待っている場合だけhostを1回優先するため、どちらの待ちも相手の1 command程度で抑えられる。read応答は最後にgrantしたreadの側へ返す。

`memory/kagura_hyperram_ctrl.sv`はGowin生成IPの代わりとなる、ライセンス依存のないHyperBus型(8bit DDR)PSRAM 1 die用controllerである。user側は`PSRAM_HS`と同じ`cmd`/`cmd_en`/`cmd_rdy`/word address/32bit data/`rd_data_valid`で、`kagura_psram_byte_bridge`へそのまま接続できる。1 commandで1 word(4 byte)を転送し、write時は`data_mask`をRWDSへ出す。リセット後にreset#解除、CR0書込み(固定2x latency)を行い`init_calib`を立てる。`cmd_reg`でregister空間(ID0/ID1/CR0/CR1)のread、およびzero latencyのregister writeも行える。coreはCK 1周期＝DDR 1 byte組で動作し、DDR I/O・CK位相は`phy_*`ポートの先のPHYが担当する。latency・捕捉遅延・CS high時間はparameter/入力で、54MHzの実機値はlat_cycles 14、rd_latency 6である(下記)。`tb_hyperram_ctrl`が独立なCAデコードと全域protocol検査(CS high時間、バス競合、予約bit、mask、register read/write)で検証する。

`memory/kagura_hyperram_phy_gowin.sv`はGowinプリミティブ(`ODDR`/`IDDR`/`IOBUF`)だけで1 dieぶんのCK(差動)、CS#、RESET#、DQ[7:0]、RWDSを駆動するPHYである。CKは`clk`から遅らせた`clk_ck`で出力し、writeデータをCK端の中央へ置く。`clk`側ODDRは入力を次のclk edgeで取り込むが、`clk_ck`側ODDRは同じedgeの直後に新しい値を取り込むため、CK enableを2段(1段目`clk`、2段目`clk_ck`)にしてDQと同じcycleへ揃え、CS#もODDR経由にしてCK pulseを囲む。read捕捉はRWDSを使わず、`clk`でのIDDRと固定`RD_LATENCY`で行う(IDDRとODDRが同じピンバッファを共有するため同一クロックが必須)。RWDSのIDDR出力は診断用に出している。`boards/tang-nano-9k/kagura_hyperram_eval_top.sv`と`tools/eval-gowin-hyperram.tcl`は合成のみの確認用である。

実機bring-up(2026-10-25、Tang Nano 9K B1、die 0、54MHz、Gowin V1.9.12.04)の結果は次のとおり。

- 初版PHY(CK enable 1段、CS#直結)ではCKがDQより1 cycle早く、memoryはCA前のpull-up状態`FF`を先頭byteとして取り込んだ。結果としてwriteを含む全commandがregister readになり、addressに依存しない同じ値が返った。`kagura_hyperram_scope_top.sv`(各transactionのDQ/RWDS IDDR出力をUARTへ出す)で、自分のCA/write dataのloopbackとRWDS read strobeを観測して特定した。
- 修正後、ID0=`005F`、ID1=`000F`、CR0=`8F1F`(固定2x、latency 6)、CR1=`0040`を読み出せた。CR0へ`8F1C`を書いて読み戻せた。memory writeはlat_cycles 14(CA先頭から15個目のCKでdata開始)で先頭wordへ一致し、13以下・15以上ではcycle単位でずれた。readは同じlat_cycles 14、rd_latency 6で取り込める。
- `kagura_hyperram_diag_top.sv`(UART memtest)でdie 0の全1M word(4MiB)をpassごとに異なるpatternで書込み/読戻しした。rd_latency 6は全pass 0 error、5と7は全word不一致。rPLL動的位相でCK位相を22.5°刻みに掃引すると、0 errorは22.5°～112.5°(step 1～5)、135°はbit単位の誤り、0°と157.5°以上は全不一致(157.5°以上は応答なし)だった。既定位相は窓の中央67.5°(`PSDA_SEL "0011"`)とし、この設定で256 pass(約1GiBの書込み/読戻し)連続0 errorを確認した。
- 動的位相ではDUTYDAが立下りの絶対位置となり、PSDA+8を与えないとduty 50%にならない(静的`DUTYDA_SEL "1000"`はduty比として働く)。
- 続く共存評価ではsystem PLLのCLKOUTPを共用し、HDMI 480p/720pのカラーバー・音声と同時に各64連続pass（全4MiB、256MiB書込み＋同量読戻し）0 errorを確認。両モードの映像・音声もユーザーが確認した。PLLは2/2個。67.5°をSDCへ明示したSTAでsetup/hold違反0（720pは既存OSER10 reset例外を維持）。詳細は[PSRAM/PCM記録](../docs/psram-pcm.md)。
- 未確認: die 1、温度・電源変動、54MHz以外、本体rendererとの同時動作、実機での`data_mask`部分write・`kagura_psram_byte_bridge`接続。自作controller→read path→PCM mixerはシミュレーションの縦通しで確認済み。

`kagura_hyperram_test_top.sv`(256 wordのLED試験、lat_cycles 14でrd_latency 4～7を掃引)、`hyperram-test.cst/.sdc`、`tools/build-gowin-hyperram-test.tcl`、診断用`tools/build-gowin-hyperram-diag.tcl`・`tools/build-gowin-hyperram-scope.tcl`(CST/SDCは`hyperram-diag`を共用、UART TXはpin 17)も同じ構成である。

| Directory | 責務 |
|---|---|
| core | register、IRQ、CPU非依存request/response、commit |
| bus | W65C02S・SPI/QSPI adapter、top-level tri-state制御 |
| vdp | tile/sprite、line ownership、2x / 4x scaling |
| audio | phase/noise/wave/mixer、sample enable |
| hdmi | protocol、packet、TMDS、platform非依存 |
| memory | VRAM arbiter、queue、async FIFO契約 |
| platform | Gowin RAM/PLL/CLKDIV/OSER10/reset wrapper |
| boot | SPI Flash readerとROM-less boot controller（段階実装中） |

`core/kagura_abi_pkg.sv`は`tools/gen-registers.ps1`が生成するレジスタ定数packageで、現時点では合成対象topに含めない。レジスタmoduleは独自のdecodeを持ち、`tb_register_abi`が両者を照合する。

規範は[architecture](../docs/architecture.md)、[register ABI 0.2](../docs/register-map.md)。現行構成と実機検証の入口は[README](../README.md)を参照。
