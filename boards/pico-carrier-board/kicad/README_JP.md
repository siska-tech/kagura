# KAGURA Pico Carrier Board — KiCad 10

[KAGURA_PicoCarrier_RevA.kicad_pro](KAGURA_PicoCarrier_RevA.kicad_pro)をKiCad 10で開いてください。回路図・PCBとも同じプロジェクトに含まれています。

- [編集用の回路図](KAGURA_PicoCarrier_RevA.kicad_sch)
- [閲覧用の回路図PDF](KAGURA_PicoCarrier_RevA_Schematic.pdf)
- [PCB](KAGURA_PicoCarrier_RevA.kicad_pcb)

## 回路図の構成

全体案内と4機能シートの計5ページです。同名のグローバルネットがシート間を接続します。

| シート | 内容 |
|---|---|
| Power | USB-C給電、PTC、SW1、Q1/R12、モジュールへのSS34ダイオード分岐 |
| USB_Host | TPS259470A、ホスト電源イネーブル、USB-A、信号抵抗・ESD保護 |
| Modules | Picoの20極ソケット2本、Tangの分割ソケット7個、XIAO RP2040 |
| Expansion | Grove I2C、プルアップ、IRQバイアス、DNP GPIO拡張 |

回路図は現在のPCBの物理端子番号に対応しています。J101/J102はPico本体の電気回路を重ねて描くものではなく、キャリア上のソケットです。Tangの支持用NC端子も省略していません。

## 同期の検証結果

- 44部品、213物理パッド、203個の番号付き接点を照合。接続する162接点のネット、部品値、フットプリントが一致しています。
- ERC：エラー0・警告0。KiCadの回路図／PCB等価性チェック：差分0。未配線0。
- 既存PCB DRCは14件（エラー7・警告7）が残ります。発注前の技術確認事項は[全体README](../README_JP.md)を参照してください。
- PCBには回路図へのUUIDリンク、Q1/R12のローカルライブラリ名、標準化したネット名表記とNC識別子、下表の参照名を反映しました。部品の物理位置、パッド寸法、配線、ビア、ベタ、外形は変更していません。
- 現PCBからガーバーを再出力し、旧版との製造図形一致を確認しました。BOM/CPLの28 SMT点も同じ配置です。

これ以降はこの回路図とPCBを組で編集してください。回路図からPCBを更新する際は表示される変更内容を確認し、編集後にDRCと製造データの再出力を行ってください。

## Tangソケットの参照名整理

KiCadのアノテーションに合わせ、末尾が数字となる参照名にしました。旧名は回路図とPCBの非表示フィールド`Legacy Reference`に保存し、購入表も新名へ更新しています。端子番号・ネット・配置は同じです。

| 旧名 | 現在の参照名 |
|---|---|
| J201A | J2011 |
| J201B | J2012 |
| J201C | J2013 |
| J201D | J2014 |
| J202A | J2021 |
| J202B | J2022 |
| J202C | J2023 |

## 同梱ライブラリと3D表示

`KAGURA_RevA.kicad_sym`と`sym-lib-table`、`Manual.pretty`、`Basic.pretty`、`BoardExtras.pretty`と`fp-lib-table`はプロジェクト相対パスです。必要な既存ローカル3Dモデルは`models/`に同梱しています。

F1・J4の外部3Dモデルは元環境にもありません。Pico/Tang本体や3Dモデル未設定部品も表示されません。モデルは参考外形であり、購入代替品の嵌合保証には使えません。[部品購入ガイド](../parts-purchase/README_JP.md)の寸法差・実物確認事項を参照してください。

J101/J102・JP1・J4の購入型番は購入ガイドで管理しています。PCBと回路図のValueは設計時の表記を維持し、購入候補を無断で確定品へ変更していません。
