# 09. Decisions and Backlog

- **文書状態:** Canonical
- **最終更新:** 2026-09-01
- **追記:** 2026-08-15 Minecraft初回起動のExecStartPre再開契約

## 1. Decision logの使い方

設計判断を変更する場合、既存決定を削除せず、`Superseded by D-xxx`として履歴を残す。

## 2. 採用済み決定

### D-090 Phase 8 MVPは停止中Data EBSのOperation-scoped Snapshotとする

- **状態:** Accepted（Phase 8A repository contract）
- **日付:** 2026-09-02
- Phase 8 MVPはroot EBSを除外し、current persistent encrypted Data EBSだけをbackupする。BACKUPはD-026/D-074のshared Admissionとglobal Lockを使用し、START/STOP/BACKUP同士を排他する。fresh Desired STOPPED、Actual/Observed stopped、HEALTHY、discrepancyなし、Lock/current operationが当該BACKUP所有である場合だけ進め、BACKUP自身はSTOP/STARTしない。
- current storageはData EBS 1本、active Game 1件であり、`game-vanilla-main`をVolumeへ明示bindingする。`/srv/minecraft/games/`は将来複数Gameを保持可能なので、Phase 9で2件目を有効化する前にdedicated/shared Volumeとretention ownershipを再Decisionする。
- AWS `CreateSnapshot`はclient tokenを持たない。Operation IDをlogical backup identityの根にし、同名Standard execution、一回限りでRetryなしのcreate intent、inline Operation/category/source tags、同一idempotency replayで新規executionなし、というat-most-one contractを採用する。create outcome不明、poll timeout、verification mismatchでは新しいsnapshotを作らずOperationをFAILEDとし、既存snapshotを自動削除しない。
- 成功は`completed`、expected source volume、account ownership、全metadata一致後だけとする。通常backupはGame単位newest 7、migration/protectedは除外するが、Phase 8Aはpure selectionだけで`DeleteSnapshot`を実装・許可しない。
- Restore、schedule、RUNNING/application-consistent backup、Discord production commandは後続sliceとする。EBS incremental snapshot storageは課金対象であり、既存15 USD Budgetとは別Budgetを追加せず、将来retention automationが必要である。
- **関連:** D-017、D-026、D-029、D-032、D-036、D-043、D-045、D-053、D-074。

### D-089 Discord initial ACKはshared Admissionより先に外部callbackで確定する

- **状態:** Accepted（Phase 7G-3 production failure recovery）
- **日付:** 2026-09-01
- HTTP Interactionの署名検証、strict parse、Application/Guild/channel/role認可が成功した後、DiscordのInteraction callback endpointへtype 5 ephemeral deferred ACKを送る。ACKはOperation acceptanceを意味せず、成功した場合だけ既存shared Admissionを同期invokeする。ACK失敗時はAdmission前にfail closedし、inline responseとの二重ACKを行わない。
- ACK後のAdmission success/failureは、15分だけ有効なInteraction tokenをprocess memory内で使ってoriginal ephemeral responseへsafe acknowledgementとして反映する。この短期edit失敗はOperation resultを変更しない。tokenはOperation/DynamoDB/log/metric/exceptionへ保存せず、Command LambdaはBot Tokenを読まない。
- 元のHTTP requestは外部callback成功後にDiscord公式contractどおり202/empty bodyとする。PINGは従来どおりinline PONG、authorization rejectionは本人限定inline responseを維持する。Command Lambda timeoutは3秒からbounded 10秒へ変更するが、3秒deadlineの解決根拠はtimeout延長ではなくACK-before-Admission orderingである。
- START/STOP/STATUSのAdmission、idempotency、Lock/Desired/workflow contractは変更しない。長時間progress/final identityはInteraction tokenへ戻さず、D-086の通常Bot message、nonce、CAS deliveryを維持する。
- **Production evidence:** Gate 1 parser fix後のreal STATUSはOperation `SUCCEEDED`、fresh stopped/HEALTHY projection、public message一件、delivery `DELIVERED`まで成功した。一方Command Lambdaは同期Admission待機中に3000ms timeoutし、API Gateway integration latency 3015ms / 5xx 1となった。Admission cold start込み2921.89msはcaller timeout後に完了したため、Control Plane safety stateはSTOPPEDのままOperationだけが正規に一件増えた。timeout alarmは既知incidentとして自然evaluationまで手動変更しない。
- **関連:** D-079〜D-087、D-045、D-074。

### D-088 Phase 7 release monitoringはread-only observerと独立SNS通知で構成する

- **状態:** Accepted（Phase 7G-M dev deployed / notification validated）
- **日付:** 2026-09-01
- D-032のstate-based監視は5分周期のsmall LambdaがSystemState、global Lock、Target EC2をread-only取得し、`Wishicraft/ControlPlane` custom metricだけを発行する。Reconcile、Desired/Lock/Operation write、START/STOP、EC2 mutation、Discord、secret access、自動remediationを行わない。
- Target running 8時間、Desired STOPPEDかつrunning 15分、Desired RUNNING未READY 20分をstage設定の正本とする。Desired/Actual divergenceは3連続period、RUNNING時のObserved freshness/UNKNOWNは10分を独立監視する。stable STOPPEDはdirect EC2 observationで評価できるため、不要なReconcile writeを監視pathへ導入しない。expired Lockは900秒leaseの`lease_expires_at`を現在UTC epochと比較し、存在だけではalarmにしない。
- START/STOP failure/timeout/abortはAWS Step Functions native metrics、重要LambdaはErrors/Throttles native metricsを使用する。custom state metricsはobserver silenceをproblemとしてmissing=breaching、native event metricsはeventなしをnormalとしてmissing=notBreachingとする。
- primary notificationはcustomer-managed KMS keyで暗号化したstage SNS TopicとEmail subscriptionとする。Email実値・subscriptionはCDK外の明示operator actionに分離する。AWS Budgetはdev account monthly 15 USD、actual 50/80/100%、forecasted 100%を同Topicへ通知する。Discord admin channelは循環依存を避けprimary通知にしない。
- monitoringはobserverでありControl Plane truthを変更しない。alarm/SNS/Budget failureはMinecraft Operation resultへ逆流せず、Phase 8のauto-remediationとは別Decision境界を維持する。
- **Dev validation:** 2026-09-01にCI success済みHEADからControl Plane stackだけをdeployし、CloudFormation `UPDATE_COMPLETE`、5分schedule、6 custom state metrics、24 alarms全件`OK`、暗号化SNS Topic、confirmed Email subscription、secret-free notification smoke受信、monthly 15 USD Budgetと4 SNS通知、14日observer log retentionを確認した。Email実値はoperator非表示入力に限定し記録していない。observer IAMはSystemState/Locks read、EC2 describe、metric publish、loggingだけであり、Minecraft/Control Plane stateを変更しなかった。
- **関連:** D-032、D-048、D-074、D-082。

### D-087 START progressはOperation progress revisionで単調配信する

- **状態:** Accepted（Phase 7E repository validated）
- **日付:** 2026-08-31
- Discord `/mc start`は既存Admission Lambdaを同期invokeし、shared START AdmissionだけがOperation、Lock、lease、Current Operationと既存START State Machine executionを作る。initial response orderingはD-089でACK-before-Admissionへ更新するが、Interaction tokenを長時間progress identityへ使用しない本Decisionのdelivery contractは維持する。
- Operation itemに単調増加する`progress_revision`を追加する。Admissionは0、公開対象となる`current_step`/terminal status transitionは同じconditional update/transactionでrevisionを1増やす。Operations Stream eventはこのrevisionをdelivery source identityとし、Message componentのconsistent readがevent revisionより新しければstale eventをno-opにする。
- 初回revisionはD-086 nonceで通常messageを一件作り、以後は保存済み`message_id`をeditする。delivery metadataはsource/delivered revisionをCAS管理する。metadata-only MODIFYはprogress revisionが変わらないためdeliveryしない。古いrevisionのFAILEDは新しいrevisionをblockせず、新revisionごとにbounded attemptを開始できる。
- progress delivery failureはD-082どおりSTART Operation、Lock、Desired、State Machineを変更しない。terminal success/failureは既存START Operation status/errorだけからsafe projectionし、DiscordがEC2/DNS/READYを独自判定しない。
- **関連:** D-079、D-081〜D-086、D-045、D-074。

### D-086 Discord通常messageはOperation nonceとdelivery CASで冪等化する

- **状態:** Accepted（Phase 7D repository validated）
- **日付:** 2026-08-31
- Discord Interaction tokenは15分だけ有効で、最大30分のSTARTと整合せず、既存契約もtoken永続化を禁じる。このためdeferred original responseを長時間Operationの公開message identityにはせず、D-027どおりMessage componentがBot Tokenでoperation channelへ通常messageを作る。
- Discord Create Messageの`nonce`（最大25文字）と`enforce_nonce=true`を使用する。Operation IDのSHA-256先頭128 bitをbase36固定25文字へ写像し、同一Operationのcreate retryでは同じnonceを使う。128 bit identityによりOperation間衝突を実用上無視できる水準へ抑える。create成功後・`message_id`条件付き保存前にLambdaが停止しても、同じStream event identityの再実行がDiscordの直近数分のnonce重複排除により既存message IDを回収する。
- nonce重複排除は無期限ではないため、create成否不明の自動回復窓を30秒に限定する。PENDINGのまま、またはtimeout/network/5xx/malformed successで成否不明の状態が窓を越えた場合、新しいmessageを作らずdeliveryだけを`FAILED / DISCORD_CREATE_OUTCOME_AMBIGUOUS`へfail closedする。429はcreateされていない応答として`retry_after`を尊重する。
- STATUS terminal transitionをOperations StreamからMessage componentへ渡す。retryable delivery metadataのconditional updateが次のStream eventとなり、SQS delay queueへenqueueするため、executorからのfire-and-forget gapを作らない。delivery attemptは最大3回、SQSとStreamはbatch size 1、暗号化DLQを持つ。429の`retry_after`がSQS per-message delay上限900秒を越える場合は早すぎるretryをせずdelivery failureへfail closedする。duplicate event、queue message、worker raceはdelivery status/attempt IDのCASで一つのlogical messageへ収束する。
- optional `discord.delivery_*` metadataと`message_id`だけを更新し、Operation `status/result/error`、SystemState、Desired、Lock、Current Operationを変更しない。Discord上でmessageが削除された、または保存済みmessage IDへのupdateが404となった場合も、自動re-createせずdelivery failureとして隔離する。
- Bot TokenはMessage Lambdaだけが固定SecureString一件をruntime取得する。Command LambdaとSTATUS executorへsecret readを付与しない。Message LambdaはOperations Get/Update、retry queue、logging以外のControl Plane/AWS lifecycle権限を持たない。
- **関連:** D-027、D-045、D-081〜D-083、D-085。

### D-085 STATUS executorはOperations Stream駆動async Lambdaとする

- **状態:** Accepted（Phase 7C repository validated）
- **日付:** 2026-08-31
- 現行Reconcileは1回のLambda invocationでfresh observationとObserved保存まで完結し、durable waitやmulti-stage orchestrationを必要としない。このためSTATUS専用Standard State Machineは追加せず、small async Lambdaを採用する。
- Command LambdaによるAdmission後の直接async invokeは、Operation commitとdispatchの間にfailure/unknown gapを作る。既存Admission transactionが作るOperations INSERTをDynamoDB `NEW_IMAGE` Streamのdispatch sourceとし、STATUS INSERTだけをfilterする。duplicate idempotencyは新規INSERTを作らないためexecutorも増殖しない。
- Stream deliveryはat-least-onceであり、executorは同じoperation_idを使用する。既存STATUS専用`complete_unlocked`をresult対応へ拡張し、terminal retryをno-opとする。Reconcile failureはgeneric unknown projectionと分類済みerrorでterminal化し、executor/terminal write failureはbounded retry後に暗号化DLQへ送る。
- Command LambdaはAdmission Lambda invokeだけ、executorはOperations Get/UpdateとReconcile Lambda invokeだけを持つ。Lock、lease、Current Operation、Desired、START/STOP State Machine、Bot Token、EC2/SSM/Route 53 direct権限を追加しない。
- Phase 7CはprojectionをOperation resultへ保存するまでとし、Discord API delivery、`message_id` persistence/recoveryはD-081/D-082に従いPhase 7Dで実装する。

### D-084 Discord command schemaとregistration mutationを分離する

- **状態:** Accepted（Phase 7G-2 production validated）
- **日付:** 2026-08-30
- `/mc status`、`/mc start`、`/mc stop`のcommand schemaはGit上のversioned artifactを正本とする。
- Discord APIへのGuild command registration/updateはCDK deployの暗黙side effectにせず、明示的なoperator script/runbookとして実行する。AWS infrastructure mutationとDiscord external configuration mutationを別のreview・実行・証跡境界にする。
- Phase 7Aではregistrationを実行しない。dev Application/Guildの公開ID一致とBot Token SecureStringの存在確認はPhase 7B/Gのpreflight blockerとして追跡する。
- Phase 7Bで`config/discord/commands.v1.json`をversioned正本として追加した。repository/CDK実装はDiscord API registrationを行わず、external mutation境界を維持する。
- Phase 7G-2でdev Guildへ明示POST upsertし、登録前0件、登録後`mc`一件、global 0件をread-backした。Discord APIでは`integration_types`と`contexts`はglobal command専用でGuild read-backに存在しないため、Guild registration正本から両fieldを除外した。Guild限定性はendpoint scopeとD-079のapplication-side認可で維持し、unrelated commandを削除するbulk overwriteは使用しない。

### D-083 Discord Bot TokenのIAM境界

- **状態:** Accepted（Phase 7A）
- **日付:** 2026-08-30
- Interaction ingress/Command Lambdaはstage設定のDiscord Public Keyだけで署名を検証し、Bot Tokenを読まない。Bot Tokenを読むIAMはDiscord Message componentだけへ分離し、固定`/wishicraft/<stage>/secret/discord-bot-token`の`ssm:GetParameter`に限定する。
- Command Lambda、START/STOP/STATUS executor、Reconcile、Minecraft TargetへBot Token readを付与しない。Message componentにはEC2、SSM、RCON、DNS、Desired/Lock mutation権限を付与しない。
- secret実値はGit、Lambda environment、SSM/Discord command argument、Operation、Step Functions input、fixture、snapshot、logへ保存しない。既存D-040のSecureString方針を精密化する。
- Phase 7B Command Lambdaは公開ID/Public Keyだけをenvironmentへ受け、application IAM policyを持たない。Bot Token parameter名もasset、template、environmentへ含めないことをinfrastructure testで固定する。

### D-082 Discord delivery failureをControl Plane resultから分離する

- **状態:** Accepted（Phase 7A）
- **日付:** 2026-08-30
- Discord message create/updateはOperation/Observed Stateのuser-facing projectionであり、Control Plane stateの正本ではない。delivery errorによって成功済みSTART/STOP/STATUSをFAILEDへ変更せず、Minecraft/AWS failureをDiscord successとして扱わない。
- delivery failureはstructured log、metric/alarm、および必要なら後方互換なoptional delivery metadataで別に観測する。Operation schema変更の要否とmigrationはPhase 7Dで確定する。
- D-045の「Discord進捗は任意adapter」をDiscord MVPのfailure semanticsとして具体化する。

### D-081 公開progress messageはOperation単位で冪等にする

- **状態:** Accepted（Phase 7A）
- **日付:** 2026-08-30
- START/STOP等の公開progress/resultは原則1 Operationにつき1 Bot channel messageとする。Interaction再送、Admission duplicate、workflow/Lambda retryで新規messageを増殖させない。
- Operationの既存Discord metadataにある`message_id`をmessage identityとして条件付きで一度だけ関連付け、以後は同一messageを更新する。create成功とidentity保存の境界で必要なrecovery/idempotency方式はPhase 7DでAPI behaviorと既存schema migrationを確認して決める。
- Interaction Tokenは長時間更新に使用・永続化せず、同一Interaction payloadは既存payload-aware idempotencyで同じOperationへ対応付ける。

### D-080 STATUSは非Lock Operationとして非同期fresh Reconcileを実行する

- **状態:** Accepted（Phase 7A）
- **日付:** 2026-08-30
- `/mc status`は明示STATUS Operationとして既存Admissionへadmitし、payload-aware idempotencyを持つ。D-046どおりLockを取得せず、`SystemState.current_operation_id`も設定しない。
- 保存済みSystemStateをそのまま表示して完了せず、非同期executorがfresh Reconcileを行い、その結果をDiscordへprojectする。Interaction handlerはReconcile完了まで同期的に待たず、期限内にDeferred Responseを返す。
- executorを小さいStandard Step Functionsとasync Lambdaのどちらにするかは、Phase 7Cで既存Reconcileのtimeout、retry、追跡性、IAM最小化を比較して確定する。方式未決定でも本Decisionのadmission/state contractは変更しない。

### D-079 Discord MVP authorizationとControl Plane adapter境界

- **状態:** Accepted（Phase 7A）
- **日付:** 2026-08-30
- `/mc status`、`/mc start`、`/mc stop`はstage設定のGuildかつoperation channelに限定し、memberがplayer roleまたはadmin roleを持つ場合だけ許可する。admin roleの通常操作もoperation channelを使用し、admin channelは後続recovery/reset/maintenance用に予約する。
- Discord command permissionはUX補助であり、Command Lambdaがsignature検証後にGuild、channel、roleをapplication側で必ず検証する。権限不足と入力errorは本人限定で返す。
- Discordは既存Operation Admission、START/STOP workflow、STATUS/Reconcileへのexternal adapterである。Desired、Lock、lease、`current_operation_id`、EC2、SSM、RCON、Minecraft、DNSを直接操作せず、State MachineをAdmission抜きで起動しない。
- D-074〜D-078のownership、CAS、freshness、typed Host Runtime、STOP/RCON安全契約をDiscord向けに複製・緩和しない。
- Phase 7Bではsignature-first、Application/Guild/operation channel exact match、player OR admin roleを実装した。valid commandでもControl Plane mutationは未接続とし、Phase 7C以降のadapter接続前にtrust boundaryだけを独立検証する。

### D-078 itzg生成RCON CLI configは固定2件だけephemeral RW nested bindとする

- **状態:** Accepted（production validated）
- **日付:** 2026-08-30
- **Upstream rationale:** 固定itzg `2026.7.2`の`start`はruntime UID/GIDへ切り替えて`start-configuration`を実行し、同scriptは`HOME=/data`、`RCON_PASSWORD_FILE`を読み、`$HOME/.rcon-cli.env`と`$HOME/.rcon-cli.yaml`へcontainer-local `rcon-cli`設定を書き込む。このupstream write contractのため生成config destinationはwritableでなければならない。
- **Decision:** password fileは固定`/run/wishicraft/rcon-password`から`/run/secrets/rcon-password`へのRO bindを維持する。生成configだけは`/run/wishicraft/rcon-cli.env`→`/data/.rcon-cli.env`と`/run/wishicraft/rcon-cli.yaml`→`/data/.rcon-cli.yaml`のexact 2 bindをRWで許可する。一般的なRCON/RW mount例外、wildcard、任意source/destinationへ拡張しない。
- **Filesystem contract:** Host sourceはruntime UID/GID所有、0600、regular/non-symlinkのephemeral `/run` fileとする。Data EBS側はexact Game rootの2 pathだけをroot:root、0644、regular/non-symlink、size 0、nlink 1のDocker backing placeholderとして認識する。running時はcanonical Compose project/serviceとexact source/destination/RO-RW/type/重複なしをDocker inspectで証明する。stopped時も同じzero-size placeholderはknown managed artifactとして許容し、non-zeroはsecurity/correctness failureへfail closedする。
- **Purity:** filesystem preflightはread-only validationであり、running中のnested bind destinationをrm/unlink/truncate/replaceしない。`stop-v1`はread-only guards、RCON availability、固定`save-all flush`、systemd graceful stop、stopped verificationだけを担う。prepare/cleanup責務をSTOP critical pathへ混在させない。
- **Recovery evidence:** running STOP recoveryは、(1) systemd外typed STOPのpreflight env不足、(2) readonly `COMPOSE_FILE` collision、(3) live nested-bind backing placeholder削除によるRCON authentication loss、の3回をいずれもexplicit save前にfail closedした。共通原因はproduction runtime topology、とくにDocker nested bind lifecycleをrepository fixtureが十分モデル化していなかったことである。failed Operationsは履歴として保持し、第四hot-patchとSTOP retryは未承認である。
- **First production validation:** inactive-only full artifact upgradeとcanonical STARTは成功したが、STOP admission前のlive preflightでDocker label用Go templateのquote escaping bugを検出した。raw device/mount guard後、RCON/save前にfail closedし、verified maintenance stopでcontainer exit 0へ戻した。running-state replacementは行わず、正しいtemplate literalとproduction regression testをrepositoryへ追加し、次のinactive-only適用を新しい承認境界とする。
- **Final production validation:** 修正版をinactive-onlyで適用後、canonical STARTとlive preflightでraw device、mount guard、exact Docker nested binds、RCON authenticationを順にPASSした。canonical STOPはexplicit save、graceful runtime stop、EC2 stopped、DNS DELETE/INSYNC、fresh stopped Reconcile、terminal/owned cleanup、duplicate idempotencyまで成功した。password/CLI configをpublic port、SG、Git、SSM argumentへ露出せず、Data EBSにはstrict zero-size backing placeholder以外のpersistent configを許可しなかった。
- **関係:** D-075のcontainer-local client、`RCON_PASSWORD_FILE`、非公開RCON境界を変更しない。D-077のephemeral generated config方式をRO一律解釈からpassword RO / exact generated config RWへ精密化する。独自RCON clientや`mc-send-to-console`へ切り替えない。

### D-076 Host Runtimeはdata mount unitへ直接依存しactive Game metadataを固定artifactでrealizeする

- **状態:** Accepted（Phase 5 recovery）
- **日付:** 2026-08-29
- **Incident evidence:** 初回Phase 5 STARTはEC2、SSM、typed Host Runtime START、container、protocol READY、player count 0まで到達したが、Target上の旧Compose artifactにD-071のactive Game labelsがなく`active-game-unknown`でfail-closedした。DNS write前にterminal FAILEDとなり、Desired RUNNING revision 2を維持した。利用上限中のoperator `StopInstances`では`/srv/minecraft` unmountとHost Runtime ExecStopが並行し、mount guardが`FAIL:MOUNT_SOURCE`となったためgraceful shutdownは証明されていない。
- **Active Game realization:** canonical rendererが`com.wishicraft.active-game-id=game-vanilla-main`と宣言data sourceをcontainerへ付与する。probeはD-071どおりexplicit labelsと一意な`/data` bindだけを比較し、directory名からGame identityを導出しない。
- **Mount ordering:** Host Runtime unitは独自mount guard serviceへの`Requires`/`After`に加え`RequiresMountsFor=/srv/minecraft`を持つ。systemdが対応するmount unitへの`Requires`/`After`を生成し、startではmount後、stopでは逆順によりHost Runtime ExecStop完了後にunmountを開始させる。boot enableなし、`Restart=no`、Compose `restart: "no"`を維持する。
- **Upgrade:** Target適用は引数なしの固定repository artifactだけを使用する。既知のpredecessor/target SHA-256、regular/non-symlink、root owner、modeを検証し、同一directoryのtemporary fileからatomic renameする。未知artifact、runtime active、container/listener存在時は変更前に停止する。secret、environment dump、任意path/payloadを受け付けない。
- **Desired retry:** STARTはDesired RUNNINGへの収束operationである。同一GameのDesiredが既にRUNNINGならrevisionを増やさず、fresh actual observationからEC2/SSM/runtime/endpoint convergenceを再開する。以前のOperationがterminalでLock/Current Operationがなければ新しいAdmissionを許可し、raw state repairは行わない。
- **Dev validation:** approved predecessorからのatomic upgrade後、実生成dependencyに`Requires/After=srv-minecraft.mount`を確認した。controlled poweroffではHost Runtime stop完了後にmount unmountが始まり、Minecraft全dimension保存、container exit 0、OOM false、restart 0を確認した。Desired RUNNING revision 2からrevisionを増やさないSTART convergenceは243.059秒でSUCCEEDEDし、active Game、DNS/endpoint、idempotency retryも一致した。

### D-074 Phase 4 Lock ownership、Desired CAS、stale recovery契約

- **状態:** Accepted（human review）
- **日付:** 2026-08-29
- **Lock identity:** `operation_id`をlogical ownerとし、各acquisitionで一意な`lease_id`を発行する。Lockはresource/system identity、`owner_operation_id`、`lease_id`、`lease_expires_at`を保持し、renew、release、protected side effect直前の確認はoperation/lease一致と未期限切れを要求する。同一Operationの二重executorや期限切れ後の古いexecutorをcurrent ownerとみなさない。
- **Desired CAS:** Desiredは`desired_revision`、Observedは`observed_at`、Operation ownershipは`current_operation_id`で独立して保護する。Desired mutationはexpected revision NのCASでN+1へ進め、必要なoperationではCurrent Operation条件もtransactionへ含める。ReconcileはDesiredを上書きしない。将来の`rendered_revision`、`applied_revision`との接続を維持する。
- **Stale recovery:** Lock expiryはOperation failureではない。deadline/lease超過はstale candidateとして新しい競合admissionをblockし、fresh Reconcile後の明示recoveryが旧Operationのterminal化とowned Current Operation/Lock cleanupを一transactionで行う。実状態を観測せず単純FAILED化せず、Phase 4 MVPの通常admissionへauto-recoveryを入れない。副作用前と安全と証明できる限定caseの将来自動化は別Decisionとする。
- **Values/retention:** lease 900秒・renew 120秒はAcceptedとする。Phase 5 START 243.059秒/5回renew、Phase 6 closeout START 243.499秒、STOP 93.353秒/6回renewを実測し、STOPの最長poll gap約30秒に対してrenew後marginは少なくとも約870秒だった。Operation/Idempotency TTLはDeferredのままとする。
- **Dev integration:** 2026-08-29にControl Plane stackだけへ4 tablesとAdmission Lambdaをdeployした。条件付きGame登録、atomic admission、idempotency、競合/STATUS、operation/lease一致、wrong lease拒否、renew/owned release、Desired revision CAS、fresh Reconcileを必須とするstale recoveryを実DynamoDBで確認した。integration後はLock 0件、Current Operationなし、識別可能なOperation/Idempotency履歴だけを保持する。Admission IAMは対象5 tableの`ConditionCheckItem`、`GetItem`、`PutItem`、`TransactWriteItems`、`UpdateItem`とLambda loggingに限定し、runtime/AWS lifecycle mutation権限を持たない。

### D-073 Phase 4前はGame desired stateとGit管理runtime lockを分離する

- **状態:** Accepted（既存D-059〜D-062の整合明文化）
- **日付:** 2026-08-28
- **Game schema:** Gameはidentity、lifecycle/materialization、Package参照、論理`runtime.class`、Game単位policyを持つ。host Java、itzg image、Docker/Compose/AL2023、container/JVM memory等のphysical runtime artifactをGame itemへ複製しない。
- **Source of Truth:** Phase 4初期単一GameではMinecraft VERSION/TYPE、Java variant、itzg image、memory、platform lockを`config/stages/dev.yaml.host_runtime`のGit管理値が所有する。Phase 9以降にPackageを導入した後は、Gameの不変Package参照が論理Minecraft構成を所有し、runtime class mappingがGit lockへrealizeする。同じkeyをGameとGitへ二重に保存しない。
- **Phase 1 history:** `compute`、Corretto 25、直接`minecraft.service`、Xms 1G/Xmx 3G、server.jar checksumはPhase 1 as-builtとして残すが、Target/Game current contractではない。
- **Phase 3 completion fix:** probe v1.3.0は既存mc-monitor responseからonline player countの非負整数だけを追加で正規化する。0とunknown/not-applicableを区別し、sample/name/UUID/MOTD/raw responseを保存せず、READY条件へ加えない。
- **Scope:** repository contract/docs/testsの整合だけを行い、Games table、Operation/Lock、AWS deployまたは実機validationを開始しない。

### D-072 Phase 3 Reconcileは独立Control Plane stackでcurrent SystemStateを単調更新する

- **状態:** Accepted
- **日付:** 2026-08-28
- **Architecture:** 独立`WishicraftControlPlaneStack-dev`にon-demand DynamoDB、薄いReconcile Lambda、read-mostly IAM、14日LogGroupだけを置く。Phase 1/Target stackへcross-stack exportや変更を追加しない。
- **Target identity:** Project/Stage/Purpose tagでexactly oneのnon-terminated Targetを解決し、0/duplicate/schema/API failureはUNKNOWNとして保存する。physical instance IDをGitへ追加しない。
- **Observation:** EC2/SSM/固定Host Runtime probeの既存short-circuitを維持し、public/private IPv4とcanonical Route 53 A recordをread-only観測する。stopped + public IPv4 absent + DNS absentは正常である。
- **Persistence:** `system_id`一件のcurrent SystemStateをUpdateItemし、fixed-width UTC `observed_at`のstrictly-newer conditional writeで古い結果と同一timestampを拒否する。観測failureもfresh UNKNOWN/ready false/error classificationとして保存し、過去READYを残さない。DynamoDB failureは成功へ変換しない。
- **IAM:** EC2/SSM/Route 53 read、固定probe実行、特定table GetItem/UpdateItem、Lambda logだけを許可し、lifecycle/EBS/SG/DNS/secret/IAM mutationを禁止する。
- **Scope:** periodic reconcile、start/stop workflow、DynamoDB history/Streams/TTL/GSI、Discord/API、DNS writeは含めない。
- **Dev deployment:** 2026-08-28にTarget diff 0、Control Planeが新規DynamoDB/LogGroup/IAM/Lambdaだけであることを確認し、`WishicraftControlPlaneStack-dev`だけをdeployした。Phase 1のAMI/UserData/旧attachment既知Frozen差分はdeployしていない。
- **Dev integration:** stopped Targetを2回Reconcileし、public IPv4/DNS absent、SSM/protocol/active game not-applicable、Host Runtime not-running、runtime ready false、discrepancy/errorなし、health HEALTHYをcurrent item一件へ保存した。2回目は新しい`observed_at`で同じitemを更新し、Target向けSSM command metadataは前後不変でSendCommand 0だった。strictly-newer条件はrepositoryのolder/equal rejection testで検証し、synthetic production observationやschema外AWS CLI writeは行っていない。

### D-071 Phase 3 active gameはHost Runtime明示metadataと実bindから観測する

- **状態:** Accepted
- **日付:** 2026-08-28
- **Source of Truth:** Control Plane期待値はGit管理の初期Game ID（将来はvalidated desired Game ID）とし、Host Runtimeがrealizeした現在値はrendererがCompose containerへ付与する明示Game ID/data source labelを正本とする。directory名、Compose project/container名、Minecraft内部fileからGame IDを逆算しない。
- **Observation:** probe v1.2.0はrunning containerだけでlogical Game IDを返し、宣言data sourceとDocker inspectの一意なbind `/data` sourceを比較する。container非runningはnot-applicable、metadata missing/malformed/ambiguousはunknown、bind不一致はruntime-state-mismatchへfail-closedする。probeはread-onlyを維持する。
- **Discrepancy:** expected/observed差は`active-game-mismatch`、running中の観測不能は`active-game-unknown`、metadata/bind矛盾は`runtime-state-mismatch`とする。EC2/container停止時はactive game discrepancyを生成しない。
- **READY boundary:** `TargetStatus.ready`はMinecraft protocol runtime READYのままとし、active game mismatchでもtrueを保持できる。START-005のoperation成功は上位Workflowがruntime READY、active game一致、後続endpoint/DNS一致を合わせて判定する。
- **Scope:** 本Decisionはrepository契約とtestだけを更新し、AWS、Host Runtime apply、Minecraft lifecycle、Reconcile、DynamoDB、Lambda、Route 53を実行・実装しない。

### D-070 Phase 3 runtime READYはcontainer-local Java protocol ping成功を必須とする

- **状態:** Accepted
- **日付:** 2026-08-27
- **Decision:** 一意に解決したrunning container内の固定`mc-monitor status --json --host localhost --port 25565 --timeout 3s`だけをHost Runtime read-only probeから実行する。host/port/timeout/commandをControl Plane inputにせず、Minecraft portのhost publish、SG ingress、DNS、RCONを必要としない。
- **Normalization:** container非runningはprotocol not-applicable、nonzeroはnot-ready、timeout/実行不能/malformed responseはunknownとし、すべてready falseとする。protocol success時も期待version token `26.2`が一致しなければnot-readyとする。
- **Data minimization:** raw JSON、MOTD、favicon、player sample/name/UUIDを伝播せず、attempt/result、互換応答有無、reported version、protocol version、online player count整数、version match、protocol observed_atだけをversioned probe JSONへ正規化する。player countは0とunknown/not-applicableを区別し、READY条件にしない。
- **READY boundary:** protocol success/version一致に加え、mount expected、Docker active、Host Runtime active、container running、component errorなしの場合だけPhase 3 runtime `TargetStatus.ready=true`とする。START-005のoperation成功には後続sliceのactive gameとconnection endpoint/DNS一致も必要であり、本sliceだけでstart workflow完成とはしない。
- **Safety:** protocol status pingはread-onlyとし、RCON、Minecraft command、properties/world/log read、container/network mutationを禁止する。
- **Fixed image validation:** 固定digest imageのmc-monitorは0.16.11で、`status`のjson/host/port/timeout flagsを確認した。Go flagのhelpはusageを出力してexit 2となるため、CIはhelp本文の必須flagとexit 0または2を組み合わせてcontractを検証する。
- **Dev observation:** Target/SSM起動後、Host Runtime停止中はprotocol not-applicable / ready falseだった。canonical unit起動直後にcontainer running / protocol not-ready / ready falseを実測し、その後reported version 26.2 / protocol 776のcontainer-local responseでready trueへ遷移した。Docker health healthyだけでREADYにならないnegative evidenceを実機でも確認した。
- **Graceful closeout:** canonical unit停止でoverworld/the_end/the_netherのsaveと`All dimensions are saved`、container exit 0、OOMKilled false、RestartCount 0、listener/process不在を確認した。EC2 running中のpost-stopはprotocol not-applicable / ready falseへ戻り、Target停止後statusはRun Commandを送信しなかった。終了時は両EC2 stopped、data EBS attachment/snapshot/SG/DNS/stacks不変である。

### D-069 Phase 3 Host Runtime observationは固定read-only probeとstrict parserに分離する

- **状態:** Accepted
- **日付:** 2026-08-27
- **Decision:** SSM online時だけ、引数なしのrepository-packaged probeを固定Run Command operationで実行する。probeはIMDSv2 identity、期待mount、systemd、Docker daemon、Compose labelで一意に識別したcontainerだけをhost-localに観測する。SSM transport、probe JSON schema v1 parser、status normalizationを分離する。
- **Safety:** Control Planeが任意shellを渡すinterface、Minecraft内部file/world、environment/log、RCON、secretの観測、probeによるrepair/lifecycle/filesystem/Docker mutationを禁止する。transport/schema/identity/command failureはHost Runtime以下を`unknown`へfail-closedする。
- **READY:** container runningやDocker healthだけではREADYにしない。v1.0.xで`ready=false`へ固定していた契約は、D-070のprotocol-aware probe v1.1.0で拡張する。
- **Timeout:** stage正本のstatus用`ssm_probe=60`秒を使い、script executionは45秒とする。start/stop用Host Runtime timeoutを流用しない。
- **Runtime compatibility:** SSMで転送するprobeはControl Plane packageのPython targetではなくTarget AMIの標準interpreterでも実行可能でなければならない。v1.0.0の初回実機試行はAL2023のPython 3.9に`datetime.UTC`がなくcommand failureとなったため成功扱いせず、Python 3.9 syntax/API compatibility testを追加したv1.0.1で修正した。protocol contractはD-070のv1.1.0、active game contractはD-071のv1.2.0、player count最小補完はD-073のv1.3.0である。
- **Dev observation:** repository validationとCI成功後、Targetを一時起動してSSM Onlineを確認した。固定probe v1.0.1はexit 0、schema v1、stderr空で、expected XFS/UUID mount、Docker active、Host Runtime inactive、固定digestのcontainer stopped、restart policy no、OOMKilled false、RestartCount 0、Minecraft not-running、protocol not-applicable、ready falseを返した。status経路も同じcanonical stateへ正規化した。
- **No mutation / closeout:** 直接probeとstatus経路の前後で、`observed_at`以外のprobe事実、mount root metadata、EBS attachment、Target SGに変化はなかった。container/Host Runtime停止を確認してTarget EC2を通常停止し、停止後status経路がRun Commandを送らずEC2 stopped / SSM not-applicable / Host Runtime not-running / ready falseを返すことを確認した。Phase 1/Target stacks、data EBS、snapshot、ingress、DNSは変更していない。

### D-063 Phase 2 target hostを独立stackで作成する

- **状態:** Accepted
- **日付:** 2026-08-23
- **Decision:** Phase 1 rollback hostをCloudFormation replacementから隔離するため、Phase 2 target hostは`MinecraftTargetStack-dev`として作成する。CDK assemblyは`deployment=target`でtarget stackだけを含め、`MinecraftStack-dev`と同時deployできない構造にする。
- **Target:** 既存dev VPC `vpc-0c3cca1e65696ed8e`のap-northeast-1a public subnet `subnet-0a70e5682ea8d0bd3`へ、固定AMIの`t3a.medium`、暗号化gp3 16 GiB root、public IPv4、ingress 0の専用SG、`AmazonSSMManagedInstanceCore`だけを持つ専用role/profileを作る。boot UserDataは持たない。
- **Data boundary:** target stackはdata EBS、volume ID、`AWS::EC2::Volume`、`AWS::EC2::VolumeAttachment`、`/dev/sdf`、data mount path、secret、DNSを参照しない。実data migration前はroot EBS上のsynthetic dataだけを使用する。
- **Deploy gate:** repository validation、CI、Phase 1既知差分以外の追加差分なし、targetが新規resourceだけ、SG ingress 0、secret/data権限なしを確認後、stack名を明示してtargetだけをdeployする。Phase 1はstopped/frozenのrollback先として維持する。
- **Observed package lock:** target host installは固定AL2023 repositoryの`docker-25.0.16-1.amzn2023.0.3.x86_64`以外なら変更前停止する。Composeとitzg/Minecraft lockはD-062を維持する。
- **停止境界:** target hostのplatform、993:993 identity、Docker/Compose/image、synthetic setup/READY/memory/lifecycle/graceful stopを検証してtarget EC2を停止した後、実data EBS migration直前で停止する。

### D-062 Phase 2 target platform lock finalization

- **状態:** Accepted
- **日付:** 2026-08-23
- **比較:** AL2023 `2023.12.20260724`維持と`2023.12.20260803`更新を比較した。旧releaseを必要とするHost Runtime互換性またはrollback理由はなく、`20260803`はOpenSSH、OpenSSL、kernel等の後続security/maintenance updateを含み、release固定による再現性も維持できるため更新する。
- **Kernel:** 6.1、6.12、6.18を比較し、AWSが2026-08-17からdefaultとし現在推奨するkernel 6.18を採用する。WishicraftはFIPS validated kernelを要件とせず、Docker/Compose、XFS、bind mount、systemd、itzgに6.1固有依存がない。AL2023は3 variantへ同じuserspace packageと互換性を提供し、6.18を最新security/maintenance経路とする。target host実動作はmigration gateで検証する。
- **AMI lock:** ap-northeast-1のAmazon公式public x86_64 AMI `al2023-ami-2023.12.20260803.3-kernel-6.18-x86_64` / `ami-0b4d2909a55ed2c78` / owner `137112412989` / creation `2026-08-03T17:39:23.000Z`を固定する。release、kernel、name、ID、architecture、owner、creation dateの整合をrepository validation対象にする。
- **Docker observation:** 固定releaseのAL2023標準repositoryは`docker` `25.0.16-1.amzn2023.0.3`をx86_64へ提供する。既知のmulti-network regressionが記録された`.0.1`ではなく後続buildであり、現行Host Runtimeは単一Compose networkを使う。RPM versionを独立した恒久設定正本にはせず、このDecisionと公式referenceに観測値を記録し、実機install時は導入NEVRAをartifactへ記録して一致を確認する。
- **維持lock:** Compose `v5.4.0` + SHA-256 `837fd1d35bf6a494f41b5b5988269a7be79de337cf1a1a6ff0e45ab51bb4e9be`、itzg `2026.7.2-java25@sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77`、Minecraft `VERSION=26.2` / `TYPE=VANILLA`を変更しない。
- **対象外:** 本DecisionはEC2作成、deploy、Docker/Compose install、image pull/run、EBSまたはPhase 1 runtimeへの操作を承認しない。

### D-061 Phase 2b-1 server.properties ownership migrationと安全側memory初期値

- **状態:** Accepted（一部はProvisional / Deferred）
- **日付:** 2026-08-22
- **観測:** 既存game directoryはnumeric `993:993`、通常fileの大半も`993:993`だが、`server.properties`だけが`0:993` / `0640`だった。extended ACL、symlink、special fileは存在しない。固定itzg release `2026.7.2`はroot entrypointから`gosu`でUID/GID 993へdropした後にmc-image-helper 1.62.1でpropertiesを更新するため、既存`0:993` / `0640`は読めても変更時にpermission errorとなる。
- **Decision:** Phase 1 Minecraft完全停止後、一回限りのHost Runtime Linux ownership migrationとして`server.properties`一件だけを`0:993` / `0640`から`993:993` / `0640`へ変更する。regular file、non-symlink、expected owner/mode完全一致、extended ACLなしをpreconditionとし、contentを変更せず、recursive chownを禁止し、postflightでowner/modeを再確認する。以後のMinecraft内部形式realizationはitzgへ委譲する。
- **Rollback:** Phase 2停止、process/listener消滅、mount identity正常を確認した後、contentを変更せず`server.properties`一件を`0:993` / `0640`へ戻せることをrollback契約とする。Phase 1 artifactは新経路の同等性確認までdisable/removeしない。
- **Provisional memory:** Phase 2b dev最小Vanillaのcurrent targetをcontainer `2816 MiB`、Xms `1G`、Xmx `2G`とする。D-060の`3 GiB` / `2304M`初期案を置き換えるが、恒久的architecture invariantではない。target host上のDocker/itzg起動peak、native memory、OOM event、save/stopを実測して再評価する。
- **Validation:** 実data適用前に、固定tag+digest、linux/amd64、synthetic fixtureだけを使うCI integration testを必須とする。`0:993` / `0640`のpermission failure、`993:993` / `0640`での更新、inode/mode/ACL、`SKIP_CHOWN_DATA=true` sentinel、同一input restart、RCON disabled時のsecret artifact不存在を検証する。
- **Deferred:** `RCON_PASSWORD_FILE`、`UMASK=0077`、`.rcon-cli.env`、`.rcon-cli.yaml`のsecurity integrationはRCON command path導入前に決定・検証し、Phase 2b最小起動のblockerにしない。
- **Resolved:** Phase 2 target platform lock reviewはD-062で完了した。Phase 1 as-built `2023.12.20260803.3` / kernel 6.1の履歴は変更しない。

### D-060 Phase 2a Host Runtime static contract

- **状態:** Accepted（一部の値はProvisional / Observation Required）
- **日付:** 2026-08-22
- **決定:** Phase 1 runtimeをrollback先として維持したまま、Phase 2aでitzg向けHost Runtimeのplatform lock、Docker/Compose installer、filesystem preflight、Compose/systemd lifecycle、secret-free canonical rendererをrepository内に構築する。AWS/EC2への適用、Docker install、image pull、container起動、既存world変更は別作業とする。
- **Accepted:** itzgはJava 25のrelease tag + digest、Minecraft `VERSION=26.2`、既存data EBSの観測済みnumeric UID/GIDを使用、recursive chown禁止、`SKIP_CHOWN_DATA=true`、`restart: "no"`、Host Runtimeだけがcontainer lifecycleを実行する。管理portをpublishせず、boot-time / restart-required / runtime operationを分離する。
- **Desired/applied:** Control Planeが妥当な要求を受理した時点でdesired revisionを進める。render成功後だけrendered revision/digest、runtime反映を実測した後だけapplied revisionを進める。Phase 2aはcanonical renderとnon-secret digestまでとし、revision永続化は後続Phaseへ送る。
- **Provisional:** dev初期値はcontainer 3 GiB、Xms 1G、Xmx 2304M。停止budgetはexplicit save 60秒、itzg 120秒、Compose 150秒、systemd 180秒、Host wrapper 300秒、SSM 360秒、Control Plane 420秒。恒久的architecture invariantではなくdev実測後に再評価する。
- **Platform lock:** AL2023 release/AMI、architecture、Compose version/checksum、itzg tag/digestをGitで固定する。Docker Engineは固定AL2023 releaseの標準repositoryから導入し、NEVRAを独立した設定正本にせず、実際の導入結果を検証・記録する。
- **Observation Required:** dev既存EBSのUID/GID、ACL/owner/file type、導入Docker NEVRA、dev停止時間・memory/OOM余裕。ap-northeast-1のrelease-specific AMI lockはD-062で解消した。未知値は推測せずhost適用前に停止する。
- **Deferred:** RCON command path/client、secret injection、whitelist runtime apply、desired/rendered/applied永続schema、backup、Mod/Plugin/Modpack、旧runtime退役順序。
- **移行境界:** Phase 1 `minecraft.service`がactiveならCompose start前にfail-closedする。新unitをboot enableせず、自動restartしない。新経路のdev同等性とrollback検証前にPhase 1 artifactをdisable/removeしない。
- **公式根拠:** `docs/11_external_constraints_and_references.md`のHost Runtime節。

### D-059 Phase 1後のMinecraft Runtimeにitzgを採用する

- **状態:** Accepted
- **日付:** 2026-08-22
- **背景:** Phase 1はhost Java、固定server.jar、直接`minecraft.service`、独自whitelist配置・修復、host firewallによるRCON制限で正式完了した。Phase 2開始前に、独自Minecraft Runtimeを継続するか、成熟したruntimeへ委譲するかを見直した。
- **決定:** Phase 1の実装と検証記録はas-built履歴として維持し、Phase 2以降のtarget architectureはControl Plane（Wishicraft）、Host Runtime、Minecraft Runtime（itzg/docker-minecraft-server）の3層とする。詳細な責務、migration inventory、安全原則は`docs/architecture/itzg-responsibility-boundary.md`を正本とする。
- **責務:** Wishicraftはユーザー操作、認可、状態遷移、AWS resource、desired state、運用policy、desired stateからitzg入力へのmapping/apply orchestrationを持つ。Host RuntimeはAL2023、EBS mount、Docker/Compose、systemd、secret injection、container lifecycle、host-local command pathを持つ。itzgはJava、distribution、Minecraft固有設定、whitelist/ops形式、RCON/runtime command、process、graceful shutdownを持つ。
- **安全条件:** boot-time configurationとrunning server operationを分離する。RCON等の管理portはhost / Internetへpublishしない。command pathはSSM等からhost-local / container-localに閉じる。EULA同意はoperator policy/gateとして残す。systemd、Docker/Compose、itzg間のlifecycle ownerを一意にし、Control Planeの停止意図とrestart policyを競合させない。
- **設定所有権:** deploy/基盤固定値はGit、運用中desired stateはControl Plane store、secretはAWS secret store、Minecraft実ファイルはdata EBS上のrealization結果とし、同じ値をGitとDynamoDB等で二重に正本化しない。
- **移行:** VPC/SG、IAM/SSM、data EBS/Retain、XFS/UUID mount guard、Discord認可/desired state、Step Functions/DynamoDBは維持する。直接Minecraft systemdとRCON firewallは再設計・置換する。host Corretto、独自server.jar downloader、whitelist artifact独自配置・修復は、新経路で代替確認後の退役候補とする。sunk costを維持理由にしない。
- **対象外:** 本DecisionはDocker/itzg導入、既存runtime削除、AWS/EC2変更を承認しない。これらはPhase 2の個別作業とする。
- **関連文書:** `docs/03_architecture.md`、`docs/05_data_and_interface_contracts.md`、`docs/06_delivery_plan.md`、`docs/07_operations_security_and_cost.md`、`docs/12_initial_configuration.md`

### D-058 Minecraft profile UUIDの正本形式とwhitelist永続形式

- **状態:** Accepted
- **日付:** 2026-08-15
- Mojang公式profile APIで`NEWISHIN_`はUUID `e912ab95758e4b7fb32e292eda293104`と確認した。project設定はAPIと同じhyphenなし32桁lowercaseを正本とする。
- 第20回read-only診断（Command ID `d4143514-0ebf-4565-94b6-9045e84bdf33`）で、接続時profile UUIDは同じ値のhyphen付き表現だった一方、既設`whitelist.json`はhyphenなし表現であり、6回のwhitelist拒否を確認した。
- Minecraftの`whitelist.json`境界ではUUIDを`8-4-4-4-12`形式へ決定的に変換する。比較はhyphenを除去した32桁lowercaseで行い、値の不一致とserialization不一致を分ける。
- 稼働中hostの修復は、whitelist、environment、game setupが承認済みpredecessorのbytes・SHA-256・metadataへ完全一致する場合だけ、通常停止とlistener停止確認後にatomic更新する。world、properties、secret、firewallは変更しない。
- 第21回Run Commandは変更開始前の`FAIL:STATIC`で停止した。第22回read-only診断で全static predicateが正常と確認され、原因はtemporary file不存在時の`compgen` status 1が`verify_static`の戻り値へ漏れたshell制御不具合と確定した。正常時は明示的に0を返し、temporary file存在時だけ拒否する。
- 第26回は通常停止後の`FAIL:STOP_STATE`でartifact更新前停止した。第27回read-only診断でJava／listenerは0、MainPID 0、world／firewallは正常だが、SIGTERM終了をsystemdが`failed`／status 143として保持したことを確認した。停止完了判定は`inactive`または`failed`を許容する一方、MainPID、Java process、25565／25575／25585 listenerが全て0であることを必須とする。
- 第28回は3 artifactが全てapproved predecessorのままの既知停止状態を、旧`stopped_partial`分岐が受容せず`FAIL:RUNTIME`で変更前停止した。全predecessorに加え、systemd `failed`／`exit-code`／143、MainPID 0、Java／listener 0が完全一致する場合だけ`approved_failed_predecessor`として再開する。

### D-035 Minecraft初回起動のExecStartPreはprivileged read-only verifierに限定する

- 第16回Run Command（Command ID `59a9d587-fde1-4b41-b194-afe64d649ecf`）はartifact配置とenable後の`systemctl start`で停止し、Minecraft Java process、listener、world、logsは生成されなかった。
- 第17回read-only診断（Command ID `c1876839-66ca-4383-b1db-8a27f9c4c95b`）では、JVM起動前のExecStartPre control process status 1とauto-restart状態を確認した。秘密値の出力は0件だった。
- mount verifierはblock device metadataを読むため、systemdの`+` prefixでroot権限のread-only ExecStartPreとして実行する。game setupの`--verify`はmount guardを必ず`--verify`で呼び、通常のmount準備経路へ入らない。
- 既知の第16回部分適用だけは、Java process、listener、world、logsがないことを確認してauto-restartを停止し、正本hash・metadataの旧game setup／unitだけをatomic upgradeする。任意の不一致artifactはconflictとして停止する。

### D-001 新規実装として開始

- **状態:** Accepted
- 旧コード、旧AWS構成、旧データモデルの互換性を要件としない。
- 既存ワールド移行も初期計画へ含めない。

### D-002 サーバーレス制御面

- **状態:** Accepted
- API Gateway、Lambda、Step Functions、DynamoDB、EventBridgeを中心とする。
- 常駐コントローラーEC2を置かない。

### D-003 Minecraft EC2だけをオンデマンド起動

- **状態:** Accepted
- Minecraft本体のEC2だけを必要時に起動する。
- EC2停止中もEBS、Route 53 Hosted Zone、S3等の費用は残るため監視する。

### D-004 初回実用版は単一バニラGame

- **状態:** Accepted
- `/mc status`、`/mc start`、`/mc stop`だけを最初に完成させる。
- create、MOD、Paper、Webを先に作らない。

### D-005 PythonとAWS CDK v2

- **状態:** Accepted
- Backend、Lambda、CDK、EC2 control scriptsをPython中心にする。
- OS bootstrap等だけShellを許可する。

### D-006 Step Functions Standard

- **状態:** Accepted
- start/stop/backup/resetの長時間処理に使用する。
- Lambda内で待機ループし続けない。

### D-007 状態を複数軸へ分離

- **状態:** Accepted
- Desired、Observed infrastructure、Observed Minecraft、Operation、Healthを分ける。
- `WAITING_FOR_SSM`等をSystemの単一state enumへ入れない。

### D-008 DynamoDBは実状態の正本ではない

- **状態:** Accepted
- EC2 API、SSM、systemd/process、RCON、runtime情報から実測する。
- 保存値は最新観測スナップショットと要求状態。

### D-009 複数テーブル方式

- **状態:** Accepted
- 初期はSystemState、Games、Operations、Idempotency、Locksへ分ける。
- 単一テーブル設計の最適化を優先しない。

### D-010 条件付きリースロック

- **状態:** Accepted
- DynamoDB conditional writeで取得・延長・解放する。
- TTL物理削除をロック解放として使わない。

### D-011 SSM管理、SSH非公開

- **状態:** Accepted
- Session ManagerとRun Commandを使用する。
- VanillaにはRCON専用のbind address設定がないため、socketがwildcard bindし得ることを前提にする。Wishicraft専用host firewall tableでIPv4の`127.0.0.1`およびIPv6の`::1`以外へ宛てたRCON port通信を拒否し、Security GroupにもRCON ingressを設けない。「localhost限定」はsocket bindではなく実効的な到達性を意味する。

### D-012 LambdaをVPCへ接続しない

- **状態:** Accepted
- EC2操作はAWS APIとSSM経由。
- NAT Gatewayを初期構成へ作らない。

### D-013 root/data volume分離

- **状態:** Accepted
- OSと再配備可能コードをroot、Gameデータをdata EBSへ置く。

### D-014 初期CPUアーキテクチャ固定

- **状態:** Accepted
- 最初は1種類のCPUアーキテクチャだけを使用する。
- ARM/x86混在は後期に再評価する。

### D-015 Discord長時間処理

- **状態:** Accepted
- 期限内にDeferred Responseを返す。
- operation進捗はBot Tokenで公開メッセージを更新する。
- Interaction Tokenだけへ依存しない。

### D-016 start/stop前にReconcile

- **状態:** Accepted
- 保存状態だけで開始可否を判断しない。

### D-017 backupを拡張機能より先に実装

- **状態:** Accepted
- 複数Game、reset、MODより先にbackupと手動復元テストを完成させる。

### D-018 Package/Preset/Template/Gameを分離

- **状態:** Accepted
- 複数ゲームフェーズで導入する。
- Gameは具体的Package versionへ固定する。

### D-019 Package version不変

- **状態:** Accepted
- 同一versionを上書きしない。
- 内容変更時は新versionを作る。

### D-020 createとstartを分離

- **状態:** Accepted
- createはGameメタデータを作成し、EC2を起動しない。
- 初回start時にmaterializeする。

### D-021 WebはHTTP pollingから

- **状態:** Accepted
- Discord MVP後に管理Webを作る。
- 最初はHTTP snapshot/polling。
- WebSocketは必要性を確認してから追加する。

### D-022 OPはGame単位・UUID正本

- **状態:** Accepted
- 起動中は即時反映、停止中は次回起動時同期。
- Discord管理者権限を認可根拠とする。

### D-023 Chat bridgeはPackage能力

- **状態:** Accepted
- 専用MOD/PluginがあるPackageだけ対応する。
- 純バニラのlog解析は行わない。
- 障害をMinecraftコアから分離する。

### D-024 MODとPaperのハイブリッドを初期対象外

- **状態:** Accepted


### D-025 固定FQDNと動的パブリックIPv4

- **状態:** Accepted
- Elastic IPを初期構成へ含めない。
- Route 53の固定FQDNを共通接続先とし、EC2起動時に現在の動的パブリックIPv4へAレコードを更新する。
- EC2停止完了後はAレコードを削除する。
- Minecraftクライアント側は固定FQDNを一度登録すればよい。

### D-026 Operation admission transaction

- **状態:** Accepted
- 競合operationの受付時にIdempotency key予約、Operation作成、Lock取得、SystemState.current_operation_id設定をDynamoDB Transactionで一体として行う。
- Transaction失敗時は新しいOperationやStep Functions executionを作成しない。

### D-027 Discord進捗はBot通常メッセージ

- **状態:** Accepted
- Interactionへは期限内にDeferred Responseを返す。
- 受付後、Bot Tokenで操作チャンネルへ通常メッセージを作成し、そのmessage IDをOperationへ保存する。
- 長時間更新にInteraction Tokenを保存・依存しない。

### D-028 MVP静的ホワイトリスト

- **状態:** Accepted
- 公開Minecraftポートを使用するため、MVPから`online-mode`と静的ホワイトリストを有効にする。
- Discordからのホワイトリスト管理は後期機能のままとする。

### D-029 Data EBS保持とUUID mount

- **状態:** Accepted
- data EBSはEC2とは別リソースとして同一Availability Zoneへ配置し、暗号化・保持する。
- filesystem UUIDでmountし、mount未確認時はMinecraftや破壊的処理を実行しない。

### D-030 SystemState部分更新

- **状態:** Accepted
- Desired、Current Operation、Observed/Health、Last Errorを別repository操作で更新する。
- ReconcileはObserved属性群だけを更新し、SystemState全体のPutItem置換を行わない。

### D-031 RuntimeHeartbeat分離

- **状態:** Accepted
- Minecraft EC2のheartbeatは専用table/itemへ書き込み、SystemStateを直接更新させない。
- 自動停止前にはReconcileを再実行する。

### D-032 初回実用リリース前の最低限監視

- **状態:** Accepted
- Budgets、ログ保持、start/stop失敗、EC2長時間running、Desired STOPPED不一致、Desired RUNNING未達、Lock期限超過、Lambda error/throttleの通知をPhase 7のrelease gateへ含める。
- backup失敗、heartbeat stale、data volume使用率はPhase 8の機能導入時に追加する。

### D-033 初期は1 stack・dev deploy

- **状態:** Superseded by D-063 and D-072（Phase 0/1 as-built）
- stageごとに1つの`MinecraftStack`を使用し、constructで責務を分ける。
- 初期からFoundation/ControlPlane/Monitoringを別stackへ固定しない。
- Phase 0からdev/prodの設定schemaを扱い、`config/stages/prod.yaml`はplaceholderとしてGit管理する。
- Phase 0〜7のsynth/deployはdevを基本とし、prod AWSリソースは最初の実用リリース直前に作成する。
- prodの必須値が未確定の間はprod向けsynth/deployをvalidationで停止する。

### D-034 Python toolchain固定

- **状態:** Accepted
- Python 3.12、uv、Ruff、mypy、pytest、AWS CDK v2を使用する。

### D-035 Step Functions AWS SDK統合優先

- **状態:** Accepted
- EC2、SSM、DynamoDB、Route 53の単純API操作はStep Functions AWS SDK統合を優先する。
- Lambdaはdomain logic、Reconcile、admission transaction、Discord、複雑な正規化へ限定する。

### D-036 Scheduled backupで停止中EC2を起動しない

- **状態:** Accepted
- scheduled backupだけを目的に停止中EC2を毎日起動しない。
- 通常stop時、稼働中の整合save後、または明示操作でbackupを作り、変更のない停止中Gameはskipできる。

### D-037 Wishicraft naming and identifiers

- **状態:** Accepted
- 利用者向け名称を`Wishicraft`、Discord Bot表示名を`ゐしクラくん`とする。
- repository名を`wishicraft-server`、project slugを`wishicraft`、AWS resource prefixを`wc`とする。
- System IDを`wishicraft-main`、初期Game IDを`game-vanilla-main`、表示名を`Wishicraft Vanilla`とする。
- 初期Minecraft Javaプロフィール名を`NEWISHIN_`とする。

### D-038 初期runtimeとstorage class

- **状態:** Phase 1 as-built。Target runtime部分はD-059〜D-062、D-068によりSuperseded
- Regionは`ap-northeast-1`、CPU architectureは`x86_64`、初期instance typeは`t3a.medium`とする。
- Amazon Linux 2023、Corretto 25 headless、Xms `1G`、Xmx `3G`を初期値とする。
- root EBSはgp3 16 GiB、data EBSはgp3 30 GiB、暗号化・保持とする。
- devのAvailability Zoneは`ap-northeast-1a`、Minecraft versionは`26.2`として`config/stages/dev.yaml`へ確定した。Minecraft 26.2はJava 25を要求する。
- 公式server.jar URLとSHA-1は同stage設定へ固定し、`latest`追従を行わない。prodは設定確定までplaceholderを維持する。

### D-039 設定ファイルを具体値の正本とする

- **状態:** Accepted
- `config/project.yaml`をproject共通値、`config/stages/<stage>.yaml`をstage別値の正本とする。
- `docs/12_initial_configuration.md`で設定と秘密情報の扱いを定義する。
- `null`や`TO_BE_CONFIRMED`をCodexや実装が推測して埋めない。

### D-053 Data EBSのXFS初期化とfail-closed mount

- **状態:** Accepted
- data EBSはpartitionを作らずvolume全体をXFSとして使用する。filesystemがない空volumeだけを初回formatし、既存XFSは再利用する。
- XFS以外、partition table、その他のsignatureは消去・変換せず停止する。Nitro上の実deviceはEBS volume IDとNVMe serialの一致で特定する。
- `/etc/fstab`はUUIDと`defaults,nofail`を使う。mount準備serviceは実volume・UUID・XFSのmountを検証し、失敗時はfailedとする。将来のMinecraft、backup、resetはこのserviceとmount guardを必須依存にする。

### D-054 Phase 1初期vanilla Gameの固定artifactと起動基盤

- **状態:** Phase 1 as-built。Target runtime部分はD-059〜D-062、D-068によりSuperseded
- 初期PackageはMinecraft Java Edition 26.2 vanilla、初期Gameは`game-vanilla-main`とする。Corretto 25 headlessで実行し、公式version metadataのURL・SHA-1・sizeとリポジトリ固定SHA-256をすべて検証する。runtimeで`latest`やmanifestを参照しない。
- 初期Gameはdata EBS上へ配置し、`online-mode`、静的ホワイトリスト、EULA同意を必須にする。Minecraft Management Protocolは無効のままとする。RCONはSecureStringから設定し、Security Group ingressなしとhost firewallによる実効的localhost限定を必須にする。

### D-040 MVP secret store

- **状態:** Accepted
- MVPのDiscord Bot TokenとRCON passwordはParameter Store `SecureString`へ保存する。
- コードとCDKには実値ではなくParameter名だけを渡す。
- Secrets Managerは自動rotation等が必要になった場合に再評価する。

### D-041 Wishicraft固定FQDN

- **状態:** Accepted
- 取得済みドメインを`wishicraft.net`、Minecraft固定FQDNを`mc.wishicraft.net`とする。
- devのHosted Zone IDは`config/stages/dev.yaml`を正本とする。prodはprod設定が確定するまで`null`を維持する。
- `mc-dev.wishicraft.net`のAレコードはPhase 0では作成しない。Phase 1で起動中EC2の現在の動的パブリックIPv4へ更新し、停止後に削除する。
- 2026-08-22、`wishicraft.net`の登録者メール確認後にcontact reachability `DONE`、domain status `ACTIVE`、`clientHold`解除を確認した。Registered DomainとHosted Zoneの4 NS、`.net`親委任、Hosted Zone authoritative回答、public resolverの`mc-dev.wishicraft.net A 13.231.152.70`が一致し、未完了operationとDSがないためPhase 1のDNS公開試験は合格とする。Hosted Zone内のAレコードが`INSYNC`でも、TLD delegationと通常resolverの一致を引き続き別gateとして扱う。
- 同日のPhase 1検証では、第33回・第34回の正常保存証跡、第35回の再起動後host診断、およびクライアント目視により、停止前のworld変更がdata EBS上に保持されたことを確認した。data EBS／world永続化試験は合格とする。

### D-042 公開設定の正本と実行時配布

- **状態:** Accepted
- `config/project.yaml`と`config/stages/<stage>.yaml`を公開設定の正本とする。
- Parameter Store String、Lambda environment、CloudFormation outputはYAMLまたはdeploy結果から生成する実行時配布先であり、人間が独立して編集する第二の正本にしない。
- `config/secrets.example.yaml`にはSecureStringのParameter名だけを保存する。

### D-043 Idempotency専用table

- **状態:** Accepted
- 外部要求の`idempotency_key`を専用tableへ条件付き作成する。
- 競合operationのadmission transactionへIdempotency、Operation、Lock、Current Operationを含める。
- 同じkeyの再送では既存operationを返し、新しいoperation IDやworkflowを作成しない。

### D-044 Operation失敗後のDesired State

- **状態:** Accepted
- Desired State更新前の検証失敗ではDesiredを変更しない。
- Desired State更新後の失敗では利用者の要求を維持し、Observed、Health、Discrepancy、Last Errorで未達を表す。
- failure cleanupがDesired Stateを暗黙に元へ戻さない。

### D-045 Discord進捗は任意adapter

- **状態:** Accepted
- start/stop workflowはDiscord metadataがある場合だけ進捗メッセージを作成・更新する。
- Phase 5、6のCLI operationでは進捗処理をskipできる。
- Discordの失敗をMinecraft operation結果と分離する。

### D-046 STATUSは非ロックOperation

- **状態:** Accepted
- 利用者の明示的statusはOperationへ記録するが、グローバルLockとCurrent Operationを使用しない。
- 定期reconcileやworkflow内部probeはOperationを作成しない。

### D-047 Workflow外停止時のDNS cleanup

- **状態:** Accepted
- EC2がworkflow外で`stopped`または`terminated`となった場合、進行中start operationがないことを確認し、残存Aレコードを削除する。
- 解放済み動的IPv4を固定FQDNが指し続けないことを優先する。

### D-048 Backup完成前は試験運用

- **状態:** Accepted
- Phase 8の検証済みS3 backup完成まではPhase 7環境を試験運用とする。
- 初回利用前と重要変更前にdata EBS snapshot runbookを実行可能にする。

### D-049 Phase 0設定validation gate

- **状態:** Accepted
- 設定schema validationと、stage・Phase・処理ごとのrequired validationを分離する。
- Phase 0のdev空stack synthはenvironment-agnosticとし、AWS Account ID、Availability Zone、Minecraft port/version、Route 53 Hosted Zone IDを要求しない。
- prodのPhase 0 synthはplaceholderを読込可能とした上で、現在の`null`値を全てパス付きで表示して拒否する。
- このprod拒否はPhase 0の一時的な安全gateであり、全ての`null`を永続的な必須項目と定義しない。Phase 1以降はstage・処理・Phaseごとのrequired pathを明示する。

### D-050 dev AWS CLI profileと接続先照合

- **状態:** Accepted
- ローカル開発者はIAM Identity Centerの`wishicraft-dev` profileを認証取得だけに使用する。
- Account IDとRegionの正本は`config/stages/dev.yaml`とし、profile名やSSO roleをstage設定の必須項目にしない。
- AWS CLIおよびCDKの手動コマンドでは`--profile wishicraft-dev`を明示する。CDKアプリケーションコードへprofile名を埋め込まない。
- deploy前にSTS caller identityのAccount IDをstage設定のAccount IDと照合し、不一致なら処理を中止する。

### D-051 Phase 1 RCON secretとserver artifactの安全条件

- **状態:** Accepted
- RCON passwordは登録済みSecureStringをEC2 roleが実行時に取得する。実値をCDK、user data、CloudFormation、Git、ログへ含めない。
- EC2 roleの`ssm:GetParameter`は対象Parameterへ限定し、復号した値を標準出力へ出さない。RCONはlocalhost限定で、インターネット向け受信ルールを作成しない。
- Minecraft 26.2 server.jarは公式version manifestで確認したURLとSHA-1をstage設定へ固定し、取得後に検証する。EULA同意、artifact取得、初回起動は人間の明示承認前に実行しない。
- 初期GameのEULA同意は明示済みである。artifact取得と初回起動はdeploy後の手動確認として引き続き分離する。

### D-052 Minecraft EC2のinstance metadata保護

- **状態:** Accepted
- Minecraft EC2はIMDSv2を必須とし、instance metadata tagsを有効にしない。

### D-053 RCON firewallの部分適用再開

- **状態:** Accepted
- firewall migrationは、既存script、unit、drop-in、rules file、enable symlinkを個別に不在・正本一致・衝突へ分類する。正本一致物は書き換えず再利用し、不一致物は削除・修復・上書きせず、永続変更前に停止する。
- target nft tableまたはrules fileだけが残る状態は、D-056で定める正本検証と状態遷移を満たす場合に限り安全に再開する。正本性を証明できないpartial stateは従来どおり変更せず停止する。
- 初期bootstrapは新規instanceの作成経路であり、既存hostの再開は一回限りのmigrationを正本とする。bootstrap再実行を衝突解消手段にしない。

### D-054 RCON firewall dependency verificationとbootstrap既設物

- **状態:** Accepted
- firewall migrationは`systemctl show`の複数unit propertyを全体文字列や順序で比較しない。commandの取得失敗、空値、対象unit欠落を別checkpointでfail-closedし、完全なunit名のtoken membershipだけを確認する。
- `minecraft.service`が`not-found`の部分適用状態では、daemon-reload後に正本hash・metadataのdrop-inが存在することまでを確認して停止境界を越える。Minecraftを起動せず、unitが後から配置された際にsystemdがdrop-inを取り込む。
- bootstrap bundleは既設regular memberを無条件に上書きしない。absenceだけを排他的に配置し、正本content・mode・owner/groupの一致物はmtimeを含め無変更で受容し、不一致またはsymlinkは書込み前に停止する。
- EC2 user dataの16 KiB上限を維持するため、bootstrap runner自体はmtime=0の決定的gzipとBase64で輸送し、host上で復元して0700にする。allowlisted bundleのSHA-256検証と既設物判定は復元された同一runner内で従来どおり行う。

### D-055 systemd enable linkの正本判定

- **状態:** Accepted
- firewall migrationのenable linkは、`WantedBy=multi-user.target`に対応する正確な`.wants` pathにあるsymlinkだけを対象とする。
- systemdはunit fileへのlinkを絶対pathまたは相対pathで作成し得るため、`readlink`のraw文字列を固定値と比較しない。symlinkが非danglingであり、解決後targetが正確なcanonical unit fileと完全一致する場合だけ正本として受容する。
- wrong target、類似unit名、dangling link、regular file、directoryは衝突として変更前に停止する。link query失敗、`systemctl enable`失敗、enable成功後のpredicate不一致は別checkpointで記録する。
- 正本linkはraw target形式やmtimeを含め書き換えない。preflightからenable直前までの状態・形式変化はraceとして停止する。

### D-056 nftables 1.0.4互換とfirewall scriptの制御upgrade

- **状態:** Accepted
- **日付:** 2026-08-15
- Amazon Linux 2023のnftables 1.0.4をproduction下限とし、1.0.7で追加された`destroy` commandをrulesへ含めない。
- target tableの新規適用は、`create table`、`add chain`、IPv4/IPv6の`add rule`をtop-levelに並べた単一batchとする。`nft --check --file`、table不存在race check、transactionalな`nft --file`、JSON semantic live検証、persistent fileのatomic確定の順で行う。nftables 1.0.4でnested object定義がstatus 0のまま空tableだけを作る挙動を正本fixtureとして固定し、nested構文をproduction rulesへ使用しない。
- target tableとpersistent rulesは、双方不存在、rulesのみ正本、tableのみ正本、双方正本を安全な再開状態として扱う。正本でないfile/table、由来を証明できないtemporary fileは削除・flush・上書きせず停止する。
- v15が残した正確なempty target tableは、v15 script/hash/metadata、systemd failed status 39、package version、rules/temp不在、Minecraft/Java/RCON停止、およびJSON内の全object不存在が一致する場合だけ`approved_empty_v15_partial`とする。適用直前の同一fingerprint再検査後、`create chain`と2つの`add rule`だけの単一recovery transactionでforward migrationし、tableのdelete/flushは行わない。
- live tableの正本判定は`nft -j`をPython 3で構文解析し、table identity、chain metadata、2 ruleのport/address/verdict、重複、未知object/expressionを個別にfail-closedする。human-readable出力やexpression順序の文字列一致を正本判定に使わない。
- firewall scriptの更新は、現行正本または明示した直前正本だけを許可する。v15 predecessorはpath、regular/non-symlink、2589 bytes、固定SHA-256、root:root、0755、構文、およびrace時の再検査が全一致し、unit processが非稼働の場合だけ同一directory内の検証済みtemporary fileからatomic replaceする。任意の旧内容は受容しない。
- scriptはsecret-freeな安定step/failure markerと固有exit statusをjournalへ残す。password、Environment全体、credentialは出力しない。

### D-057 live target table存在時のpersistent rules postflight

- **状態:** Accepted
- **日付:** 2026-08-15
- persistent rulesは再起動後のtable不存在状態から構築する`create table` batchであるため、live canonical tableの存在中に同じfileを`nft --check --file`すると、正本でも既存table衝突として失敗する。
- runtime postflightではroot:root・0600・固定bytes・固定SHA-256を再検証し、live tableは別途JSON semantic verifierで完全検証する。`nft --check --file`はtable不存在時のservice適用経路で、実適用前に実行する。
- この変更はrules bytes、live firewall semantics、transaction、selection logicを変更せず、既に完成したv16状態を無変更で受容する。


## 3. 却下した案

### R-001 常駐小型EC2コントローラー

- **状態:** Rejected
- 実装は単純になるが、常時固定費が目的に対して大きい。

### R-002 Discordから先に作る

- **状態:** Rejected
- 不具合箇所がDiscord、Lambda、SSM、Minecraft間で切り分けにくくなる。
- EC2内部→status→workflow→Discordの順にする。

### R-003 Web管理画面から先に作る

- **状態:** Rejected
- コアの状態管理と起動停止が固まる前にUIを作ると手戻りが大きい。

### R-004 単一System State enum

- **状態:** Rejected
- 処理step、実状態、healthが混ざるため。

### R-005 DynamoDB TTLによるロック解放

- **状態:** Rejected
- TTL削除は期限直後を保証しない。

### R-006 Lambda内で起動完了まで待機

- **状態:** Rejected
- 長時間実行、再試行、可視性、費用、timeoutの面で不適切。

### R-007 Lambdaをprivate subnetへ置きNAT Gatewayを使用

- **状態:** Rejected
- 現在の要件ではSSMとAWS APIで十分で、固定費を増やす。

### R-008 `latest.log`解析による汎用チャット連携

- **状態:** Rejected
- サーバー種別ごとの差異と誤解析を増やす。

### R-009 create時にEC2を起動

- **状態:** Rejected
- 作成だけで費用と長時間operationが発生する。

### R-010 backupなしでresetを先行

- **状態:** Rejected
- データ損失リスクが高い。


### R-011 Elastic IPの常時保持

- **状態:** Rejected
- 固定IP自体が目的ではなく、Minecraftクライアントで接続先を入力し直さないことが目的である。
- 固定FQDNと起動時DNS更新で要件を満たし、停止中のpublic IPv4固定費を減らす。

## 4. Provisional decisions

### P-001 Backup保持期間

- Scheduled daily: 14日
- Manual/Pre-reset: 90日
- Pre-upgrade/delete: 180日
- Phase 8で実データ量と費用を確認して確定する。

### P-002 初期idle shutdown

- 30分を初期候補とする。
- 利用者のプレイ習慣を見て調整する。

### P-003 初期runtime class

- **状態:** Superseded by D-038
- 初期は1classのみとする方針を維持し、具体値はD-038で確定した。

### P-004 Secrets ManagerとSecureStringの分担

- **状態:** Superseded by D-040
- MVPの保存方式はParameter Store SecureStringへ確定した。

### D-055 dev RCON firewall migration完了

- **状態:** Accepted
- **日付:** 2026-08-15
- 第13回Run Command（`1b62638b-8d69-4f4f-8dfb-183496a62449`）で、RCON firewall migrationはcompletion marker 1件、full postflight成功で完了した。
- firewall script、unit、drop-in、enable link、persistent rules、およびlive `inet wishicraft_rcon` tableは正本である。Minecraftは起動せず、Java processとRCON listenerは存在しなかった。
- RCON firewallを再構築せず、この状態をMinecraft初回起動のpreconditionとして扱う。

### D-056 既設部分適用からのMinecraft初回起動migration

- **状態:** Accepted
- **日付:** 2026-08-15
- Run14 read-only診断で、data EBS、Corretto 25、固定26.2 server.jar、minecraft account、Game directory、EULA、properties、whitelistが存在し、Minecraft unit、world、logs、process、listenerは不存在と確認した。
- 初回起動は、artifactごとの不在・正本・承認済みpredecessor・衝突を変更前に分類する専用migrationで行う。未知world、symlink、metadata/hash drift、mount/firewall driftでは変更せず停止する。
- 固定jarはsize/SHA-1/SHA-256検証後だけatomic配置し、secret値を出力せずpropertiesを確定する。Minecraftは全起動前predicate合格後にsystemd経由でのみ起動する。
- 第15回Run Commandは変更開始前のfirewall classifier呼出しで停止した。原因はreadonly `RCON_PORT`へのtemporary assignmentであり、実機firewall driftではない。後継candidateは`env`経由で子processへ値を渡し、この誤配線を再現testで固定する。

### D-057 Phase 1手動基盤検証完了

- **状態:** Accepted
- **日付:** 2026-08-22
- 固定FQDNによるユーザー接続、停止・再起動後のworld永続化、DNS公開、RCON localhost制限、正常停止とdata EBS保持を実地確認し、CI run `32570087910`のsuccessを確認したためPhase 1を正式完了とする。
- 終了時は限定CLIで`mc-dev.wishicraft.net`のAレコードを削除して`INSYNC`を確認した。MinecraftはMainPID、Java/cgroup process、25565／25575／25585 listenerが0、mount guard・XFS rw mount・world・`level.dat`が正常であることを確認後、EC2を通常停止した。data EBSはattachmentと`DeleteOnTermination=false`を維持する。
- 現行unitでは意図的なSIGTERM停止がsystemd上で`failed / exit-code / 143`として残る。今回はprocess/listener消滅とdata EBS正常性を組み合わせて停止済みと判定したが、Phase 2の自動停止実装前に、起動wrapper、終了コード伝播、`SuccessExitStatus=143`の妥当性を比較し、意図的停止をsuccessとして表現する方法を決定する。

### D-064 Phase 2b real-data migration boundary

- **状態:** Accepted
- **日付:** 2026-08-23
- Phase 1 stackと停止済みEC2をrollback先として維持し、snapshot完了後に既存data EBSを独立target EC2へ通常detach/attachする。
- 既存XFSは固定volume/AZ/UUID/NVMe identityをmount前に照合し、filesystem作成・repair・force detachを許可しない。
- `server.properties`一件だけをprecondition付きで`0:993 / 0640`から`993:993 / 0640`へ移行する。inode、内容hash、modeを維持し、再帰的ownership変更を禁止する。
- real-world起動はportless、RCON無効、restartなしの固定Host Runtimeで2回のREADY・正常停止・永続性を確認する。初回起動後の失敗は自動rollbackせず、target停止・snapshot保持・attachment記録で停止する。
- 手動detach/attachによるPhase 1 VolumeAttachmentの一時driftは既知状態とし、この作業ではstack update/import/reconciliationを行わない。

### D-065 Phase 2b real-data migration validation完了

- **状態:** Accepted
- **日付:** 2026-08-23
- rollback anchor `snap-0b1d9536e9c476c0f`のcompleted後、data EBS `vol-03ac9f534326c345c`を停止済みPhase 1 EC2から停止済みtarget EC2へforceなしで移動した。XFS UUID、NVMe identity、30 GiB、partitionなしをmount前に確認した。
- `server.properties`一件を`0:993 / 0640`から`993:993 / 0640`へ変更し、ownership変更時のinode、size、mode、SHA-256維持を確認した。他entryのunknown owner、ACL、symlink、special fileは0だった。
- 固定itzg imageで既存worldを2回READYにし、同じworld inode、data EBS bind、Minecraft 26.2、Java 25、healthy、restart 0、OOMなしを確認した。2回ともformal Host Runtime stopは1秒、exit 0、全dimension保存、listener/process残存なしだった。
- 終了時はPhase 1 EC2とtarget EC2がstopped、data EBSはtargetへ`/dev/sdf`・DeleteOnTermination=falseでattached、snapshot保持、target SG ingress 0、DNS recordなしである。両CloudFormation stackは更新していない。
- Phase 1 stackのVolumeAttachment logical resourceと実attachmentには意図的な一時driftがある。次工程でtarget側のattachment ownership、Phase 1側resourceの扱い、rollback boundary、旧EC2退役順序を設計・reviewしてからreconciliationする。

### D-066 Target VolumeAttachmentのResource Import

- **状態:** Accepted
- **日付:** 2026-08-23
- `AWS::EC2::VolumeAttachment`はResource Import対応だがstack refactoring非対応であるため、手動でtargetへattach済みのattachmentを`MinecraftTargetStack-dev/TargetDataVolumeAttachment`へIMPORTする。import後のCloudFormation physical IDは`i-04fc0629dc4ea466e|vol-03ac9f534326c345c`である。
- resource schemaのprimary identifierは`VolumeId`と`InstanceId`である。import identifierは両方を明示し、Device `/dev/sdf`はtemplate propertyとして一致させる。
- target stackにはVolumeAttachment一件だけを追加し、`AWS::EC2::Volume`は追加しない。DeletionPolicy/UpdateReplacePolicyはRetainとし、通常deployによる新規attachを禁止する。
- data EBS volume本体はPhase 1 stackのRetain resourceとして維持する。Phase 1 stackとold logical attachment `MinecraftDataVolumeAttachmentE11BB55A`はFrozenかつknown driftのままにし、今回更新・削除しない。
- IMPORT change set `phase2-target-attachment-import-74d9e8f`はattachment一件の`Action=Import`だけを含むことを確認してexecuteし、Target Stackは`IMPORT_COMPLETE`となった。実attachment timeはmigration時のままで、物理detach/reattachは発生していない。
- import後の`TargetDataVolumeAttachment` driftは`IN_SYNC`、`cdk diff`は0である。stack全体のdriftはstopped EC2のpublic IPv4解放により`AssociatePublicIpAddress` actualがfalseとなる既知差分だけで、attachment、IAM/profile、SGはIN_SYNCである。

### D-067 Phase 1 retirementとData EBS ownership移管

- **状態:** Accepted（retirement executionはDeferred）
- **日付:** 2026-08-23
- `MinecraftStack-dev`は`CREATE_COMPLETE`で、termination protectionを有効化した。stack policyは未設定である。rollback window中はPhase 1 stackをFrozenのまま維持し、通常CDK deploy/update/deleteを禁止する。
- current resource schemaでは`AWS::EC2::Volume`は`FULLY_MUTABLE`、primary identifierは`VolumeId`であり、stack refactoringのunsupported resource一覧にも含まれない。一方、source templateではold `VolumeAttachment`とPhase 1 EC2 UserDataがVolumeを`Ref`している。VolumeだけのMOVEにはこれらのproperty変更が必要となり、configuration変更を許さないstack refactoringとして有効に成立しないため、refactor previewは作成しなかった。
- `AWS::EC2::VolumeAttachment`は`IMMUTABLE`で、primary identifierは`VolumeId + InstanceId`である。Cloud Controlのreadではold identifier `vol-03ac9f534326c345c|i-021eaa7f33ddaf0a6`はNotFound、current target identifier `vol-03ac9f534326c345c|i-04fc0629dc4ea466e`だけが実在した。ただしEC2 `DetachVolume` APIでは`InstanceId`がoptionalで、CloudFormation providerのdelete request mappingを一次情報から完全には証明できなかったため、stale old attachmentの通常deleteは採用しない。
- deployed Phase 1 templateを基準に、Phase 1 EC2の`ImageId`をcurrent physical AMI `ami-016923362cc95896d`へliteral固定し、old attachmentへ`DeletionPolicy: Retain`と`UpdateReplacePolicy: Retain`だけを追加する非実行change set `phase1-retirement-preflight-20260823-1`を作成した。previewの唯一のactionはold attachmentの`Modify`（replacement false、policy attributesのみ）で、EC2、root EBS、IAM、SG、Data EBSのactionは0だった。change setは一度もexecuteせず、同じdeployed templateから再作成可能なことを確認したためcloseout時に削除した。
- retirementはrollback window終了まで実行しない。将来の正本候補は、target runtimeの通常運用確認後に、(1) deployed-template based surgical updateでold attachmentへRetainを追加、(2) Retain済みold attachmentとData EBS Volumeをsource管理からremove、(3) physical Volumeをtarget stackへResource Import、(4) target側drift/diffとsnapshotを確認、(5) Phase 1 EC2/rootを退役、(6) Phase 1 stackを解体、の順とする。各updateはcurrent physical AMIとeffective UserDataを固定し、EC2 replacement/restart、attachment detach、Volume mutationが0でなければ実行しない。
- 人間reviewとrollback window終了までは、Target Stackがcurrent attachment、Phase 1 StackがRetain付きVolume本体を所有する現状を安全な暫定状態として維持する。Data EBS ownership、stale attachment、Phase 1 EC2/stackはretirement debtであり、実証済みPhase 2 Host Runtime／real-world migrationの技術的成立を覆すblockerではない。RCON、public 25565、DNS、Control Plane integrationも後続機能でありPhase 1 retirementの前提にしない。
- rollback snapshot `snap-0b1d9536e9c476c0f`は、Data EBS ownership移管、Phase 1 retirement、targetの通常運用確認がすべて完了し、別途削除承認が得られるまで保持する。stopped targetのpublic IPv4 releaseによるdriftはAWSの停止時address lifecycleに起因するknown benign observationであり、この差分だけを直すstack/EC2変更を行わない。

### D-068 Phase 2 technical migration closeout

- **状態:** Accepted
- **日付:** 2026-08-23
- Phase 2 targetは固定AL2023 `2023.12.20260803` / kernel 6.18 / x86_64 AMI、AL2023標準Docker `25.0.16`、Compose `5.4.0`、固定itzg `2026.7.2-java25@sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77`で実機検証を完了した。
- existing data EBS上のMinecraft 26.2 Vanilla worldを2回READYにし、同じworld/data EBSのrestart persistence、2回のgraceful shutdown、container exit 0、OOMKilled=false、restart 0を確認した。`server.properties`一件のownershipはcontent、inode、modeを維持して`993:993 / 0640`へ移行済みである。
- current physical attachmentは`TargetDataVolumeAttachment`としてTarget StackへResource Import済みで`IN_SYNC`、post-import target `cdk diff`は0である。closeout時はPhase 1 EC2とtarget EC2がともにstopped、snapshot `snap-0b1d9536e9c476c0f`はcompleted/retained、Phase 1 stackはtermination protection有効のFrozen rollback environmentである。
- Data EBS Volume本体のstack ownership移管、stale Phase 1 attachment logical resource、Phase 1 EC2/root退役、Phase 1 stack削除はDeferred retirement debtでありPhase 2 blockerではない。RCON、public 25565、DNS automation、Control Plane integrationも後続Phaseのscopeとする。

### D-075 write-side Host Runtime command pathとRCON境界

- **状態:** Accepted
- **日付:** 2026-08-29
- **背景:** Phase 5以降のControl PlaneはHost Runtimeへwrite-side operationを要求するが、任意shell/Minecraft command、独自RCON protocol実装、secret露出を導入してはならない。
- **決定:** Control Planeからはversioned・typed・allowlist済みoperationだけをSSMで呼ぶ。Phase 5 STARTは引数がexactly `START`のhost-local wrapperを固定commandで呼び、wrapperが`wishicraft-host-runtime.service`のsystemd startへ変換する。外部requestはinstance ID、path、shell、Minecraft commandを指定できない。STARTはRCONを使用しない。
- **RCON:** Minecraft管理commandが必要な後続Phaseでは、固定itzg image内のcontainer-local `rcon-cli`を利用し、Control Planeに独自RCON client/libraryを実装しない。secretはAWS managed sourceからHost Runtimeだけが取得し、`/run`等のephemeral fileへ最小permissionで置き、read-only bindと`RCON_PASSWORD_FILE`でitzgへ渡す。password本文をCompose environment、SSM argument、log、Gitへ置かず、RCON portをpublishせずSG ingressも追加しない。
- **影響:** Phase 5 repositoryはSTARTだけをallowlistし、SAVE/STOP/whitelist/sayを先行実装しない。RCON/secretの初回AWS適用は別の明示承認境界とする。
- **関連:** START-006、EC2-002、EC2-007、NFR-010、D-074、`docs/architecture/itzg-responsibility-boundary.md`。

### D-077 Phase 6 STOP専用workflowとephemeral RCON client config

- **状態:** Accepted（Phase 6 production validated）
- **日付:** 2026-08-29
- STARTとSTOPはfailure isolationとIAM最小化のため別Standard State Machine/Task Lambdaとする。Admission、Operation/Lock、Desired CAS、Reconcile contractは共有する。
- STOPは固定Host Runtime operation内でcontainer-local `rcon-cli save-all flush`を実行し、成功後だけsystemd graceful stopへ進む。systemd/itzgだけの暗黙saveをSTOP-001のexplicit save証跡へ読み替えない。
- `RCON_PASSWORD_FILE`のsourceはHost `/run/wishicraft/rcon-password`とする。itzgが`/data/.rcon-cli.env`と`.rcon-cli.yaml`へpasswordを派生保存するため、両pathもHost `/run/wishicraft`のephemeral filesでbindし、Data EBSにsecretを残さない。mount modeの精密契約はD-078を正本とし、passwordはRO、upstream生成configの固定2件だけをRWとする。
- Actual EC2 stoppedではruntimeを起動し直さず、Desired STOPPED、DNS absent、fresh Observedへ収束する。通常pathの順序はcanonical contractどおりruntime停止確認、EC2 stopped、DNS DELETE/INSYNCである。
- Target secret read IAM、artifact、secret作成、injection、実RCON commandの最初のproduction適用は明示承認境界を維持する。
- **Stopped-state dev evidence:** `Desired RUNNING` revision 2 / Actual stopped / stale DNSからcanonical STOP Admissionを実行し、Actual stopped short-circuitでDesired STOPPED revision 3、DNS DELETE/INSYNC、fresh stopped observation、HEALTHY、Operation SUCCEEDED、Lock/current operation解放へ収束した。実行時間は42.316秒で、Target向けSSM、EC2 Start/Stop、Host Runtime、RCON、secret readは0件だった。同一payload retryは同じOperationを`created=false`で返し、新規executionもside effectも作らなかった。これは通常running STOPのsave/graceful shutdownを実証するものではない。
- **Running STOP dev evidence:** D-078修正版でcanonical START後、container-local RCON authenticationとfixed `save-all flush`、graceful systemd stop、runtime stopped確認、EC2 stopped、DNS DELETE/INSYNC、fresh Reconcile、terminal successを93.353秒で完了した。同一payload retryはsame Operation、`created=false`、新規execution/Lock/Desired/save/EC2/DNS side effectなしだった。

## 5. Current blockers

Phase 0〜6は完了した。UID/GIDとownership compatibility、AL2023/AMI、Docker/Compose/itzg pin、initial memory、status/Reconcile/SystemState、Game/Operation/Idempotency/Lock、atomic admission、lease lifecycle、Desired CAS、stale recovery、START/STOP、D-078 RCON contractは解消済みであり、current blockerへ残さない。

### Phase 4 closeout時の分類（履歴）

| 項目 | 状態 | 現在の契約 / 未決定点 |
|---|---|---|
| conditional admission transaction | Accepted | D-026。Idempotency、Operation、Lock、Current Operationを一transactionで受付し、失敗時はworkflowを開始しない。 |
| concurrent conflict policy | Accepted | 有効Lockまたはnon-null Current Operationなら競合operationを新規作成せず拒否する。同一idempotency keyは既存Operationを返す。 |
| lock renewal semantics | Accepted | D-074。owner operation ID・lease ID・未期限切れを条件に延長し、失敗は`LOCK_LOST`。副作用直前に所有権を再確認する。 |
| lock lease/renew values | Accepted | D-074。dev設定はlease 900秒、renew 120秒。Phase 5/6 STARTとPhase 6 STOPの実測、renew後marginからAcceptedとした。 |
| Operation retention / TTL | Deferred | 初期Phase 4ではTTLを有効化せず履歴を保持する。監査期間と運用query確定後にretentionを決める。 |
| Idempotency retention / TTL | Deferred | 初期Phase 4ではTTLを有効化しない。外部再送期間・Operation retentionより短くしない。 |
| Lock owner identity | Accepted | D-074。`operation_id`はlogical owner、acquisitionごとの`lease_id`はcurrent possession proof。 |
| SystemState desired-state CAS/version | Accepted | D-074。Desired=`desired_revision`、Observed=`observed_at`、Operation=`current_operation_id`へ分離する。 |
| operation timeout / stale operation | Accepted | D-074。通常admissionはblockし、fresh Reconcile後の明示recoveryでだけterminal化とowned cleanupを行う。 |

#### Phase 4 human reviewで解決した選択肢（履歴）

1. **Lock owner identity（Locks repository実装前）**
   - 単一`operation_id`案と別attempt token案を比較した。human reviewはlogical ownerを`operation_id`、current possession proofをacquisition固有`lease_id`とする組合せを採用した。
2. **SystemState desired-state CAS（SystemState write-side実装前）**
   - A: item全体の`version`を全更新で共有する。単純だが、ReconcileのObserved更新とDesired/Current Operation更新が不要に競合する。
   - B: `desired_revision`をDesired更新のCASに使い、Current Operationはnull/owner条件、Observedは既存`observed_at`条件として属性群ごとに分離する。推奨。D-030の部分更新境界を維持できるが、repository methodごとに条件式が異なる。
3. **stale Operation回復（Operations repository/admission実装前）**
   - A: admissionまたは明示recoveryで自動/手動回収する案。human reviewは通常admissionの自動回収を退け、fresh Reconcile後の明示recoveryだけを採用した。
   - B: Step FunctionsのCatch/Timeoutだけでterminal化する。通常failureは単純だが、execution開始前失敗や外部停止でstale stateが残り得る。
   - C: 定期sweeperを同時導入する。最終回復は早いが、Phase 4 scopeとAWS resourceを増やし、periodic reconcileの後続Phase境界を崩す。

Phase 7F repository completion時点で、Discord `/mc status`、`/mc start`、`/mc stop`はすべて既存Control Plane Admissionへ接続済みである。STOPはD-087のprogress revisionとD-086のdelivery protocolをSTARTと共用し、Phase 6のsave/graceful stop/EC2/DNS/Reconcile契約をDiscord層へ複製しないため、新しいDecisionは追加しない。Phase 7以降に残る既知事項は、Phase 1/Data EBS ownership retirement debt（別途承認後）、backup（Phase 8）、Package/Mod/Plugin（Phase 9/12）、chat integration（Phase 15）である。write-side Host RuntimeとRCON/secret production contractはD-075〜D-078で実証済みである。

dev用Discord Guild/channel/role/Application ID/Public Keyはrepository設定済みである。2026-08-31のPhase 7G-1で正本account/regionとPhase 6 safe stateを再確認し、operator非echo入力により固定Parameter `/wishicraft/dev/secret/discord-bot-token`をAWS managed keyの`SecureString` Version 1として新規作成した。値を取得しないmetadata queryでname/type/version/ARN/region/accountを確認し、値・fragmentをrepository、shell引数、environment、transcript、logへ保存していない。続くprocess-memory-onlyのDiscord read-only照合ではToken validity、Application ID/Public Key、Guild、operation/admin channel、player/admin roleのexact matchと、Botのoperation channelにおける`VIEW_CHANNEL`、`SEND_MESSAGES`、`EMBED_LINKS`を確認した。Gatewayとprivileged intentsはMVPのHTTP Interactions + REST message architectureでは不要である。

Phase 7G-1のcredential-backed `cdk diff --change-set=false`ではTarget差分0、Control PlaneはPhase 7 repository実装どおりHTTP API、Command/STATUS/Message Lambda、Operations Stream、SQS/DLQ、最小IAMと既存Lambda code更新だけであり、DynamoDB replacement/data loss、Target/Phase 1/EBS/SG/DNS mutationはない。`dynamodb:ListStreams`のresource `*`はresource-level restrictionをサポートしないlist actionに限定され、lifecycle/secret wildcardではない。Phase 1 diffには既知のhistorical UserData差分とreplacement可能性が残るため、Frozen stackをPhase 7G deploy対象から除外し続ける。現在のControl PlaneにはPhase 7 HTTP endpointが未deployである。Phase 7G-2のblocker/境界は、Control Plane stackだけの明示deploy、deploy後endpoint/PING確認、Discord Interaction Endpoint URL設定、Git正本commandの明示Guild registration、最低限monitoring release gate確認である。

Phase 7G-3 Gate 1では、role不足のrequestと、Discordが引数なしsubcommandへempty `options`を含めたproduction requestの双方がControl Plane Admission前にfail closedした。後者はDiscord protocolの正規shapeに対するparser compatibility bugであり、新Decisionではなく、`options`省略またはexact empty arrayだけを受理するstrict contractへ修正する。non-empty/non-array/unknown/nested shapeは拒否を維持し、deployとreal retryはrepository fixとは別の承認境界とする。

Phase 7G-3 STOPはOperation `op-6949d819-27be-4eec-85e9-8f04c735ed9c`としてsave/graceful stop/EC2 stop/DNS DELETE/INSYNC/final Reconcile/owned cleanupを完了し、Control Plane `SUCCEEDED`、Discord progress revision 5 `DELIVERED`へ収束した。一方、古いprogress workerのDiscord edit後にnewer revisionがdelivery metadataを先に完了したため、古いworkerのcompletion CASが失敗してMessage Lambda Errors alarmが発報した。D-086/D-087から直接導かれる実装修正として、completion CAS failure後のconsistent read-backが同一Operation type/channel、deterministic delivery ID、message IDを確認し、newer revision ownershipまたは同一revision terminal completionだけをstale no-opとする。revision regression、identity mismatch、same-revision unrelated ownershipは引き続きerrorとし、Alarm契約を緩和しない。Control Plane safety stateはDesired revision 9 STOPPED、fresh stopped/HEALTHY、Lock/Current Operationなし、queue/DLQ 0で不変であり、deploy/final STATUSは別承認境界とする。

Phase 7は2026-09-01にCompletedとなった。completion CAS fixをCI成功済みcommit `c88788742d08d9766c3be80f75d62c653151520d`からControl Planeだけへdeployし、final STATUS `op-0f415db5-d0a3-439a-b387-064db10d2329`でOperation 24→25、fresh stopped/HEALTHY、通常message一件、delivery revision 2 / attempt 1 / `DELIVERED`を確認した。deploy後のMessage Lambdaを含む主要Lambda Errors/Throttlesは0、24 alarmsは全件`OK`、retry/DLQは0である。production accountingはbaseline 19から、role/parser rejectionはOperation 0、initial-response timeoutを伴ったsuccessful STATUS 1、D-089後のSTOPPED STATUS、START、RUNNING STATUS、STOP、final STOPPED STATUSの計6 Operation増加で25となった。

real STARTは一Operation/一State MachineでREADY、DNS UPSERT/INSYNC、public TCP 25565とMinecraft 26.2 protocol 776へ到達し、real STOPはexplicit save、RCON fail-closed、graceful runtime stop、EC2 stop、DNS DELETE/INSYNC、fresh stopped/HEALTHY Reconcileを完了した。START/STOPはいずれも一公開messageをrevision 5まで単調更新し、duplicate/rollbackはなかった。STOP completion raceはControl Planeとfinal displayを変更せず、monitoring alarm emailが通知pathを実証した。final AWS stateはTarget stopped/public IPv4・DNSなし、Desired revision 9 STOPPED、Observed stopped/HEALTHY、Lock/Current Operation/running executionなし、Phase 1 Frozen、Data EBS/snapshot/SG safety不変である。Budgetは15 USD通知がactiveでactual 22.273 USD / forecast 23.005 USDとguardrail超過中であり、Phase 8 backup完成までは試験運用を維持する。新しいDecision Neededはない。

Phase別に決める事項:

| 項目 | 決定期限 |
|---|---|
| Lock owner identity、desired-state CAS、stale operation recovery | D-074でAccepted（2026-08-29） |
| RCON client/library / container-local command path | D-075でAccepted（2026-08-29） |
| dev Discord公開IDの実環境照合とBot Token SecureString存在確認 | Phase 7G-1で完了（2026-08-31） |
| Git正本`/mc` schemaのdev Guild registration | Phase 7G-2で完了（2026-08-31） |
| prod Discord Guild/channel/role/Application ID/Public Key/Bot Token | 最初のprod deploy前 |
| backup整合方式 | Phase 8開始前 |
| Package manifest最終schema | Phase 9開始前 |
| 最初のPaper Package | Phase 12開始前 |
| 最初のMOD loader/package | Phase 12開始前 |
| Web frontend技術 | Phase 13開始前 |

## 6. Backlog

### 高優先

- 意図的Minecraft停止のsystemd success表現（起動wrapper、終了コード伝播、`SuccessExitStatus=143`を比較してPhase 2前に決定）
- backup workflow
- 無人自動停止
- Minecraft EC2停止漏れalarm
- Game/Package/Template一般化
- create/list/info
- reset

### 中優先

- 旧バニラPackage
- Paper Package
- 最初のMOD Package
- 管理Web HTTP版
- OP/whitelist

### 低優先・将来

- WebSocket realtime
- Minecraft→Discord chat
- `/mc say`
- Discord Gatewayによる完全双方向chat
- restore UI
- Game upgrade
- archive/delete
- Package Web upload
- 高度なrole model
- plugin/mod独自権限
- chat履歴長期保存・検索
- sessionごとのDiscord thread

## 7. Decision追加テンプレート

```markdown
### D-XXX タイトル

- **状態:** Proposed | Accepted | Rejected | Superseded
- **日付:** YYYY-MM-DD
- **背景:**
- **決定:**
- **理由:**
- **影響:**
- **代替案:**
- **関連文書:**
```
