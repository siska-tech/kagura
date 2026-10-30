# Transport baseline artifacts

2026-10-30、main `a105f59`。解釈・限界は[分析](../framebuffer-transport-analysis.md)、
数値は[results JSON](../framebuffer-transport-results.json)、操作時系列は[実機ログ](../framebuffer-transport-hardware-log.md)。
raw sampleを持つログと、その時実行したコードを保存する。失敗したworkloadも成功値に混ぜず保全する。

| artifact | 内容 |
|---|---|
| [micro-0-1024.log](micro-0-1024.log) / [workload](workload-initial.py) | FW復旧前、46 micro条件×30。次の1200準備でMemoryError、finally完了 |
| [micro1200-scenes-abc.log](micro1200-scenes-abc.log) / [workload](workload-micro1200-scenes-abc.py) | FW復旧後、1200の4条件、Scene A/B/C revision1。D独立source確保でMemoryError |
| [full-source-allocation-failure.log](full-source-allocation-failure.log) / [workload](workload-full-source-allocation-failure.py) | sourceを先に確保した試験。今度はFramebuffer plane確保で失敗。性能値なし |
| [finish-device.log](finish-device.log) / [workload](workload-finish-safe.py) | Dの960byte wrap source、4 scene revision2、heap観測較正、profile、DMA9条件、primitive7条件、全VRAM照合 |
| [CPU pack / native validation workload](workload-cpu-pack-and-validation.py) | 同じmpremote接続の次action。DMA close後のCPU batch、Python/Viper1090操作、text、paint tiny stack guard。結果はfinish-device.log末尾 |
| [restore-console.log](restore-console.log) / [workload](workload-restore-console.py) | Flash再ロード後ABI0.6/ERROR0/console active。旧bootのbytesもhexで保存 |
| [finish-operations.log](finish-operations.log) | 検証成功を待ってからFlash書込み・reload・console復帰へ進んだhost時系列 |
| [flash-abi06.log](flash-abi06.log) / [reload](flash-abi06-reload.log) | exit0でもVerify Failed。reload後の起動確認とFlash照合を混同しない |
| [uf2-recovery.log](uf2-recovery.log) | 許可されたPico firmware書戻しのコピー時刻。picotoolではdriver不足でreadbackできずUF2 driveを利用 |
| [native helper manifest](native-helper-manifest.log) / [workload](workload-native-helper-manifest.py) | 復帰後に通常権限のmpremoteからread-onlyでroot Viper helper2ファイルをSHA-256取得し、console active/ERROR0を再確認 |
| [SDK host tests](sdk-tests.log) / [PIO tests](pio-tests.log) / [RTL](rtl-summary.tsv) | 既存196件中194成功・2skip、公式assembler付き60件、61 testbench。重複を含むので合計しない |

`workload-remaining.py`は旧runnerで送信が停止し実行ACKを得ていない準備コード。
`resume-operations.log`、`full-source-operations.log`は中間の失敗状態。
各baseline workloadと入力ログのSHA-256はresults JSONに収録する。
Windows PowerShellのUTF-16ログは意味を変えずUTF-8へ転記した。元ログは`build/transport-analysis/`に保持。

## 安全な再計測

PicoのABI0.6 consoleがPIOを所有していても、生成コードのpreludeがcloseしてから単独で接続する。
終了時はSession.closeでPCM停止・DMA/PIO解放。canonical `/lib/kagura`は書き換えない。

1. Git状態、FW/SDK/bitstream hash、CPU125MHz、ABI0.6、480p、QSPI5MHzを記録。
2. `python tools/prepare-framebuffer-transport.py --phase all --repetitions 30 --output build/transport-analysis/baseline.py`
3. Windows管理者terminalなど、COM7へ安定接続できる環境で標準mpremoteを利用:

   ```text
   mpremote connect COM7 run build/transport-analysis/baseline.py run docs/framebuffer-transport-logs/workload-cpu-pack-and-validation.py
   ```

   stdoutをUTF-8ログへ保存する。hostからの大きいraw REPL一括送信より、標準raw-pasteを推奨。
   この調査ではUSB parent再初期化・管理者権限等も変えているため、raw-pasteだけでCOM7が直る保証ではない。
4. 実行ログを`tools/analyze-framebuffer-transport.py --log <log>`へ渡す。
   完了markerだけでなくmicro/scene/readback/native/consoleのcoverageを確認する。
   current_run.statusはconsole復帰のログも揃うまでpartialのままとする。
5. 今回はboot.pyが既存`kagura1200.console`を使うよう移行済み。
   新しいbenchmark後はsoft resetでそのconsoleを再起動し、既存console所有deviceでABI/error/activeを確認する。
   既にPIO所有者がある状態で別のconnectを重ねない。

   ```text
   mpremote connect COM7 soft-reset exec "import json; c=kagura_console; print('TILEFB '+json.dumps(dict(event='transport_console_restored',abi=list(c.screen.device.abi),console_active=c._attached,error=c.screen.device.read_reg(0x17))))"
   ```

   この出力ログも`--extra-log`で解析へ渡す。

**workload-restore-console.pyは今回の一度だけのboot移行用で、そのまま再実行しない。**
既存backupを守るassertを含む。今後の再計測でFlash再書込みやboot移行は不要。

SDKを変える場合は、変更後の別namespaceへ配置・hash照合し、`--sdk <name>`と
`--deployment-manifest <json>`を指定する。manifestの`deployed`配列はsource/remote/sha256を持つ。
baseline/candidateともexact workload SHA・FW・clock・GC/telemetry/PCM条件を揃えて再取得する。
immutable snapshotは今回の再現用であり、新SDKへ自動追従するコードではない。

0〜1024はFW binary hash未採録の先行phaseで、他の値はFW書戻し後。
同じv1.26.0バナー・SDK16hash・clock・link条件は確認したが、微小な改善率の厳密A/Bでは
今回の数値だけと比較せず、固定FWでcontrolも再取得する。
FW書戻し用UF2は`build/transport-analysis/firmware-v126-original.uf2`、SHA256
`0aeffbeb2851b64bfcdc6412b89e19926321570100927303afda86b526d4bc5b`。

Scene Dの独立全画面source版はconsole起動後にはRAM確保に失敗したが、
一回だけconsoleを起動しないclean VMでは成功した。既定は960byte wrap sourceを使う実コピー。
`--phase fullblit --independent-full-source`は追加38400byteが必要な別条件。
追加Dと矩形は通常権限のmpremoteで取得しており、Windows管理者権限は必須とは判定しない。
heap最大使用量はsampled値、純BUSY/FPGA内部時間/物理HDMI表示頻度は未測定。

追加計測コードはホストで2件の刺激・統計テスト、実MicroPythonコンパイラで構文確認を実施。
host plottingにはmatplotlibを使い、描画時間をPico性能値として扱わない。

## 追加clean VM計測とboot復元

[矩形ログ](rectangles-clean.log) / [workload](workload-rectangles-clean.py)、
[独立全画面blitログ](fullblit-clean.log) / [workload](workload-fullblit-clean.py)を追加した。
bootの一時変更と復元は[矩形ログ](rectangles-clean.log)、[復元ログ](restore-clean-boot.log)、
[最終console確認](console-final-clean.log)に記録する。

console起動後のVMではmodule eviction後にも連続38400byteを確保できなかった。
再計測で同じ症状が出る場合、今回と同一boot SHAのみを対象とする
[setup](workload-setup-clean-boot.py)、[rearm](workload-rearm-clean-boot.py)、
[restore](workload-restore-clean-boot.py)がexact snapshotとしてある。
setupは現在bootを別名へ保存し、one-shot flagがある一回だけconsole起動を省略する。
flag消費後の次回bootは元のconsoleを起動する。元boot backupは既存ならassertで拒否する。
**setupを使用した場合、成功・失敗によらずfinallyでrestoreを実行し、soft-resetしてconsoleを確認する。**
他のboot/FW/SDKにはそのまま適用しない。Flashやcanonical SDKの変更は不要。

```text
mpremote connect COM7 run workload-setup-clean-boot.py soft-reset run workload-rectangles-clean.py
mpremote connect COM7 resume run workload-rearm-clean-boot.py soft-reset run workload-fullblit-clean.py
# 上の結果によらず最後に実施する
mpremote connect COM7 resume run workload-restore-clean-boot.py
mpremote connect COM7 soft-reset run workload-console-check-only.py
```

全計測の再取得も同じclean VM方法で可能だが、`--phase all`の既定Dはscroll版である。
独立source Dは別Sessionとして取得し、過去のscroll版との速度差を改善率と呼ばない。

[最終SDK host再実行](sdk-tests-final.log)は追加2件を含む198件中196成功・2skip。CPythonの表示描画速度は実機値ではない。
