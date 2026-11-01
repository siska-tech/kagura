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

## 比較方法

同じRP2040 125 MHz、MicroPython v1.26.0、ABI 0.6、CAPS 0x5B、
QSPI 5 MHz / bulk Link、同じ美咲font・widget・テーマ・sample数を使う。
両profileともSDKのViperは有効。`runs`はbackendのglyph8だけを無効にし、
`glyph8`は新経路を使用する。従来方式を1巡測定後、新経路の継続試験へ移る。
比較のためのcacheや独自transportは追加しない。

初回Galleryのtile buffer CRC32は、glyph8 / runs / Pythonがすべて**2036752175**。
[比較ログ抜粋](kagura-ui-logs/phase2-short-comparison.txt)。
各32 samples、cycle 0のframe時間:

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
python tools/kagura-ui-standard.py --port COM7 --expected-serial E663A837CB73512D \
  --samples 32 --cycles 2 --seconds 3600 --log build/ui-phase2/one-hour.txt
python tools/summarize-kagura-ui.py build/ui-phase2/one-hour.txt --require-seconds 3600
```

実行中は他のUSB端末を同じCOMへ接続しない。終了時はAppとfontを閉じ、consoleへ復帰する。
sample配列は固定長、ログはPCへ逐次書込み。heap開始値は初回step後のGCで取得する。
1時間判定にはms tickを使う。us tickはRP2040で短周期に周回するため長時間の終了判定には使わない。
集計toolは各巡のp50/p95/p99のmin/maxを保持し、平均して全期間のpercentileとは呼ばない。
GC回数・実allocation回数は未取得のままにする。

## 検証状況

- UI 30件、Framebuffer 89件、既存SDK/デモのPC回帰がPASS。
- 公式MicroPython v1.26 ARM compilationがPASS。CPython/unix VMのCRC3状態も一致。
- `ui_glyph_runtime.py`の288操作もCPython/unix VMで一致（rolling CRC 2456019654、buffer CRC 1936776583）。
- WindowsにC compilerがないためSTARFALL oracleはWSLで実行しPASS。
- 実機UF2 SHA256は`188f120b9ef0e557e4ce77c9a11abf6430140c5b1cd81605fecc0fc9d2e97b17`。
  text 426412 B、data 0 B、bss 5128 B。Phase 1修正版よりtextが416 B増加。
- 導入前に2 MiBのFlashをバックアップし実機SHA256と照合。
  UF2 payloadは`0x10000000 <= address < 0x10068200`のみ。
  保存領域`0x100a0000`以降は導入後もbyte単位で不変（SHA256
  `7b07b001ee9349871cc3ffee956325fdbcf9067cb5d58ff15ceb20b67ae0b873`）。
- 1時間の継続試験は進行中。最終時間・heap・復帰結果は完走後に記録する。

UART/HID、Pico 2/2 W、物理電源断からの再投入は未検証。
複数damage領域、glyph cache、dirty gap結合のUI向け設定は今後のPhase 2候補とする。
