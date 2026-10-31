# PROJECT STARFALL — Arcade Milestone 1 (Phase A/B)

現在完成しているのは **Stage 1 STAR FRONTIERの短縮版**。
6面のカタログと共通イベント/ボスinterfaceを追加したが、Stage 2〜6は未実装で選択・進行できない。
Stage 1クリア後はタイトルへ戻る。全6面/ending完成版とは扱わない。
[拡張設計・Phase別計画](../../docs/starfall-arcade-plan.md)、
[マイルストーンの検証・使用量・実機手順](../../docs/measurements/starfall-arcade-m1-2026-11-01.md)。

設計・制約・以降の計画: [Phase 0設計](../../docs/starfall-design.md)。
[Phase 1検証記録](../../docs/measurements/starfall-phase1-2026-10-31.md)。
[第2版の検証・使用量](../../docs/measurements/starfall-v2-2026-10-31.md)。
[第3版の検証・使用量](../../docs/measurements/starfall-v3-2026-10-31.md)。
[第4版の検証・使用量](../../docs/measurements/starfall-v4-2026-10-31.md)。
[第5版の場面別BGM・検証](../../docs/measurements/starfall-v5-2026-10-31.md)。
[第6版の修正・敵演出・検証](../../docs/measurements/starfall-v6-2026-10-31.md)。
既存diagnosticターゲットを変更せず、`kagura_host.c`と生成register headerを再利用する。
Phase 2（敵・敵弾・衝突・爆発・スコア・残機）から順に拡張し、Phase 3の
約60秒ステージ・地形・砲台・中ボスと、Phase 4の一部を実装した版。
機体・敵・フォント・BGMはコードから作成したオリジナル素材。

## 遊び方

- タイトルで **Space / FIRE**。WASD・矢印キーで8方向移動、Space押しっぱなしで連射。
- **EnterもSTART/FIRE**。タイトルは大型BGロゴ、惑星、fade、通過自機、FREE PLAY。
- 15秒無操作で40秒のアトラクトへ。デモ中STARTは即座に通常ゲームのintroへ移る。
- 2秒のSTAGE INTRO後、空中戦→施設外壁→climax→WARNING→部品boss→大型爆発→clear。
- 序盤は壁のない宇宙で空中戦。約19秒から基地の入口が右端に現れ、約24秒で内部へ。
- 基地では金属隔壁・警戒ストライプ・壁面砲台が登場し、最後は広いボス格納庫へ進む。
- 赤い旋回編隊、紫の可動翼機、急降下迎撃機、壁面砲台を撃破して進む。
  敵の2frameアニメーション、被弾flash、ボスの予備発光/3連射、3段階の爆発あり。
  地形・敵・敵弾に触れると被弾。
- 残機3。被弾後は3秒無敵、装備は初期状態に戻る。
- 「P」カプセルでゲージが **SPEED→MISSILE→DOUBLE→LASER→OPTION→SHIELD** と進む。
- 欲しい装備で **X / Shift** を押すと発動し、ゲージは先頭の手前へ戻る。押しっぱなしの再発動はない。
- SPEEDは3段階、MISSILEはほぼ真下に落ち、着地後に前進する副武装、DOUBLEは前方と斜め上の交互射撃。
- 空中のミサイルは下向き、着地後は横向きに描画。宇宙では見えない床に乗らず、画面下へ落ちて消える。
- LASERは最大64pxの貫通パルス。敵ごとに1発3ダメージ、地形で切れる。DOUBLEとは排他装備。
- OPTIONは履歴追従支援機を1機ずつ最大2機。自機の後方に配置するので停止中も重なりにくい。
- レーザーは**自機と全オプションが同時発射**。自機は青、オプションは金色。
  通常弾/ダブルは発射元を順番に使う。
- 混雑時は敵・敵弾を隠さず、レーザーを表示可能な長さまで短縮する。
  各発射元の先頭segmentを優先し、表示の長さと命中範囲は常に同じ。
- SHIELDは3発まで吸収。吸収時は45tick無敵。失機すると全装備を失う。
- 橙色の編隊長を撃破するとカプセル。編隊を全滅させると500点＋追加カプセル。
- カプセルが既に画面内にある場合、追加分は最大8個まで待機し、次を1個ずつ出す。
- ステージ時刻44秒でスクロール停止、2秒WARNING、48×32の大型迎撃艦が登場。
- ボスは登場後80tickまで無敵。右側の上下砲台は個別破壊可能。左側中央の光るcoreが弱点。
- core HPで攻撃が変化し、撃破後2秒の連続爆発からSTAGE 1 CLEARへ。
- clearは5秒、GAME OVERは4秒でタイトル復帰。1秒以降の新しいSTARTでもタイトルへ戻れる。

上段はスコア・残機と選択装備名。未選択ならSPACE/ENTRY/BASEを表示する。
6枠のパワーゲージは**画面下の専用パネル**。橙=選択中、緑=取得済み。
取得上限の装備を選んだ場合はゲージを消費しない。敵弾は赤、味方弾は水色。
宇宙ではラスタ対応時に中央星空が1/3速度。ラスタ帯は将来の基地床が入らない範囲に制限する。
基地入口で通常scrollに揃え、地形と衝突を一致させる。
地形はmapの画面外列を8pixelごとに更新する。再スタート時は表示停止で宇宙のmapへ戻す。
6音源BGMとショット・爆発・カプセル・被弾・警告SFXあり。
宇宙・基地接近・基地内部・警告・ボス戦・撃破後の脱出でオリジナルBGMを切り替える。
タイトル曲、クリアファンファーレ、ゲームオーバー曲も用意。後二者は最後に停止する。
ミサイルは1発、通常弾は最大4発、レーザーは自機＋オプションの最大3本。

## ビルドとテスト

Pico SDK 2.2.0 / Arm GNU 14.2.rel1 / CMake。LinuxまたはWSL:

```sh
bash software/starfall/build-test.sh
```

SDK/コンパイラ既定配置は `~/opt`。PICO_SDK_PATHとPATHで変更可能。
UF2: `build/starfall-pico/starfall.uf2`（SPI、5MHz）。
build-test.shは `build/starfall-arcade-m1-spi.uf2` / `build/starfall-arcade-m1-qspi.uf2` にもコピーする。
QSPI bitstream用は別のbuild directoryに作る:

```sh
cmake -S software/starfall -B build/starfall-qspi -DSTARFALL_PICO=ON -DSTARFALL_QSPI=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/starfall-qspi -j4
```

PCのみ（Linux/WindowsのC11 compilerで利用可）:

```sh
cmake -S software/starfall -B build/starfall-host
cmake --build build/starfall-host
ctest --test-dir build/starfall-host --output-on-failure
```

build-test.shはASan/UBSanを追加する。216000 ticks×2解像度の再現性・移動境界・
衝突・無敵・ドロップ・ゲージ循環・各装備・再開・地形wrap・16個/line最悪負荷を検査。
4000tickのステージ進行と実際の弾命中によるボス破壊/クリアも検査する。
これは実機連続運転試験ではない。
backendのmock試験も行い、VBlank・差分OAM・初期化時の表示停止・失敗時の順序を検査する。
180/240両方で4000tick分のmap列更新を模擬し、画面外への転送・地形の一致・再開を検査する。
場面別BGMは切替境界・10曲の差異・SFXの優先度・wave bank保持・終曲後の停止を検査する。
現在は専用DEMO曲を含む10曲。状態遷移/40秒replay/START割込みとbossの個別部位/HP phaseも検査する。
オプション同時レーザー、混雑時の全発射元表示、旧ラスタでの床混入再現と修正後の0件も検査する。
関連する既存RTLの限定回帰は `bash software/starfall/test-rtl.sh`。

ホストの参照シンセで曲を順番に試聴するWAVを作る場合:

```sh
build/starfall-host/starfall_music_preview build/starfall-arcade-m1-music.wav
```

30秒のタイトル→デモ→宇宙→接近→基地→警告→ボス→脱出→クリア→GAME OVER。
実機録音ではなく、BGMのみの参照合成（RTLとのbit一致を保証するものではない）。

## 実機

ABI 0.6のSPIまたはQSPI bitstreamが必要。HDMI modeはFPGA側で選び、自動で180/240に合わせる。
配線は[既存Picoガイド](../pico/README.md)。BOOTSEL接続しUF2をコピーすると起動。
この通常flash UF2を書き込むと既存Pico firmwareは置き換わる。RAM実行が必要なら
別buildで `-DPICO_DEFAULT_BINARY_TYPE=no_flash` を指定する。

入力はGP11=左、12=右、13=上、14=下、15=shot、16=装備発動のactive-low switch（各GNDへ）。
USB経由のPCキー入力はuvで:

```sh
uv run --with pyserial python software/starfall/keyboard.py COM5
```

専用windowにfocusしWASD/矢印とspace、X/Shiftで装備発動。失focusで解除、通信断は250msで解除する。
プロトコルは `@` と `A+6bit mask` の2byte（65..128）、33msごと。
従来5bitのパケットはそのまま有効。追加キーを使うにはUF2とkeyboard.pyの両方を更新する。
USB端末との同時openは不可。
GPIO入力とserial maskはOR合成。CPUは固定120MHz。

256frameごとにUSBへ性能ログ。USB未接続でもprintで長時間停止しない設定。
集計・ログ送信は次フレームのCOMMIT投入後に行い、VBlankのOAM転送を妨げない。
`hz100=5994`なら平均59.94Hz。
`cpu_us=平均/p95/最大`、`io_us=平均/p95/最大`、`commit_us=平均/p95/最大`で単位はus。
p95は直近256frame、平均/最大は起動後累計。CPU/転送/COMMIT待ちを分離する。
`wire=平均/最大`は状態poll込みのwire byte、`oam`はOAM payload平均、`map`はmap payload累計。
`load_max`はmap scene交換の最大時間（表示停止のCOMMIT/FENCE待ち込み）。
`stage`は1始まり、`scene`は0空中戦/1main/2climax/3warning/4boss/5撃破。
`demo=1`はattract、`overflow/audio/missed/blank`は従来のfault/遅延カウンタ。
`bgm`は現在の曲名（SPACE/ENTRY/BASE/WARNING/BOSSなど）。
起動時ABI/capability/既存faultが不適合ならエラーで停止する。途中I/O失敗も
再送せず停止し、最終映像を保持する。リセット後、診断firmwareでfaultを調査できる。
自動書込みや既存Flash/FPGA構成の変更は本作業では行っていない。
