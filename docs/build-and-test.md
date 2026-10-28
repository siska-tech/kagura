# ビルド・テスト・書込み

対象はTang Nano 9K（GW1NR-LV9QN88PC6/I5、GW1NR-9C）。コマンドはリポジトリのrootから実行する。ピンと配線は[ボード資料](../boards/tang-nano-9k/README.md)、構成の一覧は[アーキテクチャ](architecture.md#ビルド構成とcaps)。

## 必要なもの

| 用途 | ツール |
|---|---|
| RTL simulation | WSL/LinuxのVerilator 5.032（`tools/verilator.version`）、g++、make、python3 |
| 設計検査・生成 | PowerShell（Windows PowerShell 5.1またはpwsh） |
| FPGAビルド | Gowin EDA（Education V1.9.11.03、またはStandard V1.9.12.04で確認） |
| 書込み | Gowin Programmer（`programmer_cli.exe`）、基板内蔵のBL702 |
| Pico firmware | Pico SDK 2.2.0、Arm GNU Toolchain、CMake（[Pico firmware](../software/pico/README.md)） |
| ヘッダ検査（任意） | cc65のca65 |

## シミュレーション

```sh
bash tools/test-verilator.sh
```

SystemVerilog testbenchを`--binary --timing`で実行し、ログ・画像（PPM）・音声（PCM/WAV）を`build/verilator/`へ出す。失敗しても残りを続け、結果を`build/verilator/summary.tsv`に書いて最後に非0で終了する。開始時に前回の画像・音声・波形を消す。警告は`-Wno-fatal`で残すので、警告なしlintの合格ではない。共有のbuild/logへの同時実行はlockで拒否する。試験の一覧は[sim/README](../sim/README.md)。

| 環境変数 | 既定 | 効果 |
|---|---|---|
| `KAGURA_SEED` | 1 | `$urandom`のseed（`+verilator+seed+N`）。ログに記録する |
| `KAGURA_TEST_TIMEOUT` | 1800 | 試験ごとのtimeout（秒） |
| `KAGURA_TRACE` | なし | 空白区切りのtestbench名。`build/verilator/<top>.vcd`へ全階層を出す |
| `KAGURA_FORCE_FAIL` | なし | 指定した試験を失敗扱いにする（失敗時の資料の確認用） |
| `KAGURA_STRICT_VERSION` | 0 | 1でVerilatorの版違いを失敗にする（CI） |

Icarus Verilogがあれば`tools/test-phase1.ps1`で基礎的なsource/TMDS試験も動く（全回帰の代わりではない）。

## 設計検査とレジスタ定義の生成

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-design.ps1        # BSRAM・cycle予算、文書link、直接窓、boot分周契約
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-dependencies.ps1  # third_partyのhash
powershell -NoProfile -ExecutionPolicy Bypass -File tools/gen-registers.ps1 -Check
```

`spec/registers.json`を変えたら、`tools/gen-registers.ps1`（`-Check`なし）でSV package・Cヘッダ・ca65 includeを再生成し、`-Check`で文書の表との一致を確認する。生成物は手で編集しない。`bash tools/test-headers.sh`はCヘッダとca65 includeをコンパイル・アセンブルする（ca65がなければSKIP、CIでは必須）。

## Gowinビルド

まずWSL/Linuxで派生HDMIソースを生成する（`test-verilator.sh`も生成する）。

```sh
python3 tools/prepare-hdmi-stream.py
```

続いてWindows PowerShellで、構成ごとに別のbuildディレクトリから実行する。例は480pのデモ。

```powershell
New-Item -ItemType Directory -Force build/nano9k-demo | Out-Null
Push-Location build/nano9k-demo
try {
  & 'C:\Gowin\Gowin_V1.9.11.03_Education_x64\IDE\bin\gw_sh.exe' '../../tools/build-nano9k.tcl' demo
  if ($LASTEXITCODE -ne 0) { throw 'Gowin build failed' }
} finally { Pop-Location }
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-nano9k-timing.ps1 `
  -BuildDir build/nano9k-demo -BaseName kagura_demo -ReportOnly
```

- 第1引数は構成名（`hdmi`、`dvi`、`demo`、`phase2`、`phase2boot`、`spi`、`qspi`、`spipsram`、`qspipsram`、`bootprobe`、`magicprobe`）。`720`を付けると16:9版（dvi・bootprobe・magicprobeを除く）。
- 第2引数`bars`（既定）/`stress`はカラーバー版の映像sourceの選択で、デモ・ホスト版の描画には関係しない。
- bitstreamは`impl/pnr/<basename>.fs`。CST/SDCの断片とビルド設定package（`kagura_build_config`）はscriptがbuildディレクトリに生成する。
- `check-nano9k-timing.ps1`は最悪slackと経路・レポートhashを`timing-status.json`へ書く。`-ReportOnly`は結果の出力だけで、合否のgateではない。
- P&Rの既定は`place_option 1`・`route_option 1`（一部の720p構成は例外。[STA](timing.md#sta)）。比較実験だけ`KAGURA_PLACE_OPTION`・`KAGURA_ROUTE_OPTION`で上書きできる。
- `KAGURA_PSRAM_DEBUG=1`でPSRAM端子の捕捉機能付き、`KAGURA_TIMING_AUDIT=1`でhold経路を多く出すレポート、`KAGURA_SIM_NETLIST=1`で配置配線後のnetlistとSDFを出す。
- readbackを許可する`bit_security=0`でビルドする。

### 全構成の基準測定

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run-baseline.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run-baseline.ps1 -Configs spipsram,qspipsram720
```

全構成（16構成）をビルドし、構成ごとのmanifest（command、source/bitstream hash、CST/SDC、資源、slack、合否）を`reports/<revision>/<tool>/<構成>/`へ保存する。既定のgateはWNS ≥ +0.10ns。未コミットの変更があるときは差分hashを含む別のディレクトリへ保存する。`reports/`はGit管理外。

## SRAMへの書込み

まずSRAMへ一時的に書いて確認する。

```powershell
$prog='C:\Gowin\Gowin_V1.9.11.03_Education_x64\Programmer\bin\programmer_cli.exe'
& $prog --cable "Gowin USB Cable(FT2CH)" --channel 0 --frequency 2.5MHz --device GW1NR-9C --run 0
& $prog --cable "Gowin USB Cable(FT2CH)" --channel 0 --frequency 2.5MHz --device GW1NR-9C --run 4 --fsFile "$PWD\build\nano9k-demo\impl\pnr\kagura_demo.fs"
```

`--run 0`でchip ID `0x1100481B`を確認する。`--run 4`はSRAM Program and Verify、`--run 2`はSRAM Program。内蔵Flashは変わらず、電源断で消える。`PYTHONIOENCODING`が設定されているとprogrammer_cliの初期化に失敗した環境があり、その場合は`$env:PYTHONIOENCODING=$null`にする。

## 内蔵Flashへの書込み

`--run 4`を`--run 6`にすると内蔵Flashへ書き、電源投入時に自動で起動する（出荷時のデモは上書きされる）。`--run 1`はFlashからの再構成。書込み後は電源の再投入で起動を確かめる。

内蔵Flashへの書込みでは`Verify Failed at 0`が表示されることがある。原因は未特定で、この表示を照合成功とは扱わない（再構成・電源再投入後の動作は確認している）。SRAMの照合は成功する。

外部SPI Flash（ROM-less boot用）への書込みは[ROM-less boot](romless-boot.md#flashへの書込み)。

## programmerの注意

- BL702はWindowsでFTDI互換（VID 0403/PID 6010）として見える。
- `--scan`が応答しないことがある。残ったprogrammerのprocessがcableを保持すると「Cable failed to open」になるので、そのprocessを終了してUSBを挿し直す。

## CI

GitHub Actions（`.github/workflows/`）は、設計検査・link検査・`gen-registers.ps1 -Check`・依存hash、Icarus基礎試験、Verilator回帰（5.032を固定commitからビルドしてキャッシュ）、ヘッダ検査、Pico firmwareのビルドを実行する。失敗時もログ・`summary.tsv`・画像・PCM/WAV・指定したVCDを`verilator-results`、UF2を`pico-firmware`のartifactに残す。手動実行（workflow_dispatch）では`force_fail`と`trace`を指定できる。Gowin P&Rと実機試験はCIでは行わない。

実行条件は次のとおり。

- pull requestと`main`へのpushでは、`tools/ci-changes.sh`が変更ファイルから必要なjobを選ぶ。

  | 変更 | 実行するjob |
  |---|---|
  | RTL・テストベンチ・`third_party/` | Verilator回帰、Icarus基礎試験・ヘッダ検査・依存hash |
  | `spec/registers.json`・`tools/gen-registers.ps1`・workflow・`tools/ci-changes.sh` | すべて |
  | `software/include/` | ヘッダ検査等、Pico firmware |
  | `software/pico/` | Pico firmware（`software/pico/tests/test_pio_timing.py`はMicroPythonのテストも） |
  | `software/micropython/kagura/`・`boards/`・`manifest.py` | MicroPythonのテストとUF2ビルド |
  | 上記以外の`software/micropython/`・`tools/gen-kagura-ja-font.py` | MicroPythonのテスト |
  | Markdown・`docs/`・制約ファイル・合成用tool | Phase 0のみ |

  どの規則にも当たらないファイルは全jobを実行する。Phase 0（設計検査・link検査）は常に実行する。
- 手動実行と毎週月曜03:00（JST）の定期実行（`main`）は全jobを実行する。
- 実行しないjobはskippedになり、各workflowの`Phase 1 result`・`MicroPython result`は常に結果を返す。必須チェックにはこの2つと`design-documents`を指定する。
- 規則を変えたら`bash tools/test-ci-changes.sh`を実行する。追跡中の全ファイルがいずれかの規則に当たることも確認する。
