# 04. Domain and State Model

- **文書状態:** Canonical
- **最終更新:** 2026-08-29

## 1. 設計原則

システム全体を1つの状態文字列で表現しない。

たとえば`WAITING_FOR_SSM`は実世界のMinecraft状態ではなくoperationの進行段階であり、`ERROR`はEC2状態でもMinecraft状態でもない。これらを単一enumへ混在させると、再試行、状態ずれ、障害復旧の判断が不明確になる。

状態は次の軸へ分離する。

1. Desired State
2. Observed Infrastructure and Connection State
3. Observed Minecraft State
4. Operation State
5. Health
6. Game Lifecycle / Materialization State

## 2. ドメインエンティティ

### System

Minecraft実行基盤全体。初期構成では1つだけ存在する。

保持する主な情報:

- desired state
- requested game
- latest observed states
- current public IPv4 and fixed FQDN state
- current operation
- health
- last error

### Game

利用者が遊ぶ単位。

初回実用版では`game-vanilla-main`のみを登録する。複数ゲーム実装後もSystemが同時に要求できるGameは1つだけである。

### Operation

ユーザーまたは自動処理による操作。

主なtype:

- `STATUS`
- `START`
- `STOP`
- `BACKUP`
- `CREATE`
- `RESET`
- `OP_ADD`
- `OP_REMOVE`

### Lock

競合するoperationを排除するためのリース。

初回は`minecraft-control`というグローバルロック1個を使用する。

### Package

Minecraftサーバーを再現する不変構成。複数ゲームフェーズで導入する。

### Template

Package、Preset、ランタイム初期値を組み合わせたGame作成方法。

### Backup

特定Game、generation、Package versionに対応する復旧可能なスナップショット。

## 3. Desired State

```text
STOPPED
RUNNING
```

関連属性:

```text
desired_state
desired_game_id
requested_operation_id
desired_updated_at
desired_revision
rendered_revision
render_digest
applied_revision
convergence_status
```

規則:

- `STOPPED`では`desired_game_id`はnullを基本とする。
- `RUNNING`では`desired_game_id`が必須。
- Desired Stateは目標であり、成功した実状態を表さない。
- start受付時に`RUNNING`へ更新しても、その時点でREADYではない。
- stop受付時に`STOPPED`へ更新しても、その時点でEC2 stoppedとは限らない。

### Operation失敗時のDesired State

- `SetDesiredRunning`または`SetDesiredStopped`より前の検証失敗ではDesired Stateを変更しない。
- Desired State更新後にoperationが失敗しても、利用者が要求した目標状態は維持する。
- start失敗後はDesired `RUNNING`と未達のObserved Stateを保持し、Health、Discrepancy、Last Errorで表す。
- stop失敗後はDesired `STOPPED`と残存するEC2/MinecraftのObserved Stateを保持する。
- 初期版では失敗を理由にDesired Stateを自動で元へ戻さず、無期限の自動修復も行わない。

### Desired / Rendered / Applied revision

- 妥当な変更要求をControl Planeが受理したtransactionで`desired_revision`を進める。apply成功まで旧revisionへ留めず、失敗時もrollbackしない。
- canonicalなnon-secret itzg入力のrenderとvalidationが成功した後だけ`rendered_revision`と`render_digest`を進める。secret実値とその単純hashはdigest対象にしない。
- runtimeへの反映をprobe等で実測した後だけ`applied_revision`を進める。
- `desired_revision=N`、`applied_revision=N-1`、`convergence_status=APPLY_FAILED`のように未収束を保持できる。
- convergence statusは`CONVERGED`、`PENDING_RENDER`、`RENDER_FAILED`、`PENDING_APPLY`、`APPLYING`、`APPLY_FAILED`、`VERIFYING`、`VERIFY_FAILED`、`UNKNOWN`を候補とする。詳細schemaと永続化はPhase 2後段で確定する。
- Phase 2aはrender artifactとdigest生成までとし、DynamoDB更新やreconciliation state machineを実装しない。


## 4. Observed Infrastructure State

### EC2 State

AWS EC2 APIの値を正本とする。

```text
pending
running
stopping
stopped
shutting-down
terminated
unknown
```

`terminated`は通常運用では重大異常として扱う。

### SSM State

```text
online
offline
connection-lost
not-applicable
unknown
```

- EC2 stopped時は`not-applicable`を使用できる。
- API失敗や判定不能は`unknown`。

### Host Runtime State

```text
not-running
running
degraded
unknown
```

- EC2が`stopped`または`terminated`なら、SSMやhost probeを呼ばず`not-running`とする。
- EC2 API失敗、response schema不一致、またはrunning hostをまだprobeしていない場合は`unknown`とし、`not-running`へ読み替えない。
- running時はPhase 2 Host Runtimeのsystemd、Docker container、itzg runtimeをhost-local probeで観測する。Phase 1の直接Java `minecraft.service`をtargetの観測契約へ流用しない。


### Connection Endpoint State

```text
updating
ready
mismatch
not-applicable
unknown
```

関連属性:

```text
observed_public_ipv4: string | null
observed_dns_target_ipv4: string | null
observed_connection_endpoint_state
observed_dns_change_id: string | null
```

- EC2 stopped時は`not-applicable`を使用できる。
- EC2 running時に固定FQDNが現在のパブリックIPv4を指し、Route 53変更が`INSYNC`なら`ready`。
- 現在IPとDNS targetが異なる場合は`mismatch`。
- APIまたはDNS確認不能は`unknown`。

## 5. Observed Minecraft State

### Service State

systemdまたはプロセス管理層の状態。

```text
inactive
activating
active
deactivating
failed
not-applicable
unknown
```

### Protocol State

Minecraft Java Server List Ping等、Minecraft protocolへ互換応答できるかを示す。RCONはREADY判定へ使用しない。

```text
not-ready
ready
not-applicable
unknown
```

- container非running時は`not-applicable`。
- protocol pingのnonzero応答は`not-ready`、実行不能・timeout・出力schema異常は`unknown`。
- `ready`はprotocol response成功と期待Minecraft version一致を必要とし、Docker health、Java process、log、listenerだけから導出しない。
- Phase 3の`TargetStatus.ready`はruntime観測範囲のREADYである。START-005の最終起動成功には、後続sliceのactive game一致とconnection endpoint/DNS一致も別途必要である。

### Active Game ID

EC2ローカルruntime情報と実際の起動設定から確認したGame ID。

```text
observed_active_game_id: string | null
```

Phase 3のHost Runtime probeは、rendererがcontainerへ付与した明示的なGame IDとdata source metadataを観測し、実際の`/data` bind sourceとの整合を確認する。directory名、`server.properties`、world、`level.dat`からGame IDを逆算しない。container非running時はactive gameを`not-applicable`、running中にidentityを安全に取得できない場合は`unknown`とする。

active game差分はruntime protocol READYと別軸である。protocol応答が正常なら`TargetStatus.ready=true`を維持したまま、次を`discrepancies`へ導出できる。

```text
active-game-mismatch
active-game-unknown
runtime-state-mismatch
```

`active-game-mismatch`は期待Game IDと観測IDの差、`active-game-unknown`はrunning中のidentity観測不能、`runtime-state-mismatch`は宣言data sourceと実bindの不一致を表す。EC2またはcontainer停止時はactive game差分を生成しない。

### Player Count

```text
observed_player_count: integer | null
```

判定不能時は0ではなくnullとする。

固定Host Runtime probeは、Minecraft protocol status responseの`server_info.players.online`が非負整数の場合だけ`observed_player_count`へ正規化する。player sample、name、UUID、MOTD、raw responseは伝播・保存しない。player count fieldの欠損/不正、protocol failure、container停止、protocol not-applicableではnullとし、0人を観測した状態と区別する。player count fieldだけの観測失敗は有効なprotocol responseのREADYを変更しない。player countはREADY条件でもControl Plane convergence条件でもなく、0人でもprotocol READYは成立する。

Phase 3の最初のvertical sliceではTarget EC2が`stopped`の場合だけ、SSMを`not-applicable`、Host Runtimeを`not-running`、Minecraft service/protocolを`not-applicable`へ段階的に短絡する。次のsliceではEC2が`running`の場合だけSSM managed-node状態を照会し、AWS `PingStatus`の`Online`を`online`、`Inactive`を`offline`、`ConnectionLost`を`connection-lost`へ正規化する。SSM APIまたはresponse解析に失敗した場合とmissing/duplicate nodeは`unknown`とする。SSMがonlineでない限りHost Runtime以下は`unknown`のままとし、停止・READYを推測しない。

Phase 3 Host Runtime observationではSSM online時だけ固定read-only probeを実行する。期待XFS mount、Docker daemon active、Host Runtime unit inactive、対象container stoppedまたはnot-foundを正常に観測できた場合は、Host RuntimeとMinecraft runtimeを`not-running`、protocolを`not-applicable`とする。mount不一致、Docker unavailable、unit/container矛盾は`degraded`、transport、schema、identity、個別観測失敗は該当軸とHost Runtimeを`unknown`へfail-closedする。container runningやDocker healthだけではREADYにせず、固定container-local protocol observationの成功を必須とする。

### Runtime READYとstart convergence

Phase 3のruntime READYは、Target statusがEC2/SSM/Host Runtime/containerの正常観測とMinecraft protocol READYを満たす場合に成立する。active game、public endpoint、DNS、player countはruntime READY自体を書き換えない。

```text
observed_ec2_state == running
observed_ssm_state == online
observed_minecraft_service_state == active
observed_minecraft_protocol_state == ready
```

START-005の上位start convergence/successは、runtime READYに加え、active game一致とconnection endpoint/DNS一致を評価する。runtime READYは保存してもよいが観測値から再計算可能な派生値であり、convergenceと同一視しない。

## 6. Operation State

### Status

```text
PENDING
RUNNING
SUCCEEDED
FAILED
TIMED_OUT
CANCELLED
```

### Current Step

start例:

```text
ADMIT_OPERATION
VERIFY_LOCK_OWNERSHIP
PREPARE_PROGRESS_MESSAGE_IF_CONFIGURED
RECONCILE_BEFORE_START
VALIDATE_START
SET_DESIRED_RUNNING
START_EC2
WAIT_EC2_RUNNING
WAIT_SSM_ONLINE
RUN_START_SCRIPT
WAIT_MINECRAFT_READY
RENEW_LOCK
VERIFY_ACTIVE_GAME
UPDATE_DNS
WAIT_DNS_INSYNC
MARK_SUCCEEDED
RELEASE_LOCK
```

stop例:

```text
ADMIT_OPERATION
VERIFY_LOCK_OWNERSHIP
PREPARE_PROGRESS_MESSAGE_IF_CONFIGURED
RECONCILE_BEFORE_STOP
VALIDATE_STOP
SET_DESIRED_STOPPED
REQUEST_SAVE
STOP_MINECRAFT
WAIT_MINECRAFT_STOPPED
RENEW_LOCK
STOP_EC2
WAIT_EC2_STOPPED
DELETE_DNS_RECORD
WAIT_DNS_INSYNC
RECONCILE_AFTER_STOP
MARK_SUCCEEDED
RELEASE_LOCK
```

失敗時の共通step:

```text
RECORD_FAILURE
RECONCILE_AFTER_FAILURE
RELEASE_LOCK_AFTER_FAILURE
```

Operation statusとcurrent stepは別属性とする。

## 7. Health

```text
HEALTHY
DEGRADED
UNHEALTHY
UNKNOWN
```

### HEALTHY

Desired Stateと実測が一致し、重大なエラーがない。

例:

- Desired STOPPEDかつEC2 stopped
- Desired RUNNINGかつ対象Game READY

### DEGRADED

主要機能は利用可能だが、一部に問題がある。

例:

- Minecraft READYだがheartbeatが古い
- Discord進捗更新だけ失敗
- backupの最終成功時刻が古い

### UNHEALTHY

Desired Stateを満たさず、操作または管理者対応が必要。

例:

- Desired STOPPEDだがEC2 runningかつoperationなし
- Minecraft process activeだがRCON応答なしが継続
- active game mismatch
- data volume未マウント

### UNKNOWN

必要な観測ができず、健全性を確定できない。

## 8. Game Lifecycle State

複数ゲーム実装後に使用する。

```text
ACTIVE
ARCHIVED
DELETING
```

完全削除は後期機能のため、初期は`DELETING`を実装しなくてもよい。

## 9. Materialization State

```text
UNMATERIALIZED
MATERIALIZING
MATERIALIZED
MATERIALIZATION_FAILED
```

- `/mc create`完了直後は`UNMATERIALIZED`。
- 初回startでEC2上へ展開する。
- materialize中に失敗した場合、中途半端なディレクトリを本番Gameとして使用しない。
- stagingへ展開・検証後に原子的に切り替える方式を推奨する。

## 10. Generation

- Game作成時は`generation = 1`。
- reset成功時に1増やす。
- reset処理の途中で先に確定値を増やさない。
- 新ワールド生成・検証・停止まで成功した後、条件付き更新でgenerationを確定する。
- Backupは必ず対象generationを持つ。

## 11. 不変条件

### INV-001 単一Game

READYまたは起動途中として扱えるGameは同時に1つだけ。

### INV-002 Operation所有

`SystemState.current_operation_id`とグローバルLockの`owner_operation_id`は、競合operation中は一致する。実行者はさらにacquisition固有の`lease_id`を提示する。

### INV-003 Active Game一致

READY判定時は`observed_active_game_id == desired_game_id`。

### INV-004 停止完了

stop operationをSUCCEEDEDにするには、EC2 observed stateがstoppedでなければならない。

### INV-005 起動完了

start operationをSUCCEEDEDにするには、Minecraft、active game、固定FQDNを含むREADY条件を満たさなければならない。

### INV-006 Backup前提

resetで旧generationを移動する前に、最終backupが検証済みでなければならない。

### INV-007 Package不変

同一Package ID/versionのchecksumは変更しない。

### INV-008 秘密非出力

secretをOperation error detailや通常ログへ保存しない。


### INV-009 Current Operation所有

`SystemState.current_operation_id`の解除は、呼出元`operation_id`と保存値が一致する場合だけ行う。

### INV-010 Lock喪失後の副作用禁止

operationがLock所有権を失った後、EC2 start/stop、SSM command、Desired State更新、DNS更新等の新しい副作用を実行しない。

### INV-011 Idempotency一意性

同じ外部要求を表す`idempotency_key`は1つのOperationだけへ対応する。

### INV-012 Desired State失敗保持

Desired State更新後にoperationが失敗しても、failure cleanupがDesired Stateを暗黙に元へ戻さない。


## 12. ロックモデル

初回ロック:

```text
lock_name = minecraft-control
resource_id
owner_operation_id
lease_id
acquired_at
lease_expires_at
updated_at
```

### 取得条件

通常admissionではLock itemが存在しない場合だけ取得できる。

```text
attribute_not_exists(lock_name)
```

acquisitionごとに新しい`lease_id`を発行する。期限切れitemの存在はstale Operation candidateを示し得るため、通常admissionは自動takeoverせず競合をblockする。

### 延長条件

```text
owner_operation_id == caller_operation_id
AND lease_id == caller_lease_id
AND lease_expires_at >= now
```

Wait/pollループ中は延長間隔がリース期限より十分短くなるようにする。副作用直前にも所有権を確認する。条件付き延長に失敗した場合は`LOCK_LOST`とする。

### 解放条件

```text
owner_operation_id == caller_operation_id
AND lease_id == caller_lease_id
AND lease_expires_at >= now
```

### TTL

Phase 4 MVPではLock TTLを有効化しない。将来追加するTTL属性は古いitemの物理削除用に限り、leaseの有効性や解放完了判定には使用しない。

### Stale Operation recovery

Lock expiryとOperation failureは同義ではない。deadline超過またはlease expiryを検出した通常admissionは新しい競合operationを拒否する。fresh Reconcile後の明示recoveryだけが、観測結果を根拠に旧Operationをterminalへ条件付き遷移し、`owner_operation_id`、`lease_id`、`current_operation_id`の一致を同一transactionで確認してownershipを整理できる。実状態を観測せず単純にFAILEDへ変えない。


### Operation Admission

競合operationの受付はDynamoDB Transactionで次を同時に行う。

```text
Put Idempotency if attribute_not_exists(idempotency_key)
Put Operation if attribute_not_exists(operation_id)
Put Lock if attribute_not_exists(lock_name)
Update SystemState if current_operation_id is absent or DynamoDB NULL
```

Transactionが失敗した場合、Operationを作成せず、workflowを開始しない。受付成功後にStep Functions開始が失敗した場合は、Operationを失敗へ更新し、所有者条件付きでLockとCurrent Operationを解除する。

## 13. 冪等性

### Operation作成

- `operation_id`は呼び出し元または受付serviceが一度だけ生成する。
- 同じIDで既存operationがあれば新規作成しない。
- 外部要求には安定した`idempotency_key`を付け、専用itemを条件付き作成する。
- 同じidempotency keyが既に存在する場合は、対応する既存operationを返し、新しいoperation IDを生成しない。

### Lambda Task

各Taskは、現在状態とoperationを確認してから副作用を実行する。

例:

- EC2が既にrunningならStartInstancesを再実行せず次へ進める。
- 同じGameがREADYならstart成功相当へ進める。
- EC2が既にstoppedならstop成功相当へ進める。
- backup manifestが同一operation IDで既に検証済みなら重複archiveを作らない。

### EC2スクリプト

- `operation_id`を受け取る。
- runtimeへ最後に成功したoperationを記録する。
- 同じoperationの重複実行で破壊的処理を繰り返さない。

## 14. Reconcileルール

### 入力

- SystemState snapshot
- EC2 API結果
- SSM managed node状態
- probe JSON
- current operation

### 出力

- 新しいObserved State
- health
- discrepancy list
- observed_at

### 原則

- 観測できない属性だけを`unknown`とし、他の取得済み属性まで破棄しない。
- 古いprobe結果で新しい状態を上書きしない。
- `observed_at`またはversionを使って条件付き更新する。
- operation中の一時的不一致は、operation stepと合わせて評価する。
- EC2が`stopped`または`terminated`で、固定FQDNのAレコードが残り、start operationが進行していない場合はstale DNS discrepancyを記録し、安全なcleanup対象とする。


## 15. SystemState更新ルール

SystemState全体を読み取り、全属性をPutItemで書き戻さない。更新責務を次の属性群へ分ける。

- Desired State更新
- Current Operation設定・所有者付き解除
- Observed StateとHealth更新
- Last Error更新

ReconcileはObserved State、Health、Discrepancies、observed_atだけを条件付き部分更新し、Desired StateやCurrent Operationへ触れない。古い観測は`observed_at`または観測versionで拒否する。

## 16. STATUS Operation

利用者が明示的に要求したstatusだけをOperationへ記録する。STATUSはグローバルLockを取得せず、`SystemState.current_operation_id`を設定しない。定期reconcile、state machine内部probe、EventBridge起動はOperationを作成しない。

## 17. 初期タイムアウト

値は設定から変更可能にする。具体値の正本は`config/stages/<stage>.yaml`とし、この表は初期推奨値を示す。

| 対象 | 初期値 |
|---|---:|
| EC2 running待ち | 5分 |
| SSM online待ち | 5分 |
| バニラMinecraft READY待ち | 10分 |
| Minecraft通常停止待ち | 3分 |
| EC2 stopped待ち | 5分 |
| start/stopグローバルロック | 15分 |
| lock延長間隔 | 2分 |
| SSM probe | 1分以内 |
| Route 53 INSYNC待ち | 2分 |
| start workflow全体 | 30分 |
| stop workflow全体 | 20分 |
| status全体 | 2分 |
| backup | 15分 |

MOD Packageではmanifestまたはruntime設定によりMinecraft READY待ちを上書きできる。

## 18. エラーコード

### 共通

```text
INVALID_REQUEST
UNAUTHORIZED
FORBIDDEN
OPERATION_NOT_FOUND
OPERATION_ALREADY_RUNNING
LOCK_CONFLICT
LOCK_LOST
STATE_CONFLICT
STATE_UNKNOWN
INTERNAL_ERROR
```

### Game

```text
GAME_NOT_FOUND
GAME_NOT_ACTIVE
GAME_NOT_MATERIALIZED
GAME_ALREADY_RUNNING
ANOTHER_GAME_RUNNING
ACTIVE_GAME_MISMATCH
```

### EC2 / SSM

```text
EC2_START_FAILED
EC2_START_TIMEOUT
EC2_STOP_FAILED
EC2_STOP_TIMEOUT
EC2_TERMINATED
SSM_NOT_ONLINE
SSM_ONLINE_TIMEOUT
SSM_COMMAND_FAILED
SSM_COMMAND_TIMEOUT
```

### Minecraft

```text
MINECRAFT_SERVICE_FAILED
MINECRAFT_START_FAILED
MINECRAFT_READY_TIMEOUT
MINECRAFT_SAVE_FAILED
MINECRAFT_STOP_FAILED
MINECRAFT_STOP_TIMEOUT
MINECRAFT_PROTOCOL_UNAVAILABLE
```

### Data / Backup

```text
DATA_VOLUME_NOT_MOUNTED
PACKAGE_NOT_FOUND
PACKAGE_CHECKSUM_MISMATCH
MATERIALIZATION_FAILED
BACKUP_CREATE_FAILED
BACKUP_UPLOAD_FAILED
BACKUP_VERIFY_FAILED
RESET_PRECONDITION_FAILED
```

内部error detailと利用者向けmessageは分離する。

## 14. Phase 3 Endpoint / Reconcile state

public IPv4は`assigned | absent | unknown`、Route 53 A recordは`present | absent | unknown`としてraw factを分離する。EC2 stopped/terminatedでpublic IPv4 absentかつDNS absentは正常で、discrepancyを生成しない。

Endpoint discrepancyは`dns-missing-when-required`、`dns-points-to-wrong-ipv4`、`dns-present-while-endpoint-should-be-absent`、`public-ipv4-unknown`、`dns-observation-unknown`を使用する。runtime READY、active game discrepancy、endpoint discrepancy、healthは別軸とする。

desired STOPPEDでEC2 stoppedかつendpoint discrepancy/observation errorなしは`HEALTHY`。観測不能は`UNKNOWN`、desiredとの差分は`DEGRADED`とする。観測failure時はfresh `observed_at`、関連state unknown、runtime ready false、固定error classificationを持つ新しいSystemStateを保存し、過去のREADYを残さない。
