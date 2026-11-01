# PROJECT STARFALL — Phase 0設計 / Phase 1仕様

本書は初版の設計・予算。現在の実装範囲と使用量は
[第6版記録](measurements/starfall-v6-2026-10-31.md)を参照。

調査日: 2026-10-31。作業ブランチ: `feat/project-starfall`。
調査元: checkout `a2e2156757bfd8342e876a9cd0b8dea92ba26de0`、最新origin/main
`3f08ea623c56021cc90e49f19df95c23cc3648dc` をfetchして照合。
README、docs/programming-guide.md、register-map.md、memory-map.md、video.md、
audio-spec.md、software/pico、生成ヘッダ、core/VDP RTLを確認。
この2 revision間で上記API・RTL・仕様ファイルに差分なし。
作業開始時のMicroPython/showcase等の未コミット変更は保持する。

## 根拠と制約

生成済み `software/include/kagura_regs.h` と `spec/registers.json` がABI 0.6。
ガイドの起動例のminor=5は古い。ゲームはIDとABI完全一致を要求し、実行時に
SCREEN_HEIGHT、PATTERN_COUNT、MAX_LINE_SPRITES、CAPS.SPR16を検査する。
CAPS: HDMI_AUDIO=bit0、WAVE=1、RDY=2、PSRAM=3、SPR16=4、WIDE=5、RSCROLL=6。
full=0x53 / wide=0x73、PSRAM付き=0x5b/0x7b。RDYはW65側能力であり
SPI READYピンの利用条件ではない。PSRAMは本ゲームの必須条件にしない。

| 資源 | 現行ソースの仕様 |
|---|---|
| 表示 | bitstreamで480p/720p、論理320×240/320×180、約60Hz |
| BG | 1面、64×32の8×8 tile、512×256でwrap。map 4096 B＋上位表256 B |
| Pattern | 1200×32 B=38400 B、4bpp、上位nibbleが左画素 |
| 配置 | 0..1023: 0x0000..0x7fff、1024..1199: 0xb000..0xc5ff |
| Palette | 16×16色RGB444、shadow 512 B |
| Sprite | 登録256、選択16/scanline、符号付き10bit座標、OAM 8 B/個 |
| 16×16 | baseを4整列、base+0/1が上段、+2/3が下段 |
| 同期 | shadow OAM/palette、scrollとraster表をCOMMIT。queue先頭で次VBlankを待つ |
| Raster | CAPS.RSCROLL、最大8 entry、line厳密昇順、COMMIT_BUSY中は更新不可 |
| VRAM | 公開の非active領域合計45824 B（穴を除く）。PSRAMは別途4MiB |
| Audio | 48kHz、pulse 0..2、noise 3、wave 4..5、任意PCM 2ch |

参照: `docs/memory-map.md`、`rtl/vdp/kagura_sprite_selector.sv`、
`rtl/core/kagura_vram_engine.sv`。レジスタ・VRAMアドレスは生成ヘッダのみ使用。
patternとmapは二重bufferではなく即時反映。表示停止で初期化してFENCEを挟む。
Phase 1は以後それらを変更せず、VBlankでshadow OAM差分とscrollを送りCOMMIT。
前COMMIT完了から同じVBlankで次フレームを準備するため、不要なblank edge待ちを置かない。
低速転送でblankを越えた場合はblank_overrunsを記録する。実機でゼロを受入条件とする。

## ゲームとモジュール

オリジナル機体「Aster」、星雲採掘施設の崩壊を抜ける60秒ステージを予定。
固定60 step/s、Q8座標、整数演算、ヒープ不使用。入力maskとseedを初期条件として
同じstep列で再現する。描画・音声I/Oをゲーム状態から分離する。

| ファイル | 責務・実装時期 |
|---|---|
| game.c / player.c / bullet.c | Phase 1: tick・8方向移動・通常ショット |
| renderer.c | Phase 1: OAM生成・全scanlineの消費数検査 |
| input.c / kagura_backend.c | Phase 1: GPIO/USB入力、既存kh_*接続、同期・差分転送 |
| enemy.c / collision.c | Phase 2: pool・整数AI・hitbox・破壊 |
| stage.c | Phase 3: tick指定イベント表、地形ring更新、中ボス・終了判定 |
| powerup.c / audio.c | Phase 4:装備/支援機、楽曲シーケンサ・SFX予約 |

未実装モジュールを空stubで追加せず、各Phaseで実体を追加する。
敵イベントは `{tick, type, pattern, y, count, interval, hp, drop}`、AIは
直進・整数sin LUT・編隊位相・固定砲台・ボス状態表。乱数は専用uint32 LCG。
当たり判定は描画より小さな整数AABB、貫通武器は対象ごとの命中間隔を持つ。

## VRAM / OAM / SRAM予算

| 用途 | Phase 1 | 完成版上限（予定） |
|---|---:|---:|
| Pattern | 9 tiles / 288 B | 256 tiles / 8192 B |
| Map / high表 | 4096 / 256 B | 同じ |
| Palette | 16色 / 32 B | 128色 / 256 B |
| OAM shadow | 使用9個 / 72 B、初期化全2048 B | 使用128個 / 1024 B |
| Wave | 未使用 | 512 B、両bank同一初期化 |
| 公開VRAM予約量 | 6720 B (OAM全枠を予約) | 15360 B |
| CPU SRAM目標 | 16KiB以下のゲーム固有静的領域 | 64KiB以下、SDK/stack別 |

完成版のOAM割当: 自機1、支援2、自弾16、敵32、敵弾32、爆発16、boss16、
pickup8、予備5 =128。これは登録枠予算であり同一lineに128個は出さない。
rendererが優先順（自機→危険弾→敵→装備→演出）に全Y区間を積算し、16を越える
候補を抑制する。ゲーム側の弾生成密度を制限し、危険弾の不可視化を防ぐ。
大型bossの合成は16×16パーツ数をlineごとに積算し、敵弾と合わせ最大16。
Phase 1は自機1＋弾8で最悪9/line、登録9/256。全幅画像転送は行わない。

Phase 3地形はmapの画面外列を事前更新する。320px表示に対して512px mapの余白を
使い、表示範囲と転送対象の列を検査する。tile bit10は全0固定、動的patternは
未使用の4整列blockにupload→FENCE→次OAM/mapから参照し、参照中blockを再利用しない。

## 時間・転送予算（設計値、実測値ではない）

1フレーム16.67ms。480pは59.94Hzの可能性があるためHDMIのCOMMITに追従する。
CPUロジック＋描画1ms、転送目標1ms以内、音源0.5ms、残り余裕。
Phase 1はOAM最大72 B＋scroll、VRAM設定/ヘッダとpoll込みのwire量は毎フレーム
kh_get_stats()->bytes_sentの差分で計測する（待機pollも含む）。
5MHzで72 payload Bの理論下限はSPI約115us / QSPI約29us。
これはPIO供給・BUSY・header・COMMIT待ちを含まず、達成速度の主張ではない。
完成版はOAM差分512 B、音声256 B、地形列64 Bを目安とし、実測で調整する。
全OAM/全paletteの毎フレーム転送を前提にしない。

work_avg/max/p95はCPU更新＋shadow staging時間（COMMIT待ちを除く）。
interval_lastは同期待ちとtelemetryを含む。p95は直近256件のnearest rank。
wire_avg/maxはheader、dummy、COMMIT待ちpoll、telemetry込み。
FRAME_COUNT差分でmissedを算出、SPR_OVERFLOWはsticky IRQをackして観測イベント数を
記録（複数scanlineの正確な発生数ではない）。音声faultもsticky観測frame数。
Phase 5ではCPU/transfer/pollを個別集計し、総実行時間とcommit数からHzを計算する。

## 音声設計（Phase 4）

ch0 melody、ch1 chord/arpeggio、ch2優先SFX、ch3 percussion/爆発、ch4 bass、ch5 pad。
SFX優先度: 被弾 > boss警告 > powerup > 撃破 > shot。
同chは高優先度で置換、低優先度は棄却、短いenvelopeを60Hzで更新する。
ch3の爆発中はpercussion休止、BGMのch0/1/4/5は継続して同時発音する。
オリジナル音列・波形をC配列で管理。wave bankは毎AUDIO_COMMITで交換されるため
開始時に両bankへ同一波形を書き2回commit。Phase 1は音声を実装しない。

## 順序と受入条件

0. ソース/最新main照合、設計・予算・ビルド環境調査。本書。
1. 自機/入力/通常shot/星空scroll、両解像度対応、専用UF2、PCテスト。
   敵・得点・勝敗はまだない。実機60fps判定は計測ログ取得後。
2. 敵と敵弾pool、当たり判定、爆発、score/lives。固定入力replayで被弾/無敵を試験。
3. 0–10s導入、10–25s編隊、25–40s砲台と狭路、40–55s中ボス、55–60s脱出。
   敵全滅/ボス破壊と進行位置でclear。地形とmap wrapを試験。
4. laser/missile/speed、履歴ring追従支援2機、無敵、title/game over/clear、BGM/SFX。
5. 連続1時間実機、平均/最大/p95、転送量、overflow、audio fault、SRAM mapを保存。
   60fps維持、blank overrun/危険sprite欠落/音声underrun=0を要求する。

各Phaseでソース、UF2、PCテスト、使用量、測定ログ、未検証事項を更新する。
今回は依頼どおりPhase 1まで。Phase 2–5は設計のみで完成ゲームとは扱わない。
