# P1-06 BSRAM mode・byte RMW・dual-clock RAM評価 / 2026-10-23

BSRAM評価の受入条件: 構成ごとに予定数のBSRAMへmap、C版TDPでsystem/pixel clock配置成功、同時同一addressアクセス禁止assert合格。対象は[Memory Map](memory-map.md)の25ブロック案。

## Wrapper（`rtl/memory/`、`rtl/vdp/`）

いずれも推論記述で、配列と読出しregisterにresetを持たない。読出しは1 edge latency。

| module | 用途 | 契約 |
|---|---|---|
| `kagura_ram_sp` | pattern、wave、command | 1 clock。書込み中のrdataは旧値（read-before-write）だが、呼び出し側はread-during-writeの値に依存しない |
| `kagura_ram_rmw16` | map、OAM、palette | `kagura_ram_sp` 1024×16＋CPU byte write。word read/writeは1 edge。byte writeはread→merged word登録→write backの3 edgeで、その間`req_ready`=0のため他のアクセスが割り込まない |
| `kagura_ram_sdp` | audio FIFO用の512×32 | write clockとread clockが独立 |
| `kagura_ram_tdp` | line bank | port Aはsystemで読み書き、port Bはpixelで読出し。port Aは書込み中rdataを保持する（normal mode）。C版DPBはread-before-writeを受け付けない（PA2122）ため |
| `kagura_line_banks` | line bank 2面 | systemは裏bankだけに書き、最後の書込み後にready toggle。pixelは行境界でreadyを見たときだけ表示bankを切り替え、来ていなければ同じ行を再表示してsticky underrun（初回の受け渡し前は数えない）。systemは切り替わった表示indexが同期器を通って見えてから新しい裏bankへ書く |

同時同一addressの禁止は2段で検査する（simulationのみ。Gowinは`SYNTHESIS`を定義しないため`// synthesis translate_off`でも除外）。
- `kagura_ram_tdp`: port Aの書込みとport Bの読出しが同じaddressで`COLLISION_NS`（既定5ns）より近ければ数える／`$fatal`。
- `kagura_line_banks`: systemの書込みが表示中のbankへ向かうか、受け渡し中（filled）なら`$fatal`。addressに依存しない所有権の検査。

## Simulation（Verilator 5.032、`tb_bsram_wrappers`）

実機と同じ周期（system 18.518ns、pixel 39.683ns）。

| 試験 | 結果 |
|---|---|
| SP 2048×8 | 全addressの書込み後、addressの1 edge後にdataが出ることを確認 |
| SDP 512×32 | system clockで書き、pixel clockで全word一致 |
| byte RMW | 1024 word書込み後、byte write/readのランダム3000回を参照modelと照合。byte writeのbusyは毎回2 cycle |
| TDP衝突検査 | 異なるaddressの同時アクセス200回で0件。同一addressの連続書込み/読出しで検出（54/25.2=15/7で両clockのedgeが277.8nsごとに一致する） |
| line bank | 40論理ライン（1600 pixel clock/行）で、各行の320 wordが同じtagを持ち（tearingなし）、tagが1ずつ進む（欠落・重複なし）。underrun 0。rendererを止めるとunderrunが立つ |
| mutation | 書込み許可の待ちを外したline bank、RMWのbyte取り違えをそれぞれ検査が検出することを確認（scratchpadのコピーで実施、リポジトリは不変） |

## Gowin mapping（Education V1.9.11.03、GW1NR-LV9QN88PC6/I5）

`boards/tang-nano-9k/kagura_bsram_eval_top.sv`に25ブロックを置き、実際のPLL（system 54MHz、pixel 25.2MHz）で配置配線した。LFSRで全portを駆動し、RAMごとに書込みdataを変えて同一instanceの統合を防ぎ、読出しdataはLEDへ畳み込んで削除を防ぐ。機能設計ではない。

| 用途 | 構成 | 計画 | 結果 |
|---|---|---:|---|
| pattern | SP 2048×8 | 16 | SP |
| map×2、OAM、palette | SP 1024×16（RMW） | 4 | SP |
| wave | SP 2048×8 | 1 | SP |
| command | SP 1024×16 | 1 | SP |
| line A/B | TDP 1024×16、system/pixel | 2 | DPB |
| audio FIFO | SDP 512×32 | 1 | SDPX9B |
| 計 | | 25 | **BSRAM 25/26（SP 22、SDPX9B 1、DPB 2）** |

- RAMのFF/LUT展開なし（RAM16 0、Logic 332はLFSR・RMW制御・line bank制御・畳み込み）。FF 247。
- STA: setup/hold違反0。setup最悪+5.205ns（LFSR→pattern RAM WRE）、hold最悪+0.558ns。Fmax system54 75.113MHz、pixel25 86.862MHz。
- clock間pathはline bank受け渡しのtoggle 2本だけ（`ready_sync`/`display_sync`第1段へ`set_max_delay 10ns`、slack +7.677/+7.196ns）。scratchpadのSDCコピーで`report_timing -from_clock/-to_clock`を500本まで出して確認した。BSRAM内部のport間（DPBのA書込み→B読出し、SDPの書込み→読出し）はSTAの対象外で、安全性は所有権プロトコルとsimulationのassertで担保する。

再現（Windowsのリポジトリrootから）:

```powershell
New-Item -ItemType Directory -Force build/p1-06-bsram | Out-Null
Push-Location build/p1-06-bsram
try { & 'C:\Gowin\Gowin_V1.9.11.03_Education_x64\IDE\bin\gw_sh.exe' '../../tools/eval-gowin-bsram.tcl' } finally { Pop-Location }
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-nano9k-timing.ps1 -ReportOnly -BuildDir build/p1-06-bsram -BaseName kagura_bsram_eval
```

## 予算への影響と残り

- 現在のHDMI設計の音声FIFO（16×32）は分散RAM（RAM16 10個）へ推論されており、計画のSDPB 1個を使っていない。音声FIFOをRAM16のまま維持すれば、BSRAMは24個使用・予備2個になる。どちらにするかは全体LUT予算と合わせて決める。
- 全VDP時の配置混雑とFmax、rendererからの実アクセスパターンでのSTA、SP read-before-write以外の書込みmodeが必要になる場合の扱いは、Phase 3で再評価する。
- line bankのready/display受け渡しは、P1-06のための最小プロトコル。Phase 3のrendererはこの契約に従う（行の完成を`sys_done`で知らせ、`sys_can_write`の間だけ書く）。
