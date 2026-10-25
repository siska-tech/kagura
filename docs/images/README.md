# デモ画像

`demo-720p.png`は、`tb_demo_shooter720`のRTLシミュレーションが保存した`build/verilator/shooter-0.ppm`をPNGへ可逆変換したもの。1280×720、anim=0。トリミング、色変更、拡大縮小は行っていない。実機モニターの写真やHDMIキャプチャではない。

生成元は[シューティング試験](../../sim/tests/tb_demo_shooter.sv)と[720p用top](../../sim/tests/tb_demo_wall.sv)。RTLから取得した各画素を参照モデルと比較し、同じRGB値をPPMへ保存する。既存のVerilator 5.032実行ログではVIC4の5フレーム×921600画素の比較に合格している。画像追加時にはRTL試験を再実行せず、保存済み出力を使用した。

[ビルド・テスト手順](../build-and-test.md)の`bash tools/test-verilator.sh`で再生成できる。480pと720pは同じPPMファイル名を使うため、720p試験後の1280×720の出力を選ぶ。PPMからPNGへ変換する際は元のRGB値とサイズを維持する。

# 実機写真

`hardware-pico-tang-nano-9k.jpg`は、ブレッドボード上のRaspberry Pi Pico（SPI/QSPIホスト）とTang Nano 9Kの撮影写真。元画像1448×1086を1200×900へ縮小し、JPEG（品質85）で保存した。トリミングや色補正は行っていない。撮影時の配線は/IRQをpin 49へ移す前のものの可能性があり、現行の配線は[Pico firmware](../../software/pico/README.md)の表を正とする。
