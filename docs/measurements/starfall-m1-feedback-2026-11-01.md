# STARFALL M1 — 実機フィードバック修正

2026-11-01 JST。`feat/starfall-arcade-m1`。

- タイトルを `SISKA-TECH LAB` / `2026` の2行に変更。19文字を1行のsprite文字列にすると空白を除いても17個になり、16/scanlineを超えるため分割した。欠けていたhyphen glyphも追加。
- デモ用の定期capsule追加は、表示中/待機中のcapsuleがある間は抑止。90tick間隔とし、OPTION取得後は停止。自動装備はSPEED 1段階→LASER→OPTION 1機で止める。40秒/両解像度で決定的動作と最大装備を検査。
- ステージ編隊は最後の1機を倒した時にcapsuleを1個、bonus 500点。先頭carrierの個別dropと全滅報酬が重なっていたため、編隊所属の個別dropを廃止。単独の非編隊carrierのdropは維持。逃走/出現失敗した編隊は報酬なし。
- 砲台はspawn時のworld Xを保存し、画面X = world X − camera Xで描画。従来の固定1px/tick移動が、2px/tickのデモで地形からずれる問題を修正。scroll停止中も砲台は動かない。通常/デモと180/240両解像度で検査。
- OAM/map/palette/scrollをstagingした直後に映像COMMITを投入し、その後にログ集計と音源更新/AUDIO_COMMITを行う。音源apply待ちを映像COMMIT前のVBlank予算から外す。既存driver/RTLは変更しない。ホストbackend試験で順序を検査。

## 計測値の読み方

この版の `io_us` は映像stagingの時間。`commit_us` は映像COMMIT後から完了確認までで、ログ集計、音源register転送とAUDIO_COMMIT待ちも含む。音源applyは映像COMMITの後ろへqueueされ得るため、純粋なSPI転送時間とは異なる。`wire` は音源を含む全送信byte、`blank` は映像staging終了時のVBlank超過数。

旧[M1記録](starfall-arcade-m1-2026-11-01.md)のhash/資源/デモ装備/音源更新順序は修正前の記録。この版の生成物を優先する。

## 検証

ホスト6件PASS（C11、警告エラー扱い、ASan/UBSan）。追加した全滅単一報酬、デモcapsule重複抑止、装備上限、砲台world固定、COMMIT先行、credit末尾表示もPASS。
SPI/QSPI UF2を再生成。詳細は `build/starfall-feedback-build.log`、[最終ホストログ](starfall-m1-feedback-host-2026-11-01.txt)。

既存RTL/SDKは変更しておらず、本修正で全RTL/SDK回帰は再実行していない。前版の結果と区別する。
**修正版の実機映像/音声/fpsは未検証。基地での処理落ち解消は実機で再確認が必要。**

## 実機確認

1. 接続laneに合うUF2を書き込み、タイトルの制作名と2026が全て見えること。
2. 無操作デモでcapsuleが連続追加されず、装備が速度1段階/LASER/OPTION 1機までになること。
3. 実プレイで編隊を途中まで倒してもcapsuleが出ず、全滅で1個出ること。1機逃した場合は出ないこと。
4. 基地の天井/床に対して砲台が滑らず、デモでも同じ位置に固定されること。
5. 空中戦〜侵入〜基地の `SF` ログを比較する。`hz100`、`io_us`、`commit_us`、`blank`、`missed` を保存。処理落ちが残る場合、その区間のログとSPI/QSPIの別で次のボトルネックを判定する。

UF2は `build/starfall-arcade-m1-spi.uf2` / `build/starfall-arcade-m1-qspi.uf2`。
両方209920 B。ELFは両laneともtext 111032 B / data 0 B / bss 31796 B。
詳細な最終ビルドログは `build/starfall-feedback-final.log` と `build/starfall-feedback-final-pico.log`。

```text
SHA-256 SPI  4B1DB5326FE58D47886C5B1053FA986702B6BC8609EF160933379CC912F81D09
SHA-256 QSPI 81FE7B60E0F1525BC99BE4C9F5C35B4964A0C15A6237EB485FE04FDEB013C014
```
