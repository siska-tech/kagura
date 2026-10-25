# PSRAM活用・PCM 2ch追加の検討

2026-10-25。調査対象checkout: `0cee379`。これは設計提案であり、RTL実装・合成・実機試験の結果ではない。PCM 2chは「独立モノラル音源2個を既存6音源に追加し、各音源をL/Rへパンする」と解釈する。HDMIの出力は従来どおり48kHz・16bitステレオ。

## 推奨案

PSRAMをPCMサンプルと将来の画像資産の保存先にし、PCMはBSRAM上の小さな先読みバッファから再生する。初回はsigned 8bit、48kHz固定、ワンショット・ループ・独立L/R gainに限定する。既存pulse 3＋noise 1＋wave 2を維持し、合計8音源にする。

PSRAMからの直接描画やフレームバッファ化は別段階とする。現行rendererの同期RAMアクセスを可変レイテンシのPSRAMへ置き換えるにはキャッシュと描画期限の再設計が必要。容量拡張とBSRAM削減は同義ではなく、今回の案では先読み用BSRAMが増える。

| 用途 | 判断 | 理由 |
|---|---|---|
| PCMサンプル保存 | 最初に採用 | 連続アクセスで先読みしやすく、必要帯域が小さい |
| tile・font・画像資産の保管 | 次段階 | PSRAM→既存VRAM転送なら描画方式を維持できる。転送先は既存VRAM仲裁に従う |
| 長時間ストリーミング | 後続 | ホスト補給期限、リングバッファの所有権・通知が別途必要 |
| 描画VRAMの全面移行・bitmap | 別設計 | ランダムアクセス、帯域保証、ライン期限の再評価が必要 |

## 現状と成立条件

- 音源は`rtl/audio/kagura_audio_synth.sv`、設定は`kagura_audio_registers.sv`。54MHz/1125で48kHz、現行演算は23cycles/sample、設計上限64cycles。メモリ待ちを演算FSMへ入れず、準備済みsampleだけを渡す。
- 既存音声出力がPCMであることと、メモリから任意sampleを読むPCM音源があることは別。現在は後者が未実装。
- [現行記録](validation-status.md)の`d501a1f`測定ではホスト版24/26、デモ25/26 BSRAM。最小setupはqspi +0.142ns、demo720 +0.130ns等。これは今回checkoutの再測定ではない。統合時に新しい基準を取得する。
- `kagura_nano9k_clocks.sv`はvideo/systemでPLLを2個使用済み。PSRAM向けに3個目を追加できない。system用PLLの出力・分周・位相出力を共用できるか、選定IPとデバイスの制約を確認する。周波数や位相は未決定。system54MHzとvideo clockの維持を優先する。
- PSRAMの公称容量は64Mbit＝8MiB。ただし採用controllerで利用可能な容量・接続・アドレス単位を実測するまで、全容量利用可能とは扱わない。

## データ経路と仲裁

`host upload → PSRAM → PCM prefetch → ch別buffer → 8音源mixer → 既存audio transport → HDMI`

PSRAM controllerは要求/応答のwrapperで隔離し、systemと別clockならCDCを明示する。PCMの補給を優先し、ホストread/writeは長さを制限したburstで実行する。両PCMが同時に不足した場合は公平に補給する。平均帯域だけでなく、ホスト転送による最大待ち時間、read/write切替、メモリ待ちを含めた補給期限を保証する。

初期案は1chあたり256byte×2面、2ch合計1024byte。1個のBSRAMに収めることを目標に、read/write portとbank所有権を設計する。既存HDMI用FIFOとは別用途。controller内RAMやCDC FIFOを含めた総増分が1個以内に収まる保証はなく、P&Rで確認する。デモは+1で26/26となるため余裕がなくなる。

256byteを48kHz・8bitで消費する時間は約5.33ms。片面再生中にもう片面を埋める。burstは採用PSRAM/IPの境界・長さ制約に合わせて分割し、256byte連続burstが使えるとは仮定しない。補給完了の設計目標は両ch競合を含め2ms以内とし、初期プリフィル後に再生する。短いループでも途切れないよう、補給時にEND→LOOPの接続を処理する。

| サンプル形式・2音源合計 | payload帯域 | 8MiB全部を使う場合の同時再生時間 |
|---|---:|---:|
| 8bit / 24kHz | 48,000 B/s | 約174.8秒 |
| 8bit / 48kHz（初期案） | 96,000 B/s | 約87.4秒 |
| 16bit / 48kHz（将来） | 192,000 B/s | 約43.7秒 |

時間は両音源が同じ長さを占有する場合の算定で、管理領域や転送overheadを含まない。初期案は事前ロード後の自律再生とし、ホストの常時供給を必須にしない。既存VRAM uploaderの速度をPSRAMへの実効転送速度として流用しない。

## PCM仕様の提案

- sampleはsigned 8bit、48kHz固定。初版では補間・ADPCM・可変ピッチ・逆再生を含めない。将来の24kHz等はsample保持と位相累算で追加し、最大消費速度も仕様化する。
- 各chにSTART、END（排他的）、LOOP、GAIN_L/R、ENABLE、LOOP_ENABLE、RETRIGGERを持たせる。アドレスはbyte単位。`START < END <= 実装容量`、loop時は`START <= LOOP < END`を検査する。
- ワンショットはENDで無音停止しDONEを立てる。RETRIGGERは旧先読みを破棄しSTARTへ戻す。reset後はdisable、buffer無効。再生中領域の書換えは初版では禁止するホスト規約とし、別領域へロードして切り替える。
- START/END/LOOPの変更は停止中またはRETRIGGER付きに限定。gain変更だけなら再生位置を維持する。初期プリフィル完了はREADYで通知し、未準備の開始は拒否する。
- 設定はshadow/snapshot方式。AUDIO_COMMITによるsample境界の原子的反映に合わせるが、PSRAMのプリフィル待ちを既存COMMITへ持ち込まない。先行uploadの完了はPSRAM用FENCEで確認してから準備・開始する。
- 補給失敗時は該当PCM音源を無音停止し、sticky UNDERRUNを通知。復旧は明示RETRIGGER。既存HDMI FIFO_UNDERFLOWとは区別し、他の音源とHDMI sample cadenceは継続する。

8bit×gainの時分割演算を2音源分追加する。8音源のsum範囲は−261120〜259080なので既存signed20bitに収まり、現行master補正回路のhigh部分も−2..1の範囲を維持できる。2個の共有乗算器を使う方針は維持可能と見込むが、mux・state・snapshotを含め合成確認が必要。PCM無効時の既存6音源出力はbit単位で一致させる。MASTER_GAIN初期値32も維持し、全8音源最大gainでは飽和し得ることを仕様化する。

## ABIと変更範囲

公開アドレスや版番号はこの提案では確定しない。既存`00..5F`音源設定と`E0..E2`は維持し、未実装`60..DF`にPCM設定・状態を割り当てる候補とする。24bitアドレス3本と制御を含めるため、既存16byte/chへ無理に詰めず32byte/chを候補にする。PSRAM容量、READY、PCM有無を照会できるCAPS/拡張情報を追加する。

PSRAM upload/readbackには既存host adapterを再利用し、内部に別のaddress/data窓と完了通知を追加する案を優先。VRAMの既存範囲やINVALID_ADDRESS規則は維持する。キューへの受付と実際のメモリwrite完了を区別し、PSRAM FENCE、拒否時のaddress更新、reset・timeout時の応答を定義する。PSRAM未準備でも従来の映像・6音源は使える構成を目指す。

| 対象 | 変更 |
|---|---|
| 新規memory/PCM modules | controller wrapper、arbiter、prefetch、buffer、PCM再生状態 |
| audio synth/registers | 2音源のsample・gain、snapshot、状態通知、8音源mix |
| core/register/ABI定義 | upload/readback、容量・機能照会、FENCEとerror routing |
| board top/clocks/CST/SDC/build | PSRAM端子、clock・CDC制約、IP生成物、機能有無の構成 |
| SDK・asset tools | signed8変換、ロード照合、準備・開始・停止、timeout処理 |
| sim/CI | 可変遅延メモリモデル、PCM整数モデル、HDMI復号、既存回帰 |

## 実装順と採否判定

1. **PSRAM単体評価**: 対象QN88P・EDA版に適合するIPを選ぶ。pin・内部接続・clock・burst・byte mask・再配布条件を確認。全利用領域のaddress pattern、walking bits、ランダムread/write、境界、reset/初期化を検証する。
2. **HDMIと共存評価**: PLL 2個以内で480p/720pとsystem54MHzを維持し、追加BSRAM・Logic・FF・CDC・STAを測定。単体PSRAMが動いてもここを通らなければ採用しない。
3. **PCM単体**: 遅延メモリモデルで2音源、短いループ、同時開始、再trigger、端値、飽和、欠損・timeoutを整数参照モデルと比較。演算64cycles以内と48kHz出力を確認。
4. **統合**: PSRAM upload→readback→READY→COMMIT→再生をSPI/QSPIで縦通し。最大描画負荷とhost転送中も補給期限を満たすことを確認。古い応答が再trigger後のbufferへ混入しないよう世代識別またはdrainを検証する。
5. **受入**: 既存回帰、PCM無効時の音声完全一致、全対象構成P&R/STA、HDMI復号でsample照合、実機の連続再生・reset反復。追加の未制約clock/pathを残さず、既存720p例外も別途明示する。

採用基準はメモリ誤り0、通常負荷でPCM underrun 0、描画期限違反0、BSRAM総数26以内、PLL総数2以内、setup/hold違反0。setup余裕は既存ロードマップに合わせ+0.10ns以上を目標とし、資源が入るだけで完了とはしない。画像資産転送はPCMが安定してから追加する。

## 外部資料と未確定事項

- [Sipeed Tang Nano 9K仕様](https://wiki.sipeed.com/hardware/en/tang/Tang-Nano-9K/Nano-9K): 公称PSRAM 64Mbitを確認。
- [Gowin IPUG943-1.2E](https://www.gowinsemi.com/upload/database_doc/1185/document/60fa7b24b5337.pdf): HS/HS 2CHのport表を確認。2CHのメモリ接続とPCMの音源数は別概念。版・IP variantによりclock/phase portが異なるため、そのまま現行EDAの接続仕様にしない。
- [Gowin資料一覧](https://www.gowinsemi.com/en/document/main/database/?order=ASC&page=2&support_search=PSRAM&type=version): IPUG943 1.5E掲載を確認。今回本文確認したものは旧版1.2E。実装時は対象EDAに付属する文書と生成IPを固定し、UG803・対象メモリ仕様との整合を確認する。

最大周波数、実効帯域、利用可能容量、controller資源量、ライセンス/配布条件は未確定。今回の判断は「PCM用途の要求帯域と既存音源演算幅は小さく、評価する価値がある」であり、Tang Nano 9K上での統合動作保証ではない。

## 実装状況

2026-10-25に最初の実装単位として`rtl/audio/kagura_pcm_prefetch.sv`を追加した。ベンダーIPに依存しない1 outstandingのread要求・応答境界、2chの256byte先読みbuffer、one-shot、loop、公平な補給、明示的なprefetch完了後の開始、underrun・設定・memory error通知を実装している。`tb_pcm_prefetch`では可変応答遅延を与え、範囲拒否、one-shot、loop、memory error、応答停止時のunderrunを検査する。Verilator 5.032の全回帰は、この試験を含む45件が合格した。

このmoduleはまだcore、公開ABI、既存6音源mixer、board topへ接続していない。次は対象EDAで生成したPSRAM controllerを薄いwrapperへ収め、単体メモリ評価とPLL 2個以内でのHDMI共存P&Rを行う。その結果を確定する前に公開レジスタを固定しない。

実装用EDAはライセンス導入済みのGowin V1.9.12.04を候補とする。同版の非deprecated `PSRAM_HS` 2.1はGW1NR-LV9QN88Pの64Mbit内蔵PSRAMを対象に含み、生成テンプレート内に2ch構成を持つ。旧`PSRAM_HS_2CH` 1.0と`PSRAM_HS_2CH_V2` 2.0は同版でもdeprecatedなので採用しない。2ch構成は2本の8bit PSRAMを扱い、各channelのuser data幅は32bitで、`cmd_rdy`、`rd_data_valid`、channel別`init_calib`を持つ。

V1.9.12.04で既存`hdmi`構成の合成・P&R・bitstream生成まで完了し、ツールとライセンスがCLIフローで動くことを確認した。初回smoke buildのhold endpoint 5件は、非同期FIFOのGray pointer第1同期段に新版が独立PLL間のphase関連hold/removalを適用したものだった。既存のsetup側`set_max_delay 10ns`を残し、この第1段だけへ`set_false_path -hold`を追加した結果、V1.9.12.04のhold違反は0件になり、V1.9.11.03でもsetup/hold違反0件を維持した。

新版で残る不合格は480p serializerのOSER10 RESETに対するrecovery −0.041nsで、通常setupの最小値は+2.630ns、holdは+0.536ns。旧版の同じ構成ではrecovery +0.524ns以上だった。720p向け既存例外を480pへ拡張せず、配置・reset経路・新版primitive modelを別途監査するまで基準版を切り替えない。

PCM側のbyte readと`PSRAM_HS`の32bit user portを分離する`rtl/memory/kagura_psram_byte_bridge.sv`を追加した。1 outstanding、`cmd_rdy` backpressure、read dataのbyte lane選択、calibration喪失時のerror完了を実装し、controller addressのshiftは実機確認までparameterとしている。1-word read cacheも追加し、連続PCM readでは通常4 byteあたり1 controller commandに削減する。同一wordのcache hitはcontrollerがbackpressure中でも応答できる。単体試験は4 lane、cache hit時に追加commandがないこと、word-address変換、byte-address時のword整列、受付停止、応答待ち中のcontroller喪失を検査する。

既存`kagura_audio_synth.sv`にはparameterで有効化するPCM 2ch演算を追加した。PCM sampleはsigned 8bit、gain/enableは既存設定と同じsample境界snapshotとし、既存の共有2乗算器で8音源を29cycles/sampleで処理する。PCM有効時の独立L/R gain、snapshot、live sample、正負飽和を整数モデルと照合した。PCM無効時は既存6音源の34770 samplesが従来モデルと一致し、23cycles/sampleを維持した。core側はまだPCMを0へ固定しており、公開レジスタとprefetchとの接続は未実装である。

prefetchとmixerを48kHz `sample_boundary`で接続する縦通し試験も追加した。この試験により、one-shotの最終sampleがEND到達直後のsystem clockで消える問題を検出し、sample出力を次の`sample_tick`まで保持するよう修正した。可変レイテンシmemory modelから4個のsigned sampleを順番どおり左右へ出力し、one-shot完了とunderrunなしを確認した。

prefetchには実装容量の上限検査とparameter指定の応答timeoutも追加した。timeout時は対象channelを無効化して`memory_error`を通知するが、未回収requestはそのままdrain状態に置き、遅延応答をbufferへ書かずに破棄するまで再設定を受け付けない。これによりtimeout後の再設定へ古い応答が混入しない。単体試験では初期prefill timeout、遅延応答破棄、buffer count不変、drain後にSTARTから要求を再開することを確認した。timeout値はcontrollerの最大応答時間測定後にboard構成で設定し、既定値0では無効とする。

system clockとPSRAM user clockが異なる場合に備え、1-outstandingの`kagura_psram_read_cdc.sv`も追加した。system側でaddressを応答完了まで保持し、要求toggleを2段同期してmemory側へ渡す。memory側もdata/errorを保持して応答toggleを戻す。単体試験では非同期clock、command backpressure、0～4 cycleの可変応答遅延、error応答、両domain resetを含む302 readを照合した。board統合時には生成controllerの`clk_out`関係を確定し、実階層の同期段へCDC制約を追加する。同一clockで利用できる場合はこのCDCを構成から外せる。

さらに、32bit PSRAM controller modelから`kagura_psram_byte_bridge`、非同期`kagura_psram_read_cdc`、`kagura_pcm_prefetch`、PCM有効の`kagura_audio_synth`までを接続した縦通し試験を追加した。2つの32bit wordに格納した8個のsigned sampleを左右へ順番どおり出力し、one-shot完了、underrun/errorなし、29cycles/sampleを確認した。1-word cacheによりcontroller commandは2回だけで、想定どおり4 byte/commandとなった。残る外部memory側の実装境界は生成`PSRAM_HS`本体、clock/PLL接続、物理端子と制約である。

この縦通しで確定した接続を`kagura_psram_read_path.sv`へまとめた。system側はprefetchと同じbyte request/response、memory側は生成`PSRAM_HS` 1 channelと同じ`cmd`、`cmd_en`、`cmd_rdy`、word address、32bit read data、`rd_data_valid`を持つ。生成IP本体を含めないため、controller設定を確定する前でも上位RTLと試験を維持できる。

PSRAM生成物と設定ファイルはリポジトリへ追加していない。以下の単体評価で候補条件を絞ったが、command受付間隔、address単位、および生成物の配布条件は実機評価と文書確認まで確定しない。

V1.9.12.04同梱テンプレートを用いた合成単体評価では、54MHz、2ch、16byte burst、fixed latency 6の構成が合成を通過した。IP内部の`CLKDIV /2`によりuser clockは27MHzとなるため、既存system 54MHzとの間は追加済みの非同期read mailboxを使う。IPはPLLを追加せず、DLL、CLKDIV、DHCENを各1個使用する。

buffer実装別の単体資源量は次のとおり。これは評価topを含み、既存Kagura本体との統合値ではない。

| PSRAM_HS buffer | Logic | FF | BSRAM | SSRAM |
|---|---:|---:|---:|---:|
| BSRAM | 1517 | 906 | 4 | 0 |
| SSRAM | 1810 | 1040 | 0 | 34 |
| REG | 1871 | 1584 | 0 | 0 |

BSRAM版は既存24/26、デモ25/26へ収まらないため統合候補から外す。初回統合候補はSSRAM版とし、Logic増分、配置配線、54MHz/27MHz CDC、HDMI timingを本体へ接続した状態で判定する。`tools/eval-gowin-psram.ps1`は暗号化されたベンダーsourceをインストール先から`build/`へだけコピーして同じ評価を再現する。IP生成物のリポジトリ収録判断は引き続き配布条件の確認後とする。

生成IPの配布条件に依存しない代替として、自作の`rtl/memory/kagura_hyperram_ctrl.sv`とGowinプリミティブだけの`kagura_hyperram_phy_gowin.sv`も評価した。2026-10-25にB1のdie 0で、54MHz、CK位相67.5°、lat_cycles 14、rd_latency 6の設定により、全4MiBの書込み/読戻しを256 pass連続0 errorで確認した。CK位相の0 error窓は22.5°～112.5°。user側は`PSRAM_HS`と同じ32bit command/response形状なので`kagura_psram_read_path`へ接続できる見込みで、user clockはsystem 54MHzと同一にでき、CDCを省ける可能性がある。評価topは独立rPLLを使っており、PLL 2個以内での共存、die 1、HDMI同時動作、Logic増分(UART memtest全体で1006 LUT、594 FF)の本体統合値は未評価である。詳細と経緯は[rtl/README.md](../rtl/README.md)に記録した。

### 自作controllerからPCMまでの縦通し（2026-10-25）

生成IP形状の応答モデルに加え、実際の `kagura_hyperram_ctrl` → `kagura_psram_read_path`（byte cache + CDC）→ `kagura_pcm_prefetch` → `kagura_audio_synth` を接続する `tb_hyperram_pcm_chain` を追加した。controllerは実機で確定したlat_cycles=14、rd_latency=6、54MHzを使用する。起動時CR0設定の後、controller経由で2 wordを書き込み、交互のbyte maskで一部を更新してから読出しへ切り替える。8個のsigned sampleが左右出力と一致し、read commandは2回、演算は29cycles/sample、one-shot完了、underrun/errorなしを検査する。

メモリモデルはCAを独立に復号し、write dataとRWDS maskを格納するbyte-pair境界のモデルである。期待sampleはモデルの内容から生成せず固定値として比較するため、address/lane変換や部分writeの不一致を検出できる。system/memory clockは同周波数で位相をずらし、既存CDCを残した接続を検証する。これは1ch・8 sampleの機能試験であり、2ch連続補充の帯域保証、cache保持中のuploadとの仲裁、Gowin PHYの端子タイミングや実機部分writeの確認ではない。

本体の公開ABI・board topへの接続は引き続き未実装。次の実機段階はsystem PLLの位相出力共用とHDMI同時動作の評価で、PLL数・資源量・STA・UART結果を確認する。

検証結果: Verilator 5.032の全53件が合格（追加した縦通し試験を含む）。新規試験のビルド警告0、最終sample後の無音も確認した。ログは `build/hyperram-pcm-regression.log`、一覧は `build/verilator/summary.tsv`。この作業ではGowin合成・実機書込みは実施していない。

### system PLL共用でのHDMI共存評価（2026-10-25）

`kagura_nano9k_clocks`に既定無効の`PSRAM_CK_ENABLE`と`psram_ck`出力を追加した。有効時は既存system PLLのCLKOUTをsystem/memory 54MHzで共用し、CLKOUTPをPSDA=3、DUTYDA=11（67.5°、50% duty）でPSRAM CKへ接続する。PLL追加はない。既存topは追加出力を未接続にして従来設定を維持する。

実機確認済みのUART memtestを外部clock入力の`kagura_hyperram_memtest`へ分離し、従来の`kagura_hyperram_diag_top`と新しい`kagura_hyperram_hdmi_top`で共用する。新topはdie 0全4MiBの連続write/readと、HDMIカラーバー・48kHzテスト音を同時に動かす。PCM再生や本体rendererを含む統合ではない。

**位相制約の修正**: 動的PLLのPSDA定数はSTAへ自動反映されず、単なる`-multiply_by 2`ではCLKOUTPが0°として検査されていた。Gowin付属SUG940-2.0.5Eの`create_generated_clock -phase`に従い、`hyperram-hdmi.sdc`で67.5°を明示した。最終レポートのPSRAM clockはperiod 18.518ns、rise 3.472ns、fall 12.731ns。これにより720pのplace_option 1でCK enable→CK# ODDRのsetup −0.443nsを検出した。制約を緩めずplace_option 0へ変更し解消した。480pはplace_option 1、両構成ともroute_option 1を標準とする。

Gowin V1.9.12.04の合成・P&R・bitstream生成結果（評価top全体）:

| 構成 | Logic | Register | BSRAM | rPLL | 最悪setup | 最悪hold | setup/hold違反 |
|---|---:|---:|---:|---:|---:|---:|---:|
| PSRAM + HDMI 480p | 1645 | 1008 | 0 | 2/2 | +0.687ns | +0.539ns | 0 / 0 |
| PSRAM + HDMI 720p | 1668 | 1010 | 0 | 2/2 | +0.799ns | +0.536ns | 0 / 0 |

480pの最悪recoveryは+0.090ns、removalは+0.751ns。720pは既存`phase1-720p.sdc`のOSER10 reset例外を引き継ぎ、それ以外のrecovery/removalは+10.148ns/+0.545ns。外部PSRAMのDQ/RWDS入出力遅延を含む完全なメモリinterface STAではなく、内部のclock間経路と実機memtestを組み合わせた評価である。

互換性確認として、共通化後の単体diagは再びbitstream生成まで完了した。PSRAM clock無効の既存`hdmi`も再ビルドし、従来記録と同じ通常setup +2.630ns、hold +0.536ns、OSER10 reset recovery −0.041nsが再現した。この既知の基準構成の未解決項目を、今回の共存topの合格で解消した扱いにはしない。

再現手順は、`tools/prepare-hdmi-stream.py`で派生ソースを用意した後、別々のbuildディレクトリでGowinへ`tools/build-gowin-hyperram-hdmi.tcl 480`または`720`を渡す。今回の出力先は`build/hyperram-hdmi480`、`build/hyperram-hdmi720`。SRAM書込み後に以下でUARTの連続pass・phase・rd_latency・error数を検証できる（Flashは書き換えない）。

```powershell
powershell -ExecutionPolicy Bypass -File tools/read-hyperram-uart.ps1 -Port COM8 -Passes 64 -LogPath build/hyperram-uart.log
```

受信ツールは115200 8N1、phase 3、rd_latency 6の固定設定を対象とし、最初の途中行を除いて不正な行・pass番号の欠落・メモリエラー・timeoutを失敗にする。phase掃引用ではない。

実機結果: B1（chip ID `0x1100481B`）へ各bitstreamをSRAM一時書込みし、COM8/115200 8N1で確認した。480pは16 passの初回確認に加えて`0012..0051`の64連続pass、720pは`0002..0041`の64連続passがすべて`E 00000000`。各64 passは4MiB全域へ256MiBを書込み、同量を読戻したことに相当する。両モードのカラーバー映像・テスト音はユーザーが正常と確認した。programmerの`--run 4`は両方とも終了code 0で`Finished`、今回のログに`Verify Failed`はなかった。過去の照合失敗の原因が解消したと一般化はしない。

証跡は各buildディレクトリの`programmer.log`、`uart64.log`、`timing-status.json`、`evidence.json`。現在B1のSRAMは720p共存評価版で、内蔵Flashは未変更。長時間・温度/電源変動・die 1・部分write・本体renderer負荷・PCM実機再生は引き続き未評価。次はこのclock構成を用いた実機PCM read path接続、または本体rendererを加えた資源/STA評価へ進める。

### 実機PCM read path（2026-10-25）

`kagura_hyperram_pcm_source`（評価専用）は、起動時に自作controllerで2領域へpatternをuploadし、`kagura_psram_read_path`→`kagura_pcm_prefetch`→`kagura_audio_synth`（PCM有効）で2chをloop再生する。ch0はbyte 0x000101〜0x000301の513 byte、ch1は0x3FFC03〜0x3FFE01の511 byteで、どちらもword境界に揃っていない。ch0を左、ch1を右へgain 0x80で出す（左は64 sample周期、右は128 sample周期の鋸歯状波）。PSRAM応答の各byteを受付addressから独立に照合し（D）、mixer出力を整数参照と照合し（M）、1秒ごとのsnapshotをUARTへ出す（`kagura_pcm_uart_status`）。system54とPSRAM CK 67.5°は既存system PLLを共用する。公開ABI・host upload・本体rendererは含まない。

Verilator: 全54件合格。`tb_hyperram_pcm_source`はCAを独立にdecodeするmemory modelで1,250 sampleを照合し、memoryを意図的に壊すとD/Mの両方が検出し、reset後に再uploadして復帰することを確認する。

Gowin V1.9.12.04（`tools/build-gowin-hyperram-hdmi.tcl 480|720 pcm`、出力`build/hyperram-pcm480`・`build/hyperram-pcm720`）:

| 構成 | Logic | Register | rPLL | 最悪setup | 最悪hold | recovery | removal |
|---|---:|---:|---:|---:|---:|---:|---:|
| PCM + HDMI 480p | 2665 | 1690 | 2/2 | +1.228ns | +0.542ns | +0.090ns | +0.539ns |
| PCM + HDMI 720p | 2666 | 1691 | 2/2 | +0.799ns | +0.574ns | +10.474ns | +0.542ns |

setup/hold違反は両構成とも0。480pのrecovery +0.090nsは既存480p serializer resetと同じ経路、720pは既存OSER10 reset例外を引き継ぐ。

実機（B1、SRAM一時書込み、`--run 4`は両方`Verify success`、内蔵Flash未変更）: UART形式は`PCM N <検査sample> R <読出byte> D <byte誤り> M <mixer誤り> F <fault> A <active> H <HDMI FIFO>`。

- 480p: 約10分間の613連続report、20秒の初回確認とも全行`D 00000000 M 00000000 F 00 A 3 H 0`。report間の増分は毎回N +48,000、R +96,000（2ch×48kHz×8bit）。累計30,479,989 sample、60,960,042 byteを照合した。
- 720p: 121連続reportが全行同じく誤り0、増分N +48,000。

証跡は各buildディレクトリの`build.log`、`programmer.log`、`uart.log`（480pは`uart-soak600.log`も）。720p版のカラーバー表示とPCM音声の出力はユーザーが実機で確認した（左右別の周波数の聴き分けは未記録）。未評価: host uploadとの同時仲裁、本体renderer負荷、die 1、長時間・温度/電源変動、部分write。当時B1のSRAMは720p PCM評価版。

### host転送との同時仲裁（2026-10-25）

`rtl/memory/kagura_psram_arbiter.sv`を追加し、PCM read path（p側）とhost upload/readback（h側、valid/ready）を1つの1-outstanding controllerへ仲裁する。通常はPCM優先とし、直前がPCMへのgrantでhostが待っている場合だけhostを1回優先する。read応答は最後にgrantしたreadの側へ返す。評価engineは起動時のuploadをh側経由に変え、再生中はh側から別領域（word 0x40000〜、4096 word）へのwriteとreadbackをback-to-backで流し続ける（最悪のhost負荷）。readbackはseedごとのpatternと照合する（UARTの`W`=host command数、`E`=host誤り）。`L`はPCM byte要求（valid）から応答までの最大cycle数。再生中領域へのhost writeは引き続き規約で禁止し、cacheの一貫性は扱わない。

Verilator: 全55件合格。`tb_psram_arbiter`はランダムな所要時間のcontroller modelでPCM 5,802 read、host 3,121 read/3,173 write（mask付き含む）を照合し、最大待ちはPCM 31、host 61 cycleだった（いずれも相手の約1 commandが上限）。`tb_hyperram_pcm_source`はhost 58,434 command中に1,250 sampleを照合し、PCMの最大待ちは57 cycle。host領域の破損はhost側だけで検出され、PCM側の照合へ漏れないことも確認した。

**PHY修正**: 評価logicの増加により、480pでCK enable最終段（system54 FF）→CK# ODDR（psram54、67.5°で予算3.472ns）がsetup −0.234nsになった。最終段を`clk_ck`側のFFへ移し、短い跨ぎをfabric FF同士、ODDRへの経路を1周期にした。CKの出力timingは変えていない。

| 構成 | Logic | Register | rPLL | 最悪setup | 最悪hold | recovery | removal |
|---|---:|---:|---:|---:|---:|---:|---:|
| PCM+host+HDMI 480p | 3263 | 1967 | 2/2 | +1.598ns | +0.542ns | +0.090ns | +0.542ns |
| PCM+host+HDMI 720p | 3352 | 1968 | 2/2 | +0.719ns | +0.545ns | +9.784ns | +0.539ns |

最悪setupはどちらも新しいsystem54→psram54のFF間経路。720pはplace_option 0のまま。

実機（B1、SRAM一時書込み、両方`Verify success`、内蔵Flash未変更、出力`build/hyperram-pcmhost480`・`build/hyperram-pcmhost720`）:

- 480p: 60秒の初回確認と約10分の620連続reportが全行`D/M/E 0、F 00、A 3、H 0、L 0039`。hostは毎秒約2.24M command（4 byte/command、write+readbackで約8.9MB/s）。soak終了時点の累計はhost 1,527,205,591 command（0x5B074ED7）、PCM 32,735,989 sample。
- 720p: 120連続reportが全行同じく誤り0、L 0039。

PCMの最大待ち57 cycle（約1.06µs）は、256 byte bufferの補充期限（2ms目標）に対して十分小さい。未評価: 本体renderer負荷、実際のhost interface（SPI/QSPI）からのupload、die 1、長時間・温度/電源変動、部分write、公開ABI（いずれも本体統合は次節）。

### 公開ABI 0.4と本体統合（2026-10-25）

公開仕様は[register-map.md](register-map.md)の「ABI 0.4」、[audio-spec.md](audio-spec.md)の「PCM音源」、[memory-map.md](memory-map.md)のPSRAM領域。定義は`spec/registers.json`から生成し、`tools/gen-registers.ps1 -Check`で文書の表と一致を検査する。

- PSRAMは24bit address空間の400000–7FFFFFへ置き、既存のVRAM_WRITE/READ_REQUEST/FILLとqueue・FENCEをそのまま使う。追加の窓レジスタは作らず、既存uploader（Picoの`kh_vram_write`）が変更なしで使える。byte writeは32bit wordの1 lane＋RWDS maskで、実機でも隣接byteを壊さない（下記の照合で確認）。
- PCM 2chはaudio index 60..9F。START/END/LOOPはPREPAREで取込み、GAIN/ENABLEはAUDIO_COMMITのsample境界で反映する。提案時の「未準備の開始は拒否」は採らず、READYでないchは開始しないだけにした。one-shot終了後もENABLE=1のまま他の音源をAUDIO_COMMITできるようにするため。
- 先読みbufferは提案の256 byte×2面から各ch 32 byteに減らした。host転送が連続する最悪条件でも応答待ちが57 cycleだったため。BSRAMは増えずSSRAM（RAM16）に載る。
- 統合中の修正: (1) 一時停止のsample境界で1 sample消費して捨てていた問題。停止と同じtickでは消費しないようにした。(2) PREPARE直後のSTATUS readが旧READYを返し得る問題。RS_*と同様に、PCM_CMDのwrite後は反映まで次のregister要求を止める。(3) 74%利用率でのsetup違反3経路を構造で解消した（PCM_CMD pulseのregister化、PSRAM offset変換のregister化、prefetchの空き判定からadderを除去しEND−1を保持）。
- buildは`tools/build-nano9k.tcl spipsram|qspipsram[720]`（出力`kagura_spi_psram`/`kagura_qspi_psram`）。CAPS b3のないhost buildではPSRAM端子をidle（CS# high、RESET# low）に固定する。

Gowin V1.9.11.03（Education）の評価:

| 構成 | Logic | Register | BSRAM | rPLL | 最悪setup | 最悪hold | recovery | removal |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| qspipsram 480p | 6309 | 4533 | 24/26 | 2/2 | +0.100ns | +0.552ns | +0.541ns | +0.793ns |
| qspipsram 720p | 6351 | 4678 | 24/26 | 2/2 | +0.044ns | +0.555ns | +7.498ns | +0.569ns |

480pの最悪setupは既存のraster scroll register経路で、目標+0.10nsに一致する。720pの最悪setupは既存の上流`packet_assembler`（pixel74）経路で違反ではないが、目標+0.10nsに届かない。place_option 0では逆にprefetch経路が−0.073nsになったため、既定のoption 1を採る。720pの余裕改善は残課題。

Verilator: 新規`tb_psram_core`（公開register経由のABI 0.4全体）を含む全56件が合格。ABI_MINORを固定値で照合していた既存試験4件は4へ更新した。

実機（B1、`kagura_qspi_psram.fs`をSRAMへ一時書込み、`--run 4`は`Verify success`、内蔵Flash未変更。Pico H1、QSPI、SCK 2.5MHz。ログは`build/nano9k-qspipsram/pico-results.log`）:

- `info`: ID 4B 39、ABI 0.4、CAPS 0x5B。
- `diag`: 既存の全11項目がPASS（VRAM、FILL/FENCE、sprite COMMIT、wave-swap、6音源、IRQ、BUSY、errors）。PSRAM版でも既存機能は退行していない。
- `psram`: 乱数位置0x67FF7Bの2048 byteが0 mismatch。upload＋FENCEは877KB/sで、VRAM（911KB/s）と同等。
- `pcm`: 2秒のloopメロディ（PCM 0）と150msのドラム（PCM 1、one-shot）を、0.5秒ごとにPREPARE＋AUDIO_COMMITで61回再発音した。446,543回のstatus pollの間、UNDERRUN・CONFIG_ERROR・MEMORY_ERROR・メロディ停止・ERROR_CODEはすべて0。HDMI音声もユーザーが実機で確認した。upload表示の37KB/sはPico側の浮動小数sample生成が律速で、転送速度ではない。

未評価: 720p版の実機、spi（1 lane）版、長時間連続再生、die 1、温度/電源変動。
