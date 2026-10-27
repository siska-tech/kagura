# boot構成のStandard STA監査（2026-10-27）

対象は `phase2boot` / `phase2boot720`。RTLは `ee4a0ca`（mainへのmergeは
`475fca7`）と同じ。Education V1.9.11.03とStandard V1.9.12.04を比較した。
本書は監査とそれに基づく制約修正の記録。末尾に実装後の全経路STAとテスト結果を示す。
公開Releaseへのboot bitstream追加は、外部タイミングと実機確認後とする。

## 原因の切り分け

両版のFPGA入力ファイルのmanifestハッシュに差はなく、生成SDCも一致した。
480pのSDC SHA-256は `1f7c49cce62df95ba2ac67240816f6be8154b29e32bad82ad49e0aa5618b3a6b`、
720pは `e55d6be1638eee4e0b6280b180fbfe3642d58b5d991043642a5a47aa861911fb`。
デバイスは同じGW1NR-LV9QN88PC6/I5。各構成内のplace/route指定も同じ。

MISOに限定したsetup/holdレポートを追加して再ビルドした結果、Educationも
入力経路を解析していた。入力制約の欠落やmin/maxの取り違えではない。

`flash_miso_ibuf/I` → `boot/reader/data_0_s0/D` のhold内訳は両解像度で同じ：

| 項目（ns） | Education 1.9.11.03 | Standard 1.9.12.04 |
|---|---:|---:|
| 入力min (`tIn`) | 0.000 | 0.000 |
| 入力バッファ (`tINS`) | 1.392 | 1.392 |
| データ配線 | 0.000 | 0.000 |
| PLL出力 (`tCL`) | 0.000 | 3.155 |
| 受信クロック配線 (`tNET`) | 0.185 | 1.763 |
| 受信クロック遅延合計 | 0.185 | 4.918 |
| hold関係 | 0.000 | 0.000 |
| hold slack | **+1.207** | **−3.526** |

データ側は同じIOR11[A]内の入力レジスタまでの経路。クロック側の計算値の差が
合否の差を直接説明する。表示値の丸めにより差分計算に0.001 ns程度の誤差がある。
Standardのもう1件は `boot/reader/rx_shift_0_s0/D`、hold −1.816 ns。
setup違反は0、hold違反はこの2件のみ（各構成）。

Standardではクロック遅延の増加がMISO setup側には有利に働く。
480pのMISO最小setupはEducation +13.299 ns、Standard +20.761 ns。
通常の同一クロック内の経路では共通クロック遅延が相殺されやすいが、
外部入力min=0の経路にはその相殺がない。

**確定したのはSTA上のクロック経路計算差まで。** エディションとバージョンが
同時に違うため、Education固有の仕様差・モデル更新・解析アルゴリズム・配線差の
どこまでが寄与するかを、この比較だけで断定しない。Standardが誤りだとする根拠もない。
同一版数での比較、またはこの2経路を添えたGowinへの照会でさらに切り分けられる。

## 制約と実際の通信の差

`kagura_flash_reader.sv` は `CLK_DIV=4`。SCLKの半周期はsystem54の4周期で、
MISOはRECEIVE状態かつSCLKをLow→Highへ更新するposedgeでのみ取り込む。
`rx_shift[0]` と最後のビットを格納する `data[0]` が対象となる。

```text
system54周期       0        4        8       12
SCLK               ↓        ↑        ↓        ↑
Flash              bit A更新         bit B更新
受信                        A取込み           B取込み
```

したがって通常の連続転送では、データ更新→取込みが4周期、取込み→次回更新も4周期。
最後のビット後もHOLD状態で4周期のHighを完了する。バイト間backpressureはLowを
延長する。次のRECEIVEへの復帰時もdivider=0から4周期を数えるため、setup窓を短縮しない。

修正前の `setup -end 4` / `hold -end 3` はsetupを4周期にする一方、hold関係を0に戻す。
これは同一エッジで新データが変化し得るモデルであり、このSPI受信の保持窓を表していない。

Gowinの [SUG940 §5.4.3](https://cdn.gowinsemi.com.cn/SUG940E.pdf) は、
holdの `-end` が取込みエッジを左へ移動すると定義している。
同周期の参照クロックに対する関係は `(setup − 1 − hold) × T`。
よってsetup=4を維持し、hold=7にすれば関係は−4Tとなり、上記の次回更新までの窓に対応する。
これは外付けFlashの `tHO` を74 nsに変更する操作ではなく、異なる更新・取込みエッジを選ぶ操作。

## 対策案と採用条件

第一候補は上記のプロトコルに基づくhold制約の修正。`boot.sdc` と同条件の
`boot-probe.sdc` を揃え、setup=4、input max=55/min=0はまず維持する。
MISOを毎周期読む別のFFが追加された場合に、この例外が誤適用されないよう、
対象エンドポイント数と名前を検査する。将来CLK_DIVを変える場合も固定値を流用しない。

採用時には次を確認する：

1. JEDEC/READの全ビット、最後のビット、backpressure、リセットを対象に、
   MISO取込み前後の4周期と受信イネーブルの条件を恒久テストで検証する。
2. 両版・両解像度で全経路のsetup/hold/recovery/removalとTNS、開発下限を再確認する。
   MISO限定レポートだけを全経路の最小slackとして扱わない。
3. Flashの正確な品番・AC仕様、SCLK出力遅延と基板往復遅延を確認する。
   現行max=55 nsは暫定値であり、今回の制約案でもこれ自体は実測保証に変わらない。
4. Standard bitstreamでJEDEC、CRC検査、boot、待ち合わせ、冷間起動を実機確認してから
   boot構成をReleaseに追加する。Educationの桜吹雪試験はこの検証を代替しない。

代替案はSCLK出力を基準にした外部タイミングモデルの再構成。ただしSCLKはバイト間で停止し、
再開位相も可変なので、単純な固定divide-by-8だけでモデル化すると実装を表現できない。
転送イネーブルを含めた解析が必要になる。入力遅延セルや受信段追加は、正しい制約でも
物理違反が残る場合の次案とし、サンプリング位相・setup余裕への影響を再評価する。

min値を根拠なく+4 ns以上へ増加すること、MISOのfalse-path化、Education合格だけで
Standardを合格扱いにすることは対策として採用しない。

## 監査成果物

Standardの隔離ビルドでhold=7案を試した結果：

| 構成 | MISO最小setup | MISO最小hold | 全体setup違反数 | 全体hold違反数 |
|---|---:|---:|---:|---:|
| phase2boot | +20.761 ns | +70.548 ns | 0 | 0 |
| phase2boot720 | +21.297 ns | +70.548 ns | 0 | 0 |

hold関係は両構成で−74.074 ns（−4周期）となった。480pはMISO setupもデータ・
クロック経路遅延も現行Standardビルドと一致し、holdだけが意図した4周期分改善した。
表のslackはMISOに限定した値であり、デザイン全体の最小slackではない。
これで制約案の効果は確認できたが、上記採用条件の恒久テスト・全経路の余裕確認・
外部タイミング検証・boot実機試験は残る。

`build/boot-sta-audit/` に再実行可能な監査用Tcl、抽出スクリプト、両版レポート、
`results.json`、試験ログを保存。製品用スクリプトのコピーで追加したのは
MISO限定report_timingのみ。候補ビルドでは生成SDCのMISO holdだけ3→7へ変更した。
レポート・制約・スクリプト・試験ログの保存コピーは
`reports/ee4a0ca-boot-sta-audit/`（各ファイルのSHA-256付き）。

監査用シミュレーションは既存 `tb_flash_reader` をCLK_DIV=4とし、
JEDEC 3バイト＋READ 4バイトの計56回の取込みと56回の後続更新について、
前後4周期以上であることを確認してPASSした。これは当該シナリオの検証であり、
全状態・全タイミングの形式証明ではない。

## 実装後の検証

`boot.sdc` と `boot-probe.sdc` のholdを7に修正し、適用先を
`boot/reader/data_0_s0` と `boot/reader/rx_shift_0_s0` に限定した。
magicprobeはcontrollerを介さないため、build scriptで階層を `reader/` へ置換する。
3種類のボードtopはそれぞれ分周4を明示し、`check-design.ps1`でもタイミングテストと
分周値が一致することを確認する。

`report_exceptions` でMISOだけのsetup/hold経路を追加出力し、通常の
全経路 `report_timing` は維持した。`check-nano9k-timing.ps1` から呼ぶ
`check-boot-miso-timing.ps1` は、対象がちょうど2個、送受信clockがsystem54の立上り、
関係が+4T/−4T、slackが非負であることを検査する。対象名の変更、report欠落、
誤ったhold関係を注入したレポートはいずれも拒否した。

製品用build scriptでの再測定（ns）：

| ツール | 構成 | 全体最小setup | 全体最小hold | MISO最小hold |
|---|---|---:|---:|---:|
| Education 1.9.11.03 | phase2boot | +2.087 | +0.562 | +75.281 |
| Education 1.9.11.03 | phase2boot720 | +1.929 | +0.558 | +75.281 |
| Standard 1.9.12.04 | phase2boot | +0.848 | +0.527 | +70.548 |
| Standard 1.9.12.04 | phase2boot720 | +0.834 | +0.530 | +70.548 |
| Education 1.9.11.03 | bootprobe | +2.199 | +0.561 | +75.281 |
| Standard 1.9.12.04 | bootprobe | +2.416 | +0.708 | +70.548 |
| Education 1.9.11.03 | magicprobe | +12.820 | +0.708 | +75.281 |
| Standard 1.9.12.04 | magicprobe | +9.633 | +0.708 | +70.548 |

8ビルドともsetup/hold違反0、TNS=0、setup/holdの開発下限+0.10nsを満たした。
recovery/removalに負slackなし（probe系は該当する解析経路なし）。
`phase2boot`/`phase2boot720`のrecovery/removalはEducationが
+16.518/+0.823、+5.851/+0.558、Standardが+16.323/+0.545、+10.275/+0.846 ns。

恒久テスト `tb_flash_reader_timing` は、SCLKエッジで動く独立Flashモデルを用い、
応答0nsと55nsの両方でJEDEC/READの受信値と前後4周期を確認する。
byteごとの異なる停止時間、Low/High/byte待機中のresetとJEDEC再読出し、長さ0も検査する。
元のCLK_DIV=2の機能試験も残し、ボードの分周4に固定した制約検証と併用する。
Verilator 5.032の全58試験が合格した。さらに隔離したRTLで最終ビット後のHighを
1周期へ短縮すると、このテストがhold窓不足として拒否することを確認した。

証跡は `reports/ee4a0ca-boot-miso-fix/`。外部Flashの暫定max=55nsの実測確認、
および今回のStandard bitstreamでの実機boot・冷間起動試験は未実施。

## Standard版によるFlash読出しの実機確認

2026-10-27 12:09–12:10 JST、B1（GW1NR-9C、ID `0x1100481B`）で実施。
bootprobeの一時コピーに、controllerを1秒ごとにresetしてimageを再検査する回路と、
既存の115200 8N1 UART reporterを追加した。UARTは既存診断と同じpin 17 / COM8。
`kagura_flash_reader`・image検査・controller本体、CLK_DIV=4、MISO制約は製品と同じ。
この計測用イメージはStandard V1.9.12.04で別途合成し、setup +3.994ns、hold +0.708ns、
違反0、MISO経路の対象とエッジ関係の検査にも合格した。

SRAM Program and Verify後、起動中のUART断片を除いて16回の新しい検査を連続取得した。
成功counterは2→17で毎回1増加し、JEDEC IDは全回 `0x856016`、image検査失敗counter=0、
error_code=0、boot_ready=1。既存imageのheader/payload CRC検査が毎回完了している。
外部Flashおよび内蔵Flashへの書込みは行っていない。

終了後、60分ストレス試験で使用したEducation版qspipsram720をSRAMへ復元してVerify成功。
PicoからQSPI 5MHzでID `4b39`、ABI 0.5、CAPS `0x7b`、ERROR_CODE=0も確認した。

計測用bitstreamのSHA-256は
`09b9e7b973888cf2c7d45037e5beb49c02064587584eb776870bf8c27d5d1baf`。
証跡・計測用ソース・build scriptは `reports/ee4a0ca-boot-miso-hardware/` に保存。
初回の診断は一時コピー内のreset信号の宣言順による未駆動警告があり、再試行counterが
進まなかったため無効とした。宣言位置を修正し、未駆動警告が消えた版だけを上記合格とする。

これは計測用probeでの読出し・CRC検査であり、製品用phase2boot/720そのものの実機検証、
外部W65C02S＋SRAM＋decodeでの起動、電源再投入、SCLK/MISOのアナログ測定は含まない。

メーカーの [P25Q32U datasheet V1.4 §5.3](https://www.puyasemi.com/download_path/%E6%95%B0%E6%8D%AE%E6%89%8B%E5%86%8C/Flash%20%E8%8A%AF%E7%89%87/P25Q32U_Datasheet_V1.4.pdf)
では、2.3–3.6V、30pF負荷のtCLQVは最大7ns、tCLQXは最小0ns、通常READのSCLK上限は55MHz。
6.75MHzという設定とmin=0の根拠には整合するが、FPGAのSCLK出力遅延と基板往復遅延・
実際の負荷を含めたmax=55nsの予算は、別途波形測定で確認する必要がある。
メーカーPDFの直接取得はタイムアウトし、これらの表値はメーカーPDFの検索インデックスで確認した。
