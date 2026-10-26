# 映像仕様

背景1面とsprite、ライン単位の描画、表示モード、フレーム更新（COMMIT）、ラスタIRQとラスタスクロールの規則。データ形式は[メモリマップ](memory-map.md)、描画時間の内訳は[メモリアクセススケジュール](memory-access-schedule.md)。

## 表示モード

表示モードはbitstreamで固定する（実行時の切替はない）。

| 項目 | 4:3版（既定） | 16:9版（構成名に`720`） |
|---|---|---|
| 論理画面 | 320×240 | 320×180 |
| HDMI出力 | 640×480p60（CEA VIC 1） | 1280×720p60（VIC 4） |
| 拡大 | 2×2 | 4×4 |
| pixel / TMDS serial clock | 25.2 / 126MHz | 74.25 / 371.25MHz |
| H total × V total | 800 × 525 | 1650 × 750 |
| 論理1ラインの時間 | 物理2ライン、63.49µs（system 3428 cycle） | 物理4ライン、88.89µs（system 4800 cycle） |
| VBlank | 45ライン、約1.43ms | 30ライン、約0.67ms |
| CAPS b5 WIDE / SCREEN_HEIGHT | 0 / 240 | 1 / 180 |

どちらも正方画素で、座標系・map・scroll・spriteの規則は同じ。16:9版は論理Y 0..179だけを描画する。ソフトはCAPS b5またはEXT 0A SCREEN_HEIGHTで画面の高さLINESを判定する。

## 背景

- 64×32 entryのmap（512×256画素）を1面持つ。画面左上は(SCROLL_X mod 512, SCROLL_Y mod 256)のmap座標で、端は反対側へwrapする。
- 各entryは1024 patternのどれか、palette 0..15、左右・上下反転を持つ。
- 画素値0は透明で、BACKDROP（palette index 0..255）の色になる。それ以外は`palette*16+画素値`の色。
- BG_ENABLE=0では全画素がBACKDROP色。DISPLAY_ENABLE=0では背景もspriteも描かず、全画素が黒。

## sprite

- 256個を登録でき（EXT 05 MAX_SPRITES=0は256）、1ラインに最大16個を表示する（EXT 06）。
- 8×8または16×16、4bpp、palette 0..15。画素値0は透明。左右・上下反転とbehind属性を持つ。
- 座標は符号付き10bit（−512..511）。画面[0,319]×[0,LINES−1]の外はclipする。
- spriteの描画はDISPLAY_ENABLEとSPR_ENABLEがともに1のときだけ行う。

### ライン選択と上限

各論理ラインで、登録番号の小さい順にenableかつYがそのラインに重なるspriteを選ぶ。Xは選択に影響しないので、Xが完全に画面外でも16個の枠を消費する。17個目以降は描かず、その時点のsprite番号とラインをSPR_OVERFLOW_INDEX/LINEへ記録し、IRQ_STATUS.SPR_OVERFLOWを立てる（[レジスタ仕様](register-map.md)）。

### 優先順位とbehind

1. sprite同士は登録番号の小さいほうが前。透明画素は優先権を取らない。
2. その画素で最も前の不透明spriteを決め、そのbehindと背景の不透明（背景画素≠0）を比べる。
   - behind=0: spriteを背景の前に出す。
   - behind=1: 背景画素が0（BACKDROP）のときだけspriteを出す。それ以外は背景を出す。
3. 背景に隠れた前のspriteの下から、後ろのspriteが透けて見えることはない。

## ライン描画

描画はsystem 54MHzで1論理ラインずつ行う。pixel domainが論理ラインnの表示を始めるとき、表示していないほうのline bankへ論理ラインn+1の描画を要求する。systemの描画器は背景を書き、続いてspriteを合成してline bankを完成させ、完了を返す。pixel側は同じbankを拡大率の回数（2回または4回）表示する。

- line 0は前のフレームの末尾（V_TOTAL−3ライン目）で要求し、VBlank中に準備する。COMMITのないフレームでもline 0は毎回描き直す。
- 描画中は描画器がVRAM（pattern・map・palette・OAM）を占有し、hostのVRAM操作は描画の空き時間に進む。最悪でも1ラインの描画は2585 system cycleで終わる設計で、残りの時間がhost側の操作に回る（[スケジュール](memory-access-schedule.md)）。

### 描画期限とunderrun

ラインの完了は、そのラインの表示開始の2 pixel clock前までにpixel側へ届く必要がある。間に合わなければ未完成のbankは表示せず、その論理ラインの全コピーを黒にしてLINE_UNDERRUNを立てる。古いラインの完了通知は捨て、次の要求で同期をとり直す。現在の描画器は最悪条件でも期限内に終わるので、通常の動作ではunderrunは起きない。

## フレーム更新とCOMMIT

hostは画面の属性をshadowへ書き、COMMIT（COMMAND=03）でまとめて反映する。

| 対象 | shadow | 反映の時点 |
|---|---|---|
| OAM、palette | VRAMのshadow領域 | COMMIT完了時（VBlank中にactiveへcopy） |
| DISPLAY_CTRL、SCROLL_X/Y、BACKDROP、RASTER_LINE | registerのshadow | COMMIT受付時に捕捉し、完了時に適用 |
| ラスタ表（RS_*） | EXTのshadow | COMMIT完了時にactiveへcopy |
| pattern、map | なし（単一bank） | 書いた時点。描画中のラインにも反映され得る |

- COMMITはqueueの先頭に来た後の最初のVBlank開始（物理y=V_ACTIVE、x=0）でcopyを始め、VBlank中に終わる。active OAM・paletteはフレームの途中で変わらない。
- patternとmapは二重化していないので、書換えのtearingは防げない。VBlank中に書くか、未使用のpattern・map領域へ書いてからmapやOAMで切り替える。
- 1フレームに1回のCOMMITを想定する。COMMIT_BUSYの間は次のCOMMITを投入できない。
- FRAME_COUNT_LとIRQ.VBLANKはVBlank開始ごとに進む。

## ラスタIRQ

RASTER_LINE（COMMITで反映）が0..LINES−1のとき、その論理ラインの表示が始まる時点（物理y=SCALE×RASTER_LINE、x=0）でIRQ_STATUS.RASTERを立てる。LINES..255は無効。

- IRQの時点では、そのラインと次のラインの描画は既に始まっている。IRQで書き換えたregisterはそのラインに間に合わない。scrollのライン別変更には次のラスタスクロールを使う。
- 最終ライン（239または179）も他のラインと同じ位置で発生する。通常のラインは次ラインの描画要求と同時に開始を通知するが、最終ラインには後続の要求がないため、専用の通知で開始を知らせる。

## ラスタスクロール（CAPS b6）

背景のscrollをライン単位で変える。hostがIRQで書き換えるのではなく、最大8 entryの表を事前に設定し、描画器が各ラインの描画開始時に引く。hostの応答遅延に依存しない。

- entryは{line, X(9bit), Y(8bit)}。entry iはRS_INDEX=iとしてRS_LINE、RS_X_L、RS_X_H、RS_Yの順に書く（RS_Yのwriteで次のentryへ進む）。RS_COUNTで有効数（0..8）を指定する。
- entryのlineの論理ラインから、そのX・Yで描画し、次のentryまで続ける。最初のentryより前のライン、およびRS_COUNT=0ではSCROLL_X/Yを使う。各フレームはline 0から評価し直す。
- 表はRS_COUNTを含めてshadowで、COMMIT完了のVBlankでactiveへcopyする。COMMITは有効entryのlineが`< LINES`かつ厳密昇順でなければBAD_ACCESSで拒否する。COMMIT_BUSY中の表への書込みはBUSY_CONFLICTで拒否する（[レジスタ仕様](register-map.md#extended-registers)）。
- 対象は背景のscroll X/Yだけ。BACKDROP・DISPLAY_CTRL・spriteは変えない。ライン途中（画素単位）の切替はない。

例: 画面下半分を波打たせる、ステータス行を固定する、多重scrollで遠景・近景を別速度にする。

## 起動時の表示

VRAMとline bankの消去が終わるまで、pixel側は黒を出す。消去直後のpaletteは全色黒、DISPLAY_CTRL=0なので、hostが設定してCOMMITするまで画面は黒のままである。CPU版・ホスト版はhostがなければ黒画面で、demo版だけが内蔵のsequencerで自走する。

## 検証

`tb_vdp_frame`・`tb_vdp_sprites`（とその720p版）は、参照モデルとRTLの出力を4フレーム全画素で比較する（scroll、反転、behind、優先順位、16個/line超過とIRQ、VBLANK/RASTER/COMMIT_DONE、systemだけのreset）。ラスタスクロールは`tb_raster_scroll`系、デモの画面は`tb_demo_shooter`系で全画素比較する。実機の確認範囲は[検証状況](validation-status.md)。
