# TileFramebuffer実装・検証結果

2026-10-29、`experiment/tile-1200`。性能測定のsourceは`3d9a916`。その後、診断の四隅ラベルだけを`f99ed46`で修正した。[API・利用手順](framebuffer.md)、[機械可読実測値](framebuffer-results.json)。RTL・FPGAレジスタ仕様・ABI 0.6は変更していない。

## 実装と変更ファイル

- `software/micropython/kagura/framebuffer.py`：320×240・tile-native 4bpp、全1200セルのmap初期化、基本図形、ASCII text、dirty連続run、FENCE後の確定。
- `software/micropython/tests/test_framebuffer.py`：独立線形参照描画器、乱数図形、nibble、四隅、境界、初期化・転送例外、memory不足、Scene Aの一意性、測定ringの上限。
- `software/micropython/examples/framebuffer_diagnostic.py`／`framebuffer_benchmark.py`：A～C、D/Eの部分更新＋PCM負荷、分離した時間と通信計数、VRAM全量照合。
- `software/micropython/manifest.py`、`.github/workflows/micropython.yml`：frozen SDKと既存CIへの追加。
- `docs/framebuffer*.md/json`、SDK README・文書案内：API、配置・復帰、結果。

RAMは描画buffer38400 B＋dirty1200 B＋map用scratch384 B。線形framebufの追加コピーはない。constructorのGC後heap差分は実測40272 B。mapは64×32の余りも0、表示する40×30はtile0～1199、palette固定・反転なし。bitmapが全patternsを専有するため独立したsprite用patternsは残らない。

## 自動検証

SDK 136件（うちFramebuffer 14件）・RTL 61件すべて合格、skip 0。公式MicroPython v1.26.0 PIO assemblerと美咲フォント原本も使った既存回帰を含む。RP2040用armv6m bytecode compileも全SDK／examplesで成功した。fixed seed 1200の100図形を線形参照描画器で描き、76800画素をdecodeして比較した。

未変更pixelはdirtyにしないこと、clean flushのFPGA通信0、1023／1024跨ぎの物理分割、部分転送後のtimeoutで未確定runをdirtyに保つこと、前のFENCE成功runのみcleanとなること、初期化途中失敗と明示的retry、allocation failure時のbusy復旧も確認した。

## Pico実測

480p `qspipsram`、QSPI 5MHz、CPU125MHz、既存custom MicroPython v1.26.0。既存のViper FIFO／DMA（chunk128）を有効化。FPGAは検証済みbitstreamをSRAMへ一時構成し、専用`/lib/kagurafb`と独立scriptを配置した。PC／PicoのSHA-256一致を確認。canonical packageとPico firmwareは変更していない。

初期化（map構築・全pattern転送・表示準備）は372.285 ms。

各5回の平均。時間はホスト側の測定で、transferにはSDKのerror読出し等、FENCE待ちにはcommand送信・tag／error検査を含む。純粋なwire時間・FPGA内部処理時間ではない。

| 更新tile | pattern byte | pattern write | CPU描画 ms | 転送 ms | FENCEホスト待ち ms | flush全体 ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 32 | 1 | 0.523 | 5.378 | 7.426 | 13.718 |
| 10 | 320 | 1 | 3.765 | 5.961 | 7.400 | 14.278 |
| 100 | 3200 | 1 | 34.874 | 13.026 | 7.428 | 21.318 |
| 1200 | 38400 | 2 | 418.908 | 104.606 | 7.436 | 113.030 |

CPU描画欄は各tileの先頭pixelを1個ずつ変更した時間。全画面の複雑な絵を描く速度ではない。register read／write call数・payload byte数、各測定のp95／最大はJSONへ保存した。

- `line()` CPU描画：平均66.027 ms、最大66.704 ms（10回）。
- `fill_rect()` CPU描画：平均1236.910 ms、最大1237.305 ms（10回）。

連続試験は300.062秒、1253更新、application 4.176 Hz。移動矩形、点滅cursor、window枠、PCM2chの複合負荷で、ERROR_CODE=0・audio FIFO異常0、PCM ACTIVE維持。pattern転送は2224032 B／9285 writes。GC後heapは114640～114752 B。

iteration平均239.090 ms、最大325.699 ms、直近256回のp95 257.124 ms。平均・最大は全iteration、p95は固定ringの直近sample。CPU描画・転送・telemetry・定期GCを含むiteration計測区間の時間で、10秒ごとの進捗ログ出力は含まない。全壁時計のapplication Hzや、画面上の停止時間とは区別する。映像frame counterは60.001 Hz。実際に画面へ反映された更新頻度は未計測（null）。

Scene Cの境界sample512 Bと、Scene Aの全38400 B、全map4096 B・上位表256 BをFPGAから読み戻し、一致を確認した。Scene Aは四隅を含む全1200枚のpatternが一意となる位置codeを持つ。

初回版からdirty走査・clearの組込み操作化とprimitive内部の重複検証削減を実施。初回と最終の生ログは別保存し、数値を差し替えていない。最終配置準備の1回目にmetadata keywordの重複追加で診断が起動停止したが、準備scriptをsource非変更に直し、全テストとSHA照合後に再実行した。FPGA faultは検出されていない。

## 目視・聴感

480pの部分更新（移動矩形・window枠・cursor点滅）とPCM音声は、ユーザーが「表示・動き・音とも問題なし」と確認。全40×30マス・右下も確認済み。四隅文字が下2行の位置codeと重なっていたため、診断を3×5字形へ変更し、codeと分離した。修正版は「表示ばっちりで問題ないですね」と確認され、4隅のtileも実機読戻し一致。図形sceneも「図形・色・つながりとも問題なし」と確認済み。境界sceneも「境界・右下・音とも問題なし」と確認。A／B／C／部分更新・PCMの目視・聴感はすべて合格。以前の720pタイル診断の合格は本driverへ流用していない。

## 制限・残作業

- pattern RAMはdouble bufferでなく、表示中flushのtear-free／原子的反映は保証しない。COMMITをbitmap swapに使わない。
- CPU描画はportable Pythonで、特に大面積fill_rectが支配的。実測値を将来のViper描画kernel等の比較基準とする。
- ellipse／blit／paintは未実装。ASCII textのみ。Flood Fillの無制限stackは確保しない。
- 連続試験は5分。1時間や温度条件・別sink／ケーブルの試験は未実施。
- 実際の画面反映Hzは未測定。HDMIの60 Hzとapplication更新Hzを同一視しない。

生ログは`reports/framebuffer/`（初回）、`reports/framebuffer-final/`（最終）、回帰は`build/framebuffer-*.log`／`build/verilator/`。Git管理外のため、source・配置file・ログhashをJSONへ保存した。

## 終了と復帰

PCM停止・アクセラレータ解除・PIO解放後、Gowin `--run 1`で変更していないFlashから元の構成を再読込みし、Picoをsoft resetした。既存boot.pyのHDMIコンソール（QSPI5MHz、UART0 RX GP1 115200 baud）が起動し、そのconsole所有deviceでABI0.5・CAPS0x7B・ERROR_CODE=0・console activeを確認した。新規connectを重ねず既存deviceを再利用する。試験用packageとscriptは隔離名で残す。

## 完了条件

320×240・4bpp、全1200枚、1023／1024分割、基本描画、dirty更新、全画面／部分更新測定、独立参照一致、既存回帰、実機診断、VRAM一致、ユーザー目視、文書化の12条件を満たした。拡張APIや追加の長時間・sink互換性試験は上記の制限として区別する。
