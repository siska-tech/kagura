# メモリアクセススケジュール

1論理ラインの描画時間の上限、VRAMの仲裁、line bankの所有権、VBlankの時間配分。ここでの数値は設計上の上限であり、`spec/design-budget.json`と`tools/check-design.ps1`が算術を検査する。

## 1論理ラインの時間

```text
480p: 物理1ライン = 800 / 25.2MHz = 31.746µs、論理1ライン（2物理ライン）= 63.492µs
      system cycle = floor(54MHz × 63.492µs) = 3428
720p: 論理1ライン（4物理ライン）= 6600 / 74.25MHz = 88.889µs → 4800 system cycle
```

位相により3428または3429になるので3428を使う。描画は水平ブランキングだけに押し込めず、論理ライン全体の時間を使う。

## 描画の上限

RAMの読出しlatencyは1 cycle。描画中は描画器がpattern・map・palette・OAM・line bankを占有し、hostの操作を挟まない。

| 処理 | 最悪のアクセス・操作 | 予約cycle |
|---|---|---:|
| sprite選択 | 256件のword 1（Y・enable・size）を毎cycle連続で読む。選択1件ごとにword 0/2の読出しと、読み過ぎた2件の読み直しで4 cycle | 256×1＋16×4 = 320 |
| 背景 | fine scrollありで41 tile。map読出し、pattern 4 byte、8画素のpalette変換とline書込み | 41×17 = 697 |
| sprite行の取得 | 16個×16画素。pattern 8 byte＋座標・反転の準備と最初の画素の判定 | 16×14 = 224 |
| sprite合成 | 256候補画素。line読出し、palette読出し、条件付き書込み。透明・画面外でも上限から引かない | 256×5 = 1280 |
| 制御 | 開始、clip、bank・tag、完了通知 | 64 |
| **描画計** | | **2585** |
| CDC・切替のガード | 往復の同期とpixel側の先読み | **64** |
| **hostに残す枠（480p）** | 3428−2585−64 | **779** |

720pでは論理ラインが4800 cycleなので、hostに残る枠は2151 cycleになる。

- sprite選択は「word読出し→判定→選択」を各1段のregisterで区切ったpipelineで、RAMのenable・addressがそのcycleの比較結果に依存しない。256件を1件1 wordで走査できるよう、Y・enable・size16をrecordのword 1に集めている（[メモリマップ](memory-map.md#sprite-8byteレコード)）。
- 背景はfetch（map 1 word＋pattern 4 byte）とemit（8画素のpalette読出し・line書込み）を2段で重ね、paletteとline bankが別RAMであることを前提に1画素1 cycleで書く。41×8=328候補画素のうち画面内の320画素だけを書く。
- `tb_vdp_frame`・`tb_vdp_sprites`は描画1ライン分のcycle数を測り、spriteありで2585、背景だけで697を超えたら失敗にする。

### hostの帯域

hostに残る枠は、16bit RAMのbyte RMW（3 cycle）換算で最大259 byte操作/論理ライン（約4.08MB/s）の局所的な理論値で、保証値ではない。実際にはhost interface（SPI/QSPIのbyte速度、W65C02Sの3.375M access/s）、命令fetch、FIFO制御が律速する。実測は[ホストインターフェース](host-interface.md)と[PSRAM](psram.md#copy)を参照。

## 仲裁

全メモリを1本の固定優先度でまとめず、RAMごとに仲裁する。

- **pattern・map・palette・OAM・line bank**: 描画の予約区間を優先する。描画が終わった残りの時間でqueueのcommand（WRITE・READ・FILL・COPYの書込み・COMMITのcopy）を1件ずつ実行する。OAM・paletteのRMWは描画の開始をまたがない。
- **wave RAM**: 音源の波形読出しを優先し、残りをhostの書込みへ回す。映像のRAMとは独立。
- **command queue RAM**: 書込み（受付）を優先し、空いたcycleで先頭entryを読む。
- **音声FIFO**: system側で書き、pixel側で読む。映像の仲裁とは独立。
- **FILL・COPY**: 空き時間だけで進み、次のラインの描画開始で中断する。queueの順序は変えない。
- **PSRAM**: PCMの補充とqueueのPSRAM操作を別の仲裁器で調停する（[PSRAM](psram.md#仲裁)）。

## line bankの所有権

line bankはsystem書込み・pixel読出しの2個のTDP RAM。所有権を交換して、同じbankを同時に読み書きしない。

1. pixel domainは論理ラインnの表示開始（物理y=SCALE×n、x=0）で、表示していないbankへ論理ラインn+1の描画を要求する。payload {bank, line}を保持し、toggleでsystem側へ送る。
2. systemの描画器は要求を1回だけ受け取り、bankを完成させてからdone toggleとline tagを返す。
3. pixel側はn+1の表示開始の2 pixel clock前に、tagが一致すればbankを切り替える。一致しなければそのラインを黒にしてLINE_UNDERRUN（[映像仕様](video.md#描画期限とunderrun)）。
4. 描画器は表示中のbankを読み書きせず、pixel側も描画中のbankを読まない。line RAMの読出しlatencyはブランキング中の先読みで吸収し、sync信号は同じ遅延で揃える。

最終ラインの後は通常の要求を止め、V_TOTAL−3ライン目で次フレームのline 0を要求する。reset後は両domainの準備を交換してから要求を始めるので、古いdoneが新しいフレームのものと誤認されない。

## VBlankの時間

```text
480p: 45ライン ≒ 1.429ms ≒ 77142 system cycle
720p: 30ライン ≒ 0.667ms = 36000 system cycle
```

COMMITのcopyはOAM 1024 word＋palette 256 wordで、1 wordをread/response/writeの3 cycleとすれば3840 cycle。line 0の描画2585とガード64、制御の予約1024を加えても7513 cycleで、どちらのモードでもVBlankに収まる。waveはcopyせず、AUDIO_COMMITでbankを交換する。

## 上限の根拠となる最悪条件

上の表は、fine scroll X=7、不連続なpattern、16個がすべて16×16で全画素不透明、選択対象が登録番号の末尾側にある場合を想定した値である。描画器がgrantなしにVRAMを読んだ場合は、simulation用のassertionで検出する。
