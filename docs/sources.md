# 出典・調査記録

調査日: 2026-10-23 JST。URLは一次資料。以下の「確認」は資料・ソースを読んだ意味であり、実機で追試した意味ではありません。

ローカルTMDS置換実装: `rtl/hdmi/kagura_tmds_channel.sv`はS6の固定revisionにある`src/tmds_channel.sv`（Sameer Puri）を基にした実装として管理する。KAGURA側でprefix XORと3段パイプラインへ変更し、`sim/tests/tb_tmds_pipeline.sv`で原版と2クロック遅れの出力一致を検査する。Apache-2.0を選択し、著者・変更表記をソースへ記載。原版・ライセンス本文は`third_party/hdl-util-hdmi/`に保持する。詳細は[依存IP方針](../THIRD_PARTY.md)を参照。

| ID | 資料 | 確認箇所・留意点 |
|---|---|---|
| S1 | [Tang Nano 9K公式Wiki](https://wiki.sipeed.com/hardware/en/tang/Tang-Nano-9K/Nano-9K) | ボード仕様。型番表記はGW1NR-LV9QN88PC6/I5 |
| S2 | [W65C02Sデータシート](https://www.westerndesigncenter.com/wdc/documentation/w65c02s.pdf) | 2022-04-08版、§3.10 RDY、表6-3、図6-3。3.3V列を使用 |
| S3 | [GOWIN DS117](https://cdn.gowinsemi.com.cn/DS117E.pdf) | 3.2.5E / 2026-07-31。表1-1、1-2、1-3、2-5〜2-7、3-21 |
| S4 | [Sipeed公式回路図](https://dl.sipeed.com/fileList/TANG/Nano%209K/2_Schematic/Tang_Nano_9k_3672_Schematic.pdf) | Tang_Nano_9K_3672、履歴6202まで。GW1NR 9K、FPGA_HDMIシート。初回調査時は実物の基板版と未照合。後続の3674版照合は[ボード記録](../boards/tang-nano-9k/README.md)を参照 |
| S5 | [Sipeed HDMIサンプル](https://github.com/sipeed/TangNano-9K-example/tree/c3b795799f23de91982be52db4273a8eea100cdb/hdmi) | 下記ファイルを調査 |
| S6 | [hdl-util/hdmi](https://github.com/hdl-util/hdmi/tree/83b1c9543a91b776671a44e68e130f81cae437b7) | README、LICENSE-MIT/APACHE、serializer、packet_picker、audio_clock_regeneration_packet |
| S7 | [tn_vdp](https://github.com/lfantoniosi/tn_vdp/tree/d7b80da83701a5e66ea078523a29b8cffd1f2833) | README、LICENSE、v2_v9918のtop/serializer/CST。9K v2と20K v3を混同しない |

GitHub APIで取得した調査対象コミット:

```text
sipeed/TangNano-9K-example c3b795799f23de91982be52db4273a8eea100cdb
hdl-util/hdmi             83b1c9543a91b776671a44e68e130f81cae437b7
lfantoniosi/tn_vdp        d7b80da83701a5e66ea078523a29b8cffd1f2833
```

特に参照したS5ファイル:

- `hdmi/src/gowin_rpll/gowin_rpll.v`: IDIV_SEL=2、FBDIV_SEL=13、ODIV_SEL=4、DEVICE=GW1NR-9C。
- `hdmi/src/gowin_clkdiv/gowin_clkdiv.v`: CLKDIV、DIV_MODE="5"。
- `hdmi/src/top.v`: PLL→CLKDIVとロックを使ったリセット。
- `hdmi/src/hdmi.cst`: TMDS各ペアと27MHz入力。
- `hdmi/src/hdmi/svo_tmds.v`: ファイル内許諾文を確認。

再現用評価では上記コミットを固定し、取得ファイル一覧・SHA256・ローカル変更差分・EDAバージョン・デバイス指定・ビルドログを保存する。Phase 0時点ではベンダリングしなかった。継続作業でhdl-utilの10 RTLと2ライセンスを固定して取得済み。採用ファイル・由来は[第三者IP方針](../THIRD_PARTY.md)と`third_party/hdl-util-hdmi/manifest.json`を参照。他候補を含む網羅的な依存ライセンス監査は未実施。
