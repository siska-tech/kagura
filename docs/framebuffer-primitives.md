# TileFramebuffer blit／ellipse／paint：設計比較・検証・実測

2026-10-30。基準はPR #38のマージ`63f2685`（branch `experiment/tile-1200`の`53572c0`）。[API](framebuffer.md#blitellipsepaint)、[全実測値](framebuffer-primitives-results.json)。

RTL・ABI 0.6・レジスタ定義・通信プロトコル・`initialize`／`flush`は変更なし。追加はSDKの`framebuffer.py`／`framebuffer_viper.py`、PC試験、診断・ベンチマークだけ。

## 1. 設計比較と採用

評価はPC（CPython、同じ形状）での上限・使用量と、Pico実測で行った。

### blit

| 方式 | 時間 | 追加RAM | 複雑度・Viper | 境界・dirty |
|---|---|---|---|---|
| A. pixel単位 | 76800回のnibble read/modify/write。最遅 | 0 | 単純 | 透過・重複とも素直 |
| B. 行単位のnibble／byte転送 | 偶数ずれならbyte（2 pixel）単位 | 0 | 中。端nibbleの保持が要る | 透過はbyte内2判定 |
| C. tile整列時の32 B block | 8 word比較・更新で1 tile | 0 | 単純。ただし8 pixel整列のtile形式だけ | 非整列・線形画像に使えない |
| **D. 混合（採用）** | 整列度ごとにC＞1 tile行＝1 word＞byte＞nibble | 0 | 1つのViper関数内で分岐 | tile単位のchange判定でdirty |

採用：D。転送元形式は**GS4_HMSB線形**（MicroPython `framebuf`と同じ配置。アイコン・GUI部品を既存toolで作れる）と**TILE4**（KAGURA pattern順。block copyができ、既存pattern資産をそのまま使える）、および`TileFramebuffer`（自己blit＝scroll・領域copy）。第2の常駐planeは持たない。

- 重複は「転送元を先に全部読む」意味（memmove）に固定した。転送元が上（左）にあるときは下（右）から処理する。pixel・byte・word・tileのどの粒度でも同じ規則で、Python版とViper版の結果は一致する。
- 透過色はword copyを無効にし、byte／nibble単位で判定する。
- 4 B境界にない転送元（`memoryview`のずれたslice等）はword readしない。RP2040のCortex-M0+では非整列word accessがfaultするため、`uctypes.addressof`で判定する。

### ellipse

| 方式 | 輪郭の性質 | `circle()`との関係 | 32bit上限 |
|---|---|---|---|
| A. 半画素拡大楕円`x²/(rx+½)²+y²/(ry+½)²≤1`の4近傍境界 | 8連結・転置対称・塗り＝輪郭＋内部 | 半径1～399の391個で不一致（r=1が3×3の環） | 4rx²ry²程度 |
| B. 古典midpoint ellipse（傾き1で領域分割、丸めた値で切替） | rx=1・ry≥8等の細い楕円で行が欠け、非連結（70×70中234組） | 半径0～399で全一致 | 同上 |
| **C. 行丸め∪列丸めのspan、輪郭はその4近傍境界（採用）** | 8連結・1画素幅・転置対称、70×70全組で欠けなし | 半径0～299で全画素一致 | 誤差項を増分更新し`9(rx+1)(ry+1)(rx+ry+2)<2^31` |

採用：C。ある行の半幅を「その行で楕円に最も近い画素」と「各列で最も近い画素がその行以上にある最大列」の大きい方と定義した。円では八分円ごとに丸める`circle()`と同じ点集合になり、細い楕円でもBのような欠けがない。塗りつぶしはこの半幅のspan、輪郭は塗り領域の4近傍境界なので、輪郭＋内部＝塗りつぶしが常に成り立つ。

- Viper：行b=0..ryを1回の呼出しで進め、行丸めと列丸めの2つの誤差項を加減算だけで更新。可視行だけをword／byte／nibble spanで描く。浮動小数点なし。
- 上限を超える半径・中心（±32767外）はPython。可視の最大240行だけを整数Newton平方根の閉形式で計算するので、半径2^31-1でも処理量は画面サイズで抑えられる。上限は保守的で、PCの範囲検査実行では半径475の円で中間値の最大は約0.86×10^9、上限外の半径700では実際に32bitを超えることを確認した。

### paint

| 方式 | 作業メモリ（320×240） | 速度 | 安全性 |
|---|---|---|---|
| 4近傍pixel stack／queue | 最悪76800要素（≥300 KB） | pixel毎にpush/pop | RP2040では不可 |
| Scanline（行span単位、行ごとに再走査） | 同上の上限は小さいが未確定 | 速い | 上限を決められない |
| Span fill＋**固定容量stack（採用）** | 1要素4 B×2048＝8 KB固定 | span単位 | 上限を超えても破綻しない |

採用：Heckbertのseed fillを基に、固定容量で完了しやすくする3つの変更を加えた。いずれも「既に塗られた／元の色でない画素は元の色へ戻らない」ことだけを使い、塗られる画素の集合は変えない。

1. 対象行のsegmentに元の色が1画素もなければpushしない。
2. 継続（同方向）を先に、漏れ（逆方向）を後にpushする。漏れが先にpopされ、上段に残った未処理要素を先に満たす。
3. 満杯時は、対象segmentに元の色が残っていない要素を順序を保って除去してから積む。

| 形状（PC、容量無制限） | 元のHeckbert peak | 1のみ | 採用版 peak |
|---|---:|---:|---:|
| 矩形8×8～全画面 | 5 | 4 | 4 |
| 1画素幅の蛇行通路（38520 px） | 62 | 1 | 1 |
| 3画素通路の迷路（80×60 cell） | 114 | 71 | 71 |
| 櫛形（1画素の歯160本） | 160 | 160 | 160 |
| 40%壁の雑音 | 471 | 263 | 290 |
| 4画素周期のhatch（横線＋短い縦線） | ― | 9600 | 512で完了（compaction 29回） |
| 10～35%壁の1画素雑音（24例） | 最大4670 | 最大3782 | 2048で全例完了 |

容量2048（8 KB）を既定とした。通常のGUI・迷路形状は300未満で、compactionも起きない。容量を超えると捨てたsegmentを数えてFalseを返す（[API](framebuffer.md#paint)）。事前に必要量を見積もるには領域の走査そのものが必要なので行わず、「固定上限＋失敗時の一貫した部分状態」を仕様とした。stackはpaintの初回に確保し、確保失敗はMemoryErrorで画素・dirtyとも無変更。描画中にheapを確保しない。

## 2. 正確性と安全性

PC（`tests/test_framebuffer.py`、69件）：

- 既存の独立した線形参照描画器を拡張した。blitは転送元を先に辞書へ読むsnapshot実装、ellipseは半幅を使わない閉形式の内外判定、paintは無制限BFS。76800画素を全比較する。
- 各操作の前にdirtyを0にし、**変化したtileとdirtyの完全一致**を検査（立て過ぎも漏れも不可）。
- blit：線形・tileの乱数画像、stride、部分矩形、透過色、画面外・clip、1023／1024／1199、自己blitの全方向（±1、±3、±8、16 pixel）と全画面scroll、同一内容でdirty 0、不正形式・不足buffer。
- ellipse：乱数の輪郭／塗り、`circle()`との一致、半径0、四隅、四象限対称、同じ楕円の再描画でdirty 0、半径2^31-1・中心±2^70、輪郭の内部をpaintすると塗りつぶしと一致。
- paint：10形状と乱数領域をBFSと照合、統計の画素数、no-op、容量2～16での部分状態（変化画素⊂領域・全て指定色・dirty一致）、確保時MemoryErrorで無変更、stack再利用。
- Viper：同じkernel sourceを範囲検査pointerで実行し、上記すべてをPython版と全画素・dirty・`last_paint`まで比較。native access幅を数えて、tile整列時は1 tile＝8 word、X整列は1行＝1 word、偶数ずれはbyte、奇数ずれはnibbleで処理し、非整列の転送元をword readしないことを検査。局所変数を行ごとに追跡して32bitを超えないこと（ellipseは上限境界、blit・paint）を検査。前後32 Bのguard付きplane・dirtyと、前後8 wordのguard付きpaint stack（容量3でcompaction／dropを強制）。
- SDK全体：driver60、framebuffer69、accept2、shooter27、fifo4。skip0。全SDK／examplesのRP2040 armv6m compile成功。

Pico実機の結果は「4. 実機検証」に記す。

## 3. 性能目標

方式比較の段階で、Viper化後の目標を次のように置いた（Python比の倍率ではなく、アプリケーションの1更新内で使える絶対時間を重視）。

- 小さなicon（8×8～16×16）：既存の1回呼出し（`hline` 約1 ms）と同程度、3 ms以内。
- 64×64・160×120の整列blit：10 ms以内。全画面の整列scroll：既存`fill()`（約9 ms）の2倍以内。
- 楕円：画面大の輪郭5 ms以内、塗りつぶしは同面積の`fill_rect`程度。
- paint：全画面の実flood fill 50 ms以内。迷路・櫛形など最悪級でも1秒未満。

## 4. 実機検証

### 条件

Pico RP2040 125 MHz、custom MicroPython 1.26.0（`KAGURA_PICO`）、QSPI 5 MHz、Viper FIFO／DMA有効（`accelerate()`、両backend同じ）、Tang Nano 9Kへ`qspipsram` 480p bitstream（SHA256 `2d00ee52…f133d9`、前回受入と同一）をSRAM Program and Verifyで一時構成。ABI 0.6、PATTERN_COUNT 1200、320×240。検証用SDKは`/lib/kagurafbx/`、診断は`/fbx/`へ置き、16 fileのSHA-256をPicoで照合（`/lib/kagura`、`boot.py`、firmware、FPGA Flashは不変）。

### native実行・PC一致・guard

- `framebuffer_viper_validation.run`：共通1090操作（既存primitiveに加え、blit線形／tile／自己blit・ellipse・paint）の各操作後のbuffer＋dirty履歴CRCが、Python／Viper／PC参照ですべて`1028220238`。最終plane CRC `1578755449`。実fontのtext CRC `3371118220`（前回と同値）。
- paintのoverflow／compaction（容量3と40、迷路・雑音・櫛形）：両backendとPCで部分結果CRC `3922172375`と統計（peak・dropped・compactions・pixels）が一致。容量3のstack直後のsentinelも無傷。
- plane・dirtyの前後32 B、paint stackの前後8 wordのguardは無傷。native counterは8 kernelすべて増加（blit 127、ellipse 81、paint 27回）。Python区間では新kernelのcounterは0。
- Scene F／G／H：Python・Viperとも、Pico上のbuffer CRC（F `4066170657`、G `1950363282`、H `3895805622`）がPCで描いた値と一致し、6回すべて全38400 B・map 4096 B・上位表256 Bの実VRAM読戻しが一致。Hの20回のpaintはすべて完了（stack peak最大11）、同色指定はno-op。
- 描画時間（scene全体、fill(0)含む）：F Python 3.295 s／Viper 0.255 s、G 1.429 s／0.033 s、H 6.677 s／0.189 s。

### メモリ

| 項目 | 実測 |
|---|---:|
| TileFramebuffer constructor heap差分 | 40544 B |
| Viper native module読込み | 16736 B（追加前4832 B） |
| paint作業stack（初回paint時） | 8192 B＋array header |
| blit／ellipseの追加buffer | 0 B |
| session初期化後の空きheap（PCM・paint stack前） | 92432 B（scene）／84384 B（benchmark） |
| PCM 2ch・連続描画中のGC後heap | 87376～87488 B（300 s、変動112 B） |
| 最大stack使用（実測、全形状） | 290要素＝1160 B（40%雑音） |

native moduleの増加（約12 KB）は3 kernelのmachine code。ベンチマークは転送元画像に一時9600 Bを使い、終了後のGC後heapは102560 B。GC 1回は約12.0 ms（連続試験、最大12.2 ms）。各sampleの前にGCを行い、描画時間には含めていない。

### CPU描画時間（新primitive）

各10回、ms。倍率＝Python平均／Viper平均。標準偏差は母分散の平方根。最小・最大・p95・全sampleは[JSON](framebuffer-primitives-results.json)。入力は毎回Viperで同じ状態に戻してから（非計測）GCし、描画だけを測った。flush列は同じ描画の直後のflushで、描画時間とは別。

| 機能 | Python | Viper | 倍率 | Viper σ | Viper p95 | flush（転送／FENCE待ち） |
|---|---:|---:|---:|---:|---:|---|
| blit 16×16（TILE4整列） | 3.825 | 1.954 | 2.0× | 0.014 | 1.981 | 10.932／14.944 |
| blit 64×64（TILE4整列） | 29.236 | 2.488 | 11.8× | 0.015 | 2.507 | 45.436／59.306 |
| blit 320×240（plane自身、整列scroll） | 429.238 | 10.527 | 40.8× | 0.011 | 10.548 | 240.393／214.786 |
| ellipse輪郭（150×110） | 266.936 | 3.140 | 85.0× | 0.012 | 3.160 | 285.151／401.435 |
| ellipse塗りつぶし（150×110） | 1163.784 | 11.589 | 100.4× | 0.016 | 11.615 | 215.740／207.382 |
| paint小領域（32×32） | 93.026 | 2.012 | 46.2× | 0.015 | 2.041 | 28.216／37.176 |
| paint全画面（実flood fill） | 4970.516 | 21.560 | 230.5× | 0.013 | 21.584 | 105.297／7.552 |

blitの全条件（Viper平均 ms。Python平均は括弧内）：

| サイズ | TILE4整列 | TILE4整列＋透過 | TILE4非整列 | GS4_HMSB整列 | GS4_HMSB整列＋透過 | GS4_HMSB非整列 | GS4_HMSB非整列＋透過 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 8×8 | 1.870 (2.297) | 2.055 (5.203) | 2.011 (5.222) | 1.919 (4.944) | 2.126 (4.888) | 2.095 (4.885) | 2.202 (4.900) |
| 16×16 | 1.954 (3.825) | 2.335 (15.396) | 2.509 (15.575) | 2.035 (14.431) | 2.468 (14.274) | 2.543 (14.452) | 2.687 (14.290) |
| 32×32 | 1.905 (9.169) | 3.670 (55.228) | 4.589 (56.998) | 2.309 (52.153) | 3.688 (50.462) | 4.418 (52.224) | 4.528 (50.484) |
| 64×64 | 2.488 (29.236) | 8.933 (213.720) | 12.779 (221.877) | 3.335 (202.892) | 8.600 (194.872) | 11.881 (202.932) | 11.699 (194.865) |
| 160×120 | 4.214 (104.468) | 34.634 (991.835) | 52.544 (1030.260) | 8.351 (942.166) | 32.544 (903.815) | 48.146 (942.200) | 46.746 (903.795) |

320×240はplane自身を転送元にした：整列（(8,8)→(0,0)、312×232）10.527 ms（429.238）、整列＋透過114.698（2996.229）、奇数ずれ（(0,0)→(3,1)、317×239の重複copy）194.102（3778.000）、奇数ずれ＋透過168.834（2983.012）。

- tile整列の高速経路は機能している：TILE4整列64×64は2.49 msで、同サイズ非整列（12.78 ms）の約1/5、160×120では1/12。GS4_HMSBでも整列なら1 tile行＝1 wordで、160×120が8.35 ms。
- 8×8～16×16は約1.9～2.7 msで、ほぼ固定の呼出し費用（引数検査・clip・param設定。既存`hline`の1.04 msと同種）が支配的。
- 透過色・奇数ずれはnibble処理で、64×64で約9～13 ms、160×120で約33～53 ms。

ellipseの小（24×16）は輪郭1.198 ms（31.875）、塗り1.400 ms（43.499）。paintの他形状：

| 形状 | Python | Viper | 倍率 | 画素 | span | stack peak |
|---|---:|---:|---:|---:|---:|---:|
| 8×8 | 12.432 | 1.210 | 10.3× | 64 | 10 | 4 |
| 160×120 | 1304.874 | 7.178 | 181.8× | 19200 | 122 | 4 |
| 1画素幅の蛇行通路 | 6669.183 | 61.116 | 109.1× | 38520 | 240 | 1 |
| 迷路（80×60 cell） | 10840.573 | 168.242 | 64.4× | 57597 | 8780 | 71 |
| 櫛形（歯160本） | 27840.428 | 451.029 | 61.7× | 38560 | 38083 | 160 |
| 40%雑音 | 11391.543 | 190.811 | 59.7× | 32376 | 10291 | 290 |

すべてcomplete、compaction 0。Viperの標準偏差は全条件で0.08 ms以下。

### 目標に対する評価

- 小icon：1.9～2.7 msで目標（3 ms）内。
- 整列blit：64×64は2.5 ms、160×120はTILE4 4.2 ms／GS4_HMSB 8.4 msで目標内。全画面整列scroll 10.5 msは`fill()`（9.0 ms）の1.2倍で目標内。非整列・透過の大画像（160×120で33～53 ms、全画面で115～194 ms）は目標外で、nibble処理の限界。速い転送が必要な素材はtile整列で置く。
- 楕円：輪郭3.1 ms、塗りつぶし11.6 ms（同面積に近い`fill_rect` 288×208が7.4 ms）で目標内。
- paint：全画面21.6 msで目標内。最悪級の櫛形（38083 span）が451 msで1秒未満。

### 既存primitiveの再測定（回帰確認）

`compare_draw`、各10回、ms。前回記録（[Viper描画比較](framebuffer-viper-results.md)）との差。

| 処理 | Python | Viper | 倍率 | 前回Viper |
|---|---:|---:|---:|---:|
| fill_rect | 1229.602 | 7.436 | 165.35× | 7.672 |
| line | 54.401 | 1.671 | 32.56× | 1.923 |
| fill | 519.871 | 9.046 | 57.47× | 9.171 |
| circle | 58.996 | 1.867 | 31.60× | 2.052 |
| text | 81.830 | 6.202 | 13.19× | 6.506 |
| hline／vline | 7.005／34.366 | 1.036／1.303 | 6.76×／26.38× | 1.271／1.539 |
| pixel_1024 | 355.894 | 337.878 | 1.05× | 343.290 |

既存kernelは変更しておらず、すべて前回以下（後退なし）。

### flush（変更なし）の比較

PCM 2ch稼働中、各10回、flush全体の平均ms：1 tile Python 14.854／Viper 14.886、10 tile 15.570／15.567、100 tile 22.701／22.677、1200 tile 114.604／114.612。描画backendによらず同じで、前回の同条件（14.162～114.857 ms）と同程度。register call数も同じ（1200 tileでwrite 8／read 7）。

### 連続負荷（PCM 2ch）

移動する32×32透過sprite（背景はGS4_HMSB 9600 Bの写しからblitで復元）、楕円animation（前回位置を塗り楕円で消去）、320×120の仕切り付き領域を毎loop交互の色でflood fill、dirty flush、ERROR_CODE・audio FIFO・PCM状態・frame counter監視、32 loopごとのGC。

| backend | 秒 | 更新数 | updates/s | CPU描画平均 | うちpaint | 転送平均 | FENCE待ち平均 | iteration p95 | iteration最大 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Viper | 300.696 | 540 | 1.796 | 15.608 | 3.898 | 217.434 | 298.271 | 729.461 | 824.311 |
| Python | 60.409 | 58 | 0.960 | 523.589 | 239.694 | 207.032 | 285.601 | 1357.103 | 1450.169 |

両方ERROR_CODE=0、FIFO異常0、PCM ACTIVE維持、paint stack peak 4、終了後の全VRAM読戻し一致。HDMI frame counterは59.997／59.991 Hzで、application updates/sとは別の値（実際の画面反映頻度は未測定でnull）。

この負荷は毎loop約600 tileが変化し、多数の連続runに分かれるため、更新周期の大半は既存flushの転送とrunごとのFENCE待ちになる。Viperの描画は1 loopの約3%。flush・FENCE・通信は今回の範囲外として変更していない。

## 5. 実機への導入と復帰

1. 既存consoleを`kagura_console.close()`（dupterm・UART・PIOを解放）。heapの断片化を避けるため、Picoは各段階の前にsoft resetし、boot consoleをcloseしてから実行した。
2. `/lib/kagurafbx/`（SDK 11 file）と`/fbx/`（診断等5 file）へ書込み、16 fileのSHA-256をPicoで照合。
3. FPGAはSRAM Program and Verify（`--run 4`、Verify success）。Flashは書込んでいない。
4. 終了時は`Session.close()`でPCM停止・アクセラレータ解除・PIO解放、`--run 1`でFlashの元構成を再読込み、Picoをsoft reset。boot.pyのHDMIコンソールが起動し、ABI 0.5・CAPS 0x7B・ERROR_CODE 0・console activeを確認した。
5. 未完了の通信を自動再送したことはない。初回upload中と中断後の計3回、Windows側でCOM7への書込み／openがtimeoutし、ユーザーがPicoのUSBを抜き差しした（前回の記録と同じ症状、原因未特定）。その後に再送したのは、完了を確認済みの直後のchunkからで、全fileのSHA-256照合で整合を確認した。
6. 最初のbenchmark試行は転送元用の一時38400 Bを確保できずMemoryErrorで停止した（例外時にsessionはclose）。第2 planeを要しない方式（9600 B＋plane自身の自己blit）に改め、soft reset後に全条件を再実行した。Scene Hの初回も同色no-op検査が38400 Bのcopyを作っていたため、CRC比較に改めて再実行した。

## 6. 制限・残課題

- pattern RAMにdouble bufferはなく、paint・blit中のflushはtear-freeではない（既存仕様のまま）。
- paintは`paint_capacity`を超える極端な形状でFalseを返し得る（部分状態は仕様化済み）。事前見積りはしない。
- 非整列・透過の大きいblitはnibble処理で、全画面で約0.1～0.2 s。
- 線形bufferとして描画planeを別解釈したaliasは未サポート。転送元形式は4bppのみ（1bpp・8bppや色変換paletteはない）。
- 連続試験はViper 5分・Python 1分。1時間試験、別sink・ケーブルでの確認、HDMIの目視確認は今回行っていない（数値照合のみ）。
- COM7のtimeoutの原因（Windows CDC driverかPico側か）は未調査。
