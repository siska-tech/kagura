# 16:9 Mode: 320×180 on 1280×720p60

【設計】320×180の論理画面を1280×720p60（CEA VIC 4）へ4×4で正方画素表示する追加モード。bitstream単位で選択し、CAPSで通知する。現行の320×240／640×480は維持する。

## 方式比較

| 案 | 出力 | 拡大 | 判断 |
|---|---|---|---|
| A. 1280×720p60 | 74.25MHz、TMDS 742.5Mbps/lane | 4×4 | **採用候補**。整数倍・正方画素、描画時間も増える |
| B. 640×480内レターボックス | 現行 | 2×2、上下60行黒 | Aが物理層で成立しない場合の代替。信号は4:3のまま |
| C. 720×480p (VIC 3) | 27MHz | 2.25倍 | 整数倍にならず不採用 |

## 算定（案A）

| 項目 | 640×480（現行） | 1280×720（案A） |
|---|---:|---:|
| pixel / TMDS serial | 25.2 / 126MHz | 74.25 / 371.25MHz |
| H total × V total | 800 × 525 | 1650 × 750 |
| 論理1ライン | 物理2ライン、63.49µs | 物理4ライン、88.89µs |
| system cycles/論理ライン | 3428 | 4800 |
| 描画2633＋ガード64後のCPU枠 | 731 | 2103 |
| VBlank | 45ライン、約77142 cycles | 30ライン、36000 cycles |
| ACR (48kHz) | N=6144, CTS=25200 | N=6144, CTS=74250 |

PLL: 27MHz×55/4 = 371.25MHz（IDIV_SEL=3, FBDIV_SEL=54, ODIV_SEL=2、VCO 742.5MHz、PFD 6.75MHz）、CLKDIV /5で74.25MHz。27MHz基準との整数比を保つので、共通referenceによる固定N/CTSの前提（[hdmi-design-decision.md](hdmi-design-decision.md)）は成り立つ。

VBlankの必要量は[スケジュール](memory-access-schedule.md)の5257 cyclesで、36000 cyclesに収まる。BSRAMは増えない。line bankは320画素のまま、マップ64×32（512×256px）は180ラインを覆う。

## 変更箇所

| 対象 | 変更 |
|---|---|
| `kagura_nano9k_clocks` | video PLL定数をモード別parameterに |
| `kagura_hdmi_stream_eval` / 生成HDMI core | VIDEO_ID_CODE=4、座標11bit、固定CTS=74250 |
| `kagura_line_display` | H/V total・active・SCALE・LINESをparameter化。要求は物理y=SCALE·n、line0要求とVBlank位置を一般化 |
| `kagura_core` | RASTER比較を`< LINES`、VBlankイベントはy=V_ACTIVE |
| sprite clip | 論理Yは要求ラインだけなので変更不要（要確認） |
| ABI 0.2 | CAPS b5 WIDE、EXT 0A SCREEN_HEIGHT（RO、180/240）、RASTER_LINE有効範囲0..LINES−1 |
| demo / 試験 | 180ライン配置、SCALE=4の全画素比較、4800 cycles期限 |

## ゲートと順序

1. **物理層ゲート**: 720pのカラーバーと固定PCMだけのbitstreamを作り、P&R・STA（371.25MHz FCLK、74.25MHz pixel）と実機モニター2台以上で映像・音声を確認する。【未検証】GW1NR-9 C6のOSER10とエミュレートLVDSで742.5Mbpsが成立するかは資料で確定できない。
2. ゲート合格後に`line_display`のparameter化とABI 0.2。現行モードの全回帰が無変更で通ることを先に確認する。
3. 不合格なら案Bへ切り替え、480p内で320×180を上下中央に表示する。CAPS b5の意味は「論理180ライン」として共通にし、出力形式はホストに見せない。

実行時の240/180切替はPLLの動的再設定とsinkの再同期を伴うため対象外とする。

## 物理層ゲートの状況（2026-10-23）

`tools/build-nano9k.tcl hdmi720`で、カラーバー＋固定テスト音のVIC4評価bitstream（`kagura_hdmi720_top`）を生成する。stream部はVIC1版とinstance名が同じで、phase1.cstの配置制約を共有する。SDCはbuild時にclock比と名前（serial371/pixel74）を置換し、`phase1-720p.sdc`を追加する。

**VIC4対応で変えたもの**

| 対象 | 変更 |
|---|---|
| `kagura_nano9k_clocks` | `VIDEO_ID_CODE`でPLL定数を選択 |
| `kagura_audio_transport` | 48kHz tickを分数分周に一般化。VIC1は525/1、VIC4は12375/8 pixel clock |
| `kagura_audio_packets` | VIC/CTSをparameter化。AVIのVICと16:9 aspect |
| `kagura_hdmi_stream_eval` / bar pattern | VIC parameter、座標11bit |

**74.25MHzのための修正（VIC1にも適用）**

- `kagura_audio_packets`: header/subを`kind`からの組合せmuxでなく、packet_enableの端でレジスタに選択済みの値を入れる。sample_readyも次のcountからレジスタ化する。出力は同じサイクルで等価。
- `kagura_async_fifo`: empty/fullを「pop/pushなし」と「あり」の比較を先に作って選ぶ形にする。論理は等価。

**既存不具合の修正**: 従来のACR定数`56'h00180000627000`はCTSの3byteが1byteずれており、sinkが読むCTSは25088（正しくは25200）だった。上流hdl-utilと同じbyte順（bits 7:0=PB0、PB1..3=CTS、PB4..6=N）へ修正した。試験も同じ誤った定数を期待値にしていたので、仕様のbyte配置から求めた値に改めた。VIC1の実機でも音声は出ていたが、修正後の実機確認が必要。

**371.25MHzのリセット経路**: OSER10のリセット解除をFCLKで同期する既存構造は、fabricからIOLOGICまでの配線（約4.8ns）がFCLK 1周期（2.694ns）を超え、setup −2.529ns、recovery −1.757nsとなった。このゲート版ではsetup 2/hold 1のmulticycleで解析した。（訂正: この指定はhold側を通常どおり0番目のエッジで見るだけで、遷移が1つ目のFCLKエッジに掛からないことは保証しない。後述の320×180実装で配置制約による1サイクル化に置き換えた。）

【実測】物理層ゲート時点ではGowin 1.9.11.03 Educationでbitstream生成、上記multicycle制約下でsetup/hold/recovery/removal違反0。これは現行のreset制約とは異なる過去の測定値。

| 項目 | 値 |
|---|---|
| Logic / Register | 751 / 370 |
| 最小setup slack | +0.163ns（serial371、multicycleのリセット経路） |
| pixel74 Fmax | 75.36MHz（74.25MHzに対し約1.5%、最悪経路は上流hdl-utilの`cx`折り返し） |
| serial371 Fmax | 382.8MHz |
| 最小hold / recovery / removal | +0.562 / +1.339 / +0.561ns |

同じ変更後のVIC1系top（hdmi、phase2、demo、spi）も再ビルドし、違反0を確認した。シミュレーションは`tb_hdmi_stream720`でVIC4のTERC4経路、PCM 1024サンプルの順序、ACR（CTS=74250）、AVI（VIC4、16:9）、平均48kHzを確認した。

【実機】2026-10-23、`kagura_hdmi720.fs`をSRAMへ書込み、試験用モニター1台で次を確認した。

- モニターが1280×720として認識
- 1pixel白枠と8本のカラーバーが正常
- 左右のテスト音
- LED（PLL lock点灯、mute/underflow消灯）

GW1NR-9 C6のOSER10とエミュレートLVDSで742.5Mbpsが少なくとも1台のsinkで成立したため、物理層ゲートは条件付き合格とし、案Aで進める。

【未検証】合格条件のうち、モニター2台以上と1時間の連続表示は未実施（試験環境が1台のため）。追加のsinkが用意できた時点で確認する。このゲート時点ではACR修正後のVIC1版の実機音声も未確認だった（後述の320×180実装時に確認済み）。pixel74の余裕が小さいので、line display等を追加する際はhdl-utilのカウンタ経路の改善を先に行う。

## リスク

- pixel domainが約3倍速になり、hdl-utilのTMDS/packet経路のsetup余裕が減る。demo topのsystem側最小setupは現在+0.031nsであり、配置変動の影響も再確認する。
- 720pの消費電流・TMDS信号品質。複数sink/ケーブルで1時間の確認を合格条件に含める。

## 320×180表示の実装（2026-10-23）

**RTL**

| 対象 | 内容 |
|---|---|
| `kagura_line_display` | `VIDEO_ID_CODE`でH/V total・active・SCALE（2/4）・ライン数を切り替える。ライン要求は物理y=SCALE·n、line0はy=V_TOTAL−3、VBlankはy=V_ACTIVE |
| `kagura_vdp` / `kagura_core` | `VIDEO_ID_CODE`から`LINES`（240/180）を導出。RASTERは`< LINES` |
| `kagura_registers` | ABI 0.2: ABI_MINOR=2、EXT 0A SCREEN_HEIGHT（[register-map.md](register-map.md)）。CAPS b5 WIDEはboard topが立てる（0x33） |
| board top 4種 | ビルド時生成のpackage `kagura_build_config`から`VIDEO_ID_CODE`（hostはLANESも）を受ける。`tools/build-nano9k.tcl`のモード名に`720`を付けると16:9版（hdmi720、demo720、phase2720、spi720、qspi720） |

**74.25MHzのための変更**（VIC1にも同じRTLを使う）

- `kagura_tmds_channel`: 上流`tmds_channel`と同じ出力列を3段パイプラインで出す（レイテンシ1→3）。カラーバー評価では入力が定数に近く見えなかったが、VDPの任意RGBでは上流の1段8b/10bが−9.1nsとなった。`tb_tmds_pipeline`で上流と2クロック遅れで一致することを60万シンボル確認し、XNORマスクを壊した改変版を3サイクル目で検出することも確かめた。生成コアの差し替えは`tools/prepare-hdmi-stream.py`。
- `kagura_line_display`: 2画素先の走査判定（ライン開始、表示範囲、RAMアドレス）を3画素先の座標から1クロック前にレジスタ化。done tagとの比較もcyだけから作る`next_line`との登録済み比較にした。帰結として、line doneはライン開始の2 pixel clock前までに届く必要がある（従来は1）。間に合わない場合は従来どおりそのラインを黒にしてLINE_UNDERRUN。
- 2つの同期段`serial_reset_0/1`もレーン複製の間（R2C40）へ`INS_LOC`で置き、FCLK内の経路を1サイクルで閉じた。
- 16:9版だけ`place_option 1`を使う。既定配置ではdemo720がpixel74で−0.010nsだった。

**OSER10 RESETの扱い（16:9版）**: レーン複製からIOLOGICのRESET端子までの配線はビルドごとに1〜5nsで変わり、recovery検査が使うFCLK半周期（1.347ns）に収められない。PCLK起点に変える案も試したが、VIC1でもFCLK立下り基準のrecoveryが−1.12nsとなったため取り消した。16:9版ではこのrecovery/removal検査を`phase1-720p.sdc`でfalse pathとし、解除はFCLK/PCLKに対して非同期とみなす。リセット後のレーン整列は実機確認項目とする。VIC1版は全検査を維持する。

**検証**

- `tb_vdp_frame720` / `tb_vdp_sprites720`: 1280×720の4フレーム×921600画素を参照モデルと全画素比較。背景のみとスプライト付き、scroll、behind、16個/ライン超過、VBLANK/RASTER/COMMIT_DONE、systemだけのreset。SCREEN_HEIGHT=180も読む。最悪描画は1985 cycles（上限2633、論理ライン4800 cycles）。
- VIC1側は従来の全試験がそのまま合格（720p導入時`1c1dcd8`の全回帰30件。`918e4f7`で`tb_demo_shooter720`を追加。現行の一覧は`tools/test-verilator.sh`）。

【実測】Gowin 1.9.11.03 Education。全11構成（dviは480pのみ）でbitstream生成、解析対象のsetup/hold/recovery/removal違反0。16:9版は上記OSER10 RESET経路を除外しており、そのrecovery/removalを保証する結果ではない。数値は`443900a`の測定値（M0の`9f595f7`からの変化は[タイミング仕様](timing.md)の改善記録）。

| 構成 | Logic | Register | BSRAM | 最小setup slack | pixel Fmax |
|---|---:|---:|---:|---:|---:|
| hdmi720（カラーバー） | 811 | 416 | — | +0.391ns | 80.4MHz |
| demo720 | 6253 | 3625 | 25/26 | +0.085ns | 74.7MHz |
| phase2720 | 4351 | 3236 | 24/26 | +0.111ns | 74.9MHz |
| spi720 | 4468 | 3269 | 24/26 | +0.134ns | 75.0MHz |
| qspi720 | 4450 | 3271 | 24/26 | +0.099ns | 74.8MHz |

16:9版の最悪経路は上流hdl-utilのpacket_assemblerのBCH/parity（pixel74）で、余裕は+0.09〜0.14ns程度。system54側の経路は`443900a`で改善した。機能を追加する際は、これらのパイプライン化を先に行う。

【実機】2026-10-23、試験用モニター1台で`kagura_demo720.fs`（1280×720のdemo）と`kagura_demo.fs`（640×480、パイプライン化したTMDS encoderとACR修正を含む）をSRAMへ書込み、映像・音声とも問題ないことを確認した。16:9版ではリセット後のレーン整列にも異常は見られなかった。複数sinkと長時間試験は未実施。

**demoの16:9配置**: 240ライン前提の配置では自機（y=196）と弾が180ラインの画面外に出ていた。`kagura_demo_sequencer`に`LINES`を追加し、自機をy=LINES−44（240で196、180で136）、炎と弾をその相対位置に置く。`tb_demo_shooter720`は1280×720の5フレームを参照モデルと全画素比較する。【実機】配置変更後の`kagura_demo720.fs`で、自機が180ラインの画面内に表示されることを実機で確認した（2026-10-23、モニター1台）。
