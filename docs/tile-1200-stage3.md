# 第3段階：実機数値検証と文字キャッシュ

実験ABI 0.6の残作業。[第2段階](tile-1200-stage2.md)のRTLを変更せず、Picoによる数値受入、文字キャッシュ、未実行だった回帰・依存検査を進める。ユーザー指定により数値検証を先行し、画面の目視と音質の聴感は未確認として区別する。

## 実機の扱い

- 接続：Tang Nano 9K（chip ID `0x1100481B`）＋Pico、COM7、QSPI 5MHz（今回の実測）。
- Picoは既存のcustom MicroPython 1.26.0を使用する。firmwareの書換えは行わない。
- 既存`/lib/kagura`を上書きせず、実験用SDKを`/lib/kagura1200`へ配置。試験コードを`/tile1200_accept.py`へ配置し、Pico側のSHA-256をPCのsourceと照合する。
- FPGAはGowin ProgrammerのSRAM Program and Verify（`--run 4`）で一時構成する。内蔵Flashへは書き込まない。
- 数値試験はportable Python packerを使う。native/Viperの高速化有無を判定条件にしない。

## 数値試験

`software/micropython/examples/tile1200_accept.py` は全1,200枚の異なるpattern、BGの上位bit表、palette／flip、11bit OAM、FILL／COPY境界、PCM 2ch＋6ch PSG、描画中のCOPYと読戻しを検査する。無効番号1200／2047も描画負荷へ入れるが、実機でその画素を観測したとは扱わない。

起動時は全19 bankの先頭・末尾patternとmap／上位表／palette／wave／OAMのサンプル（計2752 B）が0であることを確認する。全量モードは38,400 Bを転送前後で照合し、pattern CRC32の期待値は`2221330119`。短時間モードは境界patternの320 Bとmapの先頭・末尾を照合する。

連続区間はFRAME_COUNTを3秒以内ごとに読み、8bit wrapを積算する。PCMのACTIVE、UNDERRUN／CONFIG_ERROR／MEMORY_ERROR、音声FIFO、ERROR_CODE、sprite overflowを監視する。GC後の空きメモリも定期記録する。FRAME_COUNTの約60HzはFPGA映像frameの進行であり、Picoの描画更新loopのfpsではない。

## 実測結果（2026-10-29）

QSPI 5MHz、CPU 125MHz、既存custom MicroPython 1.26.0で実施。全4構成のSRAM Program and Verifyが成功した。画面・音質を観測したという判定は含めない。

| 構成 | 連続区間 | pattern読戻し | PCM | 結果 |
|---|---:|---|---|---|
| qspipsram720 | 3600.308秒 | 全1200枚・38400 B、開始前と終了後 | 2ch＋PSG 6ch | 合格 |
| qspi | 60.034秒 | 境界10枚・320 B | PSG 6ch | 合格 |
| qspi720 | 60.097秒 | 境界10枚・320 B | PSG 6ch | 合格 |
| qspipsram | 60.312秒 | 境界10枚・320 B | 2ch＋PSG 6ch | 合格 |

主試験は9,058回の描画更新loop／PSRAM COPY、描画中の298,914 Bの読戻し、映像frame 216,017（60.000 Hz）を記録した。最終CRC32は`2221330119`で初期値と一致。ERROR_CODEと音声FIFO状態は全監視で0、PCMのfault bitは0でACTIVEを維持した。GC後の空きメモリは最初の1回が105,920 B、その後は105,888 Bで一定。setup・最終全量照合はこの連続時間に含めない。

`qspipsram`の480pでは実フォントから異なる1073字を流し、1072枠（tile 128～1199）を使い切った後の1字が`?`になること、全map番号、1024／1199の字形payloadを読戻し照合した。TextLayerも1023／1024跨ぎと1199、palette 15、矩形外bit保持、満杯時のI/O 0を確認。READ_READYとBAD_ACCESSを残した状態から再接続し、未読結果を消費しつつsticky faultを保持し、その後の新しいreadが成功した。

主試験のSDKは`a85f657`、fixtureとrunnerは`cb987b7`。480p PSRAMの短時間試験はPCMデータ生成の一時メモリを抑えた`23bd23f`、文字キャッシュ・再接続試験はSDK `298341a`とfixture `0d0af8a`を使う。実機の既存`kagura` packageを保持するため、文字キャッシュ試験の配置時だけ`kagura1200`／`kagura_ja1200`へimport名を置換し、配置後のSHA-256を照合した。bitstream・各配置file・生ログのhashと実測値は[機械可読結果](tile-1200-stage3-results.json)に保存する。

480p PSRAMの短時間試験の初回は、fixtureの4096 byte iterable生成中にPicoのMemoryErrorで中断した。FPGAのfaultは観測されていない。128 byte周期を32回繰り返す同一データへ変更し、終了済みfixtureを解放して再実行した。1時間の主試験は変更前fixtureで正常終了しており、その結果を差し替えていない。

全RTL回帰61件、SDK 122件がすべて合格。公式MicroPython v1.26.0のPIO assemblerと美咲フォント原本を利用し、skipは0。C／ca65ヘッダ検査、全SDK・exampleのarmv6m bytecode compile、Pico CホストのRelease build、生成物・設計検査・CI分類も成功した。旧FILL timing試験の「0x9000は未実装」という期待を更新し、新領域・穴跨ぎの境界検査を追加した。RTLは第2段階から変更していない。

生ログは`reports/tile1200-hardware/`、回帰ログは`build/tile1200-*.log`と`build/verilator/`（Git管理外）。

## 文字キャッシュ

- terminalのglyph poolを128〜1199の1,072枚へ拡張。参照数・owner・shown cellは11bit番号を保持する。
- Pico実機で多数の字形を登録すると、可変長dictの拡張時に連続メモリを確保できないことが判明した。字形検索を1024 bucket＋1072 linkの16bit固定配列（計4192 B）へ変更し、衝突・途中slotの再利用・resetを回帰検証する。
- terminalは40 cell＝上位表5 byteを行単位で専有し、その値を記憶する。ASCII等で上位bitが変わらない場合は追加I/Oを行わず、変更時も読戻しなしで5 byteだけ更新する。
- `kagura_ja.TextLayer` は1199までの範囲を指定でき、1023／1024を跨ぐ字形転送を分割する。map wordのpaletteとtile bit10を分離し、矩形外の上位bitを保持する。
- TextLayerは上位bitが変わる行だけ上位表を更新する。従来の低い番号だけを使う通常更新へ不要な読戻しを加えない。
- 満杯・1199・palette保持・隣接bit保持・高位番号の参照解放をテストする。

## 再接続

実機試験の中断で、前ホストのREAD_RESULTがFPGAに残った状態から新しいホストを接続するとREAD_COLLISIONになることを確認した。`probe()`はREAD_BUSYの完了を待ち、未読結果とREAD_DONEを消費してsessionを開始する。要求の再送やsticky ERROR_CODEの消去は行わない。

## 再現

Picoのアプリとコンソールを停止し、PIO接続を解放してから実験用SDKを配置する。FPGAのbitstreamとPicoのmodeを合わせる。例えばPico上で:

```python
import tile1200_accept
result = tile1200_accept.run(seconds=3600, mode='qspi', sdk='kagura1200', full=True, cold=True)
```

`cold=True`はFPGAのSRAM再構成直後だけ指定する。`full=False`は短時間の境界確認で、全1,200枚の読戻しを行ったとは扱わない。全量readはこのPython hostで1byteあたり約6.5msかかり、setupと最終照合は連続区間の時間に含めない。

Windowsのstreaming runner:

```powershell
./tools/tile1200-device.ps1 -Port COM7 -CodeFile run.py -LogFile result.log -TimeoutSeconds 5400 -StopFile stop.flag
```

`stop.flag`を作るとCtrl-Cを送る。中断・timeout時はPicoの処理終了を確認してから次の操作へ進み、失敗した操作を自動再送しない。最終結果の判定はJSONのpassだけでなく、runnerがstderrなしで終了したことも確認する。

## 試験後の復帰

Gowin `--run 1`で変更していないFlash内構成を再読込みし、元のABI 0.5・CAPS 0x7B・ERROR_CODE=0を確認。Picoのsoft reset後、既存boot.pyのHDMIコンソール（QSPI 5MHz、UART0 RX GP1 115200 baud）とUSB promptが起動した。実験用fileは隔離名のまま残し、既存packageやfirmwareを上書きしていない。

## 残る目視・聴感

BG／spriteの表示内容、反転・paletteの見え方、音質・音切れ、複数sink／ケーブル、物理reset・抜挿は数値検証で置き換えない。standalone demoはdeprecatedとし、これらの確認もPicoホストを使う。
