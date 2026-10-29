# TileFramebuffer：320×240・4bpp疑似フレームバッファ

ABI 0.6の全1,200パターンを、40×30セルへ一対一に割り当てる。RTL、レジスタ定義、プロトコルの変更はない。画面は480p bitstream（論理320×240）専用。720pはconstructorで拒否する。

## 使い方

```python
from kagura import connect
from kagura.framebuffer import TileFramebuffer
from kagura.video import Video

# 既存console/PIOがある場合は新規connectせず、そのdeviceを再利用する。
dev = connect(mode='qspi', baudrate=5_000_000)
fb = TileFramebuffer(dev, palette=0)
video = Video(dev)
for n in range(16):
    video.palette(n, n * 0x111)  # 例：16段階のgray
fb.initialize()
fb.fill(0)
fb.line(0, 0, 319, 239, 15)
fb.fill_rect(16, 24, 80, 40, 6)
fb.circle(160, 120, 48, 12)
fb.text('KAGURA 1200', 8, 8, 15)
stats = fb.flush()
```

既存HDMI REPLを利用中は`kagura_console.pause()`してから、そのdeviceを使って描画する。終了後の`resume()`はconsole用map・字形・palette等を再構築する。Framebufferは全patterns/mapを専有するため、console、TextLayer、独立sprite用patternの所有者と併用しない。`initialize()`はsprite表示とraster scrollを無効化する。PCM等の音源設定は変更しない。

## RAMと配置

- `buffer`：38,400 Bのtile-native `bytearray`。線形framebufの二重保持はしない。
- `dirty`：1,200 B、0=clean／1=dirty。直接値を書かず描画API／`mark_dirty()`で管理する。
- 初期化用scratch：128 Bのmap row＋256 Bの上位bit表。その他memoryview・object・統計dict等。
- flushの確定時に最大1,200 Bの一時zero列を使う。全画面コピーは生成しない。
- `text()`だけ8 Bの文字bitmap scratchを使う。字形patternを追加確保せず、描画bufferへ画素を書き込む。

画素(x,y)は`tile=(y//8)*40+x//8`、`offset=tile*32+(y%8)*4+(x%8)//2`。偶数Xが上位nibble、奇数Xが下位nibble。隣の画素は保持する。0番色はVDPでは透明なので、BACKDROPを指定paletteの色0へ設定することで16色描画として扱う。

パターン転送は既存`Video.tiles()`を呼ぶ。0～1023は`0x0000`～`0x7FFF`、1024～1199は`0xB000`～`0xC5FF`へ既存SDKが分割する。描画コード内へ同じaddress分割を再実装していない。

## APIと境界規則

座標・幅・高さ・半径は整数。色とpaletteは0～15で、不正な値は描画前にValueError／TypeError。画面外pixel書込みは無視し、読出しはNone。幅／高さが0以下の矩形・線分幅はno-op。半径は0以上、負数は拒否する。

| API | 動作 |
|---|---|
| `TileFramebuffer(device, palette=0)` | ABI 0.6・高さ240を検査しRAMを確保。FPGA I/Oはしない |
| `initialize(show=True)` | PATTERN_COUNT=1200を検査し、表示停止、map全32行と上位表、scroll、backdrop、全patternを設定後に表示。`show=False`なら停止のまま |
| `pixel(x,y,color)`／`pixel(x,y)` | nibbleを書込む／色を読む |
| `fill(color)` | 全画面。値が変わったtileだけdirty |
| `hline(x,y,width,color)`／`vline(x,y,height,color)` | clipした水平／垂直線 |
| `line(x0,y0,x1,y1,color)` | 両端を含む整数Bresenham。外側の画素は描かない |
| `rect(x,y,width,height,color)` | 外周。右下は(x+width-1,y+height-1) |
| `fill_rect(x,y,width,height,color)` | clipした塗りつぶし矩形 |
| `circle(x,y,radius,color)` | 整数midpointによる外周。radius=0は1 pixel |
| `text(value,x,y,color)` | MicroPython built-in 8×8 printable ASCII、透明背景 |
| `mark_dirty(x=0,y=0,width=320,height=240)` | `buffer`を直接編集した後、clipした矩形のtileをdirtyにする |
| `flush()` | dirty連続runを転送しFENCE。統計dictを返す |
| `last_flush` | 直前のflush／途中で失敗したflushの統計 |

全描画はローカルRAMだけを変更し、未変更画素ではdirtyを立てない。`buffer`の直接編集には明示的な`mark_dirty()`が必要。単一owner専用で、割込みや別taskからの描画は行わない。既存soft console callbackは`device.busy`を尊重する。`line()`は元の線分長、`circle()`は半径に比例する処理なので、極端に大きい画面外座標・半径はCPU時間を消費する。

`ellipse()`、`blit()`、`paint()`は初期版では未実装。Flood Fill用の無制限stackや第2framebufferは持たない。

## Viper描画backend

RP2040のMicroPythonでは内部`framebuffer_viper.py`が利用できると自動選択する。PCは従来のPure Python実装。公開描画API・例外・tile-native配置は同じで、既存の呼出しは変更不要。

```python
fb.set_viper(False)  # Pure Pythonで描画
fb.set_viper(True)   # Viper必須。利用不可ならRuntimeError
fb.set_viper()       # 自動選択へ戻す
print(fb.viper_enabled)
print(fb.kernel_counts)  # rect系/pixel/line/circle/glyphのnative内counter
```

切替えは描画・転送が実行されていない時に単一ownerで行う。bufferとdirtyはそのまま保持し、切替え自体はFPGA通信をしない。自動fallbackはmodule読込み時の利用不可に限り、描画途中の例外を隠してPythonで自動再実行することはない。

Viperは内部kernelであり、アプリケーションから直接呼ばない。Python側で型・色を検査してからrectを[0,320]×[0,240]へclipする。完全に覆われたtileはaligned `ptr32`で8 word＝32 Bを比較・更新し、変化があったtileだけdirtyにする。端tileは`ptr8`で2 pixel／byteを処理し、片側nibbleを保つ。水平・垂直線は同じrect kernel。通常の線・円はprimitive全体を1回のnative呼出しで処理し、文字は8 B bitmapを1字形単位で処理する。

lineの端点はBresenhamの位相を変えないため切り詰めない。各座標が±32767以内ならnative、範囲外は従来の任意精度Python演算を使う。nativeのdx/dyは最大65534、twice-error等も32bit内。circleも中心座標±32767・radius<=32767に限定し、大きい入力はPythonに戻す。glyphは見えるものだけx=-7..319、y=-7..239を渡す。巨大座標や負数をそのままpointer indexへ変換しない。

呼出し中のbuffer・dirty・params・counter・文字bitmapはPython側のownerが保持する。RP2040のbytearrayと32 Bのtile offsetはword aligned。アプリケーションがbufferをresize／別のunaligned viewへ置き換えることや、別taskから並行変更することはサポートしない。診断では32 B前後guardを持つaligned viewも検証する。

追加payloadはsigned params24 Bとnative内counter20 B。実測constructor heap差分は従来40272 B→40448 B（+176 B、object等を含む）。native moduleの読込みは別途4832 B。全画面bufferを追加確保しない。`flush()`、FENCE、COMMIT、通信高速化は変更しない。描画Viperを無効にしても、transportのViper FIFO／DMAは独立に利用できる。

[両backendの差分・guard・実機性能](framebuffer-viper-results.md)を参照。

## 初期化・転送と失敗

constructorは全RAMを確保してからdeviceを保持し、MemoryError時にFPGAを変更しない。`initialize()`は表示停止をCOMMITで適用してから、40×30の各セルへ固有tile番号、固定palette、反転なしを設定する。64×32の余ったセルと上位bit表の余りは0。mapと上位bit表が揃い、全patternのFENCEが完了してから表示を有効化する。

初期化中の例外では`initialized=False`、dirty全1200枚とし、表示停止をbest effortで要求する。切断等で停止要求も失敗し得るため、初期化失敗後の画面内容は保証しない。原因を解消してから利用者が`initialize()`を明示的に再実行する。元の例外は隠さず、失敗したcommandを自動再送しない。

`flush()`は連続dirty runをまとめて`Video.tiles()`へmemoryviewを渡し、そのrunのFENCEとerror検査が成功してからdirtyを解除する。前のrunだけ成功して次が失敗した場合、成功runだけcleanとなる。1023／1024跨ぎrunは物理2領域へ分割され、片方だけ送れてもrun全体のFENCE前なら全体をdirtyのまま残す。timeout後はdevice／linkの状態を確認して、明示的に次の`flush()`を行う。操作中はdevice.busyを保持しfinallyで戻す。

**pattern RAMにdouble bufferはない。** 通常flushは表示中のpatternを直接変更し、tear-freeや画面全体の原子的な反映を保証しない。COMMITはdisplay／scroll／palette等のshadowを反映するもので、描画bufferのswapではない。必要なら利用者が表示停止→flush→表示再開を選ぶ。

## 統計の意味

`tiles`はFENCE後に確定したtile数。`bytes`／`runs`／`writes`は要求したpattern byte数・連続run数・物理pattern write数で、失敗時は実際にどこまで届いたかを表す値ではない。正常な全画面は1200 tiles・38400 bytes・1 run・2 writes・1 fence。dirty 0ならFPGA通信0件・FENCE 0件。

- `transfer_us`：`Video.tiles()`にかかったホスト時間。address／INC設定、既存write_memoryのerror確認、DMA／PIO待ちを含む。純粋なQSPI wire時間ではない。
- `wait_us`：FENCE送信・tag待ち・error確認を含むホスト時間。FPGA内部の実行時間だけではない。
- `total_us`：dirty走査、転送、FENCE、確定処理を含むflush全体。

ベンチマークは別途、実transportのread／write call数とregister payload byte数を数える。protocol header／dummy cycleはそのbyte数に含まない。CPU側描画時間はflushから分離して測る。

## 診断・ベンチマーク

`examples/framebuffer_diagnostic.py`にA=全1200枚と四隅、B=16色・線・矩形・円・clip、C=1023／1024／1199のsceneを用意した。Scene Aはすべてのtileの下2行へ11bit位置codeを残し、四隅は上側の3×5字形、下2行は位置codeとして分離する。ラベル部分も含め1200個のpatternが一意であることをPCテストで確認する。

```python
from framebuffer_diagnostic import Session
import framebuffer_benchmark
s = Session(sdk='kagura', accelerated=True)
framebuffer_benchmark.run(s, seconds=300)
# 測定終了後はscene AとPCMを保持。観察が終わったら:
s.scene('B')
s.scene('C')
s.close()
```

microbenchmarkは1／10／100／1200連続tile、長いline、大面積fill_rectを測る。連続区間は移動矩形・点滅cursor・window枠を描き、PCM 2ch、ERROR_CODE、audio FIFO、frame counter、GCを監視。平均と最大は全iteration、p95は固定ringに残る直近最大256 iterationについての実測値。GC sampleも同じ規則。サンプル数を無制限に増やさない。HDMI counterの約60 Hz、application loopのHz、物理的に画面へ反映された更新数は別物で、後者は未測定ならnullとする。

`Session.verify(full=True)`は全38400 B、全map4096 B、上位表256 BをFPGAから読み戻し照合。`full=False`はpattern512 Bの境界sampleであり全量確認ではない。

## 実機への配置と復帰

検証用にはcanonical `/lib/kagura`を保持し、必要なSDK moduleを同じ相対importのまま`/lib/kagurafb/`へ配置する。診断2ファイルはrootへ置き、PCとPicoのSHA-256を照合する。`Session(sdk='kagurafb')`で利用可能。

既存console／描画sessionを停止してPIOを解放する。検証済み`qspipsram`の480p bitstreamをGowin SRAM Program and Verify（`--run 4`）で一時構成する。SDKとFPGAのABIをprobeで照合し、PATTERN_COUNT=1200、高さ240を検査する。FlashとPico firmwareは書き換えない。

終了時は`s.close()`でPCM停止・アクセラレータ解除・PIO解放を行う。Gowin `--run 1`で変更していないFlashの元構成へ戻し、Picoをsoft resetして既存boot.pyとconsoleを復帰させる。測定中断後も、未確認の転送を自動再送しない。

[検証結果・実測性能](framebuffer-results.md)を参照。
