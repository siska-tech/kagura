# KAGURA-UI focus候補走査の割当削減

2026-11-02 JST。[複数damage矩形](kagura-ui-damage.md)（#53）の後続。
引き継ぎロードマップP1「focus描画負荷削減」のうち、候補探索のallocationを扱う。

## 問題

`FocusManager`は再帰generator（`yield from`）と、ノードごとのclip tupleで木を走査していた。

- `dispatch()`は、すべてのeventで`repair(force=True)`による全走査を行う。Tabではさらに`move()`がもう一度走査する。
- ListViewの上下キーのようにwidgetが消費するeventでも、走査は行われる。
- `set_text`などのrelayoutの後も、次のstepで走査する。

unix MicroPython v1.26（64-bit object）で測ったTab 1回の`dispatch`のheap割当（`gc.mem_alloc()`差、GC無効）:

| focus可能widget数 | 変更前 | 変更後 |
| --- | --- | --- |
| 4 | 6976 B | 392 B |
| 16 | 22304 B | 436 B |

変更後の残りは、focus変更に伴うdamage矩形のtuple。走査と`repair()`の割当は0 B。

## 変更

- 走査結果を、再利用するlist（`found[:count]`）へ書き込む。clipは整数4個を引数で渡し、tupleを作らない。
- 子の走査は添字のwhile loopで行い、list iteratorを作らない。`max`/`min`の組込み関数呼出しは比較に置き換えた。
- 走査後、前回より後ろのslotを`None`にし、取り除いたwidgetを参照し続けないようにした。
- `move()`は、同じeventの`repair()`の走査結果を再利用する。ただし、handlerがtree・有効状態・layoutを変えた場合（`focus.dirty`）は走査し直す。
- 公開API、focus順序、非表示/無効/clip外の除外、押下解除、逆Tabの動作は変えていない。
- `FocusManager.candidates()`は非公開classのmethodで、戻り値をgeneratorから件数に変えた。repo内の利用者はテストのpatchだけ。

## 検証

### PC

| 確認 | 結果 |
| --- | --- |
| `test_ui.py` | 40件PASS（main 33件、#53で+6、本変更で+1）。新規: handler内で有効状態を変えたときの再走査、逆Tab、除去したwidgetの非保持、root無し |
| mutation | `move()`が常に前回の結果を再利用する改変で、新規testがFAILすることを確認 |
| `tests/ui_focus_alloc.py`（unix MicroPython） | 走査/repairが0 B、Tab配送が1024 B以下であることをCIで検査 |
| `ui_runtime.py` CPython vs unix MicroPython | 一致。CRCはmainと同一 |
| 走査時間（unix MicroPython、16行、相対値） | 65 µs → 50 µs |

### RP2040

RP2040 125 MHz、#51のfirmware（変更なし）、QSPI 4 lanes / 5 MHz、Viper有効。
[複数damage矩形](kagura-ui-damage.md)と同じ`tools/kagura-ui-damage.py`で、32 samples × 4 rounds。
同じsessionで、ベースラインと変更後を続けて実行した。各runは、送信したapp.pyだけが異なる。
logの`git=`はmainへのrebase前のcommit。送信したapp.pyのsha256は、このbranchのapp.pyと一致する。

| run | app.py | log |
| --- | --- | --- |
| base | `57b9dea`（#53）、sha256 `84947a7f…` | [focus-rp2040-base.txt](kagura-ui-logs/focus-rp2040-base.txt) |
| scan | 本変更、sha256 `3e5bc648…` | [focus-rp2040-scan.txt](kagura-ui-logs/focus-rp2040-scan.txt) |

`damage_limit=1`（既定）の結果:

| workload | frame p50 base → scan | frame p99最大 base → scan | heap/step p50 | GC観測 |
| --- | --- | --- | --- | --- |
| label | 21.5 → 21.0 ms（−2.3%） | 24.2 → 22.7 ms | 2768 → 1616 B | 0 → 0 |
| button | 39.0 → 37.5 ms（−3.9%） | 53.5 → 40.8 ms | 5520 → 3216 B | 4 → 0 |
| focus | 42.5 → 38.7 ms（−9.0%） | 57.0 → 44.2 ms（−22%） | 5600 → 3264 B | 4 → 0 |
| labels | 45.9 → 45.3 ms（−1.2%） | 49.3 → 46.7 ms | 4448 → 3296 B | 4 → 0 |
| glyphcut | 342 → 342 ms | 同等 | 32000 → 32000 B | 28 → 28 |

- `damage_limit=4`でも同じ傾向（focus 42.3 → 38.6 ms）。
- p99の短縮は主に、32 sample中の自動GCがなくなったことによる。p99は32 samplesの値であり、長期の最悪値ではない。
- GC観測は、step前後で`gc.mem_free()`が増えた回数。VMのGC回数ではない。heap/stepも、同じ方法で測ったGCで見えるheap差分。
- 全workloadでCRC一致（incremental＝全画面再描画、limit 1＝4、Viper＝Python 3228843279）、`ERROR_CODE 0`、console復帰。
  HDMI（UGREEN 15390）でも表示崩れのないことを確認した。
- `max`/`min`を置き換える前の版（`65ac3f9`）では、labelが+0.3 ms遅かった。置き換えた後は全workloadで同等以上。

## 残る課題

- glyphcutの1回あたり32 KBの割当は、部分clipで字形を行単位描画する経路によるもの。
  後続で1回のglyph8にし、9.9 KBになった（[glyph cache記録](kagura-ui-glyph-cache.md#部分clipの字形)）。
- 字形の取得は1文字約1.9 ms、SDK `fill_rect`は1呼出し約1 msの固定費がある。いずれもframe時間の大部分を占める。
- 長時間soak、Pico 2/2 W、UART/HIDは未検証。
