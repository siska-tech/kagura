# STAR RUNNER / RP2040 性能改善 第2段階

2026-10-29。RP2040 125MHz、MicroPython v1.26.0、ABI 0.5。
既存ゲーム・承認済みBGM/効果音・全音源・64 OAM・エラー検査を維持した。
専用Cユーザーモジュールは追加していない。

## 同一条件の比較

QSPI 5MHz、720p、HEAVY、400フレーム、入力なしの自動操縦、GC周期4、
`target_fps=0, renderer='viper', profile=True`。各版をソフトリセット後に測定した。
Beforeは従来のViper展開・128バイトDMAチャンクと毎フレームの空きメモリ照会。
AfterはFIFO一括処理・32bit展開・512バイトチャンク・GC周期での空きメモリ照会。
開始前GCと詳細計測コードは共通。PCMアセットのアップロードは計測外。

| 評価項目 | Before | After | 改善率 |
|---|---:|---:|---:|
| OAM構築平均 | 0.932ms | 0.920ms | 1.3%短縮（同じ構築kernel） |
| 512B OAM書込み平均（INC/ADDR/ERROR含む） | 9.461ms | 6.285ms | 33.6%短縮 |
| COMMIT発行平均（ERROR含む） | 4.056ms | 2.385ms | 41.2%短縮 |
| COMMIT完了確認・待機平均 | 2.580ms | 2.092ms | 18.9%短縮 |
| 音声コマンド平均 | 7.544ms | 4.599ms | 39.0%短縮 |
| 空きメモリ照会のフレーム平均 | 6.817ms | 1.748ms | 74.4%短縮 |
| 総合更新FPS | 23.155 | 35.122 | 51.7%増加 |
| フレーム間隔p95（統計処理込み・400件） | 67.606ms | 46.034ms | 31.9%短縮 |
| フレーム間隔最大（統計処理込み） | 106.596ms | 73.468ms | 31.1%短縮 |
| 音声エラー / FPGAエラー | 0 / 0 | 0 / 0 | 維持 |

生ログ: [Before](hardware-performance-20261029/baseline-final.txt)、
[After](hardware-performance-20261029/accelerated-final.txt)。平均30fps超は各フレーム33.3ms以内を意味しない。
40fpsは未達。GC、音声イベント集中、COMMIT待機が長いフレームを作る。

## 5分間の連続動作

QSPI 5MHz・720p・全音源・64 OAM・`profile=True`・GC周期4で300秒以上動作。
最終計測版で10,711更新、平均35.702fps、COMMIT発行/完了観測とも10,711回。
PCM/音声エラー0、FPGAエラー0、overflow 0、BGM停止検出0、終了復旧エラー0。
p95フレーム開始間隔46.152ms（直近1024フレーム）、最大80.555ms（全期間）。
平均28.009ms、中央値27.352ms。互換用更新区間p95は45.285msであり、上記と区別する。
空きメモリの標本最小値121,072バイト。FPGA VBlank進行18,002回は固有の画面反映数ではない。
音声キューの優先度制御による24イベントの破棄はPCM underrunやFPGAエラーと区別する。
[最終生ログ](hardware-performance-20261029/soak-final-300s.txt)。
フレーム開始間隔列を追加する前にも10,638更新・35.456fpsで完走している
（[初回ログ](hardware-performance-20261029/soak-300s.txt)）。

## 計測の整合性

`ticks_us()`/`ticks_diff()`で区間を計測し、実行中にprintしない。
フレーム全体は直近1024件、区間別中央値・p95は`profile=True`時に直近128件をRAMへ保存する。
区間別平均・最大は実行全体。詳細列は512バイトずつ確保し、REPLの断片化に対応する。
`loop_frame_*`はフレーム開始間隔で、統計処理とループ条件も含む。終了時に最終区間を閉じる。
互換用`frame_*`は従来の入力開始〜統計更新直前の区間。両者を混ぜない。
`loop_wall_mean_us`はCOMMIT末尾待ち・最終監視を含む実行時間÷更新数である。

`logic`はmovement+collisionの別名、`commit`はcommit_wait+commit_issueの別名。
これらを重複加算せず、`exclusive_stage_sum_us`と`unclassified_mean_us`の和が
`frame_mean_us`になる。未分類には計測呼出し・ループ・条件分岐などが含まれる。
`TransportMeter.transport_us`は上位区間と重複するので加算しない。
`instrument_transport=False`時の未測定値は0ではなくNoneを返す。

更新FPS、OAM payload bytes/s、COMMIT発行Hz、次回確認で観測したCOMMIT完了Hzを分けた。
FPGAフレームカウンタはVBlankの進行を示し、新しい画素が反映された回数ではない。
固有の画面更新頻度は取得できないため`actual_pixel_update_hz=None`とする。
COMMIT待機には状態読出しの固定費も含む。純粋なVBlank待機時間とは扱わない。
音声/FPGA状態は15フレームごとに監視する。エラー行のフレームは検出フレームであり、
FPGA内部で発生した瞬間のフレームは取得できない。sticky状態を読み落とさず記録する。

実機で`gc.mem_free()`は平均6.732ms、`gc.collect()`は18.096msだった
（試作モジュールを複数保持したREPL）。[単独測定](hardware-performance-20261029/gc-cost.txt)。
毎フレームの全ヒープ走査が見落とされていた。照会を既存GC周期へ合わせ、明示GC周期4は維持した。
空きメモリの最小値はその周期の標本最小値であり、毎フレームの厳密な最小値ではない。
モジュールを繰返し読み込むとGC費用も変わるため、比較は起動条件を揃える。

## 転送方式と安全性

`kagura.acceleration.Acceleration` / `PIOTransport.accelerate()`は着脱可能。
PIO命令列、CS開始/終了、READY確認、例外時の`_abort()`、FENCE、ERROR_CODE検査を維持する。
Viperは短いトランザクションのヘッダ・dummy・payloadを1回のFIFOポンプで扱う。
SPI/QSPI・SM0〜7のレジスタ配置に対応し、queued bit31、QSPI release bit30を維持する。
停滞時はticks差分でタイムアウトし、32反復ごとに`sleep_ms(0)`でCtrl-Cを処理する。
DMA転送は同期完了後にバッファを再利用し、スコープ終了で元のメソッドとバッファを復元する。

32bit展開は既存high-halfテーブルからワードを作る。FIFOへのDMA幅は32bitのまま。
RP2040の狭いIO書込みは値を複製するため、8bit DMAへの幅変更だけでは
queued/releaseフラグとデータ位置を保てない。PIOを変更する案は今回は実装していない。
現行PIOのまま30fpsを超え、通信タイミングと互換性を維持できたためである。

`examples/bench_transfer.py`はA=Python、B=従来Viper、C=32bit Viper、
D=FIFO一括+512バイトDMAで64/128/256/512/1024/2048バイトを比較する。
毎回ERROR検査、測定外FENCEと先頭/末尾8バイト照合を行う。
`profile_dma()`はpack/config/start/waitを分離する独立の計測。
開始を分離するためconfig(trigger=False)後にRX→TXを起動する追加呼出しを含み、
通常転送の総時間と同条件の数値として比較しない。

## SPI/QSPI転送マトリクス

各16回、64/128/256/512/1024/2048バイト、1/2.5/5MHz、A〜Dの計144条件。
SPIは480p+PSRAM、QSPIは720p+PSRAM。全条件ERROR_CODE=0、先頭・末尾照合一致。
各クロックのDでは非マスクのパターンRAMへ0〜255全値を書いて全域照合も通過した。
OAMは予約ビットをマスクするRTL仕様のため、有効ビットだけのデータを使う。
全長・平均・中央値・p95・最大は[CSV](hardware-performance-20261029/transfer.csv)へ保存した。
測定時はBGM停止・ゲーム停止。ゲーム内での同時負荷の結果とは条件が異なる。

512バイトwrite_memoryの平均（ms、INC/ADDR/ERROR含む）:

| 接続 | MHz | A Python | B Viper16 | C Viper32 | D FIFO+DMA512 |
|---|---:|---:|---:|---:|---:|
| SPI | 1 | 19.065 | 12.634 | 12.630 | 9.670 |
| SPI | 2.5 | 16.486 | 10.005 | 10.064 | 7.070 |
| SPI | 5 | 15.617 | 9.203 | 9.180 | 6.274 |
| QSPI | 1 | 16.094 | 9.693 | 9.697 | 6.676 |
| QSPI | 2.5 | 15.428 | 8.964 | 8.952 | 5.928 |
| QSPI | 5 | 15.117 | 8.699 | 8.686 | 5.676 |

C単独の差は小さく、測定ばらつきの範囲。大きな改善とは扱わない。
主な改善は短い通信の固定費削減とDMAチャンク拡大である。
5MHzを超える通信やPIO命令変更は試していない。

### DMA内訳（独立プロファイル）

QSPI 5MHz、512バイト、各16回。全て平均ms。

| 区間 | chunk128 | chunk512 |
|---|---:|---:|
| INC設定 | 0.833 | 0.868 |
| アドレス設定 | 0.890 | 0.928 |
| ERROR読出し | 0.808 | 0.936 |
| payload全体 | 3.160 | 2.409 |
| └ pack | 0.791 | 0.440 |
| └ DMA設定 | 0.407 | 0.136 |
| └ DMA開始 | 0.115 | 0.035 |
| └ DMA待機 | 0.258 | 0.269 |
| └ header/CS/計測等の残り | 1.589 | 1.528 |
| 外側処理・計測費用 | 1.685 | 1.804 |
| 総時間 | 7.377 | 6.944 |

payloadの下段はpayloadの内訳で、総時間へ重複加算しない。
DMA待機は約0.27msで、依然として主要因ではない。
[生ログ](hardware-performance-20261029/dma-profile.txt)。

## 音源別統合・回帰

QSPI 5MHz・720p、各400フレーム、GC周期4、詳細計測あり。
ゲームは乱数を使わず、初期状態・入力0・同じフレーム数・同じ敵/イベント生成条件。
全ケースで終了状態`(frame,x,y,score,lives,power)=(400,56,99,1900,1,1)`が一致した。
下表p95/最大は互換用更新区間（統計更新直前まで）で、`loop_frame_*`とは異なる。

| 音源 / OAM | fps | p95 ms | 最大ms | 構築ms | 書込みms | COMMIT待機ms | GC平均ms | 音声error | overflow |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OFF / 64 | 40.472 | 36.300 | 46.074 | 0.912 | 6.567 | 2.878 | 2.453 | 0 | 0 |
| PSG+Wave / 64 | 36.062 | 45.248 | 56.582 | 0.922 | 6.466 | 2.212 | 2.475 | 0 | 0 |
| PCM2 / 64 | 37.860 | 39.847 | 69.358 | 0.913 | 6.634 | 2.819 | 2.506 | 0 | 0 |
| 全音源 / 64 | 34.300 | 45.264 | 73.383 | 0.915 | 6.483 | 2.316 | 2.511 | 0 | 0 |
| 全音源 / 128 | 32.614 | 46.581 | 78.658 | 1.413 | 7.291 | 2.311 | 2.507 | 0 | 27 |

全ケースのERROR_CODE=0。128 OAMの27件は同一走査線16個制限の表示欠落であり、
通信失敗やPCMエラーとは区別する。[生ログ](hardware-performance-20261029/integration-qspi720.txt)。

計測費用の別試験（同じ400フレーム）は、通信メーター/詳細分布ともOFFで37.136fps、
メーターのみ35.173fps、両方ONで34.568fps。両方ONで約6.9%の更新レート低下。
区間ごとの基本タイマはどの条件でも有効。完全無計測のFPSではない。
この比較はフレーム開始間隔列を追加する前の版で実施した。
[生ログ](hardware-performance-20261029/instrument-overhead.txt)。

SPI 480p+PSRAMの全音源64 OAMは33.870fps、QSPI 480pは34.326fps、
SPI 720pは35.205fpsで各400フレーム・音声/FPGAエラー0。
SPI 720pの配布bitstreamにはPSRAMがないためPCMは無効、PSG+Waveのみである。
全音源のSPI 720pは今回の構成では検証していない。

SPI 480pのDMA稼働中にUART内部ループバックからCtrl-Cを注入し、
DMA内でのKeyboardInterrupt、CS high、両DMA停止、次のID読出し75、ERROR_CODE=0、REPL復帰を確認。
QSPI 720pではゲーム中Ctrl-CでPCM/PSG停止、console.resume、差替え解除を確認。
PIO停止・DMA途中停止の故障注入も、設定10msのタイムアウト後に復旧し、次のID/ERROR読出しが成功。
タイムアウトの壁時計実測は13.2/15.9msで、Python処理・復旧時間を含む。
物理的な電源断・ケーブル抜去・READY/BUSY固定の再試験は今回未実施。既存ホスト回帰を通した。

FPGAは既存リリースの検証済みハッシュのbitstreamをSRAMへ設定し、最後は元のFlash構成
（720p QSPI、user code E9C8）をreloadした。Flashへの書込みはしていない。

## 再現

```python
import shooter
shooter.run(console=kagura_console, mode='HEAVY', duration=300,
            renderer='viper', dma='accelerated', dma_chunk=512,
            target_fps=0, profile=True)
```

通常の`import shooter; shooter.run(console=kagura_console)`、既存操作、
`dma='driver'/'python'/'viper'`も維持する。音源アセット・音量は変更していない。
通常のMicroPythonへPythonソースを後付けできる。PCでnative .mpyを作る場合は
MicroPython v1.26のmpy-crossへ`-march=armv6m`を指定する。
古い凍結driverではdma_pack/fifo_xfer/accelerationをrootへ
`kagura_dma_pack`/`kagura_fifo_xfer`/`kagura_acceleration`名で追加できる。

測定スクリプトは生ログと同じディレクトリの`transfer_matrix.py`、`dma_profile.py`、
`integration_cases.py`、`instrument_overhead.py`、`dma_interrupt.py`、`fault_injection.py`、`ctrlc.py`。
接続済みの`kagura_console`があるUSB REPLへ、ホストの`tools/star-runner-device.ps1 -CodeFile ...`
で実行した。`bench_transfer.py`はPicoのimport可能な場所へ置く。
転送ベンチマークはOAMとパターンRAM 0x7000〜0x70FFを上書きする。
SPI/QSPIの切替は対応FPGA bitstreamを設定してから接続し直す。
基準版は同じ計測コードのコピーで空きメモリ照会だけ毎フレームに戻し、
`dma='viper'`を指定した。既存ゲームの処理・シードは変更していない。

## ローカル検証と残る確認

ドライバ57、ゲーム/音声/統計22、FIFO4、日本語29の計112テストが全て成功。
固定版フォントZIPを取得し、コミット済みフォントの再生成一致も確認した。
実際のPIO assemblerと既存SPI/QSPIタイミングモデル、定数生成、設計整合性、
ARMv6-M mpy-crossコンパイルも成功。Pico/Pico Wの凍結UF2は既存WSLビルドでリンク成功。
そのUF2を実機へは書いていない。実機は既存v1.26系UF2への後付けモジュールで測定した。
公式配布UF2そのものの再試験は今回未実施。追加Cモジュールや独自C APIへの依存はない。
GitHub Actionsの設定へFIFOテストを追加したが、未pushのためリモートActionsは未実行。

次の改善余地は、COMMIT/VBlank待機とGC・音声イベント集中による長いフレーム。
OAM構築は約0.92ms、DMA待機は約0.27msなので、ここだけの追加最適化で
全音源40fpsへ届くとは判断しない。エラー検査を省略する変更は採用していない。
