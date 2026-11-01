# PROJECT STARFALL arcade expansion — Phase A design

2026-11-01 JST。専用ブランチ `feat/starfall-arcade-m1`。
第6版を作り直さず、最初のマイルストーンPhase A/Bを実装する。
latest origin/mainとのsoftware/pico・software/include・RTL差分は調査時0。
作業開始時のMicroPython/showcaseほか未コミット変更は対象外として保持する。

## 調査結果

既存: C11/Q8固定step、3残機、全6装備、同時option laser、固定pool、整数AI、
編隊報酬、空中戦→施設のmap ring、BG/4bpp、16/scanline検査とlaser短縮、
VBlank/COMMIT、dirty OAM、9曲、USB/GPIO、ホスト4試験、SPI/QSPI UF2。
課題: TITLE/PLAY/OVER/CLEARの4状態、固定1ステージ、タイトルが小文字列、
デモなし、bossは通常敵のHPのみ、ステージ番号/次面/場面ごとのreset契約がない。

## 最小設計変更

- 既存モジュール/pool/driverを維持。game.cにBOOT/TITLE/INTRO/PLAY/CLEAR/OVERの管理。
- PLAY内をOPENING/MAIN/CLIMAX/WARNING/BOSS/DEFEATへ分ける。
- stage_frame（イベント時刻）とstage_tick（既存のcamera世界座標）を分離。
  WARNING以後はcameraを止め、bossの時刻は進める。
- StageDefを6件用意し、名前/テーマ/イベント/ボス/曲の入口を共通化。
  今回有効な内容はStage 1 STAR FRONTIERのみ。2〜6は未実装として明示し進行を止める。
- SfBossを追加し、登場・core・独立砲台・HP phase・撃破timerを共通化。
- titleは専用BG logo/planet、palette fade、raster星空、通過する自機、START/credits。
- demoは共通PLAYにdeterministic入力controller＋演出eventを流す。専用rendererは作らない。
  40秒、START即中断、初期seed/装備/音源/OAMは新規runとして初期化。
- 新面/タイトルのmap変更は表示停止＋FENCE。動的全面framebufferは使わない。
- 進行stateの切替でcombat poolsを中央関数でclearし、backendとaudioはstate/sceneに追従。

## 資源予算

Stage 1 bossは48×32、6個の16×16 sprite（3/line）。同居する通常敵は0。
option laserは既存の予約方式に入れ、危険物とboss部品を隠さず16/line以内へ短縮する。
タイトル大型logo/planetはBGを使いsprite負荷を増やさない。
patternは1024未満を目標（追加pattern addressへの依存を避ける）。mapは64×32のまま。
CPU/transfer/COMMIT waitを別計測。UF2はSPI/QSPI、既存RTLに変更なし。

## 実装順・コミット

0. v6 baseline＋本設計を保存し、既存4試験PASSを記録。
A. 状態、StageDef、title、40秒attract、reset契約とtest。host/UF2を検証してcommit。
B. Stage 1の編隊/隕石/施設外壁、scroll stop、WARNING、部品boss、clear演出。
   title→boss→clear通しtest、sprite予算、既存KAGURA回帰、UF2生成後commit。
C. Stage 2 前線基地のハッチ/前後敵/shutter boss。
D. Stage 3〜6の固有地形/敵/部位boss。
E. 各面曲/ending/難易度/実機fps/長時間試験。

今回はA/Bまでを完成させ、C/D/Eを実装済みとは扱わない。
初期面は短縮版。2〜3分へ拡張するのは全6面の動作確認後。
実機の映像/音声/操作/60fpsはユーザーによる確認手順と、未確認項目を分けて報告する。
