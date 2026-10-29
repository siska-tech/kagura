# 1,200タイル版：W65C02S ROM-less bootのビルド確認

2026-10-29、実験ブランチ`experiment/tile-1200`の`7aacc850bf88647ce43d3106193d8fac2c1ead16`で検証。ABI 0.6・1,200枚版の`phase2boot`（480p）／`phase2boot720`（720p）は、どちらもbitstream生成とP&R／STAに合格した。RTL・制約・P&R設定の変更は不要だった。

## ビルド結果

Gowin Education V1.9.11.03、GW1NR-9C。環境変数のP&R上書きなし。既存設定は480pがplace 1／route 1、720pがplace 0／route 2。clock・SDCとsetup下限+0.10 nsを変更していない。

| 構成 | Logic | Register | CLS /4320 | BSRAM /26 | 最悪setup ns | 最悪hold ns |
|---|---:|---:|---:|---:|---:|---:|
| phase2boot | 6278 | 4540 | 3972 | 26 | 0.271 | 0.405 |
| phase2boot720 | 6214 | 4541 | 3983 | 26 | 0.132 | 0.555 |

両構成ともsetup／hold違反0、各clockのTNS=0、負のrecovery／removal解析なし。720pのsetup余裕は+0.132 nsで、基準+0.10 nsとの差は0.032 ns。BSRAMは両方とも26個すべてを使用する。

Flash MISOのscoped exceptionも`check-boot-miso-timing.ps1`で検査済み。対象は`boot/reader/data_0_s0`と`rx_shift_0_s0`の2点、setup／hold関係はそれぞれ+4T／-4T（±74.074 ns）。最小setupは480p +14.046 ns／720p +13.509 ns、最小holdは両方+75.281 ns。外部遅延値は既存の仮定で、実基板のAC特性確認を置き換えない。

生成物:

- `build/baseline/phase2boot/impl/pnr/kagura_phase2boot.fs`
- `build/baseline/phase2boot720/impl/pnr/kagura_phase2boot720.fs`

bitstream・CST・SDC・STA／資源reportのSHA-256、source revisionと実測値は[機械可読結果](tile-1200-boot-results.json)に保存した。詳細manifestと全source hashは`reports/7aacc85/Gowin_V1.9.11.03_Education_x64/`にある。bitstreamと生ログはGit管理外。

## simulation

同じRTLをVerilator 5.032、seed 1で再compileし、以下7試験すべて合格。`sim/tests/test_boot_image.py`によるimage生成器の検査も合格。

- `tb_w65c02_bus`：198 selected cycles、read setup／hold、バス競合なし、IRQ位相、W1C、8 PHI2周期後のreset解除。
- `tb_flash_reader`／`tb_flash_reader_timing`：Flash command、backpressure、MISO応答、byte間pause、reset復旧。
- `tb_boot_image_check`：header、load範囲、entry、payload CRCの拒否。
- `tb_boot_window`：stub、ベクタ、保護されたdata port、backpressure。
- `tb_boot_controller`：JEDEC、二重読出し、CRC検査、prefetch、boot window統合。
- `tb_romless_boot_system`：stub命令モデルが256 BをSRAMへコピーしてentryへ到達、KAGURAとSRAMのdecode排他。

生ログは`build/tile1200-boot/`。stub命令モデルの合格は実W65C02Sの全命令・電気特性の確認ではない。既存の1,200枚BG／sprite全画素比較などは[第2段階](tile-1200-stage2.md)、全RTL 61試験は[第3段階](tile-1200-stage3.md)の記録を参照。

## 再現

```bash
python3 tools/prepare-hdmi-stream.py
```

```powershell
./tools/run-baseline.ps1 -Configs phase2boot,phase2boot720
```

CPU／bootの試験を含む全回帰は`bash tools/test-verilator.sh`。今回の再検査では7つのboot／CPU testbenchを同じsource listで再compile・実行した。

## 将来の実機確認

今回はFPGAやPicoへの書込みを行っていない。W65C02S未接続のため実機bootは未確認。将来は[ROM-less boot仕様](romless-boot.md)の外部SRAM、decode、RESB保持、BOOT_MAPのpull-downを実装して確認する。

Flashの`0x100000`へK9BT imageを配置し、JEDEC／CRC検査、reset解除、SRAM転送、entry到達とboot窓解除、通常のABI 0.6レジスタ操作までを確認する。外部CPUバスとFlashのタイミング測定、電源投入・reset反復もその時点で行う。元ABIのbootprobe実績と、今回の1,200枚版の実機bootは別の証跡として扱う。
