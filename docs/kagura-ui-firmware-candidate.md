# KAGURA-UI firmware候補（main `d219778`）

2026-11-02 JST。#53〜#60のmerge後のmainから、KAGURA_PICO用UF2を作った。
**まだ実機には書き込んでいない。**
実機のfirmwareは、[最終Phase 2 UF2](kagura-ui-phase2.md#最終uf2の1時間soak2026-11-02)（`9ebfa459…`）のままである。

## 現行firmwareの再現

同じ手順で`b02a6ef`（#51のmerge）をbuildすると、実機のfirmwareとbyte単位で一致した。

| 項目 | 値 |
| --- | --- |
| UF2 sha256 | `9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c`（853504 B） |
| payload | `0x10000000..0x10068300`、sha256 `33f2ac13…`（実機XIPのhashと一致済み） |
| size | text 426540 B、data 0 B、bss 5128 B |

- 実機のfirmwareは、`b02a6ef`のsourceから再現できる。
- これを、問題があったときの戻し先にする。

## 候補UF2

| 項目 | 値 |
| --- | --- |
| source | main `d219778dc9db10d27e379acdaa8fe2edf8c3e2ae`（clean worktree、未commit変更なし） |
| frozen source | `software/micropython/kagura` tree `21b22467e8841db3e1d0a9315bbe62928328327f`（manifestの24 module） |
| MicroPython | v1.26.0 `4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`（upstream sourceは無変更） |
| toolchain | Arm GNU Toolchain 14.2.Rel1（arm-none-eabi-gcc 14.2.1 20241119） |
| board | `software/micropython/boards/KAGURA_PICO`（rp2040、Flash storage 1408 KiB） |
| build date | `SOURCE_DATE_EPOCH`＝2026-11-02T12:00:00Z（banner `2026-11-02`） |
| UF2 sha256 | `a5166d79be8f9e766c72f2e9b001a6ac851670bac29f139316f2f605f9f1298e`（856064 B） |
| payload | `0x10000000..0x10068800`（428032 B、1672 block）、sha256 `a1095518ba604824bf416d2c7c5ac678d55572ab925d98e32c0a1ef0d1a3b515` |
| size | text 428028 B（現行比 +1488 B）、data 0 B、bss 5128 B |

buildの手順:

```sh
git worktree add --detach build/fw-src/main-d219778 d219778
export SOURCE_DATE_EPOCH=$(date -u -d '2026-11-02 12:00:00' +%s)
make -C build/micropython-src/ports/rp2 BOARD=KAGURA_PICO \
  BOARD_DIR="$PWD/build/fw-src/main-d219778/software/micropython/boards/KAGURA_PICO" \
  BUILD=build-KAGURA_PICO_main-d219778
```

- **再現性:** 別のbuild directory（`build-KAGURA_PICO_main-d219778-r2`）で最初からbuildし直すと、UF2のsha256が同じ`a5166d79…`になった。sizeとbuild dateも同じだった。
- **frozen nativeの4-byte整列:** `align_frozen.py`は適用済みである。
  - `frozen_content.c`の`fun_data`は19件すべて`aligned (4)`で、`aligned (2)`は0件。
- **payloadの範囲:** 保存領域`0x100A0000`より前で終わる。UF2の書込みは保存領域に触れない。
- **現行firmwareからのfrozen sourceの差分:** 6ファイルのみ。
  - `kagura/framebuffer.py`（#57）
  - `kagura/ui/app.py`、`fonts.py`、`render.py`、`widget.py`、`widgets.py`（#53〜#59）
  - board定義、manifest、整列scriptは同じである。
- **含まれないもの:** `d219778`より後の変更。#62（`fill_rect`/`glyph8`の高速経路）と#64（Canvas）は含まれない。
- **固定:** このUF2（`a5166d79…`）は、source commit `d219778`に恒久的に対応する。
  - 後のmainから作り直さない。置き換えない。名前を付け替えない。
  - 実機検証は、このUF2と、上記の手順で`d219778`から再現した同一のUF2だけを対象にする。

## 実機検証計画（書込みには明示的な許可が必要）

### 0. 前提

- 対象は、接続されているただ1台のPicoである。
- USB serialは照合するが、記録しない。
- HDMIはUGREEN 15390で記録する。
- eraseallはしない。保存領域のファイルは変更しない。

### 1. 書込み前（読取りのみ）

1. XIPの`0x10000000..0x10068300`のsha256が`33f2ac13…`であること（現行firmwareの確認）。
2. 保存領域`0x100A0000..0x10200000`のsha256を記録する（前回は`7b07b001…`）。
3. 2 MiBのFlash全体を読み出して保存し、実機上のhashと照合する（戻すときの保険）。

### 2. 書込み

1. BOOTSELで、候補UF2をコピーする。
2. UF2はfirmware領域だけを書き込む。

### 3. 書込み後の同一性（読取りのみ）

1. XIP `0x10000000..0x10068800`のsha256が`a1095518…`であること。
2. 保存領域のsha256が、手順1-2の値と一致すること。
3. bannerが`v1.26.0 on 2026-11-02`であること。
4. `kagura.ui.__path__`がfrozenであり、ABIが0.6、`ERROR_CODE`が0であること。

### 4. 機能

1. [Phase 2の受入](kagura-ui-phase2.md#最終uf2の受入と残る範囲)と同じ項目を再実行する。
   - 項目:
     - glyph8の288操作（`tests/ui_glyph_runtime.py`）
     - Gallery CRC
     - USBのEnter/Tab/Escape
     - 2つ目のScreenとの往復
     - console復帰
   - 前回の`phase2-final-device.txt`を出したscriptは、commitされていない（`build/ui-phase2/post-soak.py`）。
     - 再実行の前に、このscriptをreviewしてtoolsへ取り込むか決める。
     - #53〜#59は、どれも描画結果を変えていない（各PRでCRC一致）。このため、Gallery CRC `2036752175`が再現することを合格条件にする。
2. 新しいfrozen UIで、次を確認する。
   - `Widget.opaque`が存在する（RAMからの補完が不要になる）。
   - `BitmapFont8`のcacheが64である。
3. `machine.reset()`の後に、通常のconsoleが起動すること。

### 5. 性能

1. `tools/kagura-ui-damage.py run`
   - 2 session、32 samples × 4 rounds。
   - [layout/paint記録](kagura-ui-layout-paint.md)のRAM実測と比べる。
   - 同じsourceなので、CRCは同一になる。時間はfrozenとRAMの差だけが出るはずである。
2. `tools/kagura-ui-soak.py --samples 32 --seconds 3600`
   - [前回の1時間soak](kagura-ui-phase2.md#最終uf2の1時間soak2026-11-02)と比べる。
   - 合格条件:
     - 欠損groupが0件
     - heap（GC後のfree）が一定
     - 静止時の転送が0 tile
     - console復帰
     - `ERROR_CODE 0`
   - frame p50の改善量も記録する。
3. #57のframe時間への効果は、この計測で初めて実機で得られる。

### 6. 電源断（ユーザーの操作が必要）

1. USBを物理的に抜き差しする。
2. 通常のconsoleが起動することを確認する。
3. 保存領域のsha256が変わらないことを確認する。

### 7. 戻す条件と手順

- 手順3〜6のどれかが不合格なら、`9ebfa459…`（`b02a6ef`から再現できる）を同じ手順で書き戻す。
- 書き戻した後、手順1-1と1-2の値に戻ったことを確認する。

### 次の候補

後のmain（#62、#64など）から作るUF2は、別の候補として扱う。

- source commit・sha256・名前は、別に記録する。
- この`d219778`候補は置き換えない。
