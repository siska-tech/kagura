# misaki8.kfnt（美咲ゴシック 8×8）

`misaki8.kfnt`は門真なむ氏の8×8ドット日本語フォント「美咲ゴシック」2021-05-05版を`kagura_ja`用のKJ8F形式へ変換したもの。収録7171字（ASCII・半角カナと、JIS X 0208の記号・かな・漢字が中心。BMP外の文字はない）、71,718byte。字形は変更していない。半角字形（4px幅）は8×8セル内で中央寄せした。

- 配布元: https://littlelimit.net/misaki.htm
- アーカイブ: `misaki_bdf_2021-05-05.zip`（SHA-256 `a275f173cf5935890f84d3e65d05b1bf73028e4d4bf41cb3de0ef3b5ebe8e217`）
- 変換元: その中の`misaki_gothic.bdf`（SHA-256 `28a8745552c844f7c73f11bdf4470225f5e08645a98c5404b2e25bb326a5cabd`）
- 生成物: `misaki8.kfnt`（SHA-256 `cbfb1071801f7ed3b6637bb6763219e59d86c13bd149169bbbab5bca753d9238`）

## 著作権・ライセンス

Copyright (C) 2002-2021 Num Kadoma（門真なむ）

アーカイブ同梱の`misaki.txt`による許諾:

> These fonts are free softwares.
> Unlimited permission is granted to use, copy, and distribute it, with or without modification, either commercially and noncommercially.
> THESE FONTS ARE PROVIDED "AS IS" WITHOUT WARRANTY.

このフォントファイルにはリポジトリのApache-2.0は適用されず、上記の許諾に従う。

## 再生成

```sh
curl -LO https://littlelimit.net/arc/misaki/misaki_bdf_2021-05-05.zip
python3 -I tools/gen-kagura-ja-font.py misaki_bdf_2021-05-05.zip \
  software/micropython/fonts/misaki8.kfnt --check
```

ツールはアーカイブとBDFのSHA-256を検証してから変換する。`--check`を外すと書き出す。

## KJ8F形式

数値はすべてlittle endian。

| 位置 | 内容 |
|---|---|
| 0 | `KJ8F` |
| 4 | u16 形式番号（1） |
| 6 | u16 文字数N（1以上） |
| 8 + 10i | u16 Unicode BMPコード、8byteの字形 |

レコードはコード昇順で重複なし。ファイル長は8+10Nちょうど。字形は上の行から8byte、各行のbit7が左端の画素。
