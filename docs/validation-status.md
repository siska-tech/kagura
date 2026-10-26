# 検証状況と既知の制約

2026-10-27時点（`ae9ddcd`）の検証状況。simulation、P&R/STA、実機確認は別の証拠として扱い、片方の合格をもう片方の代わりにしない。

## 証拠の種類

| 種類 | 内容 | 再現方法 |
|---|---|---|
| simulation | Verilator 5.032で57試験。参照モデルとの全画素・全sample比較、protocol checker | `bash tools/test-verilator.sh`（CIでも実行） |
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

Gowinの`Logic`はLUT単独ではない。版・構成の違う数値を単純に比較しない。下表はRASTER最終ラインの修正を含むRTLでの`run-baseline.ps1`全16構成の結果（Education V1.9.11.03、2026-10-27）。

| 構成 | Logic | Register | BSRAM | 最悪setup | 最悪hold |
|---|---:|---:|---:|---:|---:|
| hdmi / hdmi720 | 834 / 850 | 665 / 667 | 0 | +7.026 / +2.684ns | +0.565 / +0.559ns |
| dvi | 93 | 55 | 0 | +33.104ns | +0.708ns |
| phase2 / phase2720 | 5094 / 5058 | 4164 / 4165 | 25/26 | +3.156 / **+0.020ns** | +0.552 / +0.559ns |
| phase2boot / phase2boot720 | 5999 / 5946 | 4542 / 4543 | 25/26 | +1.521 / +1.857ns | +0.557 / +0.557ns |
| demo / demo720 | 6866 / 6888 | 4554 / 4555 | 26/26 | **+0.068 / +0.076ns** | +0.552 / +0.570ns |
| spi / spi720 | 5117 / 5146 | 4197 / 4198 | 25/26 | +1.630 / **+0.035ns** | +0.412 / +0.566ns |
| qspi / qspi720 | 5186 / 5107 | 4199 / 4200 | 25/26 | +0.236 / **+0.063ns** | +0.408 / +0.552ns |
| spipsram | 6750 | 5148 | 25/26 | +0.752ns | +0.552ns |
| qspipsram / qspipsram720 | 6723 / 6733 | 5150 / 5151 | 25/26 | +1.374 / +1.080ns | +0.552 / +0.552ns |

すべてsetup/hold違反0。太字の5構成は開発下限の+0.10nsに届いていない。最悪経路は、720p版がHDMI protocol側の`cx`からaudio_packetsのCE（pixel74）、demo系がVRAMのpattern RAMのCEへの経路で、どれもRASTERの修正で加えたlogicを通らない。修正前のRTLではphase2720 +0.182、spi720 +0.694、qspi720 +0.517、demo +0.147、demo720 +0.007nsで、配置の変動で既存の小さい余裕が表に出たものである。chip GSR化の後、Standard版の480p/720pにもrecovery/removalの負slackはない。デバイス総量はLUT4 8640、FF 6480、BSRAM 26、PLL 2で、PSRAM版のLogicは約76〜78%に達する。demo系はart ROMを含めBSRAMを使い切っている。

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
| タイミングの余裕 | 720pのaudio_packets（`cx`→CE）とVRAMのCE経路を構造的に短縮し、`run-baseline.ps1`の全16構成でWNS ≥ +0.10ns |
| W65C02S接続 | 外部回路の製作、実CPUでID読出し・VRAM・IRQ・音源、バス波形のsetup/hold実測 |
| ROM-less boot | 実CPUでの起動（[ROM-less boot](romless-boot.md)） |
| SPI/QSPIの高速化 | 配線の改善またはSCK直接clock化で10MHz以上 |
