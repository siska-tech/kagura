# STARFALL Phase A result

2026-11-01 JST。既存v6の4試験PASSを確認してから変更。
ブランチ`feat/starfall-arcade-m1`、設計は[arcade plan](../starfall-arcade-plan.md)。

状態管理、120tick intro、6件のStageDef（Stage 1だけready）、40秒attractを追加。
demoは同じPLAYを使い、入力controllerとカプセルeventが決定的に動く。
900tick無操作で開始し、実STARTですぐintroへ、新規runの装備/敵/弾を初期化。
ホスト検査では両解像度でSPEED/LASER/OPTION/砲台/大型敵を実際に表示した（features=31）。
デモ中だけ被弾を無効にする。通常ゲームに無敵を追加したものではない。

大型BGロゴ/惑星、palette fade、星空raster、通過自機、PRESS START/1 PLAYER/
FREE PLAY/KAGURA LABを追加。タイトル専用mapからgame mapへ表示停止/FENCEで交換。
sprite/logoの著作物は全て既存の自作font/pixel生成から作成したもの。

host5/5 PASS、SPI/QSPI UF2成功。ELF text109260/data0/bss27620 B。
関連する既存RTLのsprite selector/composite/ABIもPASS。
実機映像/音声/操作/fps、full RTL regression/STAはこの段階では未確認。
UF2はbuild/starfall-arcade-A-spi.uf2 / starfall-arcade-A-qspi.uf2へ保存。
次はPhase BのStage 1専用bossとwarning/clearの完成。
