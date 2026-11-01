# KAGURA-9 — Claude Code引き継ぎ

記録日2026-11-02 JST。今回の作業は資料のみ。実機への接続・書込みは行っていない。
最初に [CLAUDE.md](../CLAUDE.md)、本書、[ロードマップ](KAGURA_ROADMAP.md)を読む。
詳細な一次証拠は [Phase2記録](kagura-ui-phase2.md)、[UI設計/API](kagura-ui.md)、[Phase1/通常配置受入](kagura-ui-validation.md)。

## Gitとレビュー

開始時branch `feat/kagura-ui-phase2`、HEAD `39d60afcf59d80b1b025370dea1bd92ae966cb14`。
trackedの未commit/未pushなし。旧remote tracking refとのahead/behindは0/0。
既存未追跡`.codex-remote-attachments/`、`.vscode/`は利用者管理として保持し、中身は転記しない。

| PR | 確認した状態 | merge commit | merged UTC |
| --- | --- | --- | --- |
| [#50](https://github.com/siska-tech/kagura/pull/50) | MERGED | `41669a2b656cebceb7f044ebf581e17ef996f200` | 2026-11-01 11:31:55 |
| [#51](https://github.com/siska-tech/kagura/pull/51) | MERGED | `b02a6ef1f39fe3c87283033ab13accf5ff028477` | 2026-11-01 15:35:23 |

fetch後origin/mainは`b02a6ef...`。旧HEADはmainに包含され、両treeのdiffはゼロ。
ローカルmainは古い場合がある。引き継ぎ資料はorigin/mainから`docs/claude-handoff`を作成して追加する。
資料コミットSHAは自己参照せず`git log -1`で取得。今回mainへのマージは行わない。
#51 headのCIはdriver、Pico/Pico W firmware、design、source simulation、Verilatorを含め全チェックSUCCESSを確認した。

```powershell
git status --short --branch
git fetch origin
git log -5 --oneline
git diff --stat origin/main...HEAD
gh pr view 50 --json state,mergedAt,mergeCommit
gh pr view 51 --json state,mergedAt,mergeCommit,statusCheckRollup
```

## 装置とSDK構造

KAGURA-9はTang Nano 9Kでタイル/スプライト映像・音声を生成し、Pico等から制御する系。
FPGAはVRAM・走査・HDMI・音源・command queue・PSRAM controllerを担当。
PicoはMicroPythonアプリ・入力・RAM描画・SPI/QSPI通信を担当する。UIはLVGL互換ではない。

```text
Application -> kagura.ui (App / widgets / layout / input / fonts)
 -> Renderer / FramebufferBackend (clip / cooperative lease)
 -> TileFramebuffer (RAM / Python・Viper / dirty tiles)
 -> Video / Kagura / Link -> transport_rp2 (PIO・DMA SPI/QSPI)
 -> FPGA command engine -> VRAM / video / audio / PSRAM
```

実コードは`software/micropython/kagura/`。`device.py`がcommand/control、`video.py`が描画資源、
`audio.py`が音声、`terminal.py`/`console.py`がHDMI console。
`link.py`/`link_viper.py`、`dma_pack.py`、`transport_rp2.py`を再利用する。
`connect()`は裸のKagura deviceを返す。公開Session APIはない。診断exampleのSessionは診断専用。
`kagura_ja.Font`は再利用するがTextLayerのハード資源はUIと併用しない。
C側は`software/include/`、`software/pico/`、`software/starfall/`も確認する。

## UIの公開APIと実装

`kagura.ui` exports: `App, Widget, Screen, Panel, HBox, VBox, Label, Button, ProgressBar, ListView, Event, EventQueue, TerminalInput, StdinInput, BitmapFont8, Theme, FramebufferBackend`。
MockBackendは`kagura.ui.mock`。Phase1と最初のPhase2最適化まで実装。Canvas/TextBox/Menu/Dialog等は未実装。

| ui/配下 | 構造・制限 |
| --- | --- |
| app.py | App/FocusManager。set_root/start/step/run/stop/close。入力後にpaint、damageなしはflushなし、1 step最大1 flush。callback同期実行で長い処理は全UIを止める |
| widget.py | 親子・cycle/二重所属拒否。arrangeで親相対座標をabsolute boundsへ変換。children順が描画順。親clip継承、移動は旧/新boundsをinvalidate。ScreenはPanel派生 |
| layout.py | HBox/VBox、固定サイズ、padding/spacing。超過は縮めずclip。flex layoutではない |
| render.py | Rendererと排他backend。App damageは単一外接矩形。背景から重なるwidgetを順に再描画し残像防止。tile trackerはSDKのみ |
| events.py | 固定ring標準32。満杯は最新eventをdrop、post=False/dropped増加。Event/UTF-8解析はallocationあり。Tab/ShiftTab/矢印/Enter/Space/Escape、文字/BS/Delete解析。repeatは端末press列、物理releaseは得られずButtonを次stepで解除 |
| fonts.py | protocolはheight/advance/glyph/measure/draw。BitmapFont8は8×8/改行。完全clip内はglyph8、部分clipは横run。内蔵ASCIIの既存text経路維持 |
| widgets.py/theme.py | 基本widgetとpalette/theme。更新はset_text/set_value/set_visible/set_enabled/set_bounds等を使う。属性直接変更ではinvalidateしない場合あり |

focus対象は可視/有効/clip内。ListView上下は選択、App Escapeはstop。
App.runはfinallyでclose。自前loopもfinallyでcloseする。font/deviceは呼出し元が寿命管理。
console指定時のdefault inputはconsole UART。**PC USB端末はStdinInputを明示する**。

通常console REPLの`kagura_console`を使用する例:

```python
from kagura.ui import App, VBox, Label, Button, Theme, BitmapFont8, StdinInput
from kagura_ja import Font
font = Font('/fonts/misaki8.kfnt')
app = App(kagura_console.screen.device, console=kagura_console,
          theme=Theme(BitmapFont8(font)), input_adapter=StdinInput())
try:
    root = VBox(spacing=6, padding=8)
    root.add(Label('KAGURA-9 日本語'))
    root.add(Button('START', on_click=lambda: print('Start!')))
    app.set_root(root)
    app.run()
finally:
    app.close()
    font.close()
```

Gallery/Monitor/Studio mockは`software/micropython/examples/ui_*.py`。examplesはfrozen manifestに含めず、importには配置かhostからsource送信が必要。
Studio mockは配置/操作実証で、保存・編集アプリではない。Monitorは取得不能のGC等を推測しない。
Fontはファイル内binary searchで8行取得、全体をRAMへ読まない。可変幅/大サイズは別draw実装が必要。IME/TTF runtime解析は未実装。

## 資源所有権とABI

TileFramebufferは320×240/4bpp、pixels38400 B、dirty1200 B＋SDK作業領域。
initializeは1200 patterns、BG map/上位bit表とdisplay/OAM状態を設定しspriteを無効化する。
UIはpalette bank0も排他所有。console/TextLayer/独立spriteと共有不可、320×180も拒否。
consoleはpause **かつdetach**。pauseだけではUART dupterm readerが残る。closeでresume/attach。
exclusive=Trueは他ownerを停止済みという呼出し元の宣言で、以前のVRAM復元ではない。
同device/transportの二重leaseは拒否するが、生SDK/別transportの競合は強制検知不能。
console復旧失敗時leaseを保持しclose再試行可能。Framebuffer確保失敗はconsole停止/I/O前に伝播。

| 資源 | 制約 |
| --- | --- |
| patterns | 8×8/4bpp、32 B/個、0..1199。0..1023は0x0000..0x7fff、残りは0xb000..0xc5ff。境界分割はSDKへ任せる |
| BG | 64×32 map、base0x8000、上位bit表0x9000。第2pixel framebufferではない |
| palette | 256色、16色bank。shadow0x9400/active0x9600、各0x200 B |
| OAM | 256 records、shadow0xa000/active0xa800、各0x800 B。line制限等はvideo RTL/仕様も確認 |
| PSRAM | CAPS b3時4 MiB、公開0x400000..0x7fffff、die0のみ。PCM/COPY元、描画器が直接読むframebufferではない。電源投入時不定 |

入力定義`spec/registers.json`、生成`kagura/regs.py`、`rtl/core/kagura_abi_pkg.sv`と実engineを確認する。
ABI0.6、受入実機CAPS0x5B（480p FULL+PSRAM、WIDEなし/RSCROLLあり）。UIは空raster_scrollにも必要なRSCROLLをI/O前検査。
WRITE/READ/FILL/FENCE/COMMIT/AUDIO_COMMIT/COPYは同じ32-entry queueで順序実行。
COMMITはdisplay/EXT snapshotとVBlank時palette/OAM等の反映。**pattern/BGの全画面atomic swapではない**。
pattern書込み/COPY途中の表示があり得る。FENCEは先行処理完了確認でtearing対策ではない。
PSRAM FENCEはcontrollerへの受渡しまで、後続PSRAMアクセスとの順序で一貫性を保証。
flushは連続dirty run/境界を処理しFENCE成功後dirty解除。例外時App damageも保持して伝播。
COMMIT_BUSY中の再COMMIT/raster表書込み等は拒否。ERROR_CODE/IRQを握りつぶさない。
詳細: [レジスタ](register-map.md)、[PSRAM](psram.md)、[Framebuffer](framebuffer.md)。

## 使用した版・実機状態

以下は前セッションの実機記録。今回再接続確認はしていない。

- RP2040/Pico125 MHz、公式MicroPython v1.26.0 commit `4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`、同梱Pico SDK2.1.1。C SDK側手順の2.2.0と区別する。
- SDK/UIは#51 `39d60af`のソースに対応。開発途中生成UF2なのでembedded git IDだけで確定しない。Viper/Link accelerator有効、QSPI5 MHz/4 lanes。
- FPGAはABI0.6/CAPS0x5Bの480p QSPI+PSRAMを確認。**実ロードbitstreamのbinary hash・合成commitは未確認**。過去ABI06 flash logは同binaryの証明にならない。UI作業でRTL/bitstream変更なし。ABI/CAPSだけではbinary identityを確定不能。
- 最終UF2 local `build/ui-phase2/kagura-ui-phase2-final.uf2`: SHA256 `9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c`、text426540/data0/bss5128 B、payload end exclusive0x10068300。
- 1時間計測UF2 local `build/ui-phase2/kagura-ui-phase2.uf2`: SHA256 `188f120b9ef0e557e4ce77c9a11abf6430140c5b1cd81605fecc0fc9d2e97b17`、text426412/data0/bss5128 B、end exclusive0x10068200。
- 差は既存ASCII textをmain実装へ戻したこと。soakはcustom BitmapFontでtext経路を使わず、glyph8ソースは一致。**最終binary自体の1時間soakは未実施**、短時間受入は実施済み。
- 導入前2 MiB Flash backupはlocal `build/ui-phase2/backup-before-glyph8/`。個人データを含むためcommitしない。復元前に対象/hash/保存時点を確認。
- 保存領域はFlash offset0xa0000から1408 KiB。Phase2前後の全領域SHA一致、ファイル変更なし。Phase1で既存boot.pyだけを現行console用に変更した履歴あり。
- 最終状態はHDMI console/USB REPL、COM解放、GUI loop停止。COM番号は再列挙で変化し得る。USB入力はPC端末、UART/HID実機未検証。

local build/は別PCに存在する保証がない。バックアップや個人ファイルをGitへ追加しない。
実機storageは空き不足（負free表示も既存状態）。format/削除で解消しない。SDK/UIは同じfrozen配布一式を使う。

### frozen native alignment対策

v1.26 mpy-toolのThumb native配列aligned(2)でbaseが2 mod4になると、word-aligned PCによるliteral loadが別値を読んだ。
fillで0x33333333が0x03a03533になり縞/CRC不一致を検出。
`align_frozen.py`が生成frozen Cのnative配列をaligned(4)に補正。
`frozen_alignment.cmake`で生成後/compile前に実行、KAGURA_PICO/PICO_W両boardがincludeする。
公式VM/compiler本体patchではない。unit test、実配置、Python/Viper/PC CRCで検証。対策を除去しない。

## 実測と受入

上記RP2040/125MHz/QSPI5MHz、同Font/theme/widget、各32 samples/cycle0。
両profile Viper有効。runsはglyph hookだけ無効。frame µs p50/p95/p99で、HDMI FPSではない。

| workload | runs | glyph8 |
| --- | --- | --- |
| idle | 458/478/480 | 532/549/553 |
| Label | 25436/27063/27760 | 16827/17054/17436 |
| Button | 57802/64955/74373 | 32272/33167/45814 |
| focus | 79604/93971/95704 | 40351/42670/45119 |
| move | 13408/15191/16603 | 13324/13711/13744 |
| scroll | 45117/55995/56874 | 23690/24681/35693 |
| screen | 60656/139201/139458 | 51824/84836/85179 |

Label中央値約34%、focus約49%短縮。同cycleの転送量一致。idle/move改善は主張しない。
percentileはsort後floor((N-1)*p/100)。32 sample p99は長期最悪値ではない。
frameはflushを含む。raw JSONにflush/合成event→invalidateもあり、物理USB到着遅延ではない。

1時間:3601176 ms、537巡、120288 step、各7 workload17184 samples。完了flag/console復帰確認。
各巡GC後free first/last/min/max全て137664 B。開始140544→終了137760 B差2784は初巡確保の固定集計表等を含む。
allocation回数・自動GC回数は未取得。free一定はallocationゼロではない。
idle全sampleで0 tiles/0 B。総22310687 tiles/713941984 pattern payload B（wire overhead除外）。
Label各group p50範囲16768..16881 µs/p99範囲17083..17357 µs。全期間のpercentileではない。
最終GalleryのApp/Theme/StdinInput/tree差4112 B、初回step後UI差45008 B、active free140832 B。
module/関数/font open後、同一関数でGC後差分測定。heap総使用量ではない。
Gallery CRC2036752175（PC/Python/Viper一致）、glyph288操作rolling2456019654/buffer1936776583。
日本語HDMI、Enter/Tab/ShiftTab/Escape、Count2/drop0、画面2→BACK/同fb、console復帰、machine.reset後起動、保存領域不変を確認。
Pico2/2W、UART/HID、正式な物理電源再投入受入は未実施。

## 再現コマンド

全てrepo rootから。依存はPython/PowerShell、gcc/Unix VM等はWSL/Linux。
コマンドのpythonは実際のPython環境を指すようにする。このWindowsではWindowsAppsのpython aliasが実行不能だったため、導入済みCPythonの実体を使用した。`Get-Command python`と`python --version`で確認し、必要ならvenvをactivateする。
過去PC回帰317件（UI33/Framebuffer89/driver62/日本語34/Link15/sakura32/shooter28/showcase10/starfall9/tile1200 2/transport2/alignment1）、C CTest6件。
保存結果と#51 CIの記録であり、資料作成時に全回帰を再実行した意味ではない。
CIの正本は`.github/workflows/micropython.yml`。新変更では再実行しSKIP条件も記録する。

```powershell
python -I software/micropython/tests/test_ui.py
python -I software/micropython/tests/test_framebuffer.py
python -I software/micropython/tests/test_frozen_alignment.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/gen-registers.ps1 -Check
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-design.ps1
python tools/render-kagura-ui.py build/ui-previews
```

Linux/WSL、official v1.26 checkoutをbuild/micropython-srcに用意後:

```sh
git -C build/micropython-src rev-parse HEAD # 上記pinと照合
python3 -I software/micropython/tests/test_driver.py --rp2 build/micropython-src/ports/rp2/modules/rp2.py
for name in ui framebuffer frozen_alignment link sakura shooter showcase starfall tile1200_accept transport_benchmark; do
  python3 -I "software/micropython/tests/test_${name}.py" || exit 1
done
curl -fsSL -o build/misaki_bdf_2021-05-05.zip https://littlelimit.net/arc/misaki/misaki_bdf_2021-05-05.zip
MISAKI_ZIP=build/misaki_bdf_2021-05-05.zip python3 -I software/micropython/tests/test_kagura_ja.py
make -C build/micropython-src/mpy-cross -j4
make -C build/micropython-src/ports/unix VARIANT=standard MICROPY_PY_SSL=0 MICROPY_PY_BTREE=0 MICROPY_PY_FFI=0 FROZEN_MANIFEST= -j4
python3 software/micropython/tests/ui_runtime.py software/micropython/fonts/misaki8.kfnt > build/ui-cpython.txt
MICROPYPATH=software/micropython build/micropython-src/ports/unix/build-standard/micropython software/micropython/tests/ui_runtime.py software/micropython/fonts/misaki8.kfnt > build/ui-micropython.txt
diff -u build/ui-cpython.txt build/ui-micropython.txt
python3 software/micropython/tests/ui_glyph_runtime.py > build/glyph-cpython.txt
MICROPYPATH=software/micropython build/micropython-src/ports/unix/build-standard/micropython software/micropython/tests/ui_glyph_runtime.py > build/glyph-micropython.txt
diff -u build/glyph-cpython.txt build/glyph-micropython.txt
bash tools/test-ci-changes.sh
```

ARM bytecode確認（実機実行の代用ではない）:

```sh
mkdir -p build/mpy
for file in software/micropython/kagura/*.py software/micropython/kagura/ui/*.py software/micropython/kagura_ja/*.py software/micropython/examples/*.py; do
  build/micropython-src/mpy-cross/build/mpy-cross -march=armv6m -o "build/mpy/$(basename "$(dirname "$file")")-$(basename "$file").mpy" "$file" || exit 1
done
```

UF2 build（Arm toolchain/CMake必須、submodule取得はnetwork利用）:

```sh
make -C build/micropython-src/ports/rp2 BOARD=KAGURA_PICO BOARD_DIR="$PWD/software/micropython/boards/KAGURA_PICO" submodules
make -C build/micropython-src/mpy-cross -j4
make -C build/micropython-src/ports/rp2 BOARD=KAGURA_PICO BOARD_DIR="$PWD/software/micropython/boards/KAGURA_PICO" -j4
# Pico WはBOARD/BOARD_DIR末尾をKAGURA_PICO_Wへ変更
```

過去imageはbuild-KAGURA_PICO_PINNEDを使用。標準build directoryと取り違えない。
このホストはWSLのCMake3.31.6/ArmGNU14.2.rel1をPATHへ追加した。
RTL変更時は`bash tools/test-verilator.sh`（5.032）と[build-and-test](build-and-test.md)の設計/依存/header/Gowin timing検査。
Verilatorは既存出力を掃除するので同じ出力先で並列実行しない。
C gameは`bash software/starfall/build-test.sh`を参照。CIはGowin P&R/実機の代用ではない。

### 実機試験

書換えはしないがGUI/REPLを占有する。担当者と時間を合わせ他端末を閉じる。
venvへ`python -m pip install mpremote==1.29.0 pyserial`を用意。
識別子はlocal入力のみ、実値をcommitしない。

```powershell
python -m serial.tools.list_ports -v
$picoPort = Read-Host '実物と照合した対象PicoのCOMポート'
$picoSerial = Read-Host '実物と照合した対象PicoのUSB serial'
python tools/kagura-ui-standard.py --port $picoPort --expected-serial $picoSerial --samples 32 --cycles 2 --log build/ui-comparison.txt
python tools/summarize-kagura-ui.py build/ui-comparison.txt
python tools/kagura-ui-soak.py --port $picoPort --expected-serial $picoSerial --samples 32 --seconds 3600 --log build/ui-quiet-hour.txt
```

toolはraw REPLへsource送信、保存ファイル/firmware変更なし。正常なfrozen SDK/UI/glyph8が必要。
quiet soakはUSBを閉じPico内固定集計を保持、soft resetなしで回収。給電維持、回収前Ctrl+C/resetを避ける。
validatorが完了/件数/時間/idle転送/consoleを検査し同名JSON保存。
host summarizerの--require-secondsは逐次log用、quiet結果にはsoak validatorを使う。
USB停止時に全hub/他機器をresetしない。write timeoutを設け、復旧不能なら対象Pico再接続を依頼。
FPGA側USBをPicoと誤認しない。Windowsのmpremote mountは停止した履歴があり避ける。
firmware更新は全Flash backup/device側hash照合、UF2 family/block/address範囲、BOOTSEL Board-ID、保存境界を確認してから。eraseallはしない。

## 失敗した方法・未解決

| 方法/現象 | 判明事項と扱い |
| --- | --- |
| text()も公開glyph8へ共通化 | Unix ASCII15文字中央値17→36 µsと悪化し不採用。元経路維持後旧17/19、新18/17 µs（2×256）。RP2040時間ではない |
| USB逐次logの1時間試験 | 約43分/386巡でPC standbyにより収集断。ユーザー説明あり。1時間PASSには数えずquiet方式で別途完走 |
| SDKクラス一時patchによる補助ASCII比較 | USB無応答/Ctrl+C timeout。原因未特定、再現条件未確定。再接続後標準ASCII/Viper/Gallery成功。公開GUI/toolはpatchしない。RP2040 ASCII比較時間は未取得 |
| frozen aligned(2) | 上記literal誤読を確認し4-byte補正。Python fallbackだけで解決扱いにしない |
| MicroPython非対応操作 | bytearray.clear/item deletionをslice代入へ変更済み。CPythonだけの合格では不十分 |
| SDK混在 | 旧deviceの_link不足等を検出。ABI一致はソフト版一致ではない。同じ配布一式を使う |
| Windows device restart | 対象Pico再接続commandがOS権限で拒否。自動承認レビュー拒否とは別。利用者USB再接続で復旧 |
| 過去FPGA embFlash Verify Failed at 0 | 原因未特定。reprogram/動作確認をbinary verify成功と呼ばない。UI受入bitstream hashも未確認 |

過去GitHub connector書込み403はgh CLIで対応。tokenを出力しない。
Windows temp sandbox/C compiler不足はbuild配下temp/WSLで対処し、実装不具合と区別した。
最終imageの1時間、正式な電源再投入、GC/allocation実測、Pico2/HIDは未確認のまま残す。

## 次の担当者が最初に行うこと

Git/PRを再確認して新feature branchを作り、UI/Framebuffer/alignment/runtime CRCを再現する。
実機は担当者と状態確認後に使う。[ロードマップ](KAGURA_ROADMAP.md)P0の識別/再現性を確認し、P1 damage/focusを小さなPRで改善する。
CPU/転送/heapを別測定し、重なり/golden/失敗時dirty/console復帰を守る。Canvas/保存まで一度に拡張しない。
