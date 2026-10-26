# PSRAM

CAPS b3版（`spipsram`・`qspipsram`とその`720`版）は、GW1NR-9内蔵PSRAM（64Mbit、2 die）のdie 0（4MiB）をVRAMのaddress 400000–7FFFFFとして公開する。用途はPCM 2chのsample置き場と、COPYによるVRAMへの高速転送の元データである。描画器はPSRAMを直接読まない。die 1は使わず、端子は非選択に固定する。

## 公開の仕様

- VRAM_WRITE・VRAM_READ_REQUEST・FILLの対象。addressとINCの規則、範囲検査、queueでの順序保証はVRAMと同じ（[レジスタ仕様](register-map.md)）。
- COMMAND 05 COPYでPSRAMからVRAM（PSRAM以外の公開領域）へ複写できる。
- PCM音源はPSRAM上のbyte列を再生する（[音源仕様](audio-spec.md#pcm音源caps-b3)）。
- EXT 12 PSRAM_SIZE_LOG2=22、EXT 13 PCM_CHANNELS=2。

### 初期化と一貫性

- 内容は電源投入時に不定で、起動時に消去しない。必要ならFILLで消す。
- PSRAMの初期化（reset解除後、約4096 system cycle≒76µs）はSTATUS.INIT_DONEに含まれない。初期化中はqueue先頭のPSRAM操作だけが待つ。
- PSRAMへのwriteは、controllerへ渡した時点で順序上は完了として扱う。controllerは1件ずつ処理するので、後続のどのPSRAMアクセスよりも先に終わる。FENCEは受理済みのPSRAM操作がすべてcontrollerへ渡るまで待つ。したがって**FENCEの完了後に始まるPSRAMアクセス（READ_REQUEST、COPY、PCMの先読み）は先行writeの結果を読む**。

### COPY

PSRAMのCOPY_SRCから始まるLENGTH byteを、VRAM_ADDRから始まる領域へ連続に複写する。engineはbyteごとにPSRAM read→VRAM writeを行い、host側の1-word cacheにより連続readはおおむね4 byteで1回のPSRAM読出しになる。

【実測】32767 byte（pattern領域の全体に相当）のCOPYはFENCE込みで6.2〜7.0ms（約4.7〜5.3MB/s）。QSPI 2.5MHzでのhostからのupload（約870KB/s）の約5倍で、1フレーム（16.7ms）の半分以下でpattern全体を入れ替えられる。複写中も描画が優先されるので、表示中のpattern・mapへ複写する場合はVRAM_WRITEと同じくtearingに注意する。

## 内部構成

```text
queue (byte op) ─▶ host port (1-word cache + 1-entry slot) ─┐
                                                            ├─▶ arbiter ─▶ HyperRAM controller ─▶ PHY ─▶ PSRAM die 0
PCM prefetch ─▶ read path (byte cache + CDC) ───────────────┘
```

| モジュール | 役割 |
|---|---|
| `kagura_hyperram_ctrl` | HyperBus型（8bit DDR）の1 die controller。1 commandで1 word（4 byte）を転送し、writeは`data_mask`をRWDSへ出す。reset後にRESET#を解除し、CR0へ固定2倍latencyを書いて`init_calib`を立てる |
| `kagura_hyperram_phy_gowin` | `ODDR`/`IDDR`/`IOBUF`だけで差動CK、CS#、RESET#、DQ[7:0]、RWDSを駆動する |
| host port（`kagura_core`内） | queueのbyte操作を32bit wordの1 byte lane（残り3 laneをmask）へ変換。readの直前wordを保持し、writeで無効化する。1段のslotでengineのhandshakeを仲裁器から切り離す |
| `kagura_psram_arbiter` | PCM側とhost側を1-outstandingのcontrollerへ仲裁 |
| `kagura_psram_read_path` | PCM側のbyte要求を32bit commandへ変換（1-word cache）し、CDC mailboxを通す |
| `kagura_pcm_prefetch` / `kagura_pcm_control` | 各ch 32 byteの先読みbuffer、one-shot・loop・underrun・timeout、公開のPREPARE/STOP/CLEARとSTATUS |

### 仲裁

通常はPCMの補充を優先する。直前のgrantがPCMで、hostが待っている場合だけhostを1回優先するので、どちらの待ちも相手の1 command程度に抑えられる。readの応答は最後にgrantしたreadの側へ返す。

【実測】hostがPSRAMを連続で読み書きする最悪条件でも、PCMの応答待ちは最大57 system cycle（約1.06µs）だった。32 byteのbufferが空になるまでの約0.67msに比べて十分小さい。PCMの応答が4096 cycle返らなければ、そのchはMEMORY_ERRORで止まる。

### 物理層の設定

| 項目 | 値 |
|---|---|
| clock | system 54MHz。CKはsystem PLLのCLKOUTP（静的67.5°） |
| latency | `lat_cycles=14`（CAの先頭から15個目のCKでdata開始）、固定2倍latency |
| read捕捉 | RWDSを使わず、`clk`のIDDRで固定`rd_latency=6` |
| CK enable | 2段。1段目は`clk`、2段目は`clk_ck`の下降端。DQと同じcycleにCKを揃え、CS#もODDR経由でCK pulseを囲む |
| 出力 | DQ/RWDSの出力enableはcontrollerの`phy_*_tx`（駆動区間を前後1 cycle広げた窓）をpinごとのregisterで受ける。RESET#もregister出力 |

- 【実測】CKの位相を22.5°刻みで掃引した結果、0 errorの窓は22.5°〜112.5°で、67.5°はその中央。rd_latency 6は全pass 0 error、5と7は全word不一致だった。
- PSRAMのpadへ出る信号はすべてregister（またはIOLOGIC）出力にする。組合せ出力のRESET#は配置によって数nsのglitchを出し、write直後のmemoryをresetして全writeを失わせた。DQ/RWDSの出力enableへのfabric経路はGowinのSTAで解析されないため、TX窓とpinごとのregisterで余裕を持たせている。
- 外部PSRAMのDQ/RWDS入出力遅延を含む完全なinterface STAではない。内部clock間の経路と、実機のmemtest（die 0全域、256 pass≒1GiBの書込み/読戻しで0 error）を組み合わせた評価である。

## debug build

`KAGURA_PSRAM_DEBUG=1`でビルドすると、1 transactionの間のPSRAM端子（IDDRの値と制御信号）を48 cycle記録し、EXT 17/18から読める（ABI外）。Picoのfirmwareでは`pdbg`コマンドでCAやRWDS maskを確認できる。

## 評価用top

PSRAM単体のbring-up用に、board directoryに次のtopがある（本体のbuild構成とは別のscript）。

| top | script | 内容 |
|---|---|---|
| `kagura_hyperram_test_top` | `tools/build-gowin-hyperram-test.tcl` | 256 wordのLED試験、rd_latencyの掃引 |
| `kagura_hyperram_diag_top` | `tools/build-gowin-hyperram-diag.tcl` | die 0全域のUART memtest（pin 17、115200 8N1） |
| `kagura_hyperram_scope_top` | `tools/build-gowin-hyperram-scope.tcl` | 各transactionのDQ/RWDSをUARTへ出す |
| `kagura_hyperram_hdmi_top` | `tools/build-gowin-hyperram-hdmi.tcl 480 memtest`（720も可） | memtestとHDMIカラーバー・テスト音の同時動作 |
| `kagura_hyperram_pcm_top` | `tools/build-gowin-hyperram-hdmi.tcl 480 pcm`（720も可） | host負荷下のPSRAM upload/読出しとPCM 2ch再生、UART状態表示 |

## 未確認の範囲

die 1、温度・電源電圧の変動、54MHz以外のclock、長時間の連続再生（約30分までは確認済み）、外部端子タイミングのSTA。実機での確認記録は[検証状況](validation-status.md)。
