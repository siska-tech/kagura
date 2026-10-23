# 音声FIFO・HDMI packet統合評価 / 2026-10-23

## 実装した経路

system-domain 32bit `{right,left}` PCM → depth16 async FIFO → pixel/525 tick駆動のtransport（mute/silence挿入） → pixel-domain 4sample収集 → packet scheduler → upstream packet assembler/BCH → HDMI data island/TERC4 → OSER10入力。

`kagura_audio_transport`はpixel clock 525cycleごと（25.2MHz/525=48kHz）に1サンプル分のcredit（3bit）を積み、creditがありpacket側がreadyなら1サンプルを渡す。FIFOの同期read結果を1語保持し、pixel_readyが下がってもvalid/dataを保持する。`kagura_audio_packets`は4語揃ったときだけAudio Sample Packetを送り、packet転送中は別レジスタに保持して収集中の上書きを防ぐ。

**入力停止時の方針（2026-10-23決定）**: [音源仕様](audio-spec.md)と[HDMI設計判断](hdmi-design-decision.md)の記述に合わせ、tick駆動とした。
- reset解除直後は強制mute（`muted`=1）。この間は無音サンプル（L=R=0）を48kHzで送り、errorは立てない。
- FIFOの読出し側占有数（`read_level`、同期済みwrite pointerから計算し過大評価しない）が4以上になったらmute解除し、FIFOから消費する。
- mute解除中にtickへ応えられない（FIFO empty）ときは無音サンプルを送り、sticky `underflow`を立てて再びmuteへ入る。4サンプル溜まれば自動で復帰する。古いPCMを繰り返さない。
- creditが7で飽和したままtickが来た場合（packet枠不足で期限を逃した）も`underflow`を立てる。
- FIFO full時の新サンプル破棄はsticky `overflow`で通知する（従来どおり）。
- `muted`は将来のAUDIO_STATUS.MUTED用で、boardのLEDやport へはまだ出していない。

ACRは共通reference専用、N=6144、CTS=1ms当たりのpixel clock数（VIC1は25200、VIC4は74250）で、CTS pixelごとに要求。2026-10-23に従来定数のCTS byte位置の誤り（sinkは25088と解釈）を修正した（[16:9モード](wide-mode.md)）。起動直後も1回要求する。AVI/Audio/SPD InfoFrameをframeごとに再送する。音声パケットはsample順に192frame blockのstatus/parityを付加する。

一時期は到着した4sampleをpacket枠でまとめてconsumeする方式（到着駆動）としていたが、入力停止時にsinkへのsample供給が途切れ、underflowも検出できないため、上記のtick駆動へ戻した。tickはpixel clockのenableで、別の48kHz fabric clockや原版toggle CDCは使用しない。systemの54MHz/1125とpixelの25.2MHz/525は同じ27MHz referenceのPLL出力から作るので長期周波数は一致し、FIFO占有は4前後で安定する。外部非同期sample clockや別modeで固定CTSを流用しない。

## 原版と派生ソース

`tools/prepare-hdmi-stream.py`はmanifestのSHA256を検証し、`build/generated/kagura_hdmi_stream.sv`を生成する。変更はmodule名、sample-valid ports、packet_picker置換、reset中control_dataのblocking/nonblocking混在の修正。原版は不変。生成ファイルには由来・選択ライセンスを記載する。

`rtl/hdmi/kagura_hdmi_stream_eval.sv`は固定VIC1/60Hz/48kHz/16bit stereo専用の外部clock評価top。PLL/差動buffer/CSTは含まない。DVI版の生成variantとしては使用しない。

## Verilator 5.032試験結果

`bash tools/test-verilator.sh`ですべて合格。

| 試験 | 結果と範囲 |
|---|---|
| `tb_audio_packets` | 2048 stereo pairs、40 sample周期の入力停止、続く1024 pairsをFIFO→packet assemblerの9bit列から復元。欠落/重複/左右混線なし。起動muteと停止中の無音（計44 samples、無音区間は停止の1回だけ）、停止前underflow=0、停止後underflow=1、refill後のmute解除、pending tick最大3（飽和7）を確認 |
| BCH | 独立した多項式long divisionでheader32bit/subpacket64bitを検査。1bit破損を検出 |
| PCM metadata | 16bit left alignment、valid/user、sample parity、192frame status、block-startを確認 |
| InfoFrame/ACR | checksum、N/CTSを照合。frame-endとsample到着が競合する条件を含む |
| `tb_hdmi_stream` | 1024 stereo pairsを実HDMIタイミング/TERC4符号化後の10bit symbolsから復元。partial-group reset後も古いsampleが混ざらない。起動muteの無音は先頭だけで、最初のsource sample以後の無音はerror |

system14ns/pixel30nsの同一比率（54MHz/25.2MHzを時間方向に縮尺）、producerは1125system cycles/sample、tickは525pixel cycles。packet試験は1行あたりpacket枠1個（実機の4個より厳しい）で約49ms、統合試験は約16ms。長時間driftや全位相sweepを検証したとは扱わない。統合decoderは内部modeをpacket区間判定に利用するため、preambleだけから自律同期する外部receiver完全モデルではない。OSER10と電気的出力はsimulation stubの外側で未検証。

## Gowin Education 1.9.11.03合成結果

GW1NR-9C / GW1NR-LV9QN88PC6/I5、SystemVerilog 2017。

| 構成 | Logic総数（tool値） | LUT | ALU | RAM16 | FF | BSRAM |
|---|---:|---:|---:|---:|---:|---:|
| stream/FIFO接続 | 1178 | 879 | 59 | 40 | 436 | 0 |

RAM16を含むLogic総数はツールの集計値をそのまま記載し、各列の単純和やLUT数として扱わない。FIFO/収集bufferは分散RAMへ推論された。Phase 0の1BSRAM割当てを実装で達成したわけではないので、全体予算への影響はP&R時に再評価する。PHY/PLLを除いた合成段階だけの結果で、配置配線・STAは未実施。

```bash
python3 tools/prepare-hdmi-stream.py
```

生成後、Windows側で全3構成を再合成・要約保存できる。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/eval-gowin-hdmi.ps1 -IncludeStream
```

## 残ゲート

clock/PLL、ELVDS出力、pin constraints、Gray転送のmax-delay/skew、domain reset、OSER10 bit order、P&R/STA、長時間FIFO安定性、複数sink実機試験。入力停止時のmute/silence政策は上記で定義・simulation済み。実機では固定test toneのため入力停止を起こせず、停止・復帰の実機確認は未実施。packet/TERC4検証済みを実機HDMI音声確認済みと呼ばない（実機の確認範囲は[検証状況](validation-status.md)）。
