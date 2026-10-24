# ビルド・シミュレーション・書込み

対象はTang Nano 9K（GW1NR-LV9QN88PC6/I5、GW1NR-9C）。ピンと電源条件は[ボード資料](../boards/tang-nano-9k/README.md)、確認済み範囲は[検証状況](validation-status.md)を参照する。以下はリポジトリrootを起点とする。

## シミュレーション

WSL/LinuxでVerilator、g++、make、python3を用意する。基準のVerilator版は`tools/verilator.version`（5.032）。異なる版では警告を出して続行し、`KAGURA_STRICT_VERSION=1`では失敗にする。CIはタグv5.032の固定commitからビルドしてキャッシュする。

```sh
bash tools/test-verilator.sh
```

SystemVerilog testbenchを`--binary --timing`で実行する。ログ・画像・PCM/WAVは`build/verilator/`へ出力する。テストが失敗しても残りを続行し、結果を`build/verilator/summary.tsv`に記録して最後に非0で終了する。開始時に前回の画像・音声・波形出力を削除する。警告は`-Wno-fatal`で残しており、警告なしlintの合格を意味しない。テストの構成は[sim/README](../sim/README.md)を参照。

| 環境変数 | 既定 | 効果 |
|---|---|---|
| `KAGURA_SEED` | 1 | `$urandom`の実行時seed（`+verilator+seed+N`）。ログに記録する |
| `KAGURA_TEST_TIMEOUT` | 1800 | テストごとの実行タイムアウト（秒）。超過は`timeout`として失敗 |
| `KAGURA_TRACE` | なし | 空白区切りのtestbench top名。`build/verilator/<top>.vcd`へ全階層を出力する。大きくなるため対象を絞る |
| `KAGURA_FORCE_FAIL` | なし | 指定topを失敗扱いにする。失敗時の資料が残ることの確認用 |
| `KAGURA_STRICT_VERSION` | 0 | 1でVerilator版の不一致を失敗にする（CI） |

CIでは失敗時も含めログ・`summary.tsv`・画像・PCM/WAV・VCDを`verilator-results` artifactとして保存する。手動実行（workflow_dispatch）では`force_fail`と`trace`を指定できる。

PowerShellで文書・設計予算・依存ファイルを確認する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-design.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-dependencies.ps1
```

レジスタ定義`spec/registers.json`を変更したら定数を再生成し、文書表との一致を確認する。生成物（SV package、Cヘッダ、ca65 include）は手で編集しない。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/gen-registers.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/gen-registers.ps1 -Check
```

WSL/LinuxではCヘッダとca65 includeを`bash tools/test-headers.sh`でコンパイル・アセンブルする。ca65（cc65パッケージ）がなければその部分はSKIPとなり、CIでは`KAGURA_REQUIRE_CA65=1`で必須にしている。

Icarus VerilogとvvpがPATHにあれば`tools/test-phase1.ps1`で基礎source/TMDS試験も実行できる。これは全Verilator回帰の代替ではない。別配置なら`-Iverilog`と`-Vvp`へ実行ファイルのパスを渡す。上流ソースのIcarus用変換はbuild内の試験用コピーにだけ適用する。

## Gowinビルド

検証に使用したEDAはGowin Education V1.9.11.03。実行ファイルのパスはインストール先に合わせる。まずWSL/Linuxのリポジトリrootで派生HDMIソースを生成する。

```sh
python3 tools/prepare-hdmi-stream.py
```

続いてWindows PowerShellで、構成ごとに別のbuildディレクトリから実行する。例は480pのシューティングデモ。

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

| 引数 | 構成 | 出力basename |
|---|---|---|
| `hdmi`（既定） | カラーバー＋左1kHz／右500Hz固定音 | `kagura_phase1` |
| `dvi` | 音声なし比較用 | `kagura_phase1_dvi` |
| `demo` | CPU不要のシューティング＋6ch演奏 | `kagura_demo` |
| `phase2` | W65C02S接続用のVDP・音源 | `kagura_phase2` |
| `phase2boot` | W65C02S ROM-less boot＋VDP・音源 | `kagura_phase2boot` |
| `bootprobe` | CPU/HDMI不要のFlash読出し・K9BT検査 | `kagura_boot_probe` |
| `spi` / `qspi` | SPI/QSPI接続用のVDP・音源 | `kagura_spi` / `kagura_qspi` |

全構成をまとめてビルドし、構成ごとの証拠manifestを`reports/`へ保存するには`tools/run-baseline.ps1`を使う（[M0基準記録](baseline.md)）。

`dvi`以外は引数に`720`を付けると16:9版になる。例: `demo720`、`phase2720`、`spi720`。basenameも末尾に`720`が付き、`hdmi720`だけは`kagura_hdmi720`となる。第2引数`bars`（既定）/`stress`は単体映像sourceを選ぶ。デモ・ホスト版の描画内容を切り替える指定ではない。

`bootprobe`には720版がない。`phase2boot720`は`kagura_line_display`の走査判定を`cy`由来の登録済みフラグに変更した結果、2026-10-24にsetup WNS +0.612ns・hold +0.555ns・TNS 0となった（変更前は-1.510ns）。実機表示は未検証。480pの`phase2boot`は+1.980ns、`bootprobe`は+1.992nsでsetup/hold違反0だった。

## ROM-lessブートイメージ

W65C02S用のraw binaryへ32-byte K9BT headerとCRCを付ける。load addressとlengthは256-byte境界、entryはpayload内でなければならない。最終ページを埋める場合だけ`--pad`を指定する。

```sh
python3 tools/make-boot-image.py program.bin program.k9bt \
  --load 0x0200 --entry 0x0200 --pad
```

Stage 1/3の配線確認用には、`EA 4C 00 02`（NOP、`JMP $0200`）から始まる256-byte payloadを生成できる。

```sh
python3 tools/make-boot-image.py build/romless-smoke.k9bt \
  --smoke-loop --load 0x0200 --entry 0x0200
```

生成物はheaderを含めて外部Flashの`0x100000`へ配置する。programmerによる任意offset書込みと番兵領域の保持はまだ実機検証されていないため、書込みコマンドは確定していない。`python3 sim/tests/test_boot_image.py`で生成器単体を検査でき、全WSL Verilator回帰からも実行される。

Gowinの既定P&R設定は全構成で`place_option 1`、`route_option 1`。後続拡張向けの余裕を優先した設定で、統合構成の実行時間は長くなる。比較実験だけは環境変数`KAGURA_PLACE_OPTION`、`KAGURA_ROUTE_OPTION`で上書きできる。正式な数値は上書きなしのclean commitで`tools/run-baseline.ps1`を実行して保存する。

bitstreamは各buildディレクトリの`impl/pnr/<basename>.fs`。CST/SDC断片とビルド設定packageはスクリプトが生成する。`timing-status.json`には最悪slackと経路・レポートhashを保存する。`-ReportOnly`は結果出力用であり、合否の自動ゲートではない。指定しない場合は数値違反に加えて実機互換性試験が未完了であることでも失敗する。720pのOSER10 RESET除外は[タイミング仕様](timing.md)を参照。

## SRAM書込み

まずSRAMへの一時書込みで確認する。例は上記`demo`構成。ピン・接続条件を確認し、CPU/ホストを接続する場合は[検証状況](validation-status.md)の未完了項目も確認する。

```powershell
$env:PYTHONIOENCODING=$null  # 設定時にprogrammer_cliのPython初期化が失敗した環境での対処
$prog='C:\Gowin\Gowin_V1.9.11.03_Education_x64\Programmer\bin\programmer_cli.exe'
& $prog --cable "Gowin USB Cable(FT2CH)" --channel 0 --frequency 2.5MHz --device GW1NR-9C --run 0
& $prog --cable "Gowin USB Cable(FT2CH)" --channel 0 --frequency 2.5MHz --device GW1NR-9C --run 4 --fsFile "$PWD\build\nano9k-demo\impl\pnr\kagura_demo.fs"
```

`--run 0`でチップID `0x1100481B`を確認した。`--run 4`はSRAM Program and Verify、`--run 2`はSRAM Program。内蔵Flashは変更しない。SRAM内容は電源断で失われる。HDMI・音声・S2 reset後の復帰を確認する。デモのLED表示は[board topのコメント](../boards/tang-nano-9k/kagura_demo_top.sv)に記載。

## 内蔵Flashとprogrammerの注意点

永続化が必要な場合、上記書込みコマンドの`--run 4`を`--run 6`へ変更すると内蔵Flashを上書きする。出荷時デモを含む旧内容は置き換わる。`--run 1`はFlashからの再構成。書込み後は電源再投入による起動も確認する。

検証環境では内蔵Flash書込みに`Verify Failed at 0`が表示された。原因は未特定で、この表示を照合成功として扱わない。再構成・電源再投入後に目的の映像と音声が出ることは確認済み。SRAMの照合は成功している。ビルドではreadbackを許可する`bit_security=0`を使用する。

BL702はWindowsでFTDI互換（VID 0403/PID 6010）として認識された。`--scan`が応答しない場合があり、残ったprogrammerプロセスがcableを保持すると「Cable failed to open」になる。該当プロセス終了とUSB再接続で回復した。無関係なプロセスを終了しない。
