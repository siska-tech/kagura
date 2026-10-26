# 検証状況と既知の制約

対象実装は`bfd2178`、検証実施日は2026-10-23。2026-10-24に開発途中の作業記録を集約した。以下は既存結果の要約であり、文書整理時の再試験結果ではない。現行checkoutでの回帰・P&R・STAの再測定は[M0基準記録](baseline.md)を参照（実機試験は含まない）。

## 確認済み範囲

| 分野 | 証拠・範囲 | 未確認の境界 |
|---|---|---|
| 基板 | シルク3674、GW1NR-9C、3674回路図とヘッダ・CPU候補18ピンを照合 | 異なる基板版への適用 |
| CPU bus | `tb_w65c02_bus`で要求回数、OE、read setup/hold、IRQ、reset解除、締切をモデル検査 | 実W65C02S接続・オシロ測定 |
| SPI/QSPI | `tb_spi_bus` / `tb_qspi_bus`で10MHz転送、BUSY、read副作用、途中中断、競合を検査 | Pico等との実配線・pad遅延込みの10MHz |
| VRAM・queue | byte参照モデル、領域境界、拒否時副作用、FILL/FENCE、満杯、順序を検査 | 外部ホストからの長時間更新 |
| 起動 | RAMのpoison/zero照合、INIT_DONE、最初のline0、system側だけのresetを検査。初期化版デモでS2復帰を実機確認 | 多数回の電源投入・reset |
| 背景・sprite | 全画素比較、scroll/flip/behind、透明色、優先順位、16個/line超過とIRQ。720pでも背景・spriteを全画素比較 | 全属性の実機個別判定 |
| 6ch音源 | `tb_audio_synth`で34770 stereo samplesが整数モデルと一致。24 system cycles/sample、noise周期、飽和、設定反映・拒否を検査 | 実機PCMのsample完全性 |
| 音源統合 | `tb_audio_core` / `tb_demo_audio`でFIFO token順序、wave bank交換、PCM、error、デモの映像・音声を検査 | 長時間の音声途切れ・停止復帰 |
| HDMI | TMDS復号、BCH/metadata/ACR、TERC4からPCMを復号。パイプラインencoderは原版と2clock遅れで60万symbol一致 | serializer出力の電気特性・規格適合 |
| デモ | 480p/720pのシューティング映像と6ch演奏をモニター1台で確認。720pの自機配置修正後も確認 | 複数sink・長時間 |

試験は[ビルド・テスト手順](build-and-test.md)で再実行できる。合格条件は[検証計画](verification-plan.md)、SPI/QSPIの具体値は[ホスト仕様](host-interface.md)、720pの試験範囲は[16:9仕様](wide-mode.md)を参照。

### Pico外部ホスト実機試験（2026-10-25）

Tang Nano 9KとRaspberry Pi Picoをブレッドボード配線し、SPI/QSPIとも5MHzでID/ABI、register、VRAM、FILL/FENCE、sprite、IRQ、BUSYを確認した。10MHzはSPI/QSPIともVRAM等の読戻しにbit化けがあり不合格のため、この配線での実測上限と運用値は5MHzとする。64 FILL＋4096byte streamではSPIでBUSYを41〜50回、QSPIで56〜59回（どちらも約2.3ms）観測し、FIFO errorなし。全6音源の同時発音を聴取し、512byte wave bank交換の読戻しも一致した。

32KiB uploaderは4096byte×8 blockを全て読戻し照合し、SPIは2.19秒・570.2KB/s、QSPIは2.06秒・1,023.1KB/s。SPI/QSPIともS2 reset後とPico USB再接続後に診断が再合格した。両方式ともheader途中・data byte途中で/CSを上げる実機試験は、FILL_VALUEが`5a`のまま変化せず、直後のID `4b 39`読出しと全診断に合格した。試験中はLED1（reset解除）が点灯、LED2（adapter `late`）が消灯しており、deadline違反は観測しなかった。QSPI bitstreamをTang内蔵Flashへ書いた後のFlash bootでも診断に合格したが、Gowin Programmerは`Verify Failed at 0`を表示するため、機能的な起動確認とFlash readback照合は区別する。詳細・生成物hashは[Pico firmware記録](../software/pico/README.md)を参照。

M2の完了条件（両方式のID/ABI、VRAM照合、IRQ、sprite・音源更新、BUSY待ち、途中中断、reset/USB再接続復帰、uploader）は実機で確認済み。ブレッドボード評価のためオシロによるSCK/IO・t_CSS測定は対象外とし、電気的マージンや量産配線の保証には用いない。LED1はreset解除表示であり、正常時の点灯を`late`と誤認しない。

## 配置配線と資源

Gowin Education V1.9.11.03、GW1NR-LV9QN88PC6/I5。LogicはGowin集計値でありLUT単独の数ではない。版・構成が異なる数値を単純加算しない。

以下は`d501a1f`の測定値（M0の`9f595f7`からの段階的な改善は[タイミング仕様](timing.md)の改善記録）。全11構成でsetup/hold違反endpoint 0、TNS 0。

| 構成 | Logic | Register | BSRAM | 最小setup slack |
|---|---:|---:|---:|---:|
| phase2 / phase2720 | 4329 / 4351 | 3235 / 3236 | 24/26 | +2.079ns / +0.377ns |
| spi / spi720 | 4405 / 4468 | 3268 / 3269 | 24/26 | +1.608ns / +0.630ns |
| qspi / qspi720 | 4399 / 4450 | 3270 / 3271 | 24/26 | +0.142ns / +0.192ns |
| demo / demo720 | 6268 / 6253 | 3624 / 3625 | 25/26 | +0.634ns / +0.130ns |

**OSER10 resetはchip GSRへ移行した**。`reset_n && pixel_lock && system_lock`をfabric FFを介さずGSRへ入力し、4個のOSER10を`GSREN=true`とする。旧720p recovery/removal false pathは削除済みで、Standard V1.9.12.04とEducation V1.9.11.03の480p/720pはいずれも負slackなし。GSR版720pはSRAM Program/Verify後にREADY、全自動診断、PSRAM/COPY/PCMが合格した。S1で映像正常とPCM melodyの明瞭な再生を確認した。drumの歪みはmelodyと伝送errorが正常なこと、および生成値・gainの数値監査からPicoデモ波形の音色問題として切り分けた。S1/S2でのreset反復は未実施。[タイミング仕様](timing.md)と[実機試験表](p1-07-hardware-test.md)を参照。

CPU/ホスト版は24 BSRAM、art ROMを含むデモは25 BSRAM（`443900a`以降。それ以前は26で予備なし）。設計予算25 BSRAMと実装使用量は区別する。単体の比較根拠は[HDMI評価](hdmi-synthesis-evaluation.md)、[音声packet評価](audio-packet-integration.md)、[BSRAM評価](bsram-evaluation.md)に残している。

## 実機互換性

基板1台で480p/720pの映像・音声をPCモニター1台にて確認した。初期480p試験ではTCL製テレビが無信号で、Sipeed公式DVI相当サンプルでも同様だった。原因は未特定であり、KAGURA固有ともテレビ非対応とも断定しない。2026-10-24に2機種目のTOSHIBA REGZA 32S5で、`443900a`のdemo bitstream（`kagura_demo.fs`、SHA256 `92bad474…`）の映像が正常に表示されることを確認した（art ROMのBSRAM割付け変更後の表示確認を兼ねる。音声・連続時間・回数は未記録）。全体の互換性試験は未完了。[実機試験手順・記録表](p1-07-hardware-test.md)を使用する。

256スプライト化（ABI 0.5）後、2026-10-25にTOSHIBA REGZA 32S5へSRAM書込みで次を確認した（連続時間・回数は未記録）。demoは実装上OAMの先頭64件だけを使うため、256件全体の表示はシミュレーションの全画素比較でのみ確認している。

| bitstream | source | SHA256 | 結果 |
|---|---|---|---|
| demo（480p） | `cf7f6b0`＋[経路短縮](timing.md#256スプライト化後の経路短縮2026-10-25)（書込み時は未コミット、内容はそのcommitと同じ） | `51893898…0C71` | 映像・LED正常 |
| demo720 | `cf7f6b0` | `7E56831F…10AE` | 映像・音声・LED・S2 reset後の復帰とも正常 |

未実施項目:

- 異なるsink 2機種以上×ケーブル2本、起動20回、抜挿10回、各1時間の連続試験。
- 実W65C02Sとの接続。SPI/QSPIホストはPicoで5MHzまで確認済みだが、ブレッドボード配線の波形・電気的マージンは未測定。CPU用外部reset保持回路、RAM/ROMのdecode/OEとbus turnaroundの確認。
- CPUのPHI2/data/OE/CS/reset/IRQの実測。FPGA未設定・電源不安定時にもRESBをlowへ保持する回路の電源投入試験。
- TMDS信号品質、実周波数・ジッタ・消費電流、実機音声の完全性、入力停止時のmute/silence復帰。
- 配置変動に対する小さいsetup余裕。chip GSR版OSER10 resetは実機の複数sink反復を再確認していない。

Flashでは`Verify Failed at 0`表示が残る一方、電源再投入後の起動は確認済み。SRAM Program and Verifyは成功。扱いと書込み方法は[ビルドガイド](build-and-test.md)を参照。

## 保守時に必要な設計上の注意

- マップRAMの1024×16 byte RMW版はsimulationに合格しても実機の読戻しが00になった。2本の2048×8 byte laneへ変更後、4箇所の読戻しと背景scrollが一致した。旧構成の正確な故障機序は未特定。OAM/paletteのRMWは維持している。公開address mapとrenderer読出しlatencyは変更していない。
- 初期ACR定数はCTSのbyte配置が誤っており、VIC1で25088を送っていた。25200へ修正し、VIC4は74250とした。旧試験も同じ誤定数を期待していたためbyte配置から期待値を求めるよう訂正した。修正後の480p/720p映像・音声は実機確認済み。
- Gray pointerの第一同期段にはmax-delayを設定し、bus全体や第二段を一括false pathにしていない。FIFO RAMを通るCDCの安全性はpointer公開後の読出し順序によるもので、STAだけで証明したものではない。
- reset入力、LED、TMDS出力には通常の外部同期I/O delayを設定していない。resetは非同期assert、LEDは状態出力、TMDSはOSER10から出力する。PLL LOCKから解除同期器への非同期assert経路も通常のclock間STAとは区別する。
- CPU I/OのGowin multicycle指定は、入力の`-to [get_clocks ...]`、出力の`-from [get_clocks ...]`を伴う。例外が「Actived」と表示されるだけでなく、実際のedge relationを確認する。

## CIと証拠の限界

GitHub Actionsは設計・リンク検査、依存hash、Icarus基礎試験、Verilator回帰を実行する。Gowin P&Rと実機試験はローカルで実施しておりCIでは再現しない。CIのVerilatorは5.032の固定commitからビルドし、失敗時もログ・画像・音声・指定した波形をartifactに残す。bitstreamとローカルの証拠はGit管理外で、ここにある表は測定記録の要約である。リリース判断時には対象commit・EDA・構成・制約・生成物hashと実機記録を揃える。
