# 05. Data and Interface Contracts

- **文書状態:** Canonical
- **最終更新:** 2026-08-31

## 1. 契約変更ルール

この文書の属性名、enum、入出力を変更する場合、次を同一変更で更新する。

- 実装コード
- 単体テスト
- CDK定義
- 対応する状態・要件文書
- Decision log

後方互換性が必要になる運用開始後は、`schema_version`または明示的migrationを導入する。

## 2. 共通形式

### ID

| 対象 | 形式例 |
|---|---|
| Game | `game-<validated-slug>`または`game-<ulid>`。初期予約IDは`game-vanilla-main` |
| Operation | `op-<ulid>` |
| Package | 人間可読slug例`vanilla`、`create-pack` |
| Package Version | SemVerまたは不変version string |
| Template | 人間可読slug |
| Backup | `backup-<ulid>` |

IDはシェルパスとして直接使用せず、許可文字を検証した上で内部resolverを通す。

### 時刻

- 保存形式はUTCのISO 8601文字列を基本とする。
- DynamoDB TTL用属性だけepoch secondsを使用する。
- Discord表示時に利用者向けtimezoneへ変換する。

### JSON応答

共通フィールド:

```json
{
  "schema_version": 1,
  "success": true,
  "operation_id": "op-...",
  "timestamp": "2026-07-23T00:00:00Z",
  "data": {},
  "error": null
}
```

失敗例:

```json
{
  "schema_version": 1,
  "success": false,
  "operation_id": "op-...",
  "timestamp": "2026-07-23T00:00:00Z",
  "data": null,
  "error": {
    "code": "MINECRAFT_READY_TIMEOUT",
    "message": "Minecraft did not become ready within the configured timeout.",
    "retryable": true
  }
}
```

secret、token、RCON password、AWS credentialを含めない。

## 3. DynamoDB: SystemState

### Key

```text
PK: system_id
```

初期値:

```text
system_id = wishicraft-main
```

### Attributes

Phase 3のcurrent status persistenceは、次の最小属性を使用する。`observation`はraw AWS responseではなく正規化済みの観測属性群である。

```yaml
system_id: wishicraft-main
schema_version: 1
environment: dev
game_id: game-vanilla-main
desired_state: STOPPED | RUNNING
target_instance_id: string | null
observation: normalized map
discrepancies: list[string]
health: HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN
observation_errors: list[string]
observed_at: fixed-width UTC timestamp
```

`observation.player_count`は正常に取得できた場合だけ0以上の整数、それ以外はnullである。将来flat属性へ展開する場合のcanonical名は`observed_player_count`とし、0人とunknown/not-applicableを区別する。player countだけの観測失敗はprotocol READYを書き換えない。

Phase 4以降にoperationを導入するときは、次の属性群を同じitemへ追加できるが、Phase 3 Reconcileはこれらを先行作成・更新しない。

```yaml
desired_revision: 42
desired_game_id: string | null
requested_operation_id: string | null
desired_updated_at: timestamp | null

observed_ec2_state: string
observed_public_ipv4: string | null
observed_dns_target_ipv4: string | null
observed_connection_endpoint_state: updating | ready | mismatch | not-applicable | unknown
observed_dns_change_id: string | null
observed_ssm_state: string
observed_minecraft_service_state: string
observed_minecraft_protocol_state: string
observed_active_game_id: string | null
observed_player_count: integer | null
observed_at: timestamp | null

health: HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN
discrepancies: list[string]
current_operation_id: string | null
last_error_code: string | null
last_error_at: timestamp | null
updated_at: timestamp
```

### 更新条件

- SystemState全体のPutItem置換を避け、属性群ごとのUpdateItemを使用する。
- Desired State更新、Current Operation更新、Observed State更新、Last Error更新をrepository APIで分離する。
- ReconcileはTarget identityを含むObserved State、Health、Discrepancies、observation errors、observed_atだけを更新する。初回item作成時のidentityと既定`desired_state=STOPPED`は`if_not_exists`で設定し、既存Desired StateやCurrent Operationを上書きしない。
- `observed_at`または観測versionで古い結果を拒否する。
- `current_operation_id`の解除は保存値が呼出元operation IDと一致する場合だけ行う。

## 4. DynamoDB: Games

### Key

```text
PK: game_id
```

### 初回Game

```yaml
game_id: game-vanilla-main
schema_version: 1
version: 1
display_name: Wishicraft Vanilla
normalized_display_name: wishicraft-vanilla
lifecycle_state: ACTIVE
materialization_state: MATERIALIZED

created_from:
  template_id: null
  template_version: null

package:
  package_id: vanilla
  package_version: initial-fixed-version

runtime:
  class: default
  idle_shutdown_minutes: 30

world:
  generation: 1
  seed: null
  difficulty: null
  hardcore: null

created_at: timestamp
updated_at: timestamp
last_started_at: null
last_backup_at: null
```

### 正式属性

```yaml
game_id: string
schema_version: 1
version: integer
display_name: string
normalized_display_name: string
lifecycle_state: ACTIVE | ARCHIVED | DELETING
materialization_state: UNMATERIALIZED | MATERIALIZING | MATERIALIZED | MATERIALIZATION_FAILED

created_from:
  template_id: string | null
  template_version: string | null

package:
  package_id: string
  package_version: string

runtime:
  class: string
  idle_shutdown_minutes: integer

world:
  generation: integer
  seed: string | null
  difficulty: string | null
  hardcore: boolean | null

created_at: timestamp
updated_at: timestamp
last_started_at: timestamp | null
last_backup_at: timestamp | null
```

DynamoDBではnested mapを使用できるが、頻繁に条件更新する属性はトップレベルへ出すことを許可する。実装前にrepository APIで隠蔽する。

`runtime.class`は論理的なruntime capability/mapping selectorであり、image tag/digest、Java runtime、Docker/Compose/AL2023、container/JVM memoryをGame itemへ複製しない。初期`default` classのrealizationは`config/stages/dev.yaml.host_runtime`とD-060〜D-062のGit管理platform lockを唯一の正本とする。初期単一GameのMinecraft `VERSION=26.2` / `TYPE=VANILLA`も現時点では同じGit lockが正本で、Phase 9以降にPackageを導入した後は不変`package_id`/`package_version`参照が論理Game構成を所有する。Phase 1 `compute`、host Corretto、直接Java、Xms/Xmx 1G/3Gはas-built履歴であり、このGame desired-state schemaへ戻さない。

初期Gameは固定admin path `python -m wishicraft.game_admin --stage dev`を明示実行し、`attribute_not_exists(game_id)`条件で一度だけ登録する。deployやLambda cold startが既存Gameを無条件上書きしない。2026-08-29のdev integrationで初回登録成功、同一payload再登録と異なるpayload上書きのconditional rejectionを実測した。

| 値 | 現在の唯一の正本 | realization / observation |
|---|---|---|
| Minecraft VERSION / TYPE | dev `host_runtime.minecraft`（将来はimmutable Package参照） | itzg入力とprotocol観測 |
| runtime class | Game `runtime.class` | Git管理mappingがHost Runtime artifactへ変換 |
| Java runtime / itzg image | dev `host_runtime.image` | pinned container image |
| container/JVM memory | dev `host_runtime.memory` | Compose/runtime observation |
| Host platform / Docker / Compose | dev `host_runtime.platform` / `compose` | Target Host Runtime |
| expected active Game ID | initial Git identity（Phase 4後はvalidated desired Game ID） | explicit container labelと`/data` bindで観測 |

## 5. DynamoDB: Operations

### Key

```text
PK: operation_id
```

### Attributes

```yaml
operation_id: string
schema_version: 1
idempotency_key: string
workflow_execution_name: string | null
workflow_execution_arn: string | null
operation_type: STATUS | START | STOP | BACKUP | CREATE | RESET | OP_ADD | OP_REMOVE
target_game_id: string | null
requested_by:
  source: DISCORD | WEB | SCHEDULE | ADMIN | CLI
  discord_user_id: string | null
  display_name: string | null
requested_at: timestamp
started_at: timestamp | null
completed_at: timestamp | null
status: PENDING | RUNNING | SUCCEEDED | FAILED | TIMED_OUT | CANCELLED
current_step: string | null
timeout_at: timestamp | null
lock_name: string | null
lease_id: string | null

error:
  code: string | null
  message: string | null
  detail_ref: string | null
  retryable: boolean | null

discord:
  guild_id: string | null
  channel_id: string | null
  message_id: string | null
  interaction_id: string | null

result: map | null
updated_at: timestamp
expires_at: epoch_seconds | null
```

STATUSの`result`はfresh Reconcile後に生成したuser-facing projectionであり、SystemStateの正本ではない。Phase 7C schema version 1は`kind=STATUS`、`status=stopped|starting|online|stopping|degraded|unknown`、`ready`、lowercase `health`、利用可能時だけのcanonical `endpoint`、`observed_at`、固定safe summaryだけを保存する。raw exception、AWS/SSM detail、instance identity、secret、role判定情報を含めない。

### Index候補

- GSI: `status` + `requested_at`
- GSI: `target_game_id` + `requested_at`

初期トラフィックではGSIなしで開始し、必要な管理画面クエリが確定してから追加してよい。

古いoperationはTTLで削除可能だが、監査期間を決めてから有効化する。

## 6. DynamoDB: Locks

### Key

```text
PK: lock_name
```

### Attributes

```yaml
lock_name: minecraft-control
resource_id: wishicraft-main
owner_operation_id: string
lease_id: string
acquired_at: timestamp
lease_expires_at: epoch_seconds
updated_at: timestamp
```

`owner_operation_id`はlogical ownership、acquisitionごとに一意な`lease_id`は現在leaseを保持するexecutorのproofである。renew、release、副作用直前の確認は両者の一致と`lease_expires_at >= now`を要求する。Phase 4 MVPではTTLを有効化せず、期限切れLockも通常admissionが自動takeoverしない。


## 7. DynamoDB: Idempotency

外部要求の再送が異なる`operation_id`で二重受付されることを防ぐため、専用itemを使用する。

### Key

```text
PK: idempotency_key
```

### Attributes

```yaml
idempotency_key: string
operation_id: string
operation_type: string
source: DISCORD | WEB | SCHEDULE | ADMIN | CLI
target_game_id: string | null
created_at: timestamp
expires_at: epoch_seconds | null
```

例:

```text
discord:<interaction_id>
cli:<client_request_id>
schedule:<rule_name>:<scheduled_time>
```

取得は`attribute_not_exists(idempotency_key)`条件付きPutで行う。同じkeyが存在する場合は保存済み`operation_id`を返す。TTLを使用する場合も、外部サービスの再送期間と監査要件より短くしない。


## 8. DynamoDB: RuntimeHeartbeats

Phase 8以降に追加する。Minecraft EC2からSystemStateを直接更新させず、heartbeat専用itemへ書き込ませる。

### Key

```text
PK: system_id
```

### Attributes

```yaml
system_id: wishicraft-main
schema_version: 1
boot_id: string
active_game_id: string | null
protocol_state: ready | not-ready | unknown
player_count: integer | null
empty_since: timestamp | null
observed_at: timestamp
expires_at: epoch_seconds
```

Minecraft EC2 roleはこのitemの更新だけを許可する。自動停止開始前にはheartbeatだけで判断せず、Reconcileを実行する。

## 9. 後期テーブル

### Packages

Key:

```text
PK: package_id
SK: package_version
```

### Templates

Key:

```text
PK: template_id
SK: template_version
```

### Backups

バックアップ一覧をDynamoDBで検索する必要が生じた時点で追加する。初期はS3 manifestとGame.last_backup_atで開始してよい。


## 10. SystemState Repository契約

```text
set_desired_state(...)
set_current_operation_if_empty(...)
clear_current_operation_if_owner(operation_id)
update_observation_if_newer(observed_at, ...)
record_last_error(...)
```

各methodは担当属性だけをUpdateExpressionで変更する。ReconcileがDesired StateやCurrent Operationを更新せず、workflowがObserved Stateを全項目書き戻ししないようにする。

## 11. Reconcile Lambda契約

### Input

```json
{"schema_version":1,"operation":"reconcile"}
```

Phase 3ではdeployment configurationで許可済みの単一system/game/Targetだけを解決する。外部inputからsystem ID、instance ID、shell、Hosted Zone、record nameを上書きできない。operation metadataを伴う呼出しはOperation domain導入後にversioned contractとして追加する。

### Output

```json
{
  "schema_version": 1,
  "system_id": "wishicraft-main",
  "environment": "dev",
  "game_id": "game-vanilla-main",
  "desired_state": "RUNNING",
  "target_instance_id": "i-...",
  "observation": {
    "ec2_state": "running",
    "public_ipv4": "203.0.113.10",
    "dns_ipv4_values": ["203.0.113.10"],
    "ssm_state": "online",
    "host_runtime_state": "running",
    "minecraft_service_state": "running",
    "minecraft_protocol_state": "ready",
    "observed_active_game_id": "game-vanilla-main",
    "player_count": 0,
    "runtime_ready": true
  },
  "health": "HEALTHY",
  "discrepancies": [],
  "observation_errors": [],
  "observed_at": "2026-08-28T00:00:00.000000Z"
}
```

Phase 3 first sliceのrepository-only outputはTarget EC2 identityを呼出元から明示的に受け取り、EC2 `DescribeInstances`の実測だけを正規化する。EC2が`stopped`なら次を返し、SSM APIまたはRun Commandを呼ばない。

```json
{
  "schema_version": 1,
  "instance_id": "i-...",
  "ec2_state": "stopped",
  "ssm_state": "not-applicable",
  "mount_state": "unknown",
  "docker_state": "unknown",
  "host_runtime_state": "not-running",
  "container_state": "unknown",
  "minecraft_service_state": "not-applicable",
  "minecraft_protocol_state": "not-applicable",
  "player_count": null,
  "ready": false,
  "observed_at": "2026-08-23T00:00:00Z"
}
```

API failure、missing/duplicate instance、未知EC2 state、response schema不一致は`ec2_state=unknown`とし、下位stateも`unknown`、`ready=false`とする。Target instance IDをGitへ新しい物理ID正本として埋め込まず、将来のLambda environmentまたはCDK output wiringからadapterへ渡す。

Phase 3 second sliceはEC2が`running`の場合だけSSM `DescribeInstanceInformation`をTarget instance IDでfilterする。単一の一致nodeについて`PingStatus=Online`を`online`、`Inactive`を`offline`、`ConnectionLost`を`connection-lost`へ正規化する。API failure、response schema不一致、missing/duplicate node、未知`PingStatus`、未処理paginationは`unknown`へfail-closedする。SSMがonlineでない場合はRun CommandまたはHost Runtime probeを実行せず、Host RuntimeとMinecraft stateを`unknown`のまま返す。

Phase 3 third sliceでは`DescribeInstanceInformation`の全pageを追跡し、Target instance IDが全pageを通じてexactly one matchの場合だけstateを採用する。空・非string・循環token、100 page超過、malformed page、0件、2件以上、API failureは`unknown`へfail-closedする。

SSM online時だけ、Control Planeがcommand文字列を受け取らない固定operation `run_probe(instance_id=...)`を呼ぶ。adapterはrepository-packaged probeをbase64で固定転送し、`AWS-RunShellScript`、単一Target、execution timeout 45秒、transport timeout 60秒、concurrency 1、errors 0でSendCommandする。Command IDを検証し、GetCommandInvocationをterminalまでpollする。timeout、API error、nonzero exit、command failure、transport schema failureではHost Runtime以下を`unknown`、`ready=false`とする。stdout JSONとstderr diagnosticを分離し、AWS detailをdomain errorへ露出しない。

### Phase 3 Host Runtime read-only probe v1

probeは引数を持たず、stdoutへ次のversioned JSON一件だけを出力する。診断はstderr、component failure codeは`errors`へsecret-freeな固定codeとして出す。

```json
{
  "schema_version": 1,
  "probe_version": "1.3.0",
  "observed_at": "2026-08-27T00:00:00Z",
  "identity": {
    "instance_id": "i-...",
    "runtime_id": "wishicraft-host-runtime",
    "compose_project": "wishicraft-host-runtime",
    "compose_service": "minecraft"
  },
  "mount": {
    "state": "expected",
    "mount_path": "/srv/minecraft",
    "filesystem_type": "xfs",
    "filesystem_uuid": "...",
    "expected_filesystem_type": "xfs",
    "expected_filesystem_uuid": "...",
    "root_uid": 0,
    "root_gid": 0,
    "root_mode": "0755"
  },
  "docker": {"state": "active"},
  "host_runtime": {
    "unit": "wishicraft-host-runtime.service",
    "state": "inactive"
  },
  "container": {
    "state": "not-found",
    "container_id": null,
    "name": null,
    "image_reference": null,
    "image_digest": null,
    "restart_policy": null,
    "health": "not-applicable",
    "oom_killed": null,
    "restart_count": null,
    "published_ports": {}
  },
  "active_game": {
    "state": "not-applicable",
    "game_id": null,
    "binding_consistency": "not-applicable"
  },
  "minecraft": {
    "runtime_state": "not-running",
    "protocol_state": "not-applicable",
    "protocol": {
      "attempted": false,
      "result": "not-applicable",
      "compatible_response": false,
      "host": "localhost",
      "port": 25565,
      "reported_version": null,
      "protocol_version": null,
      "player_count": null,
      "version_match": null,
      "observed_at": null
    },
    "ready": false
  },
  "errors": []
}
```

probeはIMDSv2 instance ID、固定mount path/type/UUID、systemd unit state、Docker daemon、固定Compose project/service labelに一致するcontainerだけを観測する。`systemctl`/Docker/Composeのstart・stop・restart、mount変更、filesystem mutation、package/image操作、secret取得、environment/log出力、Minecraft内部file/world/RCONへのアクセスを禁止する。containerが正常に存在しない場合は`not-found`、停止済みなら`stopped`、観測不能なら`unknown`を区別する。container非running時はMinecraft runtimeを`not-running`、protocolを`not-applicable`、active gameを`not-applicable`、readyをfalseとする。

probe v1.2.0で追加したactive game contractは、Host Runtime rendererがCompose serviceへ付与する`com.wishicraft.active-game-id`と`com.wishicraft.active-game-data-source`をrealized runtime metadataとして使用する。container running時だけvalidated `game-<slug>` IDを返し、宣言data sourceとDocker inspectで一意に観測したbind `/data` sourceを比較する。directory名からGame IDを逆算しない。metadata missing/malformed/ambiguousはactive game `unknown`、宣言とbindの不一致は`binding_consistency=mismatch`とし、Control Planeはそれぞれ`active-game-unknown` / `runtime-state-mismatch`へ導出する。期待IDとの差は`active-game-mismatch`とする。

container running時だけ、一意に解決したcontainer IDへ固定`docker exec <id> mc-monitor status --json --host localhost --port 25565 --timeout 3s`を実行する。外部command、host、port、timeoutをControl Plane inputにしない。probe v1.3.0はraw responseからhost/port、version name、protocol version、`players.online`の非負整数だけを抽出し、MOTD、favicon、player sample/name/UUID、raw JSONを出力しない。`player_count`は取得成功時の整数（0を含む）で、field欠損/不正、protocol failure/not-applicable時はnullとする。player count fieldだけの不正は有効なprotocol responseを失敗へ変えない。`result`は`success` / `failed` / `unavailable` / `unknown` / `not-applicable`を取り、試行時だけprotocol固有`observed_at`をUTCで持つ。nonzeroは`not-ready`、timeout/実行不能/protocol schema異常は`unknown`、container非runningは`not-applicable`とする。player countはREADY条件ではなく、0人でもREADYになり得る。

期待version `26.2`との比較は、report nameが`26.2`または`Minecraft 26.2`等の独立したversion tokenを含む場合を一致とし、`1.26.2`や`26.20`は一致させない。protocol成功、version一致、mount expected、Docker active、Host Runtime active、container running、component errorなしをすべて満たす場合だけPhase 3 runtime `ready=true`とする。active game mismatchはこのruntime READYを書き換えず、別の`discrepancies`属性に保持する。START-005全体の完了にはruntime READY、active game一致、connection endpoint/DNS一致を上位Workflowで評価する。schema version、probe version、required field、enum、type、UTC timestamp、instance/runtime identity、impossible combinationをstrict parserで検証し、未知versionをbest-effort parseしない。


## 12. Operation Admission契約

### Input

```json
{
  "schema_version": 1,
  "operation_id": "op-...",
  "idempotency_key": "discord:<interaction_id>",
  "operation_type": "START",
  "system_id": "wishicraft-main",
  "game_id": "game-vanilla-main",
  "requested_by": {
    "source": "DISCORD",
    "discord_user_id": "..."
  }
}
```

### Transaction

競合operationでは次を一体として実行する。

1. `Idempotency`へkeyを条件付きPut
2. `Operations`へ条件付きPut
3. `Locks`へ不存在条件付きPut（期限切れitemも通常admissionではtakeoverしない）
4. `SystemState.current_operation_id`をabsent / DynamoDB NULL条件付きUpdate

同じidempotency keyが既に存在し、operation type、source、target Gameも一致する場合は、保存済みoperation IDを返し、新しいOperation IDを生成しない。同じkeyを異なるpayloadへ再利用した場合はconflictとして拒否する。

成功後、Step Functionsを`operation_id`と同じexecution nameで開始し、execution ARNをOperationへ保存する。開始失敗時はOperationをFAILEDへ更新し、所有者条件付きでLockとCurrent Operationを解除する。Idempotency itemは失敗履歴との対応を維持するため削除せず、同じ要求の再送には既存の失敗結果を返すか、利用者が新しいrequest IDで再実行する。

### STATUS admission

STATUS Operationはactive GameのConditionCheckとともに`Idempotency`と`Operations`だけを条件付き作成し、`Locks`と`SystemState.current_operation_id`を変更しない。定期reconcileはOperation admissionを使用しない。
STATUSのterminal更新は、Operation typeがSTATUS、`lock_name`がNULL、現在statusがPENDING/RUNNINGである条件をすべて満たす専用repository pathだけで行う。lockを持つOperationのowned completionと混用しない。

### Desired State CAS

Desired mutationはcallerが読んだ`desired_revision=N`を条件に、同一更新で`N+1`へ進める。必要なoperationでは`current_operation_id`一致もtransaction conditionへ含める。Observed freshnessは引き続き`observed_at`で保護し、ReconcileはDesired属性を更新しない。将来の`rendered_revision`、`applied_revision`とは別のrevisionとして接続する。

### Stale Operation recovery

deadline超過またはlease expiryはstale candidateであり、それだけでFAILEDを意味しない。通常admissionは競合をblockする。明示recoveryはfresh Reconcile evidenceを必須とし、旧Operationのterminal化、owned Lock削除、owned `current_operation_id`解除を一transactionで条件付き実行する。

### CLI/Admin admission

Phase 5、6の管理CLIとintegration testは、この契約を呼び出してからworkflowを開始する。State Machineへの直接`StartExecution`を通常の確認手順にしない。

## 13. Operation Task Lambda契約

Task Lambdaは1責務に限定する。

例:

- acquire lock
- update operation step
- validate start
- start EC2
- get SSM state
- send SSM command
- parse command result
- Discord進捗先がある場合だけmessageを作成・更新する

共通Input:

```json
{
  "schema_version": 1,
  "operation_id": "op-...",
  "system_id": "wishicraft-main",
  "game_id": "game-vanilla-main",
  "context": {}
}
```

共通Outputは入力を保持しつつ、Task結果を`context`へ追加する方式を基本とする。ただしStep Functions payloadが肥大化しないよう、大きなログやarchive情報はDynamoDB/S3参照へ置く。

## 14. Host Runtime操作契約

### Phase 5 START operation v1

Control PlaneはSSM `AWS-RunShellScript`へ次のrepository固定commandだけを送る。

```text
sudo /usr/local/libexec/wishicraft/operation-v1 START
```

wrapperの入力は引数1個のliteral `START`だけである。外部requestからinstance ID、shell、path、game ID、Minecraft commandを渡さず、TargetはProject/Stage/Purpose tagでexactly oneに解決する。wrapperは固定`wishicraft-host-runtime.service`へ`systemctl start`を行い、active確認後にsecret-free JSONをstdoutへ返す。READY待機はwrapperではなくReconcile/Step Functionsが行う。

```json
{"schema_version":1,"operation":"START","status":"accepted"}
```

不正operationはexit 64と`INVALID_OPERATION`でfail-closedする。Phase 5 STARTはRCONを使わない。将来のMinecraft-aware writeはD-075のcontainer-local `rcon-cli`境界を使用し、同じwrapperへ任意commandを追加しない。

### Phase 5 START workflow task input

State Machineの初期inputはadmissionが生成した次の値だけとする。

```json
{"schema_version":1,"operation_id":"op-...","lease_id":"lease-..."}
```

各protected taskは`owner_operation_id=operation_id`、`lease_id`、未期限切れを直前に確認する。poll loopはProvisionalな120秒間隔、renew後leaseは900秒である。Desired RUNNINGは`desired_revision` CAS、Observedはfresh Reconcileの`observed_at`で独立して更新する。

START terminal successはEC2 running、SSM online、Phase 3 runtime READY、active Game一致、public IPv4存在、Route 53 change `INSYNC`、A recordが現在IPv4と一致の全条件を要求する。runtime READY、desired convergence、Operation successは別概念として保持する。

### Phase 6 STOP operation v1

Control PlaneはSSMへrepository固定command `sudo /usr/local/libexec/wishicraft/operation-v1 STOP`だけを送る。wrapperはliteral `START`または`STOP`一個だけを許可する。STOPは固定mount guard、Compose serviceから解決したexactly-one container、container-local `rcon-cli save-all flush`、systemd stop、container/process/25565・25575 listener消滅確認へ変換する。save失敗またはRCON unavailableではfail closedし、EC2 stopを呼ばない。password、任意shell、任意Minecraft command、任意path、任意container IDをinputにしない。

STOP workflow inputはPhase 5と同じ`schema_version`、`operation_id`、`lease_id`だけである。Desired STOPPEDは`desired_revision` CASし、既にDesired STOPPEDならrevisionを増やさずactual convergenceを継続する。Actual stoppedならruntimeを再起動せずDNS cleanupとfresh Reconcileへ進む。terminal successはDesired STOPPED、EC2 stopped、SSM not-applicable、Host Runtime not-running、Minecraft service/protocol not-applicable、public IPv4 absent、DNS absent、observation error/discrepancyなしを要求する。

failure codeは少なくとも`STOP_PRECONDITION_FAILED`、`LOCK_LOST`、`MINECRAFT_SAVE_FAILED`、`RCON_UNAVAILABLE`、`GRACEFUL_RUNTIME_STOP_FAILED`、`MINECRAFT_STOP_TIMEOUT`、`EC2_STOP_FAILED`、`EC2_STOP_TIMEOUT`、`DNS_DELETE_FAILED`、`DNS_INSYNC_TIMEOUT`、`OBSERVATION_FAILED`を区別する。Desired更新後のfailureはDesired STOPPEDを戻さず、fresh Reconcile後にowned terminal cleanupを試みる。

D-078によりfilesystem preflightはread-onlyである。Data EBS上のexact `.rcon-cli.env`と`.rcon-cli.yaml`はroot:root、0644、regular/non-symlink、size 0、nlink 1のときだけknown Docker backing placeholderとして許容する。running時はさらにcanonical `wishicraft-host-runtime` / `minecraft` containerのDocker inspectで、password bindがexact source/destinationかつRO、生成config 2件がexact source/destinationかつRWで各1件であることを要求する。対応する`/run/wishicraft/rcon-cli.*`はruntime UID/GID、0600、regular/non-symlinkでなければならない。STOPはplaceholderを削除・truncate・置換せず、unknown/missing/duplicate/non-zero/mode・owner不一致をfail closedする。container stopped時もstrict zero-size placeholderはknown managed artifactとして許容する。

Phase 1の直接Java/systemd操作はas-builtとして維持する。Phase 2以降はSSMから許可済みHost Runtime interfaceを呼び、Host Runtimeがcontainer-localなitzg/runtime interfaceへ接続する。以下のCLI名とpayloadは旧案を含むため、Phase 3以降はPhase 2 Host Runtimeのsystemd unit、Docker/Compose、itzg containerを観測・操作するinterfaceへ読み替える。

実装言語はPythonを基本とする。

### 共通CLI規則

```text
--game-id <validated-id>
--operation-id <operation-id>
--json
```

- stdoutはJSON結果専用。
- 診断ログはstderrまたはsystemd journalへ出す。
- exit code 0は契約上の成功。
- exit code非0でもstdoutに構造化errorを出す。
- 任意パス引数を受け付けない。

### `probe_game.py`

```bash
python /opt/minecraft-control/probe_game.py \
  --operation-id op-... \
  --json
```

Output data:

```json
{
  "service_state": "active",
  "protocol_state": "ready",
  "active_game_id": "game-vanilla-main",
  "player_count": 2,
  "minecraft_version": "...",
  "pid": 1234,
  "data_volume_mounted": true
}
```

### `start_game.py`（再設計対象）

```bash
python /opt/minecraft-control/start_game.py \
  --game-id game-vanilla-main \
  --operation-id op-... \
  --json
```

責務:

- game resolver
- data volume確認
- 別game稼働確認
- runtime metadata設定
- desired stateをitzg入力へmapping/apply
- Host Runtime経由のcontainer start要求
- 起動要求まで

READY待機はStep Functions/reconcile側が行う。

### `stop_game.py`（再設計対象）

引数:

```text
--game-id
--operation-id
--mode normal
```

責務:

- active game一致確認
- container-local command pathによるsave
- itzg/runtimeへのgraceful stop要求
- process終了待機
- runtime情報更新

通常モードで保存失敗した場合、強制停止しない。

### `backup_game.py`

Input追加:

```text
--backup-id
--destination-s3-uri
```

責務:

- 保存済みデータ確認
- staging archive作成
- checksum
- S3 upload
- manifest出力

## 15. Runtime State File

例:

```json
{
  "schema_version": 1,
  "active_game_id": "game-vanilla-main",
  "current_operation_id": "op-...",
  "minecraft_pid": 1234,
  "started_at": "2026-07-23T00:00:00Z",
  "last_successful_start_operation_id": "op-..."
}
```

書き込みは一時ファイルへ出力後、renameで原子的に置換する。

DynamoDBの代替正本ではなく、実アクティブゲームを確認する観測材料として使用する。

## 16. lifecycle / systemd契約

Phase 1の直接起動unit名:

```text
minecraft.service
minecraft-heartbeat.service
minecraft-heartbeat.timer
```

`minecraft.service`はPhase 1 as-builtの契約である。Phase 2以降はsystemd、Docker/Compose、itzgが独立にrestartしないよう、`wishicraft-host-runtime.service`とHost Runtimeをcontainer lifecycle ownerとする。systemdはmount後の起動・停止順序を統括し、Compose restart policyは`no`、各stop timeoutは`config/stages/dev.yaml.host_runtime.timeouts`を正本とする。Discord入力やDynamoDB文字列を直接`ExecStart`やshellへ埋め込まない。

### Desired state mapping / apply（Phase 2で確定）

- logical desired stateの正本はControl Planeが保持する。
- mapping層はitzgの公開environment/file/command interfaceだけを生成し、Minecraft内部ファイルを直接編集しない。
- boot-time configurationとrunning serverへのruntime operationを明示的に分類する。
- 保存済みdesiredとrunning serverへ反映済みのapplied stateを同一視しない。
- RCON等の管理portはhostへpublishせず、command pathはhost-local / container-localに閉じる。
- command認可はControl Plane、secret injectionはHost Runtime、Minecraft固有command実行はitzg/runtimeが担当する。

desired/rendered/applied revisionの概念、active game observation、read-only command adapterは確定済みである。Phase 4のwrite-side CAS詳細、Phase 5/6のmutation command adapter、RCON/secret受渡しは未決定であり、本節から推測しない。

### Phase 2a canonical boot-time artifact

Phase 2aのrendererはGit管理lock、operator EULA gate、観測済みnumeric UID/GIDから、決定的なCompose YAML、runtime environment、canonical JSON manifestを生成する。

- `VERSION=26.2`、`TYPE=VANILLA`、Java 25 release image + digestを必須とする。
- `LATEST`、`SNAPSHOT`、digestなしimageを拒否する。
- `/srv/minecraft/games/game-vanilla-main/server`だけをcontainer `/data`へbind mountする。
- secret実値、RCON password、secretの単純hashをartifactまたはrender digestへ含めない。
- manifestは非secret artifactそれぞれのSHA-256を持ち、canonical JSON自体のSHA-256をrender digestとする。
- UID/GIDは既存data EBSのread-only観測値を引数として要求し、stage設定のnullを推測で補完しない。
- Phase 2aではRCONを明示的に無効化する。container-local command pathとsecret injectionを導入する後続作業で再評価する。

apply分類は次を維持する。

| 分類 | Phase 2a |
|---|---|
| boot-time | canonical rendererとstatic artifactを実装 |
| restart-required | 分類境界のみ。Control Plane orchestrationはDeferred |
| runtime operation | 分類境界のみ。RCON/whitelist command pathはDeferred |

### Phase 2a shutdown scope

explicit save 60秒はsystemd stopの外側で将来の`stop_game` adapterが実行する。systemd `ExecStop`はCompose stopだけを包み、Composeはitzg/Minecraft graceful stopを包む。

```text
save 60
→ systemd stop 180
   → Compose grace 150
      → itzg STOP_DURATION 120
→ verification 30
→ Host wrapper 300
→ SSM 360
→ Control Plane wait 420
```

値はPhase 2 dev初期tuningであり、実測後に再評価する。通常stopはsave失敗、exit 137、SIGKILL、process/listener残存、mount不明でEC2停止へ進まない。

### Phase 2b-1 ownership migration contract

既存`server.properties`は`0:993` / `0640`であり、UID/GID drop後のitzgからはread可能だがwrite不能である。実dataへの最初のitzg起動前に、Host Runtimeは次をすべて満たす場合だけ対象一件のownerを`993:993`へ変更し、mode `0640`とcontentを維持する。

- Phase 1 Minecraft、Java/cgroup process、25565/25575/25585 listenerがすべて停止済み。
- data EBS、UUID、XFS mountが期待値と一致する。
- 対象pathがallowlist内の`server.properties`そのもの。
- regular file、non-symlink、`0:993` / `0640`、extended ACLなしが完全一致する。
- recursive chown、directory/world/他fileのownership変更、properties本文の編集を行わない。
- postflightで`993:993` / `0640`、regular/non-symlink、content digest不変を確認する。

rollback時は同じ停止・mount条件下で対象一件をcontent不変のまま`0:993` / `0640`へ戻す。これはMinecraft内部形式の管理ではなくHost RuntimeのLinux ownership migrationであり、migration後のproperties realizationはitzgの公開入力へ委譲する。

Phase 2b current memory inputはcontainer `2816MiB`、`INIT_MEMORY=1G`、`MAX_MEMORY=2G`とする。値はminimal Vanilla実測用のProvisional tuningであり、恒久的resource classではない。

## 17. Package Manifest v1

複数ゲームフェーズで正式導入する。

```yaml
schema_version: 1
package_id: create-pack
package_version: 1.0.0

server:
  type: neoforge
  minecraft_version: 1.20.1
  loader_version: "47.x"
  java_runtime: java17
  entrypoint_id: neoforge-run

runtime:
  recommended_class: large
  java_xms: 4G
  java_xmx: 6G
  ready_timeout_seconds: 900

content:
  archive_s3_uri: s3://bucket/packages/create-pack/1.0.0/package.tar.zst
  checksum_algorithm: sha256
  checksum: "..."

paths:
  world_paths:
    - server/world
    - server/world_nether
    - server/world_the_end
  backup_paths:
    - server/world
    - server/world_nether
    - server/world_the_end
    - server/config
  reset_paths:
    - server/world
    - server/world_nether
    - server/world_the_end

hooks:
  before_backup: null
  after_backup: null
  before_reset: null
  after_reset: null

client:
  required: true
  pack_name: Create Client Pack
  pack_version: 1.0.0
  distribution_note: 管理者が指定する同一構成を使用する

capabilities:
  chat_bridge:
    supported: false
    implementation: null
    protocol_version: null
```

`entrypoint_id`とhook名は許可済み実装へ解決し、manifest内の任意シェル文字列を実行しない。

## 18. Backup Manifest v1

```json
{
  "schema_version": 1,
  "backup_id": "backup-...",
  "operation_id": "op-...",
  "game_id": "game-...",
  "generation": 1,
  "backup_type": "MANUAL",
  "created_at": "2026-07-23T00:00:00Z",
  "package": {
    "package_id": "vanilla",
    "package_version": "..."
  },
  "archive": {
    "s3_uri": "s3://...",
    "size_bytes": 123456,
    "checksum_algorithm": "sha256",
    "checksum": "..."
  },
  "game_definition_s3_uri": "s3://...",
  "verified": true
}
```

## 19. Discord operation metadata

Operationへ保存するDiscord情報:

```yaml
discord:
  guild_id: string
  channel_id: string
  message_id: string | null
  interaction_id: string
  requester_user_id: string
  progress_message_kind: BOT_CHANNEL_MESSAGE
  delivery_id: string | null
  delivery_status: PENDING | DELIVERED | RETRYABLE_FAILED | FAILED | null
  delivery_attempt_id: string | null
  delivery_attempt_count: integer | null
  delivery_first_attempt_epoch: integer | null
  delivery_next_attempt_epoch: integer | null
  delivery_outcome_unknown: boolean | null
  delivery_error_code: string | null
  delivery_updated_epoch: integer | null
  delivery_source_revision: integer | null
  delivery_delivered_revision: integer | null
```

Bot Token、Interaction Tokenそのものは保存しない。

`message_id`は公開progress/result messageのOperation単位identityである。message create前後のretryやDiscord Interaction再送で別messageを無制限に作らず、未設定から一意なIDへの条件付き確定を行い、確定後は同じmessageを更新する。既存Operation schemaへdelivery属性を追加する必要がある場合は、Phase 7Dで後方互換、既存item、conditional updateを確認してからschema versionまたはoptional属性として定義する。

Discord deliveryの成功・失敗はOperationのMinecraft/AWS terminal resultと別のprojection状態である。message create/update errorによってOperationの`SUCCEEDED`/`FAILED`を変更しない。公開messageにはinternal error detail、role判定情報、Interaction Token、Bot Tokenを含めない。

Phase 7Dでは既存`discord` mapへ上記optional属性を後方互換に追加する。old Operationに属性がないことは未配送として扱うが、Discord由来OperationはAdmission transaction内でGuild/channel/Interaction identityをOperationと同時に保存する。`delivery_status`、`delivery_attempt_id`、attempt countを条件付き更新し、別workerのclaim、terminal delivery、他Operationのmessage IDを上書きしない。これらはdelivery projection metadataであり、Operation `status/result/error`の正本ではない。

通常message createはOperation IDから導出した固定25文字`nonce`と`enforce_nonce=true`を必須とする。create成功後・`message_id`保存前failureは同じevent/nonceで回収する。Discordが保証する直近数分の重複排除を無期限保証と解釈せず、成否不明の回復は30秒以内だけ許可する。期限後、保存済みmessageの404、認証/認可失敗では自動的に別messageを作らない。

Phase 7E以降のSTART/STOP Operationは`progress_revision: integer`を持つ。Admission時は0で、公開対象の`current_step`またはterminal statusを更新する同一conditional write/transactionで1増やす。Stream deliveryはeventのrevisionをsource identityとし、current Operationが異なるrevisionならstale eventをno-opにする。Discord metadata CASは`delivery_source_revision`をclaimし、成功時だけ`delivery_delivered_revision`を進める。metadata-only updateは`progress_revision`を変更しないため公開deliveryを再起動しない。既存属性のないold itemは更新時に0から開始できる後方互換な`if_not_exists`を使用する。

## 19.1 Phase 7 MVP Interaction contract

- command schemaのGit正本`config/discord/commands.v1.json`は`/mc status`、`/mc start`、`/mc stop`だけを定義する。
- HTTP API v2 eventの`body`は、`isBase64Encoded=true`ならstrict base64 decodeし、falseなら受信文字列のUTF-8 bytesとする。JSON objectへparseしてから署名用bodyを再構築しない。`X-Signature-Timestamp || raw body`をEd25519署名対象とし、署名検証をparse・authorization・side effectより先に行う。
- PINGはPONGを返す。APPLICATION_COMMANDはinteraction/application/guild/channel/command/member rolesをstrictに検証し、unsupported interaction、unknown/duplicate option、欠落member/rolesを拒否する。error responseはinternal detailを含めない。
- Phase 7Bの認証・認可済みcommand responseはephemeral type 4で、Control Plane Operationを受付けていない事実を明示する。このsliceはAdmission、Reconcile、State Machine、DynamoDB、EC2、SSM、Route 53を呼ばない。Phase 7C以降でAdmissionへ接続した時点からdeferred responseを使用する。
- Phase 7CではSTATUSだけを既存Admission Lambdaへ`RequestResponse`で渡し、idempotency keyを`discord:<interaction_id>`とする。受付成功後はephemeral Deferred Channel Message responseを返す。START/STOPはPhase 7Bの未受付responseを維持する。
- Phase 7E/7FではSTART/STOPも同じAdmission Lambdaへ同じkey contractで渡す。Admission成功後はtype 4 ephemeral ACKを返し、progress/finalはInteraction tokenではなくOperation単位の通常Bot messageへ投影する。
- STOPの公開stepは`ADMITTED`、`DESIRED_STOPPED`、`HOST_RUNTIME_STOPPING`、`EC2_STOPPING`、`ENDPOINT_CLEANUP`とterminal statusから安全にrenderする。これは表示projectionであり、save、runtime stop、EC2 stop、DNS、final Reconcileのsuccess判定をDiscordへ移さない。
- STATUS admission transactionのOperations INSERTを`NEW_IMAGE` Streamでasync executorへ渡す。filterはINSERTかつ`operation_type=STATUS`、batch size 1とし、executor input identityは保存済み`operation_id`だけとする。同じInteraction retryは既存Operationを返すため新規stream recordを作らない。
- executorはOperationがSTATUS、lock NULL、PENDING/RUNNINGであることをconsistent readし、既存Reconcile Lambdaを呼ぶ。fresh SystemStateからprojectionを生成し、既存`complete_unlocked`のSTATUS/lock NULL/non-terminal条件で`result`とterminal statusを同時更新する。terminal retryはno-opとする。
- Reconcile invocation/schema failureはSTATUSを`FAILED / STATUS_RECONCILE_FAILED`へterminalizeし、resultはgeneric unknown projectionとする。raw detailを保存しない。executor自身またはterminal write failureはStream retry対象とし、bounded retry後はDLQへ送る。
- idempotency keyはDiscord Interaction identityから決定的に作り、同じInteraction payloadの再送を既存Operationへ対応付ける。異なるpayloadによるkey再利用は既存Admission contractどおりrejectする。
- Command ingressはstage固定Guild、operation channel、member rolesを検証し、player roleまたはadmin roleを許可する。通常MVP commandでadmin channelを許可しない。
- START/STOPは既存のlock付きAdmissionを呼び、STATUSはLock/Current Operationなしの既存STATUS admissionを呼ぶ。
- STATUSはfresh Reconcileを行う非同期executorへ渡し、Interaction handlerはReconcile完了まで待たない。
- Deferred ResponseにInteraction Tokenを永続化せず、その後の公開progress/resultはBot channel messageへ投影する。

## 20. 設定と秘密情報の配置

### Environment variable

- stage名
- table名
- state machine ARN
- secret ID
- parameter path

### Git管理YAML

公開設定の正本:

- `config/project.yaml`
- `config/stages/<stage>.yaml`

### Parameter Store String

必要な場合だけ、CDKがYAMLまたはdeploy結果から生成した公開値をruntimeへ配布する。人間がYAMLと独立して編集する第二の正本にはしない。

例:

- deployで生成されたinstance ID
- 複数runtimeから参照するresource identifier

### Parameter Store SecureString / later Secrets Manager

- Discord Bot Token
- Discord public keyは秘密ではないが設定として管理可能
- OAuth Client Secret
- RCON secret
- session signing secret

## 21. 設定ファイルの正本

具体的な初期値は次を正本とする。

- `config/project.yaml`: project共通値、表示名、内部ID、resource prefix、FQDN
- `config/stages/<stage>.yaml`: stage別AWS、runtime、storage、Discord ID、timeout
- `config/secrets.example.yaml`: secretの実値ではなくParameter名

`null`または`TO_BE_CONFIRMED`の値を実装側で推測して埋めない。設計契約と設定値が矛盾する場合は、どちらかを暗黙に優先せずDecision候補として報告する。Parameter Store StringやLambda environmentへ配布された公開値がYAMLと異なる場合はdeploy driftとして扱い、手動値を新しい正本にしない。

Phase 1のvanilla server artifactはstage YAMLの`minecraft_distribution.server_jar_url`と`minecraft_distribution.server_jar_sha1`を正本として構築した。これはas-built履歴であり、itzg移行後のdistribution取得契約ではない。target architectureでは、deploy/基盤固定値はGit、運用中に変更するdesired stateはControl Plane store、secretはAWS secret store、Minecraft実ファイルはdata EBS上のrealization結果とする。同一キーをGitとDynamoDBの双方へ正本化してはならない。

## 22. AWSリソース命名

基本形式:

```text
wc-<stage>-<component>
```

例:

```text
wc-dev-system-state
wc-dev-operations
wc-dev-start-workflow
wc-prod-command-handler
```

全リソースへ最低限次のタグを付ける。

```text
Project = wishicraft
Stage = dev | prod
ManagedBy = cdk
Owner = project-owner
```

## 23. Phase 3 Control Plane Reconcile contract

Lambda inputは次の固定versioned objectだけを受理する。instance ID、shell、Hosted Zone、record nameはinputで上書きできない。

```json
{"schema_version":1,"operation":"reconcile"}
```

SystemState tableは`PK=system_id`のcurrent item一件を保持する。itemは`schema_version`、`environment`、`game_id`、`desired_state`、`target_instance_id`、normalized `observation`、`discrepancies`、`health`、`observation_errors`、fixed-width UTC `observed_at`を持つ。raw AWS response、raw mc-monitor JSON、stderr、MOTD/player content、secret/credentialを保存しない。

観測更新はUpdateItemを使い、`attribute_not_exists(observed_at) OR observed_at < :observed_at`を必須とする。timestampは`YYYY-MM-DDTHH:MM:SS.ffffffZ`へ正規化し、lexicographic orderとUTC chronological orderを一致させる。同一timestampも上書きせずConditionalCheckFailedで拒否し、異なる結果が同じ観測順序を共有する曖昧さを許さない。DynamoDB write failureは呼出元へ伝播する。

Route 53 observerはcanonical Hosted Zone/FQDNに対するread-only ListResourceRecordSetsだけを使う。record absent、単一A record、unexpected valuesを分離し、duplicate、Alias/unsupported shape、malformed response、API failureはunknownへfail-closedする。
