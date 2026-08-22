# 05. Data and Interface Contracts

- **文書状態:** Canonical
- **最終更新:** 2026-07-29

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

```yaml
system_id: wishicraft-main
schema_version: 1
version: 42

desired_state: STOPPED | RUNNING
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
- ReconcileはObserved State、Health、Discrepancies、observed_atだけを更新する。
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
  class: initial
  java_runtime: corretto-25-headless
  java_xms: 1G
  java_xmx: 3G
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
  java_runtime: string
  java_xms: string
  java_xmx: string
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
operation_id: string
owner: string
acquired_at: timestamp
expires_at: epoch_seconds
lease_version: integer
updated_at: timestamp
cleanup_ttl: epoch_seconds
```

`cleanup_ttl`は物理削除用であり、有効性は`expires_at`で判断する。


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
{
  "schema_version": 1,
  "system_id": "wishicraft-main",
  "operation_id": "op-...",
  "reason": "STATUS_COMMAND",
  "force_probe": true
}
```

`operation_id`は定期reconcileではnullを許可する。

### Output

```json
{
  "schema_version": 1,
  "system_id": "wishicraft-main",
  "observed": {
    "ec2_state": "running",
    "public_ipv4": "203.0.113.10",
    "dns_target_ipv4": "203.0.113.10",
    "connection_endpoint_state": "ready",
    "ssm_state": "online",
    "minecraft_service_state": "active",
    "minecraft_protocol_state": "ready",
    "active_game_id": "game-vanilla-main",
    "player_count": 2,
    "observed_at": "2026-07-23T00:00:00Z"
  },
  "ready": true,
  "health": "HEALTHY",
  "discrepancies": []
}
```


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
3. `Locks`へ期限切れ判定付きPut/Update
4. `SystemState.current_operation_id`をnull条件付きUpdate

同じidempotency keyが既に存在する場合は、保存済みoperation IDを返し、新しいOperationを作成しない。

成功後、Step Functionsを`operation_id`と同じexecution nameで開始し、execution ARNをOperationへ保存する。開始失敗時はOperationをFAILEDへ更新し、所有者条件付きでLockとCurrent Operationを解除する。Idempotency itemは失敗履歴との対応を維持するため削除せず、同じ要求の再送には既存の失敗結果を返すか、利用者が新しいrequest IDで再実行する。

### STATUS admission

STATUS Operationは`Idempotency`と`Operations`だけを条件付き作成し、`Locks`と`SystemState.current_operation_id`を変更しない。定期reconcileはOperation admissionを使用しない。

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

Phase 1の直接Java/systemd操作はas-builtとして維持する。Phase 2以降はSSMから許可済みHost Runtime interfaceを呼び、Host Runtimeがcontainer-localなitzg/runtime interfaceへ接続する形へ再設計する。以下のCLI名とpayloadはPhase 2で置換可否を決める既存案である。

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

`minecraft.service`はPhase 1 as-builtの契約である。Phase 2以降はsystemd、Docker/Compose、itzgが独立にrestartしないよう、Host Runtimeをcontainer lifecycle ownerとする。systemdはmount後の起動・停止順序を統括し、Composeのrestart policyはControl Planeの停止意図を打ち消さないものとする。具体的unit、restart値、stop timeoutはDecision Neededである。Discord入力やDynamoDB文字列を直接`ExecStart`やshellへ埋め込まない。

### Desired state mapping / apply（Phase 2で確定）

- logical desired stateの正本はControl Planeが保持する。
- mapping層はitzgの公開environment/file/command interfaceだけを生成し、Minecraft内部ファイルを直接編集しない。
- boot-time configurationとrunning serverへのruntime operationを明示的に分類する。
- 保存済みdesiredとrunning serverへ反映済みのapplied stateを同一視しない。
- RCON等の管理portはhostへpublishせず、command pathはhost-local / container-localに閉じる。
- command認可はControl Plane、secret injectionはHost Runtime、Minecraft固有command実行はitzg/runtimeが担当する。

具体的なdesired/applied schema、idempotency、apply result、command adapter、secret受渡しはDecision Neededであり、本節から推測しない。

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
```

Bot Token、Interaction Tokenそのものは保存しない。

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
