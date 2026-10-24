# P1-07 実機互換性試験 / 手順と記録表

実機互換性の受入条件: 2機種以上×2ケーブル、起動20回/抜挿10回/各1時間。全対象で映像と左右音声を確認し、通常運用でerror0。計測器がない項目は未測定と明記し、simulationの証拠と混ぜない。

## 状態（2026-10-24）

**受入試験を開始できる**。sink 2機種（S1 PCモニター、S2 テレビ）とケーブル2本がそろった（[機材一覧](equipment.md)）。これまでの確認は、S1でのFlash起動のカラーバー版、S1での480p/720p demo、S2での`443900a`のdemo（480p）映像で、いずれも回数・時間の内訳は未記録。TCL製テレビ（S3）は合格判定の対象外とし、原因調査として別に扱う。

## 対象bitstreamと実施範囲

[ロードマップ](implementation-roadmap.md)M3のとおり、固定テスト音のカラーバー版に加えて、配布対象の統合構成でも動的な更新中に確認する。各bitstreamは`tools/run-baseline.ps1`または[ビルド・テスト手順](build-and-test.md)で作り、書込みに使った`.fs`のSHA256とsource commitを記録表に書く。

| 段階 | 構成（`.fs`） | 映像・音声 | 実施範囲 |
|---|---|---|---|
| A | `hdmi`（`kagura_phase1.fs`）、`hdmi720`（`kagura_hdmi720.fs`） | カラーバー＋白枠、左1kHz・右500Hz | 必須。4組合せ×（起動20・抜挿10・1時間） |
| B | `demo`（`kagura_demo.fs`）、`demo720`（`kagura_demo720.fs`） | シューティング画面が毎frame動く、6ch演奏 | 必須。各sink×1本以上で起動5・抜挿3・1時間。残りの組合せは起動5 |
| C | `spi`/`qspi`＋Pico `soak 60`（[Pico host](../software/pico/README.md)） | ホストが毎frame更新するsprite、6音 | M2の縦通し合格後。各sinkで1時間 |

段階Bと段階Cは、ホストや内部sequencerが描画・音源を動かし続ける状態の確認で、段階Aの代わりにはならない。起動回数は内蔵Flash（`--run 6`）から、1時間試験はSRAM書込みでもよい（その旨を記録する）。

## LEDの読み方

LEDはactive low。基板の表記は1始まりで、`led_n[0]`（pin 10）がLED1、`led_n[5]`（pin 16）がLED6。回路図の部品番号がLED1〜LED6であることを確認済み（基板のシルク印刷は判読できない）。pinとの対応は[demo top](../boards/tang-nano-9k/kagura_demo_top.sv)の注記とCSTによる。

| 基板表記 | bit | カラーバー版（`kagura_phase1_top`） | demo版 | SPI/QSPI版（`kagura_host_top`） |
|---|---|---|---|---|
| LED1 | 0 | reset解除 | reset解除 | reset解除 |
| LED2 | 1 | mute | 表示frameで点滅 | adapter `late` |
| LED3 | 2 | audio underflow | pattern/palette読戻し不一致 | audio underflow |
| LED4 | 3 | audio overflow | map不一致、またはsprite 16個/line超過 | audio overflow |
| LED5 | 4 | system lock | system lock | system lock |
| LED6 | 5 | pixel lock | pixel lock | pixel lock |

underflow/overflowと`late`は一度でも起きるとresetまで点灯を保持する。1時間試験の終了時に消灯していれば、その間の発生は0回（回数は数えられない）。demo版のLED4はsceneの敵編隊がline上限を超える区間で点灯するのが正常で、errorではない。

## 判定基準（毎回の観察）

| 記号 | カラーバー版 | demo版 | SPI/QSPI版（Pico `soak`） |
|---|---|---|---|
| V | 8色バーが左から白・黄・シアン・緑・マゼンタ・赤・青・黒の順 | 背景がscrollし、自機・敵が動く | 背景色と64 spriteが動く |
| B | 白枠が上下左右4辺とも見える | 画面端の欠け・ずれなし | 同左 |
| A | 左が高い音、右が低い音。途切れ・ノイズなし | 曲が途切れずに鳴る | 和音とnoiseが途切れずに鳴る |
| L | LED1・LED5・LED6点灯、LED2〜LED4消灯 | LED1・LED5・LED6点灯、LED2点滅、LED3消灯 | LED1・LED5・LED6点灯、LED2〜LED4消灯、`SOAK PASS` |

## 機材の記録

| ID | 種別 | メーカー・型番 | 入力端子/設定 | 備考 |
|---|---|---|---|---|
| S1 | sink | MSI MAG 325CQRF-QD（31.5インチ PCモニター） | | |
| S2 | sink | TOSHIBA REGZA 32S5（テレビ） | | |
| C1 | HDMI cable | 型番未記録 | 2m | |
| C2 | HDMI cable | 型番未記録 | 2m | |
| P | 電源 | PC USBポート/USB電源 | | |
| — | 基板 | Tang Nano 9K（シルク3674） | | |

入力端子と、sinkの画質・音声設定（ゲームモード等）は試験前に記入する。

## 手順（組合せS×Cごとに実施）

1. **起動**: USBを抜いて5秒以上待ち、挿す。Flashから起動して映像が出るまでの時間とV/B/A/Lを確認する。sinkの電源は入れたまま。
2. **抜挿**: 動作中にHDMIケーブルをsink側で抜き、5秒以上待って挿す。映像と音声が戻るかと、V/B/A/Lを確認する。
3. **reset/mute復帰（各組合せ1回以上）**: reset button（pin 4）を押している間、カラーバー版ではLED2（mute）が点灯し、離すと消灯して映像・音声が戻ることを確認する。demo版は曲頭と画面の初期状態へ戻ることを確認する。
4. **1時間連続**: 開始時刻を記録して放置し、1時間後にV/B/A/Lを確認する。途中で画面消失・音切れに気づいたら時刻を記録する。段階CはPicoの`soak 60`の最終行も記録する。

## 記録表

各表の上に、source commit、`.fs`のSHA256、書込み先（Flash/SRAM）を書く。

### 段階A: `hdmi`（480p）

source: / SHA256: / 書込み先:

| 組合せ | 起動 合格/20 | 抜挿 合格/10 | reset復帰 | 1時間（開始〜終了） | 1時間後L | 判定 |
|---|---|---|---|---|---|---|
| S1×C1 | | | | | | |
| S1×C2 | | | | | | |
| S2×C1 | | | | | | |
| S2×C2 | | | | | | |

### 段階A: `hdmi720`（720p）

source: / SHA256: / 書込み先:

| 組合せ | 起動 合格/20 | 抜挿 合格/10 | reset復帰 | 1時間（開始〜終了） | 1時間後L | 判定 |
|---|---|---|---|---|---|---|
| S1×C1 | | | | | | |
| S1×C2 | | | | | | |
| S2×C1 | | | | | | |
| S2×C2 | | | | | | |

### 段階B: `demo`（480p）・`demo720`（720p）

source: / SHA256（demo）: / SHA256（demo720）: / 書込み先:

| 構成 | 組合せ | 起動 合格/5 | 抜挿 合格/3 | reset復帰 | 1時間（開始〜終了） | 1時間後L | 判定 |
|---|---|---|---|---|---|---|---|
| demo | S1×C1 | | | | | | |
| demo | S2×C1 | | | | | | |
| demo | S1×C2 | | — | — | — | — | |
| demo | S2×C2 | | — | — | — | — | |
| demo720 | S1×C1 | | | | | | |
| demo720 | S2×C1 | | | | | | |
| demo720 | S1×C2 | | — | — | — | — | |
| demo720 | S2×C2 | | — | — | — | — | |

### 段階C: `spi`/`qspi`＋Pico `soak 60`

| 構成 | 組合せ | SCK | `soak`最終行 | 1時間後L | 判定 |
|---|---|---|---|---|---|
| spi | S1×C1 | | | | |
| spi | S2×C1 | | | | |
| qspi | S1×C1 | | | | |
| qspi | S2×C1 | | | | |

## 不合格・異常の記録

| 日時 | 構成 | 組合せ | 手順/回 | 症状（V/B/A/Lのどれか、sink表示） | 復帰方法 |
|---|---|---|---|---|---|
| | | | | | |

## 範囲外・未測定

- 入力停止時の無音挿入/復帰は、固定test toneのため実機では起こせない。simulationの証拠は[音声packet統合評価](audio-packet-integration.md)。カラーバー版の手順3はreset起因のmute/復帰だけを確認する。
- 周波数・jitter・TMDS電気特性・sinkが受け取ったInfoFrameの内容は計測器なしでは未測定。
- TCL製テレビは公式サンプルでも無信号のため、合格判定の対象機種とは別に原因調査として扱う（[検証状況](validation-status.md)）。
