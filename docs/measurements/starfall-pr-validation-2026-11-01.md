# STARFALL Stage 1: PR validation

2026-11-01 JST。ゲーム実装は`5d9563a`までの10コミットを保存したもの。
以後の変更はCI分類・CIビルドとこの検証記録で、ゲーム・RTL・ABIは変更しない。

`bash software/starfall/build-test.sh`を再実行した。

- C11、`-Wall -Wextra -Werror`、Debug ASan/UBSanでホスト6件PASS:
  deterministic_game / arcade_flow / boss_phases / backend_contract / scene_music / keyboard_protocol。
- Pico SDK 2.2.0、Arm GNU 14.2.rel1、ReleaseでSPI/QSPIの両ターゲットをコンパイル成功。
- 両ELFともtext 114,392 B / data 0 B / bss 31,908 B。
- 設計算術、ローカルMarkdownリンク、生成register定数の検査PASS。
- CIに同じ6件のホスト回帰とSPI/QSPIビルドを追加。`software/starfall/`はPico jobを選ぶ。

これは最終版Cファームウェアの新しい実機映像・音声・連続運転試験ではない。
実機の過去の条件・版ごとの性能値は各測定記録を参照し、この版へ無条件に転記しない。
このPR整理作業ではFlash/FPGAへの書込みを行っていない。
Stage 1 STAR FRONTIERのみ実装済みで、Stage 2〜6はカタログ・拡張計画に留まる。
