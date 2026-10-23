# 検証状況と既知の制約

対象実装は`bfd2178`、検証実施日は2026-10-23。2026-10-24に開発途中の作業記録を集約した。以下は既存結果の要約であり、文書整理時の再試験結果ではない。

## 確認済み範囲

| 分野 | 証拠・範囲 | 未確認の境界 |
|---|---|---|
| 基板 | シルク3674、GW1NR-9C、3674回路図とヘッダ・CPU候補18ピンを照合 | 異なる基板版への適用 |
| CPU bus | `tb_w65c02_bus`で要求回数、OE、read setup/hold、IRQ、reset解除、締切をモデル検査 | 実W65C02S接続・オシロ測定 |
| SPI/QSPI | `tb_spi_bus` / `tb_qspi_bus`で10MHz転送、BUSY、read副作用、途中中断、競合を検査 | Pico等との実配線・pad遅延込みの10MHz |
| VRAM・queue | byte参照モデル、領域境界、拒否時副作用、FILL/FENCE、満杯、順序を検査 | 外部ホストからの長時間更新 |
| 起動 | RAMのpoison/zero照合、INIT_DONE、最初のline0、system側だけのresetを検査。初期化版デモでS2復帰を実機確認 | 多数回の電源投入・reset |
| 背景・sprite | 全画素比較、scroll/flip/behind、透明色、優先順位、16個/line超過とIRQ。720pでも背景・spriteを全画素比較 | 全属性の実機個別判定 |
| 6ch音源 | `tb_audio_synth`で34770 stereo samplesが整数モデルと一致。23 system cycles/sample、noise周期、飽和、設定反映・拒否を検査 | 実機PCMのsample完全性 |
| 音源統合 | `tb_audio_core` / `tb_demo_audio`でFIFO token順序、wave bank交換、PCM、error、デモの映像・音声を検査 | 長時間の音声途切れ・停止復帰 |
| HDMI | TMDS復号、BCH/metadata/ACR、TERC4からPCMを復号。パイプラインencoderは原版と2clock遅れで60万symbol一致 | serializer出力の電気特性・規格適合 |
| デモ | 480p/720pのシューティング映像と6ch演奏をモニター1台で確認。720pの自機配置修正後も確認 | 複数sink・長時間 |

試験は[ビルド・テスト手順](build-and-test.md)で再実行できる。合格条件は[検証計画](verification-plan.md)、SPI/QSPIの具体値は[ホスト仕様](host-interface.md)、720pの試験範囲は[16:9仕様](wide-mode.md)を参照。

## 配置配線と資源

Gowin Education V1.9.11.03、GW1NR-LV9QN88PC6/I5。LogicはGowin集計値でありLUT単独の数ではない。版・構成が異なる数値を単純加算しない。

| 構成・測定時点 | Logic | Register | BSRAM | 最小setup slack |
|---|---:|---:|---:|---:|
| 6ch統合CPU版（720p対応前） | 4327 | 3067 | 24/26 | 統合記録では数値違反0 |
| 480pタイトル・sprite上限デモ（720p対応前） | 6268 | 3490 | 26/26 | +0.013ns |
| demo720 | 6301 | 3634 | 26/26 | +0.085ns |
| phase2720 | 4332 | 3211 | 24/26 | +0.058ns |
| spi720 | 4437 | 3244 | 24/26 | +0.029ns |
| qspi720 | 4432 | 3246 | 24/26 | +0.095ns |

720p導入時には480pを含む全10構成でbitstream生成と解析対象の数値違反0を記録した。**720pはOSER10 RESETのrecovery/removal経路をSTAから除外している**。違反0はその経路を含む保証ではない。1台のモニターではreset後のレーン整列に異常は見られなかった。余裕が小さく、RTL・配置・EDA変更後は再ビルド・再検査する。[タイミング仕様](timing.md)と[16:9測定表](wide-mode.md)を参照。

CPU/ホスト版は24 BSRAM、art ROMを含むデモは26 BSRAMで予備がない。設計予算25 BSRAMと実装使用量は区別する。単体の比較根拠は[HDMI評価](hdmi-synthesis-evaluation.md)、[音声packet評価](audio-packet-integration.md)、[BSRAM評価](bsram-evaluation.md)に残している。

## 実機互換性

基板1台で480p/720pの映像・音声をPCモニター1台にて確認した。初期480p試験ではTCL製テレビが無信号で、Sipeed公式DVI相当サンプルでも同様だった。原因は未特定であり、KAGURA固有ともテレビ非対応とも断定しない。全体の互換性試験は未完了。[実機試験手順・記録表](p1-07-hardware-test.md)を使用する。

未実施項目:

- 異なるsink 2機種以上×ケーブル2本、起動20回、抜挿10回、各1時間の連続試験。
- 実W65C02S・SPI/QSPIホストとの接続。CPU用外部reset保持回路、RAM/ROMのdecode/OEとbus turnaroundの確認。
- CPUのPHI2/data/OE/CS/reset/IRQの実測。FPGA未設定・電源不安定時にもRESBをlowへ保持する回路の電源投入試験。
- TMDS信号品質、実周波数・ジッタ・消費電流、実機音声の完全性、入力停止時のmute/silence復帰。
- 配置変動に対する小さいsetup余裕と、720pのOSER10 reset解除の追加評価。

Flashでは`Verify Failed at 0`表示が残る一方、電源再投入後の起動は確認済み。SRAM Program and Verifyは成功。扱いと書込み方法は[ビルドガイド](build-and-test.md)を参照。

## 保守時に必要な設計上の注意

- マップRAMの1024×16 byte RMW版はsimulationに合格しても実機の読戻しが00になった。2本の2048×8 byte laneへ変更後、4箇所の読戻しと背景scrollが一致した。旧構成の正確な故障機序は未特定。OAM/paletteのRMWは維持している。公開address mapとrenderer読出しlatencyは変更していない。
- 初期ACR定数はCTSのbyte配置が誤っており、VIC1で25088を送っていた。25200へ修正し、VIC4は74250とした。旧試験も同じ誤定数を期待していたためbyte配置から期待値を求めるよう訂正した。修正後の480p/720p映像・音声は実機確認済み。
- Gray pointerの第一同期段にはmax-delayを設定し、bus全体や第二段を一括false pathにしていない。FIFO RAMを通るCDCの安全性はpointer公開後の読出し順序によるもので、STAだけで証明したものではない。
- reset入力、LED、TMDS出力には通常の外部同期I/O delayを設定していない。resetは非同期assert、LEDは状態出力、TMDSはOSER10から出力する。PLL LOCKから解除同期器への非同期assert経路も通常のclock間STAとは区別する。
- CPU I/OのGowin multicycle指定は、入力の`-to [get_clocks ...]`、出力の`-from [get_clocks ...]`を伴う。例外が「Actived」と表示されるだけでなく、実際のedge relationを確認する。

## CIと証拠の限界

GitHub Actionsは設計・リンク検査、依存hash、Icarus基礎試験、Verilator回帰を実行する。Gowin P&Rと実機試験はローカルで実施しておりCIでは再現しない。CIのVerilator版は固定していない。フルのログ・波形・bitstreamはGit管理外で、ここにある表は測定記録の要約である。リリース判断時には対象commit・EDA・構成・制約・生成物hashと実機記録を揃える。
