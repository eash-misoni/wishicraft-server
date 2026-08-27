# Wishicraft Phase 2 target migration・IaC reconciliation・Phase 3 status開始記録

> 記録対象: Phase 2b-1完了後のtarget platform lock確認から、独立target stack、root-only実機検証、real-data migration、VolumeAttachment Resource Import、Phase 1 retirement preflight、Phase 2正式closeout、Phase 3 stopped-target status vertical sliceまで。
> 主な作業日: 2026-08-23
> ノート作成日: 2026-08-26
> 用途: 依頼、判断、安全境界、実装、AWS操作、失敗と修正を後から学び直すためのローカルノート。
> 機密保護: password、token、secret本文、SSO cache、credential値、`server.properties`本文、worldのprivate contentは記載しない。

## 1. セッション全体の流れ

このセッションは、Phase 2b-1のsynthetic ownership test完了後から始まった。その後の依頼は、危険な変更を一度に行わず、次のgateを一つずつ通す形で進んだ。

1. AL2023 release、kernel、AMI、Docker、Compose、itzgを固定し、Phase 2 target platform lockを確定した。
2. 現行Phase 1 stackへtarget AMIを適用するとrollback hostを失う危険を確認し、独立した`MinecraftTargetStack-dev`を採用した。
3. root EBSだけを持つtarget EC2を作成し、UID/GID、Docker、Compose、固定itzg、synthetic Minecraftを実機検証した。
4. migration script/runbookを整備し、snapshot後にdata EBSをtargetへ移し、`server.properties`一件だけをownership migrationした。
5. existing worldを固定itzgで2回READYにし、restart persistenceとgraceful shutdownを確認した。
6. 手動attach済みVolumeAttachmentをCloudFormation Resource ImportでTarget Stackへ取り込んだ。
7. Phase 1 retirementを調査したが、rollback window中はFrozen維持とし、retirement executionをDeferredにした。
8. Phase 2を正式closeoutし、Phase 3「実測status」の最初のrepository-only sliceを実装した。

重要なのは、会話中の各依頼が前工程の成功状態を次の依頼の入力として提示していた点である。本ノートでは、正本文書・Git commitで確認できる結果と、利用者が次の依頼で「完了済み」として提示したAWS状態を区別して記す。

## 2. セッション開始時の前提: Phase 2b-1

### 2.1 利用者の依頼・提示内容

開始時点のHEADは次だった。

```text
576707eb788d2c0b6deac24b04b4ad467177a3e5
```

利用者はPhase 2b-1で、固定itzg imageを使うsynthetic fixture integration testにより次のmigrationが必要かつ互換であることを実証済みと説明した。

```text
server.properties
0:993 / 0640
→
993:993 / 0640
```

memory初期値も次へ更新済みだった。

```text
container limit: 2816 MiB
Xms: 1G
Xmx: 2G
```

最初の依頼は、実機migration前のPhase 2 target platform lock最終確定だった。

### 2.2 Codexの判断

- 古いAL2023 releaseを残す具体的なrollback/compatibility理由がなければ、新しい固定releaseを採用する。
- kernelは「Phase 1と同じ6.1」に固定せず、AL2023のdefault/recommendedと不要な新規性のバランスで選ぶ。
- AMI、architecture、owner、creation dateまで固定し、単にSSM public parameterへ追随しない。
- Docker RPMはreleaseに従属する観測値として記録し、独立した第二の恒久Source of Truthにはしない。
- Compose/itzg/Minecraft lockは変更不要なら維持する。

### 2.3 確定したtarget platform

次回依頼時のHEAD `f91973cf617225beebcc1a07a6ff1abc1b79dd9f`で、以下が確定済みとして提示された。

```text
AL2023: 2023.12.20260803
kernel: 6.18
AMI: ami-0b4d2909a55ed2c78
AMI name: al2023-ami-2023.12.20260803.3-kernel-6.18-x86_64
architecture: x86_64
Docker: AL2023 standard repository
Compose: v5.4.0
itzg: 2026.7.2-java25@sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77
Minecraft: 26.2 / VANILLA
```

commit `f91973c`では、設定、Host Runtime validation、tests、architecture/delivery/decision/reference docsが更新された。

主な変更ファイル:

- `config/stages/dev.yaml`
- `src/wishicraft/config.py`
- `src/wishicraft/host_runtime.py`
- `tests/unit/test_host_runtime.py`
- `docs/03_architecture.md`
- `docs/06_delivery_plan.md`
- `docs/09_decisions_and_backlog.md`
- `docs/11_external_constraints_and_references.md`
- `docs/12_initial_configuration.md`
- `docs/architecture/itzg-responsibility-boundary.md`

## 3. Deployment preflight: Phase 1 replacementを避ける

### 3.1 利用者の質問

利用者は、現在のIaCへPhase 2 target configを適用すると、既存Phase 1 EC2、data EBS、IAM、networkへCloudFormation/CDKが具体的に何をするかを調査するよう依頼した。

比較対象は次だった。

- A: 現行EC2 resourceをAMI変更でreplacementする。
- B: Phase 2 target EC2を一時的な別resourceとして追加する。
- C: より安全で単純な別方式。

Phase 1 EC2はrollback先なので、target Host Runtime validation前にreplacement、terminate、data EBS detachを行わないことが原則だった。

### 3.2 Codexの判断と理由

採用したのは方式C、独立stackだった。

```text
MinecraftStack-dev        # Phase 1 / Frozen rollback host
MinecraftTargetStack-dev  # Phase 2 target host
```

理由:

- AMI変更をPhase 1 stackへ入れるとEC2 replacementになる可能性がある。
- rollback hostのroot EBSとPhase 1 runtimeを保持したままtargetを検証できる。
- data EBSをattachせず、root-onlyでDocker/Compose/itzgを検証できる。
- target専用IAM/SGを作ることで、Phase 1 secret権限やpublic 25565を引き継がずに済む。
- stack名を明示し、`cdk deploy --all`を禁止できる。

この判断はD-063として正本化された。

## 4. 独立Target Stackとroot-only実機検証

### 4.1 利用者の依頼

次に利用者は、repository-onlyで`MinecraftTargetStack-dev`を実装し、validation、commit/push/CI後、安全条件を満たせばtarget stackだけをdeployしてroot-only実機検証まで自律的に進めるよう依頼した。

重要な禁止条件:

```text
cdk deploy --all 禁止
MinecraftStack-dev deploy/update禁止
data EBS attach/mount禁止
25565 ingress禁止
secret取得禁止
```

Target boot時の期待状態:

```text
EC2 running
SSM Online
Docker absent
Minecraft process 0
data EBS absent
```

### 4.2 実装した構成

commit `825fb07 feat: add isolated phase 2 target stack`で主に次を追加した。

- `infrastructure/stacks/minecraft_target_stack.py`
- target deploymentを選択する`infrastructure/app.py`
- `infrastructure/host_runtime/target_host_validation.sh`
- target向けDocker/Compose installer補強
- target stack/unit tests
- CIでのtarget stack synth
- D-063と関連architecture/config docs

Target resourceの要点:

- fixed AMI `ami-0b4d2909a55ed2c78`
- `t3a.medium`
- gp3 16 GiB encrypted root、DeleteOnTermination=true
- target専用SSM role/profile
- ingress 0のtarget専用SG
- HTTPS egress
- boot UserDataなし
- data EBSなし

### 4.3 実機結果

次回依頼ではHEAD `c40c23e2f843c3d3c4f0b2c17478d9e3e34e979f`とともに、root-only validation成功が提示された。

```text
Stack: MinecraftTargetStack-dev
EC2: i-04fc0629dc4ea466e
State: stopped
AL2023: 2023.12.20260803
Kernel: 6.18
Docker: 25.0.16
Compose: 5.4.0
itzg: 2026.7.2-java25 + fixed digest
minecraft identity: 993:993
SG ingress: 0
data EBS: not attached
synthetic Minecraft validation: passed
```

`c40c23e`は、target validation scriptがsystemd検証failure時の診断を失わないよう修正したcommitだった。

## 5. Phase 2b real-data migration

### 5.1 利用者の依頼

利用者は、実data EBSを変更する前にfail-closed migration artifact/runbookをrepositoryへ作成し、validation/CI後に次を実行するよう依頼した。

```text
snapshot
→ normal detach from stopped Phase 1
→ attach to stopped target
→ raw device/XFS/UUID preflight
→ mount guard
→ server.properties one-file ownership migration
→ Host Runtime deployment
→ existing world first READY
→ graceful stop
→ restart/persistence verification
→ final graceful stop
→ target EC2 stopped
```

絶対条件には次が含まれた。

- no `mkfs`
- no `xfs_repair`
- no force detach
- no recursive `chown`
- no real world manual edit
- no secret output
- first real-world起動後の自動Phase 1 rollback禁止

### 5.2 migration artifact

commit `b3e27e1 Add Phase 2b real-data migration gate`で次を追加・更新した。

- `infrastructure/migrations/phase2_real_data_migration.sh`
- `docs/runbooks/phase2_real_data_migration.md`
- `infrastructure/host_runtime/wishicraft-data-volume.service`
- `tests/unit/test_phase2_real_data_migration.py`
- Host Runtime renderer/config/docs

scriptは以下を明示的なexpected valueとして受け取り、完全一致しなければ停止する設計になった。

- source instance ID
- target instance ID
- volume ID
- AZ
- filesystem UUID/type
- source/target ownership
- allowlistされた`server.properties` path

### 5.3 migration中に発生したrepository側の修正

#### AL2023 `wipefs`出力の扱い

commit:

```text
8423e62 Fix AL2023 wipefs signature inspection
```

原因は、device signature確認をAL2023実機の`wipefs`表現へ合わせる必要があったことだった。修正はmigration script、runbook、unit testへ限定された。重要な教訓は、block device inspectionの出力形式を別distribution/versionから推測せず、対象hostの実表現をfixture化することである。

#### empty regular fileのpreflight

commit:

```text
1099690 Handle empty regular files in migration preflight
```

filesystem全entryを安全に分類する際、size 0のregular fileを異常扱いしないよう修正した。空fileとmissing/non-regular fileを同一視してはいけない。

#### Minecraft 26.2 world layout

commit:

```text
3bae5bf Support Minecraft 26.2 world layout evidence
```

existing world確認を旧layoutの記憶で決めず、Minecraft 26.2の実際のworld layoutを複数の非破壊的証跡で認識できるようにした。

#### real-data Host Runtime environment

commit:

```text
94bb75f Finalize real-data Host Runtime environment
```

主な対象:

- `infrastructure/host_runtime/phase2-real-data.env`
- `infrastructure/host_runtime/filesystem_preflight.sh`
- Host Runtime tests/runbook

固定値はUID/GID 993、`SKIP_CHOWN_DATA=true`、Minecraft 26.2/VANILLA、container 2816 MiB、Xms 1G、Xmx 2G、restart noだった。

### 5.4 実data migration結果

次回依頼時、HEAD `b56516fdeee9233a5abefc67d7d603de24551862`で成功済みとして提示された。

```text
Phase 1 EC2: i-021eaa7f33ddaf0a6 / stopped
Target EC2: i-04fc0629dc4ea466e / stopped
Data EBS: vol-03ac9f534326c345c / attached to Target as /dev/sdf
Snapshot: snap-0b1d9536e9c476c0f / completed / retained
```

実証内容:

- XFS UUIDとNVMe volume identity一致
- partitionなし
- `server.properties`だけを`0:993 / 0640`から`993:993 / 0640`へ変更
- inode、size、mode、SHA-256不変
- fixed itzg、Minecraft 26.2、Java 25
- existing worldを2回READY
- same data EBS/world persistence
- 2回のformal graceful stop
- exit 0、OOMKilled=false、restart 0
- listener/process残存なし
- 両EC2 stoppedで終了

commit `b56516f`は、この実測結果をdelivery/decision docsへ記録した。

## 6. VolumeAttachment ownership reconciliation

### 6.1 利用者の依頼

手動でtargetへattach済みのexisting attachmentを、物理detach/reattachせずTarget StackのCloudFormation管理下へ移すことが目的だった。

重要なAWS仕様:

```text
AWS::EC2::VolumeAttachment:
  Resource Import supported
  Stack Refactoring unsupported
```

通常`cdk deploy`で新規attachmentを作ろうとすると既存物理attachmentと競合するため、IMPORT change setだけを許可した。

### 6.2 repository preparation

commit:

```text
74d9e8f Prepare target attachment resource import
```

主な変更:

- Target Stackへ`AWS::EC2::VolumeAttachment`を一件追加
- VolumeIdはexisting data volume
- InstanceIdはTarget EC2 Ref
- Device `/dev/sdf`
- `DeletionPolicy: Retain`
- `UpdateReplacePolicy: Retain`
- Target Stackへ`AWS::EC2::Volume`は追加しない
- testsでPhase 1参照/Volume複製がないことを確認

一時ownership構造:

```text
MinecraftTargetStack-dev
  owns Target EC2
  owns current VolumeAttachment

MinecraftStack-dev
  owns Data EBS Volume
  retains stale old VolumeAttachment logical resource
```

### 6.3 import結果

commit `cdcbdbc Record target attachment import completion`で成功が記録された。

```text
TargetDataVolumeAttachment: IMPORT_COMPLETE / IN_SYNC
physical attachment: vol-03ac9f534326c345c -> i-04fc0629dc4ea466e /dev/sdf
post-import cdk diff: 0
```

物理attach timeはmigration時から変化せず、detach/reattachは発生しなかった。

## 7. Phase 1 retirement preflight

ここからは、この会話内で実際にread-only/control-plane確認を行った部分である。

### 7.1 利用者の質問

利用者はPhase 1 retirementをまだ実行せず、次を調べるよう依頼した。

- termination protection / stack policy
- stale old VolumeAttachmentのdelete semantics
- Data EBS Volumeのstack ownership移管方式
- Stack Refactoring / Retain-remove-import / surgical update比較
- Phase 1 EC2/root/stack retirement順序
- snapshot保持期限
- stopped public-IP drift
- Phase 2 completion criteria

### 7.2 Phase 1 protection

read-only確認結果:

```text
MinecraftStack-dev
StackStatus: CREATE_COMPLETE
TerminationProtection: false
Stack policy: none
```

利用者が明示的に許可していたため、resource updateを伴わないtermination protectionだけを有効化した。

```sh
aws cloudformation update-termination-protection \
  --enable-termination-protection \
  --stack-name MinecraftStack-dev \
  --region ap-northeast-1
```

確認結果:

```json
{
  "Status": "CREATE_COMPLETE",
  "TerminationProtection": true
}
```

stack policyは、後続surgical retirement時にoverride管理を増やすため未設定とした。

### 7.3 AWS profile誤りによる権限エラー

最初のvolume/snapshot確認では正本profileを明示しなかったため、限定権限のdefault identityが使われた。

原文:

```text
aws: [ERROR]: An error occurred (UnauthorizedOperation) when calling the DescribeVolumes operation: You are not authorized to perform this operation. User: arn:aws:iam::<account>:user/<redacted> is not authorized to perform: ec2:DescribeVolumes because no identity-based policy allows the ec2:DescribeVolumes action
```

```text
aws: [ERROR]: An error occurred (UnauthorizedOperation) when calling the DescribeSnapshots operation: You are not authorized to perform this operation.
```

原因:

- repositoryの正本runbookは`--profile wishicraft-dev`明示を要求していた。
- default credentialを使ってしまった。

修正:

```sh
aws sts get-caller-identity --profile wishicraft-dev --region ap-northeast-1
aws ec2 describe-volumes --volume-ids <data-volume-id> --profile wishicraft-dev --region ap-northeast-1
aws ec2 describe-snapshots --snapshot-ids <snapshot-id> --profile wishicraft-dev --region ap-northeast-1
```

以後はaccount/regionを照合し、正本profileを明示した。credential値やSSO情報は記録しない。

### 7.4 resource schema

重要コマンド:

```sh
aws cloudformation describe-type \
  --type RESOURCE \
  --type-name AWS::EC2::Volume \
  --region ap-northeast-1

aws cloudformation describe-type \
  --type RESOURCE \
  --type-name AWS::EC2::VolumeAttachment \
  --region ap-northeast-1
```

結果:

```text
AWS::EC2::Volume
ProvisioningType: FULLY_MUTABLE
PrimaryIdentifier: VolumeId

AWS::EC2::VolumeAttachment
ProvisioningType: IMMUTABLE
PrimaryIdentifier: VolumeId + InstanceId
Delete permission: ec2:DetachVolume
```

Cloud Control readで複合identifierも確認した。

```sh
aws cloudcontrol get-resource \
  --type-name AWS::EC2::VolumeAttachment \
  --identifier '<volume-id>|<instance-id>'
```

結果:

- old Phase 1 identifierは`ResourceNotFoundException`。
- current target identifierは実在し、`/dev/sdf`だった。
- reversed identifierはVolumeIdとしてinstance IDを渡したためinvalid parameterになった。

原文:

```text
Resource of type 'AWS::EC2::VolumeAttachment' with identifier '<volume-id>|<old-instance-id>' was not found. (HandlerErrorCode: NotFound)
```

```text
Value (<target-instance-id>) for parameter volumes is invalid. Expected: 'vol-...'.
```

### 7.5 delete semanticsの判断

CloudFormation schemaはcomposite identifierを要求する一方、EC2 `DetachVolume` APIの`InstanceId`はsingle-attach volumeではoptionalである。CloudFormation providerのdelete handlerが必ずold InstanceIdをrequestへ渡すことを、公開一次情報から完全には証明できなかった。

そのため次を判断した。

```text
stale old attachmentの通常deleteは禁止候補
DeletionPolicy/UpdateReplacePolicy Retainを先に付ける
Retain removeでdelete handlerを呼ばない
```

「old attachmentがNotFoundだから安全」と短絡せず、provider delete pathがcurrent target attachmentをVolumeIdだけでdetachする可能性を排除できない以上、Retainを安全境界とした。

### 7.6 Stack Refactoringを採用しなかった理由

`AWS::EC2::Volume`は`FULLY_MUTABLE`でunsupported listにもなかったため、形式上はrefactor候補だった。しかしdeployed Phase 1 templateを確認すると、Volumeへの`Ref`が二か所に残っていた。

```text
MinecraftDataVolumeAttachmentE11BB55A.Properties.VolumeId
MinecraftInstanceC550B42B.Properties.UserData内のDATA_VOLUME_ID
```

VolumeだけをMOVEするには、sourceに残るattachmentとEC2 UserDataをliteralまたはcross-stack referenceへ変更する必要がある。Stack Refactoringはresource configuration変更を伴わないMOVE向けなので、この構造では安全なpreview templateを作れないと判断した。

無効なrefactorを作るだけになるため、`create-stack-refactor`は実行しなかった。

### 7.7 surgical update preview

通常のPhase 1 updateでは、SSM public AMI parameterが最新AMIへ再解決され、EC2 replacement riskがあった。

確認された値:

```text
Phase 1 physical AMI: ami-016923362cc95896d
current SSM parameter resolved AMI: ami-073672ef17082c489
```

そこで、deployed templateをそのまま基準にし、次だけを変える非実行change setを作った。

```text
ImageId expression -> current physical AMI literal
old attachment DeletionPolicy -> Retain
old attachment UpdateReplacePolicy -> Retain
```

重要な作成コマンドの構造:

```sh
phase1_template=$(aws cloudformation get-template ... \
  | jq -c '
      .Resources.MinecraftInstanceC550B42B.Properties.ImageId = "<current-physical-ami>"
      | .Resources.MinecraftDataVolumeAttachmentE11BB55A.DeletionPolicy = "Retain"
      | .Resources.MinecraftDataVolumeAttachmentE11BB55A.UpdateReplacePolicy = "Retain"
    ')

aws cloudformation create-change-set \
  --stack-name MinecraftStack-dev \
  --change-set-name phase1-retirement-preflight-20260823-1 \
  --change-set-type UPDATE \
  --template-body "$phase1_template" \
  --capabilities CAPABILITY_NAMED_IAM
```

preview結果:

```text
Status: CREATE_COMPLETE
ExecutionStatus: AVAILABLE
Action: Modify
LogicalResourceId: MinecraftDataVolumeAttachmentE11BB55A
Replacement: False
Scope: DeletionPolicy, UpdateReplacePolicy
```

次のresource actionは0だった。

- Phase 1 EC2
- root EBS
- IAM
- SG
- Data EBS Volume

このchange setは絶対にexecuteしなかった。

### 7.8 retirementの最終判断

利用者はpreflight結果をreviewし、Phase 1 retirementを現時点で実行しないと決定した。

Accepted:

- Phase 2 technical migration complete
- Target VolumeAttachment reconciliation complete
- rollback window中はPhase 1 Frozen
- retirementは今すぐ実行しない

Deferred plan:

```text
deployed-template based surgical update
→ old attachmentへRetain追加
→ old attachment/Data VolumeをRetain remove
→ Data VolumeをTarget StackへResource Import
→ rollback window終了後にPhase 1 EC2/root/stack退役
```

## 8. Retirement preflight change set cleanup

closeout時、未実行change setを残す方が誤execute riskになるため、再作成可能な監査情報をdocsへ残したうえでchange setだけを削除した。

```sh
aws cloudformation describe-change-set \
  --stack-name MinecraftStack-dev \
  --change-set-name phase1-retirement-preflight-20260823-1 \
  --profile wishicraft-dev \
  --region ap-northeast-1

aws cloudformation delete-change-set \
  --stack-name MinecraftStack-dev \
  --change-set-name phase1-retirement-preflight-20260823-1 \
  --profile wishicraft-dev \
  --region ap-northeast-1
```

削除後確認:

```text
matching change sets: []
Phase 1 StackStatus: CREATE_COMPLETE
TerminationProtection: true
```

change set削除はstack resource updateではなく、EC2/EBS/attachmentへ影響しなかった。

## 9. Phase 2正式closeout

### 9.1 変更した文書

commit:

```text
1cf8116e08d5913f984fb863b28b4fbc8f223783
docs: close Phase 2 migration
```

変更:

- `docs/03_architecture.md`
- `docs/06_delivery_plan.md`
- `docs/09_decisions_and_backlog.md`

記録内容:

- D-067: retirement decision Accepted、execution Deferred
- D-068: Phase 2 technical migration Accepted
- Phase 2 delivery statusをCompletedへ変更
- Data Volume ownership/stale attachment/Phase 1 retirementをcleanup debtへ分類
- RCON/public 25565/DNS automation/Control Plane integrationを後続Phaseへ分類

### 9.2 closeout validation

```sh
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src infrastructure tests
find infrastructure tests/integration -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
npx cdk synth -c stage=dev -c phase=1 --quiet
npx cdk synth MinecraftTargetStack-dev -c stage=dev -c phase=2 -c deployment=target --quiet
git diff --check
```

結果:

```text
pytest: 204 passed
Ruff lint: success
Ruff format: success
mypy: success
shell syntax: success
Phase 1 synth: success
Target synth: success
git diff --check: success
```

GitHub Actions:

```text
run: 32639121769
conclusion: success
```

## 10. Phase 3 readiness review

### 10.1 利用者の依頼

Phase 2 closeout後、最新版のcanonical docsを読み直し、次Phaseが従来のPhase 3「実測status / Reconcile」に相当するかを確認するよう依頼された。

さらに重大なDecision Neededがなければ、最初の小さいvertical sliceとして次を実装してよいとされた。

```text
Target EC2がstoppedのとき、
AWS実測からstatusを取得し、
canonical structured statusとして返す
```

### 10.2 canonical docsから確認した次Phase

`docs/06_delivery_plan.md`の正本は次だった。

```text
Phase 3 — 実測status
主要要件: STA-001〜006
```

目的:

- EC2 state
- SSM state
- Host Runtime state
- Minecraft service/protocol
- active game
- READY
- observed_at
- health/discrepancy
- UNKNOWNのfail-closed処理

### 10.3 readiness inventory

既存:

- `docs/04_domain_and_state_model.md`のDesired/Observed/Health model
- READY/UNKNOWN/observed_at契約
- `docs/05_data_and_interface_contracts.md`のReconcile input/output案
- Phase 2 Host Runtime artifact
- target EC2 CDK resource
- target SSM managed-node IAM

不足:

- concrete SSM state adapter
- Run Command adapter
- running host用Host Runtime probe
- Docker/itzg/Minecraft probe parser
- Reconcile domain service
- SystemState repository
- DynamoDB construct
- Reconcile Lambda
- Route 53/public IP adapter
- stale DNS cleanup判定
- AWS integration test

### 10.4 itzg移行後に読み替えた契約

旧Phase 1前提:

```text
direct Java process
minecraft.service
host RCON
```

Phase 3 target前提:

```text
wishicraft-host-runtime.service
Docker/Compose lifecycle
pinned itzg container
Host Runtime -> container-local observation
```

Control Planeは`server.properties`やworldを直接parse/editしない。Minecraft固有runtimeはitzg、host-local filesystem/process/container観測はHost Runtime、AWS lifecycleとobserved/desired比較はControl Planeが担当する。

## 11. Phase 3 stopped-target vertical slice

### 11.1 実装判断

最初のsliceはSTA-001/002/003/004に限定した。

- Target instance IDはconstructor input。
- Gitへinstance IDを新しいSource of Truthとして埋め込まない。
- EC2 `DescribeInstances`だけを最初の実測境界にする。
- EC2 stopped/terminatedなら到達不能なSSM/host probeを呼ばない。
- API failureやresponse schema mismatchを`stopped`へ変換しない。
- running時のSSM/Host Runtime/Minecraftは未実装なので`unknown`を返す。
- DynamoDB/Lambda/CDK deployを同じsliceへ含めない。

### 11.2 変更ファイル

commit:

```text
7a81103cfde5acb6dfd9f07f18567e171f15da8a
feat: observe stopped target status
```

新規:

- `src/wishicraft/status.py`
- `tests/unit/test_status.py`

更新:

- `docs/03_architecture.md`
- `docs/04_domain_and_state_model.md`
- `docs/05_data_and_interface_contracts.md`
- `docs/06_delivery_plan.md`

### 11.3 structured status

stopped時の出力契約:

```json
{
  "schema_version": 1,
  "instance_id": "i-...",
  "ec2_state": "stopped",
  "ssm_state": "not-applicable",
  "host_runtime_state": "not-running",
  "minecraft_service_state": "not-applicable",
  "minecraft_protocol_state": "not-applicable",
  "ready": false,
  "observed_at": "2026-08-23T12:34:56Z"
}
```

API/schema failure時:

```text
ec2_state = unknown
ssm_state = unknown
host_runtime_state = unknown
minecraft_service_state = unknown
minecraft_protocol_state = unknown
ready = false
```

### 11.4 unit tests

新規testは次を確認した。

- stopped targetの段階的short-circuit
- canonical JSON-compatible output
- missing reservations
- unmatched instance
- unknown future EC2 state
- EC2 API exception
- invalid instance ID
- naive datetime拒否

focused result:

```text
8 passed in 0.02s
```

full result:

```text
212 passed
Ruff: success
format: success
mypy: success (39 source files)
shell syntax: success
Phase 1 synth: success
Target synth: success
git diff --check: success
```

GitHub Actions:

```text
run: 32639378104
conclusion: success
```

## 12. このセッションで発生したtooling/errorと修正

### 12.1 official provider GitHub URLが404

CloudFormation schemaの`sourceUrl`からprovider実装を取得しようとした。

```sh
curl -fsSL https://api.github.com/repos/aws-cloudformation/aws-cloudformation-resource-providers-ec2/contents
```

原文:

```text
curl: (56) The requested URL returned error: 404
```

修正:

- 公開されていない/取得できないprovider sourceを推測しなかった。
- `describe-type` schema、Cloud Control read、公式EC2 `DetachVolume` API documentationまでを一次情報とした。
- delete request mappingを完全証明できない事実を残し、安全側のRetainへ判断した。

### 12.2 shell syntax対象に存在しないdirectoryを含めた

原文:

```text
find: scripts: No such file or directory
```

原因:

- repositoryに`./scripts` directoryがないのにgeneric commandへ含めた。

修正:

```sh
find infrastructure tests/integration -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

### 12.3 存在しないCDK executable path

原文:

```text
zsh:1: no such file or directory: .venv/bin/cdk
```

原因:

- CDK CLIはPython venvではなくnpm dependencyだった。

修正:

```sh
npx cdk synth ...
```

### 12.4 jsii cacheのsandbox権限

原文:

```text
RuntimeError: EPERM: operation not permitted, utime '/Users/.../Library/Caches/com.amazonaws.jsii/.../.jsii-runtime-package-cache'
```

原因:

- jsiiがworkspace外のuser cache markerを更新しようとした。

修正:

- 同じsynthを許可されたsandbox外実行で再試行した。
- resource/deployは変更せず、local synthだけを行った。

### 12.5 CDK context不足

原文:

```text
No stacks match the name(s) MinecraftTargetStack-dev
```

原因:

- environment variableだけを設定し、CDK appが読むcontext `deployment=target`を渡していなかった。

修正:

```sh
npx cdk synth MinecraftTargetStack-dev \
  -c stage=dev \
  -c phase=2 \
  -c deployment=target \
  --quiet
```

### 12.6 CDK synthの並列出力競合

Phase 1とTarget synthを同時に既定`cdk.out`へ出した。

原文:

```text
Another CLI (PID=...) is currently synthing to cdk.out. Invoke the CLI in sequence, or use '--output' to synth into different directories.
```

修正:

- invocation固有のtemporary outputを使用した。

```sh
npx cdk synth ... --output /tmp/wishicraft-<purpose>-target-synth-20260823
```

### 12.7 RuffのPython 3.12指摘

原文:

```text
UP017 Use `datetime.UTC` alias
```

またformat checkは次を返した。

```text
unformatted: File would be reformatted
```

修正:

```sh
.venv/bin/ruff check --fix src/wishicraft/status.py tests/unit/test_status.py
.venv/bin/ruff format src/wishicraft/status.py tests/unit/test_status.py
```

### 12.8 apply_patch context mismatch

docs/codeをまとめて変更するpatchが、正確な周辺行と一致せず失敗した。

原文:

```text
apply_patch verification failed: Failed to find expected lines in .../docs/04_domain_and_state_model.md
```

修正:

- 対象箇所を`sed`/`rg`で再読した。
- patchをcode renameとdocs updateへ小分けした。
- 失敗したpatchはatomicに未適用だったため、partial editは残らなかった。

### 12.9 `gh` CLIが存在しなかった

原文:

```text
zsh:1: command not found: gh
```

修正:

GitHub Actions public APIを使用した。

```sh
curl -fsSL 'https://api.github.com/repos/eash-misoni/wishicraft-server/actions/runs?branch=main&event=push&per_page=10' \
  | jq -c '.workflow_runs[] | {id,status,conclusion,html_url,head_sha}'
```

### 12.10 Target synthの既知warning

原文:

```text
WARNING ImageId: Hardcoded AMI ID - use a parameter or mapping for portability (CloudFormation Validate)
MinecraftTargetStack-dev/TargetInstance (TargetInstance) aws-cdk-lib.aws_ec2.CfnInstance
```

これは今回のtarget platform reproducibility要件によりAMIを明示固定した結果で、失敗ではない。floating SSM AMIがPhase 1 replacement riskを作ったことを踏まえると、targetの固定AMIは意図した設計である。

## 13. 技術的に理解しておくべき内容

### 13.1 CloudFormation physical stateとlogical ownershipは別

EBSが物理的にtargetへattachedでも、CloudFormation ownershipが自動で移るわけではない。手動detach/attach後はsource stackのold logical resourceがstaleになり、target側はResource Importするまでunmanagedである。

今回、VolumeAttachmentだけをTarget Stackへimportし、Volume本体はPhase 1 stack所有のまま残した。runtimeの成立とIaC ownershipの最終整理は別問題である。

### 13.2 Retainはresourceごとに意味が違う

`AWS::EC2::Volume`のRetainはVolume削除を防ぐ。しかしattachment resourceのdeleteはdetachを伴うため、Volume本体がRetainでもmount先が変わらない保証にはならない。

stale attachmentのdelete semanticsが完全証明できない場合、attachment自身へRetainを付けてからtemplateからremoveする必要がある。

### 13.3 Resource ImportとStack Refactoringは代替関係ではない

- Resource Import: existing physical resourceをstack管理へ入れる。
- Stack Refactoring: supported resourceをstack間MOVEする。

VolumeAttachmentはimport可能だがrefactoring unsupportedだった。Volume本体は`FULLY_MUTABLE`でも、source templateに残る`Ref`依存があるため、VolumeだけのMOVEが必ず安全とは限らない。

### 13.4 floating SSM AMI parameterのrisk

CloudFormation parameter keyを`UsePreviousValue=true`にしても、SSM public parameterのkeyを維持するだけで、resolved AMIが同じとは限らない。Phase 1 deployed templateの再updateで最新AMIへ解決されるとEC2 replacementにつながる。

surgical updateではcurrent physical AMIをliteralへ固定し、change set上のEC2 action 0を必須にする。

### 13.5 stopped public IPv4 drift

EC2のauto-assigned public IPv4はstop時にreleaseされる。そのためCloudFormation driftで`AssociatePublicIpAddress actual=false`相当に見えることがある。これはstopped instanceの観測差分で、launch configuration破損とは限らない。

このdriftだけを直すためにinstance/stackを変更しない。

### 13.6 ownership migrationは最小対象・content不変

今回の`server.properties`問題はMinecraft設定内容ではなくLinux ownershipだった。解決は一件だけの`chown`であり、recursive `chown`、copy/replacement、chmod、properties本文編集は不要だった。

安全性は次のpre/postconditionで担保した。

- expected path
- regular file
- non-symlink
- no ACL
- expected numeric owner/group/mode
- inode/hash/mode不変

### 13.7 段階的status観測

EC2がstoppedなら、SSMやHost Runtimeへ問い合わせる必要はない。

```text
EC2 stopped
→ SSM not-applicable
→ Host Runtime not-running
→ Minecraft not-applicable
→ READY false
```

一方、EC2 APIが失敗した場合はstoppedと推測してはいけない。

```text
EC2 unknown
→ lower layers unknown
→ READY false
```

`not-applicable`と`unknown`は意味が異なる。

- `not-applicable`: 上位状態から問い合わせ不要と確定。
- `unknown`: 確認不能であり、安全な状態を推測できない。

## 14. セッション終了時のAWS/repository状態

正本文書に記録されたcloseout状態:

```text
Phase 1 EC2: stopped
Target EC2: stopped
Data EBS: attached to Target as /dev/sdf
TargetDataVolumeAttachment: IMPORT_COMPLETE / IN_SYNC
Migration snapshot: completed / retained
Phase 1 stack: Frozen / termination protection enabled
Target cdk diff: 0 at reconciliation closeout
DNS: no migration-time public record
Target SG ingress: 0
```

repository:

```text
HEAD: 7a81103cfde5acb6dfd9f07f18567e171f15da8a
branch: main
origin/main: same commit
working tree: clean
```

主要commit sequence:

```text
f91973c Finalize Phase 2 target platform lock
825fb07 feat: add isolated phase 2 target stack
c40c23e fix: keep target systemd verification diagnostic
b3e27e1 Add Phase 2b real-data migration gate
8423e62 Fix AL2023 wipefs signature inspection
1099690 Handle empty regular files in migration preflight
3bae5bf Support Minecraft 26.2 world layout evidence
94bb75f Finalize real-data Host Runtime environment
b56516f Record Phase 2b real-data validation
74d9e8f Prepare target attachment resource import
cdcbdbc Record target attachment import completion
1cf8116 docs: close Phase 2 migration
7a81103 feat: observe stopped target status
```

## 15. セッション終了時点の残作業

### Phase 1 retirement: Deferred

rollback window終了後、人間reviewを経て次を行う。

1. deployed-template based policy-only change setを再作成。
2. EC2/root/IAM/SG/Volume/attachment physical action 0を確認。
3. old attachmentへRetainを追加。
4. old attachmentとData VolumeをRetain remove。
5. Data VolumeをTarget StackへResource Import。
6. target drift/diff、snapshot、attachment不変を確認。
7. Phase 1 EC2/rootを退役。
8. termination protection解除を別承認し、Phase 1 stackを解体。

この作業までsnapshot `snap-0b1d9536e9c476c0f`を削除しない。

### Phase 3 status/Reconcile

次のrepository work候補:

1. concrete SSM managed-node state adapter
2. stopped/pending/running別の段階的観測
3. Host Runtime probe JSON契約
4. Docker/itzg/Minecraft probe parser
5. health/discrepancy derivation
6. SystemState DynamoDB construct/repository
7. `observed_at`/version条件付き部分更新
8. Reconcile Lambda
9. Route 53/public IPv4 observationとstale DNS cleanup判定
10. dev deploy前CDK diffと明示承認
11. AWS integration test

### 後続機能

- RCON/container-local management command path
- public Minecraft 25565 ingressの正式設計
- DNS automation
- Control Plane integration
- start/stop workflows
- Discord MVP

これらはPhase 2 technical migrationのblockerではなく、各後続Phaseで実装する。
