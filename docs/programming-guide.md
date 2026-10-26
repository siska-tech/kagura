# プログラミングガイド

ホストからKAGURA-9を使う手順。規範は[レジスタ仕様](register-map.md)・[メモリマップ](memory-map.md)・[映像仕様](video.md)・[音源仕様](audio-spec.md)で、この文書は典型的な使い方をまとめる。

## 定数とライブラリ

- C: [`software/include/kagura_regs.h`](../software/include/kagura_regs.h)。offsetは`KAGURA_REG_*`、EXT indexは`KAGURA_EXT_*`、bitはmask値。
- ca65: [`software/w65c02/kagura_regs.inc`](../software/w65c02/kagura_regs.inc)。`.include`の前に`KAGURA_IO_BASE`を定義すると窓の位置を変えられる。`KAGURA_IO_*`が絶対address。
- どちらも`spec/registers.json`から`tools/gen-registers.ps1`が生成する。手で編集しない。
- Raspberry Pi Pico用のSPI/QSPIドライバ`software/pico/kagura_host.[ch]`（`kh_*`）が、以下の手順の実装例になる。

以下の擬似コードで、`wr(reg, v)`・`rd(reg)`はレジスタ窓の1 byteの書込み・読出し、`ext_wr(i, v)`はEXT_REG_INDEX=i→EXT_REG_DATA=v、`aud_wr(i, v)`はAUDIO_REG_INDEX=i→AUDIO_REG_DATA=vを表す。

## 1. 起動と確認

```text
READYピン=1を待つ（SPI/QSPI）。W65C02SはRESB解除後に動き始める
ID0=0x4B、ID1=0x39、ABI_MAJOR=0、ABI_MINOR=5 を確認
STATUS.INIT_DONE=1 を待つ
CAPS を読み、使う機能（b3 PSRAM、b5 WIDE、b6 RSCROLL）を判定
LINES = ext_rd(SCREEN_HEIGHT)            # 240 または 180
wr(ERROR_CODE, 0xFF); wr(IRQ_STATUS, 0xFF)   # 古いerror/IRQをclear
```

起動直後はpalette全色黒・OAM全disable・DISPLAY_CTRL=0で、画面は黒い。

## 2. VRAMへの転送

```text
wr(INC_L, 1); wr(INC_H, 0)
wr(VRAM_ADDR_L/M/H, addr)
各byteについて: queueの空きを確認してから wr(VRAM_WRITE, b)
```

- 1 byteが1 queue entry（32 entry）を使う。空きはFIFO_STATUS b5:0、SPIならheaderで返る値、SPI/QSPIならBUSYピンで確認する（[ホストインターフェース](host-interface.md#フロー制御)）。
- 拒否（FIFO_FULL等）されたbyteはaddressが進まないので、ERROR_CODEを読み、W1Cしてからそのbyteだけを再送する。結果が分からない操作をむやみに再送しない。
- まとまった消去はFILL: `VRAM_ADDR`、`LENGTH`、`FILL_VALUE`を設定して`COMMAND=01`。範囲は1つの領域に収める。
- 完了を待つにはFENCE: `FENCE_TAG=t`→`COMMAND=02`→`DONE_TAG==t`（またはIRQ.FENCE_DONE）。

### 読戻し

```text
wr(VRAM_ADDR_*, addr)
wr(VRAM_READ_REQUEST, 0)
STATUS.READ_READY=1 を待つ
v = rd(VRAM_READ_RESULT)        # READYがclearされる
wr(IRQ_STATUS, READ_DONE)       # IRQを使う場合
```

読み終える前に次のREAD_REQUESTを書くとREAD_COLLISIONになる。

## 3. 画面の準備

1. **palette**: shadowの`0x9400 + index*2`へRGB444をlittle endianで書く（例: 白は`FF 0F`）。
2. **pattern**: `t*32`から32 byte（1行4 byte、上位nibbleが左）。
3. **map**: `0x8000 + (row*64+col)*2`へ`tile | palette<<10 | hflip<<14 | vflip<<15`。
4. **表示設定**: `DISPLAY_CTRL = DISPLAY_ENABLE|BG_ENABLE|SPR_ENABLE`、`BACKDROP`、`SCROLL_X/Y`。
5. `COMMAND=03`（COMMIT）→ `STATUS.COMMIT_BUSY=0`またはIRQ.COMMIT_DONEを待つ。

paletteとDISPLAY_CTRL・scrollはCOMMITで初めて画面に出る。patternとmapは書いた時点で描画に使われるので、表示中の領域を書き換えるときはVBlank中に行うか、未使用の領域へ書いてから切り替える。

## 4. sprite

sprite nのshadowは`0xA000 + n*8`の8 byte（[レコード形式](memory-map.md#sprite-8byteレコード)）。

```text
byte0 = x & 0xFF
byte1 = (x >> 8) & 3
byte2 = y & 0xFF
byte3 = ((y >> 8) & 3) | enable<<2 | size16<<3 | hflip<<4 | vflip<<5 | behind<<6
byte4 = tile & 0xFF
byte5 = ((tile >> 8) & 3) | palette<<2
byte6 = byte7 = 0
```

x・yは10bitの2の補数（−512..511）。16×16はtileの下位2bitを無視した4枚（左上、右上、左下、右下）を使う。OAMの変更もCOMMITで反映する。1ラインに17個以上重なるとSPR_OVERFLOWで知らせ、17個目以降は描かれない。

## 5. 毎フレームの更新

```text
loop:
    VBLANK（IRQまたはFRAME_COUNT_Lの変化）を待つ
    変わったspriteのshadow OAM、palette、scroll、ラスタ表を書く
    COMMAND=03（COMMIT）
    必要ならAUDIO_COMMIT
```

- COMMITはqueueで後続を止め、次のVBlank開始でcopyする。COMMIT_BUSYの間は次のCOMMITを書かない（BUSY_CONFLICT）。
- 1フレームの転送量の目安: OAM全体2 KiB、palette 512 byte。SPI/QSPI 5MHzでも60fpsに収まる。

### ラスタスクロール（CAPS b6）

```text
COMMIT_BUSY=0 を確認
ext_wr(RS_INDEX, 0)
各entry i（lineの昇順）: ext_wr(RS_LINE, line); ext_wr(RS_X_L, x); ext_wr(RS_X_H, x>>8); ext_wr(RS_Y, y)
ext_wr(RS_COUNT, n)
COMMAND=03
```

lineは厳密昇順で`< LINES`。COMMIT_BUSY中の表への書込みは拒否されるので、前のCOMMITの完了後に書く。

## 6. IRQ

```text
IRQ_ENABLE = 使う要因のmask（VBLANK、RASTER、FENCE_DONE、READ_DONE、COMMIT_DONE、SPR_OVERFLOW、ERROR）
handler:
    s = rd(IRQ_STATUS) & 有効なmask
    sを処理
    wr(IRQ_STATUS, s)     # 処理したbitだけclear。同時に起きた新しい要因は残る
```

handlerはメインのドライバが使うINDEX系レジスタ（VRAM_ADDR、EXT_REG_INDEX、AUDIO_REG_INDEX）を書き換えないか、退避・復元する。W65C02Sでは窓へRMW命令（INC、ASLなど）やindexed addressingのdummy readを使わない。

## 7. 音源

```text
ch c の index = 16*c + offset
pulse: STEP(0..2)、DUTY(3)、GAIN_L/R(4/5)、CONTROL(6)=ENABLE
noise: GAIN_L/R、CONTROL、NOISE_PERIOD(8/9)
wave : STEP、GAIN_L/R、CONTROL、LEN_LOG2(7)、波形はVRAM 0x9800（ch4）/0x9900（ch5）
MASTER_GAIN = index E0
COMMAND=04（AUDIO_COMMIT）→ AUDIO_STATUS.APPLY_BUSY=0 を待つ
```

- STEP = round(f × 16777216 / 48000)。440Hzは153791。
- AUDIO_COMMITのたびにwaveのbankが入れ替わる。起動時は同じ波形を書いて2回AUDIO_COMMITし、両bankをそろえておくと、以後は波形を変えない更新でも音色が変わらない。波形を変えるときは新しい波形をshadowへ書いてからAUDIO_COMMITする。
- 音を鳴らし直す（phaseを0から始める）にはCONTROLへ`ENABLE|PHASE_RESET`を書いてAUDIO_COMMIT。
- 曲の再生は、1フレームごとに全chのSTEP・GAINを書いてAUDIO_COMMITする方式で足りる。

## 8. PCM（CAPS b3）

```text
1. PSRAM（0x400000以降）へsampleをupload（signed 8bit、48kHz）
2. FENCEで完了を確認
3. PCM pの START/END/LOOP（index 0x60+0x20*p+0x00..0x0A）とCONTROL.LOOP_ENABLEを設定
4. CMD(+0F) = PREPARE
5. STATUS(+0F).READY=1 を待つ
6. GAIN_L/R(+0C/+0D)、CONTROL.ENABLE=1 を設定して AUDIO_COMMIT
7. STATUS.ACTIVE=1 で再生開始を確認。one-shotは終わるとDONE
```

- 同じ音を鳴らし直すには、もう一度PREPAREからやり直す（DONE等の後はREADYにならない）。STICKYなstatusはCMD=CLEARで消す。
- 再生中のchが参照する範囲へは書かない。別の範囲へのuploadやCOPYは並行してよい。
- UNDERRUN・MEMORY_ERRORはERROR_CODEに出ないので、PCMのSTATUSをpollする。

### COPY

```text
ext_wr(COPY_SRC_L/M/H, psram_addr)
wr(VRAM_ADDR_*, vram_addr); wr(LENGTH_*, n)
COMMAND=05
FENCE で完了を確認
```

PSRAMに置いたpattern・map・palette等をVRAMへ速く送れる（32KiBで約7ms）。アニメーションのコマをPSRAMに置き、毎フレームCOPYで差し替える使い方ができる。

## 9. エラー処理

- ERROR_CODEはstickyなbitmaskで、STATUS.ERROR_PRESENTでも分かる。IRQ_ENABLE.ERRORを立てればIRQで知らされる。
- 原因を読んでから、ERROR_CODEとIRQ_STATUS.ERRORをそれぞれW1Cでclearする。
- 拒否された操作は何も変えていないので、原因を取り除けば同じ操作を再送できる。
- 通常の動作でLINE_UNDERRUN・AUDIO_FIFO_ERRORは起きない。起きた場合はhardwareまたは設定の異常として扱う。
