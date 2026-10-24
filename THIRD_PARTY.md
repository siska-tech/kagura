# Third-party policy and investigation

hdl-util/hdmiの原版RTLを`third_party/hdl-util-hdmi/`に評価用として保存した。10 RTLファイルとLICENSE-APACHE/LICENSE-MITの計12ファイルは原版のまま、manifestでSHA256を固定。Apache-2.0側を選択し、著者表記と両ライセンス本文を保持。別NOTICEは調査treeに存在しなかった。Gowin/tn_vdp/SVOソースは取り込んでいない。

| Candidate | 調査した許諾 | 方針 |
|---|---|---|
| hdl-util/hdmi | READMEでMIT OR Apache-2.0、LICENSE-MIT/ LICENSE-APACHEを確認 | 採用済み。Apache-2.0を選択し、原版ファイル一覧・hashをmanifestに固定。ローカル置換実装は下記と出典台帳を参照 |
| lfantoniosi/tn_vdp | root BSD-3-Clause | 9K v2を参考。F18A/HDMI/Gowin等の個別由来を再確認してから必要箇所だけ採用 |
| Sipeed SVO | 調査したsvo_tmds.vにISC相当の許諾文 | 同じ許諾が全ファイルにあるとは仮定しない |
| Gowin generated IP | 生成wrapperにGowin copyright/all rights reserved | EDAで再生成、同梱/再配布条件を確認。独自成果物として再ライセンスしない |

revisionとURLは[出典台帳](docs/sources.md)。今後の導入時には原著作権、ライセンス本文、変更内容、必要なNOTICEを保持し、トップレベルLICENSEだけで上書きしない。

`tools/prepare-hdmi-stream.py`が原版`hdmi.sv`から評価用派生ソースをbuild内へ生成する。原版のハッシュを検証し、変更箇所をコード上のanchorで限定、由来とApache-2.0選択を生成物に記載する。原版は不変。stream構成で再利用するpacket formatters/assembler/TMDS encoderも同じライセンス条件で使用する。

`rtl/hdmi/kagura_tmds_channel.sv`は固定した上流`src/tmds_channel.sv`（著者Sameer Puri）を基にしたローカル置換実装として管理する。74.25MHz向けにprefix XORと3段パイプラインへ構成を変更し、上流より2 pixel clocks遅い同一出力列を生成する。Apache-2.0を適用し、由来・変更内容をソース先頭にも記載する。原版は比較試験とDVI構成で使用する。

`software/pico/pico_sdk_import.cmake`はRaspberry Pi Pico SDK 2.2.0（commit `a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`）の`external/pico_sdk_import.cmake`の無改変の写しで、SDKのBSD-3-Clauseに従う。CIはSDK版の同ファイルと一致することを検査する。Pico SDK本体とArm GNU Toolchainはビルド時に取得し、リポジトリに含めない。
