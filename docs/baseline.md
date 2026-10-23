# M0 基準記録

[開発ロードマップ](implementation-roadmap.md)のM0として、現在のチェックアウトから回帰・P&R・STAを再実行した結果。[検証状況](validation-status.md)の`bfd2178`時点の記録は引き継がず、ここでの再測定を基準とする。実機試験は含まない。

## 対象

| 項目 | 値 |
|---|---|
| 対象revision | `9f595f7`（tracked変更なし）。Verilatorは`73dc562`で実行し、`9f595f7`との差分は文書・pin一覧・`tools/run-baseline.ps1`だけ |
| `bfd2178`との関係 | 公開用に履歴を作り直したため祖先ではない。RTLの差分はコメントのみ、sim・tools・CST/SDCは同一 |
| 実施日 | 2026-10-24 |
| シミュレーション | Verilator 5.032（WSL Ubuntu、Debian 5.032-1） |
| EDA | Gowin Education V1.9.11.03、GW1NR-LV9QN88PC6/I5 |
| 証拠の保存先 | `reports/9f595f7/`（Git管理外）。構成ごとに`manifest.json`、STA・資源レポート、生成CST/SDC、build log |

## 結果

設計検査・依存hash検査は合格。Verilator回帰は31件すべて合格（`tools/test-verilator.sh`、exit 0、所要約21分）。Icarus基礎試験（`tools/test-phase1.ps1`、Icarus Verilog 10.1）はsource・TMDSの2件とも合格。

Gowinは全11構成でbitstreamを生成し、setup/hold違反endpoint 0、TNS 0、recovery/removalの最悪slackも正。720pはOSER10 RESETのrecovery/removal経路を除外しており（[タイミング仕様](timing.md)）、その経路を含む保証ではない。

| 構成 | Logic | Register | BSRAM | 最小setup slack | 最小hold slack | pixel Fmax | system Fmax |
|---|---:|---:|---:|---:|---:|---:|---:|
| hdmi | 786 | 414 | 0/26 | +5.634ns | +0.708ns | 74.5MHz | 136.5MHz |
| dvi | 95 | 61 | 0/26 | +5.634ns | +0.709ns | 127.3MHz | — |
| phase2 | 4306 | 3210 | 24/26 | +0.077ns | +0.568ns | 65.4MHz | 54.22MHz |
| demo | 6270 | 3633 | 26/26 | +0.020ns | +0.560ns | 67.2MHz | 54.06MHz |
| spi | 4397 | 3243 | 24/26 | +0.019ns | +0.559ns | 63.8MHz | 54.05MHz |
| qspi | 4391 | 3245 | 24/26 | +0.072ns | +0.560ns | 61.1MHz | 54.21MHz |
| hdmi720 | 811 | 416 | 0/26 | +0.391ns | +0.560ns | 80.4MHz | 133.3MHz |
| phase2720 | 4332 | 3211 | 24/26 | +0.058ns | +0.558ns | 74.87MHz | 54.17MHz |
| demo720 | 6280 | 3634 | 26/26 | +0.030ns | +0.555ns | 74.87MHz | 54.09MHz |
| spi720 | 4437 | 3244 | 24/26 | +0.029ns | +0.555ns | 74.41MHz | 54.28MHz |
| qspi720 | 4432 | 3246 | 24/26 | +0.095ns | +0.558ns | 74.94MHz | 54.28MHz |

pixel Fmaxはpixel25（480p）またはpixel74（720p）。system54・pixel74ではFmaxが要求周波数をわずかに上回るだけで、配置の変動で違反に転じ得る。

## 既存記録との差異

いずれも原因を確認し、各文書を現行値へ更新した。

- **構成数**: 既存文書は「全10構成」と記載していたが、`build-nano9k.tcl`が受け付ける構成は上表の11個（dviの720版なし）。今回は11構成すべてを測定した。
- **demo720**: 記録はLogic 6301・setup +0.085ns、再測定はLogic 6280・+0.030ns。記録は720p導入時の`1c1dcd8`の値で、その後`918e4f7`で`kagura_demo_sequencer`の自機配置が変わった。`1c1dcd8`を同じEDAで再ビルドすると6301 / 3634 / +0.085nsを再現した。他の720p構成は資源・slackとも記録と一致した。
- **480pの余裕**: demo +0.020ns、spi +0.019nsで、720p各構成より小さい。M3のcritical path改善は720pだけでなく480pも対象にする。
- **回帰件数**: 「全回帰30件」は`1c1dcd8`時点の数。`918e4f7`で`tb_demo_shooter720`が追加され、`9f595f7`時点で31件。

## 未測定・対象外

- 実機試験全般（HDMI互換性、外部ホスト・W65C02S接続、電源投入反復）。必要な機材は[機材一覧](equipment.md)。
- Verilatorの警告なしlint。
- OSER10 RESET解除の720p実機評価。
- Gowin P&RのCI上の再現（ローカルのみ）。Verilator回帰は#11以降CIで5.032に固定して実行する。

## 再実行

```sh
bash tools/test-verilator.sh
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-design.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-dependencies.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run-baseline.ps1
```

`run-baseline.ps1`は`build/baseline/<構成>/`でビルドし、`reports/<revision>/<EDA>/<構成>/manifest.json`にcommand、revision、tree hash、tracked変更、生成HDMI source・CST/SDC・bitstream・レポートのSHA256、資源、STAを記録する。いずれかの構成がビルド失敗またはSTA不合格なら非0で終了する。`-Configs`で構成を限定、`-Gowin`でEDAを指定できる。
