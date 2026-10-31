# PROJECT STARFALL Phase 0 / 1検証記録

2026-10-31。初版作成時、エージェントから実機への書込み・操作は行っていない。
その後ユーザーが実機で映像・移動・ショットを確認。
[ユーザー提供ログ](starfall-phase1-user-hardware-2026-10-31.txt)ではoverflow/audio faultは0、
missed累計46、blank_overruns累計1。欠落のない60fps達成は未確認。
以下の表の「未検証」は初版作成時点の記録。
コードと手順: [software/starfall](../../software/starfall/README.md)。
予算/全Phase計画: [設計書](../starfall-design.md)。

| 検査 | 結果 |
|---|---|
| 最新main確認 | git fetch、3f08ea623c56021cc90e49f19df95c23cc3648dc |
| 現checkoutとmainのAPI/RTL差分 | 対象仕様、software/pico、software/include、rtlに差分なし |
| PCビルド | WSL GCC 15.2.0、C11、Wall/Wextra/Werror、ASan/UBSan |
| deterministic_game | PASS、180/240各216000固定step、同入力同seedで状態一致 |
| backend_contract | PASS、表示停止初期化、FENCE、VBlank待ち、dirty OAM、転送失敗時cache保持 |
| Picoビルド | SDK 2.2.0、Arm GCC 14.2.1、Release、SPI/QSPI別UF2 |
| 生成レジスタ照合 | gen-registers.ps1 -Check PASS |
| 設計検査 | check-design.ps1 PASS（既存RTLのBSRAM予算26/26、payload 50176 B） |
| RTL sprite selector | Verilator 5.032 PASS、278 lines、2325 entries、16上限/clip/overflow/stall |
| RTL sprite composite | PASS、138 lines×320pixel、1911 writes、最大1702 cycles |
| RTL register ABI | PASS、223 checks |

これら3件は既存RTLテストであり、ゲーム全体のHDMI/音声/PIO end-to-end simulationではない。
RTLは変更していない。全RTL回帰、合成、STAは今回実施していない。

## 使用量

SPI/QSPI ELF: text=50088 B、data=0 B、bss=9628 B（SDK/USB/driverを含む）。
静的SRAMは9628 B。stack、SDK実行時利用、high-water markは別途実機測定が必要。
ゲーム状態120 B、描画frame76 B（ホスト試験出力）。
UF2は通常flash build。生成物は `build/starfall-pico/starfall.uf2` と
`build/starfall-qspi/starfall.uf2`。ビルドログ: `build/starfall-build-test.log`。
RTLログ: `build/starfall-rtl/*.run.log`。再現コマンド:

```sh
bash software/starfall/build-test.sh
bash software/starfall/test-rtl.sh
```

最終UF2は各92160 B。SHA256:

```text
SPI  9C9761512800C5E5D1CE38842D6D99643AE99ABA0745206EE2FE0A0569F74309
QSPI 752009D41DF18AD3C0127871B521D2FAB17ED2CF9596976E04CDCE6E3F5371E0
```

保存済みログ: [ホスト試験](starfall-host-2026-10-31.txt)、[関連RTL](starfall-rtl-2026-10-31.txt)。
最終ホスト再検査2/2 PASS、合計0.42秒（性能値ではなく試験実行時間）。

VRAM予約6720 B（静的map、高位表、9pattern、palette16色、OAM全枠）。
使用sprite9/256、最悪9/scanline。毎frame OAM payloadは0..72 B、scroll差分用
レジスタ書込みとCOMMIT/状態pollが加わる。pattern/mapの動的転送は0 B。

## 実機未検証と未実装

| 項目 | 状態 |
|---|---|
| 60fps / 入力応答 / 見た目 | 未検証。COMMIT周期で固定stepを進める実装 |
| 平均/最大/p95処理時間 | 実機未測定。USBログのwork_*で取得可能 |
| SPI/QSPI転送量、BUSY待ち | 実機未測定。wire_*は既存kh_statsのwire byte差分 |
| sprite overflow | 設計上最大9、RTL制限試験PASS。ゲーム実機発生件数は未測定 |
| 音声underrun | 実機未測定、音声fault監視あり。Phase 1はBGM/SFX未実装 |
| 長時間 | PCで1時間相当×2解像度を高速実行、実時間1時間の実機試験は未実施 |
| GPIO/USBキー入力 | 実装済み、実機未検証 |
| 敵/当たり判定/score/lives | Phase 2以降 |
| 60秒stage/中ボス/clear | Phase 3以降 |
| laser/missile/支援機/title/音楽 | Phase 4以降 |

現段階はPhase 1の最小操作系であり、1ステージを遊び切る最終完了条件にはまだ達していない。
実機で初期化失敗/blank_overruns/missed/errorが出た場合、ログを保存して以後のPhaseの前に解決する。
