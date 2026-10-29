# KAGURA-9：1,200パターンへの拡張検討

調査日：2026-10-29。対象：作業ツリー HEAD `e909cac`。RTL・仕様・既存の合成結果の静的調査であり、拡張版の合成・simulation・実機検証は未実施。

## 結論

8×8・4bppのパターンを1,200枚常駐させ、BGとspriteから参照する拡張は設計上可能と考える。ただし定数変更だけでは実現できない。BSRAMの再配置、11bitのタイル番号、追加パターンの公開アドレス、ソフトウェア対応が必要。実装可否の確定には合成とP&R/STAが必要。

まずホスト構成で「line bank統合＋command queueの分散RAM化」を試作する案を推奨する。demoはさらにart ROM等の対策が必要。同一仕様で全構成に展開できるかは別途確認する。

## 現状の制約

| 項目 | 現状 | 1,200枚に必要な変更 |
|---|---|---|
| パターン容量 | 1,024×32＝32,768 B | 38,400 B。追加5,632 B（5.5 KiB） |
| パターンRAM | 2048×8を16 bank | 同じ方式なら19 bank、物理上は1,216枚分 |
| 描画アドレス | 15bit | 16bit、bank番号も4→5bit |
| BG map | 16bitすべて使用済み | タイル番号の追加1bitが必要 |
| sprite | タイル番号10bit | 予約bitを用いた11bit化が可能 |
| 公開アドレス | pattern直後の0x8000にmap | 単純な連続延長はmap等と衝突 |

根拠：[メモリ配置](memory-map.md)、[VRAM RTL](../rtl/vdp/kagura_vram.sv)、[BG RTL](../rtl/vdp/kagura_bg_renderer.sv)、[sprite RTL](../rtl/vdp/kagura_sprite_row.sv)。

[既存P&R結果](validation-status.md#資源とタイミング)ではホスト・CPU構成がBSRAM 25/26、demoが26/26。単純に3 bank追加すると28/26、29/26となり収まらない。設計モデルの未使用8,640 Bは複数の用途・ポートに分散しており、そのままパターン領域として利用できる空きではない。

## RAM確保案

### 第一候補：line bank統合とqueue移設

- 実際にVDPが使う `kagura_line_display` のline bankは512×16を2個使うが、各配列は1個ずつBSRAMを消費し、有効画素は各320 word。旧 `kagura_line_banks` は1024×16を2個使う。1個の1024×16 TDPを前半512 wordと後半512 wordに分け、アドレスを `{bank, pixel_index[8:0]}` とすれば2本を格納できる。system用portとpixel用port、既存の所有権handshakeを維持し、1個削減する。初期化とsystem単独resetも修正対象。
- command queueは実データが32×64bit＝256 Bで、現在は1024×16 SPを1個占有する。128×16の分散RAM等へ移せれば1個削減できる。単にDEPTHを減らすだけでBSRAMが解放されるとは限らず、合成結果の確認が必要。FF実装ではデータだけで2,048 FFを要するため、資源の厳しいPSRAM構成では安易に選ばない。
- ホスト構成の概算は `25 - 1 - 1 + 3 = 26`。後述のBG上位bit表もBSRAMを増やさない実装が条件。
- demoは同じ対策でも27個。art ROMの分散ROM化・生成方式変更、または別のRAM統合を追加検討する。

対象：[実際のline bank](../rtl/vdp/kagura_line_display.sv)、[TDP wrapper](../rtl/memory/kagura_ram_tdp.sv)、[queue](../rtl/core/kagura_command_queue.sv)。

### 他の候補

| 案 | 評価 |
|---|---|
| paletteとwaveの統合 | payloadは各1 KiBで合計2 KiB。容量上は1個に収まるが、音源読出しと描画・COMMITの同時アクセスを支えるポート設計が必要。単純なSP統合では不可 |
| 他RAMの空き領域へ追加patternを分散 | 容量は活用できるが、port競合・bank decode・返却タイミングが複雑化。第一候補より影響が広い |
| PSRAMに1,200枚保管し既存VRAMへCOPY | PSRAM構成では現在の機能で可能。ただし直接参照できる常駐パターンは1,024枚のまま。場面ごとの差替えで足りる用途向け |
| PSRAMから描画器が直接読む | 先読み/cacheとPCM・host間の仲裁変更が必要。現在の1cycle読出しを前提とする描画器には接続できず、今回の176枚追加には大きな変更 |

## 互換性を優先したABI案（未採用）

既存のmap・palette・wave・OAMアドレスとBGの16色palette・両方向反転を維持する。

1. pattern 0～1023は0x000000～0x007FFFを維持。1024～1199を0x00B000～0x00C5FFに割り当てる案とする。追加領域内のアドレスは `0xB000 + (tile-1024)*32`。描画器の内部アドレスは引き続き `tile*32` とし、hostの公開アドレスから変換する。物理上の余剰16枚は非公開にする。
2. BGは2,048 entryに対する1bit表（256 B）を追加する。例えば0x009000～0x0090FFに8 entry/byteの表を置き、mapと同時に読む。通常のmapには従来の下位10bitを保持する。小容量の分散RAM候補だが、byte書込みと1bit読出し、同期readの実装・資源を確認する。旧map領域を32bit化する方法はRAMと互換性の負担が大きい。
3. spriteはbyte 5 bit 6をタイル番号bit 10へ割り当て、palette bits5:2は維持する。現在このbitは書込み時に0へマスクされるため、VRAMのマスクも変更する。16×16は11bitの番号を4枚境界に整列し、最終グループ1196～1199を扱えるようにする。
4. PATTERN_COUNTは0x04B0（L=0xB0、H=0x04）に変更。ABIバージョン／機能識別を更新する。範囲外番号1200～2047の描画結果を明示し、例えば透明として扱う。未実装bank参照や下位bitへの折返しを避ける。

旧ソフトは追加bitが0なら従来どおり動作する。ただし拡張ソフトの実行後に旧ソフトへ切り替える場合、BG上位bit表のクリアが必要。map下位wordと別表の更新は原子的でないため、表示停止またはVBlank中の更新等を契約に含める。

追加領域は独立した公開領域として範囲検査する。現在のFILL/COPY検査は開始・終了のregion一致を使うため、離れた旧pattern領域と追加領域に同じregion番号を割り当てるだけでは、中間のmap等を跨ぐ操作を許す恐れがある。SDK側も1023→1024の境界で転送を分割する。

## 変更範囲と確認手順

- RTL：VRAMの19 bank化・返却mux・初期化、BGとspriteの11bit化、core/VDP内の配線、OAMマスク、公開領域decodeとFILL/COPY範囲検査、line bank統合、queue実装。
- 仕様・生成物：`spec/registers.json`、生成ABI/C/assembler/Python定義、`spec/design-budget.json`、メモリマップ・映像仕様。生成物は生成元から更新する。
- ソフト：MicroPython `kagura/video.py`の上限とアドレス変換、map上位bit更新、sprite pack、`kagura_ja`とterminalのキャッシュ上限、Pico等の直接アドレス計算、素材生成・ロード経路。
- 第1段階：line統合とqueue移設だけで既存動作を回帰検証し、qspi/qspipsramの480p/720pでBSRAM削減、Logic/FF使用量、STAを確認する。
- 第2段階：追加領域のread/write/FILL/COPY、reset後の全ゼロ、1023/1024/1199/1200境界、旧領域の非破壊、範囲外拒否を検証する。
- 第3段階：BG上位bitと全palette・flip、8×8/16×16 sprite、スクロール、旧データ互換、全画素比較を検証する。BSRAM読出しlatencyを維持できればタイル数増加自体で1ライン当たりの読出し回数は増えないが、mux拡大のSTAと追加表のcycle影響は確認が必要。
- 最終段階：対象全構成のP&R/STA、実機VRAM照合、映像確認、PCM併用の長時間動作。既存demo720のsetup余裕は小さいため、資源数だけで成立と判定しない。

調査時点ではRTL・公開仕様の変更は行っていない。その後の実装・検証結果は[1,200タイル対応の記録](tile-1200-experiment.md)を参照。
