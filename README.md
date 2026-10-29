> **1,200タイル対応の実験用リポジトリ**
>
> 元リポジトリ `Kagura` の `e909cacd87c207383924b8c15313147940fc14bc` から分岐。
> 公開タイル数を1,200枚へ拡張し、ホスト4構成のP&R/STA、RTL 61試験、SDK 122試験に合格しました。Picoで全量読戻し・PCM併用1時間連続動作・文字キャッシュ1072枠を数値検証済みです。720p・Picoホストの追加領域・境界BG／sprite・反転・palette・左右PCMもユーザーの目視・聴感確認に合格しました。
> 実機の結果は[数値検証](docs/tile-1200-stage3.md)。進捗・再現手順は[実験記録](docs/tile-1200-experiment.md)、設計案は[調査書](docs/tile-1200-feasibility.md)を参照。

# ![KAGURA-9](docs/images/logo.png)

Kinetic Audio & Graphics Unified Rendering Architecture。
Tang Nano 9K（GW1NR-9）1枚で動く、外部ホスト制御のHDMIビデオ・サウンドチップです。ホストは32 byteのレジスタ窓だけを操作し、FPGAが背景・spriteの描画、音源の合成、HDMI（映像＋48kHz音声）出力を行います。

![KAGURA-9のシューティングデモ。星空と惑星を背景に敵編隊と自機を表示](docs/images/demo-720p.png)

*720pデモのRTLシミュレーション出力（論理320×180を1280×720へ4倍表示）。実機モニターの撮影ではありません。[画像の生成元](docs/images/README.md)。*

デモ動画（YouTube）: [KAGURA-9: Custom HDMI Video & 6-Channel Sound Chip](https://www.youtube.com/shorts/ZjfHmth6I0A)

![ブレッドボード上のRaspberry Pi PicoとTang Nano 9K。ジャンパ線でSPI/QSPIホスト接続し、Tang Nano 9KからHDMIを出力](docs/images/hardware-pico-tang-nano-9k.jpg)

*実機構成: Raspberry Pi Pico（SPI/QSPIホスト）とTang Nano 9K。配線は[Pico firmware](software/pico/README.md)を参照。*

## 仕様

| 分野 | 内容 |
|---|---|
| 画面 | 320×240（640×480p60へ2倍）または320×180（1280×720p60へ4倍）。bitstreamで選択 |
| 背景 | 1面、64×32 map、8×8 tile、1200 pattern（4bpp）、scroll、ライン別scroll表（8 entry） |
| sprite | 256個登録、16個/line、8×8・16×16、反転、behind |
| 色 | RGB444、16色×16 palette |
| 音源 | pulse 3、noise 1、wavetable 2。PSRAM版はPSRAM上のsigned 8bit PCM 2chを追加 |
| 音声 | 48kHz・16bitステレオ（HDMI） |
| メモリ | VRAM約49KiB（BSRAM）。PSRAM版は内蔵PSRAM 4MiBを公開し、PCM・COPYの元に使う |
| ホスト | SPI/QSPI（Raspberry Pi Pico等）、またはW65C02S（3.3V、3.375MHz） |
| レジスタABI | 0.6（[レジスタ仕様](docs/register-map.md)） |

## 現在の状態

- **実験ABI 0.6の数値検証**: ホスト4構成のSRAM起動・境界検査、全1200枚の読戻し、PCM併用1時間連続動作、文字キャッシュ1072枠。詳細は[第3段階](docs/tile-1200-stage3.md)。[720pの目視・聴感](docs/tile-1200-visual.md)も確認済み。
- **拡張前ABI 0.5の過去の実機記録**: 480p/720pの映像・音声（PCモニターとテレビの2機種）、内蔵sequencerのシューティングデモ、Raspberry Pi PicoからのSPI/QSPI制御（5MHz）、PSRAMへのupload・COPY・PCM 2chの連続再生。
- **simulationのみ**: W65C02Sバス接続、SPI FlashからのROM-less boot（Flash読出しとimage検査は実機確認済み）。
- **未実施**: 480pや動きのある画面の目視、複数sink×ケーブルでの反復・長時間の互換性試験、実W65C02Sとの接続、SPI/QSPIの10MHz動作。

詳細と既知の制約は[検証状況](docs/validation-status.md)を参照してください。

FPGA standaloneの`demo`／`demo720`はdeprecatedです。Picoホスト上のデモ・診断を利用してください。旧ソースと過去の検証記録は残しますが、1,200タイル対応の受入対象から外します。

## はじめかた

1. [アーキテクチャ](docs/architecture.md)で全体とビルド構成を確認する。
2. [ビルド・テスト](docs/build-and-test.md)の手順でbitstreamを作り、SRAMへ書き込む。主な動作確認はPicoホストの`qspipsram`／`qspipsram720`構成で行う。
3. Picoから操作する場合は`qspipsram`（または`spi`/`qspi`）を書き込み、[Pico firmware](software/pico/README.md)の`diag`・`show`・`stress`を実行する。
4. 自分のホストから使う場合は[プログラミングガイド](docs/programming-guide.md)と[レジスタ仕様](docs/register-map.md)を読む。

```sh
bash tools/test-verilator.sh                 # RTL回帰（WSL/Linux）
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-design.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/gen-registers.ps1 -Check
```

文書の一覧は[ドキュメント案内](docs/README.md)にあります。

[MicroPythonドライバ](software/micropython/README.md)は、SPI/QSPI制御とUARTキーボード入力・HDMI REPL、REPL出力とアプリ画面の8×8日本語表示（美咲ゴシック）を提供します。導入方法と実機検証の残作業はリンク先を参照してください。

## リポジトリ

| path | 内容 |
|---|---|
| `rtl/` | RTL（core、vdp、audio、memory、hdmi、bus、boot、platform）。[RTL一覧](rtl/README.md) |
| `boards/tang-nano-9k/` | board top、CST/SDC、ピン一覧。[ボード資料](boards/tang-nano-9k/README.md) |
| `sim/` | SystemVerilog testbenchと参照モデル。[試験一覧](sim/README.md) |
| `spec/` | 機械可読のレジスタ定義と設計予算 |
| `software/` | 生成ヘッダ（C/ca65）、Pico host firmware |
| `tools/` | ビルド・生成・検査・書込みのscript |
| `docs/` | 仕様と検証の文書 |
| `third_party/` | 固定revisionのhdl-util/hdmi |

## ライセンス

オリジナル成果物はApache-2.0。第三者のRTL・フォント等は`third_party/`と各ファイルの記載に従います。[第三者IP方針](THIRD_PARTY.md)を参照してください。
