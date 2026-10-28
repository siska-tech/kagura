# KAGURA-9 STAR RUNNER v2

既存STAR RUNNERの地形・敵・敵弾・カプセル・追従機・自動操縦・手動操作を維持し、映像／音声／通信の同時負荷を測るデモです。320×240／320×180を自動判別し、通常の8×8スプライトで動作します。ドライバAPIは変更していません。

**検証状況（2026-10-29）**: v1／v2の実測、720p QSPIで全モード、480p SPI／QSPIでPCM混合、720p SPIでPSG／waveを確認しました。新編曲BGM・64 OAM＋全音源の5分試験は5,035更新・音声error 0・overflow 0。UART内部ループバックの操作・q・Ctrl-CとREPL復帰も確認済みです。64 OAM＋全音源は約16.8fpsで、約30fps目標は未達です。[性能比較](../benchmarks/README.md)に実測値と制約を記載しています。

## 配置と起動

[ドライバの導入](../README.md)を済ませ、次をPicoへコピーします。BGMとPCM効果音には`spipsram`／`qspipsram`系bitstreamが必要です。ABI 0.5、MicroPython v1.26.0を使用してください。

```sh
# software/micropython で実行。COM番号は環境に合わせる
mpremote connect COM7 fs cp examples/shooter.py :shooter.py
mpremote connect COM7 fs cp examples/shooter_pool.py :shooter_pool.py
mpremote connect COM7 fs cp examples/shooter_sound.py :shooter_sound.py
mpremote connect COM7 fs cp examples/shooter_stats.py :shooter_stats.py
mpremote connect COM7 fs cp examples/shooter_bench.py :shooter_bench.py
mpremote connect COM7 fs cp examples/shooter_oam_viper.py :shooter_oam_viper.py
mpremote connect COM7 fs cp -r examples/star_runner_assets :/
mpremote connect COM7 repl
```

起動方法は従来どおりです。

```python
import shooter
shooter.run(console=kagura_console)
```

自動操縦で開始し、対応capabilityとアセットがあればPCM BGM＋全効果音を使用します。PCMアセットが未配置ならPCMを無効にして続行し、終了結果の`audio_reason`に理由を出します。PSRAM非対応版ではPSG／waveのみです。`pcm_enabled`と`wave_enabled`で実際に有効だった機能を確認してください。FULLを指定しただけで全音源の試験合格にはなりません。

Viper高速版は明示して選択できます。両方有効のHEAVY実測は約23.7fpsで、通常版の約16.4fpsから改善しました。通常版との一致試験と、DMA内訳は[高速化の追加調査](../benchmarks/acceleration.md)を参照してください。

```python
shooter.run(console=kagura_console, renderer='viper', dma='viper')
```

更新した`kagura/`が必要です。古い凍結driverを持つUF2では、`kagura/dma_pack.py`をPicoの`/kagura_dma_pack.py`にも置けば、アプリ実行中だけの互換差替えを利用できます。driverのCS・abort・timeout処理は維持し、終了後に元へ戻します。native `.mpy`をPCで作る場合はRP2040用の`-march=armv6m`を指定します。

起動コンソールがある場合は必ず`console=kagura_console`を渡してください。同じPIO SMを`connect()`で再取得しないでください。コンソールを使わない接続例:

```python
from kagura import connect
dev = connect(mode="qspi", baudrate=5_000_000)
try:
    shooter.run(device=dev, duration=60)
finally:
    dev.deinit()
```

`shooter.run()`だけならドライバの自動速度選択でSPI接続し、終了時に解放します。`sound=False`は全音声OFF、`music=False`はPCM BGMのみOFFです。`input_fn`、`duration`など既存引数も維持しています。アプリはタイル・map・palette・OAM・scroll・使用音源とPSRAMのサンプル領域を占有します。

## 操作とゲーム内容

| キー | 動作 |
|---|---|
| `t` | 自動操縦／手動切替 |
| WASD／矢印 | 手動時の移動 |
| Space／`z` | 手動時の発射 |
| `q`／Ctrl-C | 終了 |
| `x` | 特殊攻撃、画面内の敵を消去 |
| `n` | NORMAL → HEAVY → STRESS → EXTREMEの映像負荷切替 |
| `p` | パーティクルのプール上限8 → 16 → 32 → 64 → 8 |

USB REPL、または既存コンソールのUART入力を使います。UARTは115200bps・GP1 RXです。最後の移動／発射キーを180ms保持します。端末ではキー解放や同時押しを正確に検出できないため、GPIOボタン等では押下中のビットマスクを返す`input_fn`を指定できます。`AUTO`・`SPECIAL_KEY`・`LOAD_KEY`・`PARTICLE_KEY`は押下エッジだけ返してください。

HUDの`S`はスコア、`L`は残機、`P`は強化段階、`A`／`M`は自動／手動です。敵撃破100点、カプセル500点。カプセルで速度UP → 弾速・連射UP → 追従機と追加ショットが有効になります。被弾で強化解除・一定期間無敵、残機0で90更新後に自動再開します。ゲームの進行は更新回数に依存するため、低FPSでは進行も遅くなります。

新演出は低速で流れる2群の星、上下地形のハードウェアスクロール、ステージごとの背景色、直線／波状／円弧編隊、左右・上下からの出現、進行による速度・間隔変化、噴射炎、弾の明滅、爆発、破片、取得時の光です。`enhanced=False`で追加演出と編隊変更を止め、旧版ルールの比較測定ができます。

## 負荷モード

音声試験の`mode`と映像試験の`load`を分けています。キーボードの`n`は`load`だけを変えます。

| mode | 映像 | 音声要求 |
|---|---|---|
| BASE | 通常ゲーム | OFF |
| PSG | 通常ゲーム | Pulse 3＋Noise＋Wave 2 |
| PCM | 通常ゲーム | PCM BGM＋効果音 |
| FULL | 通常ゲーム | 全音源 |
| HEAVY | STRESS負荷、64 OAM recordsを継続更新 | 全音源 |
| EXTREME | 128または256 OAM recordsを継続更新 | 全音源 |

| load | 内容 |
|---|---|
| NORMAL | 通常の敵・弾数と装飾 |
| HEAVY | 敵・弾・爆発の増加 |
| STRESS | 64 recordsの空きも移動する負荷スプライトで埋める |
| EXTREME | `sprites=128`／`256`、同一ラインの過負荷を意図的に発生 |

NORMAL／HEAVYでは通常64 recordsを転送します。旧版演出の比較時は32 recordsです。パーティクル上限を32以上にした通常／HEAVY表示では128 recordsを確保します。STRESSは64 recordsを維持し、収まらない装飾は省きます。

通常・HEAVY・STRESSではCPU側の8ライン帯の使用数表で16個を超える表示を抑えます。8pxスプライトが接する最大2帯を数え、帯の予算を16以下にすることで各走査ラインも16以下にします。実際には重ならない配置も保守的に省略する場合があります。ゲーム要素とHUDを優先し、星・破片は後に割り当てます。`particle_culled`には破片に限らず表示予算で抑制したスプライト数が入ります。`p`は生成プール上限であり、必ずその数が同時表示される指定ではありません。EXTREMEだけは上限チェックを外し、FPGAのoverflow index／lineを記録します。OAM転送record数、enable数、実際に描画できた数は別です。描画できた全スプライト数の直接カウンタはありません。

HUDは固定OAMをキャッシュし、数値が変わったときだけ字形を書き換えます。負荷を下げた最初の更新だけは、前の大きなOAM範囲の末尾をdisableしてまとめて転送し、その後に短い転送へ戻します。これによりEXTREMEから戻った際の古いスプライトの残留を防ぎます。

```python
shooter.run(console=kagura_console, mode="HEAVY", duration=60, target_fps=0)
shooter.run(console=kagura_console, mode="EXTREME", sprites=256, duration=30)
```

## 音源とアセット

| 音源 | 用途 |
|---|---|
| Pulse 0／1／2 | 自機ショット／敵ショット／取得音 |
| Noise | 爆発 |
| Wave 0／1 | ステージ開始／特殊攻撃・警告 |
| PCM 0 | 160BPM・6秒のオリジナルBGM、無限ループ |
| PCM 1 | 大爆発・取得・開始・特殊攻撃の4サンプル |

曲名は **Star Runner - Afterburner**。Eを主音とするB7 → C → D → E（V7 → ♭VI → ♭VII → I）を4小節で回し、明るいEメジャーへ解決します。速いパルス系リード、オクターブベース、和音スタブ、アルペジオ、キック・スネア・ハイハットとループ直前のフィルをPCMにまとめています。元曲の旋律・録音は使用していません。[進行の用語参考](https://guitarblog.net/twinbee/)。

BGMの既定ゲインは224です。BGMの編曲・音量は維持したまま、効果音を聞き取りやすく調整しました。Pulseは自機48／敵40／取得72、Noiseは72、Waveは64、PCM効果音は144です。BGM音量は`shooter.run(console=kagura_console, bgm_gain=160)`など0..255で調整できます。BGMの編曲はPCで済ませるため、曲の密度を増やしてもゲームループにリアルタイム合成処理は追加されません。

すべてオリジナル生成素材です。[生成スクリプト](../../../tools/gen-star-runner-audio.py)で再生成できます。リポジトリのルートから:

```sh
python tools/gen-star-runner-audio.py
# ホストで試聴するWAVも生成する場合（出力先を別にする）
python tools/gen-star-runner-audio.py --output build/star-runner-audio --wav
```

[音源仕様](../../../docs/audio-spec.md)とPCM制御RTLを確認し、PCMはsigned 8bit mono・48000Hz固定で生成しています。PSRAMの`0x400000..0x7FFFFF`に収め、サンプルごとに256byte境界で別領域を割り当てます。START含む／END含まない形式です。正確な配置・長さ・SHA256は`star_runner_assets/manifest.json`にあります。起動時に1024byteずつ転送し、全uploadのFENCE完了後にPREPAREします。準備／再生中のサンプル領域は書き換えません。

BGMの開始に既存`Audio.prepare_pcm()`／`play_pcm()`を使用します。効果音のPREPAREだけは同じ公開レジスタ手順をアプリ側で分割し、次回serviceでREADYを確認してENABLEを設定します。これによりゲーム内でREADYをbusy waitしません。通信・APPLY待ちには既存ドライバのtimeoutを使い、分割PREPAREにも1秒のtimeoutがあります。ch1の効果音処理はch0のSTART／END／CONTROLへ書き込まず、ch0の再生位置を保ちます。

音声イベントは固定8枠で重複をまとめ、特殊攻撃・警告・開始・取得・爆発・ショットの順に優先します。1更新で最大2イベント、同期AUDIO_COMMITは最大1回です。gain／duty／固定周波数は起動時に設定し、通常の発音はCONTROLのみ更新します。音色変更時だけSTEPを更新します。waveはAUDIO_COMMITでbank交換されるため、2bankを同じ内容に初期化します。

BGMと各サンプルは先頭／末尾を0にし短いfadeを設けています。これはデータ境界の連続性の検査であり、実機で異音がないことの証明ではありません。聴感によるループ境界の確認は受入手順に含めています。

## 計測と終了処理

```python
import shooter_bench
shooter_bench.phase1(kagura_console)  # 旧版比較、追加演出OFF、32 records
results = shooter_bench.matrix(kagura_console)  # 各モード300更新、上限制御なし
result = shooter_bench.soak(kagura_console)  # HEAVY、5分、目標30fps
```

`target_fps=0`は速度上限なし、通常は30更新/秒が目標です。`frames=300`でも打ち切れます。実行中はprintせずRAMに集計し、終了後にUSBへ`STAR_RUNNER key value`形式で出力します。結果は戻り値と`shooter.LAST_STATS`にも残します。`report=False`で出力を省略できます。

- `logic_fps`: 成功したゲーム更新回数／計測経過時間。入力・I/O・待ち・GC・指定したsleepを含みます。
- `commit_successes`: COMMIT受付に成功した回数。最終pending完了も待ちます。映像内容の目視確認回数ではありません。
- `hardware_frame_delta`: FPGAの8bit FRAME_COUNT_Lを積算したVBlank数。同じ画面を繰返すフレームも含み、実際に新規画面が出た回数ではありません。観測間隔が4秒以上空いた場合はwrap数が不明なので`None`です。
- フレーム時間の平均・最大は全更新。p95は直近最大1024更新の正確なnearest-rank値です。窓の数は`p95_window_frames`。`samples=16..8192`で変更できます。
- `mean_us`／`max_us`: 入力、移動、当たり判定、OAM構築、OAM転送、scroll、COMMIT、音声、監視、GC、sleepを分離します。OAM転送はDMA処理を含むAPI呼出しの時間で、DMA装置だけの時間ではありません。
- `transport_us`／`wire_bytes`: 全transport呼出しをアプリ内wrapperで測定。レジスタ・読出しheader等を含み、上の各区間と**重複**します。`dma_payload_bytes`はDMA対象writeのpayload量です。途中例外時は試みた転送量で、部分完了byte数の保証ではありません。
- GCは自動回収を測定区間で止め、既定4更新ごと、または空き24KiB未満で明示回収します。停止時間は`gc`、最小空きは`minimum_free_bytes`です。元のGC有効／無効状態は終了時に戻します。
- 約15更新ごとにPCM両ch、AUDIO_STATUS、ERROR_CODE、sprite overflowをpollします。音声errorはsticky bitの新しい出現をincidentとして数えます。PCM faultは勝手に再PREPAREせず、BGM予期せぬ停止も数えます。瞬間的な停止やpoll間の聴感異常は直接検出できません。

errorは直近32incidentを保存し、列順は`[frame, enabled_sprites, oam_bytes, frame_wire_bytes, ERROR_CODE, AUDIO_STATUS, PCM0_STATUS, PCM1_STATUS, overflow_index, overflow_line]`です。`audio_errors`と描画上限の`sprite_overflows`を分けます。ホスト例外は`failure`、復旧中の例外は`cleanup_errors`へ残します。

非同期COMMIT後、次のOAM／palette書換え前にCOMMIT_BUSY解除を待ちます。COMMIT待ちの間にshadowを上書きする最適化は行いません。終了・例外・Ctrl-Cでは全使用音源へ停止を試み、既存コンソールを`resume()`してタイル等を復元します。停止時に通信が失敗してもコンソール復旧とtransport解放を別々に試みます。物理的な切断時の消音・HDMI復元は保証できず、結果に失敗を残します。

## 実機受入手順

FPGA書換えは通常のボード手順で行い、各構成を記録してから測定してください。

1. 480p／720p、それぞれSPI／QSPIで導入・起動・HDMI表示を確認します。SCK・ABI・caps・MicroPython・CPUクロック・bitstream版を記録します。
2. `phase1()`を旧版と同じ条件で実行し、更新fpsと各時間を比較します。比較用の旧版と測定器は[benchmarks](../benchmarks/README.md)に保存しています。
3. `matrix()`を実行し、BASE／PSG／PCM／FULL／HEAVY／EXTREME 128・256を保存します。比較中は`n`を押さず、requested modeと実効音源flagsを確認します。
4. BGMを少なくとも20周聴き、6秒境界のクリック・欠落を確認します。同時に`x`、カプセル、敵撃破でch1効果音を鳴らし、ch0が途切れないことを確認します。PSG 3ch、noise、wave 2chの混合も確認します。
5. `soak()`で5分間継続し、PCM UNDERRUN／MEMORY_ERROR／CONFIG_ERROR、HDMI FIFO、FPGA error、overflowを別々に確認します。STRESSの表示抑制とEXTREMEの意図した欠落を区別します。
6. 手動切替、WASD／矢印、Space、UART GP1の実配線を試します。`q`終了と実行中Ctrl-Cで音が止まり、HDMI REPLへ戻ることを確認します。
7. 可能なら計測区間に外部HDMIキャプチャ／音声録音を行います。FRAME_COUNTだけでは描画内容や聴感を検証できません。

ホスト検証:

```sh
python -I software/micropython/tests/test_shooter.py
python -I software/micropython/tests/test_driver.py --rp2 build/micropython-src/ports/rp2/modules/rp2.py
```

Windowsでmpremoteを使わない計測補助として[タイムアウト付きraw REPLツール](../../../tools/star-runner-device.ps1)も用意しています。既存ファイルを上書きする前に別名で退避し、CodeFile内で自分のコンソールを指定してください。5分試験を送る場合は`-TimeoutSeconds 360`など実行時間より長く設定します。USB無応答時に無限再送や自動リセットは行いません。
