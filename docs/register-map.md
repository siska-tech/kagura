# レジスタ仕様 / ABI 0.6（1,200タイル）

KAGURA-9のホスト向けレジスタ仕様。この文書を規範とする。ID0/ID1=`'K' '9'`、ABI_MAJOR=0、ABI_MINOR=6。全bitstreamが同じ0.6を返し、機能の有無はCAPSで区別する（[ビルド構成とCAPS](architecture.md#ビルド構成とcaps)）。

offset・名前・access・bit・reset値の機械可読定義は`spec/registers.json`にある。`tools/gen-registers.ps1`がSystemVerilog package（`rtl/core/kagura_abi_pkg.sv`）、Cヘッダ（`software/include/kagura_regs.h`）、ca65 include（`software/w65c02/kagura_regs.inc`）を生成し、`-Check`がこの文書・[音源仕様](audio-spec.md)・[メモリマップ](memory-map.md)の表と定義の一致を検査する。副作用の規範はこの文書の本文である。

## 共通規則

- 窓は32 byte。W65C02Sでは`$9F00–$9F1F`（`KAGURA_IO_BASE`で変更可）、SPI/QSPIではheaderのoffsetで指定する。
- ROへのwrite、WOへのreadはBAD_ACCESS。WOのreadは0を返す。
- 予約bitはread 0、writeは無視。未定義のEXT index・音源indexはread 0、writeはBAD_ACCESS。
- reset値は明示したもの（ID、ABI、CAPS、INC、RASTER_LINE、MASTER_GAIN等）を除き0。
- 読出しの副作用はVRAM_READ_RESULTだけ。STATUS等のstatus読出しは何も変えない。
- 各要求の応答は受付から2 system cycle後。直前の書込みの検査が終わるまで、次の要求は数cycle待たされる（ホストからは見えない。[アーキテクチャ](architecture.md#cpu非依存インターフェース)）。

## 32byte直接窓（CPU base $9F00）

| Off | Name | Access | bit/意味・副作用 |
|---|---|---|---|
| 00 | STATUS | RO | b0 INIT_DONE,b1 CMD_FULL,b2 READ_READY,b3 READ_BUSY,b4 COMMIT_BUSY,b5 VBLANK_LIVE,b6 ERROR_PRESENT,b7 ENGINE_BUSY |
| 01 | IRQ_STATUS | RW1C | b0 VBLANK,b1 RASTER,b2 FENCE_DONE,b3 READ_DONE,b4 COMMIT_DONE,b5 SPR_OVERFLOW,b6 ERROR,b7予約 |
| 02 | IRQ_ENABLE | RW | IRQ_STATUSと同配置、reset0 |
| 03 | DISPLAY_CTRL | RW shadow | b0 DISPLAY_ENABLE,b1 BG_ENABLE,b2 SPR_ENABLE。COMMITで反映 |
| 04 | VRAM_ADDR_L | RW | address[7:0] |
| 05 | VRAM_ADDR_M | RW | address[15:8] |
| 06 | VRAM_ADDR_H | RW | address[23:16]。未実装範囲をaliasしない |
| 07 | VRAM_WRITE | WO | address・dataを捕捉してWRITEをqueueへ投入。成功時だけaddress+=INC |
| 08 | VRAM_READ_REQUEST | WO | 値0だけ有効。addressを捕捉してREADを投入。成功時だけaddress+=INC |
| 09 | VRAM_READ_RESULT | RO | READY時に結果を返しREADYをclear。未READYなら0とNOT_READY |
| 0A | EXT_REG_INDEX | RW | extended register番号。自動増加なし |
| 0B | EXT_REG_DATA | indexed | 選択したextended registerの定義に従う |
| 0C | AUDIO_REG_INDEX | RW | 音源register番号。自動増加なし |
| 0D | AUDIO_REG_DATA | indexed | [音源仕様](audio-spec.md)に従う |
| 0E | COMMAND | WO | opcode。引数を受付時に捕捉し、成功時だけ投入 |
| 0F | FIFO_STATUS | RO | b5:0 queueの空きentry数0..32（組立中のentryも減算）、b6予約、b7 FULL |
| 10 | INC_L | RW | INC[7:0]、reset1 |
| 11 | INC_H | RW | INC[15:8]、reset0。unsigned、0なら同じaddressへ繰り返す |
| 12 | LENGTH_L | RW | FILL/COPYのbyte数[7:0] |
| 13 | LENGTH_H | RW | byte数[15:8]。0はno-op（65536ではない） |
| 14 | FILL_VALUE | RW | FILLで書くbyte値 |
| 15 | FENCE_TAG | RW | 次のFENCEで返す任意の8bit値 |
| 16 | DONE_TAG | RO | 最後に完了したFENCEのtag |
| 17 | ERROR_CODE | RW1C | 下記のsticky error bitmask |
| 18 | ID0 | RO | reset/read 0x4B ('K') |
| 19 | ID1 | RO | 0x39 ('9') |
| 1A | ABI_MAJOR | RO | 0 |
| 1B | ABI_MINOR | RO | 6 |
| 1C | CAPS | RO | b0 HDMI_AUDIO=1,b1 WAVE=1,b2 RDY=0,b3 PSRAM（PSRAM領域・PCM 2ch・COPY）,b4 SPR16=1,b5 WIDE（320×180）,b6 RSCROLL（ラスタスクロール）、b7は0。全体版は0x53、16:9版は0x73、PSRAM版はそれぞれ0x5B、0x7B |
| 1D | FRAME_COUNT_L | RO | VBlankごとに+1する8bit counter（wrap） |
| 1E | SPR_OVERFLOW_INDEX | RO | 最初にline上限を超えたsprite番号0..255。IRQ b5のclearで0 |
| 1F | SPR_OVERFLOW_LINE | RO | 最初に超過した論理Y。IRQ b5のclearで0 |

CAPSは機能を実装したbitstreamだけが立てる。カラーバー試験用のbitstreamはこの窓を持たない。

- STATUS: ENGINE_BUSYはqueueが空でないかcommand実行中。CMD_FULLはqueueが満杯（組立中を含む）。READ_BUSYは受理したREADの完了待ち。COMMIT_BUSYは映像COMMIT専用で、音源の反映待ちはAUDIO_STATUSのAPPLY_BUSYで見る。VBLANK_LIVEは物理走査が垂直ブランキング中であること。ERROR_PRESENTはERROR_CODE≠0。
- IRQ: 外部/IRQは`|(IRQ_STATUS & IRQ_ENABLE)`のlevel出力（open drain）。IRQ_ENABLE=0でも要因は記録する。IRQ_STATUSへ1を書いたbitだけclearし、同じcycleの新しいイベントはclearより優先する。
- SPR_OVERFLOW: IRQ_STATUS.b5が0の間に起きた最初の超過のindexとlineを捕捉し、b5のclearまで保持する。同cycleのclearと新しい超過は新しい超過を優先する。spriteの描画（DISPLAY_ENABLEかつSPR_ENABLE）が有効なlineだけで判定する。
- FENCE_DONE: 複数の完了は1つのIRQにまとまり得る。DONE_TAGは常に最新の完了値。

ERROR_CODE: b0 FIFO_FULL、b1 INVALID_ADDRESS、b2 BAD_ACCESS（不正opcode・値を含む）、b3 READ_COLLISION、b4 NOT_READY、b5 LINE_UNDERRUN、b6 AUDIO_FIFO_ERROR、b7 BUSY_CONFLICT。複数を保持し、W1Cでclear、同cycleの新しいイベントを優先する。新しいerrorが立つとIRQ_STATUS.ERRORもsetする。ERROR_CODEのclearとIRQ.ERRORのclearは独立で、IRQ.ERRORだけを先にclearしても既存の原因で再setはしない。

| bit | 発生条件 |
|---|---|
| FIFO_FULL | queueが満杯のときにVRAM_WRITE・READ_REQUEST・COMMANDを書いた |
| INVALID_ADDRESS | VRAM_WRITE/READの現在addressが公開領域外、FILL/COPYの範囲が単一の公開領域に収まらない |
| BAD_ACCESS | RO/WOの誤用、未定義EXT・音源indexへのwrite、READ_REQUESTへの0以外、未定義opcode、AUDIO_COMMITの不正な設定、COMMITのラスタ表の不正、RS_COUNT/RS_INDEXの範囲外 |
| READ_COLLISION | READ_BUSYまたはREAD_READYのときにREAD_REQUESTを書いた |
| NOT_READY | INIT_DONE前のVRAM_WRITE・READ_REQUEST・COMMAND、READY前のVRAM_READ_RESULT読出し |
| LINE_UNDERRUN | 論理lineの描画が表示開始に間に合わなかった（[映像仕様](video.md#描画期限とunderrun)） |
| AUDIO_FIFO_ERROR | HDMI音声FIFOのoverflowまたはunderflow（[音源仕様](audio-spec.md#hdmiへの受け渡し)） |
| BUSY_CONFLICT | COMMIT_BUSY中のCOMMITやラスタ表の書込み、APPLY_BUSY中のAUDIO_COMMIT |

拒否された操作は何も変えない。address、LENGTH、READY、queue、COMMITのsnapshotはそのまま残り、ERROR_CODE（とIRQ.ERROR）だけがsetされる。STATUS・FIFO_STATUSの読出し、通常registerの設定、error/IRQのclearはqueueが満杯でも行える。

### 起動

電源投入・reset後、STATUS.INIT_DONEは0。VRAMとline bankの消去（約2048 system cycle）が終わると1になる。それまでVRAM_WRITE・READ_REQUEST・COMMANDはNOT_READYで拒否する。ID・STATUSの読出しなど通常のregister操作はできる。PSRAMの初期化はINIT_DONEに含まれない（[PSRAM](psram.md#初期化と一貫性)）。SPI/QSPI版のREADYピンとW65C02S版のRESB解除は、さらに最初のline 0の準備を待つ。

## コマンドと順序

| COMMAND value | 内容 | 受付/完了規約 |
|---|---|---|
| 01 | FILL | 開始address・LENGTH・FILL_VALUEを捕捉し、連続byteを書く（INCは使わない）。直接addressは変えない |
| 02 | FENCE | 先行commandがすべて完了した後にDONE_TAG更新とIRQ.FENCE_DONE。tagは受付時に捕捉 |
| 03 | COMMIT | DISPLAY_CTRLとEXTのshadowを受付時に捕捉。先行書込みの完了後、次のVBlankでOAM・paletteをactiveへcopyし、IRQ.COMMIT_DONE |
| 04 | AUDIO_COMMIT | 全音源のshadowを捕捉。先行waveの書込み完了後、次のsample境界で反映しwave bankを交換。[音源仕様](audio-spec.md#audio_commit) |
| 05 | COPY | CAPS b3版のみ。PSRAMのCOPY_SRCからLENGTH byteをVRAM_ADDRへ複写。直接addressとCOPY_SRCは変えない |
| その他 | 未定義 | BAD_ACCESS、投入しない |

WRITE・READ・FILL・FENCE・COMMIT・AUDIO_COMMIT・COPYはすべて同じqueue（32 entry）に入り、投入順に1件ずつ実行する。後続のREADは先行するWRITE/FILL/COPYの反映後に読む。長いFILLやVBlank待ちのCOMMITを後続の操作が追い越さない。FILL・COPY自身は完了IRQを出さないので、完了を知るにはFENCEを後置する。

- **VRAM_WRITE/READ**: 現在addressだけを検査する。成功後の自動増分は24bit modulo（範囲検査は次の操作時）で、領域境界から次の領域へ自動で移る機能はない。
- **READ**: pendingまたは未消費のREADYがあるとREAD_COLLISIONで拒否し、結果を上書きしない。受付でREAD_BUSY=1、完了でREAD_BUSY=0・READ_READY=1・IRQ.READ_DONE=1。VRAM_READ_RESULTの読出しはREADYだけをclearし、IRQ.READ_DONEはclearしない。
- **FILL**: 投入前に開始〜開始+LENGTH−1が単一の公開領域に収まるかを検査し、外れればINVALID_ADDRESSで部分実行もしない。LENGTH 0は有効な開始addressならno-opとして投入する。PSRAM領域もFILLできる。
- **COMMIT**: 受付時にCOMMIT_BUSY=1。同時に1件だけで、COMMIT_BUSY中の再投入はBUSY_CONFLICT。受付後のDISPLAY_CTRL・EXTのshadow書換えは次回用で、今回のsnapshotを変えない（ラスタ表は例外。下記）。OAM・paletteのshadow書込みはqueueでCOMMITの後ろに並ぶので今回には入らない。COMMITがqueueの先頭に来た後の最初のVBlank開始でcopyを始め、完了でCOMMIT_BUSY=0、active化、後続commandの実行再開。CAPS b6版では、RS_COUNT未満の全entryが「line < LINES かつ厳密昇順」でなければBAD_ACCESSで拒否する。
- **COPY**: 受付時に両範囲を検査する。複写元はPSRAM領域内、複写先はPSRAM以外の単一の公開領域内でなければINVALID_ADDRESS。LENGTH 0は有効な開始addressならno-op。INCは使わず連続byteを複写する。複写先がpattern・mapなど表示中の領域ならVRAM_WRITEと同じく描画中に反映され得る。shadow OAM・palette・waveへの複写の反映はCOMMIT・AUDIO_COMMITの規則に従う。速度は[PSRAM](psram.md#copy)。

## Extended registers

EXT_REG_INDEXで選び、EXT_REG_DATAで読み書きする。readはshadow値を返し、activeの値を読む手段はない。RW shadowはCOMMITで画面へ反映する（COPY_SRCはCOPYの受付時に使う）。

| Index | 内容 | Access/reset |
|---|---|---|
| 00 | SCROLL_X bits7:0 | RW shadow /0 |
| 01 | SCROLL_X bit8をb0、他予約 | RW shadow /0 |
| 02 | SCROLL_Y bits7:0 | RW shadow /0 |
| 03 | BACKDROP（palette index 0..255） | RW shadow /0 |
| 04 | RASTER_LINE 0..LINES−1、LINES..255は無効 | RW shadow /255 |
| 05 | MAX_SPRITES（登録数。0は256） | RO/0（256） |
| 06 | MAX_LINE_SPRITES | RO/16 |
| 07 | PATTERN_COUNT_L | RO/176 |
| 08 | PATTERN_COUNT_H | RO/4（1200 patterns、合計0x04B0） |
| 09 | WAVE_LENGTH_MAX（log2） | RO/8（256 sample） |
| 0A | SCREEN_HEIGHT（論理ライン数LINES） | RO/240、16:9版180 |
| 0B | RS_COUNT（有効entry数0..8。9以上のwriteはBAD_ACCESS） | RW shadow /0 |
| 0C | RS_INDEX（対象entry 0..7。8以上のwriteはBAD_ACCESS。RS_Yのwrite後に自動+1、7の次は0） | RW shadow /0 |
| 0D | RS_LINE（対象entryの論理ライン） | RW shadow /0 |
| 0E | RS_X bits7:0 | RW shadow /0 |
| 0F | RS_X bit8をb0、他予約 | RW shadow /0 |
| 10 | RS_Y | RW shadow /0 |
| 11 | RS_MAX（entry数） | RO/8 |
| 12 | PSRAM_SIZE_LOG2（PSRAM領域のbyte数のlog2） | RO/22 |
| 13 | PCM_CHANNELS（PCM音源数） | RO/2 |
| 14 | COPY_SRC bits7:0（COPYの複写元address） | RW shadow /0 |
| 15 | COPY_SRC bits15:8 | RW shadow /0 |
| 16 | COPY_SRC bits23:16 | RW shadow /0 |
| 17..FF | 未実装 | read0/write BAD_ACCESS |

- 0B..11はCAPS b6版、12..16はCAPS b3版だけが持つ。持たない版では未実装と同じ（read 0、write BAD_ACCESS）。
- SCROLLはX modulo 512、Y modulo 256で背景mapへ掛かる。RASTER_LINEとラスタ表の意味は[映像仕様](video.md)。
- ラスタ表（0B..10）: entryは{line, X(9bit), Y}で、RS_INDEXで選んだentryをRS_LINE/RS_X/RS_Yで書く。RS_COUNTを含む表全体をCOMMIT完了時（VBlank）にactiveへcopyする。copyを守るため、COMMIT_BUSY中のRS_COUNT・RS_LINE・RS_X・RS_Yへのwriteは**BUSY_CONFLICTで拒否**する（RS_INDEXの変更はできる）。他のshadowと違い、COMMIT受付後〜完了前の書換えは今回のcopyに入るためである。
- RS_*と音源registerのwrite後は、内部の検査・反映が終わるまで次の要求を約3 cycle待たせる。write直後のreadは反映後の値を返す。
- debug用bitstream（`KAGURA_PSRAM_DEBUG=1`）だけがEXT 17/18にPSRAM端子の捕捉値を出す。ABIの一部ではない。

## ABIの履歴

ABI 0.xの間は互換性を保証しない。1,200パターン対応を0.6とする。従来と同じ下位10bitのデータ形式は保つが、ABIを厳密に検査する旧ソフトは再ビルドが必要。

| ABI | 変更 |
|---|---|
| 0.1 | 初版。直接窓、EXT 00..09、6ch音源、FILL/FENCE/COMMIT/AUDIO_COMMIT |
| 0.2 | CAPS b5 WIDE、EXT 0A SCREEN_HEIGHT（320×180の16:9版） |
| 0.3 | CAPS b6 RSCROLL、EXT 0B..11（ラスタスクロール表） |
| 0.4 | CAPS b3 PSRAM、EXT 12..16、PSRAM領域、PCM 2ch（音源index 60..9F）、COPY |
| 0.5 | 登録sprite 64→256。OAMを009000から00A000へ移し、flagをrecord byte 6からbyte 3へ移動 |
| 0.6 | 1,200パターン、BG上位bit表、sprite byte 5 bit6をtile bit10に使用、追加pattern窓 |

ソフトはID・ABI_MAJOR/MINOR・CAPSを確認してから使う。手順は[プログラミングガイド](programming-guide.md)。
