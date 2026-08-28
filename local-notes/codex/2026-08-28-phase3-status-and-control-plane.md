# Wishicraft Phase 3 status observation・Control Plane persistence・AWS closeout記録

> 記録対象: Git housekeeping、Phase 3のEC2/SSM/Host Runtime/Minecraft protocol/active game/endpoint observation、Reconcile、SystemState persistence、独立Control Plane stack、stopped Target AWS integration、Phase 3 closeout。
>
> 主な作業日: 2026-08-26〜2026-08-28
>
> ノート作成日: 2026-08-28
>
> 用途: 利用者の依頼、Codexの判断、安全境界、実装、失敗と修正、検証結果を後から学び直すためのローカルノート。
>
> 機密保護: AWS credential、SSO token/cache、password、secret本文、生environment、`server.properties`/world本文、MOTD/player情報は記載しない。

## 1. セッション全体の流れ

このセッションでは、Phase 2 closeout後のGit整理から始め、Phase 3を小さいvertical sliceに分けて完成させた。

1. local-onlyの学習note commitと未追跡noteを整理した。
2. stopped EC2 observationへSSM managed-node statusを追加した。
3. versioned read-only Host Runtime probe、SSM Run Command adapter、strict parserを追加した。
4. container-local Minecraft Java protocol pingをREADYの必須条件にした。
5. Host Runtimeの明示metadataとDocker bindからactive game identityを観測し、discrepancyを導出した。
6. public/private IPv4、Route 53 A record、endpoint discrepancyを追加した。
7. Reconcile domain service、current SystemState repository、DynamoDB、Lambda、独立Control Plane stackを実装した。
8. Control Plane stackだけをdevへdeployし、stopped Targetを2回Reconcileしてcurrent state persistenceを実測した。
9. Phase 3を正式にcloseoutした。

一貫した境界は、Control PlaneがMinecraft内部fileを直接読まず、AWS adapterと固定Host Runtime probeから正規化済み事実だけを受け取ることだった。また、runtime READYとdesired stateへのconvergenceを別概念として維持した。

## 2. 利用者が依頼・質問したこと

### 2.1 RepositoryとGit housekeeping

利用者は当初申告したHEADが古いことを訂正し、local HEAD、`origin/main`、未追跡note、canonical docs/sourceへの変更有無を確認するよう依頼した。

特に次を求めた。

- local-notesだけの安全なcommitが未pushならpushする。
- `2026-08-22-itzg-design-review.md`は統合noteとの重複を確認し、独自情報がなければ削除する。
- `2026-08-23-phase2-migration-and-phase3-status.md`はcanonical docsとの整合、実施済み/未実施、secret、古い判断を精査し、問題なければ単独commit/pushする。
- canonical docsとPhase 3 sourceは変更しない。

### 2.2 Phase 3 status slices

利用者はPhase 3を次のsliceへ分け、各sliceでtest、validation、commit、push、CIまで求めた。

- stopped/running EC2とSSM managed-node status
- SSM pagination
- versioned Host Runtime read-only probe
- fixed SSM Run Command operation
- strict JSON parser/normalization
- Minecraft protocol-aware READY
- active game identity/discrepancy
- public IPv4/Route 53/endpoint discrepancy
- Reconcile/SystemState/DynamoDB/Lambda/Control Plane stack

実AWSを使うsliceでは、Phase 1をFrozenに保ち、Targetの起動/停止、Minecraftのcanonical start/stopだけを明示範囲で許可した。Control Plane sliceではTargetを起動せず、Phase 1/Target/EBS/snapshot/DNSへのwriteを禁止した。

### 2.3 中断からの復元

利用上限による中断が二度あった。

- protocol READY sliceでは、CIの`mc-monitor status help failed`確認後から再開した。
- Control Plane sliceでは、利用者が中断後にEC2を手動停止したため、Git/CI/AWSをread-onlyで復元し、未commit変更を失わず再開するよう依頼した。

復元時には、作業を推測で続けず、commit済み/未push、working tree、CI、stack/resource状態、in-progress operation、manual stopの影響を証跡から分類することが要求された。

### 2.4 Control Plane deployとPhase 3 closeout

repository実装とCI成功後、利用者は次を依頼した。

- 3 stackを明示してcredential付きCDK diffする。
- Phase 1/Targetをdeployしない。
- Control Planeが新規resourceだけでIAMがread-mostlyの場合に限り、Control Plane stackだけをdeployする。
- stopped Targetをcanonical inputでReconcileする。
- stopped instanceへSendCommandが0件であることを確認する。
- DynamoDB current item、repeated Reconcile、stale-write protection、CloudWatch log safetyを検証する。
- 実測した内容だけをdocsへ反映し、Phase 3 closeout可否を判断する。

## 3. Codexが行った主要な判断

### 3.1 正本と責務境界

設計判断は`docs/02`〜`06`、`docs/09`、itzg responsibility boundary、project/stage configを正本とした。

観測の責務は次の3層に分離した。

```text
Control Plane
  -> AWS/SSM transportと正規化
Host Runtime probe
  -> host、systemd、Docker、container、protocolのread-only観測
Minecraft/itzg
  -> Minecraft内部dataとprotocol response
```

Control Planeは`server.properties`、world、`level.dat`、logを読まない。任意shellを渡すinterfaceも作らず、「repository-packaged canonical probeを実行する」という固定operationだけを公開した。

### 3.2 Fail-closedとshort-circuit

状態を推測で正常補完せず、API/schema/identity/command failureは`unknown`、`ready=false`へ正規化した。一方、正常に存在しない状態はUNKNOWNと区別した。

```text
EC2 stopped
  -> SSM not-applicable
  -> Run Commandなし
  -> Host Runtime not-running
  -> protocol not-applicable
  -> ready=false
```

running EC2でもSSMがOnlineでなければHost Runtime probeへ進まない。SSM paginationは全pageを見てTargetを一意に解決し、0件/duplicate/malformed/token loop/API failureをUNKNOWNへ落とした。

### 3.3 READYの意味

container running、Docker health healthy、Java process、listener、logの`Done`だけではREADYにしなかった。固定container内のMinecraft Java status pingが成功し、期待versionと整合した場合だけruntime READYとした。

固定operationの概念は次である。

```sh
docker exec <expected-container> \
  mc-monitor status \
  --json \
  --host localhost \
  --port 25565 \
  --timeout 3s
```

host port publish、public 25565、DNS、RCONは不要である。raw JSON、MOTD、favicon、player sampleはControl Planeへ流さず、必要なversion/protocol/resultだけを正規化した。

### 3.4 runtime READYとactive game discrepancyを分離

active game identityはdirectory名やcontainer名から逆算せず、Host Runtime rendererがcontainerへ付与する明示Game ID/data source labelと、一意な`/data` bindをSource of Truthとした。

```text
runtime_ready = true
active_game_discrepancy = active-game-mismatch
```

は表現可能である。protocolが利用可能でもdesired gameと不一致なら、上位workflowのSTART成功条件は満たさない。しかしprotocol READY自体をfalseへ書き換えない。

### 3.5 endpoint observationとdesired lifecycleを分離

public IPv4とRoute 53は観測事実として扱い、desired/stopped contextからendpoint discrepancyを導出した。

```text
stopped + public IPv4 absent + DNS absent
  -> normal / no discrepancy

running + public IPv4 assigned + matching A record
  -> no discrepancy
```

DNS missing、wrong IP、unexpected present、public IP/DNS observation unknownは別々に表現する。Route 53 adapterはread-onlyで、record shape/API failureをUNKNOWNへfail-closedした。

### 3.6 ReconcileとLambdaの分離

Lambda handlerに観測順序やdomain判断を詰め込まず、Reconcile domain serviceを中心にした。

```text
target identity resolution
-> desired/context
-> EC2
-> conditional SSM
-> conditional Host Runtime
-> network and DNS
-> discrepancies and health
-> normalized SystemState
-> repository persistence
```

Target identityはphysical instance IDをGitへhard-codeせず、Project/Stage/Purpose tagでexactly oneを解決した。0件/複数件/API/schema failureは新しいUNKNOWN stateとして保存する。

### 3.7 current SystemStateとstale-write protection

history/event sourcing/TTL/GSI/Streamsを先行追加せず、`system_id`一件のcurrent stateとした。`observed_at`はfixed-width UTCでlexicographically sortableにし、DynamoDB ConditionalExpressionでstrictly newerだけを許可した。

```text
new observed_at > stored observed_at
```

olderだけでなくequal timestampも拒否する。新しい観測が失敗した場合はfresh UNKNOWN/ready falseを保存し、過去のREADY=trueを残さない。DynamoDB write failureだけは成功へ変換しない。

### 3.8 Deploy判断

credential付きdiffでPhase 1に既知のFrozen差分が出た。差分0と偽らず、次を確認した。

- AMI parameter再解決によるEC2 replacement候補
- historical UserData差分
- 移行済み旧VolumeAttachment差分

これらはPhase 3由来でなく、Control Planeとcross-stack dependencyがないため、Phase 1をdeployせずControl Planeだけをdeploy可能と判断した。Target diffは0、Control Plane diffは新規DynamoDB/LogGroup/IAM/Lambdaだけだった。

## 4. 実行した重要なコマンドと目的

以下は代表例である。ID/ARN/credential/secret値を出力するcommandや生payloadは省略または一般化している。

### 4.1 Git状態と差分の復元

```sh
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git status --short --branch
git diff --name-status
git diff --cached --name-status
git log --oneline 58de93c..HEAD
```

目的:

- 中断前成果を消さず、commit済み/未push/unstaged/untrackedを分類する。
- local mainとorigin/mainの差を確認する。
- 意図しないcanonical docs/Phase 1/Target変更を見つける。

### 4.2 Repository validation

```sh
.venv/bin/pytest <focused test files>
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src infrastructure
find infrastructure -type f -name '*.sh' -exec bash -n {} \;
git diff --check
```

目的:

- domain、adapter、parser、repository、Lambda、CDK regressionを検証する。
- Python lint/format/typeとshell syntaxを確認する。
- trailing whitespace等のpatch品質を確認する。

### 4.3 Stackごとのsynth

実際のapp/contextでstack名を明示し、順番に実行した。

```sh
.venv/bin/cdk synth MinecraftStack-dev \
  --context stage=dev --context phase=1 --context deployment=phase1

.venv/bin/cdk synth MinecraftTargetStack-dev \
  --context stage=dev --context deployment=target

.venv/bin/cdk synth WishicraftControlPlaneStack-dev \
  --context stage=dev --context deployment=control-plane
```

目的:

- `--all`を避け、Phase 1/Target/Control Planeを個別に検証する。
- context違いでstackがassemblyに存在しない問題を見落とさない。

### 4.4 Credential付きCDK diff

```sh
npx --no-install cdk diff MinecraftStack-dev \
  --profile wishicraft-dev \
  --context stage=dev --context phase=1 --context deployment=phase1 \
  --change-set true --no-color

npx --no-install cdk diff MinecraftTargetStack-dev \
  --profile wishicraft-dev \
  --context stage=dev --context deployment=target \
  --change-set true --no-color

npx --no-install cdk diff WishicraftControlPlaneStack-dev \
  --profile wishicraft-dev \
  --context stage=dev --context deployment=control-plane \
  --change-set true --no-color
```

目的:

- CloudFormation change set相当でreplacement/modify/deleteを確認する。
- Frozen Phase 1とTargetをdeploy対象から隔離する。
- Control Planeが新規かつ想定resourceだけであることを確認する。

### 4.5 Control Planeだけのdeploy

```sh
npx --no-install cdk deploy WishicraftControlPlaneStack-dev \
  --profile wishicraft-dev \
  --context stage=dev --context deployment=control-plane \
  --require-approval never
```

目的:

- 明示stackだけを作成する。
- `cdk deploy --all`やPhase 1/Target updateを避ける。

### 4.6 stopped Target Reconcile

canonical input:

```json
{"schema_version":1,"operation":"reconcile"}
```

Lambda invokeの前後で、CloudFormation、EC2、EBS、snapshot、SG、Route 53、SSM command metadata、DynamoDB item、CloudWatch logをread-only確認した。

目的:

- stopped Targetのshort-circuitを実AWSで確認する。
- SendCommand 0件を実execution metadataから確認する。
- current itemがfresh stopped stateへ更新されることを確認する。

### 4.7 Commit、push、CI

```sh
git add <intended files>
git diff --cached --check
git commit -m "<slice-specific message>"
git push origin main
gh run list --branch main --event push
gh run view <run-id>
```

目的:

- sliceごとに検証済み変更を固定する。
- CIの最終successを確認してから次のAWS gateへ進む。

## 5. 変更した主なファイル

### 5.1 Status domainとadapter

- `src/wishicraft/status.py`
- `src/wishicraft/host_runtime_probe.py`
- `src/wishicraft/reconcile.py`
- `src/wishicraft/system_state.py`
- `src/wishicraft/lambda_handlers/reconcile.py`

責務:

- EC2/SSM/Host Runtime/protocol/active game/network/DNSの正規化
- probe schemaのstrict parse
- discrepancy/health/SystemState導出
- DynamoDB current-state repository
- versioned Lambda inputの薄いadapter

### 5.2 Host Runtime artifact

- repository管理のHost Runtime read-only probe artifact
- Host Runtime renderer/metadata関連file

probe versionは機能追加に合わせて進み、現行active game契約はv1.2.0となった。probeは固定command、stdout JSON only、diagnosticはstderr、mutation禁止を維持した。

### 5.3 Infrastructure

- `infrastructure/app.py`
- Control Plane stack/construct
- Lambda packaging/IAM/DynamoDB/LogGroup定義
- stack/unit testsとCI synth設定

Control PlaneはPhase 1/Targetから独立し、cross-stack exportやTarget stack更新を追加しなかった。

### 5.4 Tests

- status/SSM pagination tests
- probe parser/transport/protocol/active game tests
- endpoint/Reconcile/SystemState/Lambda tests
- Control Plane CDK tests
- fixed probeがread-onlyでpublic portを要求しないことのtests

### 5.5 Canonical docs

- `docs/03_architecture.md`
- `docs/04_domain_and_state_model.md`
- `docs/05_data_and_interface_contracts.md`
- `docs/06_delivery_plan.md`
- `docs/09_decisions_and_backlog.md`
- 必要に応じたrequirements/config boundary docs

最終closeout commitでは次だけを更新した。

```text
docs/03_architecture.md
docs/06_delivery_plan.md
docs/09_decisions_and_backlog.md
```

## 6. 発生したエラー、原因、修正

### 6.1 申告HEADが古かった

最初に提示されたHEADと実local HEADが一致しなかった。

原因:

- Phase 3 status slice後にlocal-notes commitが追加されていた。

対応:

- `HEAD`、`origin/main`、remote commit存在、working treeを証跡で再確認した。
- local-notesだけのcommitを安全と確認してpushした。
- 未追跡noteは自動commitせず、重複noteを削除し、独立したmigration/status noteだけを単独commitした。

### 6.2 SSM pagination未処理

旧adapterはpagination tokenがあるとUNKNOWNへfail-closedしていた。

原因:

- 安全な最初のsliceでは単一pageだけを受容していたため。

修正:

- 全pageを取得しTarget instance IDを一意に解決した。
- 0件、複数件、malformed response、API failure、token loop/異常tokenをUNKNOWNへ正規化した。

### 6.3 AL2023 Python 3.9で`datetime.UTC`が使えない

原文上の重要なfailure:

```text
AttributeError: module 'datetime' has no attribute 'UTC'
```

原因:

- Control Plane packageのPython 3.12前提APIを、Target AMI標準Python 3.9で動くprobeへ持ち込んだ。

修正:

- `datetime.timezone.utc`等のPython 3.9互換APIへ変更した。
- probeのsyntax/API compatibility testを追加し、probe v1.0.1として再検証した。

教訓:

- SSMで転送するscriptはLambda/package側ではなく、実行先hostのinterpreter contractに合わせる。

### 6.4 `mc-monitor status help failed`

GitHub Actionsの失敗名:

```text
Phase 2b-1 integration failure: mc-monitor status help failed
```

調査した原文の挙動:

```text
mc-monitor status --help
# usage/help本文を出力するが exit status 2
```

原因:

- Go flag parserのhelpは正常なusage表示でもexit 2を返す。
- CIが「help contract成立」をexit 0だけで判定していた。

修正:

- 必須flagがhelp本文に存在することを検証し、exit 0または2を許容した。
- commit `605c18c test: accept mc-monitor help usage exit`で修正した。
- 固定image内の`mc-monitor` 0.16.11とstatus command contractを改めて確認した。

### 6.5 Target synthでstackが見つからない

原文:

```text
No stacks match the name(s) MinecraftTargetStack-dev
```

原因:

- CDK appはdeployment/contextに応じてassemblyへ含めるstackを切り替えるため、stack名だけを渡してもTarget stackが生成されないcontextがあった。

修正:

- appのdeployment selectionを確認し、Phase 1/Target/Control Planeそれぞれに正しいcontextを明示した。
- 3 stackを順番に個別synthし、Target synth失敗を成功扱いしなかった。

### 6.6 利用上限による中断とmanual EC2 stop

原因:

- 長いrepository/AWS作業中にCodex利用上限へ到達した。
- 中断後、利用者がEC2を手動停止した。

対応:

- 既存作業をやり直さず、Git、CI、CloudFormation、EC2、EBS、snapshot、SG、DNS、Control Plane resourceをread-onlyで復元した。
- manual stopを前回integration成功の証拠にせず、現在のstopped状態を新しいstarting pointとした。
- working treeをreset/checkout/stashせず、中断前の変更をレビューして完成させた。

### 6.7 Phase 1 credential diffが0ではなかった

重要な差分:

```text
AMI parameter re-resolution
historical UserData difference
old Phase 1 VolumeAttachment replacement-related difference
```

原因:

- Frozen Phase 1 templateと現在のparameter解決/as-built migration状態に既知差分がある。

対応:

- Phase 1 diffを0と偽らず、replacement候補を明示した。
- Phase 1をdeployしなかった。
- Target diff 0、Control Planeとのdependencyなし、Control Plane new-onlyを確認してControl Planeだけをdeployした。

### 6.8 実AWS stale-write testを実行しなかった

local確認の原文:

```text
ModuleNotFoundError: No module named 'boto3'
```

理由:

- production Lambdaはsynthetic state/timestampをinputで受け付けない設計だった。
- raw AWS CLI `UpdateItem`でschema外itemを書くことは利用者の禁止条件に反する。
- local venvにはrepository adapterを直接実AWSへ接続する`boto3`がなかった。

判断:

- production observationを偽装するためだけにinterfaceやdependencyを変えなかった。
- older/equal timestamp rejectionとREADYからfresh UNKNOWNへの更新を強いrepository testsで証明した。

## 7. 今回理解しておくべき技術的内容

### 7.1 Observation、desired state、health、discrepancyは別軸

`ready=true`はMinecraft protocolが利用可能というruntime事実である。desired game、public endpoint、DNSとの一致を意味しない。

```text
runtime READY = protocol-aware runtime availability
discrepancy   = expected と observed の不一致
health        = 現在の観測品質/運用上の健全性
convergence   = 上位workflowが複数条件をまとめて評価
```

これらを単一status enumへ押し込むと、`READYだがactive game mismatch`のような重要な状態を失う。

### 7.2 Not-applicable、absent、unknownを混同しない

- stopped EC2でSSM/protocolを観測しない: `not-applicable`
- stopped EC2にpublic IPv4がない: 正常な`absent`
- API/schema failureで判断できない: `unknown`
- containerを正しく検索して存在しない: `not-found`/`not-running`

この区別により、正常停止を障害扱いせず、観測失敗を正常値へ偽装しない。

### 7.3 Paginationでも一意性を最後まで検証する

first pageでTargetを見つけても即returnせず、全pageを見る必要がある。後続pageにduplicateがあれば一意ではない。token loop検出も無限loop回避に必須である。

### 7.4 Probe artifactはversioned protocolである

shell/Python scriptもControl Planeとのinterfaceであり、単なる内部実装ではない。

- fixed operation
- schema/probe version
- stdout JSON only
- diagnostic stderr
- required field/type/enum/timestamp/impossible combinationのstrict validation
- unknown schemaをbest-effort parseしない
- read-only/no repair

schema変更時はproducerとparser/testsを同時に更新する。

### 7.5 Protocol queryはnetwork公開を必要としない

Minecraft Java status pingはcontainer内localhostへ送れるため、host port publish、SG 25565 ingress、DNSはREADY observationに不要である。観測のためにattack surfaceを増やさない設計になった。

### 7.6 DynamoDB current stateの単調更新

Reconcile Aが古く、Bが新しい場合、Aが遅れて到着してBを上書きしてはいけない。fixed-width UTC timestampとconditional updateでstrictly newerだけを許可する。

同一timestampも拒否したことで、同じ観測versionを別payloadで上書きする曖昧さを避けた。

### 7.7 観測failureも保存対象

以前のcurrent stateがREADYでも、新しい観測が失敗したらexception終了だけにしてはいけない。DynamoDBが書ける限り、fresh UNKNOWN、ready false、error classificationをcurrent stateへ保存する。そうしないと過去READYが現在も有効に見える。

### 7.8 CDK synth、diff、deployは別gate

- synth: templateを生成できるか。
- credential付きdiff/change set: 実環境に対するModify/Replace/Deleteを確認する。
- deploy: 実際のwrite。

synth成功は実環境差分0を意味しない。今回のPhase 1がその典型であり、Frozen差分を認識したまま明示stack deployで隔離した。

## 8. Commitの流れ

Phase 3の主要到達点:

```text
addef380  Phase 3 SSM managed-node status slice
c8328bd   Host Runtime observation slice closeout
b728e40   protocol READY validation記録
58de93c   feat: observe active game discrepancies
2a80ecb   feat: add Phase 3 control plane status persistence
8f19d3a   docs: close out Phase 3 AWS integration
```

protocol CI修正:

```text
605c18c test: accept mc-monitor help usage exit
```

各sliceでpush後にGitHub Actions successを確認し、AWS writeを伴う作業はrepository/CI gate後に進めた。

## 9. 検証結果

### 9.1 Repository最終検証

```text
focused tests: 79 passed
full pytest: 330 passed
Ruff lint: success
Ruff format check: 79 files already formatted
mypy: success (55 source files)
shell syntax: success
git diff --check: success
```

3 stackのcredentialless sequential synth:

```text
MinecraftStack-dev: success
MinecraftTargetStack-dev: success
WishicraftControlPlaneStack-dev: success
```

### 9.2 Final CI

```text
GitHub Actions run #67
head: 8f19d3a1f1ee07dee2d149a5b37f86be386b1cb1
quality: success
host-runtime-integration: success
overall: success
```

### 9.3 AWS Control Plane integration

Control Plane stack:

```text
WishicraftControlPlaneStack-dev: CREATE_COMPLETE
wc-dev-system-state: ACTIVE
wc-dev-reconcile: Active / LastUpdate Successful
LogGroup retention: 14 days
```

deployed resourceはDynamoDB、Lambda、LogGroup、IAM role/policyの5つだけだった。

stopped Target Reconcileを2回実行し、最終的に次を確認した。

```text
system_id: wishicraft-main
environment: dev
game_id: game-vanilla-main
desired_state: STOPPED
ec2: stopped
ssm: not-applicable
host_runtime: not-running
minecraft_service: not-applicable
minecraft_protocol: not-applicable
runtime_ready: false
active_game: not-applicable
public_ipv4: absent
dns: absent
discrepancies: []
health: HEALTHY
observation_errors: []
```

- `observed_at`は2回目が新しかった。
- DynamoDB itemは1件のまま更新され、duplicateを作らなかった。
- Target SSM command metadataは前後不変で、SendCommandは0件だった。
- CloudWatch logはINIT/START/END/REPORTだけで、秘密情報やraw observationを含まなかった。

### 9.4 Final AWS safe state

```text
Phase 1 EC2: stopped
Target EC2: stopped
Data EBS: Targetへattached
DeleteOnTermination: false
Snapshot: retained/completed
Target SG ingress: 0
DNS A record: absent
Minecraft/Host Runtime: stopped
Phase 1 stack: unchanged / not deployed
Target stack: unchanged / not deployed
Control Plane stack: CREATE_COMPLETE
SystemState: fresh stopped current state
```

## 10. 残っている作業

Phase 3は2026-08-28にCompletedとなった。次はPhase 4「Operationと排他制御」である。

主な残作業:

- Games repository/schema
- Operations repository/schema
- Idempotency
- conditional lease Locks
- Current Operationとadmissionの原子性
- lock取得、延長、所有者条件付き解放
- concurrent requestとretry/error path tests

さらに後続Phaseで扱うもの:

- start workflow
- stop workflow
- endpoint/DNS write workflow
- Discord/API integration
- periodic/event-driven reconcile
- backup/reset等の運用workflow

次の作業ではPhase 4全体を一度に実装せず、canonical delivery planに従い、例えば「Operation/Lock domain modelとDynamoDB conditional contract」のような一つの明確なsliceへ分ける。

## 11. 最後に覚えておくこと

このセッションの中心的な学びは、「観測できたこと」と「期待どおりであること」と「操作が成功したこと」を分けることである。

- protocol READYはruntime observationである。
- active game/endpoint mismatchはdiscrepancyである。
- stopped + endpoint absentは正常である。
- observation failureはfresh UNKNOWNとして保存する。
- persistence failureは成功扱いしない。
- AWS deployはstack名を明示し、Frozen stackの既知差分から隔離する。
- 中断後は作業を推測で再開せず、Git/CI/AWS evidenceから現在地点を復元する。

この分離により、Wishicraftは将来のstart/stop workflowでも、古いREADYや不明な実状態を根拠に危険な副作用へ進まない基盤を得た。
