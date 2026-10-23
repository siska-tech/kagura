# デモ画像

`demo-720p.png`は、`tb_demo_shooter720`のRTLシミュレーションが保存した`build/verilator/shooter-0.ppm`をPNGへ可逆変換したもの。1280×720、anim=0。トリミング、色変更、拡大縮小は行っていない。実機モニターの写真やHDMIキャプチャではない。

生成元は[シューティング試験](../../sim/tests/tb_demo_shooter.sv)と[720p用top](../../sim/tests/tb_demo_wall.sv)。RTLから取得した各画素を参照モデルと比較し、同じRGB値をPPMへ保存する。既存のVerilator 5.032実行ログではVIC4の5フレーム×921600画素の比較に合格している。画像追加時にはRTL試験を再実行せず、保存済み出力を使用した。

[ビルド・テスト手順](../build-and-test.md)の`bash tools/test-verilator.sh`で再生成できる。480pと720pは同じPPMファイル名を使うため、720p試験後の1280×720の出力を選ぶ。PPMからPNGへ変換する際は元のRGB値とサイズを維持する。
