# デモ画像

`demo-720p.png`は、`tb_demo_shooter720`のRTLシミュレーションが保存した`build/verilator/shooter-0.ppm`をPNGへ可逆変換したもの。1280×720、anim=0。トリミング、色変更、拡大縮小は行っていない。実機モニターの写真やHDMIキャプチャではない。

生成元は[シューティング試験](../../sim/tests/tb_demo_shooter.sv)と[720p用top](../../sim/tests/tb_demo_wall.sv)。RTLから取得した各画素を参照モデルと比較し、同じRGB値をPPMへ保存する。既存のVerilator 5.032実行ログではVIC4の5フレーム×921600画素の比較に合格している。画像追加時にはRTL試験を再実行せず、保存済み出力を使用した。

[ビルド・テスト手順](../build-and-test.md)の`bash tools/test-verilator.sh`で再生成できる。480pと720pは同じPPMファイル名を使うため、720p試験後の1280×720の出力を選ぶ。PPMからPNGへ変換する際は元のRGB値とサイズを維持する。

# KAGURA-UIプレビュー

`kagura-ui-gallery.png`と`kagura-ui-studio-mock.png`は、KAGURA-UIのPC MockBackendを
`python tools/render-kagura-ui.py build/ui-previews`で描画した320×240画像。
既存の美咲fontとUI paletteを使用し、画素とサイズを変えずPNG保存した。
実機写真やHDMIキャプチャではない。[設計・API](https://github.com/siska-tech/kagura-sdk/blob/aae8699d8db01ed9825b37443b8ff8f3bb1cd14b/docs/kagura-ui.md)を参照。

`kagura-ui-gallery-hdmi.png`、`kagura-ui-studio-hdmi.png`、`kagura-ui-monitor-hdmi.png`、
`kagura-ui-console-restored.png`は2026-11-01のRP2040実機HDMI出力。
UGREEN 15390の720×480 YUYV入力をFFmpegで640×480・SAR 1へ正規化し、PNG保存した。
横方向のキャプチャカードによる伸長を戻したもので、cropやUIの描き足しは行っていない。
[受入・計測記録](https://github.com/siska-tech/kagura-sdk/blob/aae8699d8db01ed9825b37443b8ff8f3bb1cd14b/docs/kagura-ui-validation.md)を参照。

# 実機写真

`hardware-pico-tang-nano-9k.jpg`は、ブレッドボード上のRaspberry Pi Pico（SPI/QSPIホスト）とTang Nano 9Kの撮影写真。元画像1448×1086を1200×900へ縮小し、JPEG（品質85）で保存した。トリミングや色補正は行っていない。撮影時の配線は/IRQをpin 49へ移す前のものの可能性があり、現行の配線は[Pico firmware](https://github.com/siska-tech/kagura-sdk/blob/aae8699d8db01ed9825b37443b8ff8f3bb1cd14b/software/pico/README.md)の表を正とする。

# ショーケース

`showcase/`の画像は、2026-11-04にRP2040実機（ファームウェア`e49871e`、480p FULL+PSRAM構成）のHDMI出力を、UGREEN 15390で録画したものから切り出した。

- **取込み:** 1280×960 YUYVで入力し、FFmpegで640×480・SAR 1へ正規化してH.264で録画した。
- **静止画:** 録画から1フレームを抜き出し、256色のパレットPNGで保存した。ディザはかけていない。
- **加工:** 描き足しはしていない。

| 画像 | 元 |
|---|---|
| `title`、`host`、`colour`、`plasma`、`tunnel`、`hypercube`、`ribbons` | 紹介プレゼンテーション（`showcase.run`、`mpremote mount`から実行） |
| `starfall-base`、`starfall-boss` | `starfall.run(autoplay=True)`の単体実行 |
| `wave-sine`、`wave-staircase` | kagura-desktopの`tools/kagura-audio-board.py wave`（神楽トラッカーの波形エディタ） |
| `skk-popup` | kagura-desktopの`docs/hardware/popup-hdmi.png`（受入時の一覧画像）の1コマを切り出したもの |
| `desktop-paint` | kagura-desktopの`docs/hardware/hdmi-08-paint.png`（2026-11-03、ファームウェア`1c9c234`の受入時HDMI静止画）をそのまま複製したもの |

撮影はすべてRAMとmountで行った。Flashとファイルシステムは変更していない。一覧と説明は[ショーケース](https://github.com/siska-tech/kagura-sdk/blob/aae8699d8db01ed9825b37443b8ff8f3bb1cd14b/docs/showcase.md)。
