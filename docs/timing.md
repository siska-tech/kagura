# Clock, Reset and W65C02S Timing

## クロック計画

| Domain | 構成案 | 状態 |
|---|---|---|
| reference | onboard 27MHz、FPGA pin52 | 公式CSTで確認、実周波数/精度は未測定 |
| TMDS | PLL0: 27×14/3=126MHz、VCO候補504MHz | 公式サンプルIDIV=2/FBDIV=13/ODIV=4と一致 |
| pixel | CLKDIV /5 →25.2MHz | 公式サンプルに同構成 |
| system | PLL1: 27×2=54MHz、VCO候補432MHz | IDIV=0/FBDIV=1/ODIV=8の候補、IP generatorで確認要 |
| CPU | systemの4bit phase counter、/16→3.375MHz | FPGA出力FFを使用、内部RTLをPHI2でclockしない |
| audio | system /1125 clock enable →48kHz | 独立clockを作らずCEとして使用 |

DS117のPLL入力/PFD 3MHz以上、GW1NR-9 VCO 400..1200MHzの範囲に上記算術は入る。ただし許される組合せ・HCLK配線・PLL配置・ジッタはGowin生成/STAで確認する。[DS117 表3-21](https://cdn.gowinsemi.com.cn/DS117E.pdf)、[公式PLL](https://github.com/sipeed/TangNano-9K-example/blob/c3b795799f23de91982be52db4273a8eea100cdb/hdmi/src/gowin_rpll/gowin_rpll.v)。

HDMI pixelとserializerは関連clock。これらをfalse pathにしない。systemとpixelは同じ発振器由来でも独立PLLの位相関係を仮定せずCDCとして扱う。音声と映像の平均周波数比は共通referenceにより固定される。54MHz側のサンプル更新と25.2MHz側の/525 tickは位相が異なるが、ともに48kHz。

## CDC一覧

| 経路 | 方式 | 安全条件 |
|---|---|---|
| pixel→system line request | req/ack toggle＋保持payload | 次要求をack前に上書きしない |
| system→pixel line done | done/ack＋保持tag | bank所有権を含めて確認 |
| pixel→system VBlank/raster | event toggle、必要なlineタグ保持 | 最短間隔1frame/1lineは同期遅延より十分長い |
| system→pixel stereo sample | depth16 async FIFO、Gray pointers | L/Rを32bitで一括、pointer bus skew制約、同時reset |
| lock/external reset | 非同期assert・各domain同期release | reset解除後にdomain readyを交換 |

FIFOのGray同期は制御信号の同期であり、多bit PCM値を独立2FF同期する方法ではない。通常のCDC例外は同期器入口に限定し、Gray転送のmax delay/bus skewも制約する。各domainのresetは同期解除する。

**720p（VIC4）のOSER10 RESETは例外**。lane別FFからOSER10 RESETへの配線がFCLK半周期に収まらないため、[phase1-720p.sdc](../boards/tang-nano-9k/phase1-720p.sdc)でこの経路をfalse pathとし、OSER10での解除はFCLK/PCLKに対して非同期として扱う。FCLK同期器とlane別FFまでの経路は1サイクルで解析する。VIC1ではOSER10 RESETのrecovery/removal検査も維持する。720p版の「STA違反0」は除外経路のタイミング保証を含まない。リセット後のレーン整列は実機確認項目であり、1台での確認と複数sink・長時間試験の残課題は[16:9記録](wide-mode.md)を参照。

【設計】解除順序は、外部`reset_n`またはいずれかのPLL lock解除で即assertし、pixel clockの4段同期器が解除された後、serializer内でFCLKの2段同期器とlane別FFを通して4個のOSER10へ渡す。`tb_serializer_reset`はFCLKに対する入力resetの位相を変え、非同期assert、解除まで3 FCLK立上り、4 lane同時解除を確認する。この試験はFFまでのデジタルな順序だけが対象であり、Gowin OSER10端子のrecovery/removal、配線遅延、電源投入時のPLL挙動はモデル化しない。除外した物理境界は[実機試験表](p1-07-hardware-test.md)の720p reset反復で評価する。

## CPUバスタイミング案

W65C02S 3.3V列: cycle>=125ns、PHI2 high>=62ns/low>=63ns、address setup最大40ns、write data delay最大40ns、read setup>=15ns、read hold>=10ns、write hold>=10ns、control setup>=15ns/hold>=10ns。立上り/立下り<=5ns、表の負荷条件35pFを参照。[W65C02S 表6-3/図6-3](https://www.westerndesigncenter.com/wdc/documentation/w65c02s.pdf)

本設計ではTsys=18.5185ns、半周期8T=148.148ns、周期16T=296.296ns。実遅延を0と見なさず、次のphaseを起点にSTAと測定を行う。

| phase（system立上り） | 動作 |
|---:|---|
| 0 | PHI2 falling。前read cycleの出力データ/OEをラッチで保持 |
| 1 | 18.52ns後、前cycleのOE解除。10ns hold条件を外部clock/data skew込みで確認 |
| 6 | 111.11ns後、A[4:0]/CS/RWBを取り込む。readは即内部要求 |
| 8 | PHI2 rising。選択readのみデータ駆動開始。未選択/書込はHi-Z |
| 10 | read応答を遅くともここまでにdata latchへ格納 |
| 13 | PHI2 risingから92.59ns後、write dataを一度だけ取り込む |
| 14–15 | 内部write応答確定、error更新。次phase0までread data固定 |

アドレス安定まで最大40ns＋外部decode＋配線＋FPGA入力setupを111ns内に収める。writeは40ns＋clock出力/配線/input setupを92.6ns内に収める。readはphase10→fallingまで111.1nsから出力遅延・配線・15ns setupを差し引いた余裕を測る。phase13取り込みが成立しない遅延ならCPU分周を落とす。内部2FF化で全バスを無条件に同期する方式は採らない。

**OEを単純にCS && RWB && PHI2とするとfalling直後に10ns holdを失う可能性がある。** OEはcycle stateから生成してphase1まで保持する。外部RAM/ROM等はPHI2 lowで出力しないようにdecode/OEを設計し、低位相の18.52ns延長と競合させない。CPUが次の書込みでdataを駆動し始めるタイミングもWDCの波形と実測で確認する。競合があれば方向付きトランシーバを用いてbus turnaroundを再設計する。

CPUのI/O範囲は通常のload/storeだけで操作する。RMW命令・indexed dummy read・ページ境界を跨ぐI/O読出しで副作用を起こさないようドライバを定義する。CSがlowの複数system cyclesを複数要求として数えない。

## RDYとIRQ

v0.1はRDYなし。CPUはFIFO空きをpollし、満杯時はアクセスを拒否してsticky ERROR/IRQを残す。受付失敗でaddressを進めない。割り込みハンドラはドライバのindexed register/VRAM addressを無断で変更しない。

将来RDY版はW65C02Sのbidirectional RDY/WAIとの整合、falling前setup、停止中同じwriteの再受付防止を別途設計する。単純なpush-pull HIGH駆動を前提にしない。

IRQは`|(IRQ_STATUS & IRQ_ENABLE)`でlevelを作る。外部線はopen-drain相当（0またはHi-Z）＋3.3V pull-up。IRQ_STATUSはW1C、同cycleの新規イベントを優先して保持。IRQ_ENABLE=0でも要因は記録する。変化がCPUのsetup/hold窓に入らないようPHI2 lowの所定位相（phase3候補）で外部IRQ出力を更新する。

## reset/起動/障害

設定前のFPGAはCPUを能動resetできない。キャリア基板のプルダウン付きrelease信号とreset supervisor/ゲートを用い、FPGA未設定・電源不安定ならCPU RESBが必ずlowになる回路を設ける。FPGA直接出力だけに依存しない。

外部reset/PLL unlock→即assert、全domainのresetを同期release→RAM clear→FIFO empty/ready交換→line0準備→PHI2を少なくとも8周期動かしてからlow位相でCPU RESB release。通常稼働中のresetもFIFO両側・toggle双方を揃える。PLL unlock時はCPU reset、data OE off、映像mute、音声0。回復時は起動シーケンスから再実行する。

## STA受け入れ

27MHz input clock、126MHz/25.2MHz/54MHz generated clocks、PHI2 outputとのI/O delays、RAMとOSER10関連clock、CDC例外を定義。setup/hold WNS>=0、TNS=0、未制約の同期パス0。Fmaxの1数値だけで3domainを評価しない。合成成功とP&Rのsetup/hold収束は別証拠として保存する。

## 余裕の改善記録（M3）

【実測】Gowin Education V1.9.11.03、`tools/run-baseline.ps1`。基準は[M0基準記録](baseline.md)の`9f595f7`、改善後は`443900a`（証拠は`reports/443900a/`、Git管理外）。全11構成でsetup/hold違反endpoint 0、TNS 0。720pのOSER10 RESET除外は上記のまま。

| 構成 | 最小setup slack（9f595f7 → 443900a） | 改善後の最悪経路 |
|---|---:|---|
| phase2 | +0.077 → +0.105ns | 音源レジスタのindex → channel_dataキャッシュ |
| demo | +0.020 → +0.095ns | q_addr → 音源 capture_pending |
| spi | +0.019 → +0.147ns | pattern RAM出力 → sprite合成（visible_q） |
| qspi | +0.072 → +0.063ns | pattern RAM出力 → sprite合成（pixels） |
| phase2720 | +0.058 → +0.111ns | packet_assembler（pixel74、上流hdl-util） |
| demo720 | +0.030 → +0.085ns | packet_assembler（pixel74） |
| spi720 | +0.029 → +0.134ns | packet_assembler（pixel74） |
| qspi720 | +0.095 → +0.099ns | packet_assembler（pixel74） |

hdmi/dvi/hdmi720は変化なし（+5.634/+5.634/+0.391ns）。全構成の最小値は+0.019ns（spi）から+0.063ns（qspi）になった。

変更内容（機能・ABI・応答cycle数は不変）:

- COMMANDのopcodeとREAD_REQUESTの値0判定を、要求の取込み時にflagへ前もって復号する。受付・error判定が高fanoutの`q_wdata`（fanout 54）を再度比較しなくなり、最悪だった`q_wdata`→`capture_pending`/`error_code`経路（論理7段）が消えた。
- FILLの範囲検査を、加算と領域比較の2段に分けた。ADDR/LENGTH書込みとVRAM_WRITE/READのaddress進行の後は、`checks_stale`が次の要求を両段の更新後まで受け付けない。この前提はsimulation専用のassertionと、最大速度で要求を出す`tb_fill_timing`で検査する（3段に遅らせた改変版はassertionで失敗することを確認）。
- demo sequencerの`req_wdata`を`syn_preserve`でfabricのFFに残した。art ROMのBSRAM出力レジスタへ吸収されると、遅いDOが上記の復号へ直結していた（demo720が+0.010nsへ悪化した原因）。副作用としてart ROMのpROMが2→1個になり、demo/demo720のBSRAMは26→25/26。シミュレーションの結果は同じ。ROM割付けの変更後のdemo（480p）の映像は、2026-10-24にTOSHIBA REGZA 32S5で正常表示を確認した（[検証状況](validation-status.md)）。

残る経路と次の候補:

- pattern RAM出力 → sprite合成: 16:1のbank選択の直後に`pixels`書込みと最初の画素の可視判定があった。256スプライト化（ABI 0.5）の際にdemoでこの経路が+0.006nsまで下がったため、最初の画素の判定を`pixels`の登録後の1cycle（`kagura_sprite_row`のFIRST状態）へ移した。1 spriteあたり+1cycle、最大16cycles/lineで、描画期限は2585 cycles。BSRAM出力は`pixels`の取込みだけに使う。
- packet_assembler（pixel74）: 上流hdl-utilのBCH/parity経路。[16:9仕様](wide-mode.md)のとおりpipeline化の候補。上流ファイルは無改変で固定しているため、派生ソース生成（`tools/prepare-hdmi-stream.py`）側での対応を検討する。

当面の受入れは「全構成でWNS≥+0.05ns」とし、上の2件の対応後に目標値を見直す。

### P&R effort固定（後続拡張の余裕）

【実測】`d501a1f`、Gowin Education V1.9.11.03、`tools/run-baseline.ps1`。`place_option 1`と`route_option 1`を全構成の既定値に固定した。RTL・制約・資源使用量は`443900a`から不変。全11構成でsetup/hold違反endpoint 0、TNS 0。証拠は`reports/d501a1f/`（Git管理外）。

| 構成 | 最小setup slack（443900a → d501a1f） |
|---|---:|
| hdmi / dvi | +5.634 → +5.951ns |
| phase2 / phase2720 | +0.105 → +2.079ns / +0.111 → +0.377ns |
| demo / demo720 | +0.095 → +0.634ns / +0.085 → +0.130ns |
| spi / spi720 | +0.147 → +1.608ns / +0.134 → +0.630ns |
| qspi / qspi720 | +0.063 → +0.142ns / +0.099 → +0.192ns |
| hdmi720 | +0.391 → +0.708ns |

全構成の最小値は+0.063nsから+0.130nsへ改善した。最悪経路は構成ごとに移動しており、qspiはregister addressから音源capture、demo720はsequencer counter、その他の720p統合構成は主にpacket assemblerである。単一RTL経路の修正ではなく配置配線探索の改善であり、機能追加後に同じ余裕を保証するものではない。P&R時間は統合構成で増える。

後続拡張では必須条件WNS≥0/TNS=0に加え、全構成WNS≥+0.10nsを開発中の下限、+0.20nsを目標とする。+0.10nsを下回る変更は、経路を短くする設計変更または機能分離を先に検討し、配置optionの再探索だけを恒久対策にしない。demo系はBSRAM 26/26（256スプライト化後の見込み）で空きがないため、BSRAMを使う拡張は別途空きを確保する。

### 256スプライト化後の経路短縮（2026-10-25）

256スプライト化（`cf7f6b0`）のP&Rで、変更していない経路が配置の変動で期限を割った。繰り返し現れた次の4経路を、出力を変えずに短くした。

| 経路 | 変更 |
|---|---|
| packet_assembler（pixel74）counter → BCH parity | `rtl/hdmi/kagura_packet_assembler.sv`に置換。counterで選ぶbit muxをshift registerにし、counterの範囲判定を1cycle先にregisterで作る。`tb_packet_assembler`が原版と毎cycleの出力一致を検査 |
| audio_synth（system54）state → 乗算 → sum | 音源ごとの積をregisterし、次のcycleで加算。1 sampleは23→24 cycles（PCM有効時29→30）、上限1125に対して影響なし |
| audio_transport（pixel74）tick_acc | 定数加算と比較を直列から並列に（`tick_acc < TICK_NUM`を前提に等価） |
| hdmi guard/preamble（pixel74）cy → video_guard | cyの行判定をregisterで受ける。cyは行内で一定で、判定はcx≥frame_width−10でだけ使う |

【実測】Gowin Education V1.9.11.03、`tools/run-baseline.ps1`、最小setup slack（`cf7f6b0` → この変更）。

| 構成 | slack |
|---|---:|
| demo / demo720 | +0.78 → +0.03ns / +0.003 → **−0.69ns** |
| phase2 / phase2720 | +0.58 → +2.29ns / −0.46 → +0.39ns |
| spi / spi720 | +0.47 → +0.91ns / +0.49 → +0.43ns |
| qspi / qspi720 | +0.045 → +0.87ns / +0.46 → +0.008ns |
| phase2boot / phase2boot720 | +0.07 → +0.009ns / −1.22 → +0.096ns |

対象の4経路は元の形では最悪経路から消えたが、分割後の段や別の場所が最悪経路へ移った（phase2720は分割後のaudio product register、phase2boot720は追加した`guard_line`、demo720は`kagura_tmds_channel`の`video_data`→`qm1`、qspi720はaudio_packetsの`cx`判定、phase2bootはregistersの`ext_index`→`rs_table`）。Register数は約+280。単一のP&R結果だけでは配置変動が支配要因とは断定しない。

demo720はsetup違反9 endpointで、pixel74の`video_data`→`qm1`（−0.691ns）だけでなく、system54の`init_done`→OAM address（−0.531ns）、`q_addr`→`error_code`（−0.251ns）等も違反した。phase2boot720の+0.096ns、demoの+0.028ns、qspi720の+0.008ns、phase2bootの+0.009nsも、丸め前の値では開発下限+0.10nsに達していない。この変更はタイミング改善として未受入れであり、実機確認用のdemo720は`cf7f6b0`のbitstream（+0.003ns）を使った（[検証状況](validation-status.md)）。

後続修正では次の経路を構造で短縮した。

- TMDS encoderの入力をregisterで受け、外部`video_data`配線とpopcount/prefix XORを別cycleにした。全lane・全modeで上流encoderの3 pixel遅れと一致することを試験する。
- PSRAM CK enableの第2段を`clk_ck`下降端へ移した。system54立上りから12.731nsを確保しつつ、ODDRが値を取る次の`clk_ck`立上りは従来と同じである。
- EXT_DATAとRS entry選択をPSRAM構成だけ事前register化し、非PSRAM構成へ追加FFを残さない。

Gowin Education V1.9.11.03で監査時の境界構成を再P&Rした結果は次のとおり。すべてsetup/hold違反0で、開発下限+0.10nsを満たした。実機はこの修正版bitstreamでは未確認である。

| 構成 | Logic | Register | BSRAM | 最悪setup | 最悪hold |
|---|---:|---:|---:|---:|---:|
| demo720 | 6871 | 4545 | 26/26 | +0.181ns | +0.563ns |
| phase2boot720 | 5933 | 4533 | 25/26 | +0.683ns | +0.558ns |
| spipsram | 6673 | 5138 | 25/26 | +0.851ns | +0.563ns |
| qspipsram720 | 6649 | 5141 | 25/26 | +0.113ns | +0.555ns |

`tools/run-baseline.ps1`は+0.10nsを既定gateとし、spipsram、qspipsram、qspipsram720も既定対象に含める。dirty buildは差分hashを含む固有directoryへ保存し、manifestへtracked diffと対象sourceのSHA-256を記録するため、同じHEAD上の試行が互いの証跡を上書きしない。
高密度720pのphase2boot720とqspipsram720はroute option 2、demo720は従来どおりplace option 0を使用する。
`tools/test-verilator.sh`は共有build/logへの同時実行をlockで拒否し、並行回帰による実行物・summaryの相互上書きを防ぐ。
