# 運搬機の即時報酬

オレンジ色のcarrierを倒した時点でcapsuleを落とす仕様へ修正。
同じ編隊の全滅時には500点bonusを付与するが、capsuleは重複させない。
通常編隊は従来どおり全滅時にcapsule1個。
group_rewardedの16bit maskで編隊ごとの支払いを記録し、回収後も二重発生を防ぐ。

ホスト6件PASS。通常編隊/運搬機編隊の4機撃破、運搬機撃破直後のdrop、先に回収した後の編隊全滅、両解像度を検査。
SPI/QSPI UF2を従来M1名へ再生成。ログは `build/starfall-carrier-build.log` と `build/starfall-carrier-host.log`。
実機での本修正の確認は未実施。描画/音源/同期方式の変更なし。
