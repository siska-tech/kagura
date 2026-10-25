# Memory Access Schedule / worst-case model

【算定】25.2MHz、800 clocks/物理ライン、525 lines/frame。1論理ラインを2物理ライン表示するため:

```text
physical_line = 800 / 25.2 MHz = 31.746031746 us
logical_line  = 1600 / 25.2 MHz = 63.492063492 us
system_slots  = floor(54 MHz * logical_line) = 3428 cycles
```

位相により3428または3429となるので3428を使用。horizontal blankだけの時間へ描画を押し込めない。

## 描画アルゴリズムと上限契約

次のモデルはRTLが満たすべきスケジュールであり、実測結果ではない。RAM read latencyは1 cycle。バーストでは連続addressを発行でき、read完了をpipelineで消費する。パターンはbyte幅、map/OAMはword幅。CPU割込みをこの時間へ挿入しない。

| 処理 | 最悪アクセス/操作 | 予約cycles |
|---|---|---:|
| スプライト評価 | 256件のword 1（Y・enable・size）を毎cycle連続読出し。選択した1件ごとにword 0/2の読出しと、後続の読出し済み2件の破棄・再読出しで4cycles | 256×1＋16×4 = 320 |
| BG tile fetch/emit | fine scrollありで41タイル。1map読出し2cycles、4 pattern bytesを5cycles、8 pixelsをpalette pipelineへ8cycles、排出2cycles | 41×17 = 697 |
| Sprite row fetch/setup | 16個×16px。8 pattern bytesを9cycles、座標/反転setupと初画素の判定5cycles | 16×14 = 224 |
| Sprite composite | 256候補pixels。line読出し2、palette読出し2、conditional write1。透明・画面外でも上限から減算しない | 256×5 = 1280 |
| 制御 | 開始、境界クリップ、bank/tag、done等の上限 | 64 |
| **描画計** | | **2585** |
| CDC/切替ガード | 往復同期とpixel prefetch余裕 | **64** |
| **CPU等に残す枠** | 3428−2585−64 | **779** |

スプライト評価は、読出しword・判定・選択の各段をregisterで区切る3段pipeline。RAMのenable/addressが同じcycleの比較結果に依存しない。ABI 0.4までの64個版は1件6cycles（4word読出し＋排出＋判定）の逐次処理で384 cycles、描画計2633、CPU枠731だった。256個をこの方式で走査すると1536 cyclesとなり480pの期限を超えるため、レコード配置を変えて1件1wordの判定にした（[メモリマップ](memory-map.md)）。

BGの41×8=328候補画素のうち320だけ書く。各BG tileでpaletteの読み要求を1cycleに1件出し、その応答RGBを別RAMのlineへ書くため、paletteとlineが独立であることが必須。8pixelを順次3cyclesずつ処理する実装では上記予算を満たさない。

総VRAM要求: map41 word、pattern BG164byte＋sprite128byte=292byte、OAM最大320word（走査256＋選択16件×4）、palette最大328＋256=584word、line BG320write＋sprite256read＋256write（実際はtransparent/claimedで減少）。RAM群は独立。これらを1本の共有メモリへ移すと同じ計算は使えない。

CPU残枠は3cycles/RMWなら最大259 byte operations/論理ライン（約4.079MB/sの局所理論値）。これはCPUソフト実効帯域でも保証スループットでもない。CPUバス自体の上限3.375M accesses/s、命令fetch、FIFO制御、FILL待機で実効値は低下する。

## 調停

グローバルな固定優先度1本へ統合しない。

- line/palette/pattern/map/OAM: 描画の予約区間を優先、完了後の779 cycles以上をCPU/commandへ供給。長いCPU RMWは描画開始を跨がせない。
- waveform RAM: 最大6ch演算中の2ch波形読出しを優先。その他をCPU/コピーへ。画像メモリと独立。
- command RAM: enqueue/descriptor fetchを交互処理。キュー実行待ちはenqueueを阻害しない限り受け付ける。
- audio FIFO: 書込system、読出pixel。映像メモリの仲裁から独立。
- FILL: 空き枠だけで進行、次ライン開始前に中断可能。コマンド順は変えない。

## ライン所有権と2回表示

pixel domainが物理y=2*n、x=0で、表示中bankと別bankに論理n+1の要求を出す。payload={bank,line,frame tag}を保持し、req toggleを同期する。rendererは要求を一度だけ受け取り、完成後done toggleとtagを返す。payloadはackまで固定。

pixel側はy=2*nと2*n+1の両方で同じbankを使う。次のy=2*(n+1)開始前のガード内でdone/tagを確認してbankを交換する。rendererは表示中bankを読み書きしない。pixel側も作業bankを読まない。line read latencyとRGB pipeline分はブランキング中に先読みし、DE/HS/VSを同じ遅延で揃える。

line0はVBlank中に準備。line239完了後は通常のn+1要求を止め、VBlankのCOMMIT完了後に次フレームline0を要求する。COMMITがないフレームもline0を再生成する。frame境界や片側resetで古いdoneが新フレームに化けないよう、reset解除時に両domain readyを交換する。

## VBlankの時間

45 physical lines = 約1.428571ms、system約77142 cycles。
OAM active 1024word、palette active 256wordのコピーを各word read/response/write=3cyclesとして3840 cycles。line0描画2585、ガード64を含め6489 cycles。その他制御を1024 cycles予約しても7513 cycles。VBlank予算内という算定であり、COMMIT遅延はFSMで検証する。waveはコピーせず、AUDIO_COMMITによるsample境界でのbank交換を用いる。

## 悪条件テスト

X fine scroll=7、全タイルパターン不連続、256個Y一致、先頭16個16×16、末尾16個だけ選択、全不透明、全て重なり、反転、behind混在、最大CPU投入、FILL継続、全音源ch発音を組み合わせる。2585 cycles以内・表示bankへの書込み0・CPU残枠779以上をカウンタとassertで確認。8個版の算定は(256+8×4)+697+8×94+64=1801 cycles（ガード別）となり、タイミング余裕を増やせるがソフトへ上限変更の通知が必要。
