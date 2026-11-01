# KAGURA-9 開発ルール

毎回 [引き継ぎ](docs/CLAUDE_HANDOFF.md) と [ロードマップ](docs/KAGURA_ROADMAP.md) を読み、Git・PR・機器状態を再確認する。

- ドキュメントだけで判断せず、実コード・テスト・生成レジスタを確認する。不一致は記録する。
- RTL・ABI変更前に全構成、C/ca65/MicroPython SDK、生成定義、ホスト、テストへの影響を調査する。生成物は手編集しない。
- 既存SDKのViper描画・dirty tile・Link・SPI/QSPI転送・FENCE処理を再利用する。UIへ重複実装しない。
- PC参照実装、Unix MicroPython、RTL simulation、合成、実機の結果を区別する。未検証をPASSと報告しない。
- CPU描画時間、frame時間、flush時間、転送payload、GC回数、heap差分、allocation回数を混同しない。
- UIは単一owner。Framebufferとconsole/TextLayer/独立spriteを共用しない。consoleはpause/detach、closeでresume/attachする。生SDK利用者も所有権を守る。
- FPGA pattern RAMに全画面ダブルバッファはない。COMMIT/FENCEを全画面atomic swapとして扱わない。
- 実機firmware書換え前は対象ボード・USB識別・全Flashバックアップ・復元方法・保存領域・UF2範囲を確認する。eraseallや利用者データ削除をしない。
- MicroPython v1.26互換とfrozen nativeの4-byte alignment対策を維持する。実験的VM改造を前提にしない。Pico2/2Wは未検証。
- エラーを伝播させ、描画/転送失敗時のdamage/dirtyを保持する。復旧失敗を成功扱いしない。
- 専用featureブランチを使い、mainへ勝手にマージしない。既存未追跡ファイルを削除しない。秘密・シリアル番号・個人ファイルをcommitしない。

基本PC確認: `python -I software/micropython/tests/test_ui.py`、`python -I software/micropython/tests/test_framebuffer.py`、`python -I software/micropython/tests/test_frozen_alignment.py`。全手順は引き継ぎ資料を参照。
