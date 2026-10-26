# W65C02S

W65C02S（構成`phase2`/`phase2boot`）から使うための定数。I/O baseは`$9F00`、ABI 0.5（[レジスタ仕様](../../docs/register-map.md)）。

- `kagura_regs.inc`は`tools/gen-registers.ps1`が`spec/registers.json`から生成する（手で編集しない）。`.include`の前に`KAGURA_IO_BASE`を定義すると窓の位置を変えられる。offsetは`KAGURA_REG_*`、絶対addressは`KAGURA_IO_*`、bitはmask値。C用の同じ定数は[`software/include/kagura_regs.h`](../include/kagura_regs.h)。`tools/test-headers.sh`がCとca65でのコンパイル・アセンブルを検査する。
- 窓へはRMW命令（INC、ASL等）やindexed addressingのdummy readを使わない。READ_RESULTを誤って消費する。index系レジスタ（VRAM_ADDR、EXT_REG_INDEX、AUDIO_REG_INDEX）は割込みとメインで排他にする（[プログラミングガイド](../../docs/programming-guide.md#6-irq)）。
- バスtimingとreset回路の条件は[CPUバス](../../docs/timing.md#w65c02sバス)、外付けROMなしの起動は[ROM-less boot](../../docs/romless-boot.md)。

実CPUでの接続は未確認で、CPU側のROM/RAM配置も決まっていないため、linker設定やサンプルのバイナリはまだ置いていない。
