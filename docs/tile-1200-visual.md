# 1,200タイル版：Picoホストの目視・聴感確認

2026-10-29、ユーザーが帰宅後に接続中の画面と音を確認した。対象は`qspipsram720`、ABI 0.6、論理320×180／HDMI 720p、PicoのQSPI 5MHz。bitstreamは[第3段階](tile-1200-stage3.md)と同じSHA-256 `52c8675c70262002a20452ef0c447af68adff8a47f1ed24cafcbf2592706b00d`。

FPGAはSRAM Program and Verifyだけで切り替えた。既存のPico HDMIコンソールをpause／detachしてPIOを解放し、既存packageを保持したまま`/lib/kagura1200`と`/tile1200_visual.py`で確認した。FPGA FlashとPico firmwareの書換えは行っていない。

## 確認結果

| 画面 | 確認内容 | 結果 |
|---|---|---|
| 追加176枚 | tile 1024～1199の16列×11行一覧と範囲ラベル | ユーザー確認、合格 |
| 最終・無効番号 | tile 1199の白い矢印、1200／2047の角括弧内が黒 | ユーザー確認、合格 |
| 境界BG／sprite | 1023、1024、1087、1088、1151、1152、1199のBGとspriteが同じ模様 | ユーザー確認、合格 |
| 反転・palette | 1199の通常／左右／上下／両反転、白／赤／緑／青 | ユーザー確認、合格 |
| 表示の安定 | 上記の静止画面でちらつき・崩れなし | ユーザー確認、合格 |
| PCM 2ch | 左375 Hz／右750 Hz、確認中の途切れ・ノイズなし | ユーザー確認、合格 |

ユーザー回答は1画面目が「1.2.3 OKです」、2画面目が「123 問題ありません」。両画面を設定した時点でERROR_CODE=0、PCM 2chのACTIVEも確認した。観察者はユーザーであり、エージェントがHDMI画面や音を直接取得したという記録ではない。source・生ログのhashと確認項目は[機械可読結果](tile-1200-visual-results.json)に保存した。

これは接続中の1つのsinkでの720p静止画面の受入。480pの目視、動くspriteやscrollの目視、全1200枚の画素を1枚ずつ確認する検査、他sink／ケーブル、電源・物理reset反復、1時間の聴感確認は未実施。先行した1時間の数値試験や、simulationの全画素比較とは検査範囲を分ける。

## 再現

`software/micropython/examples/tile1200_visual.py`をPicoの`/tile1200_visual.py`へ配置する。隔離SDK`kagura1200`と対応する720p PSRAM bitstreamを用意し、コンソールを停止してからUSB REPLで実行する。

```python
import tile1200_visual
_visual1200 = tile1200_visual.Scene()  # 追加176枚の一覧＋左右PCM
_visual1200.page(1)                   # BG／sprite境界、反転、palette
```

mapと上位bit表を更新する間は表示を止める。page変更後もPCMを継続し、sceneは観察用に保持する。`_visual1200.close()`はPCMを停止してPIOを解放する。元環境へ戻す場合は、その後に変更していないFlashからFPGAを再構成し、Picoをsoft resetする。今回の確認終了時は2画面目を表示したままとした。
