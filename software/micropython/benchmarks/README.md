# STAR RUNNER v2 性能調査・比較レポート

調査日: 2026-10-29。基点: `main d18117a`。旧版は前作業で保存したstashからSTAR RUNNER関連ファイルだけを復元し、[shooter_v1.py](shooter_v1.py)を変更せず比較用に保存しました。古いドライバや無関係なstash差分は戻していません。

旧版のSHA256: `c96d8ba38906162f06054cf1b272a8025e4ea3b36e139802b9b2da3c562eaf8c`。

## 調査した実装・仕様

- 旧版の`Game.step/draw`、ART／FONT、2声BGM、終了時のコンソール復旧。
- 現行MicroPythonの`device.py`、DMA対応`transport_rp2.py`、`video.py`、`audio.py`、`console.py`。
- [PR #30](https://github.com/siska-tech/kagura/pull/30)の本文、[ドライバ実機記録](../README.md#実機の受入結果)。PRはmainへmerge済み。
- [映像仕様](../../../docs/video.md)、[音源仕様](../../../docs/audio-spec.md)、[メモリマップ](../../../docs/memory-map.md)、[PCM制御RTL](../../../rtl/audio/kagura_pcm_control.sv)。PCMは2ch、PSRAM signed 8bit、48kHz、START含む／END含まない形式。STOP／PREPARE／ACTIVE／sticky errorの扱いとwave bank交換を確認。

PR #30にあるCOMMIT約60fps、scroll＋COMMIT 58〜59fps、64 records一括転送約29fps、個別`Video.sprite()`8回約15fpsは**ドライバ単体の参考値**です。今回のゲーム実測値と同じ試験ではありません。

## Phase 1前の実機ベースライン

実際にCOM7で応答した機器: RP2040 Pico、KAGURA_PICO custom build、MicroPython v1.26.0-1.g3069c562f、ABI 0.5、caps `0x7B`、320×180／720p、QSPI 5MHz。FPGAの正確なbitstream commitとCPU周波数はこの試験では取得していないため不明です。

[baseline.py](baseline.py)で旧版のロジックと描画を各300更新実行しました。元の33ms目標sleepは入れず、最大更新速度を測っています。比較器でGCを各更新末に明示実行し、時間を集計します。これは「通常起動でのFPS」をそのまま測ったものではなく、GC方針を統一した比較用条件です。音声ONでは旧版のPulse 2声BGM＋効果音を含み、PCM／waveは含みません。

| 項目 | v1 音声制御OFF | v1 旧BGM・効果音ON |
|---|---:|---:|
| ロジック更新fps | 20.001286 | 13.295017 |
| 平均フレーム時間 µs | 49,972.55 | 75,124.56 |
| p95 µs（全300更新） | 50,699 | 101,070 |
| 最大 µs | 51,900 | 133,412 |
| 移動＋衝突＋step内音声 µs/更新 | 1,138.4334 | 30,181.16 |
| draw全体 µs/更新 | 40,007.81 | 36,148.85 |
| OAM write API µs/更新 | 11,343.713 | 11,158.283 |
| COMMIT API µs/更新 | 18,343.2 | 14,912.264 |
| audio register／commit合計 µs/更新 | 0 | 27,393.84 |
| 明示GC µs/更新 | 6,647.47 | 6,680.9632 |
| COMMIT成功 | 300 | 300 |
| ハードウェアVBlank差分 | 900 | 1,354 |
| OAM payload合計 byte | 76,800 | 76,800 |

区間に重複があります。audio時間はstepにも含まれ、転送・COMMIT時間はdrawにも含まれるため表の列を足してはいけません。「音声制御OFF」は旧版の`sound=False`で音声コマンドを出さない条件です。試行開始前の音源ENABLE状態は記録しておらず、HDMI出力の完全な無音までは確認していません。v2のBASEでは計測前に音源を明示停止するようにしました。

基準測定の入力は自動操縦で実キーボード待ちはありません。旧版の移動と衝突は入り組んでいるため、変更せず測るこのベースラインでは分離できません。OAM構築のみの時間、純粋なDMA機器時間、全wire量、PCMエラー数も取得していません。差引き計算や推測では補完しません。v2では処理区間を分離しました。両測定器自身の計時・wrapperのオーバーヘッドは未校正です。

生ログ: [baseline-hardware-20261029.txt](baseline-hardware-20261029.txt)。USB長文出力の欠落を避け、測定終了後に項目ごとに出力しています。最初の試行ではGC間隔16更新でMemoryErrorになったため、上表は毎更新GCに修正した後の完走結果です。失敗した試行は性能値に混ぜていません。

## ボトルネックと実装した対策

旧版も256byteのOAMをすでに一括転送していました。個別sprite APIを一括に置き換えるだけの改善ではありません。

| 観測・調査 | 対策 |
|---|---|
| draw約40ms、うちCOMMIT約18ms、OAM約11ms | 一括転送を維持し、COMMITを非同期受付。次のshadow書換え前に完了を待ち、CPU処理と待ちを重ねる |
| scroll Yは毎回0、高X bitはまれにしか変化しない | 低Xだけ毎更新、高Xは変化時のみ、Yは初期化時のみ |
| 各更新でlist slice、append/remove、機体追跡tupleを生成 | 機体・敵・弾・破片を固定長array／bytearrayへ、追従履歴はringへ |
| 旧音声ONでaudio約27ms/更新 | 固定優先度キュー、重複抑制、音色事前設定、通常発音はCONTROLだけ、commit最大1回/更新 |
| GC約6.6ms/更新 | 区間を明示計測し、通常は4更新ごと＋低空き時。公平なPhase 1比較では毎更新に揃える |
| 無制限ログは測定に影響 | 固定長統計ringとerror ringに保持し、終了後のみUSB出力 |
| 最初のv2でOAM構築13.4ms、17.5fpsへ悪化 | 8ライン帯の保守的な上限管理、必要範囲だけのclear、固定HUDのキャッシュへ変更 |
| 負荷低下後に高番号OAMが残留する可能性 | 小さい負荷に戻る最初の更新だけ、前の末尾をdisableした大きい範囲を送信 |

このレポートの初版比較は通常のMicroPythonだけで、native／viperは使っていません。現行ドライバの16byte以上の連続VRAM_WRITEがDMA経路に入ることを利用しています。その後のViper最適化・4条件A/B比較は[追加調査](acceleration.md)へ分けました。公開ドライバAPIの変更はありません。

## Phase 2〜4の実装

PCM ch0 BGMとch1効果音、PSG 3ch・noise・wave 2ch、両wave bank初期化、音声優先度制御、状態監視を追加しました。PCMアセットは生成スクリプトとSHA256付きmanifestで再現できます。地形・自動操縦・操作を維持したうえで、星、編隊、炎、破片、取得演出を追加し、映像負荷と音源組合せの試験を用意しました。

COM7はユーザーによる挿し直しで復旧し、実機試験を再開しました。CPUは`machine.freq()`で125MHzと確認しています。最初のv2ではOAM構築が約13.4msに増えて17.53fpsへ悪化しました。実測に基づいて8ライン帯の予算管理・HUDキャッシュ等へ修正し、旧演出32 records・毎更新GCの比較で22.46fpsになりました。旧版20.00fpsに対して約12.3%の更新速度増です。GC等の計測器差があるため、純粋な描画器単体の改善率ではありません。

| 720p QSPI 5MHz、CPU 125MHz | 更新fps | 平均 ms | p95 ms | 音声error incident | sprite overflow poll |
|---|---:|---:|---:|---:|---:|
| Phase 1、32 records、毎更新GC、300更新 | 22.46 | 44.22 | 50.43 | 0 | 起動前の残留1件のみ |
| BASE、64 records、400更新 | 22.85 | 43.48 | 50.46 | 0 | 0 |
| PSG＋Wave、64 records、400更新 | 20.62 | 48.21 | 64.94 | 0 | 0 |
| PCM 2ch、64 records、400更新 | 21.80 | 45.57 | 62.70 | 0 | 0 |
| FULL、64 records、400更新 | 19.92 | 49.89 | 74.90 | 0 | 0 |
| HEAVY、64 recordsを継続更新、400更新 | 16.67 | 59.69 | 84.16 | 0 | 0 |
| EXTREME 128、400更新 | 11.91 | 83.61 | 109.68 | 0 | 27 |
| EXTREME 256、400更新 | 7.55 | 132.16 | 160.70 | 0 | 28（起動前残留1件を含む） |

Phase 1以外は4更新ごとのGC・速度上限なしです。`sprite overflow poll`は15更新ごとのsticky観測回数で、overflowした全フレーム数ではありません。EXTREMEでは意図した16個/line超過を検出し、index／lineを保存できました。ERROR_CODE・AUDIO_STATUS・PCM両chの異常とは分けて扱っています。

EXTREME後のPhase 1とEXTREME 256の最初の観測には、前の描画で残ったSPR_OVERFLOWフラグが含まれていました。ログにはframe 0、sprites 0として残し、消して書き換えてはいません。最終版では初期OAM消去・COMMIT完了後にこの古いフラグをclearしてから計測を始めます。多重reloadで旧module参照が残りGCが約18msになった試行も保存し、通常の単一module状態で再測定した値を上表に採用しました。

## 30fps未達の内訳

HEAVYの平均は約59.69ms/更新で、目標33.33msを超えています。

| 区間 | 平均 ms/更新 |
|---|---:|
| OAM転送（512byte、既存DMA対応API） | 15.35 |
| OAM構築（64 records、上限管理・負荷スプライト含む） | 13.11 |
| 音声イベント・制御 | 7.46 |
| COMMIT受付・先行完了確認 | 6.67 |
| 自機・敵・弾の更新 | 2.27 |
| 当たり判定 | 1.28 |
| GC（4更新ごとを平均） | 2.12 |
| 音声／FPGA状態監視 | 1.24 |
| scroll・palette | 2.07 |

OAM転送と構築だけで約28.46ms使い、残りに音声・COMMIT等が乗ります。EXTREME 256では構築62.75ms・転送37.76msに増え、CPU側構築と通信の両方の負担が確認できます。一方、全モードでPCM0はACTIVE、PCM error 0で、音声停止やunderrunでFPSを落としている兆候はありません。

未分類のループ処理・計時そのもの等もあるため、この表の合計はフレーム全体と一致しません。個々の計測器オーバーヘッドは未校正です。30fpsを達成したとは扱わず、125MHz・通常MicroPython・既存通信APIでの今回の到達値を報告しています。native／viperやオーバークロックによる値には置き換えていません。

## 解像度・通信方式・連続動作

| 実機構成 | 試験 | 更新fps | 音声error |
|---|---|---:|---:|
| 480p QSPI 5MHz、PSRAMあり | FULL 400更新 | 19.96 | 0 |
| 480p SPI 5MHz、PSRAMあり | FULL 400更新 | 19.86 | 0 |
| 720p SPI 5MHz、PSRAMなし | FULL要求、実効PSG＋Wave、400更新 | 20.56 | 0 |
| 720p QSPI 5MHz、PSRAMあり | 64 records＋全音源、300秒、5,025更新 | 16.75 | 0 |
| 720p QSPI 5MHz、PSRAMあり、最終6秒曲 | 64 records＋全音源、300秒、5,035更新 | 16.78 | 0 |

初回5分試験ではCOMMIT 5,025回、VBlank積算18,003、最小空きヒープ121,008byte、sprite overflow 0、BGM予期せぬ非ACTIVE観測0、cleanup error 0でした。旧4秒BGM・ゲイン36の結果です。ユーザーの聴感では異音は聞こえず、BGMが小さくおとなしいとの意見があったため、音量と曲を改良しています。

最終BGMは160BPM・6秒、B7→C→D→Eの4小節ループです。パルス系リード、ベース、和音・アルペジオ、ドラムとフィルをPCMへ事前合成し、BGMゲイン224としました。曲の密度は上がりますが、再生は同じ48kHz PCM ch0なのでゲームループに合成処理は追加されません。以下の5分試験は、効果音を控えめにした時点の結果です。

**最終曲の5分再試験も完走**しました。5,035更新、16.781874fps、平均59.30ms、直近1024更新p95 82.916ms、最大124.128ms、VBlank積算18,002、最小空きヒープ120,256byte。PCM／音声error、sprite overflow、BGM非ACTIVE観測、cleanup errorはすべて0です。BGMはPCM0 ACTIVEのまま、終了後にREPLへ復帰しERROR_CODE=0を確認しました。上表の400更新matrixは旧4秒BGMの結果であり、曲を取り違えて比較しません。480pと720p SPIの追加試験も旧曲・ゲイン96で、最終編曲の5分再試験は720p QSPIです。

解像度切替は配布Standard release（source `8aee28e`）のSHA256を照合してSRAMだけへProgram and Verifyしました。内蔵Flashへは書いていません。終了時に元のFlashから再構成し、720p／QSPI／caps 0x7B、User Code `0xE9C8`へ戻ったことを確認しています。[programmer要約](hardware-20261029/programmer-summary.txt)にhashと検証結果があります。配布物の720p SPI版はPSRAMなしなので、720p SPIのPCM試験は未実施です。

生ログと機械可読結果: [hardware-20261029/results.json](hardware-20261029/results.json)。途中の改善試行・残留フラグも元の値のまま保存しています。

最終版をPicoの`shooter.mpy`として配置し、既存の`shooter.py`は`shooter_before_v2.py`へ退避しました。通常の`import shooter`で120更新を実行し、PCM・wave有効、音声error 0、BGMゲイン224、cleanup error 0を確認しました。最終health checkでもREPL復帰、PCM ACTIVE=false、PSG ENABLE=false、ERROR_CODE=0です。試験用の別名`shooter_v2`だけでの確認にはしていません。

その後の聴感フィードバックは「BGMはバッチリ、効果音がささやか」でした。BGMの曲・ゲイン224は維持し、Pulseを自機48／敵40／取得72、Noise 72、Wave 64、PCM効果音144へ増量しました。変更は起動時のgain設定だけで、発音キューや更新頻度は変えていません。追加の30秒試験は589更新・音声error 0・BGM非ACTIVE観測0・overflow 0・cleanup error 0。特殊攻撃を2回含めて確認しています。上記5分試験はこの効果音増量より前、追加30秒が増量後の結果です。

## 確認済みと残りの検証

| 項目 | 今回の確認 |
|---|---|
| v1 720p／QSPI 5MHzの比較基準 | 実機300更新×音声OFF／ON、上表 |
| v2両解像度のゲームロジック・上限 | ホスト試験、各NORMAL／HEAVY／STRESS 600更新 |
| Phase 1のゲーム内容保持 | 旧版と500更新の自機位置・スコア・残機・強化段階を比較 |
| PCM ch0とch1の分離、音源割当て、wave初期化 | ホスト試験。RTLシミュレーションや聴感の代用ではない |
| Ctrl-C・q・cleanup時の通信例外 | ホスト試験、音源停止・コンソール復旧の試行を確認 |
| v2実機の480p／720p、SPI／QSPI | 上表の4構成で完走。720p SPIはPSRAMなし |
| 入力・qでのREPL復帰 | UART0内部ループバックでt・右・上矢印・Space・qを入力、受信mask 118、36更新で終了、console復帰を確認 |
| Ctrl-Cでの全音源停止 | UART0内部ループバックで実行中にCtrl-C。KeyboardInterrupt捕捉、PCM ACTIVE=false、PSG ENABLE=false、ERROR_CODE=0、console復帰 |
| 外部UART GP1への実配線、実キーボード機器 | 未検証。内部ループバックを実配線の代用とはしない |
| PCM BGMループ境界の聴感、効果音との混合 | 旧曲ではユーザー確認「特に異常は聞こえない」。音量・編曲の要望で最終曲を制作。最終曲はユーザー向けに再生したが、聴感の合否コメントは未取得 |
| 5分の64 records＋全音源 | 旧曲5,025更新、最終曲5,035更新の両方で完走、音声error 0 |

今回実行した自動検証: STAR RUNNER 15件、既存ドライバ57件（公式PIOアセンブラとタイミングモデルを含む）、日本語29件（フォント原本zip再生成の1件のみ未実行）。v2の5モジュールはMicroPython v1.26.0のmpy-crossでコンパイル成功。CIの定義にもゲーム試験を追加しましたが、この変更をGitHub Actionsで実行した結果は未取得です。

再測定は[操作・ベンチマーク・受入手順](../examples/shooter.md)の`phase1()` → `matrix()` → `soak()`を使ってください。FPSが30を下回った場合は、`mean_us.oam_transfer`、`commit`、`audio`、`gc`とp95を優先して原因を比較します。未計測の改善後の値を、PR #30のドライバ単体値やPC上の実行速度で補完しません。
