# モジュール3Dモデル

## Tang Nano 9K

ユーザー提供の`Tang_Nano_9K_3672.step`を内容未改変で同梱しています。STEPヘッダーの生成日時は2021-12-07です。基板上ではJ2011を基準に、J5/J6の列間隔22.86mm・ピッチ2.54mmをソケット列に合わせています。

- モジュールPCB下面：キャリア表面から11.05mm（ソケット8.51mm＋オスヘッダ樹脂2.54mmの公称積み高さ）。
- このSTEPは3672版で、電気設計の3674版の実測モデルではありません。
- 元STEP内の全長24ピンヘッダ2列も表示されます。実際の組立は購入ガイドの7分割ソケット・対応する24接点のヘッダ構成です。全長ヘッダのまま実装できることを意味しません。

## Raspberry Pi Pico

KiCad 10付属`Module.3dshapes/RaspberryPi_Pico_AddedHeaders_H2.54mm.step`を内容未改変で同梱しています。J101を基準に、反対列J102を含む20極×2列の接点位置へ合わせています。部品面はキャリア裏面の外側を向きます。

- ソケット高さ8.5mm、モジュール側ヘッダ樹脂2.54mmを仮定し、Pico PCB下面をキャリア裏面から11.04mmに配置。
- モジュール側ヘッダを含むKiCadの参考モデルです。購入ソケットの全公差や実物嵌合を保証しません。
- 出典：[KiCad Packages3D](https://gitlab.com/kicad/libraries/kicad-packages3D)。帰属・著者情報はSTEPヘッダーを維持しています。
- ライセンス：[Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/)。[KiCadのライセンス表記](https://gitlab.com/kicad/libraries/kicad-packages3D/-/blob/master/LICENSE.md)。この第三者モデルにはリポジトリのApache-2.0を適用しません。

## 表示の範囲

モデルの追加による配線・ランド・銅箔・穴・外形・ネット・参照名・部品数の変更はありません。PCB内と対応するローカルフットプリントにモデルのパス・位置・回転だけを追加しています。製造用ガーバー・BOM・CPLは変更していません。

既存のソケットモデルも汎用品です。この画像は組立外観の参考であり、部品の干渉、ケーブル・カードの挿抜、板間の実測隙間を検証したものではありません。F1・Grove・スイッチ等の未設定モデルは省略されています。
