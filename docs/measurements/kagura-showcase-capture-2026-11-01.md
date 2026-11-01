# KAGURA-9 live showcase: HDMI capture

2026-11-01 JST。Picoの通常MicroPython v1.26.0（既存fw-ABC）、RP2040 125 MHz、
QSPI 5 MHz、480p FULL+PSRAM、CAPS 0x5b、GC有効。デモはARMv6-M `.mpy`を
`mpremote mount`で読み、soft reset後に`showcase.run(loops=1)`を実行した。
ユーザー承認による既存MicroPythonへの復元後の録画で、録画作業中のFlash/FPGA変更はない。

## 収録

- UGREEN 15390のDirectShow映像と同機器のHDMI音声だけを使用。Webカメラ・PCマイクは使っていない。
- 720×480 YUYV422、指定60000/1001 fps。原本はH264 CRF15/veryfast + PCM stereo 48 kHzのMKV。
- デバイス初期画面と待機、末尾黒画面を除き、原本13.397〜265.899秒を採用。
- 配布MP4: 252.502秒（約4分13秒）、81,718,784 B、H264 CRF17/medium、640×480・4:3・59.94 fps。
- HDMI音声はAAC 192 kb/s・48 kHz stereo。元のダイナミクスを保ち、音量だけ+13 dB。
  完成動画の平均-22.5 dBFS、最大sample -2.0 dBFS。無補正PCMは原本に残す。
- FFmpegの全編デコードはエラーなし。スライド、描画4種、STARFALL、桜吹雪、終了画面の代表フレームを目視確認。
- FFmpegの原本タイムスタンプ変換はdrop_frames=20/dup_frames=0を報告。capture buffer overflowの警告はなかった。
  信号タイミングや色再現・音声同期の厳密な測定ではない。

動画は`build/recordings/kagura9-showcase-20261101.mp4`、原本・コンタクトシートも同ディレクトリに保存。
大容量の動画はGitに含めず、外部へのアップロードも行っていない。

## 録画中の実機結果

- STARFALL: 1,566描画COMMIT/40.030404秒（約39.12更新/秒）、2,398 simulation tick、積み残し最大1tick。
  準備128,851 µs、最大16 sprite/line、sprite overflow/audio fault/ERROR_CODEすべて0。
- 桜吹雪: 40秒に2,369更新、2,368 COMMIT確認、59.20 displayed/s。
  sprite overflow/PCM underrun/line underrun/ERROR_CODEすべて0。
- 最後まで1周し、`CAPTURE_COMPLETE`後に正常停止。デバイスログを併記する。

[録画中のデバイスログ](kagura-showcase-capture-device-2026-11-01.txt)。
単体性能や以前の通常速度測定と区間・heap配置が異なるため、数値を置き換えない。
通常速度の2周目に38,400 B framebufferの連続確保が失敗する問題は残っている。
短縮2周の合格と区別し、録画および既定動作は1周とする。
