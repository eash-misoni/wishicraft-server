# Two-Game SWITCH migration

**Proposed — production未承認。D-097の設計承認と、この実行計画のGOを一括して求める。**
現在productionはD-096単一Game契約。意味・認可・保護単位の差分の正本は
[設計提案](../reviews/two_game_switch.md)。過去のD-096 migrationを再実行しない。

## 承認対象と固定入力

A=`game-vanilla-main`は既存`/srv/minecraft/games/game-vanilla-main/server`を維持。
B=`game-vanilla-secondary`は独立したserver directoryを新設。同じstageの固定image/version、
同じ既存Target/Data EBS、同時一つのみ。Bの表示名・初期whitelist・EULA適用は生成した宣言で確認する。
Aのwhitelist/propertiesやworldをコピー、再生成、上書きしない。Bの初回world生成だけを明示許可する。

承認に必要なwriteは、normal BACKUP二回（下記の異なる目的）、二Lambdaの一時concurrency制御、
既存Targetの保守起動/正常停止とexact SSM、承認bundleのhost更新、B初期配置/条件付きGames登録、
Control Plane限定deploy（SWITCH State Machine/role/alarm、既存code/configと限定IAM）、
Discord command body更新、通常START/SWITCH/STOP、必要なcontrolled Reconcile。
Target stack/IAM、EBS配置、SG/DNS構成、既存Snapshot/provenance、retention削除権限は変更しない。
通常START/STOPによる既存DNS recordの作成/削除は通常経路だけを使用する。

## オフライン成果物

新規temporary rootへ一度生成し、宣言のtimestampと全hashをそのまま再開時にも使用する。

```sh
./tools/dev-env run -- python -m wishicraft.two_game_admin --declaration <new-root>/second-game.json
./tools/dev-env run -- python -m wishicraft.two_game_migration --declaration <new-root>/second-game.json --output <new-root>/bundle
./tools/dev-env run -- npx --no-install cdk synth WishicraftControlPlaneStack-dev --context stage=dev --context phase=8 --context deployment=control-plane --context two_games=true
```

`install.json`はD-096の実適用証跡から旧hashとexact stopped receiptを固定する。
operation-v2は当時と同じshebang付与を含むGit artifactと照合する。
実hostのreceipt/hashが変わっていれば、今回の値に無条件で差し替えず由来を再確認する。
`SHA256.json`、宣言、synth、実production templateとの差分を承認HEADへ対応づける。

## 実行順序とcheckpoint

1. 正規SSO caller/account/region、HEAD/CI、Target/EBS/Game A、両Lambda元concurrency、
   DNS、全未終了Operation/Lock/workflow/SSMを再観測。現在値を過去evidenceで代用しない。
   STOPPED/HEALTHYで、旧v1 normal BACKUPを一回取得する。移行後の正規起動による書込み前の最新保護が目的。
   completed/source/owner/tag、Operation成功、durable provenance pair一致が条件。結果不明で別requestを作らない。
2. Discord CommandとAdmissionの新規受付を止め、各元設定を保持。既存呼出し、workflow、SSM、
   host jobをdrainし、BACKUP以降にworld書込みがないことを確認。concurrency 0だけでdrain済みとしない。
   自動停止の非eligibleと既送信要求なしも照合する。新旧component混在中は閉じたままにする。
3. exact Targetを保守起動。Minecraft inactive、DNSなし、container/listenerなし、stopped receipt、
   元volume/filesystem/mountとAの既存world/player inventoryを確認する。未知containerは削除せず停止。
   D-096の旧container整理は既に完了しており再実行しない。
4. `/var/tmp/wishicraft-two-game-v1`へbundleを配送し、全hash/通常file/root owner/modeを照合。
   `install.py`の全artifact preflightを通してatomic置換する。旧fileは専用namespaceへ保持しreceiptは保持する。
   新しい実行receiptがある場合は再installationを拒否する。同一bundleの既知旧/新の混在だけ前進再開可能。
5. 配送済み`prepare-game.py`を実行し、Bの宣言済み二fileと初期化許可markerだけを作成。
   同host排他、mount確認、別Game directory、既存未知内容の拒否を通す。返却proofを保存して
   `two_game_admin --execute-registration --declaration <same-file> --proof <saved-proof>`で登録する。
   この入口はGameだけを条件付き登録し、稼働対象をraw編集しない。登録応答喪失は同一recordをread-backする。
6. host全hashをread-back後、inactiveのまま保守EC2正常停止。
   `two_games=true`のControl Plane template差分を確認してdeploy。予期しないreplacement/deletion、
   IAM範囲拡大、Target変更で停止。新definition、11 Lambda code/config、IAM、alarmをread-backする。
   deploy前後も受付0を照合。Discordは宣言内command bodyだけを正規登録手順で反映する。
7. 新host/CPのcatalogとdigest一致、EC2停止/DNSなし、fresh STOPPED/HEALTHY、Lock/未終了Operationなし
   を確認し、Admission、Discordの順で各元設定を復元する。元UNSETならUNSETへ戻す。
8. canonical START A → SWITCH B → SWITCH A → STOP。全てshared Admissionで別固定request identityを記録。
   A/B/AのOperation target、receipt、container/image/bind、Game/run/process、READY/DNS、heartbeatを照合。
   二つのSWITCHで同一instance/boot IDが続きEC2 stop/startがないこと、保存停止/removalを確認する。
   Aの既存world/player dataと再入場時の保持を確認し、Bは初回のみ新world生成を確認する。
   開始・source停止・destination READYの時刻から実所要時間を報告し、事前の秒数保証を置かない。
   新runのempty_since/warningが旧runから流用されないことを確認。実Dockerのscoreboard検証と区別し、
   productionへ試験用scoreboardを書かない。人間目視をしない場合は建築物等の目視確認済みとはしない。
9. final STOP後、v2 shared-volume normal BACKUPを一回取得する。新契約の実正常系と、初回保存済みBを含む
   recovery description/provenanceの一致確認が目的。最初のv1保護Snapshotとは混同しない。
   既存5件と手順1の一件を保持し、この一件だけ追加。新旧retentionはdry-run分類だけを検証する。
   Aだけの抽出方法は下記。隔離復元試験/30分auto-stopの無条件再実行はこの計画に含めない。

## 失敗・再開と戻し方

各checkpointでexact request/Operation/execution/SSM ID、bundle hash、receipt、container、両受付設定を保存。
送信済みを成功済みとしない。未確定mutationは別Operation/別Game/worldで置き換えない。
A save失敗ならAとそのデータを保持し、正常停止の証明なしに削除/次Game起動しない。
A停止後Bが未起動なら両データを保持。B選択後の起動失敗はB選択とDEGRADED/UNKNOWNを表示する。
同じ生きたOperation/lease内は同対象のreceipt/SSM再観測から続行する。
terminal後は自動redriveせず、Lock解放と未知命令なしを確認した上で通常START/STOPの対象検証を通す。
STARTが既存非stopped receiptを採用する場合も、同Game/path/config/runだけであり別runを捏造しない。
Aへ戻す前にはB非稼働/保存状態を確認する。Operation/Lock recoveryや保存不明なら受付を閉じて停止する。

新host/metadata/B書込み後は単純な旧コードdowngradeをしない。途中bundle適用は同bundleで前進修復。
新しい契約や権限が必要な修復は別承認。B初期配置の再実行はまだ既知の二fileだけの場合に限定し、
world生成後を初期状態に戻さない。初回正常STOPで初期化許可を消費し、その後level.dat欠損は拒否する。

A単独復元はSnapshotから隔離volumeを作り、当該schemaの復旧情報でA directoryを特定して別領域へ抽出する。
稼働Gameを正常停止してからAだけを検証・切替する別承認作業とし、共有EBS全体やSystemStateを巻き戻さない。
B側directory/参照を保持する。v2は保存したGame定義とruntime情報を根拠にできるが、v1は履歴再構築が必要。
実multi-Game単独復元は今回repositoryテストと手順準備の範囲で、production実証済みではない。

## 最終条件・費用

STOPPED/HEALTHY、DNSなし、Lock/Current Operation/unfinished Operationなし、両受付元設定、
元EBS identity/attachment/encryption、A既存配置、B独立配置、既存Snapshot/provenance保持を確認する。
alarmは実収束で戻し、無効化/fake metricをしない。新しい常時instance/serviceやvolumeは追加しない。
Bの使用容量とSnapshotの変更block分、SWITCH State transitions/Lambda/SSM/ログが追加コストとなる。SWITCH用CloudWatch alarmの通常料金も別途発生する。
同じEC2を維持する切替時間も通常の稼働料金に含む。容量不足は安全停止し、自動EBS拡張/削除はしない。
Budgetは変更しない。実単価・仮定・template差分は最終準備証跡へ記録する。


東京EBS Snapshot公式Price List（2026-09-11照会、SKU `4NHX4ZW7X52XZACJ`）は
USD 0.05/GB-month。追加保持blockが計10 GBなら月USD 0.50、二件が各30 GB全量相当という
保守的な上限計算は月USD 3.00。実際は既存Snapshotとの共有blockと変更量で変わるため件数×volume容量を
実課金量と断定しない。[AWSの増分Snapshot説明](https://docs.aws.amazon.com/ebs/latest/userguide/how_snapshots_work.html)。
既存volumeの課金容量は増やさない。保守/E2Eの稼働時間は既存東京t3a.mediumとIPv4の合計USD 0.054/hを
同日確認済み復元runbookの単価から参照し、4時間なら約USD 0.216にSnapshot/実行/通信/ログを加える。
4時間で費用と状態を見直すが、時間だけを理由に強制停止やデータ削除はしない。
価格照会・template差分・検証範囲は[準備証跡](../evidence/2026-09-11-two-game-preparation.json)に保存する。
