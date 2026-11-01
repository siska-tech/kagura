# KAGURAロードマップ

2026-11-02、main b02a6efと実コードを確認した分類。希望と実装を区別する。
手順と制約は[引き継ぎ](CLAUDE_HANDOFF.md)、測定根拠は[Phase2](kagura-ui-phase2.md)。

## 完了済み

- #50 merged: App/Screen/Widget、Label/Button/Panel、HBox/VBox、ProgressBar/ListView、clip/damage、focus/queue、USB StdinInput、BitmapFont8日本語、MockBackendとPC試験。
- Gallery/Monitor/Mini Studio mockと受入記録。Studioは配置/操作のmockで完成エディタではない。
- #51 merged: 公開glyph8で既存Viper kernel再利用、旧ASCII経路維持、partial clip fallback、性能比較と1時間soak。
- RP2040日本語/USB操作/画面切替/console復帰/reset受入。計測imageの1時間、最終imageの短時間。最終binary1時間/正式な電源再投入は未実施。
- frozen native 4-byte alignment補正、Pico/Pico W board統合、unit/実機CRC確認。
- 既存SDKのLink/Viper/dirty転送、SPI/QSPI、Font、C/MicroPythonデモ、CIを再利用する土台。

## 進行中のテーマと未着手課題

Phase2は最初の最適化PRまで完了。性能改善全体は継続テーマで、新しい実装が仕掛かり中という意味ではない。
P0は再現性/現状保全、P1は次の小規模開発、P2以降は別設計・別PR。

| 優先 | 課題・実装状態 | 次の作業と完了判断 |
| --- | --- | --- |
| P0 | 検証環境識別（未完） | 実ロードbitstream由来/hashを確認。不明なら未確認維持。最終UF2の1時間/正式な電源再投入受入は機器利用可能時に実施。推定版へ勝手に上書きしない |
| P0 | 補助ASCII診断USB停止（未解決） | official VM/最小fixture/timeout/段階logで再現条件を調査。公開GUIの不具合と断定しない |
| P1 | damage領域最適化（未着手） | 現在App._damageは単一外接矩形。固定上限複数矩形/mergeを検討。tile trackerを複製せず、離れた更新/重なり/移動/overflow fallback/失敗再試行のgoldenを比較 |
| P1 | focus描画負荷削減（未着手） | 前後widget間の余計な描画と候補探索allocationを測る。damage改善効果と分離。非表示/無効/clip/押下解除/逆Tabを維持 |
| P1 | Font cache（未着手） | glyph8あり、glyph cacheなし。lookup負荷測定後に固定容量/eviction/Font寿命とRAM対効果を設計 |
| P1 | GC/allocation観測（未完） | frame/flush/tiles/payload/heap/合成遅延あり、自動GC/実allocation回数なし。測定器の影響と正味heap差を分ける |
| P2 | 汎用Canvas（未着手） | Studio専用Widgetによる描画は汎用Canvasではない。clip/invalidate/input API、追加全画面buffer回避を設計。Phase1回帰再現後に開始 |
| P2 | TextBox/Menu/Dialog等（未着手） | 文字eventはあるが編集widgetなし。編集モデル/focus/容量制限を設計。IMEは別段階 |
| P2 | Studio sprite編集（未着手） | 16×16風領域/ツール/パレットはmock。Canvas、編集データ、undo上限を設計。Framebufferと独立spriteを競合させない |
| P2 | UI/Studio保存読込み（未着手） | Font読込みや既存ゲームscoreはあるがproject形式/保存APIなし。空き容量、部分write/復旧、サイズ/versionを設計。現実機storageを削除しない |
| P2 | Tile/Sprite backend（未実装） | widget/backend分離あり。pattern/BG/OAM/palette allocator、参照/eviction/console返却を設計してから実装。共有を仮装しない |
| P3 | Pico2/Pico2 W（未対応/未検証） | RP2350 board定義なし。PIO/DMA/native/SDK/USB監査、compile/CRC/実機を別検証。Pico W CI buildと混同しない |
| P3 | USB HID（未着手） | 現在PC terminal→USB CDC。USB host HIDは別物。host hardware/電力/stack、共通Event adapter、release/repeatを設計 |
| P3 | MicroPythonコンピュータ環境（土台のみ） | console/REPL/日本語/GUIデモあり。file manager/launcher/settings/editor/IMEは製品として未実装。起動/寿命/保存/入力/復旧を設計 |

次はP0確認・既存テスト再現後、P1 damage/focusへ絞る。同条件でframe/CPU/flush/転送/heapを比較する。
60fpsやallocationゼロを未測定で保証しない。静止転送ゼロ、dirty保持、console復帰を退行させない。
Phase3もCanvas・編集モデル・保存を独立してレビューできる単位へ分ける。
