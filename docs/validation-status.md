# 検証状況と既知の制約

> 以下は元の1,024パターン設計の過去の証跡。実験ABI 0.6のP&R/STAは[1,200パターン実装](tile-1200-stage2.md)、実Picoの数値受入は[第3段階](tile-1200-stage3.md)を参照。standalone demoはdeprecated。

2026-10-27時点（`a5a9ca2`に下記のタイミング改善を適用）の検証状況。simulation、P&R/STA、実機確認は別の証拠として扱い、片方の合格をもう片方の代わりにしない。

## 証拠の種類

| 種類 | 内容 | 再現方法 |
|---|---|---|
| simulation | Verilator 5.032で58試験。参照モデルとの全画素・全sample比較、protocol checker、boot MISO保持窓 | `bash tools/test-verilator.sh`（CIでも実行） |
| 設計検査 | BSRAM・cycle予算の算術、レジスタ定義と文書・生成物の一致 | `tools/check-design.ps1`、`tools/gen-registers.ps1 -Check` |
| P&R/STA | Gowin EDAでのbitstream生成とsetup/hold | `tools/run-baseline.ps1`（ローカル。証跡は`reports/`、Git管理外） |
| 実機 | Tang Nano 9K（シルク3674、chip ID `0x1100481B`）1枚、HDMI sink 2機種、Raspberry Pi Pico | 手順は[実機試験](hardware-test.md)、Picoは[firmware](../software/pico/README.md) |

## 機能ごとの状況

| 分野 | simulation | 実機 | 未確認 |
|---|---|---|---|
| HDMI映像・音声（480p/720p） | TMDS・TERC4・BCH・ACR・InfoFrameを復号して照合 | 2機種のsinkで映像・音声 | 複数sink×ケーブルの反復・長時間、電気特性 |
| 背景・sprite（256個、16個/line） | 480p/720pで4フレーム全画素比較、overflow IRQ | デモとPicoのshowcaseで表示 | 256個全体の実機での個別確認 |
| ラスタスクロール | 480p/720pの全画素比較 | 480p/720pで波打つ表示を目視 | — |
| 6ch音源 | 整数モデルと34770 stereo sampleが一致 | 全6音源の同時発音、wave bank交換の読戻し | sample単位の完全性（計測器なし） |
| VRAM・queue・IRQ | byte参照モデル、領域境界、拒否時の副作用、順序 | Picoの`diag`（VRAM照合、FILL/FENCE、IRQ、BUSY） | 長時間の連続更新 |
| SPI/QSPI | 10MHzのモデルでBUSY・中断・競合を検査 | 5MHzで全診断に合格。10MHzは読戻しにbit化け | オシロでの波形・電気的余裕 |
| PSRAM・COPY・PCM | 実controllerとCA復号モデルでABI 0.4を縦通し | memtest 1GiB 0 error、upload/COPY照合、PCM約30分の連続再生でfault 0 | die 1、温度・電圧変動 |
| W65C02Sバス | 要求回数、OE、read setup/hold、IRQ、reset解除をモデル検査 | 未接続 | 実CPU、外部reset保持回路、decode/OE |
| ROM-less boot | Flashモデル＋6502スタブモデルで全payloadのコピーとentry到達 | Flash読出し、image検査、CRC誤りの検出 | 外部decode、実CPUでの起動 |
| reset | 起動時のRAM消去、systemだけのreset | S2 resetからの復帰（デモ・Pico診断） | chip GSR版での多数回の反復 |

### 実機で確認した主な結果

- **デモ**: 480p/720pのシューティング画面と6ch演奏を、S1（MSI MAG 325CQRF-QD）とS2（TOSHIBA REGZA 32S5）で確認。720pではS2 reset後の復帰も確認。
- **Pico（SPI/QSPI、5MHz）**: ID/ABI、register、VRAM 2048 byte照合、FILL/FENCE、sprite移動、6音源、VBLANKの/IRQ、64 FILL＋4096 byteの連続書込みでBUSY待ちありFIFO_FULLなし、header/data途中の中断で副作用なし、S2 reset・USB再接続後の再合格。32KiB upload＋全域照合はSPI 570.2KB/s、QSPI 1,023.1KB/s。
- **PSRAM（qspipsram 480p/720p、spipsram）**: `diag`全項目、PSRAM 2048 byteの照合（upload＋FENCE 約870KB/s）、COPY 2048/32767 byteの照合（32767 byteで6.2〜7.0ms）、`pcm`の連続再生（spipsramで約30分・再発音3603回、fault 0）。chip GSR版の720pでも同じ診断に合格し、S1で映像・PCMの音を確認。
- **合成器の修正（`f730319`）**: 乗算器入力のregister化の後、実録ピアノが歪まないこと、gain 0の音源が漏れないことをqspipsram720で確認。

## 資源とタイミング

Gowinの`Logic`はLUT単独ではない。版・構成の違う数値を単純に比較しない。下表はRASTER最終ラインの修正とタイミング改善を含むRTLでの`run-baseline.ps1`全16構成の結果（Education V1.9.11.03、2026-10-27）。P&R optionは`tools/build-nano9k.tcl`の既定値で、環境変数の上書きは使っていない。

| 構成 | Logic | Register | BSRAM | 最悪setup | 最悪hold |
|---|---:|---:|---:|---:|---:|
| hdmi / hdmi720 | 837 / 848 | 666 / 668 | 0 | +7.020 / +4.665ns | +0.708 / +0.562ns |
| dvi | 93 | 55 | 0 | +33.104ns | +0.708ns |
| phase2 / phase2720 | 5072 / 5092 | 4165 / 4166 | 25/26 | +0.612 / +1.689ns | +0.552 / +0.552ns |
| phase2boot / phase2boot720 | 5897 / 5886 | 4543 / 4544 | 25/26 | +2.087 / +1.929ns | +0.562 / +0.558ns |
| demo / demo720 | 6874 / 6885 | 4555 / 4556 | 26/26 | +0.269 / +0.190ns | +0.561 / +0.555ns |
| spi / spi720 | 5096 / 5150 | 4198 / 4199 | 25/26 | +1.487 / +1.186ns | +0.408 / +0.559ns |
| qspi / qspi720 | 5143 / 5105 | 4200 / 4201 | 25/26 | +0.760 / +1.615ns | +0.408 / +0.555ns |
| spipsram | 6719 | 5149 | 25/26 | +2.137ns | +0.552ns |
| qspipsram / qspipsram720 | 6724 / 6666 | 5151 / 5152 | 25/26 | +1.103 / +1.479ns | +0.552 / +0.552ns |

全16構成でsetup/hold違反0、TNS=0、recovery/removalの負slackなし。すべて開発下限の+0.10nsを満たす。最小はdemo720の+0.190ns（demo sequencerの`count[5]`→`count[8]`）で、目標の+0.20nsには0.010ns届かないが、今回の受入値とする。改善前に下限未達だった5構成はphase2720 +0.020、spi720 +0.035、qspi720 +0.063、demo +0.068、demo720 +0.076nsで、RASTERの追加logicを通らない既存経路だった。

Standard V1.9.12.04では同じRTL/SDCで14構成が合格し、boot系2構成はMISO入力のholdが−3.526nsとなったため、2026-10-27のStandard版Release ZIPから除外した。その後、SPI受信の保持期間に基づきMISO受信2レジスタのhold制約を3→7へ修正した。全経路の最小setup/holdはStandardでphase2boot +0.848/+0.527ns、phase2boot720 +0.834/+0.530ns。Educationも+2.087/+0.562ns、+1.929/+0.558nsで合格した。両版のbootprobe・magicprobeを含む8ビルドで違反0、TNS=0、負のrecovery/removalなし。[boot STA監査と実装検証](boot-sta-audit.md)を参照。Standardの計測用bootprobeではJEDEC ID 0x856016・既存imageのCRC検査を16回連続で確認した。製品用boot構成、外部CPUでの起動、冷間起動と波形実測、Releaseへの追加は未実施。

構造的な対策は次の3点。Verilator 5.032の全57試験が合格し、HDMIのpacket開始位置は480p/720pで毎pixel照合した。

- HDMIの`packet_enable`を1 pixel前に判定してregisterへ入れ、元と同じ開始位置を保ったまま`cx`のdecodeと音声packet制御の経路を分割する。
- 16×16 spriteのtile番号は4の倍数へ整列済みなので、row/column offsetの加算をbit連結に置き換え、RAM bankのCE手前のcarry chainを除去する。
- pattern RAMのCEは、grant済みrenderer読出しと排他的なcommandアクセスを直接ORし、重複したgrant muxを除去する。

構造変更後はdemo720のplace optionを0から1へ戻した（0ではOAM RAMアドレスへの経路が−1.401ns）。spipsramはroute option 1でEXT読出しmuxの余裕が+0.064nsとなったため、2へ変更して+2.137nsを確保した。他の構成のP&R optionとSDCは変更していない。証跡は`reports/a5a9ca2-raster-timing/`に保存し、統合STA summaryには構成別の元manifestのpathを記録している。同じRTL・生成HDMI・制約のhashを照合して集計し、optionを変更した2構成は最終build scriptで再測定した。

タイミング改善後のEducation版qspipsram720をB1へSRAM書込みし、既存Pico firmware・QSPI 5MHzで桜吹雪ストレス試験を2026-10-27 07:25–08:25 JSTに実施。3600.0秒、216000 frame、60.00fpsでPASS、sprite overflow・PCM/line underrun・ERROR_CODEは0。証跡は`reports/ee4a0ca-sakura-60m-20261027-072539/`。判定はシリアルtelemetryで、映像・音質の観測は含まない。Pico firmwareはデバイスから読み戻していないため作業ツリーの版とは同定しない。Standard版またはboot構成の実機試験を示す結果ではない。

デバイス総量はLUT4 8640、FF 6480、BSRAM 26、PLL 2で、PSRAM版のLogicは約77〜78%に達する。demo系はart ROMを含めBSRAMを使い切っている。

## 既知の制約

- **SPI/QSPIの速度**: ブレッドボード配線では5MHzが上限。10MHzは設計上の値で、実機では未達。
- **内蔵Flashの照合表示**: programmerが`Verify Failed at 0`を表示する。電源再投入後の起動は確認済みだが、Flashのreadback照合とは扱わない。
- **TCL製テレビ**: 480pで無信号（Sipeed公式のDVIサンプルでも同じ）。原因は未特定。
- **タイミングの余裕**: PSRAM版は資源の使用率が高く、配置の変動でslackが大きく動く。一部の720p構成はP&R optionを個別に指定している。
- **PSRAMの範囲**: die 0（4MiB）だけを使う。外部端子タイミングを含む完全なSTAではない。
- **W65C02S**: 実CPUでの動作は未確認。CPU用の外部回路（RESB保持、RAM/ROMのdecode/OE、bus turnaround）も未製作。
- **計測していないもの**: TMDSの信号品質・規格適合、実周波数・jitter、消費電流、実機音声のsample完全性。

## 保守上の注意

- mapのRAMは1024×16のbyte RMW構成ではsimulationに合格しても実機で読戻しが00になった。現在は2048×8のbyte lane 2本で、RMWを使わない（原因の機序は未特定）。OAM・paletteのRMWは維持している。
- 合成器の乗算器の入力を`state`の組合せで選ぶと、STAは通っても実機で前の音源のsampleが混入した。乗算器の入力は専用registerにする。
- PSRAMのpadへ出る信号はregister出力にする。組合せのRESET#がglitchを出し、配置によって全writeが失われた。
- DQ/RWDSの出力enableへの経路はGowinのSTAで解析されない。TX窓とpinごとのregisterで余裕を持たせている。
- OSER10のresetはchip GSRを使う。lane別fabric FFからIOLOGICのRESETへ配線する方式は、配置によってrecovery違反になった。
- ACRのCTSは仕様のbyte配置から期待値を求めて試験する（過去に送信側と試験の両方が同じ誤った定数を持っていた）。

## 残っている作業

| 作業 | 完了条件 |
|---|---|
| HDMI互換性 | 2機種以上×2ケーブルで起動20回・抜挿10回・各1時間（[実機試験](hardware-test.md)） |
| chip GSR版のreset反復 | S1/S2で720pのreset 20回ずつ |
| タイミングの余裕の維持 | 今後の変更でも全16構成でWNS ≥ +0.10nsを維持 |
| W65C02S接続 | 外部回路の製作、実CPUでID読出し・VRAM・IRQ・音源、バス波形のsetup/hold実測 |
| ROM-less boot | 実CPUでの起動（[ROM-less boot](romless-boot.md)） |
| SPI/QSPIの高速化 | 配線の改善またはSCK直接clock化で10MHz以上 |
