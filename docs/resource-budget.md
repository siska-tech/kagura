# Resource Budget

## 管理方法

【設計】以下は割り当て目標であり、合成推定でも実測でもない。RTLを作る前に予算を置くための数値。LUTとFFの資源競合・制御信号共有・配置制約によって収まらない可能性がある。合成後は下の実測表へ記録し、机上予算を実測で上書きしない。

| Block | LUT4予算 | FF予算 | BSRAM計画 | PLL | 18×18 DSP予算 |
|---|---:|---:|---:|---:|---:|
| HDMI protocol/serializer/audio FIFO | 2000 | 1500 | 1 | 0 | 0 |
| Bus/register/IRQ | 650 | 650 | 0 | 0 | 0 |
| VRAM/control/queue | 500 | 350 | 19 | 0 | 0 |
| Tile/palette/line banks | 900 | 450 | 3 | 0 | 0 |
| Sprite | 1300 | 650 | 1 | 0 | 0 |
| PSG/noise/mixer | 650 | 550 | 0 | 0 | 2 |
| Wave | 300 | 250 | 1 | 0 | 0 |
| Clock/reset/integration | 400 | 300 | 0 | 2 | 0 |
| **計** | **6700** | **4700** | **25** | **2** | **2** |
| デバイス総量 | 8640 | 6480 | 26 | 2 | 20 |
| 予備 | 1940 | 1780 | 1 | 0 | 18 |

VRAM行の19はpattern16＋map2＋queue1。Tile行の3はpalette1＋line2。Sprite行はOAM1、Wave行はwave1。audio FIFOはHDMI行に1回だけ計上。LUT RAMは初期設計では必須0bit、必要になればLUT予算と一緒に再配分する。小レジスタ、snapshot、同期器、スプライト一時行32/64bit等はFF予算に含む。

## 実装の測定値

全体の測定値は[検証状況](validation-status.md)、720pの構成別数値は[16:9仕様](wide-mode.md)を参照。CPU/ホスト版は24/26 BSRAM、art ROMを含むデモ版は25/26（`443900a`以降。art ROMのpROMが2→1個）であり、上記25ブロックの設計予算とは区別する。

合成のcell数とP&Rの使用数を両方保存する。LogicとLUTを混同せず、各clockのslackと制約例外を報告する。個別moduleの合成量を単純加算して統合使用量としない。変更後は同じ構成・EDAで再測定する。

## 削減順序と期待効果

| 順序 | 変更 | 効果・失うもの | 元仕様への回復条件 |
|---:|---|---|---|
| 1 | wave 256→32 | address/演算を小さくする。単独BSRAM1個は普通は減らない | 配置余裕と音源テスト合格 |
| 2 | sprite演算器を時分割 | LUTを減らすがcycles増加 | 2633cyclesの期限内、余裕実測 |
| 3 | 16→8 sprites/line | 744描画cycles減。密集時欠落増 | P&R＋負荷試験で16個版合格 |
| 4 | 64→32 registered sprites | OAM走査192cycles減。BSRAMは残りやすい | FFと描画期限に余裕 |
| 5 | pattern 1024→512 | **BSRAM8個削減**、パターン資産半減 | 26個以内・全体STA合格 |
| 6 | palette bank減 | 色表現減、物理RAM削減は別検討 | RGB/priority回帰試験 |
| 7 | map 64×32→32×32 | **BSRAM1個削減**、横map幅256に変化 | メモリ予算回復、scroll ABI更新 |

BSRAM不足にはwave長縮小だけでは効かない。小メモリをLUT RAMへ移す場合は論理資源への転嫁を測る。削減はCAPS/EXT上限/ABIと文書を同時更新する。HDMI音声は維持し、音声部が原因ならgeneric mux定数化や固定mode実装を先に比較する。
