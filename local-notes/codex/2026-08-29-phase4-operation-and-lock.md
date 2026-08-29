# Wishicraft Phase 4 Operation・Lock・DynamoDB integration学習記録

> 記録対象: Phase 4前Decision確定、Game/Operation/Idempotency/Lock repository foundation、Admission Lambda、Control Plane stack更新、実DynamoDB integration、Phase 4 closeout。
>
> 主な作業日: 2026-08-29
>
> ノート作成日: 2026-08-29
>
> 用途: Phase 5のstart workflowへ進む前に、Operation受付、排他、CAS、stale recoveryがなぜこの形なのかを復習するための学習・引き継ぎnote。
>
> 正本: 本noteは学習用であり、設計・契約の正本ではない。D-074、domain model、interface contract、delivery planを優先する。
>
> 機密保護: AWS credential、SSO token/cache、password、secret本文、生environmentは記載しない。AWS Account ID、role ARN、request ID等も学習に不要な箇所では省略・一般化する。

## 1. 今回の目的と到達点

Phase 3までにWishicraftは、実状態を観測してcurrent `SystemState`へ保存できるようになった。Phase 4の目的は、その上にstart/stop等のwrite-side workflowを安全に載せるための受付・履歴・排他基盤を作ることだった。

今回完成したものは次である。

- canonical initial Gameの条件付き登録
- Games / Operations / Idempotency / Locksの4 table
- versioned Admission Lambda
- DynamoDB transactionによるatomic admission
- `operation_id`とacquisition固有`lease_id`による所有権
- lease verify / renew / release
- Desiredの`desired_revision` CAS
- Observedの`observed_at` freshnessとの分離
- fresh Reconcileを必須とする明示stale recovery
- STATUS用non-lock admissionと専用terminal更新
- dev実DynamoDB integration

Phase 5のStep Functions、EC2 start、Host Runtime start、Minecraft start、DNS writeは実装・実行していない。Phase 4は副作用を実行するworkflowではなく、副作用を安全に開始できるか判断するfoundationである。

## 2. 利用者が依頼・判断したこと

### 2.1 Phase 4前の3つのDecision

利用者のhuman reviewにより、次がAcceptedになった。

1. Lockのlogical ownerは`operation_id`とする。
2. current lease possession proofとしてacquisitionごとに一意な`lease_id`を発行する。
3. Desired、Observed、Operation ownershipのversion/freshnessを分離する。
4. stale Operationをlease expiryだけで自動FAILED化しない。

Lockは概念上、次を保持する。

```text
resource/system identity
owner_operation_id
lease_id
lease_expires_at
```

renew、release、protected side effect直前の確認には次をすべて要求する。

```text
owner_operation_id == caller operation_id
lease_id == caller lease_id
lease_expires_at >= now
```

### 2.2 AWS integrationの安全境界

利用者はControl Plane stackだけの更新を許可し、Phase 1/Target stack、EC2、EBS、snapshot、SG、DNS、SSM Run Command、Minecraft/Host Runtimeを変更しないよう指定した。

実integrationはDynamoDBとAdmission/Reconcile Lambdaだけを使い、runtime side effectを発生させないOperation受付として行った。

## 3. OperationとLockを分けて考える

### 3.1 Operationは「論理的な仕事」

`operation_id`はユーザー要求から生じた一つの論理Operationを識別する。

Operationは次の情報を持つ。

- 何を要求したか
- 誰が要求したか
- 現在のstatus/step
- timeout/deadline
- terminal result/error
- Lock取得時の`lease_id`

同じOperationをworkflow executorが再実行しても、logical identityは同じ`operation_id`である。

### 3.2 Leaseは「現在実行してよいexecutorの証明」

`operation_id`だけでは、同じOperationを処理する古いexecutorと新しいexecutorを区別できない。

例えば次の競合があり得る。

```text
executor A acquires lease-1
executor A becomes delayed
lease-1 expires
explicit recovery / new acquisition creates lease-2
executor A resumes
```

ここで`operation_id`だけを確認すると、Aも現在のownerに見えてしまう。`lease_id`も照合すれば、古いAは`lease-1`なので拒否できる。

したがって役割は次のように分かれる。

| identity | 意味 |
|---|---|
| `operation_id` | どの論理Operationに属するか |
| `lease_id` | 現在のlease acquisitionを所持しているexecutorか |

この分離は、再試行やdistributed executorを扱ううえで重要なfencingに近い考え方である。ただしlease tokenの大小で順序付ける方式ではなく、保存されたexact IDとの一致で現在の所持を証明する。

## 4. Atomic admission

### 4.1 なぜ複数itemを一transactionにするのか

競合Operationのadmissionでは、次を一体として作る必要がある。

```text
Put Idempotency if absent
Put Operation if absent
ConditionCheck active Game
Put Lock if absent
Update SystemState.current_operation_id if absent/NULL
```

個別writeにすると、途中失敗で次の不整合が起こり得る。

- IdempotencyだけありOperationがない。
- OperationはあるがLockがない。
- LockはあるがCurrent Operationが別の値である。
- 競合を拒否したのにpartial Operationが残る。

`TransactWriteItems`を使えば、全条件が成立したときだけ全itemが反映される。1つでも失敗すれば何も作らない。

### 4.2 STATUSの例外

STATUSは状態変更を伴わないため、Lockと`current_operation_id`を使用しない。

```text
Put Idempotency
Put STATUS Operation
ConditionCheck active Game
```

実AWSでは競合Lockが存在する間にもSTATUS admissionが成功し、LockとCurrent Operationが変化しないことを確認した。

STATUS terminal更新もlock-owned completionと混用しない。次を条件にする専用repository pathを追加した。

```text
operation_type == STATUS
lock_name is DynamoDB NULL
status in PENDING/RUNNING
```

## 5. Idempotency

Idempotency keyは、外部要求の再送が別Operationを作ることを防ぐ。

### 5.1 同じkey・同じpayload

保存済みIdempotency recordの次の属性を比較する。

- operation type
- request source
- target Game

すべて一致すれば、既存`operation_id`を返す。

```text
created = false
operation_id = existing operation
```

新しいOperationやLockは作らない。

### 5.2 同じkey・異なるpayload

同じkeyをSTARTとSTOP等で使い回した場合はconflictとして拒否する。既存Operationを別の意味へ読み替えない。

### 5.3 実AWSで確認したatomicity

実integrationでは次を確認した。

- same key / same payloadは同じOperationを返した。
- same key / different payloadは拒否された。
- Lock保持中の別Operationは拒否された。
- 拒否されたrequestのIdempotency/Operation partial itemは0件だった。
- existing Lockと`current_operation_id`は上書きされなかった。

## 6. Desired revision CASとObserved freshness

### 6.1 3つの独立した軸

SystemState itemには異なる責務の属性が共存する。

| 領域 | 競合制御 |
|---|---|
| Desired | `desired_revision` |
| Observed | `observed_at` |
| Operation ownership | `current_operation_id` |

これらを1つのglobal versionで保護すると、ReconcileのObserved更新とworkflowのDesired更新が不要に競合する。

### 6.2 Desired CAS

Desired mutationは次の形にする。

```text
read desired_revision = N
conditional update where desired_revision == N
write desired_revision = N + 1
```

operation-owned pathでは、さらに次を要求する。

```text
current_operation_id == caller operation_id
```

実AWSではrevision 0から1への更新だけ成功し、古いexpected revision 0の再利用は`ConditionalCheckFailedException`になった。

### 6.3 Observed freshness

ReconcileはObserved属性だけを更新し、`observed_at`が保存済み値よりstrictly newerの場合だけ受理する。Desiredを上書きしない。

実integrationではDesired CAS前後で`observed_at`が変化しないことを確認した。その後のfresh ReconcileではObservedだけが新しい時刻へ進み、Desired revisionは保持された。

この分離により、将来の`rendered_revision`、`applied_revision`もDesired/Observedを混同せず追加できる。

## 7. Stale Operation recovery

### 7.1 Lock expiryはOperation failureではない

leaseやOperation deadlineが切れても、外部副作用が次のどこにいるかは分からない。

```text
未開始
実行途中
AWS側では成功済み
Host Runtime側では成功済みだがControl Plane未記録
```

したがって、時刻だけを根拠にOperationをFAILED化したりLockをtakeoverしたりすると、二重副作用を起こし得る。

### 7.2 採用したflow

```text
Operation becomes stale candidate
-> normal conflicting admission remains blocked
-> fresh Reconcile observes real state
-> explicit recovery decides terminal result
-> transactionally update old Operation
-> delete exact owned Lock
-> remove exact current_operation_id
-> next Operation may be admitted
```

recovery transactionは少なくとも次を条件にする。

- Operationの保存済み`timeout_at`が期待値と一致
- Lockのresource / owner operation / leaseが一致
- SystemStateの`current_operation_id`が一致
- SystemStateの`observed_at`がrecovery判断に使ったfresh observationと一致

expired Lockの削除自体は許可するが、exact owner/lease照合は外さない。

### 7.3 実AWS synthetic integration

runtime side effectを起こさず、repository-defined schema/pathで期限切れのsynthetic Operationをadmitした。

確認できたこと:

- stale Lockがあっても通常admissionは自動takeoverせずblockした。
- fresh evidenceなしのrecoveryは拒否された。
- stopped Targetのfresh Reconcile後だけrecoveryが成功した。
- Operationは`TIMED_OUT`へterminal化された。
- exact Lockと`current_operation_id`が同じtransactionで整理された。
- 古いlease proofは以後ownershipを証明できなかった。
- cleanup後の次Operationはadmitできた。

## 8. 実DynamoDB integrationで分かったこと

### 8.1 Mockで通ってもIAM authorizationは別問題

unit testのfake DynamoDBはtransaction shapeを検証できるが、IAM policy evaluationは行わない。CDK synthもpolicy JSONを生成するだけで、実際のDynamoDB API authorizationまでは証明しない。

初回Admission Lambda実行は次のerrorになった。

```text
AccessDeniedException when calling the TransactWriteItems operation:
... is not authorized to perform: dynamodb:PutItem
on resource: ...:table/wc-dev-idempotency
because no identity-based policy allows the dynamodb:PutItem action
```

最初のpolicyは概念上次だけだった。

```text
dynamodb:GetItem
dynamodb:TransactWriteItems
```

しかしtransaction内ではPut/Update/ConditionCheckを行う。実AWS authorizationでは内部item actionに対応する権限も必要だった。

### 8.2 修正した最小権限

Admission roleへ次を追加・限定した。

```text
dynamodb:ConditionCheckItem
dynamodb:GetItem
dynamodb:PutItem
dynamodb:TransactWriteItems
dynamodb:UpdateItem
```

Resourceは次の5 table ARNだけである。

- SystemState
- Games
- Operations
- Idempotency
- Locks

追加しなかった権限:

- EC2 start/stop/modify
- SSM SendCommand
- Route 53 write
- EBS/SG mutation
- secret read
- IAM mutation

重要な学びは、「高水準API名だけを許可すれば十分」と推測せず、実際にtransactionへ含める各DynamoDB actionとresourceをIAMでも対応させることである。

### 8.3 IAM failure時もtransactionはpartial writeしなかった

AccessDeniedはtransaction開始時に失敗し、Idempotency/Operation/Lock/Current Operationは作られなかった。同じintegration keyでIAM修正後に再実行できた。

これはatomicityの重要な実証だが、すべてのfailure modeを同じ結果と推測してはいけない。各repositoryはtransaction failure後にexisting Idempotencyをconsistent readし、同じrequestのraceか真のconflictかを分類する。

### 8.4 DynamoDB reserved word

Operation terminal updateで`error`属性をExpressionへ直接書いていた。実DynamoDBでreserved keywordとして扱われ得るため、次のaliasへ修正した。

```text
ExpressionAttributeNames:
  #status -> status
  #error  -> error
```

read-only確認時のProjectionExpressionでも`error`を直接指定すると、実際に次のerrorになった。

```text
ValidationException: Invalid ProjectionExpression:
Attribute name is a reserved keyword; reserved keyword: error
```

この経験から、write pathだけでなく運用queryでもreserved word aliasが必要だと分かる。

### 8.5 NULLとattribute absence

formal schemaのnullable fieldを初期itemから省略すると、`attribute_not_exists`とDynamoDB `NULL`が混在する。条件式や将来のreaderが複雑になるため、Operation/Game/Idempotencyのformal nullable fieldsは明示`NULL`としてserializeするよう補完した。

一方、`current_operation_id`の解放はattribute removalを使用する。ここは「値がNULL」と「属性がない」の両方をadmission条件で安全に扱う。

## 9. Initial Game registration

初期GameはdeployやLambda cold startで自動作成せず、固定admin pathから明示登録した。

```sh
AWS_PROFILE=wishicraft-dev \
uv run --python 3.12 --with boto3 \
python -m wishicraft.game_admin --stage dev
```

repositoryは次を使う。

```text
PutItem
ConditionExpression = attribute_not_exists(game_id)
```

結果:

- 初回登録: success
- 同一payload再登録: conditional rejection、既存item不変
- 異なるpayload上書き: conditional rejection、既存item不変

Game recordにはlogical desired stateだけを保存し、itzg image、Java、memory、Docker/Compose/AMI等のphysical runtime lockを複製しない。

## 10. 実行した重要なコマンドと目的

### 10.1 Git / repository状態

```sh
git rev-parse HEAD
git rev-parse origin/main
git status --short
git diff --name-status
```

目的は中断時の未commit成果を保持し、base、origin、working treeを復元することだった。

### 10.2 Stackごとのcredential付きdiff

```sh
AWS_PROFILE=wishicraft-dev npx --no-install cdk diff MinecraftStack-dev \
  --context stage=dev --context phase=1 --context deployment=phase1

AWS_PROFILE=wishicraft-dev npx --no-install cdk diff MinecraftTargetStack-dev \
  --context stage=dev --context phase=2 --context deployment=target

AWS_PROFILE=wishicraft-dev npx --no-install cdk diff WishicraftControlPlaneStack-dev \
  --context stage=dev --context phase=4 --context deployment=control-plane
```

結果:

- Phase 1: 既知historical replacement差分のみ。deployしなかった。
- Target: diff 0。deployしなかった。
- Control Plane: Phase 4 tables、Admission Lambda/IAM/LogGroup、共有source asset更新だけ。

### 10.3 Control Planeだけのdeploy

```sh
AWS_PROFILE=wishicraft-dev npx --no-install cdk deploy \
  WishicraftControlPlaneStack-dev \
  --context stage=dev --context phase=4 --context deployment=control-plane \
  --require-approval never
```

明示stack名を使い、`cdk deploy --all`は使用しなかった。

### 10.4 Admission Lambda invocation

conceptual payloadは次である。

```json
{
  "schema_version": 1,
  "operation": "admit",
  "operation_type": "STOP",
  "idempotency_key": "phase4-integration-...",
  "requested_by": "ADMIN"
}
```

STOPを使ったが、Phase 5 workflowは存在せず、AdmissionはDynamoDB transactionだけを実行するため、EC2/Host Runtime/Minecraft stop side effectは発生しない。

### 10.5 最終validation

```sh
.venv/bin/pytest tests/unit/test_operation.py \
  tests/unit/test_game_admin.py \
  tests/unit/test_stack.py \
  tests/unit/test_system_state.py -q

.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src infrastructure tests
bash -n <all repository shell artifacts>
git diff --check
```

stack synthも明示contextで順番に実行した。

```sh
npx --no-install cdk synth MinecraftStack-dev \
  --context stage=dev --context phase=1 --context deployment=phase1

npx --no-install cdk synth MinecraftTargetStack-dev \
  --context stage=dev --context phase=2 --context deployment=target

npx --no-install cdk synth WishicraftControlPlaneStack-dev \
  --context stage=dev --context phase=4 --context deployment=control-plane
```

## 11. 変更した主なファイル

Phase 4 repository foundation commitで追加・変更した主な対象:

- `src/wishicraft/game.py`
- `src/wishicraft/game_admin.py`
- `src/wishicraft/operation.py`
- `src/wishicraft/admission_lambda.py`
- `src/wishicraft/system_state.py`
- `infrastructure/stacks/control_plane_stack.py`
- `tests/unit/test_game_admin.py`
- `tests/unit/test_operation.py`
- `tests/unit/test_admission_lambda.py`
- `tests/unit/test_system_state.py`
- `tests/unit/test_stack.py`
- `README.md`
- `docs/04_domain_and_state_model.md`
- `docs/05_data_and_interface_contracts.md`
- `docs/06_delivery_plan.md`
- `docs/09_decisions_and_backlog.md`

Phase 4 AWS closeout commit:

```text
ee64dc7 docs: close out Phase 4 AWS integration
```

## 12. 検証結果

### 12.1 Repository

```text
focused tests: 41 passed
full pytest: 372 passed
Ruff lint: success
Ruff format check: success, 88 files formatted
mypy: success, 63 source files
shell syntax: success
git diff --check: success
3 stack synth: success
```

Target synthには固定AMIに対するCloudFormation validation warningが出たが、D-062の固定platform lockに基づく既知warningであり、synth failureではない。

### 12.2 CI

```text
GitHub Actions CI run 71
head: ee64dc7fa94a2fcbc43f863923c9201755b52f32
result: success
```

### 12.3 DynamoDB integration後の状態

```text
Games: canonical item 1
Operations: integration history 4
Idempotency: matching history 4
Locks: 0
SystemState.current_operation_id: absent
SystemState.desired_state: STOPPED
SystemState.desired_revision: 1
Observed: fresh stopped observation
```

Operation/Idempotency TTLはDeferredなので、integration recordsをraw deleteせず、明示的なintegration keyを持つ履歴として保持した。

### 12.4 AWS安全状態

```text
Phase 1 EC2: stopped
Target EC2: stopped
Data EBS: Target attached, DeleteOnTermination=false
Snapshot: completed/retained
Target SG ingress: 0
DNS A record: absent
Minecraft: stopped
Phase 1 stack: unchanged
Target stack: unchanged
Control Plane stack: UPDATE_COMPLETE
Target向けSSM Run Command during integration: 0
```

## 13. Phase 4で得た設計上の学び

1. **Logical ownershipとcurrent possessionは別物である。** `operation_id`だけでは古いexecutorを排除できず、acquisition固有`lease_id`が必要になる。
2. **Lock expiryは事実の一部でしかない。** 外部副作用の結果はfresh observationなしに決められない。
3. **Admissionのatomicityはworkflow開始前に完成させる。** partial ownership stateを後からrepairする設計にしない。
4. **Idempotencyはkey存在だけでなくpayload一致を検証する。** 同じkeyを別要求へ流用させない。
5. **Desired/Observed/Operationは更新主体が違う。** 同一global versionより、責務別CAS/freshnessの方が不要な競合を避けられる。
6. **DynamoDB TTLは排他解放機構ではない。** 論理lease expiryとphysical item deletionを分離する。
7. **MockとsynthではIAMの実効性まで証明できない。** dev実integrationで最小権限を確認する必要がある。
8. **DynamoDB expressionのreserved wordは運用queryにも影響する。** updateだけでなくprojectionでもaliasを使う。
9. **NULLとabsenceを意図的に使い分ける。** schemaのnullable fieldとownership解放の意味を混同しない。
10. **Phase foundationとruntime side effectを分離すると安全に実測できる。** STOP Operationをadmitしても、Phase 5/6 workflowがなければruntime mutationは起きない。

## 14. 残っている作業

Phase 4は正式closeout済みで、次はPhase 5「安全なstart workflow」である。

Phase 5前またはslice開始時に確認する項目:

- fixed write-side Host Runtime operation adapterのControl Plane contract
- protected side effect直前のlease verification配置
- Wait/poll中のrenewとProvisional値900秒/120秒の妥当性
- Step Functions failure pathでのfresh Reconcileとowned cleanup
- START成功条件: runtime READY、active Game一致、endpoint/DNS一致
- RCON client/libraryとcontainer-local command pathのDecision期限

Deferredのまま維持するもの:

- Operation retention / TTL
- Idempotency retention / TTL
- Phase 1/Data EBS ownership retirement
- backup
- Package/Mod/Plugin
- Discord/chat integration

Phase 5で、Admissionを迂回してState Machineを直接開始してはいけない。CLI/integrationでも、まず既存Operation admission contractを通す。
