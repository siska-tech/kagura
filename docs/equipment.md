# 機材一覧

[開発ロードマップ](implementation-roadmap.md)の各段階に必要な機材と、既存記録から確認できる状態。「要確認」は記録がなく、手持ちかどうか不明なもの（2026-10-24時点）。型番・本数が決まり次第この表を更新し、試験記録には機材IDを使う。

## 開発環境

| ID | 機材・ソフト | 状態 | 使う段階 | 備考 |
|---|---|---|---|---|
| B1 | Tang Nano 9K（シルク3674、GW1NR-LV9QN88PC6/I5、チップID `0x1100481B`） | 確認済み・1台 | 全段階 | [検証状況](validation-status.md) |
| — | 基板内蔵programmer（BL702、FTDI互換として認識） | 確認済み | 全段階 | 注意点は[ビルドガイド](build-and-test.md) |
| — | Windows PC＋WSL Ubuntu | 確認済み | 全段階 | Verilator 5.032、Icarus 10.1（`build/toolchain`）、Gowin Education V1.9.11.03。ライセンス導入済みV1.9.12.04は`hdmi`のbitstream生成とCDC hold修正を確認したが、480p OSER10 reset recovery −0.041nsのため基準移行は未完了 |
| P | 電源（PC USBポート/USB電源） | 確認済み | M3 | 試験記録には使った電源を書く |

## 段階別

| ID | 機材 | 状態 | 使う段階 | 備考 |
|---|---|---|---|---|
| S1 | HDMI sink: PCモニター MSI MAG 325CQRF-QD（31.5インチ） | 手持ち | M3 | 480p/720pで映像・音声を確認済み |
| S2 | HDMI sink: TOSHIBA REGZA 32S5（テレビ） | 手持ち | M3 | 互換性試験の2機種目。2026-10-24に`443900a`のdemo bitstreamで映像を確認 |
| S3 | HDMI sink: TCL製テレビ 43V型（Unitech LCK4303S相当、HDMI入力2ポート） | 手持ち | M3 | 480pで無信号。原因調査用に残す。正確な型番は未記録 |
| C1, C2 | HDMIケーブル 2m×2本 | 手持ち（型番未記録） | M3 | 受入条件は2本 |
| H1 | SPI/QSPIホストMCU: Raspberry Pi Pico（RP2040、無線なし） | 手持ち | M2 | [ホスト仕様](host-interface.md)はPIOでのQSPI駆動を想定 |
| — | ジャンパ線・ブレッドボード等の配線材 | 要確認 | M2・M4 | 10MHzでは配線長を記録する |
| M1 | オシロスコープ: Siglent SDS1202X-E（200MHz・2ch） | 手持ち | M2・M4 | SPI 10MHz波形、CPUのsetup/hold、reset保持の実測に必要。2chのため同時に見られる信号は2本 |
| M2 | ロジックアナライザ | なし | M2・M4 | 多信号のプロトコル確認はFPGA内の診断とホスト側ログで補う。必要になれば調達を検討 |
| U1 | W65C02S（3.3V動作） | **未調達（欠品）** | M4 | [成立性](hardware-feasibility.md)の8MHz列条件 |
| U2 | 外部RAM/ROM、decode・reset保持回路の部品 | 未調達 | M4 | 回路は未確定（[検証状況](validation-status.md)の未実施項目） |
| F1 | 外部SPI Flash書込み手段 | 未決定 | 後続拡張 | 基板上のP25Q32U。programmer経由か、FPGA経由の自作書込みか未決定 |

## 着手への影響

- M2（SPI→QSPI実機）: PicoとSDS1202X-Eで着手できる。ロジックアナライザがないため、多信号の確認はホスト側の読戻し照合とログを主にし、オシロはSCKとデータ線など2本ずつ確認する。
- M3（HDMI互換性）: S1とS2の2機種、ケーブル2本がそろい、[実機試験表](p1-07-hardware-test.md)の受入試験（起動20回・抜挿10回・各1時間）を実施できる。S3の無信号調査も並行できる。
- M4（W65C02S）: CPUと周辺部品が未調達のため着手できない。ロードマップどおりSPI/QSPI評価版を先に進める。

## 計測できないもの

TMDS信号品質、実周波数・ジッタ、消費電流、実機音声のsample完全性は専用計測器がなければ未測定として扱い、機能試験の結果で代替しない。
