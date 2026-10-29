# メモリマップ

ホストから見えるVRAM・PSRAMのaddressと、データ形式、BSRAMへの物理配置。

## 公開address

addressは24bit。下表の範囲だけを実装し、上位bitを無視したaliasはしない。表にない範囲へのアクセスはINVALID_ADDRESS（読出し結果は0）。多byte値はlittle endian。

| VRAM address | 用途 | CPUアクセス |
|---|---|---|
| 000000–007FFF | pattern、1024個×32 byte | RW。描画と時分割 |
| 008000–008FFF | 背景map下位word、64×32 entry×2 byte | RW。描画と時分割 |
| 009000–0090FF | 背景mapのtile bit10、8 entry/byte | RW。描画と時分割 |
| 009400–0095FF | shadow palette、256色×2 byte | RW。COMMITでactiveへ |
| 009600–0097FF | active palette | 非公開（アクセスエラー） |
| 009800–0099FF | shadow wave、ch4/ch5×256 byte | RW。AUDIO_COMMITでbank交換 |
| 009A00–009BFF | active wave | 非公開（アクセスエラー） |
| 00A000–00A7FF | shadow OAM、256 sprite×8 byte | RW。COMMITでactiveへ |
| 00A800–00AFFF | active OAM | 非公開（アクセスエラー） |
| 00B000–00C5FF | 追加pattern、番号1024～1199（176個×32 byte） | RW。描画と時分割 |
| 400000–7FFFFF | PSRAM（4MiB）。CAPS b3版のみ | RW。queue経由。電源投入時の内容は不定で、起動時に消去しない |

009100–0093FFは未実装。009000–0090FFは実験ABI 0.6のmap上位bit表として使用する（ABI 0.4までのOAMとは異なる）。active領域はhostから読めず、COMMIT・AUDIO_COMMITでだけ変わる。

## 画素と背景

- **pattern**: 8×8画素、4bpp、32 byte。行優先で1行4 byte、1 byteの上位nibble（bits7:4）が左の画素。pattern tは、t<1024ならaddress `t*32`、1024≤t<1200なら `0xB000+(t-1024)*32` から。内部描画アドレスはt*32。1200～2047は透明画素0で描画し、公開patternアドレスは持たない。
- **背景map**: 64×32 entry（512×256画素）。entry (col,row)はaddress `0x8000 + (row*64+col)*2`の16bit word。

| map bit | 内容 |
|---|---|
| 9:0 | pattern番号の下位10bit |
| 13:10 | palette番号（0..15） |
| 14 | 左右反転 |
| 15 | 上下反転 |

map entry iのtile bit10はaddress `0x9000+i//8` のbit `i%8`。下位wordと上位bit表は別々に更新するため、表示停止中または安全なblanking期間に書く。resetで表は0となる。旧mapデータをロードする場合は対応する上位bitも0へ戻す。FILL/COPYは旧pattern・map・上位bit表・追加patternそれぞれの領域内だけを許可し、領域境界や穴を跨がない。

- **palette**: 256色、各16bit word。bits11:8 R、7:4 G、3:0 B（RGB444）。color index = palette番号×16 + 画素値。上位byteのbits7:4は書込み無視・読出し0。出力時は各4bitを2回並べてRGB888にする（例: 0xF→0xFF）。

## sprite 8byteレコード

sprite nのshadowはaddress `0xA000 + n*8`。

| byte | 内容 |
|---|---|
| 0 | X bits7:0 |
| 1 | X bits9:8をbits1:0、残り予約0 |
| 2 | Y bits7:0 |
| 3 | Y bits9:8をbits1:0、bit2 enable、3 size16、4 Hflip、5 Vflip、6 behind、bit7予約0 |
| 4 | pattern番号 bits7:0 |
| 5 | pattern番号 bits9:8をbits1:0、paletteをbits5:2、pattern bit10をbit6、bit7予約0 |
| 6 | 予約0 |
| 7 | 予約0 |

- X・Yは符号付き10bit（−512..511）。画面外の部分はclipする。
- size16=0は8×8、1は16×16。16×16はpattern番号の下位2bitを無視した`base=tile&0x7FC`から連続する4 patternを、左上base、右上base+1、左下base+2、右下base+3に並べる。反転は16×16全体に掛かる。
- 予約bitへの書込みは無視、読出しは0。disabledのspriteも内容を保持する。
- 1ラインの選択に使うY・enable・size16をbyte 2–3（word 1）に集め、選択回路が1 sprite 1 wordで判定できるようにしている。
- 表示規則（優先順位、behind、16個/line）は[映像仕様](video.md#sprite)。

## wave

009800–0098FFがch4、009900–0099FFがch5のshadow。各byteがsigned 8bitのsample。LEN_LOG2で使う長さを選び、短い長さでは先頭だけを使う（[音源仕様](audio-spec.md)）。

## PSRAM

CAPS b3版のPSRAM領域は、GW1NR-9内蔵PSRAM（2 die）のdie 0の4MiB。VRAMと同じVRAM_WRITE・VRAM_READ_REQUEST・FILLの対象で、addressとINCの規則、範囲検査、queueでの順序保証も同じ。PCMの再生元とCOPYの複写元になる。詳細は[PSRAM](psram.md)。

## 物理配置（BSRAM）

Tang Nano 9KのGW1NR-9は18Kbit BSRAMを26個持つ。8/16/32bit幅で1個2048 byte相当として数える。同じ行にあるshadowとactiveは1個の配列へまとめて置く。

| 用途 | 構成/個 | 個数 | 利用payload | 8/16/32bit構成の未使用容量 | ポート |
|---|---|---:|---:|---:|---|
| Pattern＋map上位bit表 | 2048×8 | 19 | 38656 B | 256 B | SP。最終bankの空き256 Bを上位bit表に使用 |
| Map | 2048×8 | 2 | 4096 B | 0 B | SP。下位/上位byte laneを独立に書く |
| OAM shadow＋active | 1024×16 | 2 | 4096 B | 0 B | SP。2048 word（shadow 0..1023、active 1024..2047） |
| Palette shadow＋active | 1024×16 | 1 | 1024 B | 1024 B | SP |
| Wave shadow＋active | 2048×8 | 1 | 1024 B | 1024 B | SP。音源の読出しを優先 |
| Line bank ×2（統合） | 1024×16 | 1 | 1280 B | 768 B | TDP。512 wordずつ2面、system書込み／pixel読出し |
| Command queue | 32×64分散RAM | 0 | 256 B（BSRAM集計外） | — | 32 entry×64bit。同期read |
| Audio FIFO | 分散RAM | 0 | 64 B（BSRAM集計外） | — | SDP。16 stereo sample |

実験第2段階の設計モデルは計26ブロック、BSRAM利用50176 B、モード上の未使用3072 B（`spec/design-budget.json`と`tools/check-design.ps1`）。別途command queue 256 B・audio FIFO 64 Bを分散RAMに置く。map上位bit表はpattern bank 18のbyte 1536～1791へ同居させ、BGのmap読出しcycleを共有する。pattern読出しとは同時に行わない。audio FIFOの配置は合成結果で確認する。PCM先読みbufferもFF/分散RAMを使う。実測値と対象構成は[実験記録](tile-1200-experiment.md)を参照。

- line wordは`bits11:0 RGB444、bit12 BG_SOLID、bit13 SPR_CLAIMED、15:14予約`。pixel側はRGBだけを読み、2bitはsprite合成の優先判定に使う。
- OAM・paletteへのbyte書込みは16bit wordの不可分なread-modify-write（最大3 cycle）で、描画の読出しを途中に挟まない。mapは2本のbyte laneで、RMWを使わない。
- command descriptorは`opcode8 | address24 | length16 | data8 | flags8`の64bit。queueはstagingの4 cycle後に1 descriptorをまとめて書き、write pointerを進める。読出しも64bit単位で、未公開のstagingは実行しない。

## 起動時の初期化

巨大なRAMに非同期resetは使わず、resetの解除後にsystem domainのFSMが通常のwrite portで全RAMを並列に0へ書く（2048 cycle）。pattern全19 bank、mapの両laneと上位bit表、OAMの全2048 word、paletteの全word、waveの全域が対象。queueとFIFOはpointerのresetで空にする。

line bankは、pixel側の読出しが止まったことをsystem側で確認してから統合RAMの全1024 wordを順に0にする。systemだけがresetされた場合も走査と衝突しない。消去が終わるまでpixel側は黒を出す。

結果として、paletteは全色黒、OAMは全sprite disable、mapとpatternは0、音源は全ch無効で起動する。STATUS.INIT_DONE=1まではVRAM操作をNOT_READYで拒否する（[レジスタ仕様](register-map.md#起動)）。
