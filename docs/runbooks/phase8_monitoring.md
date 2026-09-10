# Phase 8.3 monitoring production gate and evidence

- 対象は既存実環境のdev stage。`prod.yaml`はplaceholderのまま。
- 状態: D-094 Accepted / Phase 8.3 Completed（2026-09-10 UTC）。基準HEAD `bc6b4ca52db3c3f72c97b2462181edb5ffe74f84`についてユーザーの限定GOを受領し、設計承認後にdev production適用・監視E2Eを実証した。
- 実行時は直前deployed template/config/code識別情報を保存し、template diff後に`cdk deploy --method=prepare-change-set`で実ChangeSetを作る。全paginationを確認して承認差分・replacement/deletionなしの場合だけ、その同じChangeSetを実行する。rollback元はGitの直前commitではなく保存済みdeployed構成とする。
- 最初のpreflight（2026-09-10）はSSO期限切れで停止したが、人間のlogin後に実caller/account/state/diffを再確認した。以下の途中validation記録は履歴であり、当時の未確認状態を現在地点としない。

## Production deployment evidence（2026-09-10 UTC）

設計承認後のdeploy commitは`b2b867f6d9b5581d1fd756330ffafd61dc92693e`、CI `34489664870`はsuccess。直前のdeployed template、resource physical IDs、IAM、Lambda code SHA/S3 asset識別情報とconfiguration比較結果を専用rootへ保存した。Lambda environment値は出力せず、deployed templateとの一致booleanだけを記録した。

`phase83-b2b867f-v1` ChangeSetをprepareし、property評価後の実ChangeSetは9 Add / 16 Modify、全ModifyのReplacement=false、Removeなしだった。templateの実変更は11 Lambda code、うち2 environment、2 IAM policy。追加表示された3 State Machineは参照再評価で、実ASLとsynthの意味的一致を確認した。初期previewの既存Permission Conditionalを見て直ちに実行せず、property評価後に当該変更が消えたことを確認してから同じChangeSetをexecuteした。

Control Planeは14:43:25 UTCにUPDATE_COMPLETE。全既存physical IDが不変でreplacement/deletionなし。11 LambdaはActive/Successfulでhandler/runtime/architecture/role/timeout/memory/environmentがsynthと一致、実deployed assetのprobe/parserはrepository v1.4と一致した。41 alarmの全設定がsynthと一致し、新Reconcile ruleはENABLED / rate(5 minutes)、固定scheduled_reconcile payload、target側とLambda async側はretry 0 / maximum event age 300秒をread-backした。Target/Frozen、永続Host file/unit、Docker/Compose、installed heartbeat producerは更新していない。

### 初期欠測通知と初回schedule delivery

6 alarmは14:41:44 UTC頃に作成され、observer更新・最初のdatapoint到着より先行した。missing=breachingの5 alarmが14:42:07〜14:42:59 UTCにINSUFFICIENT_DATAからALARMへ遷移し、ユーザーは5件の実メール受信を確認した。これはRuntimeIdentityMismatch、DataFilesystemObservationUnknown、SystemStateObservationStale、RuntimeHeartbeatUnavailable、RuntimeObservationUnknownの**metric欠測通知**であり、実測flag=1のidentity不一致・容量取得失敗等ではない。新規alarm初回deployではこの過渡通知があり得ることを事前に説明する。通知隠しのalarm無効化、missing-data変更、試験metric投入は行わない。

正常な停止中not-expected flag=0が到着し、5 alarmは14:46 UTC台に自然復帰、14:48:50 UTCのread-backで既存分を含む41 alarmすべてOKを確認した。ALARM actionだけなので復帰メールは送られない。容量highはmissing=ignoreであり、容量値がないことを容量正常の実測証拠とは扱わない。STOPPED中は4容量Percent/Bytes datapointなし、SSM commandなしだった。

EventBridgeの最初の14:42 UTC invocationはinvoke permission作成完了前でFailedInvocations=1となった。14:47 UTCの次回deliveryでReconcileが実行され、停止中Observedを14:48:07.894585Zへ更新した。初回失敗を継続成功に数えず、以降のperiodic成功とerror metricを別途照合する。重複・遅延が絶対にないことは前提にしない。

証跡: `/private/tmp/wishicraft-phase83-production-v1.sderKE/`（predeploy/readback/change-set/deploy/watch）、`/private/tmp/wishicraft-phase83-evidence-v2.Qr0JHW/stopped-evidence.jsonl`。最初の補助collectorはDescribeAlarmHistoryに未対応のAlarmNamePrefixを指定して途中失敗したため、その結果を完全証跡とは扱わない。公式APIに沿ってexact AlarmNameごとの取得へ修正したv2を別rootで実行し、元の失敗証跡を保持した。

### RUNNING監視と通常STOP

shared AdmissionのSTART `op-bbfcdb09-bc65-4532-880c-7b7e956ef839`は14:51:23 UTCに受付、14:55:27.085053ZにSUCCEEDED/READYとなった。手動Reconcileを繰り返さず、独立scheduleによるObserved更新を14:58:03.980022Z、15:03:04.185081Z、15:08:04.193742Zに確認した。15:10:45 UTCの最終RUNNING checkpointはREADY後15分18秒で、HEALTHY、heartbeat 15:10:13.790907Z、Current Operation/Lock/unfinished Operationなしだった。START grace終了後も通常監視を継続し、15:00–15:05と15:05–15:10 UTCの完了済みperiodで6異常flagと既存MonitoringObservationUnknownは0、41 alarmはOKだった。

実probe v1.4はmount `/srv/minecraft`、source `/dev/nvme1n1`、XFS UUID `420cea6d-0520-4436-bb5a-db1191f1e63b`、NVMe volume identity `vol-03ac9f534326c345c`を確認した。root volume `vol-092c04a633ffc6010`とは異なる。Game `game-vanilla-main`、runtime `wishicraft-host-runtime`、instance `i-04fc0629dc4ea466e`、boot `3525f917-fd64-4283-969c-c87b41bf7fd6`もheartbeatと一致した。

| 容量値 | 実probe / CloudWatch照合結果 |
|---|---:|
| total bytes | 32,145,145,856 |
| used bytes | 462,544,896 |
| available bytes | 31,682,600,960 |
| 100 * used / (used + available) | 1.4389261074504176% |

4容量metricの値・Percent/Bytes単位・namespace・固定Stage/SystemId dimensionsが実probeと一致した。80%未満という実測であり、high alarmのmissing=ignoreだけから正常とは判断していない。定期RUNNING ReconcileのLambda Durationは14:58に2,667.87 ms、15:03に2,638.01 msだった。これは今回の実測であり月間総費用の保証ではない。

保存済み14:56〜15:10 UTCの15 checkpointでは、SystemState observation ageの最大は288.788秒、heartbeat ageの最大は47.018秒だった。これはcheckpoint実測であり全瞬間の連続観測ではない。独立scheduleの複数実行時刻・正常probe・metricを組み合わせ、手動更新なしに10分以内を維持したことを確認した。

必要なRUNNING evidence取得後、shared Admissionのmanual STOP `op-8630fde9-a0ed-4133-8b02-4350ffcaad28`を15:11:07 UTCに一度だけ送信した。15:12:34の途中checkpointではEC2 stoppedでもCurrent Operation/Lockが残っていたためterminal assertionは失敗し、その証跡を保存して待機した。15:13:27 UTCにはSTOPPED/HEALTHY、DNS absent、Current Operation/Lock/unfinished Operationなしへ正常収束していた。結果不明の再送、Lock recovery、raw state補正は行っていない。

STOP Operationのcompleted_atは15:12:40.641823Zだった。15:13:04.131208Zには、STOP完了後の独立scheduleがstopped observationを更新した。START/STOPの業務semanticsを変更せず、D-093 warning/automatic STOPに到達する前にmanual STOPで終了した。

RUNNING証跡はproduction rootの`running-final-state.jsonl`、evidence-v2 rootの`running-final-evidence.jsonl`、`/private/tmp/wishicraft-phase83-probes-v3.jPc5WY/running-early.jsonl`。最初のprobe補助collectorはnested identityをtop-levelから投影してnullを出したため不完全として保持し、canonical nested identityをassertするv3で別rootへ再取得した。これはcollectorの失敗でありproduction telemetryのnullではない。

### 停止後最終判定とPhase 8 closeout

停止後の独立scheduled ReconcileはObservedを15:13:04.131208Z、15:18:04.507076Z、15:23:04.119999Zへ更新した。最終checkpointは15:25:39.038353Z、Desired revision 15 STOPPED / Actual stopped / Observed stopped / HEALTHY、discrepancy・observation error・DNS・Current Operation・Lock・unfinished Operationなし。最終heartbeatは15:11:14.602333Zのままで、TTL削除やheartbeat repairをせずnot-expectedとして扱った。

15:15–15:20、15:20–15:25 UTCの完全な2 periodで、6異常flagとMonitoringObservationUnknownはCount 0、4容量Percent/Bytesはdatapointなし、41 alarmすべてOKだった。停止後のSSM command metadataは0件、定期Reconcile/observerのErrors/Throttlesは実datapoint 0。EventBridge FailedInvocationsには新しい失敗datapointがなく、permission作成前の初回1件と区別した。停止を容量0%へ補正せず、high flag 0はnot-expectedへの移行を示すものとした。

最終inventoryと変更前の比較でTarget template/resources、Data EBS全metadata/attachment、SG、Game、SNS topic/subscription、Budget/全4通知・subscriberは不変。11 Lambda log retentionはすべて14日。Data EBSは同じ30 GiB encrypted gp3、DeleteOnTermination=falseを保持した。Budget actual 2.85 USD / forecast 7.371 USDはread-back時の値で、今月の確定請求や追加費用の実測ではない。RUNNING/STOPPED SystemStateのAttributeValue JSON表現はそれぞれ1,975/1,483 bytesだったが、これは通信表現サイズでありDynamoDB課金item sizeそのものではない。

START/STOP双方の実Step FunctionsもSUCCEEDED、START約243.224秒、manual STOP約89.044秒を確認した。STOP途中のDEGRADEDをHEALTHYへ補正せず、workflowのDNS/Observed収束を待った。5分observerがSTARTING/STOPPINGの全瞬間を採取したとは主張しない。grace期限、clock anomaly、identity mismatch、missing/unknown、capacity high、publication failure、Admission/save CAS raceはsynthetic検証済みで、productionで故障・競合を注入していない。初期欠測以外の新alarm異常遷移や実障害メールは未実施。受信した5件は初期欠測の実SNS Email delivery evidenceだけである。

最終read-backは全11 Lambda configuration/assetと41 alarmがsynth一致、schedule有効・5分・固定payload・target/async両retry 0・event age 300秒を確認した。Control Planeのpostdeploy canonical template diffは0。rollback・schedule無効化・追加のconfiguration修正deployは不要だった。production rootの`final-safe-state.jsonl`、`final-inventory.jsonl`、`final-readback.jsonl`、`final-template-diff.log`、`workflow-terminal-evidence.jsonl`とevidence-v2 rootの`stopped-final-evidence.jsonl`を保存した。

Phase 8.3とPhase 8全体をCompletedと判定する。8.1の実BACKUP/Discord/provenance/dry-run、8.2のcanonical 30分/5分・再接続・warning・STOP evidenceを再利用し、今回の監視・容量・鮮度・通知配線・最終安全状態でcompletion criteriaを充足した。RETENTION実削除はnormal backup自然8件以降の独立gate、Restore/復元試験はPhase 16、Phase 1 retirement/ownership整理は独立debt、Phase 9は未着手。新CloudWatch分3.60 USD/月は見積、8,640回は30日分のReconcile概算であり、Lambda/DynamoDB/logs込みの総費用上限ではない。

## Design and alarms

既存SystemState observerを継続し、独立した5分Reconcile scheduleで実観測を更新する。SystemState freshnessは10分のままであり、古いsnapshotをfresh扱いしない。scheduled pathはCurrent Operation/Lock存在時にskipし、保存はmonotonic observed_at、Desired revision一致、Current Operationが属性なしまたはnullという条件付き。checkとAdmissionのraceではSSM read-only probeが重なる可能性だけがあり、save CASでOperation前の状態を混入させない。

| Signal | Source / condition | Evaluation |
|---|---|---|
| RuntimeHeartbeatUnavailable | item missing、5分超、future/不正時刻、EC2 launch以前 | 5分Maximum、2/2 |
| RuntimeObservationUnknown | fresh heartbeatでもprotocol/active Gameがunknown、またはheartbeat信頼不能 | 5分Maximum、2/2 |
| RuntimeIdentityMismatch | System/runtime/instance/Game/boot不一致、boot形式不正 | 5分Maximum、2/2 |
| SystemStateObservationStale | Desired RUNNINGでSystemStateが10分超/不正時刻 | 5分Maximum、2/2 |
| DataFilesystemObservationUnknown | RUNNINGで容量を信頼できない | 5分Maximum、2/2 |
| DataFilesystemUsageHigh | valid usage >=80% | 5分Maximum、2/2 |

全flagはCount単位の0/1、threshold>=1。capacity high以外はmissing=breaching。capacity unknown時はhigh flagを発行せず、high alarmだけmissing=ignoreで直前状態を保持する。unknown/silenceの検出は独立したDataFilesystemObservationUnknownと既存observer監視が維持する。これにより観測不能をhigh alarmの復帰として送らない。namespaceは`Wishicraft/ControlPlane`、dimensionsは`Stage`/`SystemId`。発行対象を同一batchでPutMetricDataする。publication失敗はLambda failureを伝播する。監視だけの理由で新たなOperationを起動しない。

EC2 stoppedではheartbeatと容量はnot-expected。pending/stoppingではtransitionとし、既存Desired divergence、DesiredRunningNotReady、停止漏れalarmを維持する。EC2 running時は、Current Operationと有効Lockのowner一致、非future Desired timestampがある場合だけSTART 600秒/STOP 420秒のgraceを使う。期限到達で通常評価へ戻る。snapshot healthをHEALTHYへ補正せず、既存MonitoringObservationUnknownも維持する。

新alarmはALARM遷移で既存暗号化SNSに通知する。continuous abnormal flagを発行してもperiodごとの通知はしない。違反2/2が解ければOKへ戻り、復帰はalarm history/consoleで確認する。missing時のCloudWatch evaluation rangeと過去datapoint取得により、検出latencyは厳密なwall-clock 10分ではない。healthy sampleが新periodへ入り2/2を解くことと、producer停止後のmissingがbreachingとして扱われることをread-backする。

Data capacityはHost probe v1.4のstrict telemetryから取得する。mount path、XFS UUID、NVMe source serial（Data EBS ID）、directory fdのdevice、採取前後mountが一致する場合だけfstatvfsする。total=f_blocks*f_frsize、used=(f_blocks-f_bfree)*f_frsize、available=f_bavail*f_frsize、単位bytes。usage=100*used/(used+available)でreserved blocksをavailableへ含めない。`DataFilesystemUsagePercent`はPercent、`DataFilesystemUsedBytes/AvailableBytes/TotalBytes`はBytes。valid telemetry/SystemStateが10分以内、fresh heartbeatとのsame boot/identity照合を条件にし、停止/missing/unknown/stale時はこれら4値を送らない。容量値なしと「異常なしflag 0」を混同しない。実probeが観測したused=0だけは正当な0%である。

## IAM, host, cost, retention

- 変更stack: `WishicraftControlPlaneStack-dev`だけ。new schedule/rule permission、6 alarm、observer/Reconcile envと限定IAM、shared code assets。Target/Frozen stackのdeployは対象外。
- observer: RuntimeHeartbeats tableのGetItem追加。既存GetItem/DescribeInstancesを維持し、PutMetricDataへnamespace condition追加。SSM/Invoke/Desired/Lock write/secretなし。
- Reconcile: Locks tableのGetItem追加。既存SystemState UpdateItem、tag限定SSM、EC2/DNS readを再利用。START/STOP、Lock recovery、heartbeat repairなし。
- Host: SSM転送型probeだけv1.4。persistent file/unit、Docker/Compose、installed heartbeat v1.3、world、RCON、service enableは変更しない。heartbeat installerは今回実行しない。
- Budget: 15 USD、actual50/80/100%、forecast100%通知を維持。running8時間、停止漏れ15分、not-ready20分も維持。過去Budget超過額を現在額として扱わない。
- Log retention: 全Control Plane Lambda logをstageのdev14日/prod30日へ接続。devの実保持期間短縮なし。on-demand DynamoDB、Retain、heartbeat cleanup TTLを維持。
- S3: D-090 backupはEBS。archiveはDeferred、PackageはPhase 9以降。bootstrap assetsへ削除lifecycleを追加しない。retention実削除gateは独立。
- 増分: 6 standard alarm、最大10 classic custom metrics、5分schedule（30日で8,640回）、新Lambda/agentなし。observerは追加consistent GetItem一回/周期。Reconcileは最大8,640回/月、runningかつSSM onlineで最大同数のfixed Run Command、停止時はSSMゼロ。DynamoDB read/writeはitemサイズに依存し、容量map追加後も実itemサイズをread-backする。
- 費用見積は`6 * regional alarm price + (6 + 4 * running_fraction) * regional metric price + Lambda duration + DynamoDB + logs`を基本とする。metricは発行時間による按分、free tier/creditsは前提にしない。Run CommandはEC2利用に追加料金なしだが、Lambda/CloudWatch等は別課金。厳密なTokyo単価と現Budget actual/forecastはAWS preflight時に確認し、未取得の金額を確定値にしない。

## Read-only preflight

1. `tools/dev-env check`、`tools/dev-env auth-check`。GitHub認証とtool導入を分離する。CIはpytest/lint/type/synth/synthetic DockerだけでAWS/Discord writeなし。
2. `tools/dev-env run -- aws sts get-caller-identity --profile wishicraft-dev --region ap-northeast-1`のAccountをstageの`385526546525`と照合する。SSO期限切れなら人間の`aws sso login --profile wishicraft-dev`を依頼する。credential/tokenを表示しない。
3. CloudFormation `describe-stacks`/`list-stack-resources`の全paginationでControl PlaneとTargetのoutputs/resources/statusを記録し、deploy対象と実Targetを一意に確定する。Game/SystemState/Lock/heartbeatをcanonical table/keyでconsistent GetItemする。Current OperationがあればそのOperationと実executionをread-only照合し、稼働中の作業を変更しない。
4. EC2 DescribeInstances/DescribeVolumesでinstance、state、launch、Data EBS attachment、DeleteOnTermination=false、暗号化/gp3/size/SGを確認する。Route53 readでDNS状態を確認する。SSM SendCommand/Invoke/Reconcileはまだ実行しない。
5. CloudWatch DescribeAlarms、log retention、EventBridge rules/targets、SNS confirmation件数（Email値は出力しない）、Budget actual/forecast/notification設定をread-backする。既存ALARMを無効化せず原因とsnapshot時刻を記録する。
6. 新規専用temporary rootへsynth/diff evidenceを保存する。`cdk diff --method=template`（旧`--change-set=false`）を使用し、ChangeSet作成をしない。

```sh
tools/dev-env run -- npx --no-install cdk diff WishicraftControlPlaneStack-dev --context stage=dev --context phase=8 --context deployment=control-plane --profile wishicraft-dev --method=template
tools/dev-env run -- npx --no-install cdk diff MinecraftTargetStack-dev --context stage=dev --context deployment=target --profile wishicraft-dev --method=template
```

期待差分は上記監視構成とcode assetだけ。Target差分0、replacement/deletion0を実diffで確認する。Frozen Phase 1はdeployしない。unexpected IAM/resource/attachment/SG/DNS/durable data変更やresource曖昧性があればNO-GO。

## Production write gate and execution plan

### 2026-09-10 read-only preflight再開

14:15 UTC（23:15 JST）の実測で、canonical `wishicraft-dev`のSSO callerはAccount `385526546525`と一致した。Control Plane/TargetはUPDATE_COMPLETE。GameはACTIVE/MATERIALIZED、idle 30分、SystemStateはDesired revision 13 STOPPED、保存済みObserved stopped/HEALTHY（11:40:23 UTC）、discrepancy/errorなし、Current Operation属性なし、Lockなし、4 workflowのrunning executionなし。実EC2 `i-04fc0629dc4ea466e`もstopped、public IPv4/DNS absentである。保存済みObservationの古さをfreshとは扱わず、停止はdirect EC2で確認した。

Data EBS `vol-03ac9f534326c345c`は同Targetへ`/dev/sdf`でattached、30 GiB encrypted gp3、DeleteOnTermination=false。SG ingressはTCP 25565だけ。停止中なのでmount/使用量を新規観測せず、heartbeatは11:39:14 UTCのunknown/null最終recordが残存しているだけで、現在のheartbeatはnot-expectedである。

既存35 alarm全件OK、11 Lambda LogGroup全件14日、SNS confirmed email 1/pending 0（Email実値は証跡から除外）。Budgetは15 USD/HEALTHY、actual 2.85 USD/forecast 7.371 USD、actual 50/80/100%とforecast 100%の4通知すべて正本SNS subscriberを確認した。Budgetはcredit/discount込み設定であり、追加監視のgross単価見積と直接同一視しない。

証跡は`/private/tmp/wishicraft-phase83-preflight-v1.paNm6j/preflight.jsonl`。全paginationを取得し、Lambda invoke/SSM/ChangeSet/deploy/metric投入は未実行。固定CDK CLIのhelpとAWS公式資料に従い、`--method=template`で実deploy済みtemplateを比較した（`--change-set=false`の推奨後継）。Target差分0、Control Plane差分は監視追加のみ。これはChangeSetによるreplacement検証ではなくtemplate diffである。[CDK公式diff](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-diff.html)

preflightで既存Operation完了処理が`REMOVE current_operation_id`を使うことを確認し、新schedulerの明示NULL限定不具合をlocalで3 failuresとして再現した。handlerと保存CASだけを属性なし/NULLの両方へ整合させ、既存Lock存在時のskipも回帰検証する。実SystemStateの補正・raw repairは行わない。修正後のvalidation/diffは新規root `wishicraft-phase83-validation-v5.dn7yRg` / `wishicraft-phase83-preflight-v2.3dOqL0`へ保存し、v1 evidenceを上書きしない。

修正後はfocused 25 passed、full pytest **852 passed**、Ruff check/format成功、no-incremental mypy 128 files成功。最終Control Plane synth/template diffは追加9・削除0、既存変更は11 LambdaのCode（共通asset更新）、うち2 LambdaのEnvironment、2 IAM Policyだけで、replacement表示はない。新共通assetは`4e207af4c04b39696a8ba91fa7f055ff7835d3282052b9cde033f8f489e439fd`。未変更Targetの実diff 0とPhase 1 synth既存evidenceは再利用し、commit後CIで3 synth/shellcheck/synthetic integrationも確認する。

`preflight-v2.3dOqL0/check.jsonl`には全resource property差分の機械的検査と実Reconcile/observerの公開environment・inline/attached IAM read-backを保存した。Reconcileは既存のtag限定SSM、固定Hosted Zone read、SystemState Get/Update、observerは既存のstate/lock Get・EC2 describe・metric publishと、双方のbasic loggingだけである。今回広いsecret/lifecycle権限を追加せず、上記2限定GetItemとmetric namespace制限だけを適用する。D-094はproduction GOまでProposedのままとする。

基準commit `fb1b2c5`と今回実装のcredential不要template比較では、119→128 resources、35→41 alarms、新規9（6 alarm/EventBridge rule/Lambda permission/EventInvokeConfig）、削除0。既存変更は11 Lambda code、うちReconcile/observerのenvironment、2 IAM policyだけ。table/State Machine/Target/SG/DNS/Budget/log retention実値の変更はない。この比較は実AWS diffの代替ではない。baseline archiveとsynth evidenceは`/private/tmp/wishicraft-phase83-baseline-v2.N73DU5`に保持する。

HEAD/clean tree/origin/CI、validation evidence、D-094、実AWS状態、diff、費用増分と下記手順を一度に提示する。SSO失効や未実施preflightがある間はREADYを宣言しない。最初のproduction write前に一度だけ承認を得る。

承認対象はControl Plane deployとscheduled Reconcileの有効化、必要な通常START/STOPによるmonitoring verificationである。30分automatic STOP E2Eは繰り返さない。実環境異常を演出するfake heartbeat/SystemState、時刻改変、disk-full、試験metric/通知の注入は使わない。

```sh
tools/dev-env run -- npx --no-install cdk deploy WishicraftControlPlaneStack-dev --context stage=dev --context phase=8 --context deployment=control-plane --profile wishicraft-dev --require-approval never
```

1. 実行直前にcaller/state/Lock/HEAD/diffを再確認。deploy中に意味不明なmutationがあれば停止する。
2. CloudFormation UPDATE_COMPLETE後、実template/IAM/env/rule/alarm/log retentionをread-back。転送probe payloadとprobe parserがv1.4で一致することをcode assetから確認する。新たなEC2/SSM/DNS/secret権限がobserverへないことを確認する。
3. STOPPEDならnot-expected metricsと容量値なし、2 period後alarm stateを確認する。periodic ReconcileがstoppedでSSMを呼ばずObservedだけを更新することをevent evidenceで確認する。
4. 承認された既存Admission経由STARTを一回実施しREADYまで進める。heartbeatは元producerの60秒、probe telemetryは5分、SystemState freshnessが10分を超えないことを少なくとも15分にわたる保存済みcheckpointで確認する。Game/runtime/boot/instance/source/UUIDとbytesを検証する。loop中に不要なSSM probeを追加しない。
5. 実容量>=80%なら正常なwarningとして扱い、通知/recordの対応を確認する。満杯化しない。自然なmissing/staleが発生しなければ、そのalarm遷移はsynthetic testでのみ検証済みと報告する。新alarmのSNS配線と既存confirmed pathはread-backし、fake incidentを発生させない。
6. 既存Admission経由のmanual STOPで最終STOPPED/HEALTHY、DNS absent、Lock/Current Operationなし、Data EBS保持へ戻す。heartbeat last recordは残ってよく、TTL削除を待たない。容量値を停止後に0へ補正しない。
7. metrics/alarms/schedule/error historyのtimestamp付き証跡、CI、docs/commit/push、Learning Wiki、clean tree、local-origin一致をcloseoutする。

停止条件は対象不一致、unknown mutation result、Lock recovery必要、広い権限、world/volume変更、継続的SSM failure、想定外alarm/cost増加。automatic repairは行わない。rollbackは保存済み直前template/HEADへControl Planeだけを戻し、新schedule/alarm/IAM追加を除去する。既存Observationをraw rollbackせず、元の正規Reconcileで収束させる。新規alarm削除等も承認済みrollback範囲に明示してから実施する。Target/world/heartbeatにはrollback write不要。

## Repository validation履歴（当時の状態）

以下のSSO未完了・production未実行は各途中checkpointの履歴であり、現在の状態ではない。現在のproduction結果は上記evidenceを参照する。

Repository validation（2026-09-10）: full pytest 849 passed、Ruff check/format成功、mypy 128 source files成功、shell syntax成功、dev Phase 1/Target/Phase 8 Control Plane synth成功。Docker CLI/local shellcheckは未導入（optional）。最初のfull runは847 passed/2 bundling DNS failures、最初のControl Plane synthもsandbox DNSで失敗し、既存`tools/setup-dev-tools bundling-cache`後、新しい専用rootで全件再検証した。skipで成功扱いにしていない。

最終reviewでcapacity unknownからfalse recoveryを発行しない回帰を追加した後、`/private/tmp/wishicraft-phase83-validation-v3.FfVkRG`へ新しい証跡を保存し、full pytest **850 passed**、Ruff check/format、mypy 128 files、Control Plane synthを再度成功させた。Phase 1/Targetに追加変更はないため、それらのsynth成功証跡はv1を再利用する。production preflightはSSO期限切れのため引き続き未完了である。

Local evidence: `/private/tmp/wishicraft-phase83-validation-v1.1CT2Jn`（最初の結果、lint/type/Phase 1/Target synth）、`/private/tmp/wishicraft-phase83-validation-v2.8DX4aJ`（849 passed/Control Plane synth）。uvはvenvでPython user baseが変わる条件を再現し、既存macOS user installation discoveryで解消、子process/CDK bundlingでも利用できた。GitHub認証とorigin/mainはread-only確認成功。AWS STSはSSO期限切れのため実Account/実state/credential-backed diff未確認。production write/実環境E2Eは未実行。

最初のCI `34485618133`はpytest/synthetic integration成功後、既存STOP Lambdaのboto3 import ignoreが`import-not-found`のままである不整合を検出した。boto3をdev依存へ追加したことで分類は`import-untyped`となるため、注釈だけを修正する。STOPの実行動作・30分/5分/final gateは変更しない。local incremental mypyの既存cacheで検出されなかったため、最終型検査は`--no-incremental`を使用する。

修正後の`mypy --no-incremental src infrastructure tests`は128 filesで成功し、Ruff check/formatも成功した。証跡は`/private/tmp/wishicraft-phase83-validation-v4.Ok19v7/mypy.log`。実行コードは注釈以外に変更がないため、local full pytestの850 passedは再利用し、修正commitのCIでもfull validationを行う。

続くCI `34486136649`はpytest/lint/type/3 synth/synthetic integration成功後、uv fallback条件の`A && B || continue`をshellcheck SC2015が指摘した。同じ判定を2つの明示checkへ分け、toolchain回帰testを再検証する。指摘を無効化・skipしない。

2026-09-10にAWS公式公開Price List（publicationDate 2026-08-31）のTokyo単価をread-only確認した。classic custom metricは最初の10,000件で0.30 USD/metric-month、standard alarmは0.10 USD/alarm-month。新規10 metricsを全月発行する保守的見積は3.00+0.60=**3.60 USD/月**で、Lambda/DynamoDB/logsは別途。停止中は容量4 metricsを発行しないため実際は稼働時間に依存する。free tier/creditsを控除せず、Budget 15 USDは維持する。[公式regional Price List](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/ap-northeast-1/index.json)。現在のBudget actual/forecastはSSO復旧後のpreflightで確認する。

GO後の最終local validationはcanonical toolchainでfull pytest **852 passed**、Ruff check/format成功（160 files）、`mypy --no-incremental`成功（128 files）、dev Phase 1/Target/Phase 8 Control Planeの3 synth成功。最初のrunは845 passed / 7 CDK bundling failures（sandbox DNSでPyPI依存を取得不能）で、実装失敗と分離し結果を保持した。同じlocked dependencyをnetwork許可下の新rootで全件再実行し、skipなしで852 passedとなった。証跡: `/private/tmp/wishicraft-phase83-closeout-validation-v1.NTNWzN/`（失敗）、`/private/tmp/wishicraft-phase83-closeout-validation-v2.NJAbzX/`（成功・3 synth）。Docker/local shellcheckはoptionalの未導入、CIで実行する。

今回の対象はheartbeat/observation freshness/identity監視、Data EBS usage/unknown監視、既存失敗通知とコスト・ログ保持の整合。8.1 BACKUPとdurable provenance/dry-run RETENTION、8.2 automatic STOPの完了evidenceは再利用する。実削除release、Restore（Phase 16）、Package/Game抽象（Phase 9以降）、bootstrap/Phase 1 retirement debtは独立であり、今回へ戻さない。

## Official references

- [CloudWatch namespace IAM condition](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/iam-cw-condition-keys-namespace.html)
- [PutMetricData limits, types and timestamps](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricData.html)
- [CloudWatch alarm behavior](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Alarms.html)
- [EBS NVMe device identity and volume serial](https://docs.aws.amazon.com/ebs/latest/userguide/identify-nvme-ebs-device.html)
- [statvfs filesystem counters](https://docs.python.org/3.12/library/os.html#os.statvfs)
- [CloudWatch regional pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Systems Manager pricing](https://aws.amazon.com/systems-manager/pricing/)
