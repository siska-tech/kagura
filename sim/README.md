# Simulation layout

`tests/`にSystemVerilogの単体・統合・負荷テストを配置する。pixel/audioの参照モデル、busホストモデル、HDMI decoderもtestbench内に実装している。専用C++ harnessと`verilator/`・`reference/`ディレクトリは未実装。

`tests/tb_phase1_sources.sv`は2frameの映像と746 stereo samplesを自己判定する。[ビルド・テスト手順](../docs/build-and-test.md)を参照。全体の検証範囲は[Verification Plan](../docs/verification-plan.md)、設計数値の検査は`tools/check-design.ps1`を参照。

WSL/Linuxではリポジトリrootから`bash tools/test-verilator.sh`で基礎source、TMDS、CPU/SPI/QSPI bus、VRAM、背景・sprite、6ch音源、デモ、720p表示の試験を実行できる。Verilator、g++、make、python3が必要。SystemVerilog testbenchを`--binary --timing`で動かし、build/runログと画像・音声出力を`build/verilator/`へ保存する。波形は`KAGURA_TRACE`で指定したtopだけ、`support/kagura_trace.sv`をbindして出力する（[ビルドガイド](../docs/build-and-test.md)）。Verilator 5.032での検証結果は[検証状況](../docs/validation-status.md)と[16:9記録](../docs/wide-mode.md)を参照。

`tests/tb_register_abi.sv`は生成されたABI package（`spec/registers.json`由来）とregister RTLのreset値・access可否・EXT・音源indexを照合する。挙動の検査は従来の手書きテストが担う。

同じrunnerで`tests/tb_async_fifo.sv`も実行する。depth16の満杯、1024語の順序・wrap、nonempty reset、empty popの検査が合格済み。

`tests/tb_flash_reader.sv`はROM-less boot向けの単線SPI readerをFlashモデルへ接続し、JEDEC ID、`03h`連続読出し、byte境界でのbackpressure、長さ0の拒否を検査する。
`tests/tb_boot_image_check.sv`は32-byteヘッダ、配置範囲、entry、header/payload CRCを検査し、各拒否理由を確認する。
`tests/tb_boot_window.sv`は6502スタブ、RESET/BRKベクタ、保護されたデータポートとpayload backpressureを検査する。
`tests/tb_boot_controller.sv`はFlashモデルを使い、JEDEC確認、二重読出し、CRC検査、先読み、ブート窓までを統合検査する。
`tests/tb_romless_boot_system.sv`はW65C02Sのスタブ命令モデル、SRAM/decodeモデル、Flashモデルを接続し、全payloadのコピー、entry到達、データポート消費数、KAGURA/SRAMの排他選択を検査する。
`tests/test_boot_image.py`はホスト側のブートイメージ生成器について、header/payload CRC、padding、配置範囲の拒否を検査する。

`tb_audio_packets`は2048 stereo pairsとBCH/metadata/ACR、`tb_hdmi_stream`はpartial-group reset後の1024 stereo pairsをTERC4から復号する。[統合評価条件](../docs/audio-packet-integration.md)を参照。

`tb_serializer_reset`はGowin primitiveを機能stubへ置き換え、入力resetのFCLK位相を変えて非同期assert、serializer内の3 FCLK立上り後の解除、4 lane同時解除を検査する。OSER10端子の物理的なrecovery/removalと配線遅延は対象外で、[実機試験表](../docs/p1-07-hardware-test.md)の720p反復と区別する。
