# 弾幕追加後の処理落ちへの対策

ユーザー実機で弾幕版の処理落ち報告。前版は発射する各弾ごとのsf_render、毎tickのsf_laser_fit、予算超過時の最大10回のsf_renderを追加していた。

発射時の全描画再生成を廃止し、移動/発射後に1回だけrayなしの描画を生成して非弾objectを予約し、各弾の8走査線を順に加算する。予算超過弾はcollisionより前に無効化。laserの予算調整は既存collision内の処理にまとめる。敵弾が0なら追加処理を省略。

敵弾10発、3/5方向扇弾、攻撃周期は維持。全弾集中時の間引き、両解像度のreplay、ボス各phaseをホスト試験で検査。
実機での改善とCPU/io時間は未確認。修正UF2は `build/starfall-arcade-m1-spi.uf2` / `build/starfall-arcade-m1-qspi.uf2`。
ログ: `build/starfall-barrage-perf-host.log` / `build/starfall-barrage-perf-build.log`。
