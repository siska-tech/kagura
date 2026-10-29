# 1,200タイル対応実験

2026-10-29開始。元リポジトリ `C:\Users\Shion\Documents\Projects\Kagura` の `e909cacd87c207383924b8c15313147940fc14bc` をローカルcloneし、独立したGitリポジトリ `C:\Users\Shion\Documents\Projects\Kagura-tile1200` を作成した。ブランチは `experiment/tile-1200`。元の履歴を保持し、source remoteは元リポジトリの参照用とする。GitHubへの新規作成・公開は行っていない。

第1段階のRAM確保を完了し、[第2段階の1,200パターン実装](tile-1200-stage2.md)がsimulationとホスト4構成のP&R/STAに合格し、[第3段階](tile-1200-stage3.md)で実Picoによる全量読戻し・1時間連続動作・文字キャッシュを数値検証した。以下の第1段階の数値は1,024枚版の記録。調査とABIの候補は[調査書](tile-1200-feasibility.md)を参照。

## 第1段階の変更

- `kagura_line_display.sv`：512×16の2配列を1024×16の1配列へ統合。system用portとpixel用portは維持し、bank番号をアドレスbit9へ組み込む。通常描画は従来の1cycle読出しを維持する。初期化はpixel読出し停止を確認してから全1024 wordを順に消去する。
- `kagura_command_queue.sv`：32 descriptor分の128×16配列を明示し、Gowinの `syn_ramstyle="distributed_ram"` を指定。4wordのstaging、満杯判定、同期読出しと順序保証は維持する。
- `tb_vdp_frame.sv`：起動前のRAM汚染・全領域ゼロ照合を新しい物理配置へ追従。system単独resetの既存試験も実施する。
- `spec/design-budget.json` とメモリマップ：BSRAMの設計モデルを26→24個へ更新。command queueの256 BはBSRAM payload集計から外し、分散RAMとして記載する。Logic/FFの旧概算は新実装の測定値ではなく、資源判断は以下のP&R結果を使う。

実験では現在使用されている `kagura_line_display` を変更した。旧 `kagura_line_banks` はwrapper検証用の別moduleとして残している。

## 検証

Verilator 5.032、seed 1。再実行はリポジトリ直下で以下を実行する。

```bash
bash tools/test-tile1200-stage1.sh
```

対象は `tb_vram_core`、`tb_psram_core`、`tb_startup_cpu`、`tb_vdp_frame`、`tb_vdp_sprites`、`tb_vdp_frame720`、`tb_vdp_sprites720`。ログは `build/tile1200-stage1/` に保存する。

P&R/STAはGowin Education V1.9.11.03、既定のboard制約・P&R optionで行う。

```bash
python3 tools/prepare-hdmi-stream.py
```

```powershell
./tools/run-baseline.ps1 -Configs qspi,qspipsram,qspi720,qspipsram720
./tools/check-design.ps1
./tools/gen-registers.ps1 -Check
```

7試験すべて合格。480p/720pそれぞれBGのみ・spriteありの全画素比較、起動時RAM汚染からのクリア、pixelを動かしたままのsystem単独resetを確認した。この段階では全58試験の一括回帰は未実施。第3段階の最終版では追加試験込み61件すべて合格。

4構成すべて `sta_pass`、setup/hold違反0、負のrecovery/removal解析なし。開発下限のsetup +0.10nsを満たした。

| 構成 | Logic | Register | CLS /4320 | BSRAM /26 | 最悪setup ns | 最悪hold ns |
|---|---:|---:|---:|---:|---:|---:|
| qspi | 5330 | 4216 | 3842 | 23 | 1.689 | 0.552 |
| qspipsram | 6911 | 5167 | 4136 | 23 | 0.156 | 0.552 |
| qspi720 | 5364 | 4217 | 3870 | 23 | 0.383 | 0.552 |
| qspipsram720 | 6978 | 5168 | 4128 | 23 | 0.536 | 0.555 |

4構成ともBSRAMは23個となり、追加パターン用に3個を確保できた。command queueは分散RAMに配置され、line RAMはDPB 1個に統合された。BSRAMを確保できても、BG上位bit表・11bit配線・19bankの返却muxを加えた実装の成立は未確定。

特にqspipsramはCLSが4136/4320（約96%）、最悪setupは+0.156nsと余裕が小さい。次段階ではBG上位bit表の資源と、追加muxによる配置・タイミング変動を重点確認する。demo・CPU・SPI構成のP&Rは今回の対象外。

機械可読の結果と変更RTLのSHA-256は[第1段階の結果](tile-1200-stage1-results.json)に保存した。詳細manifestは `reports/e909cac-dirty-*/Gowin_V1.9.11.03_Education_x64/`、生のsimulation・合成・P&Rログは `build/` にある（いずれもGit管理外）。

`check-design.ps1`、`gen-registers.ps1 -Check`、`git diff --check`も合格。

## 次の段階

第2段階の1,200枚対応は[実装・検証記録](tile-1200-stage2.md)を参照。追加領域の全量読戻し、PCM併用・1時間連続動作、文字キャッシュの数値検証は[第3段階](tile-1200-stage3.md)で完了。その後、720p・Picoホストで追加領域・境界BG／sprite・反転・palette・PCMの[目視・聴感にも合格](tile-1200-visual.md)。480pや動きのある画面、sink／ケーブル互換性等は未確認。

FPGA standaloneのdemo／demo720はdeprecatedとし、既定のP&R対象から除外した。以降はPicoホストを中心に検証する。ソースと旧試験・過去の証跡は保持する。

実機にはSRAMだけを書き換えて数値検証を実施した。FPGA FlashとPico firmwareは変更していない。既存の[検証状況](validation-status.md)は元設計の過去の証跡であり、実験版の動作保証とは区別する。

## W65C02Sの将来実装に向けた確認

1,200枚版の`phase2boot`／`phase2boot720`もbitstream生成・P&R／STAとboot／CPU simulationに合格した。[検証記録](tile-1200-boot.md)を参照。W65C02S実機でのbootは未確認。
