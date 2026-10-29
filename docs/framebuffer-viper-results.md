# TileFramebuffer Viper描画高速化：実装・実測結果

2026-10-29。基準`0929059`、branch `experiment/tile-1200`。描画kernelとfallback／初期計測は`a84d50b`、native上限検査は`f97c949`、同一PCM負荷のflush比較は`5317295`。[API](framebuffer.md#viper描画backend)、[全実測値・sourceとログhash](framebuffer-viper-results.json)。

RTL・ABI 0.6・レジスタ定義・board／bitstream設定・通信プロトコルは変更なし。`initialize`／`mark_dirty`／`flush`／`_flush`は基準とAST一致を検査した。Viperは描画だけに使用し、FENCEやerror確認を省かない。

## 実装

`framebuffer_viper.py`にrect／pixel／line／circle／glyph kernelを追加。fillとfill_rectの全包含tileは32bit×8 wordで比較・更新し、端tileはnibble保持で処理する。値が変わったtileだけdirtyとする。線・円はprimitive全体、文字は字形単位でnative処理し、Pythonから各画素を繰り返しnative呼出しする実装にはしない。利用者がpixel APIを連続呼出しする場合はPython側検証が残る。

`set_viper(None/False/True)`でauto／Python／Viper必須を切替え、`viper_enabled`で確認する。大きい座標・半径はPython演算へ戻し、境界のBresenham位相や例外を保つ。追加の線形画像や新しい描画機能は持たない。kernel入力範囲とbuffer寿命は[APIの安全性説明](framebuffer.md#viper描画backend)を参照。

## 条件とCPU描画比較

Pico RP2040、CPU125MHz、custom MicroPython1.26.0、QSPI5MHz、480p・320×240。基準と同じbitstream。両描画backendで同じViper FIFO／DMA（chunk128）を有効化。CPU計測中のPCMは両方停止、flush比較・連続負荷では両方PCM2ch稼働。CPU時間と転送／FENCE待ちは別計測。

各10回。表示値はms、倍率はPython平均／Viper平均。標準偏差は母分散の平方根。全sample・分散(us²)・p95はJSONに保存し、loop overhead等を差し引いていない。

| 処理 | Python平均 | Viper平均 | 倍率 | Python標準偏差 | Viper標準偏差 | Python最大 | Viper最大 |
|---|---:|---:|---:|---:|---:|---:|---:|
| pixel_1024 | 358.947 | 343.290 | 1.05× | 0.185 | 0.228 | 359.213 | 343.666 |
| hline | 7.137 | 1.271 | 5.62× | 0.053 | 0.041 | 7.293 | 1.391 |
| vline | 44.946 | 1.539 | 29.21× | 0.078 | 0.056 | 45.139 | 1.705 |
| line | 66.857 | 1.923 | 34.77× | 0.062 | 0.100 | 66.979 | 2.222 |
| fill_rect | 1239.183 | 7.672 | 161.52× | 0.071 | 0.064 | 1239.288 | 7.858 |
| fill | 519.905 | 9.171 | 56.69× | 0.022 | 0.016 | 519.970 | 9.217 |
| circle | 57.309 | 2.052 | 27.93× | 0.137 | 0.067 | 57.696 | 2.250 |
| text | 76.468 | 6.506 | 11.75× | 0.125 | 0.100 | 76.771 | 6.799 |

lineは(0,0)→(319,239)、fill_rectは(16,16)・288×208・色5で基準と同じ。hlineは320 pixel、vlineは240 pixel、fillは全320×240、circleは中心(160,120)・radius80、textは17文字`KAGURA 1200 Viper`。pixel_1024は重複を含む1024回のpublic API呼出し。各sample前に同じ0番色へ戻し、dirtyをreset、GC後に計測した。

基準記録のline 66.027 ms／fill_rect 1236.910 msに対し、今回のPython対照も66.857／1239.183 msで近い値。Viperは通常目標（line<10ms、fill_rect<100ms）と挑戦目標（<5ms、<20ms）の双方を満たす。pixel API単位では型・色の検証やPython呼出しが支配的で改善は約1.05倍。高速化倍率を他のprimitiveから流用しない。

## flushの比較

PCM2chを両方で稼働し、共通のuntimed準備・同じdirty tile数・同じデータ・GC後の条件で各10回測定。時間にはSDK command／error読出し等を含み、純粋なwire時間・FPGA実行時間ではない。

| dirty tile | Python flush平均 ms | Viper flush平均 ms | 差 % | pattern writes | register write/read calls |
|---:|---:|---:|---:|---:|---:|
| 1 | 14.162 | 14.259 | +0.684 | 1 | 5 / 6 |
| 10 | 14.938 | 14.940 | +0.013 | 1 | 5 / 6 |
| 100 | 21.987 | 21.972 | -0.070 | 1 | 5 / 6 |
| 1200 | 114.857 | 114.713 | -0.125 | 2 | 8 / 7 |

全画面と部分flushは同程度。1 tileの平均差は約0.1 msで、全画面はViper側が約0.14 ms短い。flush処理そのものはAST一致、同じ通信回数・FENCE・error検査で、描画backendを条件分岐に使わない。基準の113.030 msはPCM開始前の別条件であり、この同一PCM負荷の約114.7～114.9 msと混ぜて比較しない。clean flushは両方とも実transportのwrite/read calls=0を検査し、dirty.findの時間もJSONへ保存した。

## 連続描画・PCM

両方同じ300秒、移動矩形・window枠・cursor点滅・PCM2ch。平均／最大は全iteration、p95は直近最大256 sample。iterationはCPU描画・転送・telemetry・定期GCを含み、10秒ごとの進捗ログ出力は除く。application Hzは全壁時計、HDMI counter Hzは別に記録し、実際の画面反映Hzは未測定(null)。

| backend | 秒 | 更新数 | updates/s | CPU描画平均 ms | iteration p95 ms | iteration最大 ms | GC後heap B |
|---|---:|---:|---:|---:|---:|---:|---:|
| Python | 300.156 | 1253 | 4.174 | 127.593 | 258.133 | 329.032 | 104272～104384 |
| Viper | 300.058 | 2523 | 8.408 | 6.983 | 137.637 | 209.984 | 105520～105632 |

両方ERROR_CODE=0、audio FIFO異常0、PCM ACTIVE維持。Viperの描画が短くなった後は、既存のtransfer／FENCE待ちが更新周期の大きい部分を占める。ここを削るためのprotocol変更やerror省略はしていない。

## 正確性・安全性・実行証拠

- PC：既存独立線形参照描画器との76800画素比較、同じkernel sourceの範囲検査pointer実行。1024組の固定seed図形と重複描画、全bufferとdirty完全一致。±32767のnative境界と、それを超えるPython fallbackも検査。これはnative実行とは区別する。
- Pico：1074操作のbuffer38400 Bとdirty1200 Bの履歴CRCがPC参照`3474596942`と一致。最終plane CRC`569902760`。実fontのprintable ASCII・clip・重複描画も両backendでCRC`3371118220`一致。
- Picoのbufferとdirtyの前後32 B guardは無傷。native内counterはrect／pixel／line／circle／glyphすべて増加。Python対照区間の描画native counter差分は0。
- 両backendとも全1200 tile・38400 B、map4096 B、上位表256 Bの実VRAM読戻し一致。1023／1024／1199の境界sampleも一致。
- SDK 156件（Framebuffer34件）、RTL61件すべて合格、skip0。公式PIO assembler／font原本を含む既存回帰を維持。全SDK／examplesのRP2040 armv6m compile成功。

メモリはnative module読込み4832 B、constructor heap差分40448 B（基準40272 Bより+176 B）。params24 B・counter20 B等を追加し、描画planeは38400 Bの1面だけ。Pico guard診断は元planeを解放してからguard付きの1面を確保し、2面を同時保持しない。

## 目視・復帰・制限

ユーザーがPython／Viperの同じ図形・16色・線・矩形・円・clipを確認し、同じ表示・音声正常と回答。Viper全40×30・四隅・右下と、1023／1024／1199境界も確認済み。観察者はユーザーで、エージェントがHDMI画像を取得したという記録ではない。

独立`/lib/kaguravip`へ配置してSHA-256を照合し、canonical `/lib/kagura`、boot.py、Pico firmware、FPGA Flashは上書きしていない。終了時はPCM停止・アクセラレータ解除・PIO解放、未変更Flashから元構成をreload、Picoをsoft reset。起動bannerは出たがWindows COM7がtimeoutしたためユーザーがPico USBを抜き差しし、その後console active・ABI0.5・CAPS0x7B・ERROR_CODE=0を確認した。

追加の新描画機能はない。pattern RAMの非double-buffer／tear-free非保証、ASCIIのみ、大きい入力のPython処理時間等の制限は維持する。連続試験は各5分で、追加の1時間・別sink／ケーブル・温度試験は未実施。

## 再現

```python
from framebuffer_diagnostic import Session
import framebuffer_benchmark as bench
s = Session(sdk='kaguravip', accelerated=True, viper=False)
bench.compare_draw(s, repetitions=10)
for enabled in (False, True):
    s.fb.set_viper(enabled)
    bench.run(s, seconds=300)
bench.compare_flush(s, repetitions=10)  # PCM activeのまま両modeを測る
s.close()
```

native CRC検証は`framebuffer_viper_validation.run(sdk='kaguravip', expected=...)`、共通caseは`framebuffer_viper_cases.py`。PC参照生成と実機ログは`reports/framebuffer-viper/`、回帰ログは`build/viper-framebuffer-*.log`（Git管理外）。配布sourceとログhash・全sampleはJSONで追跡する。

完了条件11項目（互換性・全画素一致・dirty一致・範囲検査・PC試験・Pico native実行・性能・flush比較・既存回帰・文書化・元環境復帰）を満たした。
