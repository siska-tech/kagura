# PROJECT STARFALL — MicroPython

[C版Stage 1](../../starfall/README.md)の再移植です。ショーケースのSTAR RUNNERを置き換えます。
機体・編隊・基地・装備ゲージ・レーザー・オプション・部位別ボス・タイトル・アトラクトと、
オリジナル10曲のBGMを移植しています。Stage 2〜6はC版同様に未実装です。
共通SDK、MicroPython本体、ABI、FPGAは変更しません。

## 起動

ABI 0.6、SPR16、PSRAM、180/240ライン。音楽はHDMI_AUDIOとWAVEが必要です。
実機ではARMv6-Mの`.mpy`を使います。配置は次で生成できます。

```sh
python3 tools/prepare-showcase.py
```

既存コンソールを閉じたMicroPythonで:

```python
import starfall
starfall.run(autoplay=True, duration=40)  # C版と同じ自動デモ
starfall.run()                          # 手動プレイ、Q / Ctrl-Cで終了
```

PCからmountする場合は`assets='/remote/starfall_assets'`を指定します。
手動操作はWASD、Space/Enterで開始・発射、Xで装備発動。USB端末の文字入力は140 ms保持されます。
同時押し・キー離しを厳密に扱うゲームパッド入力ではありません。
`input_fn`を渡せばC版と同じ6bitの入力を直接渡せます（LEFT1/RIGHT2/UP4/DOWN8/FIRE16/EQUIP32、QUIT64）。

ショーケースではSpace/Nで次章、Qで全体停止。C版の40秒アトラクトを実行します。

## 起動とフレーム処理

- PCMの大容量BGMは読みません。C版の6音源（pulse/noise/wave）で曲と効果音を合成します。
- C版から生成した映像素材は **34,976 B**。512 B以下の実bytearrayでストリームし、CRCを確認します。
- ショーケースの初回準備中にPSRAM `0x690000`へ配置し、ゲーム章の開始時はCOPYを使います。
  スライド7枚と桜吹雪のキャッシュには重なりません。単体起動時だけ素材を転送します。
- Q8整数の59.94 Hzゲーム処理、固定数の敵・弾・爆発プール、固定512 B OAM。
  変更したOAMの最初〜最後を1回の転送にまとめ、背景は画面外の1列32 Bだけ更新します。
- ゲーム処理はnative、OAM文字・走査線判定・差分・音楽計算はViper。映像COMMITを音源更新より先に送ります。
  16 sprite/lineを超える弾は衝突前に除外し、レーザーの表示長と当たり判定をそろえます。
- GCは有効のまま。通常VMのheap純増と総確保回数は測定していません。
- 表示回数とゲームのtickを分離。描画が遅れた場合も経過時間に応じて衝突処理を含むtickを実行します。
  1回の追い付きは最大4tickで、残りは次回へ繰り越します。`lag_max_ticks`はその積み残しの最大値です。

`ready_us`は`run()`呼出しから準備完了までで、モジュールのimport時間は含みません。
`cached=True`の場合は先行する素材転送時間も含まれません。
結果の`frames`は完了を待った映像COMMIT数。`cpu_*`はゲーム＋描画、`present_*`は
前COMMIT待ち・映像転送・音源更新を含む時間です。純粋な通信時間とは異なります。
実際の更新率は`frames * 1e6 / elapsed_us`で求めます。60 Hzの処理設計と実測速度は区別してください。

## 検証

`tests/test_starfall.py`は変更していないC版をホストコンパイラで直接リンクして照合します。

- 180/240ライン × 通常プレイ/自動デモ × 各4,000tick: 計16,000tickの28状態値と512 B OAMが一致。
- ミサイル・ダブル・レーザー・オプション・シールドを含む通常プレイと、基地・ボスへの進行。
- 背景400列 × 2解像度の一致、10曲 × 420tickの音源出力・発音停止が一致。
- 差分OAM、画面外mapリング、タイトル復帰、Q/Ctrl-C/例外時の消音・表示停止。
- 元C素材・生成バイナリのSHA-256、CRC、PSRAM領域の分離。

全ホスト279テスト、54モジュールのARMv6-Mコンパイル、CI分類チェックに合格しています。
ホスト比較は実機の速度・画音品質を保証しません。

## 実機測定（2026-11-01）

ユーザー承認によりPicoへ既存の通常MicroPython v1.26.0 `fw-ABC`を復元しました。
RP2040 125 MHz、QSPI 5 MHz、480p FULL+PSRAM、CAPS 0x5b、GC有効、ARMv6-M `.mpy`を
`mpremote mount`で読む条件です。FPGA・ABI・MicroPython本体・共通SDKのソース変更はありません。

| デモ | import | ゲーム準備 | 合計 | 描画更新 |
|---|---:|---:|---:|---:|
| 旧STAR RUNNER | 2.02秒 | 23.70秒 | 25.72秒 | 29.75更新/秒（15秒） |
| STARFALL | 4.66秒 | 1.82秒 | 6.47秒 | 42.65更新/秒（45秒） |

合計はモジュール読込み開始からゲーム準備完了までで、最初の描画フレームまでの時間とは異なります。
STARFALLの45秒は1,920描画COMMIT、2,697 simulation tick、積み残し最大0tick、最大16 sprite/line、
sprite overflow・audio fault・ERROR_CODEは0でした。ゲーム時刻は約59.9tick/秒で進みます。
CPU時間は平均8.58 ms・最大61.7 msで、常時60描画更新/秒を達成した結果ではありません。
旧作と新作はゲーム内容も測定区間も異なるため、同一処理の厳密なA/Bベンチマークではありません。
各デモの起動待ちと実際の描画頻度の比較です。

ショーケースでは素材を最初に一度だけPSRAMへ転送し、ゲーム本体のimportは紹介スライドの表示中に行います。
大きなnativeコードは描画章より前には読まず、38,400 Bの連続フレームバッファ領域を確保できる順序にしています。
周回用の識別子テーブルも配置ツールで生成し、この領域を確保したまま事前登録します。
短縮2周ではゲーム章の準備が約0.125秒で、STARFALL・桜吹雪ともfault 0で完走しました。
この1秒のゲーム章はintro部分なので、戦闘中の性能測定には使用しません。
通常速度のショーケース内では40.03秒に1,555描画（38.85更新/秒）、2,398 simulation tick、
積み残し最大1tick、準備0.127秒で、sprite overflow・audio fault・ERROR_CODEは0でした。
単体実行とはheapの配置・空き量が異なるため、単体の42.65更新/秒と区別します。
測定ログは[STARFALL](../../../docs/measurements/starfall-micropython-2026-11-01.txt)と
[旧STAR RUNNER](../../../docs/measurements/star-runner-comparison-2026-11-01.txt)、
[短縮ショーケース2周](../../../docs/measurements/starfall-showcase-smoke-2026-11-01.txt)、
[通常速度1周](../../../docs/measurements/starfall-showcase-full-cycle-2026-11-01.txt)を参照してください。
その後UGREENで全編をHDMI録画しました。[録画条件と結果](../../../docs/measurements/kagura-showcase-capture-2026-11-01.md)。
録画は代表フレームの目視と全編デコードを確認していますが、厳密な色・音声同期の比較試験ではありません。

素材の再生成（ホストC11コンパイラのみ必要、Flash操作なし）:

```sh
python3 tools/gen-starfall-mpy-assets.py
python3 -I software/micropython/tests/test_starfall.py
```

元C版のアルゴリズムや素材を変えた場合は、生成と比較を再実行してください。
