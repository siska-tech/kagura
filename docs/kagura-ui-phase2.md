# KAGURA-UI Phase 2 — ビットマップ文字の高速描画

PR #50を取り込んだmain `41669a2`から開始した。未マージPRは開始時点で0件。
専用ブランチは`feat/kagura-ui-phase2`。Phase 3のエディタ機能には進んでいない。

## 変更と判断

通常配置のPhase 1基準値ではLabelのframe中央値が約25 ms、flushは約1.9 ms。
日本語fontは1行ずつ複数のfill_rectで描画しており、通信以外の負担が大きかった。
既存Viperの8×8 glyph kernelを使う`TileFramebuffer.glyph8()`を公開し、
UIから完全にclip内に入る字形だけを渡す。SDKの描画・dirty・転送処理の重複実装はしない。
部分clipや未対応backendは従来の行単位描画を使う。

追加のframebufferやglyph cacheは持たない。内蔵ASCII、任意bitmap、日本語のbit順は
MSB左端で統一し、Python/native/独立PC surfaceを比較する。
既存API、RTL、ABI、資源所有権、flushのFENCEと失敗時dirty保持は変更しない。
allocation回数は計測していないためallocation-freeとは主張しない。

既存`text()`はmainと同じ実装を維持する。毎文字を新しい公開APIへ迂回させる案は、
公式Unix VMでASCII 15文字の中央値が17→36 µsとなったため採用しなかった。
元実装維持後は旧参照17/19 µs、新側18/17 µsだった（2巡、各256 samples）。
これはUnix VMの確認値であり、RP2040の値ではない。公開API間の共通化より既存の高速経路を優先し、
両入口が同じ既存glyph kernelを使う構造とした。

## 比較方法

同じRP2040 125 MHz、MicroPython v1.26.0、ABI 0.6、CAPS 0x5B、
QSPI 5 MHz / bulk Link、同じ美咲font・widget・テーマ・sample数を使う。
両profileともSDKのViperは有効。`runs`はbackendのglyph8だけを無効にし、
`glyph8`は新経路を使用する。従来方式を1巡測定後、新経路の継続試験へ移る。
比較のためのcacheや独自transportは追加しない。

初回Galleryのtile buffer CRC32は、glyph8 / runs / Pythonがすべて**2036752175**。
[比較ログ抜粋](kagura-ui-logs/phase2-short-comparison.txt)。
各32 samples、cycle 0のframe時間:
percentileは既存benchmarkと同じ`floor((N-1)*p/100)`番目のsort値であり、
32 samplesのp99を長期の最悪応答時間とは解釈しない。

| workload | runs µs p50 / p95 / p99 | glyph8 µs p50 / p95 / p99 |
| --- | --- | --- |
| 静止 | 458 / 478 / 480 | 532 / 549 / 553 |
| Label | 25436 / 27063 / 27760 | 16827 / 17054 / 17436 |
| Button | 57802 / 64955 / 74373 | 32272 / 33167 / 45814 |
| focus | 79604 / 93971 / 95704 | 40351 / 42670 / 45119 |
| Panel移動 | 13408 / 15191 / 16603 | 13324 / 13711 / 13744 |
| List scroll | 45117 / 55995 / 56874 | 23690 / 24681 / 35693 |
| 画面切替 | 60656 / 139201 / 139458 | 51824 / 84836 / 85179 |

Label中央値は約34%、focusは約49%短縮。静止・Panel等の改善は主張しない。
同じcycleのdirty tile数とpayload byte数は全workloadで一致し、静止は転送ゼロ。
これはCPU側の文字描画の比較であり、HDMI refresh FPSの測定ではない。
長いcallbackによる停止や、pattern RAM更新の非原子性は変わらない。

## 再現

UIとSDKを同じソースの凍結manifestでビルド・配置し、通常のHDMI consoleを起動する。
`glyph8`を含まない旧firmwareはtoolが拒否する。toolは指定USB serialを検査し、
ファイルやfirmwareを書き換えない。通常のraw REPL経由でアプリのソースだけを送る。

```sh
python tools/kagura-ui-standard.py --port <PORT> --expected-serial <USB_SERIAL> \
  --samples 32 --cycles 2 --log build/ui-phase2/comparison.txt
python tools/summarize-kagura-ui.py build/ui-phase2/comparison.txt
python tools/kagura-ui-soak.py --port <PORT> --expected-serial <USB_SERIAL> \
  --samples 32 --seconds 3600 --log build/ui-phase2/quiet-hour.txt
```

比較toolの実行中は他のUSB端末を同じCOMへ接続しない。終了時はAppとfontを閉じ、consoleへ復帰する。
sample配列は固定長、ログはPCへ逐次書込み。heap開始値は初回step後のGCで取得する。
1時間判定にはms tickを使う。us tickはRP2040で短周期に周回するため長時間の終了判定には使わない。
集計toolは各巡のp50/p95/p99のmin/maxを保持し、平均して全期間のpercentileとは呼ばない。
GC回数・実allocation回数は未取得のままにする。

長時間toolは開始後にUSBを閉じ、Pico内の`ui_benchmark.Summary`へ集計する。
保持するのは7 workloadの件数・転送合計・各巡percentileのmin/max、heapのfirst/last/min/max、
完了結果のみ。履歴は蓄積せず、未知のworkloadは拒否する。
終了後にsoft resetなしで回収し、全巡の件数、経過時間、完了flag、console復帰、静止の転送ゼロを検査する。
結果はlogと同名の`.json`へ保存する。Picoの給電は維持すること。
PCのstandby等で回収が遅れても、Picoが再起動して完了flagを失えば成功とは扱わない。
回収前のCtrl+Cは試験を中断する。

## 検証状況

- UI 33件、Framebuffer 89件、既存SDK/デモのPC回帰がPASS。
- host側timeout時はsoft resetせず現在のループを中断してからAppを閉じる。
  模擬timeoutでcleanup順序と分割UTF-8ログを検証した。実通信障害の再現試験ではない。
- 公式MicroPython v1.26 ARM compilationがPASS。CPython/unix VMのCRC3状態も一致。
- `ui_glyph_runtime.py`の288操作もCPython/unix VMで一致（rolling CRC 2456019654、buffer CRC 1936776583）。
- WindowsにC compilerがないためSTARFALL oracleはWSLで実行しPASS。
- 実機UF2 SHA256は`188f120b9ef0e557e4ce77c9a11abf6430140c5b1cd81605fecc0fc9d2e97b17`。
  text 426412 B、data 0 B、bss 5128 B。Phase 1修正版よりtextが416 B増加。
- 導入前に2 MiBのFlashをバックアップし実機SHA256と照合。
  UF2 payloadは`0x10000000 <= address < 0x10068200`のみ。
  保存領域`0x100a0000`以降は導入後もbyte単位で不変（SHA256
  `7b07b001ee9349871cc3ffee956325fdbcf9067cb5d58ff15ceb20b67ae0b873`）。
- USB非依存の1時間試験を完走。全件の回収結果と最終FW受入は下記に記録する。

長時間計測用UF2は上記`188f...`。最終UF2は
`9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c`で、
text 426540 B、data 0 B、bss 5128 B、書込み終端は`0x10068300`未満。
差は既存ASCII `text`をmainと同じ実装へ戻した点。`glyph8`のソースは計測版と完全一致し、
今回のsoakはcustom bitmap fontを使うため`text`経路を通らない。
最終UF2の実機短時間検証は長時間試験終了後に実施し、下記のとおり合格した。

### 最初の連続試験の中断

USB逐次log方式は386巡を完了し、最後のheap記録は2575977 ms（約43分）、
GC後freeは全386巡で140432 Bだった。次の巡の途中でWindows側の
`ClearCommError failed`（PermissionError 13 / Windows error 22）により収集が中断した。
ユーザーから「テストPCの電源ケーブルを抜き、standbyへ入った」との説明を受けた。
1時間完走とは扱わず、GUI不具合による中断とは区別する。

COM7を開き直し、soft resetなしで中断処理を通すことでconsoleへ復帰した。
paused=False、attached=True、FPGA check_errors()は成功。
同じsessionからCPU 125 MHz、SCK 5 MHz、4 lanesも取得した。
この経験を踏まえ、USB接続の維持を必要としないPico内集計方式を追加した。
短時間の実機試験では5巡・2091 msの全groupを回収し、完了flagとconsole復帰を確認した。
この短時間結果を長期安定性の証明には使わない。

[中断時の逐次log（gzip）](kagura-ui-logs/phase2-standby-interrupted.txt.gz)を保存した。
展開後826220 B、SHA256 `f168975f5164ba9141d78445e37a6ba7d3fecb412915915439a0764a115186f2`。

## 1時間のPico内集計による受入

[全結果JSON](kagura-ui-logs/phase2-hour.json)、[回収log](kagura-ui-logs/phase2-hour.txt)。
開始2026-11-01 12:42:05 UTC、USBを閉じた時刻12:42:08 UTC、回収終了13:42:38 UTC。
Picoの計測値は**3601176 ms、537巡、120288 step**。
各7 workloadについて537 group × 32 samples = 17184 samplesが揃い、欠損groupはない。
完了flag=True、error=None、console paused=False / attached=True、FPGA check_errors()成功。

| heap観測点 | free B |
| --- | --- |
| 各巡GC後 first / last / min / max | 137664 / 137664 / 137664 / 137664 |
| run開始（集計表の初巡確保前） | 140544 |
| run終了 | 137760 |

開始→終了のfree差2784 Bには、初巡に確保して保持する7 workloadの固定集計表等を含む。
同じ測定点である各巡GC後は537巡すべて一定。allocation回数・自動GC回数は未取得で、
allocation-freeや任意アプリのleak-freeを保証する結果ではない。

静止17184 samplesは**転送0 tiles / 0 B**。
全workloadの合計は22310687 tiles / 713941984 pattern payload B（wire framing等を含まない）。
各巡のLabel frame p50は16768～16881 µs、p99は17083～17357 µs。
focus p50は40256～40589 µs、p99は43584～47761 µs。
いずれも各32 samplesのpercentile範囲であり、全期間のpercentileではない。
Buttonのcountが増えると文字数が増えるため、Button時間の後半増加をそのまま性能劣化とは扱わない。
frame/flush/合成event→invalidateの全p50/p95/p99範囲はJSONに保存した。
物理USB到着からの遅延測定ではない。

## 最終UF2の受入と残る範囲

[HDMI Gallery](images/kagura-ui-phase2-gallery.png)、[実機log](kagura-ui-logs/phase2-final-device.txt)。
最終UF2 `9ebfa459...`へ更新した後、以下を確認した。

- glyph8境界288操作のPython/native一致（rolling 2456019654、buffer 1936776583）。
- 日本語Gallery CRC32 2036752175、HDMIの字形・配置を確認。
- USB Enter/Tab/Shift+Tab/Escape、Count 2、queue drop 0、押下の解除。
- Second screen訪問1回→BACK、元rootへ復帰し、同じFramebuffer instanceを継続使用。
- console復帰、`machine.reset()`後も通常の凍結UI・現行consoleが起動、last_error=None。
- 最後に保存領域全体のSHA256が導入前の`7b07b001...`と完全一致。Phase 2で保存ファイルの変更なし。
- App/Theme/StdinInput/Gallery treeは4112 B、初回step後のUI差分は45008 B。
  module・Gallery関数定義・font openは測定前に済ませ、各値はGC後差分。起動中freeは140832 B。
  計測中のprintを避けて同じ関数内で差分を取り、consoleの表示更新を混ぜないようにした。
- 既存ASCII 15文字の通常`fb.text()`もViperで完了（buffer CRC 1619569713）。

1時間試験完了後、追加ASCII比較用にSDKクラスへ参照関数を一時追加する補助スクリプトで
USB応答が停止した。通常のCtrl+Cも受信できず、対象deviceのWindows restartはOS権限で拒否。
ユーザーのUSB抜き差し後、標準framebuf描画、通常のfb.text、最終Galleryは正常だった。
この補助診断の停止原因は未特定で、RP2040のASCII比較時間は取得できなかった。
公開GUI・計測toolはこのクラス変更を行わず、実験的なVM変更も前提にしない。
1時間試験はそれ以前に完走・回収済みであり、補助診断とは分けて記録する。

Pico 2/2 W、UART/HID、物理電源断からの再投入は未検証。
glyph cache・複数damage領域・dirty gap結合は次のPhase 2候補で、Phase 3へは進んでいない。
複数damage領域は後続の[damage rectangle記録](kagura-ui-damage.md)で実装した（PC検証のみ）。
