# Register Specification / ABI 0.2

【設計】この文書をv0.1実装の規範とする。ABI_MAJOR=0、ABI_MINOR=2（0.2で16:9モード用のCAPS b5とEXT 0Aを追加。下記「ABI 0.2」）。予約bitsはread 0/write ignored、未定義register read 0/write error。ROへのwrite、WOへのreadはBAD_ACCESS。全register reset=0（明示したID/CAPS/INC/MASTER_GAIN以外）。読出し副作用はREAD_RESULTのみ。通常registerの応答は最大2system cycles。status読出しは破壊的でない。

## 32byte直接窓（CPU base $9F00）

| Off | Name | Access | bit/意味・副作用 |
|---|---|---|---|
| 00 | STATUS | RO | b0 INIT_DONE,b1 CMD_FULL,b2 READ_READY,b3 READ_BUSY,b4 COMMIT_BUSY,b5 VBLANK_LIVE,b6 ERROR_PRESENT,b7 ENGINE_BUSY |
| 01 | IRQ_STATUS | RW1C | b0 VBLANK,b1 RASTER,b2 FENCE_DONE,b3 READ_DONE,b4 COMMIT_DONE,b5 SPR_OVERFLOW,b6 ERROR,b7予約 |
| 02 | IRQ_ENABLE | RW | IRQ_STATUSと同配置、reset0 |
| 03 | DISPLAY_CTRL | RW shadow | b0 DISPLAY_ENABLE,b1 BG_ENABLE,b2 SPR_ENABLE、COMMITで反映 |
| 04 | VRAM_ADDR_L | RW | address[7:0] |
| 05 | VRAM_ADDR_M | RW | address[15:8] |
| 06 | VRAM_ADDR_H | RW | address[23:16]、未実装範囲をaliasしない |
| 07 | VRAM_WRITE | WO | address/data/INCを捕捉しWRITE descriptor enqueue。成功だけaddress+=INC |
| 08 | VRAM_READ_REQUEST | WO | 値0のみ有効。READ descriptor enqueue、addressを捕捉し成功だけ+=INC |
| 09 | VRAM_READ_RESULT | RO | READY時に結果を返しREADY clear。未READYなら0＋NOT_READY error |
| 0A | EXT_REG_INDEX | RW | extended register番号。自動増加なし |
| 0B | EXT_REG_DATA | indexed | 選択registerの定義に従う |
| 0C | AUDIO_REG_INDEX | RW | audio register番号。自動増加なし |
| 0D | AUDIO_REG_DATA | indexed | audio-specに従う |
| 0E | COMMAND | WO | opcode。全引数を受付時に捕捉、成功時のみenqueue |
| 0F | FIFO_STATUS | RO | b5:0 空きentries 0..32（組立中予約も減算）、b6予約、b7 FULL |
| 10 | INC_L | RW | INC[7:0]、reset1 |
| 11 | INC_H | RW | INC[15:8]、reset0。unsigned、0なら同一address |
| 12 | LENGTH_L | RW | FILL byte count[7:0] |
| 13 | LENGTH_H | RW | count[15:8]。0はno-op、65536とはしない |
| 14 | FILL_VALUE | RW | 繰り返すbyte値 |
| 15 | FENCE_TAG | RW | 次FENCE用任意8bit token |
| 16 | DONE_TAG | RO | 最後に実行完了したFENCEのtoken |
| 17 | ERROR_CODE | RW1C | 下記sticky error bitmask |
| 18 | ID0 | RO | reset/read 0x4B ('K') |
| 19 | ID1 | RO | 0x39 ('9') |
| 1A | ABI_MAJOR | RO | 0 |
| 1B | ABI_MINOR | RO | 2 |
| 1C | CAPS | RO | b0 HDMI_AUDIO=1,b1 WAVE=1,b2 RDY=0,b3 PSRAM=0,b4 SPR16=1,b5 WIDE（320×180）、残り0。全体版は0x13、16:9版は0x33 |
| 1D | FRAME_COUNT_L | RO | VBlankイベントで増える8bit counter、wrap。snapshot不要な8bit値 |
| 1E | SPR_OVERFLOW_INDEX | RO | 最初にline上限を超えたsprite番号0..63。IRQ b5 clearで0に戻す |
| 1F | SPR_OVERFLOW_LINE | RO | 最初にoverflowした論理Y。IRQ b5 clearで0に戻す |

CAPSは機能を実装したbitstreamだけが立てる。Phase 1のテストtopにKAGURA全体CAPSを偽装しない。ENGINE_BUSYはキュー非空またはcommand実行中、READ_BUSYは受理済みREADの実行完了待ち、COMMIT_BUSYは映像COMMIT専用である。audio待ちはAUDIO_STATUSを参照する。

SPR_OVERFLOWのindex/lineはIRQ_STATUS.b5が0のとき最初の超過だけを捕捉し、clearまで保持する。同cycleのclearと新超過は新超過を優先する。FENCE_DONEは複数完了がcoalesceし得るのでDONE_TAGは常に最新完了値。複数FENCEを同時に待つソフトはtagのwrapを考慮する。

ERROR_CODE: b0 FIFO_FULL、b1 INVALID_ADDRESS、b2 BAD_ACCESS（opcode/値も含む）、b3 READ_COLLISION、b4 NOT_READY、b5 LINE_UNDERRUN、b6 AUDIO_FIFO_ERROR、b7 BUSY_CONFLICT。複数保持、W1C、新イベント優先。ERROR_PRESENTはERROR_CODE!=0。新規errorでIRQ.ERRORをset。原因clearとIRQ clearは独立。IRQ.ERRORを先にclearしても古い原因だけでは再setしない。

起動時のSTATUS.INIT_DONEは0。RAM消去完了で1になり、それまではVRAM_WRITE/READ_REQUEST/COMMANDをNOT_READYとして拒否する。拒否時はaddress、queue、COMMIT snapshotを変更しない。ID/STATUSの読出しなど通常のregister操作は可能。CPU接続topではさらに最初のline0準備までCPU resetを保持する。

## コマンドと順序

| COMMAND value | 内容 | 受付/完了規約 |
|---|---|---|
| 01 | FILL | 開始address、LENGTH、VALUEを捕捉。連続byteでINCを使わない。直接address registerは変更しない |
| 02 | FENCE | 先行command完了後DONE_TAG更新、IRQ.FENCE_DONE。tagを捕捉 |
| 03 | COMMIT | display/extended shadowを捕捉。先行書込み完了後のVBlankでOAM/paletteをcopy、IRQ.COMMIT_DONE |
| 04 | AUDIO_COMMIT | 全音源shadow設定を捕捉。先行wave書込み完了後のsample boundaryで設定反映＋wave bank交換。詳細は[audio-spec.md](audio-spec.md) |
| その他 | 未定義 | BAD_ACCESS、enqueueなし |

WRITE/READ/FILL/FENCE/COMMIT/AUDIO_COMMITは同じFIFOで順序保証する。後続READは先行WRITE/FILLの反映後に実行する。長いFILLやCOMMIT待ちを後続操作が追い越さない。FENCEにより連続WRITEの完了IRQを1回で受けられる。FILL自身はIRQを出さず、必要ならFENCEを後置する。

FIFO fullではキューへ投入する操作（VRAM_WRITE、VRAM_READ_REQUEST、FILL/FENCE/COMMIT/AUDIO_COMMIT）を拒否し、error/IRQを残す。拒否された操作はaddress、length、READY、COMMIT snapshotを変更しない。STATUS/FIFO_STATUSの読出し、通常レジスタの設定、error/IRQのclearは引き続き可能。READはpendingまたは未消費READYがあればREAD_COLLISIONとして拒否し、結果を上書きしない。正常受付時READ_BUSY=1、完了時BUSY=0/READY=1/IRQ.READ_DONE=1。READ_RESULTの消費ではIRQ.READ_DONEはclearしない。

FILLはenqueue前に範囲全体を検査し、開始〜開始+length−1が単一の公開領域に含まれなければINVALID_ADDRESS、部分実行なし。length0は有効な開始addressならno-op enqueue。WRITE/READは現在addressを検査し、自動増分結果は24bit modulo（次操作時に範囲検査）。境界から次領域へ自動wrapする機能はない。

COMMITは受付時にCOMMIT_BUSYを立てる。同時に1件だけ、再投入はBUSY_CONFLICT。待機中のshadow display/EXT書換えは次回COMMIT用で許可するが、今回のsnapshotを変えない。OAM/palette更新はFIFOでCOMMITの後ろに並ぶので今回には入らない。COMMITがVBlank開始時の実行headでなければ、次frameのVBlankまで待つ。コピー完了時BUSY clear、後続command再開。

## Extended registers

| Index | 内容 | Access/reset |
|---|---|---|
| 00 | SCROLL_X bits7:0 | RW shadow /0 |
| 01 | SCROLL_X bit8をb0、他予約 | RW shadow /0 |
| 02 | SCROLL_Y bits7:0 | RW shadow /0 |
| 03 | BACKDROP palette index | RW shadow /0 |
| 04 | RASTER_LINE 0..LINES−1（240または180）、LINES..255 disable | RW shadow /255 |
| 05 | MAX_SPRITES | RO/64 |
| 06 | MAX_LINE_SPRITES | RO/16（削減版は8） |
| 07 | PATTERN_COUNT_L | RO/0 |
| 08 | PATTERN_COUNT_H | RO/4（1024） |
| 09 | WAVE_LENGTH_MAX encoding | RO/8（2^8=256） |
| 0A | SCREEN_HEIGHT（論理ライン数LINES） | RO/240、16:9版180 |
| 0B..FF | 未実装 | read0/write BAD_ACCESS |

全readはshadow値（RO除く）。active値への暗黙read切替はしない。scrollはX modulo512/Y modulo256で背景マップへ適用。

## 典型手順

1. ID/ABI/CAPS確認。ドライバが全indexed/address操作を排他管理する。
2. addressとINCを設定。FIFO_STATUSの空き数以下のWRITEを投入。満杯ならpoll。errorなら原因を読みW1Cし、失敗分だけ再試行。
3. FILLはlength/value/addressを設定後COMMAND=1。完了確認はFENCE_TAG設定→COMMAND=2→DONE_TAG/IRQ確認。
4. READ_REQUEST=0→STATUS.READ_READYをpoll→READ_RESULT取得→IRQ.READ_DONEをW1C。
5. shadow OAM/palette/scrollを設定→COMMAND=3→COMMIT_DONE待ち。パターン/マップの書換えは別途VBlank時間を管理。
6. IRQ handlerはIRQ_STATUSを読み、処理したbitsだけ1を書いてclear。同cycle再イベントは残る。
7. 音源はAUDIO_REG_INDEX/DATAで全chのshadowを設定し、wave shadow（009800..0099FF）を転送してCOMMAND=4。AUDIO_STATUS.APPLY_BUSYまたは後置FENCEで反映完了を確認する。設定だけの更新でもwave bankが交換される点に注意。[音源仕様](audio-spec.md)を参照。

【実装】offset・名前・access・bit・reset値・コマンド・VRAM領域の機械可読定義は`spec/registers.json`。`tools/gen-registers.ps1`がSystemVerilog package（`rtl/core/kagura_abi_pkg.sv`）、Cヘッダ（`software/include/kagura_regs.h`）、ca65 include（`software/w65c02/kagura_regs.inc`）を生成する。副作用の規範はこの文書の本文のまま残す。文書の表は生成せず、`-Check`で本書・[音源仕様](audio-spec.md)・[メモリマップ](memory-map.md)の表と定義の一致、生成物が最新であることをCIで検査する。`tb_register_abi`は生成packageとRTLのreset値・access可否を照合する。

## ABI 0.2（2026-10-23）

16:9モード（[wide-mode.md](wide-mode.md)）のための追加。既存のregister配置・副作用は変更しない。

- ABI_MINORを2にした。全bitstreamが0.2を返す。
- CAPS b5 WIDE: 論理画面320×180を1280×720へ4×4で表示するbitstreamだけが立てる。
- EXT 0A SCREEN_HEIGHT（RO）: 論理ライン数LINES。従来版240、16:9版180。
- RASTER_LINEの有効範囲は0..LINES−1。LINES以上はdisable。16:9版では180..255が無効。
- 背景・スプライトの座標系、scroll、マップの扱いは同じ。16:9版は論理Y 0..179だけを描画する。

ソフトはCAPS b5またはSCREEN_HEIGHTで画面高を判定する。ABI_MINOR=1のbitstreamにはEXT 0Aがない（read 0）。
