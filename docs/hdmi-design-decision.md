# HDMI Design Decision / ADR-001

## 判断

継続実装ではpixel /525消費案から、systemの48kHz producerをFIFO経由で4sampleずつpacketへ送る方式を採用した。固定N/CTSの前提は維持し、原版audio CDCを除去した。詳細と検証範囲は[音声packet統合評価](audio-packet-integration.md)。

【設計】**hdl-util/hdmiのプロトコル部を第一候補として評価し、Gowin serializer・出力・audio受け渡しを明示的な境界で移植する。** 最終採用は単体合成/STA/音声復号/実機試験の後。DVI-only構成は比較測定用であり、最終仕様の代替ではない。

| 案 | 根拠 | 長所 | リスク / 判断 |
|---|---|---|---|
| hdl-util/hdmi | 音声packet/ACR/InfoFrame実装をソース確認。MIT OR Apache-2.0 | 機能の出発点がある、同じコアでDVI差分測定 | serializerの条件分岐、sample CDC、reset、Gowin合成対応を修正評価。第一候補 |
| tn_vdp v2 9Kから移植 | topでDVI_OUTPUT=0、16bit音声、OSER10/ELVDS系経路。READMEに音声動作報告 | 9Kへの接続方法の実例 | ADC入力やVDP依存を含む。root BSD-3-Clauseを全依存へ適用できない。参考/差分調査に限定 |
| 固定mode独自実装 | VIC1/2ch/48kHzだけに限定可能 | 不要mux/動的機能を削れる | BCH/TERC4/packet/channel status/ACR/guard bandの検証量が大きい。既存コアの定量的不足が判明した場合に比較 |
| Sipeed SVO | 公式配線/PLL/出力例 | 物理層とDVI baseline確認 | 音声部の根拠にはならない |

参照: [hdl-util固定revision](https://github.com/hdl-util/hdmi/tree/83b1c9543a91b776671a44e68e130f81cae437b7)、[tn_vdp 9K v2](https://github.com/lfantoniosi/tn_vdp/tree/d7b80da83701a5e66ea078523a29b8cffd1f2833/fpga/tn_vdp_v2_v9918)。

## RTL読取りで判明した移植課題

1. `serializer.sv`ではSYNTHESIS側の分岐がGW_IDEより先にある。両方定義されるビルドでは意図しないXilinx OSERDESE2を選ぶ可能性がある。マクロの偶然の状態に頼らずGowin wrapperを明示選択する。
2. `packet_picker.sv`はclk_audioでsampleを保持しtoggleをpixelへ送る構造。FIFO backpressureの契約ではなく、4sample単位のdouble bufferを使用する。KAGURAではsystem→pixel FIFOとpixel側sample-valid受入へ置換し、既存のclk_audio境界をそのまま重ねない。
3. `audio_clock_regeneration_packet.sv`にはN算定とaudio→pixel時刻計測がある。common-referenceの固定modeでは固定N/CTSを使う案を評価し、packet書式は既存実装と照合する。
4. resetされない初期値依存state、Xを含むunused fields、可変packet type mux、array構文のGowin対応を単体検証。Xを物理出力の未定義動作として残さない。
5. tn_vdp topのsample二段レジスタを一般的なmulti-bit CDC保証としてコピーしない。9K v2と20K v3の資源値・回路を混同しない。

## 固定出力契約

640×480、H=640+16+96+48=800、V=480+10+2+33=525、negative HS/VS、pixel25.2MHzで60Hz。内部pixel counterはx=0..799/y=0..524、activeはx<640&&y<480。HDMI core側座標が別原点ならwrapperで1回だけ変換する。

RGB444→RGB888は各4bitを2回連結。試験用barはprimary/secondary/black/whiteを含み、左右端・上下端に1pixel markerを置く。音声テストは左右異なる整数周期音（例L=1kHz、R=500Hz）と連番sampleパターンの2種。

## ACRとpacket帯域

【算定】48kHz、N=6144、CTS=25200なら:

```text
Fs = F_TMDS * N / (128 * CTS)
   = 25200000 * 6144 / (128 * 25200) = 48000 Hz
```

同一27MHz referenceのPLLからvideo/audioを生成するため長期周波数比が一致する。pixel /525をpacket側sample tickに使い、深さ16 FIFOを4sample prefill後にconsume開始する。失速/PLL unlock時はリセットしmuteする。任意の外部sample clockへ切り替えた場合は固定CTSを流用しない。

4 stereo samples/packetなら12000 audio packets/s、1frame800 samples→200 packets/frame。仮に各physical lineのblankingへ1 packet枠を置ければ31500 slots/s。ACRを1msごと1000/s、AVI/Audio/SPD InfoFrameを各frame送って180/s、合計13180/sで平均枠の約42%。平均帯域だけではburst欠落を証明できないので、全525linesのpacket選択をsimulationで確認する。

1 packetは32pixel期間、前後guard bandとpreamble/control期間も必要。Hblank160pixelにただ32pixelずつ詰め込む設計をしない。既存coreのpacket_enable区間をデコードし、active videoとの重複、guard/preamble、BCH、checksum、sample-present、IEC60958 block192frames、16bit位置、左右順を検査する。ACR/InfoFrameとaudioが競合した最長待ちでもFIFOが尽きないことを確認する。

## 最初に測るもの

DVI bar構成とHDMI bar＋PCM構成を同一tool/part/optionsでbuildし、LUT/FF/BSRAM/DSP/PLL・各clockのsetup/hold WNS/TNS・未制約パス・bitstream生成を記録。audio有効時の差分を独立に報告。Fmaxの推測値を表へ入れない。初回目標はHDMI protocol＋PHY 2000 LUT/1500 FF/1 BSRAM以内（予算であり実測ではない）。audio FIFOはこのBSRAM1個に含む。

HDMI予算を超えた場合はpacket mux/固定parameter/reset/重複buffer/clock域を順に確認し、generic機能の定数化を先に行う。変更前後の復号一致と資源差分を保存。規格の必要packetや音声そのものを消して「成功」にしない。

## 互換性・未検証

v0.1は固定modeでEDID/DDC/CEC/HDCPを実装しない。HPD/5V/DDCの実配線・電圧は基板照合で確認し、未接続pinを仮定で追加しない。実機では音声対応HDMIモニター/TVを2機種以上、ケーブル2本、電源投入/抜挿/1時間連続を確認する。映像が出るだけでは音声合格にしない。

## ライセンス判断

hdl-utilはREADMEの`MIT OR Apache-2.0`と両LICENSEファイルを確認し、採用時はApache-2.0側を選ぶ案。元の著作権・NOTICEがあれば保持し、変更箇所を記録する。tn_vdpはroot BSD-3-Clause、SVO確認ファイルはISC相当の許諾文、Gowin生成ファイルはGowin copyright/all rights reservedの表記であり、リポジトリ全体を一括してApacheへ変更しない。ファイル単位監査が終わるまでコピーしない。これはソース利用条件の調査であり、HDMI商標・製品認証の取得を意味しない。
