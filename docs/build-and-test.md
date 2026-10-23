# ビルド・シミュレーション・書込み

対象はTang Nano 9K（GW1NR-LV9QN88PC6/I5、GW1NR-9C）。ピンと電源条件は[ボード資料](../boards/tang-nano-9k/README.md)、確認済み範囲は[検証状況](validation-status.md)を参照する。以下はリポジトリrootを起点とする。

## シミュレーション

WSL/LinuxでVerilator、g++、make、python3を用意する。ローカル検証に使用したVerilatorは5.032。CIはUbuntuの配布パッケージを使用し、版を固定していない。

```sh
bash tools/test-verilator.sh
```

SystemVerilog testbenchを`--binary --timing`で実行する。ログ・画像・PCM/WAVは`build/verilator/`へ出力する。警告は`-Wno-fatal`で残しており、警告なしlintの合格を意味しない。テストの構成は[sim/README](../sim/README.md)を参照。

PowerShellで文書・設計予算・依存ファイルを確認する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-design.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-dependencies.ps1
```

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
| `spi` / `qspi` | SPI/QSPI接続用のVDP・音源 | `kagura_spi` / `kagura_qspi` |

全構成をまとめてビルドし、構成ごとの証拠manifestを`reports/`へ保存するには`tools/run-baseline.ps1`を使う（[M0基準記録](baseline.md)）。

`dvi`以外は引数に`720`を付けると16:9版になる。例: `demo720`、`phase2720`、`spi720`。basenameも末尾に`720`が付き、`hdmi720`だけは`kagura_hdmi720`となる。第2引数`bars`（既定）/`stress`は単体映像sourceを選ぶ。デモ・ホスト版の描画内容を切り替える指定ではない。

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
