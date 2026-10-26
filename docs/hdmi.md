# HDMI出力

映像と48kHz音声をHDMIで出力する。固定のmode（640×480p60または1280×720p60）だけを扱い、EDID・DDC・CEC・HDCP・HPDは実装しない。

## 構成

protocol部は固定revisionの[hdl-util/hdmi](https://github.com/hdl-util/hdmi/tree/83b1c9543a91b776671a44e68e130f81cae437b7)（MIT OR Apache-2.0、Apache-2.0を選択）を基にする。上流のファイルは`third_party/hdl-util-hdmi/`に無改変で置き、`tools/prepare-hdmi-stream.py`がhashを確認してから派生ソース`build/generated/kagura_hdmi_stream.sv`を生成する。生成時に置き換えるもの:

| 置換 | 内容 |
|---|---|
| 音声入力 | 上流の`clk_audio`とsample wordを、FIFOからの`sample_valid/sample_data/sample_ready`に置き換える |
| `packet_picker` → `kagura_audio_packets` | pixel domainだけで動く固定48kHz/16bitステレオのscheduler。header/subはpacket_enableの端でregisterへ入れる |
| `tmds_channel` → `kagura_tmds_channel` | 8b/10b encoderをpipeline化（74.25MHz用）。上流と一定の遅れで同じ符号列 |
| `packet_assembler` → `kagura_packet_assembler` | counterで選ぶbit muxをshift registerにし、BCH更新の経路を短くする |

serializerは`rtl/platform/kagura_gowin_serializer.sv`（OSER10×4、10:1、LSB first）で、board topの`ELVDS_OBUF`から差動出力する。OSER10はchip GSRで4 lane同時にresetを解除する（[clockとreset](timing.md#reset)）。

## 映像timing

| 項目 | 640×480p60（VIC 1） | 1280×720p60（VIC 4） |
|---|---|---|
| pixel clock | 25.2MHz | 74.25MHz |
| H: active+front+sync+back | 640+16+96+48=800 | 1280+110+40+220=1650 |
| V: active+front+sync+back | 480+10+2+33=525 | 720+5+5+20=750 |
| AVI InfoFrame | VIC 1、4:3 | VIC 4、16:9 |

RGB444の各成分は4bitを2回並べてRGB888にする（limited/full rangeの指定は上流のAVI設定に従う）。line displayの出力は内部遅延を見越してHDMI側の座標と同じcycleに揃えてある。

## 音声

- 48kHz、16bit、2ch。1 packetに最大4 sample。
- ACRはN=6144、CTS=pixel clockの1ms分（480pは25200、720pは74250）の固定値で、CTS pixel clockごとに1回送る。video/audioが同じ27MHzから作られるので、`Fs = F_TMDS × N / (128 × CTS) = 48000Hz`が長期的に成り立つ。外部の任意のsample clockへ切り替える場合はこの固定CTSを使えない。
- Audio InfoFrame、SPD InfoFrameも送る。
- sampleの受け渡し（FIFO、prefill、mute、underflow）は[音源仕様](audio-spec.md#hdmiへの受け渡し)。

packet帯域の目安（480p）: 音声packet 12000/s、ACR 1000/s、InfoFrameが各フレーム。各物理ラインのblankingに1 packet枠を置けば31500 slot/sで、平均の使用率は約42%。

## 検証

| 試験 | 内容 |
|---|---|
| `tb_tmds_channel` / `tb_tmds_pipeline` | 上流encoderとの一致（pipeline版は60万symbol、全lane・全mode） |
| `tb_packet_assembler` | 上流assemblerと毎cycleの出力一致 |
| `tb_audio_packets` | 2048 stereo pairのBCH・metadata・ACRを復号して照合 |
| `tb_hdmi_stream` / `tb_hdmi_stream720` | TMDS/TERC4を復号し、partial-group reset後の1024 stereo pair、ACR（CTS）、AVI（VIC・aspect）、平均48kHzを確認 |
| `tb_serializer_reset` | OSER10のlocal RESETを使わない接続であること（GSRとprimitive内部はsimulation対象外） |

decoderはtestbench内の独立実装で、送信側の関数を写したものを唯一の基準にしない。

## 実機の互換性

確認済みのsink: MSI MAG 325CQRF-QD（PCモニター、480p/720pの映像・音声）、TOSHIBA REGZA 32S5（テレビ、480p/720p）。TCL製テレビの1台はSipeed公式のDVIサンプルでも無信号で、原因は未特定。複数sink×複数ケーブルの反復・長時間試験は[実機試験](hardware-test.md)で管理する。TMDSの電気特性・規格適合は計測していない。これはHDMIの商標・認証を得たものではない。
