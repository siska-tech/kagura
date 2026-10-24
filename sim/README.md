# Simulation layout

`tests/`にSystemVerilogの単体・統合・負荷テストを配置する。pixel/audioの参照モデル、busホストモデル、HDMI decoderもtestbench内に実装している。専用C++ harnessと`verilator/`・`reference/`ディレクトリは未実装。

`tests/tb_phase1_sources.sv`は2frameの映像と746 stereo samplesを自己判定する。[ビルド・テスト手順](../docs/build-and-test.md)を参照。全体の検証範囲は[Verification Plan](../docs/verification-plan.md)、設計数値の検査は`tools/check-design.ps1`を参照。

WSL/Linuxではリポジトリrootから`bash tools/test-verilator.sh`で基礎source、TMDS、CPU/SPI/QSPI bus、VRAM、背景・sprite、6ch音源、デモ、720p表示の試験を実行できる。Verilator、g++、make、python3が必要。SystemVerilog testbenchを`--binary --timing`で動かし、build/runログと画像・音声出力を`build/verilator/`へ保存する。波形は`KAGURA_TRACE`で指定したtopだけ、`support/kagura_trace.sv`をbindして出力する（[ビルドガイド](../docs/build-and-test.md)）。Verilator 5.032での検証結果は[検証状況](../docs/validation-status.md)と[16:9記録](../docs/wide-mode.md)を参照。

`tests/tb_register_abi.sv`は生成されたABI package（`spec/registers.json`由来）とregister RTLのreset値・access可否・EXT・音源indexを照合する。挙動の検査は従来の手書きテストが担う。

同じrunnerで`tests/tb_async_fifo.sv`も実行する。depth16の満杯、1024語の順序・wrap、nonempty reset、empty popの検査が合格済み。

`tb_audio_packets`は2048 stereo pairsとBCH/metadata/ACR、`tb_hdmi_stream`はpartial-group reset後の1024 stereo pairsをTERC4から復号する。[統合評価条件](../docs/audio-packet-integration.md)を参照。

`tb_serializer_reset`はGowin primitiveを機能stubへ置き換え、入力resetのFCLK位相を変えて非同期assert、serializer内の3 FCLK立上り後の解除、4 lane同時解除を検査する。OSER10端子の物理的なrecovery/removalと配線遅延は対象外で、[実機試験表](../docs/p1-07-hardware-test.md)の720p反復と区別する。
