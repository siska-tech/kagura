# クロック・リセット・CPUバス

clockの生成、reset、CDC、W65C02Sバスのタイミング、STAの受入条件。

## clock

| domain | 構成 | 備考 |
|---|---|---|
| reference | 基板の27MHz、pin 52 | |
| TMDS serial | video PLL。480p: 27×14/3=126MHz（IDIV 2、FBDIV 13、ODIV 4）、720p: 27×55/4=371.25MHz（IDIV 3、FBDIV 54、ODIV 2、VCO 742.5MHz） | Sipeed公式サンプルと同じ480p設定 |
| pixel | serialのCLKDIV /5 → 25.2MHz / 74.25MHz | serialとは関連clock |
| system | system PLL: 27×2=54MHz | PSRAM版はCLKOUTPを静的位相67.5°（`PSDA_SEL "0011"`、duty 50%）でPSRAM CKに使う |
| CPU | systemの16分周 → 3.375MHz | PHI2はFPGAのregister出力 |
| 音声 | systemの1125分周のclock enable → 48kHz | 独立clockは作らない |

PLLは2個とも使用済み。pixelとserialは関連clockとして解析し、false pathにしない。systemとpixelは同じ発振器から作るが、位相関係を仮定せずCDCとして扱う。音声と映像の平均周波数比は共通のreferenceで固定され、system側の48kHz sample生成とpixel側の48kHz tickは位相が違っても長期的に一致する。

## CDC

| 経路 | 方式 | 安全条件 |
|---|---|---|
| pixel→system ライン要求 | req toggle＋保持payload {line, bank} | 次の要求まで上書きしない（1論理ライン間隔） |
| system→pixel ライン完了 | done toggle＋保持tag | tagが一致したときだけbankを交換する |
| pixel→system VBlank・underrun | event toggle | 最短間隔（1フレーム・1ライン）は同期遅延より十分長い |
| system→pixel memory ready | 2段同期のlevel | systemだけのresetでは、pixel側の読出し停止を確認してからline bankを消去する |
| system→pixel 音声sample | 深さ16の非同期FIFO、Gray pointer | L/Rを32bitで一度に書く。pointer公開後に読む |
| pixel→system 音声underflow・mute | toggle・levelの2段同期 | |

Gray pointerの第一同期段にはmax-delayを設定し、bus全体を一括false pathにしない。多bitのデータは2FFで独立に同期せず、toggleが渡るまで保持するか、FIFOのpointer公開の順序で守る。

## reset

- 外部reset（S2、pin 4、押下でlow）またはいずれかのPLLのlock喪失で、chip GSRを直ちにassertする。GSRの入力は`reset_n && pixel_lock && system_lock`で、fabric FFを通さない（GSRは全fabric FFをINITへ保持するので、解除源にfabric同期器を使うと自己lockする）。
- 両PLLがlockするとGSRを解除し、pixel/systemの各domainが4段の同期器でresetを解除する。
- 4個のOSER10は`GSREN=true`、local RESETは0固定で、GSRの解除で4 lane同時に動き出す。
- reset解除後: VRAMとline bankの消去 → pixel側の準備の確認 → line 0の描画 → host版はREADYピンを1、W65C02S版はPHI2を8周期以上出してからPHI2 lowの位相でRESBを解除する。

## W65C02Sバス

【設計】W65C02S 3.3V列の主な条件: cycle ≥125ns、PHI2 high ≥62ns/low ≥63ns、address setup 最大40ns、write data delay 最大40ns、read data setup ≥15ns・hold ≥10ns、write hold ≥10ns（WDCデータシート 表6-3/図6-3）。

本設計ではTsys=18.5185ns、PHI2の半周期8Tsys=148.1ns、周期16Tsys=296.3ns。adapterはすべてsystem clockで動き、PHI2の位相（system立上りを0..15で数える）で次を行う。

| phase | 動作 |
|---:|---|
| 0 | PHI2立下り。前のread cycleの出力データとOEを保持 |
| 1 | 18.5ns後にOEを解除（read hold 10nsを外部のskew込みで確保） |
| 3 | 外部/IRQ出力を更新（PHI2 low、CPUのsetup/hold窓の外） |
| 6 | 111.1ns後にA[4:0]・/CS・RWBを取り込む。readはここで内部要求 |
| 8 | PHI2立上り。選択されたreadだけデータの駆動を始める（未選択・writeはHi-Z） |
| 10 | read応答を遅くともここでデータregisterへ格納 |
| 13 | PHI2立上りから92.6ns後にwrite dataを1回だけ取り込み、write要求を出す |
| 15 | write応答とerrorの確定 |

- address安定（最大40ns）＋外部decode＋配線＋FPGA入力setupを111ns以内に、write data（最大40ns）＋配線＋setupを92.6ns以内に収める。readはphase 10から立下りまでの111.1nsから出力遅延・配線・15nsのsetupを引いた余裕になる。満たせない配線ではCPU分周を落とす。
- OEを単純に`CS && RWB && PHI2`で作ると立下り直後のholdを失う可能性があるため、cycle stateから作りphase 1まで保持する。外部RAM/ROMはPHI2 lowで出力しないようにdecode/OEを作り、この18.5nsの延長と競合させない。
- /CSが複数のsystem cycleにわたってlowでも、1 CPU cycleを1要求として数える。
- I/O範囲は通常のload/storeだけで操作する。RMW命令、indexed addressingのdummy read、page境界を跨ぐI/O読出しで副作用（READ_RESULTの消費など）を起こさないようにドライバを書く。
- RDYは使わない。queueの空きはFIFO_STATUSで確認し、満杯時の書込みは拒否してsticky errorを残す。割込みhandlerはドライバの使うindex・addressを無断で変えない。

### IRQとCPU reset

- /IRQは`|(IRQ_STATUS & IRQ_ENABLE)`のlevelで、0またはHi-Z（open drain相当）。外部に3.3Vのpull-upが要る。
- FPGAは設定前にCPUを能動的にresetできない。キャリア基板にpull-down付きのrelease信号とreset supervisor／gateを置き、FPGA未設定・電源不安定のときRESBが必ずlowになる回路にする。FPGAの出力だけに頼らない。
- 外部reset・PLLのunlockでは直ちにCPU resetをassertし、データのOEを切り、映像を黒、音声を無音にする。回復時は上記の起動手順をやり直す。

W65C02S版のピンは[ボード資料](../boards/tang-nano-9k/README.md#cpu接続)。

## STA

制約は`boards/tang-nano-9k/*.sdc`。27MHz入力、PLL/CLKDIVの生成clock、PHI2出力とのI/O delay、RAM・OSER10の関連clock、CDCの例外（同期器の入口だけ）を定義する。

- 必須条件: 全構成でsetup/hold WNS ≥ 0、TNS = 0、未制約の同期経路なし。
- 開発中の下限は全構成でWNS ≥ +0.10ns、目標は+0.20ns。下回る変更は、配置optionの探索だけで済ませず、経路を短くする設計変更を先に検討する。
- `tools/run-baseline.ps1`は+0.10nsを既定のgateとして全構成をビルドし、構成ごとのmanifestを`reports/<revision>/<tool>/<構成>/`へ保存する。
- P&Rの既定は`place_option 1`、`route_option 1`。`phase2boot720`はplace option 0、`phase2boot720`・`qspipsram720`・`spipsram`はroute option 2を使う（`tools/build-nano9k.tcl`）。`demo720`はpacket開始判定とVRAM経路の短縮後、place option 1に戻した。
- reset入力・LED・TMDS出力には外部同期のI/O delayを設定しない（resetは非同期assert、LEDは状態表示、TMDSはOSER10から出力）。SPI/QSPIの入力は同期器の入口までfalse path。
- boot用Flash MISOは同期器の入口ではなく、SCLK立下りから4 system周期後に取り込む。次の立下りも取込みの4周期後なので、受信2レジスタに限定したsetup=4／hold=7で関係を+4T／−4Tとする。`check-nano9k-timing.ps1`は全経路のSTAに加えて対象2個とエッジ関係を検査する。ボードの分周値4とテストの一致は`check-design.ps1`で確認する。[監査と検証結果](boot-sta-audit.md)も参照。
- 合成成功とP&Rのsetup/hold収束は別の証拠として扱う。各構成の最新値は[検証状況](validation-status.md#資源とタイミング)。
