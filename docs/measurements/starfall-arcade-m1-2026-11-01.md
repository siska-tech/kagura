# STARFALL Arcade Milestone 1 — Phase A/B

2026-11-01 JST。branch `feat/starfall-arcade-m1`。
目的・差分・以降の計画: [arcade plan](../starfall-arcade-plan.md)。
既存v6の移動/装備/同時option laser/音源/driver/map ringを維持し、追加で完成させた。

## 完成範囲

- BOOT→大型タイトル→START→2秒intro→Stage 1→warning→部位boss→爆発→clear→title。
- 15秒無操作→40秒attract→title。START割込みで新規runとして全装備/敵/弾を初期化。
  冒頭の8方向入力表＋決定的controllerを同じPLAYで動かす。デモのcapsule出現は演出event、
  デモ中だけ被弾を無効化し、出現時計を2倍で進める。録画の再生や別rendererではない。
- 大型original BG logo、64×64惑星、palette fade、raster星空、通過する自機、credits。
- 6面カタログと個別event table入口。**有効な内容はStage 1のみ**。
- Stage 1 STAR FRONTIER: 直線/V/波/円弧/挟撃/後方奇襲/運搬の7編隊、破壊可能な隕石、施設外壁。
- event時計とcameraを分離。44秒でcamera停止、2秒warning、boss登場中80tickの保護。
- boss共通APIで48×32迎撃艦、上下砲台各HP12、core HP100、HP依存3phase、2秒の連続爆発。
  coreは左中央の24×12領域、砲台は右側の上下で独立に壊せる。armorにはdamageが入らない。
- 専用DEMO BGMを追加し、既存曲と合わせ10曲。BGM tickもcamera停止から独立。
- clearは5秒、game overは4秒でtitle。未実装のStage 2へ進まない。

STAGE 2 FRONTLINE BASE、3 VOLCANIC BELT、4 ANCIENT RUINS、5 BIO HIVE、
6 CENTRAL FORTRESSは名前/metadataを登録しただけで、ready=false。
ハッチ/個別地形/専用boss/各面曲/全6面の通し/endingはPhase C〜Eの残課題。
Stage 1は約1分前後の短縮版（戦闘時間次第）。2〜3分版は全体動作確認後に拡張する。

## 検証

| 検査 | 結果 |
|---|---|
| ホスト6件、C11/Wall/Wextra/Werror、ASan/UBSan | PASS |
| v6由来の216000tick replay×両解像度、全武器/16-line予算 | PASS |
| 40秒demo再現/START割込み/装備初期化/title復帰 | PASS、両解像度features=31 |
| 全7編隊/隕石event、intro/scene reset | PASS |
| warning停止→boss登場→armor/砲台/core/HP phase→爆発→clear | PASS、両解像度 |
| title/game map高位byte復帰、fade/raster/column安全、音源/入力 | PASS |
| 既存RTL全回帰 | **61/61 PASS**、Verilator 5.032 |
| 既存MicroPythonのdriver/FB/fixture/transport/shooter/link/sakura/showcase | 8 scripts、235 tests PASS |
| 既存C TileFramebuffer差分試験 | 6 tests PASS |
| 既存日本語SDK・font生成（cached MISAKI） | 34 tests PASS |
| 既存診断firmware `kagura_host` | ビルドPASS |
| 生成register / design checks | PASS |

これらはホスト/RTL/ビルドでの結果。新ゲームをRTL上でpixel単位にend-to-end実行した結果ではない。
実機での映像/操作/音量/音声underrun/fps/長時間動作は**未確認**。
MicroPython/showcase等の作業開始前からの変更は編集/commitしていない。

## 性能と資源

ホストのASan/UBSanビルドで共通demo経路12000frameを計測:
平均11205ns、最大362482ns、直近256frame p95=6us、最大line=16。
ホストのwall-clock値（OSとsanitizerの影響あり）であり、Pico処理時間や60fpsの証明ではない。

実機ログではCPU/転送/COMMITを独立に集計する。
`cpu_us/io_us/commit_us=平均/p95/最大`。p95は直近256件。
`io_us`はVBlank中のOAM/map/palette/音源register stagingで、bus待ちとdriver overheadを含む。
`commit_us`は次VBlank待ちで、待機中の集計/USB出力も含む。
`load_max`はsceneのmap交換（表示停止COMMIT/FENCEも含む）の最大時間。
asset upload/scene交換は通常frameと分け、steady-stateのfpsも確認する必要がある。

| 資源 | 使用量 |
|---|---:|
| pattern予約 | 704個×32 = 22528 B（全て0..1023の旧pattern領域内） |
| map / upper表 | 4096 / 256 B |
| palette / OAM予約 / wave | 160 / 2048 / 512 B |
| 公開VRAM予約合計 | 29600 B |
| 管理OAM / 最大line | 64枠512 B / 16 |
| boss合成 | 6個の16×16、3/line。通常敵とは同居しない |
| 状態 / frame（host） | 700 / 520 B |
| CPU0 stack | 4096 B。実機high-water markは未測定 |

Pico ELFは両laneともtext 111864 B、data 0 B、bss 31780 B。
static SRAMに加えstackやSDKの実行時使用量が必要で、実機の最大使用量は未測定。
PSRAMも新規RTLも不要。runtimeの全画面pixel転送や動的heap確保は使わない。

## 実機確認手順

1. 現在のFPGA bitstreamと同じlaneのM1 UF2を書き込む（ABI 0.6のまま）。
2. タイトルのfade/logo/planet/通過自機を確認。無操作15秒でdemoが40秒動いて戻ること。
3. demo中Enter/Spaceでintroへ移り、装備が初期状態であること。
4. `uv run --with pyserial python software/starfall/keyboard.py COM5`。
   WASD/矢印、Space射撃、X/Shift選択。装備仕様はv6と同じ。
5. intro後44秒でscroll stop＋WARNING、46秒で迎撃艦。右上下の砲台と左中央coreを撃つ。
   撃破後2秒爆発→clear→5秒でtitle。次面はまだ始まらない。
6. 定常区間で`hz100≈5994/6000`、`overflow=0`、`audio=0`、`blank=0`とCPU/io/commitの値を保存。
   scene交換を含む累積`missed/load_max`は通常frameの遅延と分けて評価する。

## 最終生成物・ログ

UF2: `build/starfall-arcade-m1-spi.uf2` / `build/starfall-arcade-m1-qspi.uf2`。
両方211456 B。SHA-256:

```text
SPI  8323C4B038CA2C7D290E1D2B2F6435B0E16CB18D48780643CEC0B345A7BEC435
QSPI B4393FD917EA002A28C1373EE823316D06CAA1453DFBBA3D4D454B23511DEA55
```

Phase A保存UF2: `build/starfall-arcade-A-spi.uf2` / `build/starfall-arcade-A-qspi.uf2`。
host: [M1 host](starfall-arcade-m1-host-2026-11-01.txt)、[host bench](starfall-arcade-m1-bench-2026-11-01.txt)。
RTL: [61件summary](starfall-arcade-m1-rtl-2026-11-01.tsv)。
詳細ログ: `build/starfall-arcade-B-build.log`、`starfall-arcade-full-rtl.log`、
`starfall-arcade-compat.log`、`starfall-arcade-font-compat.log`、`starfall-arcade-diagnostic-build.log`。
参照画像は同じtile/OAMからのソフトウェア合成で、実機写真ではない。
