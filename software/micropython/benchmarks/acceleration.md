# OAM Viper化と512byte DMA転送の調査（2026-10-29）

RP2040 Pico 125MHz、MicroPython v1.26.0-1.g3069c562f、720p／QSPI 5MHz。
BGM・効果音の曲、音量、ゲーム内容は変更していません。

## DMAの15.35msはどこで使われるか

従来ゲームのOAM転送約15.35msを調べるため、同じ64 OAM＋PCM BGMの状態を作り、
`write_memory(0xA000, 512byte)`を64回計測しました。各回の前後でqueueをFENCEし、
GCとFENCEは計測区間の外です。計測器の追加により全体値は約16.19msになっています。

| 区間 | 通常版 ms/write | Viper展開 ms/write |
|---|---:|---:|
| DMA用ワード列の展開（4×128byte） | 6.873 | 0.465 |
| RX/TX DMA設定（合計） | 0.383 | 0.374 |
| RX DMA完了待ち（合計） | 0.244 | 0.250 |
| INC設定のtransport呼出し | 1.654 | 1.719 |
| VRAMアドレス設定のtransport呼出し | 1.525 | 1.523 |
| ERROR_CODE読出しのtransport呼出し | 1.849 | 1.878 |
| payload transport全体（上のDMA区間を含む） | 9.002 | 2.645 |
| write_memory全体 | 16.192 | 9.911 |

**主因はDMA待ちではなくPythonでの展開と短いレジスタ操作です。**
上のpayload区間とその内訳は重複するため足し合わせません。未分類のAPI処理・計時自体もあり、
個別の計測器オーバーヘッドは未校正です。DMA待ちが小さいのはこの実測条件の結果で、
すべてのPSRAM負荷で待ちが小さいと一般化はしません。

## 実装

- [`shooter_oam_viper.py`](../examples/shooter_oam_viper.py): OAM全体を構築する任意選択のViperカーネル。
  通常版と同じ優先順位・culling・HUD・符号付き座標・負荷低下時の末尾disableを実装します。
- [`kagura/dma_pack.py`](../kagura/dma_pack.py): byteからPIO用wordへの展開をViper化。
  SPI／QSPIのtableとqueued flagをそのまま使い、既存のword列を保ちます。
  非byte要素のbufferは従来の要素単位Python処理へ戻します。
- DMAのRX/TX設定・完了待ち・progress timeout・保守的な`completed`算出は共有helperへ移し、
  ロジックを維持。CS処理・abort・PIO命令列・SCK設定は従来のtransportが所有します。
- 新しいdriverは利用可能な場合にViper展開を使います。公開Kagura APIに変更はありません。
  凍結ドライバのある既存UF2では、アプリ所有期間だけ同じhelperへ差替え、終了・例外時に復元できます。
  UF2の再書込み、boot.py変更、CPUオーバークロックは行っていません。

`@micropython.viper`はコンパイル構文で、実行時moduleに`viper`属性があるとは限りません。
その属性の有無で有効判定せず、RP2040向けに実際にコンパイルして検証しています。
CPythonのdriverテストはPython参照版を使用します。

## ゲーム全体のA/B比較

全音源＋64 OAMを継続更新するHEAVY、各400更新、GC間隔4、速度上限なし。
全条件で音声error・BGM非ACTIVE観測・通常表示のoverflow・cleanup errorは0でした。

| OAM構築 | DMA展開 | 構築 ms | OAM転送 ms | 更新fps |
|---|---|---:|---:|---:|
| Python | Python | 13.327 | 15.674 | 16.45 |
| Viper | Python | 0.939 | 15.751 | 20.42 |
| Python | Viper | 13.187 | 9.235 | 18.50 |
| Viper | Viper | 0.935 | 9.275 | 23.67 |

両方有効で約44%の更新fps改善です。**30fps目標は未達**です。
両方有効の平均フレーム時間は41.94ms、p95は65.79ms、最大103.91ms。
残る平均コストは音声7.57ms、COMMIT 6.77ms、OAM転送9.27ms、移動2.32ms、GC2.29ms等です。
ここまでの結果から、さらに改善する場合は短いレジスタアクセスと音声制御が候補になります。

## 正しさと検証範囲

- ホスト試験で通常版とカーネルの参照動作を比較。CPython上のpointer代替であり、機械語試験とは区別。
- 実RP2040の機械語で、両解像度・32/64/128/256 records・追加演出OFF・負荷切替・符号付き座標・culling等のOAM 256状態をbyte単位で比較。
  OAMだけでなくband使用数・enable数・転送範囲・culling累計も一致しました。
- 実RP2040でSPI/QSPI両table、queued／非queued、途中offset、1/15/16/127/128byteの計80ケースを比較。
  low half-wordを壊さないことも検査しました。
- driverのDMA停止／timeout／abort、公式PIOアセンブラ・既存タイミングモデルは別途ホスト試験で確認します。
- 高速版の5分連続動作: HEAVY、7,027更新、23.42fps、音声error／通常表示overflow／BGM非ACTIVE観測／cleanup errorすべて0。
  平均42.41ms、直近1024更新p95 61.48ms、最大111.53ms、最小空きヒープ111,024byte。
- 高速版のCtrl-C: UART内部ループバックでKeyboardInterruptを発生させ、音源停止、REPL復帰、DMA差替え復元、ERROR_CODE=0を実機確認。
- 通常ゲームFULLも両方有効で400更新・24.81fps・音声error 0。
  EXTREME 256は100更新・20.84fps・音声error 0、意図したoverflowを7回のpollで観測。
  EXTREMEの初版400更新とは試験長が違うため、その値から厳密なfps改善率は出しません。
- 480p SPI 5MHzもHEAVY 200更新・23.35fps・音声error／overflow 0を確認。
  配布bitstreamのhash照合・SRAM Program and Verifyを経て試験し、内蔵Flashは変更せず元の720p QSPIへ復元。
  最後にPCM／PSGの停止、ERROR_CODE=0、console復帰を確認しました。
- ホスト: ゲーム／参照カーネル／buffer互換／差替え復元18件、driver57件（公式PIOアセンブラとSPI/QSPIタイミングモデルを含む）に合格。

生ログ・機械可読結果は[hardware-viper-20261029/results.json](hardware-viper-20261029/results.json)に保存しています。

Gameが所有する固定長bufferだけをカーネルへ渡します。Gameの配列形状や表示順を変更する際には、
通常版との一致試験を再実行してください。

## 使用方法

通常版は従来どおりです。OAMは通常版を既定とし、明示して高速版を選べます。

```python
import shooter
shooter.run(console=kagura_console, renderer='viper', dma='viper')
```

`renderer='python'`でOAM参照版、`dma='python'`でDMA展開の参照版、
`dma='driver'`（既定）で元のdriver設定をそのまま使います。
既存UF2用のDMA差替えはアプリ終了後に復元され、console等の通信方式は変更しません。

通常のソース配置では`shooter_oam_viper.py`と更新した`kagura/`もコピーします。
凍結driverを優先する既存UF2でアプリだけを追加する場合は、`kagura/dma_pack.py`を
Picoの`/kagura_dma_pack.py`へ配置すると互換helperとして使用できます。
RP2040向けの事前コンパイルでは**`mpy-cross -march=armv6m`**を指定してください。
このnative `.mpy`は他アーキテクチャへそのまま移せません。

再計測器: [`dma_profile.py`](dma_profile.py)、[`accel_compare.py`](accel_compare.py)。
PCでこれらを実行した時間をハードウェア性能値の代用にはしません。
