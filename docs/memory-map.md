# Memory Map / BSRAM配置案

【設計】CPUは24bit論理アドレスを使用するがv0.1では下表の範囲だけを実装する（PSRAM領域はABI 0.4のCAPS b3版のみ）。上位アドレスを無視してaliasさせない。未実装領域はINVALID_ADDRESS、読出し結果は0。多byte値はlittle endian。

| VRAM address | 用途 | CPUアクセス |
|---|---|---|
| 000000–007FFF | 1024 patterns ×32byte | RW、表示と仲裁 |
| 008000–008FFF | 64×32 map ×2byte | RW、表示と仲裁 |
| 009400–0095FF | shadow palette、256×2byte | RW、上位4bitは0 |
| 009600–0097FF | active palette | 非公開、アクセスエラー |
| 009800–0099FF | shadow wave、2×256 signed 8bit | RW |
| 009A00–009BFF | active wave | 非公開、アクセスエラー |
| 00A000–00A7FF | shadow OAM、256×8byte | RW |
| 00A800–00AFFF | active OAM | 非公開、アクセスエラー |
| 400000–7FFFFF | PSRAM（die 0、4MiB）。CAPS b3版のみ | RW、queue経由。内容は電源投入時に不定で消去しない。CAPS b3のない版ではアクセスエラー |
| その他 | 未実装 | アクセスエラー |

パレットwordはbits11:8 R、7:4 G、3:0 B。CPUの低byte/高byte書込みはshadowだけに作用する。高byteのbits7:4は無視し、読出し0。

009000–0093FFはABI 0.4までのOAM（64個）の位置で、ABI 0.5では未実装（アクセスエラー）。OAMは256個に増やした際、palette/waveの位置を変えずに済むよう00A000へ移した。

## スプライト8byteレコード

| byte | 内容 |
|---|---|
| 0 | X bits7:0 |
| 1 | X bits9:8をbits1:0、残り予約0 |
| 2 | Y bits7:0 |
| 3 | Y bits9:8をbits1:0、bit2 enable、3 size16、4 Hflip、5 Vflip、6 behind、bit7予約0 |
| 4 | tile bits7:0 |
| 5 | tile bits9:8をbits1:0、paletteをbits5:2、bits7:6予約0 |
| 6 | 予約0 |
| 7 | 予約0 |

予約bitへの書込みは無視、読出し0。disabledの内容も保持する。COMMIT以外ではactiveへ影響しない。

ライン選択に要るY・enable・size16をbyte 2–3（word 1）に集めたので、選択回路は1件1wordの読出しで判定できる（[スケジュール](memory-access-schedule.md)）。ABI 0.4まではフラグがbyte 6にあった。

## 物理割当て（合成前の具体案）

9bit/18bitモードの余剰ビットを無理に使わず、8/16/32bitモードで数える。小領域を別RAMに分割するとブロック数が増えるため、同じ行にあるshadow/activeは1個の配列へ明示的に配置する。

| 用途 | 構成/個 | 個数 | 利用payload | 8/16/32bit構成の未使用容量 | ポート |
|---|---|---:|---:|---:|---|
| Pattern | 2048×8 | 16 | 32768 B | 0 B | SP、systemでCPUと描画を時分割 |
| Map | 2048×8 | 2 | 4096 B | 0 B | SP、上位/下位byte laneを独立write |
| OAM shadow＋active | 1024×16 | 2 | 4096 B | 0 B | SP、2048word（shadow 0..1023、active 1024..2047）、4word/sprite |
| Palette shadow＋active | 1024×16 | 1 | 1024 B | 1024 B | SP、systemで色変換 |
| Wave shadow＋active | 2048×8 | 1 | 1024 B | 1024 B | SP、audio優先の独立仲裁 |
| Line A/B | 1024×16 | 2 | 1280 B | 2816 B | TDP、system RW/pixel R |
| Command queue | 1024×16 | 1 | 256 B | 1792 B | SP、32 entries×64bit、4word逐次転送 |
| Audio FIFO | 512×32 | 1 | 64 B | 1984 B | SDPB、16 stereo samples使用 |

計26ブロック、利用44608 B、モード上の未使用8640 B。各ブロックのparity相当2048bitは別枠で未使用。物理使用量26×18432bitで、byte payloadの単純合計とは一致しない。256スプライト化でOAMが1→2個になり、予備ブロックはなくなった。実装の使用数はホスト版24→25/26、art ROMを含むデモ版25→26/26の見込みで、合成で確認する。

Line word: bits11:0 RGB444、bit12 BG_SOLID、bit13 SPR_CLAIMED、15:14予約。pixel側はRGBだけ読む。スプライトのbehind判定と小番号優先のための2bitをRGBと同じRAMに保持し、別の画面幅フラグ配列を作らない。

commandの64bit descriptorは`opcode8 | address24 | length16 | data8 | flags8`の情報量。メモリ格納順はword0 bits15:0から。キューに公開するwrite pointerは4word全てを書いた後だけ進める。1件の取得も4wordを揃えてから実行。CPUバス16 system cycles/アクセスに対し、最大4word書込みと4word取出しを収容する。CPU向けFULLには組立中の予約entryも含める。

OAM/paletteの16bit RAM byte書込みは最大3 cycles（read/response/write）の不可分RMW。描画読出しとの間に割り込ませない。mapは実機修正後の2本のbyte lane構成でRMWを使わない。同一アドレスread-during-writeのデバイス依存値に依存しない。

【実測】P1-06でOAM 1個版の25ブロックを推論wrapperで配置配線し、SP 22・SDPX9B 1・DPB 2の計25/26へmapされ、LUT/FF展開なし、system/pixel 2 clockのDPBでSTA違反0を確認した（[BSRAM評価](bsram-evaluation.md)）。C版DPBはread-before-writeを受け付けないため、line bankのsystem portは書込み中rdataを保持するnormal modeとした。全VDP実装時の配置・Fmaxは再評価する。音声FIFOのデータRAMはBSRAMでも、Gray pointer・同期器はFFを消費する。

## 起動

巨大RAM配列へ非同期リセットを記述しない。実装ではsystem FSMから通常の同期write portを使い、pattern全16bank、mapの両byte lane、OAMの全2048word、paletteのshadow/active/未使用word、waveの物理領域を並列に0へ書く。VRAM消去は2048 system cycle。キュー/FIFOはpointer resetで空にする。

line bankも両方の512wordを0へ書く。pixel側のread gateが停止したことをsystem側へ同期してから消去を開始し、systemだけのreset時にも走査との衝突を防ぐ。VRAM/line消去完了はpixelへ2段同期し、それまではline要求・走査readを止め、RGBを黒に保つ。

STATUS.INIT_DONEはVRAM消去完了で1。初期化中のVRAM_WRITE/READ_REQUEST/COMMANDはNOT_READYで拒否し、queueやアドレスを進めない。デモはINIT_DONEをpollしてから書き込む。CPU接続topはVRAM/line初期化、pixel domain ready、最初のline0準備を待ち、その後8回のPHI2パルスを送ってからCPU resetを解除する。

paletteは黒、OAMはdisableが初期状態。6ch音源の起動muteは音源統合時の課題であり、現在の独立した固定テスト音を停止する機能ではない。
