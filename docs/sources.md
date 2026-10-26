# 出典

設計で参照した一次資料と、取り込んだ外部ソースの固定revision。「確認」は資料・ソースを読んだという意味で、実機で追試したという意味ではない。

| ID | 資料 | 参照箇所・留意点 |
|---|---|---|
| S1 | [Tang Nano 9K公式Wiki](https://wiki.sipeed.com/hardware/en/tang/Tang-Nano-9K/Nano-9K) | ボード仕様。型番表記はGW1NR-LV9QN88PC6/I5 |
| S2 | [W65C02Sデータシート](https://www.westerndesigncenter.com/wdc/documentation/w65c02s.pdf) | 2022-04-08版。§3.10 RDY、表6-3、図6-3、表7-1。3.3V列を使う |
| S3 | [GOWIN DS117](https://cdn.gowinsemi.com.cn/DS117E.pdf) | 表1-1、1-2、1-3、2-5〜2-7、3-21（資源、BSRAMのport、PLLの範囲） |
| S4 | Sipeed公式回路図 `Tang_nano_9K_3674_schematics.pdf`（2024-03-11、SHA256 `5e720b0d…f3d8`）、比較用に[3672版](https://dl.sipeed.com/fileList/TANG/Nano%209K/2_Schematic/Tang_Nano_9k_3672_Schematic.pdf) | ヘッダJ5/J6、HDMI回路、SPI Flash（U3）。照合結果は[ボード資料](../boards/tang-nano-9k/README.md) |
| S5 | [Sipeed HDMIサンプル](https://github.com/sipeed/TangNano-9K-example/tree/c3b795799f23de91982be52db4273a8eea100cdb/hdmi) | rPLL（IDIV 2、FBDIV 13、ODIV 4）、CLKDIV /5、TMDSのCST |
| S6 | [hdl-util/hdmi](https://github.com/hdl-util/hdmi/tree/83b1c9543a91b776671a44e68e130f81cae437b7) | HDMI protocol部の基。MIT OR Apache-2.0 |
| S7 | [tn_vdp](https://github.com/lfantoniosi/tn_vdp/tree/d7b80da83701a5e66ea078523a29b8cffd1f2833) | 9K v2の音声付きHDMIの参考（コードは取り込んでいない） |

固定revision:

```text
sipeed/TangNano-9K-example c3b795799f23de91982be52db4273a8eea100cdb
hdl-util/hdmi             83b1c9543a91b776671a44e68e130f81cae437b7
lfantoniosi/tn_vdp        d7b80da83701a5e66ea078523a29b8cffd1f2833
```

## hdl-utilからの派生

- `third_party/hdl-util-hdmi/`にS6の10 RTLと2つのライセンス文を無改変で置き、`manifest.json`にhashを記録する（`tools/check-dependencies.ps1`が検査）。
- `rtl/hdmi/kagura_tmds_channel.sv`は`src/tmds_channel.sv`（Sameer Puri）を基にpipeline化した実装。`tb_tmds_pipeline`が原版との出力一致を検査する。
- `rtl/hdmi/kagura_packet_assembler.sv`は`src/packet_assembler.sv`を基に、counterで選ぶbit muxをshift registerに置き換えた実装。`tb_packet_assembler`が原版と毎cycleの一致を検査する。
- いずれもApache-2.0を選択し、著者と変更をソースに記載している。方針は[第三者IP](../THIRD_PARTY.md)。
