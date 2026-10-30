# 実機操作ログ（2026-10-30 JST）

時刻はホストログのCreationTime/LastWriteTimeおよび実行時clockから記録。
過去のCOM7障害と今回の事象を同一原因とは断定しない。

| 時刻 | 操作・観測 | 転送・復旧状態 |
|---|---|---|
| 開始 | main `a105f59`、git status clean。COM7/COM8列挙 | 未コミット変更なし。Flash/firmware/libに書込みなし |
| 07:46頃 | 権限なしCOM7 OpenがAccess denied、WSLもE_ACCESSDENIED | sandbox境界による拒否。実機timeoutと区別 |
| 07:47:15〜07:47:47 | 権限付きraw REPL。MicroPython1.26.0、SDK配置、console有無を確認 | `console.__dict__`出力がduptermの出力buffer自身を含み、出力が膨張。この診断出力は不適切だったため以後行わない。raw runner自体はexit0 |
| 07:49:59〜07:50:43の間 | console closeとhash照合用の準備コード送信。SerialPort.Writeが「セマフォがタイムアウトしました: COM7」 | prepare.logは0byte。`OK`/CONSOLE_CLOSEDを受信しておらず、コード実行・closeの成否はこの時点で未確認。ABI0.6はまだロードしておらず、ベンチマークQSPI転送も未開始 |
| 同時刻 | ユーザーへUSB抜き差しを依頼 | QSPI/FPGAの原因とは断定しない。PC側CDC、Pico側USB/REPL、dupterm出力負荷の切り分けが必要 |
| 07:55:29 | ユーザーのUSB差し直し後、同じ準備コードを明示的に再実行 | CONSOLE_CLOSED、3 SDK hash一致、/fbx一覧を受信。以前の未確定QSPIコマンドの再送ではない |
| 07:55:49〜07:55:58 | ABI0.6 bitstreamをSRAM Program and Verify（--run4） | SHA256 `2d00ee52…f133d9`、Verify success。FPGA Flashはこの時点では未変更 |
| 07:56頃 | closed console参照を解放、gc、boot.py/SDK1200を読出し | free heap208592byte。bootは`from kagura.console import start`。`/lib/kagura1200`にはconsole/terminalを含む既存0.6 SDKがある |
| 07:56:42〜 | RAM上でbenchmark開始、16file hash照合成功 | ABI[0,6]、height240、Viper/Acceleration有効、CPU125MHz、SM_CLKDIV136448、PCM2ch。rawデータはresults JSONへ保存 |
| 08:10頃 | 0〜1024タイルの46条件×30反復を完了。1200タイル用indicesのリスト確保8192byteでMemoryError | 転送前の刺激準備で失敗。TRANSPORT_SESSION_CLOSEDを受信。音源停止・acceleration解除・PIO解放のfinallyを完了。取得済みraw logとworkloadを保全 |
| 08:11頃 | 計測器のindicesをrange/16bit arrayへ変更し、条件間に参照解放・GCを追加 | SDK本体や通信経路を変更していない。省メモリ刺激のタイル数・重複なし・境界はhostテストで検証 |
| 08:12:12〜08:14:58の間 | 再開用17262byteコードの一括raw upload。実行ACK前にSerialPort.Writeが再びセマフォtimeout | remaining.logは0byte。正確な送信offsetを旧runnerは記録していないため不明。USB再接続を依頼。MemoryErrorとの関連やraw buffer成長の影響は仮説であり未確認 |
| 08:15頃 | RTL全回帰終了 | Verilator5.032、61/61 pass。SDK196件pass（2skip）、公式PIO assembler60件pass、計測器2件pass |
| 08:25:44〜08:26:01 | ユーザーのPC再起動後に、小さいhealthコードをCOM7へ送信 | 同じSerialPort.Writeのセマフォtimeout。reboot-health.logは0byteで実行ACKなし。PC再起動だけでは復旧を確認できなかった |
| 08:26頃 | PnP状態と限定再初期化を確認 | COM7はStatus OK、Pico USB CDC interface `USB\VID_2E8A&PID_0005&MI_00\6&1E4D8D20&0&0000`。このinterfaceだけの`pnputil /restart-device`を試行したがWindowsがAccess is deniedを返し、再初期化は未実施。他USB機器・PC・Flashは操作していない |
| 08:28頃 | ユーザーが再初期化を明示許可。UAC経由で管理者pnputilを実行 | COM7 CDC interfaceの再起動は成功、exit0。ただし後続の2文字Ctrl-C送信と小さいhealth送信は両方セマフォtimeout。PnP成功とREPL復旧を区別する |
| 08:29:32 | Pico本体のUSB親デバイスを特定 | `USB\VID_2E8A&PID_0005\e663a837cb73512d`。このPico1件だけの管理者再起動を要求。USBハブ全体・他機器は対象外 |
| 08:30〜08:31頃 | 管理者によるPico USB親デバイス再起動が成功、exit0 | 最初のCOM7接続ではCtrl-C/CTRL-B/CTRL-Aに対してMicroPython bannerとraw REPL promptを受信。しかしポートを閉じて次のhealth接続を開くと再びWriteセマフォtimeout。1回の観測なのでport再openが原因と確定しない |
| 08:33〜08:38頃 | ユーザーがpicotoolでのFW書換えを提案・許可。WSL既存ツールを探索 | `/home/shion/mp-v126-utf8/ports/rp2/build-KAGURA_PICO/_deps/picotool/picotool`はUSB対応v2.1.1。mainのbuild内v2.2.0はUSB非対応ビルド。WSL内にUSB機器は公開されていない |
| 同時刻 | 元firmwareをWSLから保全 | `/home/shion/mp-v126-utf8/ports/rp2/build-KAGURA_PICO/firmware.uf2`。バナー`v1.26.0-1.g3069c562f on 2026-10-29`が実機と一致。SHA256 `0aeffbeb2851b64bfcdc6412b89e19926321570100927303afda86b526d4bc5b`。バナー一致だけではbinary完全一致とは扱わず、書込み前に現Flashとの照合を条件にした |
| 同時刻 | 公式Windows picotool v2.3.1をworkspaceへ取得 | [公式release](https://github.com/raspberrypi/pico-sdk-tools/releases/tag/v2.3.1-0)。ZIP SHA256 `68730be0813f8f35be2cca147cf7f1572662d5dcf0f5ba468e02a6dd9e85db2b`がrelease API digestと一致。PicoはMicroPython deviceとして検出できたが、`reboot -u -f`ではBOOTSEL移行できず、Flash書込みなし |

FW回復用に、USB親デバイス再初期化後の最初のCOM7接続を維持し、
raw REPLで`machine.bootloader()`を送り、picotoolへ引き継ぐ処理を準備した。
全Flashバックアップ、UF2 payloadと現firmwareの完全一致、firmware-onlyアドレス範囲、
書込み検証、ファイル領域の前後hash一致を条件とし、erase-allは使わない。
準備・起動要求と、実際のBOOTSEL移行・書換え完了は区別して記録する。

08:41:09のbootloader commandでBOOTSEL移行自体は成功した。
BOOTROMのUSB serialは`E0C9125B0D9B`で、MicroPythonの`e663a837cb73512d`とは異なったため、
最初の回復scriptは対象同一性チェックで停止した。書込みは行っていない。
Pico MicroPython deviceの消失直後、同じbus2に唯一のRP2040 BOOTSEL deviceが現れたことを確認した。
Windows picotoolはMI_01のdriver不足（RP2 Boot PnP Error）で接続不可。
BOOTSELのD: RPI-RP2にはCURRENT.UF2はなく、picotoolでの全Flash backup/照合は取得できなかった。

08:43:24〜08:43:29に、元バナーと一致する保全UF2をD: RPI-RP2へコピーしてfirmwareを書戻した。
全UF2 blockのmagicとaddressを検査し、範囲は`0x10000000..0x10058CFF`。
元build sourceのfilesystem開始`0x100A0000`には一切payloadがない。erase-allなし。
ただしこの経路では書込み後のraw Flash readback/hash照合はできておらず、
ファイル保持は次回SDK hash照合で確認する。FPGA Flashは未変更。

08:45:15の再接続ではraw REPL prompt ACKを受信したが、その次のcleanupコード送信で
.NET SerialPort.Writeが再びセマフォtimeoutになった。
FW書戻しだけでは症状が解消しないことを確認。
標準mpremote1.29.0/pyserial3.5をworkspace内へ配置し、raw-paste経路の切り分けを準備した。
非管理者側のmpremote healthも応答がなく、自分が起動した該当health processだけを終了した。
Pico USB再初期化後に管理者mpremoteを単一接続で実行する追加試験を開始要求した。

## 復旧後の計測と最終復帰

| 時刻 JST | 観測・操作 | 結果 |
|---|---|---|
| 08:51:42〜 | Windows標準PowerShellから管理者mpremote、USB parent再初期化後に実行 | MPREMOTE_HEALTH、SDK16 hash照合成功。Pico USB通信は復旧。ただしFPGA ABI0.5を検出し、FB接続を拒否して安全停止 |
| 08:57:07 | 既存console closeを独立確認 | CONSOLE_RELEASED。PIO所有者を解放してから再構成 |
| 08:57:17 | 同じhashのABI0.6をSRAM Program and Verify | Verify success |
| 08:57〜09:00 | 1200 micro4条件、Scene A/B/C revision1 | 各30反復。PCM2ch、ERROR0。Dの独立source38401byte確保でMemoryError。Session.close完了、Flash保存はskip |
| 09:07:58〜09:08:04 | full sourceを先に確保した別Session | sourceは確保できたがFramebuffer plane38400byte確保でMemoryError。SDK/allocatorを変更する方式は採らず、独立全画面sourceを未測定へ分類 |
| 09:19〜09:26 | 管理者起動の再要求 | 非表示起動のUAC要求が待機・取消。ユーザーにUACが見えていないと報告され、通常ウィンドウへ変更すると起動成功。これをUSB/FPGA障害と混同しない |
| 09:26:21 | 最終省メモリ版を管理者mpremoteで開始 | CONSOLE_RELEASED、SDK16 hash一致。full blitは960byte退避＋self-scroll/wrap実コピー。heap API観測負荷を較正し、4 scene revision2を再取得 |
| 09:26:27 | ABI0.6 SRAM Program and Verify | Verify success。FPGA source/ABI/PIO wire形式は変更なし |
| 09:26〜09:34 | Scene D/A/B/C、profile、DMA128/256/512、primitive、全VRAM読戻し | ERROR_CODE0、FIFO fault0、PCM2ch faultなし。pattern38400byte/map4096byte/upper256byte照合成功、transport_complete |
| 09:34〜09:37 | Session.close後にCPU-only pack batch、Python/Viper native検証 | DMA closeをassert。各backend1090操作がPC rolling CRCと一致、text/paint stress一致、guard intact、differential_pass |
| 09:37:30 | 全benchmark/native検証の完了をhost側で確認 | 完了markerとexit0を確認してからFlash段階へ進む |
| 09:37:43 | 許可されたABI0.6のFPGA Flash保存（--run6） | exit0だがログにError: Verify Failed。書込照合成功ではない。過去にもある症状で原因は未特定 |
| 09:37:43〜09:37:49 | --run1でFlashから再構成、console起動 | ABI[0,6]、height240、QSPI5MHz、CPU125MHz、SM_CLKDIV136448、console active、ERROR_CODE0 |
| 同時刻 | boot移行 | 元bootを`/boot.pre-transport-20261030.py`へbytes保存・照合。既存`kagura1200.console`へimport1行変更。canonical `/lib/kagura`は未変更。PCM停止・acceleration解除・PIO解放後にconsoleへ所有権移譲 |

最後の管理者helperは成功終了し、retry待ちを残していない。
HDMI画面・音声の直接目視/聴取は今回行っておらず、console activeはsoftware状態確認。
COM7停止原因は未特定。USB parent再初期化、権限、FW書戻し、raw-pasteなど複数条件を
変えて復旧したので、特定の1条件が原因/解決だったとは断定しない。

初回の大きなコード送信は成功しているので、コードサイズだけをCOM7停止原因と断定しない。
次の対策は、大きなコード受信前の独立cleanup、512byteごとのfile write ACK、
送信prefixとSHA-256記録である。これは原因特定結果ではなく、復旧時の観測性改善。

過去の記録は[プリミティブ検証](framebuffer-primitives.md)と
[Viper検証](framebuffer-viper-results.md)を参照。
過去のFlash0.5復帰後にもCOM7停止が記録されている。
今回のUSB障害が特定のABI/QSPI/FPGA構成に固有であるという証拠はない。

再発時は、UTC/JSTの時刻、最後のraw REPL ACK、送信済みコードoffset、
最後のflush/run/chunk、PIO/DMA所有者、CS/BUSY/READY、USB列挙とWindows側例外を保存する。
QSPIの部分転送timeoutとUSB upload失敗は別の事象として扱う。
Picoが応答不能な場合にPIO内部値を取得できたかのように推定記録しない。


## 追加計測と最終復帰（JST 13時台）

- 13:05/13:09: console起動後の追加矩形Sessionはframebuffer38400byte確保でMemoryError。
  console.close/module eviction後にも失敗。各試験後soft resetでABI0.6 console active/ERROR0を確認。
  これはheap条件の失敗で、QSPI転送不良とは分類しない。
- 13:24頃: `/boot.py` SHA `301d9cc8067d001cb812be43f9bccbd183abeacd514d21347f725a7989c497f0`
  を確認してbackupし、one-shot flagで一回だけconsoleを起動しないVMを利用。
  通常権限のmpremoteでSDK16hashを再確認し、256/512 compact矩形を各30反復取得。
- 次のclean VM: 独立38400byte sourceをSDK初期化前に確保、Scene Dを30反復取得。
  application updates/s=7.33148036、PCM[3,3]、ERROR0、FIFO0。
  全pattern38400byte・map4096byte・upper256byteのreadback成功。
- 13:28頃: Session.close後にfinallyでboot bytesを復元、上記SHA完全一致。
  runtime backup/flagを除去。soft reset後ABI[0,6]、height240、console active、ERROR0。
  rectangles/fullblit/restore/consoleのhost exitはすべて0。Flashとcanonical SDKへの追加書込みなし。

raw値とboot操作は[追加ログ](framebuffer-transport-logs/README.md#追加clean-vm計測とboot復元)を参照。
追加計測後のSDK hostは198件中196成功・2skip。design/link・register生成一致・依存12hashも成功。
任意のnative機械語追加ダウンロードは承認レビューの利用上限により実施できなかった。
これは原因特定済みの結果ではなく、機械語レベルの追加確認は未実施。PIO命令列はsourceを追跡した。
