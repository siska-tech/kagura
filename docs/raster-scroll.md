# ラスタスクロール 実装検討

状態: 実装済み（ABI 0.3、`feature/raster-scroll`）。規範は[レジスタマップ](register-map.md)の「ABI 0.3」。この文書は設計の経緯と根拠を残す。実装時の差分: 範囲外のRS_COUNT/RS_INDEXおよび順序違反COMMITのエラーは`BAD_ACCESS`（`INVALID_ARGUMENT`は存在しない）、RS_INDEXの変更はCOMMIT_BUSY中も可、COMMITではテーブルを受付時にsnapshotせず、書込み禁止にして完了時に一括copyする。

## 現状の制約（コード確認結果）

- `SCROLL_X/Y`はCOMMIT受付時のsnapshotで、VBlankのCOMMIT完了時に`active_scroll_*`へ入る（`kagura_core.sv`）。画面途中では変わらない。
- `kagura_line_display`は表示中ライン`N-1`の開始時に`render_start`で論理ライン`N`を描画する（1ライン先読み）。`kagura_bg_renderer`は`start`時に`line+scroll_y`と`scroll_x`をlatchする。つまりscrollは「ライン描画開始時の1回」だけ参照され、ライン途中で変えない。
- RASTER IRQは`shown_line==RASTER_LINE`で出る。この時点で次ラインの描画は既に開始済み。
- host締切: W65C02S 3.375MHzで480p論理1ライン≈31.8µs≈107 CPU cycle（720pは約半分）。SPI/QSPI経由のレジスタ書込みを含めると、**IRQ駆動で毎ライン更新する方式は成立しない**。

結論: IRQ handlerで書き換える方式ではなく、**事前にライン別scrollテーブルを設定し、ハードウェアが描画開始時に適用する方式**にする。host遅延に依存せず、決定的で全画素比較しやすい。

## 方針

1. 小さなscrollテーブル（`N`エントリ、初期案`N=8`）を追加。各エントリ = `{line[7:0], x[8:0], y[7:0]}`（25bit）。
2. テーブルはshadowとactiveの2面。shadowはhostが書き、COMMITのVBlankでactiveへ一括copyする（既存のframe atomicityを維持。OAM/palette 512wordコピーは行わない）。
3. BG rendererの`start`時、`render_line`に一致する（または超えた）次エントリがあれば、その`x,y`を現在scrollとして採用して以後のラインへ引き継ぐ。frameの最初（line0）は通常の`SCROLL_X/Y`で開始し、ポインタを0に戻す。
4. 実装は`kagura_core`内の小モジュール（例`kagura_raster_scroll`）に閉じ、rendererの入力`scroll_x/scroll_y`を差し替えるだけにする。renderer本体・VRAM調停・スプライトは変更しない。
5. 対象はBGのscroll X/Yのみ。backdrop/display_ctrl/スプライトは対象外（必要なら別途）。

## ABI案（ABI_MINOR 3）

CAPSに`RSCROLL`ビット（b6案）を追加。未対応bitstreamはCAPS=0で、新EXTはread 0/write BAD_ACCESS（現行規則どおり）。

| EXT | 名前 | 内容 |
|---|---|---|
| 0B | RS_COUNT | 有効エントリ数 0..N、RW shadow /0。0で機能無効（現行動作と同一） |
| 0C | RS_INDEX | 書込み対象エントリ 0..N−1、RW。範囲外書込みはBAD_ACCESS |
| 0D | RS_LINE | エントリのライン 0..LINES−1 |
| 0E | RS_X_L / 0F RS_X_H(b0) | scroll X |
| 10 | RS_Y | scroll Y。この書込みでshadowエントリ確定、RS_INDEXを自動+1 |
| 11 | RS_MAX | RO/N |

規則（確定が必要な項目の提案値）:

- **適用ライン**: エントリの`line=L`は、論理ラインLの描画から適用し、次のエントリまで継続する（それ以前は`SCROLL_X/Y`）。
- **順序**: `line`は`RS_COUNT`範囲で厳密昇順。違反・`line>=LINES`はCOMMITを`BAD_ACCESS`で拒否（snapshot不変）。同一ラインへの複数更新はABI上存在しない（最後勝ちの曖昧さを排除）。
- **遅延**: 適用はhardware描画開始時で決まり、hostの応答遅延の影響を受けない。描画がunderrunした場合は既存のunderrun挙動に従い、テーブルは描画要求のライン番号で引くのでずれない。
- **更新**: shadowテーブルの書換えは次回COMMIT用。今回COMMITのsnapshot（RS_COUNTを含む）は受付時点で固定。テーブル本体はCOMMIT受付後に書換えると完了時copyに混入するため、COMMIT_BUSY中のRS_*書込みは`BUSY_CONFLICT`（OAMと違いFIFO順序保証がない点の対策）。
- 480p/720p共通。LINESは240/180、同じテーブル。

## 資源・タイミング

- 記憶は`N×25bit×2面`＝N=8で400bit。BSRAM増加0を守るためFF/分散RAMで実装。copyはVBlank内（lineが進む前）に数cycleで完了する構成にし、並列copyで足りるか資源で判断する。
- 比較はライン開始時の1回（昇順ポインタ1個＋比較器1個）。renderer内のクリティカルパスには入れない（`start`時のlatch前段で1cycle確定）。
- 全11構成でWNS≥+0.10ns維持、BSRAM増加0を受入条件とする（ロードマップ記載どおり）。

## 検証計画

- `tb_raster_scroll`（新規）: 参照モデルにライン別scrollを追加し全画素比較。ケース: 無効（現行と全画素一致）、1エントリ、昇順N個、line0エントリ、最終ライン、X/Y同時、frame跨ぎでpointerが戻る、COMMIT未実施で不変、COMMIT_BUSY中書込み拒否、順序違反拒否。
- 480p（LINES=240）と720p（LINES=180）の両方、スプライト有無。
- 最大頻度: N個全てが連続ライン（line=0..N−1）に並ぶ場合でもrenderer期限（最悪cycle上限）が変わらないこと。
- 既存TB・`tb_register_abi`・`gen-registers.ps1 -Check`が通ること。
- ソフト: `software/include`にヘルパ（波紋・パララックス）を追加し、デモ1つで実機確認。

## 実装手順

1. 方針確定（この文書のABI案を承認/修正）。特に`N`と、line昇順制約・BUSY_CONFLICT規則。
2. `spec/registers.json`にEXT 0B..11、CAPS b6、ABI_MINOR 3を追加し生成物を更新。
3. `kagura_registers.sv`にshadowテーブルとCOMMIT snapshot（RS_COUNT）、検査を追加。
4. `kagura_raster_scroll`追加、`kagura_core`で接続。
5. TB・参照モデル更新、全画素比較。
6. 資源/タイミング（全構成）確認、docs反映（register-map、architecture、build-and-test）。

## 決定事項

- エントリ数`N=8`。水面の揺れ、画面分割、ステータスバーには十分。資源とSTAを優先する。
- X/Yの個別更新なし。エントリは常に両方指定し、状態管理を単純にする。
- lineは厳密昇順。比較回路と検証を簡素化する。
- COMMIT_BUSY中のRS_*書込みは拒否。shadow/activeの整合性を守る。
- ABI 0.3。既存0.2との互換性を維持して拡張する。
- ライン途中（ピクセル単位）切替は対象外。
