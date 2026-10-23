# W65C02S SDK (planned)

Phase 2でca65/ld65のID読出し・背景色変更・IRQサンプル、Phase 3でVRAM/font/map、Phase 4でsprite/6ch音源を追加する。
I/O baseは$9F00、[ABI 0.2](../../docs/register-map.md)。indexed/address registerは排他管理し、I/OへRMW命令を使用しない。

レジスタ定数は`kagura_regs.inc`（`tools/gen-registers.ps1`が`spec/registers.json`から生成、手で編集しない）。`.include`の前に`KAGURA_IO_BASE`を定義すると窓の位置を変えられる。offsetは`KAGURA_REG_*`、絶対addressは`KAGURA_IO_*`、bitはmask値。C用の同じ定数は[`software/include/kagura_regs.h`](../include/kagura_regs.h)。`tools/test-headers.sh`がCとca65でのコンパイル・アセンブルを検査する。

現時点ではCPUホストのROM/RAM配置が未定義なので、動作を装う仮のlinker設定や未試験バイナリは置かない。
