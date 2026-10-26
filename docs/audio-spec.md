# 音源仕様

6ch音源（pulse 3、noise 1、wavetable 2）と、CAPS b3版だけが持つPCM 2chの仕様。出力はsigned 16bitステレオ、48000 samples/sで、HDMIの音声packetとして送る。

- sample境界はsystem 54MHzの1125分周（48kHz）。音源用の別clockは作らずclock enableとして使う。
- 1 sampleの演算は6ch版で25 system cycle、PCM版で31 cycle。上限は1125 cycle。
- 補間、ADSR、帯域制限はない。高音の波形にはaliasが出る。

## 周波数と波形

各周期波形（pulse・wave）はunsigned 24bitのphaseを持つ。各sampleで現在のphaseから波形を計算し、その後`phase=(phase+STEP) mod 2^24`とする。

```text
f = STEP * 48000 / 16777216 Hz
分解能 = 0.00286102294921875 Hz
STEP(440Hz) = round(440 * 16777216 / 48000) = 153791（実周波数 440.0014877319336 Hz）
```

有効なSTEPは0..0x7FFFFF。bit23=1の値があるとAUDIO_COMMITをBAD_ACCESSで拒否する。STEP 0はDCを出さず無音。

- **Pulse（ch0..2）**: `phase[23:16] < DUTY`なら+127、それ以外は−127。DUTYは1..255、0は無音。1/8、1/4、1/2はそれぞれ32、64、128。
- **Wave（ch4..5）**: 長さ2^LEN_LOG2（5..8、32〜256 sample）の波形を、phaseの上位LEN_LOG2 bitで引く。sampleはsigned 8bit（−128..127）。ch4・ch5はそれぞれ256 byteの領域を持ち、短い長さでは先頭だけを使う。LEN_LOG2が5..8以外だとAUDIO_COMMITはBAD_ACCESS。
- **Noise（ch3）**: 15bit LFSR、初期値1。sampleは更新前の`state[14]`（1で+127、0で−127）。その後COUNTが0ならLFSRを`{state[13:0], state[14]^state[13]}`へ進めてCOUNT=PERIOD、0でなければCOUNT−1。更新間隔はPERIOD+1 sample（PERIODは16bit）。周期は32767状態。PERIODを変えただけではCOUNTを再ロードせず、phase reset時かCOUNT=0の更新時に新しいPERIODを読む。

disabledのchは出力0で、phase・counter・LFSRを保持する。phase reset要求はenableに関係なくphase=0、noiseはLFSR=1・COUNT=PERIODに戻す。reset直後のsampleはphase 0から出す。

## 音源レジスタ（AUDIO_REG_INDEX/DATA）

ch cはindex=16*c+offset（00..5F）。すべてshadowのRWで、AUDIO_COMMITで反映する。reset値は0（LEN_LOG2を除く）。

| offset | 内容 |
|---|---|
| 0 | STEP bits7:0（pulse・wave） |
| 1 | STEP bits15:8 |
| 2 | STEP bits23:16 |
| 3 | DUTY（pulseのみ） |
| 4 | GAIN_L 0..255 |
| 5 | GAIN_R 0..255 |
| 6 | CONTROL b0 ENABLE、b1 PHASE_RESET（要求。AUDIO_COMMITの受付で自動clear）、他予約 |
| 7 | LEN_LOG2（waveのみ）、reset5 |
| 8 | NOISE_PERIOD bits7:0（noiseのみ） |
| 9 | NOISE_PERIOD bits15:8（noiseのみ） |

offset A..Fと、そのch種別が使わないfield（noiseのSTEP、pulse以外のDUTYなど）は予約で、read 0・write無視。index 60..9FはCAPS b3版ではPCM音源（下記）、それ以外では未実装。A0..DFは未実装（read 0、write BAD_ACCESS）。

| index | 内容 |
|---|---|
| E0 | MASTER_GAIN RW shadow、0..255、reset32 |
| E1 | AUDIO_STATUS RO: b0 APPLY_BUSY、b1 FIFO_UNDERFLOW sticky、b2 OVERFLOW sticky、b3 MUTED、残り0 |
| E2 | AUDIO_ERROR_CLEAR WO: b1/b2に1を書くと対応するstickyをclear。同cycleの新イベントを優先 |
| E3..FF | 未実装（read 0、write BAD_ACCESS） |

- APPLY_BUSY: AUDIO_COMMITの受付から反映完了まで1。
- FIFO_UNDERFLOW・OVERFLOW: HDMI音声FIFOの異常（下記）。ERROR_CODE.b6とIRQ.ERRORも立つ。AUDIO_ERROR_CLEARはこの2bitだけをclearし、ERROR_CODE・IRQはそれぞれのW1Cでclearする。
- MUTED: HDMI側が起動待ち・underflow回復待ちで強制的に無音を出していること。全chをdisableやgain 0にして無音でも、強制muteでなければ0。

## AUDIO_COMMIT

音源の設定は書いた瞬間には反映しない。COMMAND=04（AUDIO_COMMIT）が全chの設定・MASTER_GAIN・PHASE_RESET要求（PCM版ではPCMのGAIN・ENABLEも）を専用のsnapshotへ捕捉し、queueへ投入する。

- 同時に1件だけ。APPLY_BUSY中はBUSY_CONFLICT、queue満杯はFIFO_FULL、STEP・LEN_LOG2の不正はBAD_ACCESSで拒否し、shadow・PHASE_RESETを変えない。
- 受付時にshadowのPHASE_RESETを0に戻す。受付後に書いたPHASE_RESETは次回用。
- queueで先頭に来たら、先行するVRAM操作（waveへの書込みを含む）の完了を待ち、次のsample境界で設定を反映し、**同時にwaveのactive/shadow bankを交換する**。copyはしない。
- 交換後のshadowには直前までactiveだった内容が残る。waveを変えない更新でもbankは交換されるので、ドライバは両bankに同じ波形を用意するか、毎回使う波形をshadowへ書いてからAUDIO_COMMITする。
- 反映完了はAPPLY_BUSY=0で見る。IRQで知りたい場合はFENCEを後置する。AUDIO_COMMITの完了まで後続のqueue操作は待つ。

waveのshadowはVRAMの009800–0099FF（ch4が前半256 byte、ch5が後半256 byte）。[メモリマップ](memory-map.md)を参照。

## PCM音源（CAPS b3）

2ch。PSRAM領域（400000–7FFFFF）に置いたsigned 8bitのbyte列を、48kHz固定で1 sampleごとに1 byte進めて再生する。補間・可変ピッチ・ADPCMはない。6chの後段で同じmixerへ加算し、MASTER_GAINと飽和は共通。PCM pはindex=0x60+0x20*p+offset（p=0,1、60..7Fと80..9F）。

| offset | 名前 | 内容 |
|---|---|---|
| +00 | START_L | 再生開始address bits7:0（24bit。PREPAREで取込み） |
| +01 | START_M | START bits15:8 |
| +02 | START_H | START bits23:16 |
| +04 | END_L | 終了address（この直前のbyteまで再生）bits7:0 |
| +05 | END_M | END bits15:8 |
| +06 | END_H | END bits23:16 |
| +08 | LOOP_L | loopで戻るaddress bits7:0 |
| +09 | LOOP_M | LOOP bits15:8 |
| +0A | LOOP_H | LOOP bits23:16 |
| +0C | GAIN_L | 0..255。AUDIO_COMMITで反映 |
| +0D | GAIN_R | 0..255。AUDIO_COMMITで反映 |
| +0E | CONTROL | b0 ENABLE（AUDIO_COMMITで反映）、b1 LOOP_ENABLE（PREPAREで取込み） |
| +0F | CMD | WO（AUDIO_REG_DATAへのwrite）: b0 PREPARE、b1 STOP、b2 CLEAR |
| +0F | STATUS | RO（AUDIO_REG_DATAのread）: b0 READY、b1 ACTIVE、b2 DONE、b3 UNDERRUN、b4 CONFIG_ERROR、b5 MEMORY_ERROR、b6 PREPARING |

+0F以外はRWでreset 0。+03・+07・+0B・+10..+1Fは予約（read 0、write無視）。

- **PREPARE**: 再生中なら直ちに止め、START・END・LOOP・LOOP_ENABLEを取り込み、先読みbufferを捨ててSTARTから先読みを始める（PREPARING=1）。条件は`0x400000 <= START < END <= 0x800000`、LOOP_ENABLE時はさらに`START <= LOOP < END`。外れるとCONFIG_ERROR。値は受付時に取り込むので、PREPARING中にSTART等を書き換えてもよいが反映はされない。先読みが終わるとREADY=1。
- **開始と一時停止**: AUDIO_COMMITが反映されるsample境界で、ENABLE=1・READY・非ACTIVEのchが再生を始める。READYでないchは開始しないが、AUDIO_COMMIT自体は拒否しない（one-shotの終了後もENABLE=1のまま他の音源を更新できる）。開始したかはACTIVEで確認する。ENABLE=0が反映されると再生中のchは一時停止し、bufferと位置を保つ。次にENABLE=1が反映されると続きから再生する。GAINだけの変更は再生位置を変えない。
- **終端**: ENDに達すると、LOOP_ENABLE時はLOOPへ戻って途切れず続ける。one-shotは最後のsampleの次から無音になり、ACTIVE=0、DONE=1。
- **STOP**: 直ちに止める。再び鳴らすにはPREPAREが要る。
- **sticky**: DONE・UNDERRUN・CONFIG_ERROR・MEMORY_ERRORはCLEARまで残る。どれかが立った後とSTOPの後は、PREPAREするまでREADYにならない。
- **異常**: UNDERRUN（補充が間に合わない）とMEMORY_ERROR（PSRAMの応答errorか4096 cycleのtimeout）は、そのchだけを無音で止める。他の音源とHDMIのsample cadenceは続く。ERROR_CODE・IRQ・AUDIO_STATUSには出ないので、STATUSをpollする。
- CMDのwrite直後のSTATUS readは、そのcommandの結果を返す（反映まで次の要求が待たされる）。

先読みbufferは各ch 32 byte。補充はPSRAMへ1 byteずつ要求し、host側のPSRAM操作より優先して仲裁する（[PSRAM](psram.md#仲裁)）。

host規約:

- PREPAREの前に、そのsampleのuploadの後へFENCEを置いて完了を確認する。
- PREPARE済み・再生中のchが参照する範囲（START..END−1）は書き換えない（再生結果は不定）。別の範囲へのupload・読戻し・COPYは再生と並行してよい。

## ミキサーと演算幅

各音源の独立したL/R gainで音量とpanを表す（中央ならL=R、片側0ならhard pan）。

```text
voice_sample = signed8                         # pulse/noise ±127、wave/PCMはsigned 8bit
product_L/R  = voice_sample * unsigned8_gain   # signed 17bit
sum_L/R      = sum(products)                   # 6chはsigned 20bit、8chも−261120..259080に収まる
scaled       = arithmetic_shift_right(sum * MASTER_GAIN, 8)
output       = clamp(scaled, -32768, 32767)
```

gain 255は255/256相当。MASTER_GAINが大きいとclipし得るので、最後に飽和してwrapさせない。reset値32でheadroomを取る。乗算器はL/R各1個（18×9）を全音源のgainとMASTER_GAINで時分割共有し、乗算器の入力は使う1 cycle前にregisterへ読み込む（入力を組合せで選ぶと実機で前の音源のsampleが漏れた）。PCMのないbitstreamは6ch・25 cycleで、出力はPCM版でPCMを鳴らさない場合とbit単位で同じ。

## HDMIへの受け渡し

1 sample（L/R 32bit）ごとにsystem→pixelの非同期FIFO（深さ16、Gray pointer）へ書く。pixel側は48kHzのtick（480pは25.2MHzの525分周、720pは74.25MHzの12375/8分周）ごとに1 sampleを取り出し、HDMIのaudio sample packetにする。

- 起動時とunderflow後はmute状態で無音を出し、4 sampleたまってからmuteを解く（AUDIO_STATUS.MUTED）。
- muteでないtickでFIFOが空なら、無音を出してFIFO_UNDERFLOWを立て、再びmuteへ入る。
- FIFOが満杯のときの新しいsampleは捨ててOVERFLOWを立てる。
- 通常動作ではどちらも起きない。system/pixelは同じ27MHz発振器から作るので、長期の周波数比は一致する。

HDMI側の詳細（ACR、InfoFrame）は[HDMI出力](hdmi.md)。

## 検証

`tb_audio_synth`は独立した整数参照モデルと34770 stereo sampleを全数比較する（STEPの丸め、DUTY境界、enableでの保持、phase reset、noise全周期、wave長と符号端、gain 0/255、全ch最大、正負飽和、反映中の設定変更、25 cycle/sample）。`tb_audio_pcm_mix`はPCMの独立gain・snapshot・飽和と31 cycle/sample、`tb_audio_core`は公開register経由のAUDIO_COMMIT順序・wave bank交換・拒否、`tb_psram_core`はPCMの公開ABIを検査する。実機での確認範囲は[検証状況](validation-status.md)。
