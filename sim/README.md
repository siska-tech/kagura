# Simulation

`tests/`にSystemVerilogの単体・統合試験を置く。参照モデル、busのホストモデル、HDMI decoder、PSRAMのmodelはtestbench内（共有部品は`support/`）に実装している。WSL/Linuxのrootから`bash tools/test-verilator.sh`で全試験（57件）を実行する。手順・環境変数は[ビルド・テスト](../docs/build-and-test.md#シミュレーション)。

- 画像はPPM、音声はraw PCMとWAVとして`build/verilator/`へ保存する。期待値はRTLの出力からではなく、独立した参照モデルや仕様の値から作る。
- 波形は`KAGURA_TRACE`で指定したtopだけ、`support/kagura_trace.sv`をbindして出力する。
- 専用のC++ harness、`verilator/`・`reference/`ディレクトリは使っていない（空）。

## 試験一覧

| 分野 | 試験 | 内容 |
|---|---|---|
| HDMI | `tb_phase1_sources` | カラーバーと固定テスト音の2フレーム・746 stereo sample |
| | `tb_tmds_channel`、`tb_tmds_pipeline` | TMDSの復号、上流encoderとの出力一致（60万symbol） |
| | `tb_packet_assembler` | 上流assemblerとの毎cycle一致 |
| | `tb_audio_packets` | 2048 stereo pairのBCH・metadata・ACR |
| | `tb_hdmi_stream`、`tb_hdmi_stream720` | TERC4から1024 stereo pair、ACR、AVI、平均48kHzを復号 |
| | `tb_serializer_reset` | OSER10のlocal RESETを使わない接続（GSRは対象外） |
| | `tb_async_fifo` | 深さ16の満杯、1024語の順序・wrap、非空reset、空pop |
| メモリ | `tb_bsram_wrappers` | RAM wrapperのlatency、dual clock、byte RMWの不可分性 |
| | `tb_vram_init` | 全RAMにpoisonを入れてから、command readで0を確認 |
| host bus | `tb_w65c02_bus` | 要求回数、OE、read setup/hold、IRQ、reset解除、締切 |
| | `tb_spi_bus`、`tb_qspi_bus` | 10MHzのホストモデル、BUSY、中断、競合（`tb_host_bus.sv`） |
| | `tb_startup_cpu` | VDPの初期化とline 0の準備からCPU adapterのreset解除まで |
| register・queue | `tb_vram_core` | 公開registerの検査、領域境界、拒否時の副作用、FILL/FENCE、満杯、順序 |
| | `tb_register_abi` | 生成ABI packageとregister RTLのreset値・access可否 |
| | `tb_fill_timing` | 最大速度の連続要求でFILLの範囲検査が間に合うこと |
| | `tb_sprite_irq` | SPR_OVERFLOWの捕捉とclearの規則 |
| 映像 | `tb_vdp_frame`、`tb_vdp_frame720` | 背景の4フレーム全画素比較、IRQ、systemだけのreset、描画cycle上限 |
| | `tb_vdp_sprites`、`tb_vdp_sprites720` | spriteを含む全画素比較、優先順位、behind、16個/line超過 |
| | `tb_raster_scroll`、`tb_raster_scroll720` | ラスタスクロール表の全画素比較 |
| | `tb_sprite_selector`、`tb_sprite_composite` | sprite選択と合成の単体 |
| デモ | `tb_demo_sequencer`、`tb_demo_sprites`、`tb_demo_raster` | sequencer＋VDPの画面 |
| | `tb_demo_audio`、`tb_demo_music` | デモの映像・音声と曲 |
| | `tb_demo_shooter`、`tb_demo_wall`、`tb_demo_flicker`、`tb_demo_shooter720`、`tb_demo_shooter_raster`、`tb_demo_shooter_raster720` | シューティング画面の全画素比較 |
| 音源 | `tb_audio_synth` | 6chと整数モデルの34770 stereo sample比較、25 cycle/sample |
| | `tb_audio_pcm_mix` | PCMのgain・snapshot・飽和、31 cycle/sample |
| | `tb_audio_core` | 公開register経由のAUDIO_COMMIT順序、wave bank交換、拒否 |
| PCM・PSRAM | `tb_pcm_prefetch`、`tb_pcm_timeout` | 先読みの範囲拒否・one-shot・loop・underrun、応答timeoutと遅延応答の破棄 |
| | `tb_pcm_audio_path` | 可変latencyのmemoryからmixerまでの縦通し |
| | `tb_psram_byte_bridge`、`tb_psram_read_cdc`、`tb_psram_arbiter` | byte→word変換とcache、CDC mailbox、host/PCMの仲裁と待ち時間 |
| | `tb_hyperram_ctrl` | cycle単位のHyperRAM protocol checker（CS high時間、競合、mask、register空間） |
| | `tb_psram_pcm_chain`、`tb_hyperram_pcm_chain`、`tb_hyperram_pcm_source` | controller（modelまたは実RTL）からPCM出力までの縦通し |
| | `tb_psram_core` | CAPS b3の`kagura_core`を公開ABIで検査（upload、FILL、COPY、PCMのPREPARE〜DONE、一時停止、STOP、CLEAR） |
| boot | `tb_flash_reader`、`tb_boot_image_check`、`tb_boot_window`、`tb_boot_controller`、`tb_romless_boot_system` | [ROM-less boot](../docs/romless-boot.md#検証) |
| | `test_boot_image.py` | boot image生成器（Python） |

`support/kagura_hyperram_pair_model.sv`はCAを独立に復号するbyte-pair境界のPSRAM modelで、Gowin PHYやCKの位相、実機timingは対象外。
