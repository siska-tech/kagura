# 弾幕時のフレーム待ち改善

前回のCPU最適化後も実機で改善が小さいとの報告。
ユーザー提供QSPIログ: frames11520→12544で平均52.77→51.32Hz、CPU最大1707us、io最大1393us、commit最大16520us。overflow/audio=0、missed1576→2121。blankも2792→3200。転送帯域のみの不足より、LIVE待ちで更新機会を失う経路と整合する。これは修正前の実機値であり、修正後の結果ではない。
backendはCOMMIT完了後、CPU処理を終えてからVBLANK_LIVEを待ち、転送後さらにCOMMIT完了を待っていた。
CPU/音源処理で短いblankを過ぎるとLIVE待ちが1frameを消費し、COMMIT待ちと合わせ更新周期が落ち得る。

shadow OAM/palette/scroll/rasterは即時stagingし、COMMITによるVBlank反映に同期を一本化。
docs/memory-map.mdのshadow/active分離とprogramming-guideのCOMMIT仕様に基づく。
初期化/scene切替のmap全面転送は表示停止、runtime map更新は画面外列に限定したまま。
ゲームの弾数/速度/パターンは変更しない。

ホスト6件PASS。backend試験はVBLANK_LIVE待ちを行わないこと、表示中のmap列に書かないこと、COMMIT順序を確認。
実機fpsの改善は未検証。SPI/QSPI UF2を従来のM1名へ生成。
ログの `blank` は `active_stage` に改名。staging完了が表示期間だった件数で、shadow方式では正常。
`hz100` と `missed`、CPU/io/commitの値で更新周期を評価する。
