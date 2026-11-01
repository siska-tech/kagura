# Stage 1 boss barrage

敵弾poolを3から10へ拡張。追加OAMは57〜63を使用し、既存の装備/laser/HUDと分離。
ボスの上下砲台の狙い弾に、コアの3方向扇弾を重ねる。HP66以下では5方向へ強化。
扇弾は左方向2px/tick、上下速度差224 Q8の固定軌道。発射後の追尾はしない。
発射予兆と位置保持、砲台破壊による攻撃削減は維持。

生成時にsprite予算を確認し、移動による重なり増加時もcollisionより前に新しい敵弾から間引く。
非表示の弾が当たることを防ぐ。最大装備を含む既存replayと各HP段階の3/5発斉射を両解像度で検査。
ホスト6件PASS。実機の難易度・処理時間は未確認。
UF2は `build/starfall-arcade-m1-spi.uf2` / `build/starfall-arcade-m1-qspi.uf2`。
