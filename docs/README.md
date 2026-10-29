# ドキュメント案内

初めて使う場合は[アーキテクチャ](architecture.md)で全体を把握し、[ビルド・テスト](build-and-test.md)と[検証状況](validation-status.md)を確認する。

## 使う

| 文書 | 内容 |
|---|---|
| [アーキテクチャ](architecture.md) | 仕様の概要、ブロック構成、clock、ビルド構成とCAPS、LED |
| [プログラミングガイド](programming-guide.md) | ホストからの初期化・転送・sprite・COMMIT・音源・PCMの手順 |
| [レジスタ仕様](register-map.md) | ABI 0.5の直接窓、command、extended register（規範） |
| [メモリマップ](memory-map.md) | VRAM/PSRAMのaddress、pattern・map・palette・OAM・waveの形式 |
| [映像仕様](video.md) | 表示モード、背景・sprite、優先順位、COMMIT、ラスタIRQ・ラスタスクロール |
| [音源仕様](audio-spec.md) | 6ch音源、PCM 2ch、AUDIO_COMMIT、mixer |
| [ホストインターフェース](host-interface.md) | SPI/QSPIのピン・timing・transaction・flow制御 |
| [クロック・リセット・CPUバス](timing.md) | clock、CDC、reset、W65C02Sバス、STAの基準 |
| [ROM-less boot](romless-boot.md) | SPI FlashからのW65C02S起動（`phase2boot`） |

## 内部と根拠

| 文書 | 内容 |
|---|---|
| [メモリアクセススケジュール](memory-access-schedule.md) | 1ラインの描画上限、仲裁、line bank、VBlankの時間 |
| [PSRAM](psram.md) | PSRAM controller・PHY・仲裁、COPY、物理層の設定 |
| [HDMI出力](hdmi.md) | hdl-utilからの派生、timing、音声packet、ACR |
| [RTL一覧](../rtl/README.md)、[試験一覧](../sim/README.md) | moduleとtestbench |
| [ボード資料](../boards/tang-nano-9k/README.md)、[ピン一覧](../boards/tang-nano-9k/pin-inventory.csv) | Tang Nano 9Kのピン・ヘッダ・回路図の照合 |

## 開発・検証

| 文書 | 内容 |
|---|---|
| [ビルド・テスト・書込み](build-and-test.md) | simulation、生成、Gowinビルド、SRAM/Flash書込み、CI |
| [1,200タイル実験](tile-1200-experiment.md) | 実験用リポジトリの段階・検証結果・次の作業 |
| [検証状況と既知の制約](validation-status.md) | 確認済みの範囲、資源・タイミング、制約、残作業 |
| [実機試験](hardware-test.md) | HDMI互換性・連続動作の手順と記録表、機材 |
| [Pico host firmware](../software/pico/README.md) | 配線、コマンド、実機確認の記録 |
| [MicroPython driver / HDMI REPL](../software/micropython/README.md) | SPI/QSPIドライバ、自動検出、UARTキーボード入力、REPL出力・アプリの8×8日本語表示、導入・受入手順 |
| [出典](sources.md)、[第三者IP](../THIRD_PARTY.md) | 一次資料と外部ソース |
