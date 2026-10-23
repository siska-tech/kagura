# Verification Plan

## 証拠の段階

1. Phase 0: 文書・算術・ソース調査。`tools/check-design.ps1`はこの段階だけを検査。
2. RTL simulation: Verilatorと独立reference modelの一致。実機性能の保証ではない。
3. Synthesis: 資源とRAM推論。timing収束と区別。
4. P&R/STA: 制約付きsetup/hold合格。配線・モニター相性は未保証。
5. Board: 波形測定、HDMI映像/音声、複数機種での長時間試験。

## テスト構成

現在はVerilatorの`--binary --timing`でSystemVerilog testbenchを実行し、testbench内にclock生成・bus model・pixel/audio参照モデル・HDMI decoderを置く。専用C++ harnessは未実装。RTLのpixel出力はPPM、PCMはrawからWAVへ変換して保存する。clock初期位相やreset条件を変え、送信器と同じ関数をコピーしたdecoderを唯一のoracleにしない。serializer出力の電気的検証は別途実機で行う。

topのinoutは`data_in/data_out/data_oe`へ分けてテストし、board wrapperだけにtri-stateを置く。Verilatorの2-stateモデルだけで電気的Hi-Zや競合を保証しない。出力enableのassertionsと、必要な4-state simulator/実機波形を併用する。

## 必須テストと合格条件

| 分野 | stimulus | 合格条件 |
|---|---|---|
| Bus | 全32 offsets、CS high/low、RWB、連続cycles、reset各phase | 1cycle=1要求、未選択OE=0、read setup/hold計画を満たす |
| FIFO | depth32全域、同時push/pop、組立中full、長FILL/COMMIT | order保持、full拒否でaddress不変、sticky error+IRQ、復帰後再試行成功 |
| IRQ | 全要因、mask中発生、W1C同時event | event優先で取りこぼしなし、maskとcause独立 |
| VRAM | 各領域両端、穴、24bit高位、INC0/1/65535、FILL0/1/max | aliasなし、range全体validate、部分FILLなし、READ順序保証 |
| RAM | byte RMWとrenderer競合 | 同一address衝突禁止、未定義read-during-write依存なし |
| Tile | 1024pattern、全palette、scroll0/7/511/255、flip全組合せ | 独立modelと320×240全画素一致 |
| Sprite | signed座標端、8/16、16×16基底、transparent、behind、小番号優先 | 全画素一致、17個目overflow index/line一致 |
| Commit | FIFO直前/直後write、VBlank直前/直後token、shadow更新 | active切替時刻・snapshotが仕様どおり、二重受付なし |
| Line banks | y=0/1/478/479/480/524、done遅延、reset片側 | 2行同bank、tag照合、期限失敗は黒＋error、partial表示0 |
| Scheduler | 最悪画面＋最大CPU＋全音源 | renderer<=2633 cycles、guard64確保、CPU枠>=731 cycles |
| Audio | 各step/duty/wave長、enable、seed、左右gain、clip | sample-by-sample整数model一致、noise周期32767、左右混線なし |
| HDMI video | 全RGB/制御、line/frame境界 | 800×525、2倍画素、running disparity/制御記号がdecoderと整合 |
| HDMI audio | 連番L/R、InfoFrame/ACR競合、FIFO位相 | 48k samples/s、欠落/重複0、BCH/checksum/channel status一致 |
| Drift/reset | clock位相sweep、reset/unlock、mute復帰 | FIFO占有が長期増減しない、domain reset整合、silenceから正常復帰 |

## 実機受入

音源統合の現在の試験は`tb_audio_synth`（整数モデルと34770 stereo samples）、`tb_audio_core`（公開register、FIFO token順序、wave bank、PCM、拒否とsticky error）、`tb_demo_audio`（実sequencer＋VDP＋音声FIFO、全画素比較とPCM順序照合）。HDMI packetの復号は`tb_hdmi_stream`/`tb_audio_packets`で別途検証する。実施範囲は[検証状況](validation-status.md)、実機の合格条件・記録表は[実機試験](p1-07-hardware-test.md)で管理する。

- 基板版、チップ刻印、電源、CST、EDA版、source commit、bitstream SHA256を記録。
- PHI2/data/OE/CS/reset/IRQを測定し、3.3Vのsetup/hold・rise/fall・負荷条件と照合。受入時は最悪値を表に残す。
- HDMI対応で音声を受けられる異なる2機種以上、ケーブル2本で起動20回、抜挿10回、各1時間連続。
- 映像はbarと1pixel境界、音声は左右別周波数・無音・連番capture。耳で聞こえるだけをsample完全性の証明にしない。
- FIFO under/overflow、line underrun、PLL unlockをカウンタ取得。通常連続試験で0。障害注入時は期待フラグとmute/resetを確認。
- HDMIキャプチャ/解析器がない場合はpacket試験をsimulation証拠、実機は互換性試験と分けて報告する。

## CIの段階導入

現在は文書リンク・数値整合性・依存hash、Icarus基礎試験、HDMI decoder・VDP・音源・ホストを含むVerilator回帰をworkflowで実行する。Verilator版の固定と失敗時artifactは実装済み（[ビルドガイド](build-and-test.md)）。register定義`spec/registers.json`からのSV/C/ca65定数生成と、文書表・生成物の差分検査も実行する（[レジスタABI](register-map.md)）。[ロードマップ](implementation-roadmap.md)を参照。

各testに固定seed、タイムアウト、失敗時VCD/画像/PCM差分を用意する。未実装testをpass/skipで隠して総合合格にしない。Gowin P&Rはlicensed/self-hosted環境で独立ジョブとし、一般CIで利用不能なら「未実施」を明示する。

## 保存する証拠

`reports/<revision>/<tool-version>/<configuration>/`にmanifest、sources hash、command line、logs、utilization、STA、CDC例外、CST/SDC、test seed、board結果を保存する。生成済みファイルだけでなく再生成手順を保存。巨大波形はCI artifactとし、Gitへ無条件追加しない。
