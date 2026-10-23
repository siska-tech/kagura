# RTL module boundaries

背景VDP・VRAM・sprite・6ch音源をHDMIへ統合し、CPU不要のシューティングデモを実機確認済み。`vdp/kagura_sprite_selector.sv`・`kagura_sprite_row.sv`・`kagura_sprite_renderer.sv`を含む全画素試験にも合格。[検証状況](../docs/validation-status.md)を参照。

`hdmi/kagura_hdmi_stream_eval.sv`に音声FIFO/packet経路を接続し、Gowin用`platform/kagura_gowin_serializer.sv`で出力する。[合成評価条件](../docs/hdmi-synthesis-evaluation.md)を参照。

`audio/kagura_audio_registers.sv`がindexed shadowとAUDIO_COMMIT snapshotを保持し、command engineが先行VRAM操作の完了後に`audio/kagura_audio_synth.sv`へ渡す。次sample境界でwaveのactive/shadow bankと設定を同時に切り替える。demo/CPU topは6ch音源をHDMI FIFOへ接続し、Phase 1 topは固定テスト音を維持する。

| Directory | 責務 |
|---|---|
| core | register、IRQ、CPU非依存request/response、commit |
| bus | W65C02S・SPI/QSPI adapter、top-level tri-state制御 |
| vdp | tile/sprite、line ownership、2x / 4x scaling |
| audio | phase/noise/wave/mixer、sample enable |
| hdmi | protocol、packet、TMDS、platform非依存 |
| memory | VRAM arbiter、queue、async FIFO契約 |
| platform | Gowin RAM/PLL/CLKDIV/OSER10/reset wrapper |

規範は[architecture](../docs/architecture.md)、[register ABI 0.2](../docs/register-map.md)。現行構成と実機検証の入口は[README](../README.md)を参照。
