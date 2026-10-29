# RTL

合成対象のSystemVerilog。仕様は[docs](../docs/README.md)、全体の構成は[アーキテクチャ](../docs/architecture.md)を参照。board topと評価用topは`boards/tang-nano-9k/`にある。

| Directory | 責務 |
|---|---|
| core | レジスタ窓、command queue・engine、raster scroll、system domainの統合（`kagura_core`）、デモsequencer |
| vdp | VRAM、背景・sprite描画、line display（拡大・CDC）、VDPの統合（`kagura_vdp`）、試験用映像source |
| audio | 音源レジスタ・snapshot、6ch＋PCM合成器、PCMの先読みと制御、HDMI向けの音声転送 |
| memory | BSRAM wrapper、非同期FIFO、PSRAM controller・PHY・仲裁・read path |
| hdmi | 音声packet scheduler、TMDS encoder・packet assemblerの置換実装、HDMI streamのwrapper |
| bus | W65C02S adapter、SPI/QSPI adapter |
| boot | ROM-less boot（SPI Flash reader、image検査、boot窓、controller） |
| platform | Gowin用のPLL/CLKDIV/GSRとOSER10 serializer |

## 主なmodule

| module | 内容 |
|---|---|
| `core/kagura_core` | registers、queue、engine、VRAM、背景・sprite描画、音源を接続する。CAPS b3のときPSRAM controller・仲裁・PCMを生成し、PHY境界（`psram_*`）だけを外へ出す |
| `core/kagura_registers` | 32 byte窓とEXT。要求を受けて2 cycle後に応答し、command型の書込みは全検査が済んでから投入する。拒否時は何も変えない |
| `core/kagura_command_queue` | 64bit descriptor×32を分散RAM（32×64）に格納する。4cycle staging後に公開し、descriptor単位で読み出す |
| `core/kagura_vram_engine` | descriptorを順に実行する（WRITE/READ/FILL/FENCE/COMMIT/AUDIO_COMMIT/COPY） |
| `core/kagura_raster_scroll` | active表を引いて、各ラインの背景scrollを決める |
| `core/kagura_abi_pkg` | `tools/gen-registers.ps1`の生成物。合成topには含めず、`tb_register_abi`がregister RTLとの一致を照合する |
| `core/kagura_demo_sequencer`、`kagura_demo_art` | deprecatedの`demo`構成で、CPUの代わりにレジスタ窓を操作するsequencerと、そのtile art（`tools/gen-demo-art.py`の生成物） |
| `vdp/kagura_vram` | pattern 19 bank（末尾の空きにBG上位bit表を同居）、map 2 lane、OAM・palette（RMW）、wave。描画器への占有許可とcommand portを管理し、起動時に全RAMを0にする |
| `vdp/kagura_bg_renderer` | 背景1ライン。fetchとemitの2段で1画素1 cycle |
| `vdp/kagura_sprite_selector`、`kagura_sprite_row`、`kagura_sprite_renderer` | 256件のOAM走査と16件の選択、pattern取得と優先順位付きの合成 |
| `vdp/kagura_line_display` | pixel domainの走査、line bankの所有権交換、拡大、VBlank・underrun通知 |
| `audio/kagura_audio_registers` | 音源index registerのshadowとAUDIO_COMMITのsnapshot。PCM版はPCM registerも持つ |
| `audio/kagura_audio_synth` | 6ch（＋PCM 2ch）の合成。L/R各1個の乗算器を時分割で共有する |
| `audio/kagura_pcm_prefetch`、`kagura_pcm_control` | PCMの先読みbuffer（各ch 32 byte）、one-shot・loop・underrun・timeout、公開のPREPARE/STOP/CLEAR |
| `audio/kagura_audio_transport` | system→pixelのFIFOと48kHzのtick、prefill・mute・underflow |
| `memory/kagura_hyperram_ctrl`、`kagura_hyperram_phy_gowin` | HyperBus型PSRAM 1 dieのcontrollerとGowin primitiveのPHY |
| `memory/kagura_psram_arbiter`、`kagura_psram_read_path`、`kagura_psram_byte_bridge`、`kagura_psram_read_cdc` | host/PCMの仲裁、PCM側のbyte→word変換とCDC |
| `hdmi/kagura_audio_packets` | 固定48kHzの音声packet、ACR、InfoFrameの選択 |
| `hdmi/kagura_tmds_channel`、`kagura_packet_assembler` | hdl-utilの同名moduleのpipeline化した置換実装 |
| `hdmi/kagura_hdmi_stream_eval` | 音声転送と生成HDMI core（`build/generated/kagura_hdmi_stream.sv`）の接続 |
| `platform/kagura_nano9k_clocks` | 2個のrPLL、CLKDIV、chip GSR |
| `platform/kagura_gowin_serializer` | OSER10×4（GSRでreset解除） |

`vdp/kagura_line_banks`、`vdp/kagura_test_pattern`、`hdmi/kagura_hdmi_eval`、`memory/kagura_ram_sdp`は単体の評価・試験用で、現在のboard topでは使わない。

## 記述上の規約

- RAMは`memory/kagura_ram_*`のwrapperで推論させる。巨大な配列に非同期resetを書かず、起動時の消去は通常のwrite portで行う。
- 54MHzで余裕を確保するため、高fanoutの信号やBSRAMの出力はregisterで受けてから判定に使う。前の要求からの間隔（2 cycle以上）を前提にした先行計算は、simulation用のassertionで前提を検査する。
- PSRAMのpadへ出る信号はregister出力にする（組合せ出力のglitchが実機で問題になった）。
- Gowinは`SYNTHESIS`を定義しないので、simulation専用のcheckは`synthesis translate_off/on`で囲む。
