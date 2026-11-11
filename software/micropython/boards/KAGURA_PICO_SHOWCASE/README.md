# KAGURA_PICO_SHOWCASE

`KAGURA_PICO`に[紹介プレゼンテーション](../../examples/showcase.md)を組み込んだRaspberry Pi Pico用ファームウェア。リリースの標準ファームウェアとして配布する。

- SDK（`kagura/`）、`kagura_ja`、ショーケースの17モジュールを凍結（frozen）する。バイトコードと識別子がFlashに残るため、`.mpy`をmountする方法よりheapが空く。
- スライド・ゲーム映像・ピアノ音源・美咲フォントは読取り専用のROMFSへ置き、`kagura_showcase`が`/rom`へmountする。
- デスクトップと音源のCモジュールは`KAGURA_PICO`と同じ。

## Flashの配置（2 MB）

| 範囲 | 大きさ | 内容 |
|---|---|---|
| `0x10000000`〜 | 960 KB | ファームウェア |
| `0x100F0000`〜 | 576 KB | ROMFS（`MICROPY_HW_ROMFS_BYTES`） |
| `0x10180000`〜 | 512 KB | ファイルシステム（`MICROPY_HW_FLASH_STORAGE_BYTES`） |

`KAGURA_PICO`（ファイルシステム1,408 KB）と配置が違う。どちらの向きに書き換えても、ファイルシステムは初回起動で作り直され、中のファイルは消える。

## 実行

FPGAはABI 0.6の`qspipsram`（480p、PSRAM）、PicoはQSPIで配線する（[Pico firmware](../../../pico/README.md#配線)）。

```python
import kagura_showcase
kagura_showcase.run()   # 約4分の1周。Space/Nで次の章、Q/Ctrl-Cで終了
```

`boot.py`がHDMIコンソールを作っていれば、開始前に閉じる。1周ごとにsoft resetする（`loops=1`のみ。繰り返しは[メモリの制約](../../examples/showcase.md#検証)があり未対応）。

## ビルド

```sh
make -C ports/rp2 BOARD=KAGURA_PICO_SHOWCASE \
  BOARD_DIR="$KAGURA_ROOT/software/micropython/boards/KAGURA_PICO_SHOWCASE" -j4
```

続いてROMFSを作り、ファームウェアと1本のUF2にまとめる。MicroPythonソースに同梱のmpremoteから`romfs.py`だけを読み込む（CIも同じ手順）。

```sh
python3 tools/make-showcase-firmware.py \
  --firmware "$MPY/ports/rp2/build-KAGURA_PICO_SHOWCASE/firmware.uf2" \
  --out kagura-pico-showcase.uf2 --romfs-py "$MPY/tools/mpremote/mpremote/romfs.py"
```

`$MPY`はMicroPython v1.26.0のソース。

UF2はファームウェアの末尾からROMFSの先頭までを消去済みページで埋め、連続した1つのイメージにしている。間を空けたUF2では、RP2040のBOOTSELでROMFSの大半が書かれなかった（2026-11-12、実機）。
