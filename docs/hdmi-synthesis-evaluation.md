# HDMI単体合成評価 / 2026-10-23

## 評価構成と条件

Gowin Education V1.9.11.03、GW1NR-9C / GW1NR-LV9QN88PC6/I5、SystemVerilog 2017。
固定したhdl-util revisionのプロトコル部を変更せずに使い、serializerだけを`rtl/platform/kagura_gowin_serializer.sv`へ置き換えた。Xilinx向け分岐を避け、Gowin OSER10を明示する。

`rtl/hdmi/kagura_hdmi_eval.sv`は外部25.2MHz/126MHz/audio clockと16bit PCM入力を持つ**診断用top**。VIC1/60Hz、48kHz/stereoに固定。DVI版は同じtopのDVI parameterだけを変更した。RGBは座標由来のパターンで、VDP/タイル/スプライトではない。

## 実測値（合成段階）

| 構成 | Logic合計 | LUT | ALU | FF | BSRAM |
|---|---:|---:|---:|---:|---:|
| DVI | 226 | 189 | 37 | 78 | 0 |
| HDMI video+audio | 1023 | 963 | 60 | 625 | 0 |
| 差分 | 797 | 774 | 23 | 547 | 0 |

合成レポートのLogicはLUTとALUの合計なので、1023を「LUT数」と表現しない。いずれもnetlist/reportの生成と`GowinSynthesis finish`を確認した。

**PLL、差動出力buffer、KAGURA audio FIFOはこの構成に含まない。** 予算表のHDMI行（FIFO/PHY込み）と同じ実装ではない。配置配線、Fmax、setup/hold WNS/TNS、CDC制約、実機音声は未評価。現在の原版audio CDCもKAGURAの最終契約に置換する必要がある。

## 検出した課題

- `add_file -type verilog`だけではVerilog dialectとなったため、`set_option -verilog_std sysv2017`を明示する。
- 原版にはoutput宣言時の初期値、未駆動packet配列、最適化で削除されたpacket moduleの警告がある。定数関数の展開/flattenでもmoduleが消えるため、警告だけからaudio消失とも正常とも判断しない。packet復号・PCMの出力依存性とreset挙動を次に検証する。
- Education版の生成netlistは保護形式。今回はその内部信号を目視確認したとの主張はしない。
- OSER10のD0..D9へLSB firstで接続したが、physical serializerとclock位相の試験は未実施。
- 今回追加したgeneric async FIFOは16×32bit、Gray pointer、domainごとの同期reset解除、同期read出力を実装した。まだHDMI topへ接続していない。BSRAMへのmappingは未測定であり、FIFO込みBSRAM使用量はこの表から推測しない。

## 再現手順

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/eval-gowin-hdmi.ps1
```

`-Gowin`でCLIパスを変更可能。DVI/HDMIを別buildディレクトリで実行し、ログ、HTMLレポート、`build/gowin-hdmi-summary.json`（レポートSHA256付き）を生成する。RTLの固定SHAは`third_party/hdl-util-hdmi/manifest.json`、ローカル評価コードはGit差分と合わせて管理する。依存検査は`tools/check-dependencies.ps1`。

## 次のゲート

継続作業で[FIFO接続版の統合試験と合成](audio-packet-integration.md)と、下記のP1-05 board P&R比較を実施済み。

上表の合成値は外部clock診断topのもので、P1-05の判定には下記のboard P&R比較を使う。Phase 0の成立性ゲートはVDP・CPU接続を含む全体予算で判定し、HDMI単体の結果だけで完了にしない。

## P1-05 board P&R比較（2026-10-23）

上記の合成だけの診断に続き、PLL・CLKDIV・OSER10×4・ELVDS_OBUF・CST/SDCを含むboard topで、DVI版とHDMI＋音声版を配置配線まで実行して比較した。

**条件**: Gowin Education V1.9.11.03、GW1NR-LV9QN88PC6/I5、同一option・同一CST（serializer reset最終段の`INS_LOC`を含む）。
- 両版共通: clock・reset解除・serializer・pin。
- DVI版`kagura_phase1_dvi_top`: 固定revisionの原版`hdmi.sv`を`DVI_OUTPUT=1`で使い、音声経路を持たない。SDCは共通部分（`phase1.sdc`）だけ。
- HDMI＋音声版`kagura_phase1_top`: 生成した`kagura_hdmi_stream`、test tone、async FIFO、tick駆動transport、packet scheduler。SDCは`phase1.sdc`＋`phase1-audio.sdc`。
- 映像入力: 両版とも計測用の`kagura_video_source_stress`（全24bitが変化）。カラーバーは各色成分が0x00/0xFFだけでTMDS encoderの大半が定数化され、DVI版がLogic 95まで縮んだため、計測には使わない。Flashへ書くカラーバー版（HDMI＋音声）はLogic 713/FF 333。

| 構成 | Logic | LUT | ALU | RAM16 | FF | BSRAM | DSP | rPLL | OSER10 | 違反（setup/hold） | P&R実行時間 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DVI | 357 | 302 | 55 | 0 | 100 | 0 | 0 | 2 | 4 | 0 / 0 | 7.8 s |
| HDMI＋音声 | 939 | 781 | 98 | 10 | 354 | 0 | 0 | 2 | 4 | 0 / 0 | 11.8 s |
| 差分 | +582 | +479 | +43 | +10 | +254 | 0 | 0 | 0 | 0 | — | — |

| 構成 | 最悪slack setup / hold / recovery / removal | Fmax pixel25 / system54 / serial126 | 全clockのTNS |
|---|---|---|---|
| DVI | +2.243 / +0.709 / +0.865 / +0.793 ns | 39.794 / — / 175.625 MHz | setup・holdとも0 |
| HDMI＋音声 | +1.593 / +0.560 / +0.524 / +0.560 ns | 41.046 / 131.078 / 157.653 MHz | setup・holdとも0 |

- DVI版はsystem54で動くロジックがないためsystem54のFmaxは出ない。system PLLはLEDのlock表示のため残し、PLL数を両版でそろえた。
- 差分にはHDMI data island（packet assembler/BCH、TERC4、ACR、InfoFrame）、音声FIFO/transport/scheduler、test tone（単体合成でLogic 26/FF 22）が含まれる。
- **予算との比較**: HDMI protocol＋PHYの予算LUT 2000/FF 1500/BSRAM 1に対し、HDMI＋音声版全体でLUT 781（ALU 98、RAM16 10は別計上）、FF 354、BSRAM 0。音声FIFOはBSRAMではなく分散RAM（RAM16）へ推論されたため、予算の1 BSRAMは未使用。
- 未制約pathはGowinのレポートに一覧がないため、clock間pathとport起点/終点を個別に`report_timing`で監査した（[検証状況の設計上の注意](validation-status.md)を参照）。
- recoveryの最悪値は配置で変わる（HDMI＋音声版のstress映像で+0.524ns、カラーバー版で+0.865ns）。serializer reset最終段のうち2本がLW網へ割り当てられることが主因。

再現（WSLで`python3 tools/prepare-hdmi-stream.py`を実行後、Windowsのリポジトリrootから）:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/compare-nano9k-variants.ps1
```

`build/p1-05-dvi-stress/`・`build/p1-05-hdmi-stress/`にbuildし、`build/p1-05-summary.json`へ使用量・slack・TNS・Fmax・実行時間・レポートとbitstreamのSHA256を保存する。今回の値はDVI bitstream `c1f5625669ce405a…`、HDMI＋音声 bitstream `1387ea6c7fe27584…`。
