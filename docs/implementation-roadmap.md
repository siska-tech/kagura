# 開発ロードマップ

現行の機能・検証結果は[検証状況](validation-status.md)にまとめる。この文書は残る作業と拡張方針を扱う。

## 初版で残る作業

| 作業 | 完了条件 |
|---|---|
| 外部ホスト接続 | W65C02SおよびSPI/QSPIホストでID/ABI読出し、VRAM転送、IRQ、音源更新を実機確認 |
| CPU外部回路 | FPGA設定前を含むreset保持、RAM/ROMのdecode/OE、bus turnaroundを回路図と波形で確認 |
| HDMI互換性 | 2機種以上×2ケーブル、起動20回・抜挿10回・各1時間。TCLテレビの無信号原因を調査 |
| タイミング余裕 | 配置変更後のSTA再確認、720p OSER10 reset解除の追加評価、pixel/system経路の余裕改善 |
| ホストソフト | レジスタ定義の機械可読化、SV/ca65定数生成、ca65/ld65サンプルとVRAM uploader |
| 再現性 | CIのVerilator版固定、失敗時の画像・PCM・波形保存の整備、リリース対象の測定証拠を保存 |

SPI/QSPI、320×180表示とABI 0.2は実装済み。機材待ちのCPU試験を未完了として維持したまま、VDP・sprite・6ch音源・デモの実装を進めている。RTL試験やデモの実機表示を、外部ホストによる更新試験の代わりにはしない。

## 初版の範囲と変更方針

背景1面、1024パターン、64登録sprite・16個/line、6ch音源、wave最大256sample/ch、CPU 3.375MHzを基準とする。描画は2633 system cycles/論理ラインの設計上限を維持する。デモ版はart ROMによりBSRAM 26/26を使用するため、追加機能は資源・配置の再評価を伴う。

仕様削減や変更は原因・実測・比較案・失う機能・回復条件を設計判断へ記録する。sprite数、pattern数、画面高などホストに見える変更はCAPS/EXT/ABIと文書を同時更新する。資源の削減案は[資源予算](resource-budget.md)を参照。

## 後続拡張

PSRAM、PCM、COPY、DMA、bitmap、raster更新は初版の必須範囲外。別仕様・ABIで管理する。SPI/QSPIのSCK直接clock化、burst VRAM転送、8080型パラレルバスは[ホスト仕様](host-interface.md)に候補を記載する。まず現行の実機接続・互換性・タイミングを確認してから評価する。

CPUのROM/RAM配置はホスト依存としてlinker設定へ分離する。C++ harnessやCPUエミュレータを使う命令副作用の試験は未実装で、現在のSystemVerilog bus modelによる検証と区別する。
