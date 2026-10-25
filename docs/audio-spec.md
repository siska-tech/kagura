# Audio Specification / 6 voices

【設計】ch0..2 pulse、ch3 noise、ch4..5 wavetable。出力signed16bit L/R、48000 samples/s。system54MHzに/1125 enable、最初のsample boundaryをreset解除後に統一する。補間/ADSRはv0.1に含めない。PSRAMのsampleを再生する2ch PCM音源はABI 0.4のCAPS b3版だけが持つ（下記「PCM音源」）。

## 周波数と波形

各周期波形にunsigned24bit phaseを持つ。各sampleで現在phaseから波形を計算してから`phase=(phase+step) mod 2^24`。

```text
f = step * 48000 / 16777216 Hz
resolution = 0.00286102294921875 Hz
step(440Hz) = round(440 * 16777216 / 48000) = 153791
actual = 440.0014877319336 Hz
```

有効stepは0..0x7FFFFF。bit23=1の値はAPPLYをBAD_ACCESSで拒否。step0はDCを出さず無音にする。帯域制限・アンチエイリアシングは行わないので高音の波形にはaliasが出る。これは初版の音色仕様である。

- Pulse: phase[23:16] < DUTYなら+127、それ以外−127。DUTY1..255、0は無音。1/8、1/4、1/2は32、64、128。
- Wave: 長さ2^LEN_LOG2（5..8）、phase上位LEN_LOG2 bitでインデックス。ch4/ch5それぞれ256byteの固定領域、短い長さでは先頭だけ使用。signed8bit -128..127。
- Noise: 15bit LFSR初期値1。更新式`{state[13:0],state[14]^state[13]}`、出力state[14]を±127へ変換。COUNTが0ならLFSRを進めCOUNT=PERIOD、それ以外COUNT--。reset COUNT=PERIOD。更新間隔はPERIOD+1 samples、PERIOD16bit。テストで全非0状態32767個の周期を確認する。

disabled channelは出力0、phase/counter/LFSRは保持。phase reset requestはenable状態に関係なくphase=0、noise seed=1/counter=PERIODに戻す。リセット直後のsampleはphase0由来で出す。

Noiseのsampleは更新前のstate[14]（1なら+127、0なら−127）から計算し、その後COUNT/LFSRを更新する。PERIODの設定変更だけではCOUNTを再ロードせず、phase reset request時またはCOUNT=0の更新時に新PERIODをロードする。

## 音源レジスタ（AUDIO_REG_INDEX/DATA）

ch cはindex=16*c+offset（00..5F）。全てshadow RW、reset0。予約はread0/write ignored。

| offset | 内容 |
|---|---|
| 0 | STEP bits7:0（noiseでは予約） |
| 1 | STEP bits15:8 |
| 2 | STEP bits23:16 |
| 3 | DUTY（pulseのみ） |
| 4 | GAIN_L 0..255 |
| 5 | GAIN_R 0..255 |
| 6 | CONTROL b0 enable、b1 phase_reset_pending（COMMIT成功で自動clear）、残り予約 |
| 7 | LEN_LOG2（waveのみ）、reset5 |
| 8 | NOISE_PERIOD low（ch3のみ） |
| 9 | NOISE_PERIOD high（ch3のみ） |
| A..F | 予約 |

他channel種別に使わないフィールドはread0/write ignored。60..9FはCAPS b3版ではPCM音源レジスタ（下記）、それ以外では未実装。A0..DFは未実装read0/write BAD_ACCESS。

| index | 内容 |
|---|---|
| E0 | MASTER_GAIN RW shadow、0..255、reset32 |
| E1 | AUDIO_STATUS RO: b0 APPLY_BUSY、b1 FIFO_UNDERFLOW sticky、b2 OVERFLOW sticky、b3 MUTED、残り0 |
| E2 | AUDIO_ERROR_CLEAR WO: b1/b2の1で対応sticky clear。新イベント優先 |
| E3..FF | 未実装read0/write BAD_ACCESS |

MUTEDはlink起動待ち/障害回復時の強制mute状態を示す。単に全channel disableまたはgain0で無音でも、強制mute中でなければ0。error clearはERROR_CODE.b6およびIRQ.ERRORを自動clearしない。

音源設定は書いた瞬間にactive化しない。直接COMMAND=04 AUDIO_COMMITで全ch設定/MASTER_GAIN/phase reset maskを専用snapshotへ捕捉し、FIFOへtokenを投入する。1件だけpending。fullまたはAPPLY_BUSY時は拒否し、shadow/phase reset bitsを変更しない。有効なLEN/STEPは受付前に検査する。演算は23system cycles/sampleで実装し、受付から次sample境界までの待ち時間はこの演算時間に含めない。

token実行時、先行wave書込みを完了させ、次sample boundaryで設定反映しwaveのactive/shadow bankを交換する。コピーは不要。交換後のshadowには以前のactive内容が残るので、差分編集時はこの規則に従う。waveを変えない設定更新でもbank交換するため、ドライバは両bankへ同じ初期波形を準備するか、毎回使用波形をshadowに書く。

COMMIT完了まで後続VRAM commandは待機。音源shadow registerは書換え可能だがsnapshotには影響しない。phase_reset_pendingは受付でclearし、後から書いたreset requestは次COMMIT用。完了はAPPLY_BUSY=0、必要ならFENCEを後置して通知する。音源commitの全処理は1sample内の64system cyclesを上限にする。

## PCM音源（CAPS b3、ABI 0.4）

2ch。sampleはsigned 8bit、48kHz固定で1 sampleごとに1 byte進む。PSRAM領域（400000–7FFFFF）のbyte列を再生する。補間・可変ピッチ・ADPCMはない。6音源の後段で同じmixerに加算し、MASTER_GAINと飽和は共通。PCM pはindex=0x60+0x20*p+offset（p=0,1、60..7Fと80..9F）。

| offset | 名前 | 内容 |
|---|---|---|
| +00 | START_L | 再生開始address bits7:0（24bit、PREPAREで取込み） |
| +01 | START_M | START bits15:8 |
| +02 | START_H | START bits23:16 |
| +04 | END_L | 終了address（排他的）bits7:0 |
| +05 | END_M | END bits15:8 |
| +06 | END_H | END bits23:16 |
| +08 | LOOP_L | loop再開address bits7:0 |
| +09 | LOOP_M | LOOP bits15:8 |
| +0A | LOOP_H | LOOP bits23:16 |
| +0C | GAIN_L | 0..255、AUDIO_COMMITで反映 |
| +0D | GAIN_R | 0..255、AUDIO_COMMITで反映 |
| +0E | CONTROL | b0 ENABLE（AUDIO_COMMITで反映）、b1 LOOP_ENABLE（PREPAREで取込み） |
| +0F | CMD | WO（AUDIO_REG_DATAへのwrite）: b0 PREPARE、b1 STOP、b2 CLEAR |
| +0F | STATUS | RO（AUDIO_REG_DATAのread）: b0 READY、b1 ACTIVE、b2 DONE、b3 UNDERRUN、b4 CONFIG_ERROR、b5 MEMORY_ERROR、b6 PREPARING |

+0F以外はRW shadow、reset0。+03、+07、+0B、+10..+1Fは予約（read0/write ignored）。

- PREPARE: 再生中なら直ちに止め、START/END/LOOP/LOOP_ENABLEを取り込み、先読みbufferを捨ててSTARTから先読みを始める（PREPARING=1）。条件は`0x400000 <= START < END <= 0x800000`、LOOP_ENABLE時は`START <= LOOP < END`。違反はCONFIG_ERROR。取込みは受付時なので、PREPARING中にSTART等を書き換えない。先読みが終わるとREADY。
- 開始と一時停止: AUDIO_COMMITが反映されるsample境界で、ENABLE=1かつREADYでACTIVEでないchが再生を始める。READYでないchは開始しないが、AUDIO_COMMIT自体は拒否しない（one-shot終了後もENABLE=1のまま他の音源を更新できるようにするため）。開始したかはACTIVEで確認する。ENABLE=0が反映されると再生中のchは一時停止し、bufferと位置を保つ。次にENABLE=1が反映されると続きから再生する。GAINだけの変更は再生位置を変えない。
- 終端: ENDに達すると、LOOP_ENABLE時はLOOPへ戻り途切れず続ける。one-shotでは最後のsampleを出した次のsampleから無音になり、ACTIVE=0、DONE=1。
- STOP: 直ちに止める。再生には再びPREPAREが要る。
- CMDのwrite後、次のregister要求はSTATUSが反映されるまで数cycle待たされる（RS_*と同じ）。したがってwrite直後のSTATUS readはcommandの結果を返す。
- DONE、UNDERRUN、CONFIG_ERROR、MEMORY_ERRORはstickyで、CLEARで消える。いずれかが立った後とSTOP後は、PREPAREするまでREADYにならない。UNDERRUN（補充が間に合わない）とMEMORY_ERROR（PSRAM応答の失敗またはtimeout）は該当chだけを無音で止め、他の音源とHDMIのsample cadenceは続く。ERROR_CODE・IRQ・AUDIO_STATUSには反映しないので、STATUSをpollする。
- 先読みbufferは各ch 32 sample。補充は1 byteごとにPSRAMへ要求し、hostのPSRAM転送が連続する最悪条件でも応答待ちは実機で最大57 system cycles（約1.06µs）だった（[psram-pcm.md](psram-pcm.md)）。
- PCMの出力換算は他の音源と同じ`sample*GAIN`で、8音源のsumはsigned20bit（−261120..259080）に収まる。PCM版の演算は29 system cycles/sample（上限64）。PCMのない版は従来どおり6音源・23 cycles/sampleで、出力も従来とbit単位で同じ。

## ミキサーと演算幅

独立L/R gainを音量とパンの表現に使う（中央ならL=R、片側0ならhard pan）。

```text
voice_sample = signed8
product_L/R = voice_sample * unsigned8_gain    # signed17bitで保持
sum_L/R = sum(6 products)                     # signed20bit
scaled = arithmetic_shift_right(sum * MASTER_GAIN, 8)  # signed29bit乗算
output = clamp(scaled, -32768, 32767)
```

gain255は255/256相当の係数として扱う。最大sumは正194310、負−195840なので20bitに余裕がある。MASTER_GAIN255ではclipし得るため、最後に飽和を行いwrapさせない。reset32でheadroomを取る。計算中の幅を言語の暗黙符号拡張に任せない。

乗算器を2個以内へ時分割共有する予算。6ch×左右の乗算、phase更新、2wave読出し、2master乗算、飽和を64cycles以内に完了し、次のsample境界前まで結果を保持する。FIFOへはL/Rを同時に1回だけ書く。FIFO full時は新sampleを捨ててOVERFLOW/ERRORを立てる（無言で捨てない）。pixel側empty時は無音sampleを出してUNDERFLOW/ERRORを立てる。通常状態ではどちらも0を受入条件とする。

## 検証

独立の整数参照モデルと全sampleを比較。440Hz等のSTEP丸め、DUTY境界、enable保持、phase reset、noise全周期、wave長/符号端値、gain0/255、全ch最大入力、正負飽和、COMMIT途中の設定変更を含める。RTL出力からWAVを作る。Python等のモデルだけで作ったWAVをRTL検証結果と呼ばない。
