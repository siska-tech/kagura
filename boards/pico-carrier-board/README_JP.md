# KAGURA Pico Carrier Board — Basic RevA

2026-11-12時点の最終出力一式です。電源ダイオードのBasic品化、配置・配線修正、電源ベタの輪郭と微細隙間の仕上げを反映しています。

## JLCPCBにアップロードするファイル

| ファイル | 用途 |
|---|---|
| [KAGURA_Basic_RevA_Gerbers.zip](KAGURA_Basic_RevA_Gerbers.zip) | PCB注文のGerber欄へ、ZIPのままアップロード |
| [JLCPCB_BOM.csv](JLCPCB_BOM.csv) | PCBAのBOM欄へ |
| [JLCPCB_CPL.csv](JLCPCB_CPL.csv) | PCBAのCPL／Pick & Place欄へ |

この3ファイルは同期済みPCBに対応する組です。ガーバーは同期済みPCBから再出力し、BOM/CPLは28 SMT点の一致を再確認しました。旧版との混用を避けてください。

## KiCad編集用プロジェクト

[kicad/KAGURA_PicoCarrier_RevA.kicad_pro](kicad/KAGURA_PicoCarrier_RevA.kicad_pro)をKiCad 10で開いてください。[プロジェクトの説明](kicad/README_JP.md)に構成を記載しています。PCB・必要なローカルライブラリ・参照中のローカル3Dモデルを同梱し、旧版・ロック・自動保存・個人表示設定は除いています。PCBに同期した5ページの回路図と閲覧用PDFを含みます。ERCと回路図／PCB等価性チェックはともに差分0です。

## 基板・実装範囲

- 外形72×48mm、4層、設計板厚1.6mm。Gerber ZIPには銅箔4層、マスク、ペースト、シルク、外形、PTH/NPTHドリル等14ファイルを収録しています。
- JLCPCB実装対象は表面SMT **28点**。Basic20点、Extended8点（7品種）。Basic/Extended区分と在庫は注文時に確認してください。
- J101/J102、J2011〜J2014、J2021〜J2023、J2/J3/J4、JP1、SW1は手配・後実装です。XIAOモジュールU1も別途用意し、DNPのJ5は実装しません。JLCPCBのBOM/CPLにはこれら16点を含みません。
- 部品単体の手配は[部品購入ガイド](parts-purchase/README_JP.md)を参照。純TH 7種類・13個と、SMT接点を持つUSB-C J3 1個をLCSCで調達するリストです。

## 発注時の設定・確認

Gerber・ドリル・CPLは共通のKiCad絶対原点です。CPLの座標はmm、Yは負値、面はtopです。座標や角度を手動で補正する前に、JLCPCBの配置プレビューで基板上の位置を確認してください。

4層・板厚1.6mmを基に、材質、銅厚、スタックアップ、表面処理等を注文設定と照合してください。配置プレビューでは全体位置・角度・極性、特にD1〜D4、C4、Q1、U2/U4/U5を確認してください。

## 残っている発注前の確認事項

ファイル整合性確認済みの最終出力ですが、製造リリース判定は未完了です。未接続0・新規DRC指摘0に対し、既存DRC14件（エラー7・警告7：J5保持帯1、PTH/courtyard6、シルク端5、シルク/マスク2）が残ります。

- C4（Panasonic EEEFK1A221P）とU2（TPS259470ARPWR）のメーカー推奨ランドと現カスタムランドの適合。
- Q1 AO4407Aの約-5V駆動での性能、Q1/R12の実装、D4の実装要否、F1のLittelfuse代替品選定。
- C3の実使用条件での実効容量1µF超、C8を含む起動・突入挙動、2A経路の電圧降下と温度。
- SS34ダイオードの温度・逆漏れ、XIAOの3.3V余裕と起動挙動。
- SW1の穴・長穴と端子番号、ソケットの積み高さ、Grove代替品のケーブル嵌合とピン方向。購入ガイドに寸法照合結果を記載。

ポータルへのアップロード・発注・支払は実行していません。

## 内容の確認

`SHA256SUMS.txt`はこのフォルダのファイル照合用です。作業途中の画像、ログ、旧版、製造に不要な設計検討データは同梱していません。

同期済みPCB SHA-256：`796165a7377b2b3204bb4c1c27e3a243f639fdb45c2359178ba950efa2eb3fcc`

同期に伴い参照名・ライブラリ名・ネット表記を整理しました。物理レイアウトと製造図形は従来版を維持しています。
