# 第2段階：1,200パターン実装

実験ABI 0.6。PicoホストのQSPI／QSPI＋PSRAM構成を主な対象とする。実機書込み・Pico接続での受入は未実施。

## 実装

- 8×8・4bppのパターンを1,200枚常駐させる。RAMは2048×8を19 bankとし、余剰16枚は公開しない。全19 bankをreset後の2048 cycleで並列消去する。
- 0～1023のアドレスは従来どおり。1024～1199は `0xB000+(tile-1024)*32`、最後のbyteは0xC5FF。0xC600以降へのホストアクセスは拒否する。
- BGは従来の16bit mapに、0x9000～0x90FFのbit10表を追加する。表は最終pattern bankの空きbyte 1536～1791へ格納し、mapとpatternを別cycleに読む既存の手順でポートを共有する。entry iのbitはbyte i//8のbit i%8。map下位wordと同じread cycleで取り込み、palette 16色・左右／上下反転と既存の描画cycleを維持する。
- spriteはbyte 5 bit6をtile bit10とする。palette bits5:2を維持し、16×16の4枚整列を11bitへ拡張する。
- 1200～2047の番号はBG／spriteとも画素0として描画する。旧番号への折返しや未実装bankの値は表示しない。
- 公開領域の識別を4bitに広げ、旧pattern、map、BG上位表、追加patternを別のregionにする。FILL/COPYは領域境界や穴を跨げない。
- command queueは分散RAM 32×64でdescriptorをまとめてstore／fetchする。容量32・4cycle staging・FIFO_STATUSの数え方は維持し、16bitへの分割muxとheadの組立回路を取り除く。
- MicroPythonの `Video.tile/tiles/map_entry/map_words/sprite` と公開領域検査を対応。`tiles` は1023／1024境界で転送を分割し、`map_words` は同じbyte内の他entryの上位bitを保持する。複合転送中はdevice.busyを保持する。

データ形式と更新手順は[メモリマップ](memory-map.md)、SDK例は[プログラミングガイド](programming-guide.md)を参照。別表とmapの更新は原子的ではないため、表示停止または安全なblanking期間が必要。既存raw mapを使う場合は上位表を0へ戻す。

## 検証

```bash
bash tools/test-tile1200-stage2.sh
python3 -I software/micropython/tests/test_driver.py
python3 -I software/micropython/tests/test_fifo_xfer.py
python3 -I software/micropython/tests/test_kagura_ja.py
python3 -I software/micropython/tests/test_shooter.py
```

```powershell
./tools/run-baseline.ps1 -Configs qspi,qspipsram,qspi720,qspipsram720
./tools/check-design.ps1
./tools/gen-registers.ps1 -Check
```

RTLの対象は15試験：queue、ABI、VRAM初期化・転送、PSRAM／COPY／PCM、CPU起動、SPI／QSPI／W65C02バス、既存BG／sprite（480p・720p）、追加タイルを使うBG／sprite（480p・720p）。追加タイルの試験は全画素比較を行い、1023/1024、1087/1088、1151/1152、1199、無効番号1200/2047、16×16最終グループ、palette／flip、clipping、system単独resetを含む。

既定のP&R設定はplace option 1。qspi／qspipsram／qspipsram720はroute option 2、qspi720はroute option 1を使う。クロック・SDCと開発下限0.10nsは変更していない。環境変数の上書きなしで再現する。

15件のRTL試験すべて合格。VRAMは8541件のモデル読出し照合、初期化は92672件のゼロ読出し、queueは256個のランダム64bit descriptorと8回のwrapを確認した。SPI／QSPI／W65C02のバスモデル、COPY／PCM併用、既存・拡張BG／spriteの全画素比較、system単独resetも合格。

SDKは114件を実行し、112件合格・外部依存の2件skip。生成Cヘッダのcompile検査は合格、ca65は未導入のためskip。ABI生成物・文書・設計算術とdiffの整合性も合格。

4構成すべてsetup/hold違反0、TNS=0、負のrecovery/removal解析なし。最悪setupは開発下限の+0.10ns以上。下表は現在のRTL・build scriptとhash一致を確認した最終結果。

| 構成 | Logic | Register | CLS /4320 | BSRAM /26 | 最悪setup ns | 最悪hold ns |
|---|---:|---:|---:|---:|---:|---:|
| qspi | 5345 | 4197 | 3826 | 26 | 0.507 | 0.552 |
| qspipsram | 7044 | 5156 | 4116 | 26 | 0.106 | 0.552 |
| qspi720 | 5369 | 4198 | 3843 | 26 | 0.955 | 0.555 |
| qspipsram720 | 7038 | 5157 | 4146 | 26 | 1.477 | 0.552 |

機械可読の結果とsource hashは[第2段階の結果](tile-1200-stage2-results.json)。生ログは `build/tile1200-stage2/`、`build/baseline/`、`build/tile1200-sdk-*.log`、詳細manifestは `reports/7a2f872-dirty-*/` に保存する（Git管理外）。

これはsimulationとP&R/STAによる検証であり、実機・実Picoによる1,200枚の受入を示すものではない。BSRAMは26個すべてを使用する。

## deprecated構成と残作業

FPGA standaloneの `demo`／`demo720` はdeprecated。ソース・旧試験・過去の証跡は保持するが、既定のP&R対象から外し、この実験の受入条件には含めない。Picoホスト上のデモと診断を使う。HDMI／DVIの信号確認構成はこの非推奨化の対象ではない。

残る受入は実機での追加領域読戻し、BG／sprite表示、PCM併用・長時間動作。terminal／`kagura_ja` の文字キャッシュ上限は従来の1,024枚内で、1,200枚へのキャッシュ拡張は別段階。旧ABI 0.5用ホストは0.6の定義で再ビルドする。

第3段階で上記の数値検証と文字キャッシュ拡張を実施した。結果と残る目視・聴感は[第3段階](tile-1200-stage3.md)を参照。この文書の数値は第2段階時点の記録として保持する。
