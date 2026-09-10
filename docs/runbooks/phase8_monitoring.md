# Phase 8.3 monitoring production gate

- 対象は既存実環境のdev stage。`prod.yaml`はplaceholderのまま。
- 状態: repository implementation / D-094 Proposed。production write未承認。
- 最初のpreflight（2026-09-10）で`wishicraft-dev`のSTS確認がSSO期限切れにより失敗した。Account/実AWS状態/diffは未確認。過去closeoutを現在のevidenceにしない。

## Design and alarms

既存SystemState observerを継続し、独立した5分Reconcile scheduleで実観測を更新する。SystemState freshnessは10分のままであり、古いsnapshotをfresh扱いしない。scheduled pathはCurrent Operation/Lock存在時にskipし、保存はmonotonic observed_at、Desired revision一致、Current Operation=null条件付き。checkとAdmissionのraceではSSM read-only probeが重なる可能性だけがあり、save CASでOperation前の状態を混入させない。

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
6. 新規専用temporary rootへsynth/diff evidenceを保存する。`cdk diff --change-set=false`を使用し、ChangeSet作成をしない。

```sh
tools/dev-env run -- npx --no-install cdk diff WishicraftControlPlaneStack-dev --context stage=dev --context phase=8 --context deployment=control-plane --profile wishicraft-dev --change-set=false
tools/dev-env run -- npx --no-install cdk diff MinecraftTargetStack-dev --context stage=dev --context deployment=target --profile wishicraft-dev --change-set=false
```

期待差分は上記監視構成とcode assetだけ。Target差分0、replacement/deletion0を実diffで確認する。Frozen Phase 1はdeployしない。unexpected IAM/resource/attachment/SG/DNS/durable data変更やresource曖昧性があればNO-GO。

## Production write gate and execution plan

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

## Phase 8 completion

Repository validation（2026-09-10）: full pytest 849 passed、Ruff check/format成功、mypy 128 source files成功、shell syntax成功、dev Phase 1/Target/Phase 8 Control Plane synth成功。Docker CLI/local shellcheckは未導入（optional）。最初のfull runは847 passed/2 bundling DNS failures、最初のControl Plane synthもsandbox DNSで失敗し、既存`tools/setup-dev-tools bundling-cache`後、新しい専用rootで全件再検証した。skipで成功扱いにしていない。

最終reviewでcapacity unknownからfalse recoveryを発行しない回帰を追加した後、`/private/tmp/wishicraft-phase83-validation-v3.FfVkRG`へ新しい証跡を保存し、full pytest **850 passed**、Ruff check/format、mypy 128 files、Control Plane synthを再度成功させた。Phase 1/Targetに追加変更はないため、それらのsynth成功証跡はv1を再利用する。production preflightはSSO期限切れのため引き続き未完了である。

Local evidence: `/private/tmp/wishicraft-phase83-validation-v1.1CT2Jn`（最初の結果、lint/type/Phase 1/Target synth）、`/private/tmp/wishicraft-phase83-validation-v2.8DX4aJ`（849 passed/Control Plane synth）。uvはvenvでPython user baseが変わる条件を再現し、既存macOS user installation discoveryで解消、子process/CDK bundlingでも利用できた。GitHub認証とorigin/mainはread-only確認成功。AWS STSはSSO期限切れのため実Account/実state/credential-backed diff未確認。production write/実環境E2Eは未実行。

最初のCI `34485618133`はpytest/synthetic integration成功後、既存STOP Lambdaのboto3 import ignoreが`import-not-found`のままである不整合を検出した。boto3をdev依存へ追加したことで分類は`import-untyped`となるため、注釈だけを修正する。STOPの実行動作・30分/5分/final gateは変更しない。local incremental mypyの既存cacheで検出されなかったため、最終型検査は`--no-incremental`を使用する。

修正後の`mypy --no-incremental src infrastructure tests`は128 filesで成功し、Ruff check/formatも成功した。証跡は`/private/tmp/wishicraft-phase83-validation-v4.Ok19v7/mypy.log`。実行コードは注釈以外に変更がないため、local full pytestの850 passedは再利用し、修正commitのCIでもfull validationを行う。

続くCI `34486136649`はpytest/lint/type/3 synth/synthetic integration成功後、uv fallback条件の`A && B || continue`をshellcheck SC2015が指摘した。同じ判定を2つの明示checkへ分け、toolchain回帰testを再検証する。指摘を無効化・skipしない。

2026-09-10にAWS公式公開Price List（publicationDate 2026-08-31）のTokyo単価をread-only確認した。classic custom metricは最初の10,000件で0.30 USD/metric-month、standard alarmは0.10 USD/alarm-month。新規10 metricsを全月発行する保守的見積は3.00+0.60=**3.60 USD/月**で、Lambda/DynamoDB/logsは別途。停止中は容量4 metricsを発行しないため実際は稼働時間に依存する。free tier/creditsを控除せず、Budget 15 USDは維持する。[公式regional Price List](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/ap-northeast-1/index.json)。現在のBudget actual/forecastはSSO復旧後のpreflightで確認する。

今回閉じる項目はheartbeat/observation freshness/identity監視、Data EBS usage/unknown監視、既存失敗通知とコスト・ログ保持の整合。8.1 BACKUPとdurable provenance/dry-run RETENTION、8.2 automatic STOPの完了evidenceは再利用する。実削除release、Restore（Phase 16）、Package/Game抽象（Phase 9以降）、bootstrap/Phase 1 retirement debtは独立であり、今回へ戻さない。production validation完了まではPhase 8.3 pendingを維持する。

## Official references

- [CloudWatch namespace IAM condition](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/iam-cw-condition-keys-namespace.html)
- [PutMetricData limits, types and timestamps](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricData.html)
- [CloudWatch alarm behavior](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Alarms.html)
- [EBS NVMe device identity and volume serial](https://docs.aws.amazon.com/ebs/latest/userguide/identify-nvme-ebs-device.html)
- [statvfs filesystem counters](https://docs.python.org/3.12/library/os.html#os.statvfs)
- [CloudWatch regional pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Systems Manager pricing](https://aws.amazon.com/systems-manager/pricing/)
