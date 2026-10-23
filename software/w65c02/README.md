# W65C02S SDK (planned)

Phase 2でca65/ld65のID読出し・背景色変更・IRQサンプル、Phase 3でVRAM/font/map、Phase 4でsprite/6ch音源を追加する。
I/O baseは$9F00、[ABI 0.1](../../docs/register-map.md)。indexed/address registerは排他管理し、I/OへRMW命令を使用しない。

現時点ではCPUホストのROM/RAM配置が未定義なので、動作を装う仮のlinker設定や未試験バイナリは置かない。
