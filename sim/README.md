# Simulation layout

`tests/`にSystemVerilogの単体・統合・負荷テストを配置する。pixel/audioの参照モデル、busホストモデル、HDMI decoderもtestbench内に実装している。専用C++ harnessと`verilator/`・`reference/`ディレクトリは未実装。

`tests/tb_phase1_sources.sv`は2frameの映像と746 stereo samplesを自己判定する。[ビルド・テスト手順](../docs/build-and-test.md)を参照。全体の検証範囲は[Verification Plan](../docs/verification-plan.md)、設計数値の検査は`tools/check-design.ps1`を参照。

WSL/Linuxではリポジトリrootから`bash tools/test-verilator.sh`で基礎source、TMDS、CPU/SPI/QSPI bus、VRAM、背景・sprite、6ch音源、デモ、720p表示の試験を実行できる。Verilator、g++、make、python3が必要。SystemVerilog testbenchを`--binary --timing`で動かし、build/runログと画像・音声出力を`build/verilator/`へ保存する。波形は`KAGURA_TRACE`で指定したtopだけ、`support/kagura_trace.sv`をbindして出力する（[ビルドガイド](../docs/build-and-test.md)）。Verilator 5.032での検証結果は[検証状況](../docs/validation-status.md)と[16:9記録](../docs/wide-mode.md)を参照。

`tests/tb_register_abi.sv`は生成されたABI package（`spec/registers.json`由来）とregister RTLのreset値・access可否・EXT・音源indexを照合する。挙動の検査は従来の手書きテストが担う。

同じrunnerで`tests/tb_async_fifo.sv`も実行する。depth16の満杯、1024語の順序・wrap、nonempty reset、empty popの検査が合格済み。

`tests/tb_pcm_prefetch.sv`は可変応答遅延のメモリmodelを使い、PCM 2ch先読みの不正範囲拒否、one-shot、loop境界、補給停止時のunderrunを検査する。
`tests/tb_pcm_timeout.sv`は初期prefill中の応答timeout、遅延応答の破棄、buffer非混入、drain後のSTARTからの再設定を検査する。
`tests/tb_audio_pcm_mix.sv`はPCM 2chの独立L/R gain、commit snapshot、live sample入力、正負飽和、30/64cyclesを整数計算と照合する。既存`tb_audio_synth`はPCM無効時の6音源を24cyclesで照合する。
`tests/tb_pcm_audio_path.sv`は可変レイテンシmemory model、prefetch、48kHz境界pulse、PCM mixerを接続し、signed sampleの順序とone-shot末尾sampleの保持を縦通しで検査する。
`tests/tb_psram_byte_bridge.sv`は32bit controllerのbackpressure、4 byte lane、1-word cache hit、word/byte address変換と整列、calibration喪失時のerror応答を検査する。
`tests/tb_psram_read_cdc.sv`は非同期なsystem/memory clock間で302 readを往復させ、要求backpressure、可変応答遅延、error、reset後の再利用を検査する。
`tests/tb_psram_core.sv`はCAPS b3の`kagura_core`を実controllerとCAを独立にdecodeするmemory modelへ接続し、公開register経由でABI 0.4を検査する。PSRAM領域へのupload・READ_REQUEST読戻し・FILL・範囲外のINVALID_ADDRESS、byte maskによる隣接byteの保持、EXT 12/13、PCM registerのreset値と予約offset、PREPARE→READY→AUDIO_COMMITでの2ch開始、one-shotのDONE、領域上端を跨ぐloop、再生中のhost転送でUNDERRUNなし、ENABLE=0/1の一時停止と途切れない再開、STOP、CONFIG_ERRORとCLEAR、PREPARE直後のSTATUSが旧READYを返さないこと、終了したone-shotの再生を照合する。
`tests/tb_psram_arbiter.sv`はランダムな所要時間の1-outstanding controller modelへPCM側(byte bridge型)とhost側(読み書き混在・mask付き)を同時に流し、応答の振り分け、data、両側の最大待ち時間を検査する。
`tests/tb_hyperram_ctrl.sv`は`kagura_hyperram_ctrl`をcycle単位のHyperRAM protocol checkerへ接続し、reset pulse、CR0書込み、register空間のwrite/read、CAの各field、固定latency、CS high時間、バス競合、write mask、40 word乱数write/readの往復を検査する。PHYと実機timingは対象外で、実機値は`rtl/README.md`に記録している。
`tests/tb_psram_pcm_chain.sv`は32bit PSRAM controller model、1-word cache、非同期CDC、prefetch、PCM mixerを縦通しし、8個のsigned sampleを2 controller commandsで左右へ出力することを検査する。

`tests/tb_hyperram_pcm_chain.sv`は自作`kagura_hyperram_ctrl`を実際に接続した縦通し試験。lat_cycles=14、rd_latency=6、54MHzで、初期CR0設定、2 wordのupload、交互byte maskによる部分write、read pathのcache/CDC、prefetch、mixerを検査する。独立した期待値の8個のsigned sampleと左右出力が一致し、read command 2回、30cycles/sample、one-shot完了、underrun/errorなしを要求する。`support/kagura_hyperram_pair_model.sv`はCAを独立に復号するbyte-pair境界モデルであり、Gowin PHY、DDR端子、CK位相・RWDS captureの実機検証ではない。

`tests/tb_flash_reader.sv`はROM-less boot向けの単線SPI readerをFlashモデルへ接続し、JEDEC ID、`03h`連続読出し、byte境界でのbackpressure、長さ0の拒否を検査する。
`tests/tb_boot_image_check.sv`は32-byteヘッダ、配置範囲、entry、header/payload CRCを検査し、各拒否理由を確認する。
`tests/tb_boot_window.sv`は6502スタブ、RESET/BRKベクタ、保護されたデータポートとpayload backpressureを検査する。
`tests/tb_boot_controller.sv`はFlashモデルを使い、JEDEC確認、二重読出し、CRC検査、先読み、ブート窓までを統合検査する。
`tests/tb_romless_boot_system.sv`はW65C02Sのスタブ命令モデル、SRAM/decodeモデル、Flashモデルを接続し、全payloadのコピー、entry到達、データポート消費数、KAGURA/SRAMの排他選択を検査する。
`tests/test_boot_image.py`はホスト側のブートイメージ生成器について、header/payload CRC、padding、配置範囲の拒否を検査する。

`tb_audio_packets`は2048 stereo pairsとBCH/metadata/ACR、`tb_hdmi_stream`はpartial-group reset後の1024 stereo pairsをTERC4から復号する。[統合評価条件](../docs/audio-packet-integration.md)を参照。

`tb_serializer_reset`はGowin primitiveを機能stubへ置き換え、OSER10のlocal RESETが無効であることを検査する。chip GSRの生成源、専用配線、OSER10内部の動作はRTL simulation対象外で、P&Rの生成netlist監査と[実機試験表](../docs/p1-07-hardware-test.md)のreset反復で確認する。
