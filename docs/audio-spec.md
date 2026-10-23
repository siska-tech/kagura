# Audio Specification / 6 voices

【設計】ch0..2 pulse、ch3 noise、ch4..5 wavetable。出力signed16bit L/R、48000 samples/s。system54MHzに/1125 enable、最初のsample boundaryをreset解除後に統一する。補間/ADSR/PCMはv0.1に含めない。

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

他channel種別に使わないフィールドはread0/write ignored。60..DFは未実装read0/write BAD_ACCESS。

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
