# 通信改善の計測artifact

- [実機比較](device-ram.log): baseline隔離SDK16hash、3設定×6micro×30反復、3設定×4scene、PCM、全VRAM照合。
- [exact RAM workload](run-ram.py) / [候補メソッド](ram-methods.py): SDK sourceからASTで抽出したflush/_flushをRAM subclassへ設定。
- [boot復元](restore-ram.log) / [console](console-ram.log): SHA一致、ABI0.6、ERROR0、console active。
- [SDKテスト](sdk-tests.log): 206件中204成功・2skip。
- [全SDKコピーの容量不足](upload-sdk.log) / [今回の不完全コピーだけの除去](cleanup.log)。
  statvfs換算の負の値も返答どおり記録し、物理空き容量として解釈しない。
- 初回配置失敗後の[boot状態](restore.log)と[console復帰](console.log)も保持。

再計測は事前調査の[clean boot手順](../framebuffer-transport-logs/README.md#追加clean-vm計測とboot復元)と同じ。
SDK16hashに一致する既存kagurafbxが必要。canonical SDKへの上書きやFlash書込みは不要。
setup後は失敗時にも必ずrestoreとsoft-reset、console確認を行う。
RAM workloadの候補methodsは今回のsnapshotで、自動的に新SDKへ追従しない。
今後は新しい候補から抽出してworkload SHAを記録し、controlも取り直す。
解析: `python tools/analyze-framebuffer-gap.py --log <device> --restore-log <restore> --console-log <console> --workload <exact.py>`。

結果は[JSON](../framebuffer-gap-results.json)と[解説](../framebuffer-gap-optimization.md)。
