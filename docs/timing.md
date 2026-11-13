# クロック・リセット

clockの生成、reset、CDC、STAの受入条件。

## clock

| domain | 構成 | 備考 |
|---|---|---|
| reference | 基板の27MHz、pin 52 | |
| TMDS serial | video PLL。480p: 27×14/3=126MHz（IDIV 2、FBDIV 13、ODIV 4）、720p: 27×55/4=371.25MHz（IDIV 3、FBDIV 54、ODIV 2、VCO 742.5MHz） | Sipeed公式サンプルと同じ480p設定 |
| pixel | serialのCLKDIV /5 → 25.2MHz / 74.25MHz | serialとは関連clock |
| system | system PLL: 27×2=54MHz | PSRAM版はCLKOUTPを静的位相67.5°（`PSDA_SEL "0011"`、duty 50%）でPSRAM CKに使う |
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
- reset解除後、VRAMとline bankを消去し、pixel側の準備を確認してline 0を描画する。準備ができるとhost版はREADYピンを1にする。

## STA

制約は`boards/tang-nano-9k/*.sdc`。27MHz入力、PLL/CLKDIVの生成clock、RAM・OSER10の関連clock、CDCの例外（同期器の入口だけ）を定義する。

- 必須条件: 全構成でsetup/hold WNS ≥ 0、TNS = 0、未制約の同期経路なし。
- 開発中の下限は全構成でWNS ≥ +0.10ns、目標は+0.20ns。下回る変更は、配置optionの探索だけで済ませず、経路を短くする設計変更を先に検討する。
- `tools/run-baseline.ps1`は+0.10nsを既定のgateとして全構成をビルドし、構成ごとのmanifestを`reports/<revision>/<tool>/<構成>/`へ保存する。
- P&Rの既定は`place_option 1`、`route_option 1`。`qspi`・`qspipsram`系の一部720p・PSRAM構成はroute option 2を使う（`tools/build-nano9k.tcl`）。`demo720`はpacket開始判定とVRAM経路の短縮後、place option 1に戻した。
- reset入力・LED・TMDS出力には外部同期のI/O delayを設定しない（resetは非同期assert、LEDは状態表示、TMDSはOSER10から出力）。SPI/QSPIの入力は同期器の入口までfalse path。
- 合成成功とP&Rのsetup/hold収束は別の証拠として扱う。各構成の最新値は[検証状況](validation-status.md#資源とタイミング)。
