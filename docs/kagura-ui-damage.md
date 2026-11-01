# KAGURA-UI 複数damage矩形

2026-11-02、main `b02a6ef`から`feat/kagura-ui-damage-rects`で実施。
引き継ぎロードマップ（`docs/claude-handoff`の`docs/KAGURA_ROADMAP.md`）のP1「damage領域最適化」。**PC検証のみで、RP2040実機は未計測**。

## 変更

`App._damage`は単一外接矩形から、最大`damage_limit`個（既定4）の矩形listになった。

- 重なる矩形、または辺を共有する矩形は結合する。角だけ接する矩形は結合しない。
- 上限を超えたら、新しい矩形を面積増加が最小の既存矩形へ結合し、再度重なりを判定する。
- stepは各矩形をclipにして背景fillと木全体の再合成を行い、flushはframe当たり1回のまま。
- 描画用と受付用の二つのlistを交換し、描画中のinvalidateは次frameへ残す。
- 描画・flushで例外が出た場合、そのframeの全矩形をdamageへ戻して伝播する。SDK dirtyも従来どおり保持。
- `damage_limit=1`は従来の単一外接矩形と同じ。比較測定やrollback用に残した。

SDKのdirty tile tracker、Framebuffer、転送、FENCE、RTL、ABIは変更していない。
tile trackerを複製せず、UI側は矩形のclipだけを増やした。

### 代償

- 矩形数だけtree走査が増える。widgetはclip外で打ち切るが、走査自体のCPU時間はRP2040で未計測。
- 矩形境界で字形が部分clipになると、glyph8ではなく従来の行単位描画になる。
- `_add_damage`は矩形tupleを生成する。allocation回数は従来どおり未計測で、allocation-freeとは主張しない。

## 検証（PC）

| 項目 | 結果 |
| --- | --- |
| `test_ui.py` | 38件PASS（既存33＋新規5、うち1件は実機benchmarkのPC実行）。既存の`_damage`参照はlist形式へ更新 |
| 新規: 離れた2 widget | 間のsentinel pixelを描き直さない。`damage_limit=1`では描き直す |
| 新規: 結合規則 | 重なり/辺共有/角接触/上限超過/画面clipの各期待値 |
| 新規: 40操作の乱数列 | 移動/非表示/日本語Label/Tab/List操作とflush失敗再試行で、limit 4とlimit 1の全pixelが毎step一致。最後に全画面再描画しても不変 |
| 新規: SDK dirty | 実TileFramebuffer（register model）で離れた2 Label更新のtile数がlimit 1より少なく、decode結果は一致 |
| mutation確認 | 先頭矩形だけ描画する改変で、新規2件がFAILすることを確認後に復元 |
| `ui_runtime.py` | CPythonとunix MicroPython v1.26（`4ce2dd2`）のCRCが一致。origin/mainの出力とも同一（4231501191/2117273149/26039419） |
| `ui_glyph_runtime.py` | CPython/unix MicroPython一致（288, 2456019654, 1936776583） |
| ARM | `mpy-cross -march=armv6m`でui/*.pyとtest_ui.pyをcompile |
| 他回帰 | framebuffer/frozen_alignment/link、`tools/test-ci-changes.sh` PASS |

### dirty tile比較

`python -I tools/compare-ui-damage.py`。既存`ui_benchmark`のworkload各32 samplesを
register model上で実行し、SDKが転送したtile数とpattern payload byteを比較する。
決定的な数で、時間ではない。CIでも実行し、最終bufferのCRCが異なれば失敗する。

| workload | limit 1 tiles / B | limit 4 tiles / B |
| --- | --- | --- |
| idle | 0 / 0 | 0 / 0 |
| label | 53 / 1696 | 53 / 1696 |
| button | 287 / 9184 | 272 / 8704 |
| focus | 1440 / 46080 | 960 / 30720 |
| move | 620 / 19840 | 620 / 19840 |
| scroll | 786 / 25152 | 774 / 24768 |
| screen | 38400 / 1228800 | 38400 / 1228800 |

最終buffer CRC32は両方2644429476。focusはButton（x=8）とListView（x=200）の間にある
Panelと空白を再描画しなくなり、tile数が約33%減った。
label/move/screenは元々単一矩形なので変化しない。静止の転送ゼロは維持。

## RP2040比較（準備済み・未実施）

**実機測定はまだ行っていない。** dirty tileが減ってもframe時間が短くなるとは限らないため、merge判断は実機値で行う。

### 方法

`tools/kagura-ui-damage.py run`と`examples/ui_damage_benchmark.py`を使う。

- 既存firmware（#51以降、glyph8あり）のまま実行する。firmware、Flash、ファイルシステムには書き込まない。
- このcheckoutの`kagura/ui/app.py`だけを、相対importを絶対importに変えてraw REPLでsource送信する。
  RAM上の`App`を**limit 1と4の両方**で使うため、frozenとRAMの差は比較に入らない。
  他のUI moduleとSDKはfrozenのまま。本変更ではapp.py以外のUI/SDKは変わっていない。
- SDKクラスへのpatchは行わない。Phase 2で停止した補助診断は、SDKクラスを一時patchする方式だった。
- 1つのApp、1つのFramebuffer（38400 Bの確保は1回）、1つのwidget木を使う。各（round, limit, workload）は
  同じreset状態から始める。roundごとにlimitの順を入れ替え（1,4 / 4,1）、時間経過による偏りを分散させる。
- workload:

| workload | 内容 |
| --- | --- |
| idle | 変更なし（転送0を確認） |
| label | 1 Label（単一矩形の対照） |
| button | Enterで押下し、離れたLabelを更新 |
| focus | Tabで、x=8のButtonとx=200のListViewを往復する |
| labels | 画面の対角にある日本語Label 2個（text-heavy、離れた矩形） |
| glyphcut | 8 px格子からずれたbadge 2個が日本語4行のblockと重なる。limit 4では矩形境界が字形を切り、行単位描画になる |

- sampleごとの測定値:
  - frame: `App.step`全体
  - flush: SDKの`total_us`
  - cpu: frame − flush（入力・layout・描画を含む）
  - tiles、pattern payload byte
  - heap: step前後の`gc.mem_free()`差。増加したstepはGC観測として数え、差分から除く。VMのGC回数やallocation回数は取得できない。
- 各workloadの後に落ち着くまでstepし、CRC32を取る。続けて全画面を再描画し、同じCRCであることを確認する。
  limit 1と4のCRCも一致を確認する。最後にViperとPythonで全画面のCRC一致を確認する。
- 終了時に`REG_ERROR_CODE`を読み、`check_errors()`、console復帰（paused=False / attached=True）を検査する。
- PCでは`test_ui.py`がregister model上で同じmoduleを実行し、CRC一致、focus/glyphcutのtile減少、集計を検査する。

### 手順

Windows venvに`python -m pip install mpremote==1.29.0 pyserial`を用意する。他のUSB端末は閉じる。
COMとUSB serialは実物と照合し、localで入力する（実値をcommitしない）。

```powershell
python -m serial.tools.list_ports -v
$picoPort = Read-Host '実物と照合した対象PicoのCOMポート'
$picoSerial = Read-Host '実物と照合した対象PicoのUSB serial'
python tools/kagura-ui-damage.py run --port $picoPort --expected-serial $picoSerial --samples 32 --rounds 4 --log build/ui-damage/device.txt
python tools/kagura-ui-damage.py summarize build/ui-damage/device.txt
```

logの`HOST_SOURCE`には、送信したapp.pyとbenchmarkのSHA256、git commitが記録される。
run中はUSB COMとHDMIを占有する。異常時は実行中のloopを中断し、App.closeでconsoleを戻す。

### merge判断の基準（提案）

- 全workloadでCRC一致、`DAMAGE_FPGA_ERROR_CODE 0`、console復帰。
- focusのframe p50が、全roundで明確に短縮していること。
- label/button/labels/glyphcutのframe p50・p95が、limit 1に対して大きく悪化しないこと。
  round間のp50範囲を超える悪化があれば原因を調べる。特にglyphcutは行単位描画の代償が出る候補。
- 悪化するworkloadがあれば、既定値を下げる、または辺共有・近接矩形の結合規則を見直してから再測定する。

## 実機で未確認の事項

- 上記RP2040比較の全項目（frame/CPU/flush時間、heap、ERROR_CODE、console復帰）。
- 長時間soak、Pico 2/2 W、UART/HIDは本変更でも未検証。
