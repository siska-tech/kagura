# ドキュメント案内

初めて使う場合は[ビルド・テスト手順](build-and-test.md)と[検証状況・既知の制約](validation-status.md)から読む。

| 目的 | 文書 |
|---|---|
| ボード接続・ピン | [ボード資料](../boards/tang-nano-9k/README.md)、[ピン一覧](../boards/tang-nano-9k/pin-inventory.csv) |
| ホストから制御 | [レジスタABI](register-map.md)、[SPI/QSPI](host-interface.md)、[CPUタイミング](timing.md) |
| 映像・音声データ | [メモリマップ](memory-map.md)、[音源仕様](audio-spec.md)、[16:9モード](wide-mode.md) |
| 内部実装 | [アーキテクチャ](architecture.md)、[メモリアクセス](memory-access-schedule.md)、[RTL一覧](../rtl/README.md) |
| 設計根拠 | [成立性とリスク](hardware-feasibility.md)、[資源予算](resource-budget.md)、[HDMI設計判断](hdmi-design-decision.md) |
| 個別の評価根拠 | [BSRAM](bsram-evaluation.md)、[HDMI合成](hdmi-synthesis-evaluation.md)、[音声packet](audio-packet-integration.md) |
| 検証・今後の開発 | [検証計画](verification-plan.md)、[M0基準記録](baseline.md)、[機材一覧](equipment.md)、[実機試験表](p1-07-hardware-test.md)、[ロードマップ](implementation-roadmap.md) |
| 出典・依存 | [出典台帳](sources.md)、[第三者IP方針](../THIRD_PARTY.md) |

仕様・設計予算、simulation、P&R、実機確認は別の証拠として扱う。評価資料の古い構成の数値は現行版の保証ではなく、測定条件と制約を併せて参照する。
