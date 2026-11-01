# KAGURA-9 LIVE SHOWCASE

HDMI上で自動進行する、KAGURA-9の紹介プレゼンテーションです。
日本語の疑似256色スライド、短い字幕を添えた実演、[PROJECT STARFALL](starfall.md)、桜吹雪を一つの流れで見せます。
PowerPointや動画の再生ではなく、PicoからFPGAの映像・音源をその場で駆動します。

## 流れ

| 章 | 見せるもの | 伝えること |
|---|---|---|
| A chip. A world. | タイトル | 小さなFPGAに、画と音を |
| Host × FPGA | 接続図 | ホストが指示し、FPGAが映像と音をHDMIへ出力 |
| Colour, by design | 疑似256色スライド | 8×8セルごとに16色、16パレットを使い分ける |
| 色と動き | プラズマ → トンネル | 絵を描き直さず、色の変化で動きを作る |
| 線と立体 | 4D超立方体 → ネオンリボン | 線描画と変わったタイルだけの転送 |
| Make it play | PROJECT STARFALL、自動操縦 | 装備・基地・ボス戦と6音源BGM・効果音 |
| All together | PSRAM・COPY・音源の解説 → 桜吹雪 | 256 sprite登録、ラスタ、PSRAM、PCMを重ねる |
| Your turn | 短いコードとリポジトリ案内 | ゲーム・音源・スプライトエディタへの入口 |
| Thank you | エンディング | 次のループへ |

表示時間の合計は約3分50秒。背景生成・音源読込み・フェードを含めて1周約4分です。
スライド7枚とゲーム素材の初回読込みは別です。ゲーム時刻は約59.94 Hzで進み、描画回数とは分離しています。
紹介スライドに表示する480p/720pは対応モードの説明で、このショーケース自体は480pで動きます。

「疑似256色」は任意の256色を各画素で選べる方式ではありません。1セルは16色、色0は共通背景です。
256 spriteは登録数で、同じ走査線では16個が上限です。これらの制約も画面に記載しています。

## 必要な構成

- ABI 0.6、480p（論理320×240）、FULL+PSRAMのFPGA構成。
- PicoのMicroPython v1.26とKAGURA SDK。QSPI 5 MHzを使用。実機確認はSDKを凍結した通常fw-ABCで行っています。
- `fonts/misaki8.kfnt`、`starfall_assets/`と`sakura_assets/`、`showcase_assets/`。
- このディレクトリの`showcase*.py`、`framebuffer_demo.py`、`starfall*.py`、`sakura*.py`。

代表的な素材とcapabilityを開始前に確認します。ゲームのBGMは6音源で合成し、PCMの実演は桜吹雪で行います。
RAMの余裕のため、RP2040では`mpy-cross -march=armv6m`で`.mpy`にして使ってください。
SDK・FPGA・ABI・MicroPython本体の変更や、専用のCファームウェアは不要です。
SDK全体を`/lib`やmountからRAMへ読む構成はメモリ条件が異なり、この紹介プレゼンでは未検証です。

## 起動

Pico上へ配置した場合は、既存コンソールを閉じてPIO資源を解放してから接続します。
`showcase.run()`自身が接続・終了時の解放を行います。

```python
kagura_console.close()
kagura_console = None
import gc
gc.collect()
import showcase
showcase.run()  # 既定は実機確認済みの1周。Q / Ctrl-Cで停止
```

Flashの空きが少ない場合は、PC上に`.mpy`と3つの素材ディレクトリを置き、`mpremote mount`で実行できます。
`showcase`のimport前にconsoleを閉じ、不要な参照を外してGCを行うとRAMを確保しやすくなります。

リポジトリのルートで、ビルド済みの`mpy-cross`を使って配置できます。WindowsではWSL内で実行するか、
`--mpy-cross`にWindows版コンパイラを指定してください。

```sh
python3 tools/prepare-showcase.py
```

この配置ツールが生成する`showcase_names.mpy`も必要です。初回に38,400 B領域を確保した状態で
各章の識別子を事前登録し、周回後も同じ大きさの連続領域を確保できるようにします。
MicroPythonの識別子テーブルはモジュールを解放しても残るため、空き総量だけでは不十分です。
生成テーブルを配置しないソース単体実行は`loops=1`に限定します。

```sh
mpremote connect COM7 soft-reset exec "import gc; kagura_console.close(); kagura_console=None; globals().pop('start', None); gc.collect()" mount build/showcase-live/run exec "import showcase; showcase.run(assets='/remote/showcase_assets', star_assets='/remote/starfall_assets', sakura_assets='/remote/sakura_assets')"
```

`build/showcase-live/run`は上のツールによる配置先です。リポジトリに生成済みビルドは含みません。

操作はSpace/Nで次の章、QまたはCtrl-Cで終了です。自動操縦のゲーム中も同じ操作です。
`loops=0`は実験的な繰り返し指定です。通常速度の2周目には下記のRAM制約があります。
背景・音源の読込み中は次へ進む操作を待つ場合があります。USBで`mpremote exec`から起動した場合は、
このチャットやホスト側から割込みを送り停止できます。終了後はsoft resetで通常コンソールへ戻せます。

```python
showcase.run(loops=1)              # 1周だけ
showcase.run(loops=2, speed=0.05)  # 配置・章間遷移の短縮確認。読込み時間は短縮しない
```

## 画面・音・メモリ

スライドはPCで日本語・図解を描き、既存の`send_image.py`と同じ量子化でKIMGへ変換しています。
実機では`kagura.image256.Slots.save_file/show`のストリーミングとPSRAM COPYを利用します。
プライベートな小型surfaceアダプタに必要な状態だけを持たせ、スライド用に38,400 BのCPU framebufferを保持しません。
描画実演の間だけ通常のTileFramebufferを確保します。

スライドはPSRAM `0x600000`以降の7スロット。桜吹雪のピアノ・オーロラ・静止背景、STARFALLの素材`0x690000`とは分離しています。
章ごとに不要なモジュールとバッファを解放し、PSRAMのスライドだけを残します。
前の章のスプライト、scroll、ラスタ表、パレットをスライド復帰時にリセットします。

桜吹雪の静止背景はPCで事前生成し、C版goldenと一致するタイル265枚とmapを`SCN1`ファイルへ保持します。
紹介プレゼンではCRC確認後に512 B以下のバッファでPSRAMの`0x680000`へ事前転送し、
実演開始時にCOPYします。桜吹雪のRAM使用量が大きい間は、背景ファイルを読んだり重複除去辞書を作ったりしません。
背景の画素は同一で、花びら、ラスタ、COPY、PCM、時間進行は通常の桜吹雪を実行します。
通常の`sakura.run()`は従来どおり実機で背景を生成します。

解説中は静かなPSG、描画実演は既存PSG曲、STGはC版STARFALLの6音源BGMと効果音、最後は桜吹雪のピアノです。
紹介プレゼン中はGCを有効に保ちます。ゲーム素材34,976 Bは初回に一度だけPSRAMへ転送します。

## 素材の再生成

```sh
uv run --with pillow --with numpy tools/gen-showcase-assets.py
```

WindowsではローカルのBIZ UDゴシックを利用します。他の環境では`--font`と`--bold`に手元の日本語フォントを指定できます。
フォントファイル自体は配布しません。字幕はリポジトリの美咲ゴシックを使用し、許諾・表示は[フォント資料](../fonts/README.md)に従います。
日本語の解説・図解・配色はジェネレータにあり、PNGプレビューは`build/showcase-preview/`へ出力します。
実機用KIMG・字幕・SHA-256一覧は`showcase_assets/`に保持します。

## 検証

2026-11-01のSTARFALL置換版はホスト279テスト、54モジュールのARMv6-Mコンパイル、CI分類チェックに合格しています。
Stage 1のC版との状態・描画・音源照合は[移植の検証](starfall.md#検証)を参照してください。
STARFALL単体の実機測定は[移植の測定値](starfall.md#実機測定2026-11-01)を参照してください。
[短縮2周](../../../docs/measurements/starfall-showcase-smoke-2026-11-01.txt)は全章を完走し、
STARFALL・桜吹雪のfaultは0でした。ゲーム本体は紹介カード表示中に読み、章開始後の準備は約0.125秒です。
識別子の事前登録により短縮2周のheap断片化は回避できました。
通常速度でも全章1周と2周目への復帰を確認しました。STARFALLは40秒で38.85描画更新/秒、
桜吹雪は40秒で59.20 displayed/s。どちらもsprite・音声・ERROR_CODEのfaultは0でした。
[通常速度ログ](../../../docs/measurements/starfall-showcase-full-cycle-2026-11-01.txt)を保存しています。
その後、**通常速度の2周目の描画章では38,400 Bの連続確保が再び失敗**しました。
短縮2周の合格は通常速度での連続再生を保証しません。長時間周回の断片化対策は未解決です。
確実な1周再生・録画にはsoft reset後の`loops=1`を使用してください。

UGREEN 15390で通常速度の全章をHDMI録画し、代表フレームの目視と完成動画の全編デコードを確認しました。
[録画条件と結果](../../../docs/measurements/kagura-showcase-capture-2026-11-01.md)を参照してください。

`tests/test_showcase.py`は全KIMGのCRC・パレット規則、tile 1023/1024境界を含むCOPY、
別デモからの表示復帰、章順、2周、Q/Ctrl-C/例外後の消音と表示停止を検証します。
ホストテストは画音の実機品質や実際の表示速度を保証するものではありません。

以下は2026-10-31のSTAR RUNNERを含む旧構成の結果です。STARFALL置換版の実機結果とは区別してください。
旧構成で全ホスト269テスト、全47モジュールのARMv6-Mコンパイル、CI分類の自己テストは成功しました。
疑似256色の量子化後プレビューも確認済みです。実機では最終構成で全章の短縮2周を完走しました。
桜吹雪は両周ともPASSで、PCMアンダーラン・spriteオーバーフロー・line underrun・ERROR_CODEは0でした。
短縮試験の更新速度は通常速度の性能測定には使いません。背景はC版goldenと一致します。

通常速度でも全章を1周完走し、2周目への復帰を確認しました。RP2040 125 MHz、QSPI 5 MHz、
480p FULL+PSRAM（CAPS 0x5b）、SDK凍結の通常fw-ABC、`.mpy`をmountした構成です。
桜吹雪の40秒間は2367 COMMIT適用確認・59.16 displayed/s、音声・sprite・line underrun・ERROR_CODEは0でした。
これは紹介プレゼンの構成での結果で、他の起動条件の性能保証ではありません。
[短縮2周ログ](../../../docs/measurements/showcase-smoke-2026-10-31.txt)と
[通常速度1周ログ](../../../docs/measurements/showcase-full-cycle-2026-10-31.txt)を保存しています。
外部の映像キャプチャ・音声録音による品質比較は行っていません。

初期のmount実行では、大きなmemoryviewを`RemoteFile.readinto`へ渡すと、通信開始後の一時コピーがRAM不足になり、
USBのリモートFS通信が途中で止まる問題を確認しました。背景はPSRAMへの事前配置、ピアノは小さいbytearrayによる
読込みへ変更しています。元のピアノ22音はC版golden一致を保っています。
2026-10-31の検証ではFlashを書き換えていません。2026-11-01はユーザー承認で既存MicroPythonへ復元しています。
