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
- demo sequencerの`req_wdata`を`syn_preserve`でfabricのFFに残した。art ROMのBSRAM出力レジスタへ吸収されると、遅いDOが上記の復号へ直結していた（demo720が+0.010nsへ悪化した原因）。副作用としてart ROMのpROMが2→1個になり、demo/demo720のBSRAMは26→25/26。シミュレーションの結果は同じだが、ROM割付けが変わったため実機でdemo表示を再確認する。

残る経路と次の候補:

- pattern RAM出力 → sprite合成: 16:1のbank選択の直後に`pixels`書込みと最初の画素の可視判定がある。最初の画素の判定を1cycle遅らせる（1 spriteあたり+1cycle、最大16cycles/line）か、pattern出力をregisterで受ける（背景を含め読出しlatencyが変わる）案がある。描画期限（2633 cycles）と参照モデルに影響するため別の変更とする。
- packet_assembler（pixel74）: 上流hdl-utilのBCH/parity経路。[16:9仕様](wide-mode.md)のとおりpipeline化の候補。上流ファイルは無改変で固定しているため、派生ソース生成（`tools/prepare-hdmi-stream.py`）側での対応を検討する。

当面の受入れは「全構成でWNS≥+0.05ns」とし、上の2件の対応後に目標値を見直す。
