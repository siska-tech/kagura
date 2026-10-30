# dirty gap統合と既存DMA512の適用

2026-10-30。[事前調査](framebuffer-transport-analysis.md)の優先順位1を実装し、
優先順位2の既存DMA512設定との組合せを比較する。
RTL、ABI、通信プロトコル、FENCE、Videoのbank分割、DMA handshakeは変更しない。

## 実装と使い方

```python
# 従来の転送範囲。既存アプリはそのまま。
fb.flush()

# run間の1タイルのclean gapも送る。小転送の固定費を削減。
stats = fb.flush(max_gap=1)
```

`max_gap`は0〜1198の整数で既定0。bufferの画素は変更しない。
dirtyの連続run間にある指定サイズ以下のgapだけをdirtyへ追加する。
先頭や末尾のclean領域は追加しない。線形tile順で、行境界と1023/1024境界も対象。
計画処理は`device.busy`保持中、全てのwriteより前に行い、通常のflushへ渡す。
default 0では追加scanを実行しない。自動の全面dirty化・gap閾値の推定は導入しない。

追加gapもFENCEとerror確認が完了するまでdirtyに保持する。
部分write、FENCE timeout、FENCE後errorのいずれでもrun全体を未確定として残し、
先に完了したrunはcleanを維持する。再送は呼出し元が障害を解消して明示的に行う。
統計の`tiles`は確定済みtile、`bytes`は要求送信byteで、両方ともgapを含む。
追加bufferはgapのmark用の一時byte列のみで、全画面コピーは作らない。

bufferはVRAMの唯一の正しい描画元である必要がある。他のownerがVRAMだけを変更している
場合、その内容を保持する用途には使えない。既存の単一owner制約を維持する。

大転送用の`device.transport.accelerate(chunk=512)`は既存APIで、既定は128のまま。
既存accelerationをcloseしてから切替え、転送完了後にcloseする。
128に対してworkspaceが1536byte増える。アプリのmemory条件に応じて明示的に選ぶ。

## 比較方法と安全性

[framebuffer_gap_benchmark.py](../software/micropython/examples/framebuffer_gap_benchmark.py)は
同じSessionで(128,0)→(128,1)→(512,1)の順にchunk/max_gapを比較する。
各micro条件とScene A〜Dは30反復＋warmup3。sceneのGC/heap観測間隔は32操作。
前回の別phaseの値をcontrolにせず、その場の(128,0)を基準にする。
microはGCを各flushの前に実行し、GCをflush値へ含めない。sceneは自動GCを含む。
条件順は固定で、ランダム化cross-overではない。小さな差に一般化しない。

MicroPython v1.26.0-1.g3069c562f、CPU125MHz、QSPI5MHz、ABI0.6、320×240/4bpp、
Viper描画・FIFO・pack32、PCM2chのPSRAM loop再生を使用する。
HDMIへの物理反映頻度は未測定。PCMのhost streaming公平性や長時間rare-faultは別試験。
Scene Dは事前調査のscroll/wrap版であり、独立全画面source版との改善比較ではない。

新namespaceへのSDK全体コピーは空き容量不足で停止した。事前にnamespace未存在を確認していた
今回の不完全コピーだけを除去し、console復帰を確認した。
実測ではbaseline隔離SDK16ファイルのSHA-256を検証し、SDKの`flush`/`_flush`をASTから
そのまま取り出したsubclassをRAM上へ読み込む。描画・Video・transportは既存SDKを継承する。
canonical `/lib/kagura`と既存baseline SDKのファイルは上書きしない。
clean VMで一時的にconsole bootを抑止し、成功・失敗にかかわらずboot bytesを復元してresetする。

## 回帰

- SDK host 206件中204成功・2skip。PythonとViperで同じ新規試験を実行。
- gap閾値、先頭/末尾非追加、clean時no-I/O、不正引数、bank跨ぎのpayload/readbackを検証。
- 部分write・FENCE失敗・error確認失敗では追加gapもdirty保持。
  FENCE後errorでも前の確定runはcleanを維持し、暗黙の再送がないことを検証。
- RTLは変更なし。事前調査の61 testbench成功記録を参照し、Python変更の検証と区別する。

FENCEのgroup化、DMA/PIO handshake変更、packer guard hoist、RTL/protocolのbulk化は
今回の実装へ混ぜない。最初の2案を比較可能な単位で適用した後、残りは別変更で評価する。

## 適用判断

1タイルgapが多いことが分かる描画では`max_gap=1`、既に1 runの大転送では
`max_gap=0`＋既存DMA512を第一候補にする。dirty統合は常時有効にしない。
clean・1タイルだけ・統合可能なgapがない場合にも追加走査費が発生する。
送信量を最小にするよりrun数を減らす方が速い場合を対象に、アプリが明示的に選択する。

前回の100離散tileモデル約56msは統合CPUを除いた未実装見積りだった。
今回の統合のみ実測約65msとの違いは隠さず記録し、取得phaseとコードも異なるため
差の全てを統合CPU時間だと断定しない。
改善の小さいgameはこの閾値で結合できるgapが少なく、loop内のGC変動もある。
小差を改善として採用せず、次の候補は描画locality/cacheか、別変更でのpacker guard hoistとする。

## 実機結果

全条件は[JSON](framebuffer-gap-results.json)、exact workloadとログは[artifact一覧](framebuffer-gap-logs/README.md)。

| 条件 | DMA128 / gap0 ms | DMA128 / gap1 ms | DMA512 / gap1 ms |
|---|---:|---:|---:|
| clean | 1.040 | 1.534 | 1.507 |
| one | 15.771 | 16.302 | 16.282 |
| bank_gap | 29.082 | 21.552 | 21.807 |
| dispersed100 | 1327.449 | 65.276 | 58.859 |
| compact256 | 228.782 | 230.282 | 221.888 |
| full1200 | 116.075 | 117.133 | 77.158 |

| Scene | DMA128 / gap0 updates/s | DMA128 / gap1 updates/s | DMA512 / gap1 updates/s |
|---|---:|---:|---:|
| A | 6.177 | 6.658 | 6.763 |
| B | 4.285 | 4.273 | 4.263 |
| C | 0.957 | 1.032 | 1.034 |
| D | 1.841 | 6.426 | 8.682 |

改善率は同一Session内controlから算出する。全sample、平均・中央値・p95・最大、
sceneのdraw/flush/loop、GC、memory、送信量、transactionsをJSONに保存した。

100離散tileは100 runs/3200byteから3 runs/6304byteへ変わり、
統合のみで95.08%、DMA512併用で95.57%のflush短縮を実測した。
全面1200tileは元から1 runなので統合では速くならず、DMA512併用で33.53%短縮。
cleanの統合走査は約0.49ms、1 tileは約0.53msの追加費用だった。
gameのupdates/sは4.285→4.263で、改善とは評価しない。

## 最終状態

全pattern38400byte・map4096byte・upper256byteの読戻し照合成功。
全測定のtelemetryでERROR_CODE0、FIFO fault0、PCM2ch ACTIVE・underrun/fault検出なし。
Session.close完了後、boot SHA
`301d9cc8067d001cb812be43f9bccbd183abeacd514d21347f725a7989c497f0`
の完全一致復元とsoft reset後のABI0.6/height240/console active/ERROR0を確認。
benchmark・restore・consoleのhost exitは全て0。Flashとfirmwareの書換えは行っていない。
リポジトリのSDKには実装済みだが、実機はRAM検証であり、既存SDKへ恒久インストールしていない。
追加の全SDKコピーは容量不足で中止・専用不完全コピー除去済み。canonical SDKは未上書き。

既存の[事前ベースライン](framebuffer-transport-results.json)は更新せず保持した。
今回の基準と候補は[別JSON](framebuffer-gap-results.json)として保存し、次の変更も同様にcontrolを取り直す。
