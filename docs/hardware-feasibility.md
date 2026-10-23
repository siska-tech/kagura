# Hardware Feasibility Report

この資料はPhase 0の設計判断とリスクの根拠を残すもの。以下の「未検証」「次のゲート」は机上検討時点の状態である。現在の実装・測定結果と残課題は[検証状況](validation-status.md)を参照する。

## 判定

**条件付きで実現候補。Phase 0の机上設計を完了し、HDMI単体評価へ進める。ただし実装成立の最終ゲートは未通過。**
以降の文書で【資料確認】は一次資料・公開ソースの確認、【設計】は本プロジェクトの規約、【算定】は明示した仮定からの計算、【未検証】は合成/STA/実機で証拠が必要な事項を表す。

## ハードウェア確認

| 対象 | 資料確認 | KAGURAでの判断 / 未検証 |
|---|---|---|
| FPGA | Sipeed表記GW1NR-LV9QN88PC6/I5、公式生成IPのDEVICEはGW1NR-9C | C版を初期対象。手元のチップ刻印・基板版を確認してからプロジェクトを固定 |
| 論理資源 | LUT4 8640、FF 6480、18×18乗算器20、PLL 2 | 全量を予算上限にせず、配置配線余裕を確保 |
| BSRAM | 26×18432bit = 479232bit。8/16bit幅では1ブロックあたり2048byte相当 | 58.5KiBの総ビット量と52KiBの8bit幅容量を混同しない |
| ポート | DS117表2-5で9系のTrue Dual PortはC版のみ | パターンはSP、ラインバッファはC版TDP。両ポート同一アドレス衝突は禁止 |
| PSRAM | QN88P内蔵64Mbit、パッケージメモリ表の幅16bit | SDRAMではない。2チャネル等の内部接続・制御は対象版のIPUG943/767とUG803で追加確認。初版では未使用 |
| GPIO | QN88Pの上限はパッケージ表、ヘッダは電源・予約ピンも含む | 2×24ヘッダを48 GPIOと数えない。18信号の候補はボード文書に分離 |
| I/O電源 | 公式回路図はVCCO0/1/2=3.3V、VCCO3=1.8V | CPUバスは3.3Vの候補ピンだけを使用 |
| HDMI | 公式CSTに4ペアの配置あり | OSER10＋ELVDS系出力を評価。専用HDMI PHYとは扱わない |
| CPU | W65C02S 3.3V±10%、AC表の8MHz列 | 3.375MHzで開始。信号レベル・配線負荷・電源・実波形は別確認 |

出典: [Sipeed](https://wiki.sipeed.com/hardware/en/tang/Tang-Nano-9K/Nano-9K)、[DS117 表1-1/1-2/2-5](https://cdn.gowinsemi.com.cn/DS117E.pdf)、[回路図](https://dl.sipeed.com/fileList/TANG/Nano%209K/2_Schematic/Tang_Nano_9k_3672_Schematic.pdf)、[W65C02S 表6-3](https://www.westerndesigncenter.com/wdc/documentation/w65c02s.pdf)。正確な版・ソースの固定値は[sources.md](sources.md)。

## 成立性の根拠と限界

- 【資料確認】SipeedのPLL/CLKDIV設定は126MHz→25.2MHz候補と一致する。HDMI音声の動作保証にはならない。
- 【資料確認】tn_vdpの9K v2には音声付きHDMI出力の報告とRTLがある。KAGURAの解像度・音源・資源余裕を追試したものではない。
- 【算定】BSRAMは25個を用途・幅・深さで割り付け可能。パレット変換をsystem側で行い、RGBをラインバッファへ置くことでpalette CDCを避ける。
- 【算定】最悪ライン処理2633 cyclesに64 cyclesのCDC/切替余裕を加えて2697 cycles。理論上の3428 cycles以内。ただし各処理の上限をRTLで守る必要がある。
- 【未検証】HDMI単体LUT/FF/BSRAM、全体STA、バスI/O遅延、モニター互換性。全体の「動作可能」を確定しない。

## リスク台帳

| ID | 重要度 | リスク / 検出方法 | 対応と終了条件 |
|---|---|---|---|
| R01 | 最優先 | HDMI音声が資源を消費。単体合成・P&R | DVIとHDMIの差分を測る。2000 LUT目標を超えたら原因別に最適化、HDMIを削除しない |
| R02 | 最優先 | SYNTHESIS/GW_IDEの分岐でXilinxセルを選択 | serializerをプラットフォーム境界へ分離。ネットリストにOSER10、Xilinxセルなし |
| R03 | 最優先 | audio CDC/リセットで欠落・重複 | FIFO化とsample-enableインターフェース。連番PCMを復号し完全一致 |
| R04 | 高 | C版以外・RAM推論不一致 | 実型番確認と各RAM単体合成。非C版なら合成を拒否、26個を超える代案は別仕様 |
| R05 | 高 | 描画期限超過 | 2633 cycles契約のテスト。pipeline改善、それでも不足なら16→8 sprites/line |
| R06 | 高 | CPU読出しホールド違反・バス競合 | OE遅延解除、外部RAM側のCS/PHI2ゲート、オシロ測定 |
| R07 | 高 | 設定中のCPUリセットが浮く | 外部プル抵抗/監視回路で設定前も保持。電源投入試験 |
| R08 | 高 | TMDS電気特性・ケーブル相性 | 実基板版照合、複数モニター/ケーブルで1時間試験。映ることと規格適合は区別 |
| R09 | 中 | ライセンスがルートだけでは判定できない | 採用ファイル単位で出典と許諾を記録。Gowin生成物は再生成条件を記載 |
| R10 | 中 | ROM/波形/RAMがFFに展開 | RAMリセットは逐次初期化。合成レポートで配置を確認 |
| R11 | 中 | FIFO満杯とFILLでCPU要求が失われる | エラーsticky＋IRQ、受付失敗時アドレス不変。順序付きFENCEで完了検出 |

## Phase 0の残ゲート

設計書・ソース調査・算定は提出済み。次はHDMI最小構成を実装して計測する。HDMI単体の資源測定が未実施であるため、Phase 0を「全検証完了」と表現しない。Phase 1の最初のIssueでこのゲートを閉じる。実基板情報やEDA環境の確定が必要だが、文書設計はそれらを仮定のまま確定事項に昇格させない。
