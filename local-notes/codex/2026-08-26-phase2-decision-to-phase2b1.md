# Wishicraft Phase 2 Decision PassからPhase 2b-1までの作業記録

> 記録対象: このCodexセッション開始時に提示されたPhase 1完了状態の確認から、Phase 2 Decision Pass、Phase 2a、AWS metadata preflight、Phase 1 hostでのfilesystem observation、migration compatibility検討、固定itzg imageによるPhase 2b-1 synthetic integration testのCI成功まで。  
> 主な作業日: 2026-08-22  
> ノート作成日: 2026-08-26  
> 用途: 依頼、設計判断、安全境界、実装、検証、失敗と修正を、後から時系列で学び直すためのローカルノート。  
> 機密保護: password、token、AWS credential、secret本文、実`server.properties`本文、world内容は記載しない。このノート作成のためにAWSや実hostへ再アクセスしていない。

## 1. セッション全体の流れ

このセッションでは、正式完了済みのPhase 1をrollback可能なas-builtとして維持しながら、Minecraft Runtimeをhost上の直接Java実行から`itzg/docker-minecraft-server`へ移すため、次の順序で判断と検証を進めた。

1. repositoryのPhase 1 as-builtとitzg責務境界を確認した。
2. Phase 2実装前に、image pinning、Docker/Compose、identity、memory、lifecycle、shutdown、Source of Truth、mapping/applyの8項目をDecision Passとして整理した。
3. desired/rendered/applied revision semantics、停止timeoutの累積scope、AL2023 repository再現性を再検討した。
4. Phase 2aとしてHost Runtimeの静的artifact、renderer、preflight、Compose/systemd契約、test、文書を実装した。
5. AWS APIだけを使うPreflight Aで、停止中Phase 1 instanceとdata EBS metadata、boot impact、target AL2023 AMIを確認した。
6. Phase 1 EC2を通常起動する方式Aでfilesystem metadataをread-only観測し、既存正常停止経路で停止した。
7. `server.properties`だけが`0:993 / 0640`であるcompatibility問題を調査し、一件だけ`993:993 / 0640`へ移す方針を選んだ。
8. 実dataへ触れる前に、固定tag+digestのitzg imageとsynthetic fixtureだけを使うPhase 2b-1 integration testをGitHub Actionsへ追加した。
9. CI harnessの複数の問題を、一つずつ原因が見える形に直した。
10. 最終的にquality jobとDocker integration jobが成功し、HEAD `576707eb788d2c0b6deac24b04b4ad467177a3e5`で停止した。

以降に別セッションで行われたtarget host作成、実data EBS migration、Phase 2 closeout、Phase 3 status実装は本記録の対象外である。

## 2. 開始時点: Phase 1完了とitzg方針

### 2.1 利用者の依頼

開始時点で利用者は次を前提として示した。

- Phase 1は正式完了済み。
- Minecraft Runtimeに`itzg/docker-minecraft-server`を採用する方針へ変更済み。
- 3層アーキテクチャと責務境界はrepositoryの正本文書へ反映済み。
- その設計変更のcommit、push、CI確認も完了済み。
- 今回はPhase 2実装前のDecision Passであり、調査と提案に留める。
- Phase 1履歴、既存runtime、config、infrastructure、AWS resourceは変更しない。

最初に確認対象として指定された主な文書は次だった。

- `docs/architecture/itzg-responsibility-boundary.md`
- `docs/01_product_scope_and_glossary.md`
- `docs/02_requirements.md`
- `docs/03_architecture.md`
- `docs/05_data_and_interface_contracts.md`
- `docs/06_delivery_plan.md`
- `docs/07_operations_security_and_cost.md`
- `docs/09_decisions_and_backlog.md`
- `docs/12_initial_configuration.md`
- Phase 1 runbook
- 現行config / infrastructure / runtime implementation

### 2.2 3層責務境界

設計の軸は次の3層である。

```text
Control Plane (Wishicraft)
  -> Host Runtime
    -> Minecraft Runtime (itzg/docker-minecraft-server)
      -> Minecraft process
```

各層の中心責務は次のように整理した。

- **Control Plane:** 操作受付、認可、desired state、状態遷移、AWS resource orchestration、start/stop intent。
- **Host Runtime:** AL2023、EBS mount guard、Docker/Compose、identity、secret injection、container lifecycle、host-local command boundary。
- **itzg:** Java/Minecraft互換性、distribution、Minecraft固有設定形式、process start/stop、graceful shutdown。

Phase 1のhost Java、固定`server.jar`、直接`minecraft.service`、whitelist artifact、RCON firewallは、誤りとして消すのではなく、正式なas-builtとrollback先として残す判断だった。

## 3. Phase 2 Decision Pass

### 3.1 利用者が判断を求めた8項目

1. itzg image pinning
2. AL2023上のDocker Engine / Docker Compose導入とversion管理
3. container UID/GIDとdata EBS ownership
4. container memory / JVM heap / OOM policy
5. lifecycle owner / restart policy
6. graceful shutdown / timeout hierarchy
7. 設定カテゴリごとの唯一のSource of Truth
8. desired stateからitzg inputへのmapping/apply contract

### 3.2 Codexの主な推奨判断

#### Image lock

自動更新を避け、dev検証後に明示更新する要件から、release tagだけでなくdigestも固定する案を推奨した。

```text
release tag + digest
```

理由:

- tagは人間がrelease/Java variantを理解しやすい。
- digestは同じrepository revisionから同じimage bytesを取得する再現性を与える。
- rollbackは旧tag+digestへrepository lockを戻すことで成立する。
- floating `latest`、`stable`、Java別floating tagだけでは意図しない更新を防げない。

#### Docker / Compose

- Docker Engineは固定AL2023 releaseの標準repositoryから導入する。
- Docker RPM NEVRAを独立した恒久設定として二重管理しない。
- 実際に導入されたpackage/versionはbootstrap時に検証・記録する。
- Compose CLI pluginはversionとchecksumをGitで固定する。
- bootstrapはplatform/toolingの導入と検証、Host RuntimeはMinecraft lifecycleを担当する。
- 自動upgradeを行わない。

#### Identity

- existing data EBSのnumeric UID/GIDへcontainer identityを合わせる。
- 名前ではなくnumeric IDを契約とする。
- `SKIP_CHOWN_DATA=true`を使う。
- recursive chownは禁止する。
- 具体的UID/GIDは推測せず、実機read-only preflightの`Observation Required`とする。

#### Memory

当初のPhase 2a provisional値は次だった。

```text
container limit: 3 GiB
Xms: 1G
Xmx: 2304M
```

これは恒久的architecture constraintではなく、devでOOM、RSS、native memory、save/stopを観測して調整するinitial tuning valueとした。

#### Lifecycle

- desired lifecycleの判断はControl Planeだけが持つ。
- EC2上で意図を実行するownerはHost Runtimeだけとする。
- systemdはHost Runtime wrapperの境界を提供するが、boot時にMinecraftを勝手に起動しない。
- Compose/containerは`restart: "no"`。
- Docker/systemd/itzgがControl Planeによる停止を打ち消さない。
- Phase 1 `minecraft.service`がactiveならPhase 2 Compose startをfail-closedにする。

#### Source of Truth

```text
Git:
  infrastructure lock、image tag/digest、Minecraft VERSION/TYPE、
  provisional memory、static boot-time policy、mapping rules

Control Plane state:
  whitelist desired state、ops desired state、運用中に変更するdesired state

AWS secret store:
  RCON password等のsecret実値

data EBS:
  generated server.properties、whitelist.json、world、runtime realization
```

同一値をGitとDynamoDB等で同時に正本化しないことが原則だった。

#### Apply categories

```text
boot-time configuration
restart-required configuration
running serverへ即時反映できるruntime operation
```

各カテゴリでSource of Truth、mapping先、apply timing、成功probe、applied確認、失敗時状態を分ける案を採用候補とした。

## 4. Decision Passへの再検討依頼

### 4.1 desired / rendered / applied revision semantics

利用者は、apply成功までdesired revisionを旧値に留める考え方を明確に否定した。

正しい状態例:

```text
desired revision = N
applied revision = N-1
status = APPLY_FAILED / DEGRADED
```

Codexは次のsemanticsへ修正した。

- Control Planeが妥当な変更要求を受理した時点で`desired_revision`を進める。
- render成功後にだけ`rendered_revision`とnon-secret `render_digest`を記録する。
- runtimeへ反映され、probeで確認できた後にだけ`applied_revision`を進める。
- apply失敗時もdesired stateを巻き戻さず、revision差を未収束状態として残す。
- Phase 2aでは永続state machineまで実装せず、canonical renderとdigest計算までとする。

技術的な要点は、**要求を受理した事実**と**runtimeが収束した事実**を同じrevisionで表さないことである。

### 4.2 Shutdown timeoutの累積scope

単純な大小関係だけでは不十分だった。

```text
STOP_DURATION < Compose < systemd < SSM < Control Plane
```

特にexplicit saveとcontainer graceful stopが直列なら、上位timeoutは両方のworst-case合計を包む必要がある。

採用したprovisional budget:

```text
explicit save:                60s
itzg STOP_DURATION:          120s
Compose stop_grace_period:   150s
systemd TimeoutStopSec:      180s
Host Runtime wrapper:        300s
SSM timeout:                 360s
Control Plane wait:          420s
```

重要なscope:

```text
Host Runtime wrapper (300s)
  ├─ explicit save (最大60s)
  └─ systemd/Compose stop
       ├─ itzg/Minecraft graceful shutdown (120s)
       ├─ Compose grace boundary (150s)
       └─ systemd stop boundary (180s)

SSM (360s) contains wrapper worst-case + margin
Control Plane (420s) contains SSM execution + polling/API margin
```

つまり`systemd TimeoutStopSec=180s`はsaveを含む全wrapperのtimeoutではなく、save後に呼ばれるsystemd stop portionのscopeとした。直列全体は300秒wrapperが包む。

### 4.3 AL2023 reproducibility

比較した案:

- AMI自体をrelease単位でpinする。
- AMI lookupはlatestのまま、`dnf releasever`/repositoryだけをpinする。
- AL2023のversioned repository modelとAMI lockを組み合わせる。

採用した基本方針:

- AL2023 release / official AMIを固定する。
- architectureを固定する。
- そのreleaseのversioned standard repositoryからDockerを導入する。
- Compose version/checksumとitzg tag/digestは独立して固定する。
- Docker RPM NEVRAを永続的な第二正本にしないが、導入結果をfail-closedで照合・記録する。

## 5. Phase 2a repository実装

### 5.1 利用者の依頼

Decision Set承認後、利用者は既存Phase 1 runtimeを保持したまま、AWS適用前までのHost Runtimeをrepository内に構築するよう依頼した。

主なscope:

- platform/runtime lock
- idempotentかつfail-closedなDocker/Compose installer artifact
- identity/filesystem preflight
- itzg Compose定義
- systemd/Host Runtime lifecycle artifact
- shutdown contract
- canonical boot-time renderer
- static/unit validation
- 正本文書更新
- commit、push、CI success

明示的non-scope:

- AWS deploy、EC2、SSM
- Dockerのローカルinstall
- image pull/container起動
- 実world/EBS変更
- secret取得
- Phase 1 runtimeのdisable/remove

### 5.2 実装上の判断

- fixed valuesはstage configからrendererへ渡す。
- render outputはdeterministicかつcanonicalにする。
- secret本文とsecretの単純hashはrender artifact/digestへ含めない。
- `/srv/minecraft`のmount guard成功後だけCompose操作可能にする。
- unknown owner、ACL、symlink、special fileはfail-closed。
- `restart: "no"`、管理port非publish、Minecraft接続portだけを公開候補にする。
- data EBS上game directoryを`/data`へbind mountし、container layerを永続正本にしない。
- Phase 1 serviceとの同時起動をinterlockする。

### 5.3 完了結果

Phase 2aはcommitとして完了し、利用者が次を提示した。

```text
34759b4b14113a63b353b59d10714b3b400c0404
```

CIも成功済みだった。

commit `34759b4`で変更・追加されたファイルは次だった。

```text
README.md
config/stages/dev.yaml
config/stages/prod.yaml
docs/03_architecture.md
docs/04_domain_and_state_model.md
docs/05_data_and_interface_contracts.md
docs/06_delivery_plan.md
docs/07_operations_security_and_cost.md
docs/09_decisions_and_backlog.md
docs/11_external_constraints_and_references.md
docs/12_initial_configuration.md
infrastructure/host_runtime/docker_compose_install.sh
infrastructure/host_runtime/filesystem_preflight.sh
infrastructure/host_runtime/start.sh
infrastructure/host_runtime/stop.sh
infrastructure/host_runtime/wishicraft-host-runtime.service
src/wishicraft/config.py
src/wishicraft/host_runtime.py
tests/unit/test_host_runtime.py
```

この一覧からも、Phase 2aがAWSへ適用する作業ではなく、installer、preflight、lifecycle wrapper、systemd unit、renderer/validation、tests、canonical docsをrepository内で揃える作業だったことが分かる。

## 6. Preflight A: AWS read-only metadataとboot impact

### 6.1 利用者の依頼

Phase 2b前に、EC2を起動せず、repositoryとAWS read-only APIから次を確認するよう依頼された。

- current dev instance metadata
- current AMIとPhase 2 target AL2023 platform lock
- root/data volume metadata
- Security Groupとpublic IP有無
- Phase 1 `minecraft.service`のboot behavior
- 次回filesystem observation方式A/B/Cの比較

許可されたのは`sts get-caller-identity`、各種`describe-*`、public AL2023 parameter等のread-only APIだけで、secret parameter取得やresource writeは禁止だった。

### 6.2 Repositoryから確定したboot behavior

repositoryのPhase 1 bootstrap、systemd unit、mount guard、runbookから次を確認した。

```text
EC2 boot
  -> data EBS mount
  -> mount identity/UUID/XFS guard
  -> enabled minecraft.service
  -> Java/Minecraft process
  -> world open/write
  -> listener 25565
```

要点:

- Phase 1 `minecraft.service`はenabledであり、通常bootで自動起動する。
- mount guardを通過しない限りMinecraftを起動しない。
- mount guard成功後は、EC2をstartしただけでもMinecraftがworldをopen/writeし得る。
- service/processがREADY/listenへ進むと、SGに25565 ingressがあればplayer接続可能になり得る。
- Phase 1で確立済みのsave、service stop、process/listener複合確認、EC2 stop経路を再利用できる。

### 6.3 Filesystem observation方式比較

#### A. Phase 1 EC2を通常起動

メリット:

- 既存の検証済みrunbookを再利用できる。
- 新しいinspection infrastructureが不要。
- data EBSの実mount状態をそのhostから観測できる。
- rollbackは既存正常停止とEC2 stop。

リスク:

- Minecraftが通常起動し、短時間world writeが起こる。
- 25565が開いていればplayer接続可能性がある。

#### B. Phase 1 Minecraftを起動させず既存EC2を観測

- boot前にserviceをmask/disableするにはroot filesystemへの事前変更が必要。
- その変更自体が既存as-builtへのmutationになる。
- 観測だけのために新しい状態差分と復旧手順を増やす。

#### C. snapshot/temporary inspection environment

- 元EBSを直接writeしない安全性は高い。
- ただしsnapshot、temporary volume、temporary instance、XFS read-only mount、cleanupが必要。
- Wishicraftの規模と短時間metadata観測には複雑・高コスト。

### 6.4 推奨

方式Aを推奨した。ただし起動前に25565 ingressを一時revokeし、停止確認後だけ同一ruleをrestoreする条件を付けた。

## 7. Phase 1 host filesystem observation

### 7.1 利用者が許可した操作

- AWS read-only API
- Minecraft TCP 25565 ingressだけの一時revoke/restore
- `StartInstances`
- SSM Online確認
- SSM Run Command
- Phase 1 `minecraft.service`通常stop
- `StopInstances`

禁止事項にはDocker install、Compose、image pull、itzg、filesystemへの手動write、secret取得、world/config編集、Phase 1 serviceのdisable/maskが含まれた。Minecraft自身の通常起動中world writeだけは明示許可された。

### 7.2 安全sequence

```text
STS / expected account-region確認
-> dev instanceとSGを再確認
-> 現在のTCP 25565 ingressを完全な形で退避
-> 25565だけrevoke
-> revoke後に25565不存在を再確認
-> EC2 start
-> running / SSM Online確認
-> mount・EBS・UUID・XFS・service・process・listener確認
-> filesystem metadataのみ観測
-> Phase 1正常停止runbook
-> process/listener/mount/journal複合確認
-> EC2 stop
-> stopped終端確認
-> 元の25565 ruleを同一内容でrestore
-> 余分なrule/RCON ingressがないことをread-only確認
```

### 7.3 観測結果

対象game directory:

```text
/srv/minecraft/games/game-vanilla-main/server
```

実ファイル本文は読まず、metadataだけを集計した。

確定した重要な観測値:

```text
game directory:             UID:GID 993:993
通常fileの大半:             UID:GID 993:993
server.propertiesのみ:      UID:GID 0:993
server.properties mode:     0640
extended ACL:               なし
symlink:                    なし
special file:               なし
filesystem:                 expected XFS mount
```

numeric IDを正本観測値とした。Phase 1 host上のlocal account/groupとの対応もread-onlyで確認したが、Phase 2 target hostで同じ自動採番になるとは仮定せず、target側では993を明示的に再現する必要があると判断した。

### 7.4 Memory baseline

```text
total memory:                    約3.76 GiB
available (light Phase 1):       約2.49 GiB
Java RSS:                        約959 MiB
swap:                            0
```

これはPhase 1 hostのbaselineであり、Phase 2 target kernel、Docker、Compose、itzgの動作を証明するものではない。

### 7.5 正常停止

Phase 1で確立済みのrunbookに従い、save、`systemctl stop minecraft.service`、MainPID、Java process、cgroup process、Minecraft listener、RCON/management listener、mount、journalを複合判定した。

既知のsystemd `failed`やstatus 143だけで停止失敗とせず、process/listener消滅とsave証跡を含む複合条件を用いた。正常停止後だけEC2を停止し、`stopped`終端確認後に25565 ingressを復元した。

この観測はPhase 1正常停止baselineを与えたが、itzgの`STOP_DURATION`やPhase 2 timeoutの最終確定には使わないとした。

## 8. server.properties compatibility調査

### 8.1 利用者の質問

実機で判明した次の差を、itzg公式startup scripts/documentationと照合するよう依頼された。

```text
game directory:             993:993
通常fileの大半:             993:993
server.propertiesのみ:      0:993 / 0640
extended ACL:               なし
symlink/special file:       なし
```

Phase 2方針:

```text
UID=993
GID=993
SKIP_CHOWN_DATA=true
server.properties realizationはitzgへ委譲
```

比較対象:

- A: `server.properties`を`993:993`へ変更
- B: `0:993`のままgroup writeを追加
- C: itzgによる更新を無効化
- D: その他の標準機能を維持する方式

### 8.2 itzg startupの技術的理解

固定releaseのstartup pathでは、root entrypointがUID/GID調整等を行った後、`gosu`で指定identityへdropし、その後の`server.properties` realizationを`mc-image-helper`が実行する。

したがって`0:993 / 0640`はUID 993からgroup-readはできるがgroup-writeできず、propertiesに変更が必要な入力を与えると更新できない。

`SKIP_CHOWN_DATA=true`はdata directoryへのrecursive chownをskipするが、既存fileの個別write権限を与えるものではない。

`OVERRIDE_SERVER_PROPERTIES`や`SKIP_SERVER_PROPERTIES`で更新を避ける案は、Linux permission conflictを隠せる一方、Minecraft内部形式を原則itzgへ委譲する責務境界を弱める。

### 8.3 推奨したmigration

方式Aを推奨した。

```text
server.properties一件だけ
0:993 / 0640
->
993:993 / 0640
```

理由:

- itzg標準のproperties realizationを維持できる。
- group writeを広げず、0640のsecurity intentを保てる。
- recursive ownership変更が不要。
- Phase 1 rollback時は一件だけ`0:993 / 0640`へ戻せる。
- content編集ではなくHost RuntimeのLinux ownership migrationとして扱える。

### 8.4 RCON secret boundary

- RCON passwordのSource of TruthはAWS SecureStringのまま。
- Git/render artifact/non-secret digestへsecret本文を含めない。
- RCON portはhostへpublishしない。
- `server.properties`にsecret realizationが必要でも、生成fileはcontainer runtime identityだけがwriteできる`993:993 / 0640`を基本境界とする。
- secretがfileへrealizeされる以上、group 993のmembershipとhost privilegeをsecurity boundaryとして管理する。

## 9. Memory初期値の再評価

### 9.1 比較

#### A. 3 GiB / Xmx 2304M維持

- JVM heap余裕は大きい。
- 3.76 GiB host、swap 0ではOS、SSM、Docker daemon、container native memory、page cacheのmarginが薄い。
- Phase 2b最小Vanilla検証の目的に対してOOM riskが相対的に高い。

#### B. 2816 MiB / Xmx 2G付近

- JVMに2 GiBを与えつつ、container内native memoryへ約768 MiBを残す。
- host側にも3 GiB limit案より追加marginを残せる。
- 性能最大化より最小安全検証を優先する目的に合う。

### 9.2 採用値

利用者は次を採用した。

```text
container limit: 2816 MiB
Xms: 1G
Xmx: 2G
```

この値はProvisional tuning valueであり、恒久constraintではない。target host上のDocker/itzg起動peak、RSS、OOM event、save/stopを実測して再評価する必要がある。

## 10. Phase 2b-1 synthetic Docker integration test

### 10.1 利用者の依頼

実data EBSを変更する前に、固定imageとsynthetic fixtureで次を実証するよう依頼された。

1. `0:993 / 0640`の`server.properties`ではitzg更新がpermission errorになる。
2. `993:993 / 0640`へmigration後は更新できる。
3. `SKIP_CHOWN_DATA=true`でrecursive chownが起きない。
4. 同一入力のrestart後もowner/mode/content/inodeが安定する。
5. Phase 2b最小構成が固定imageで成立する。

固定image:

```text
ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77
platform: linux/amd64
```

ローカルMacへDockerをinstallせず、Dockerが利用可能なGitHub-hosted Linux runnerを優先するよう指定された。

### 10.2 変更したファイル

最初の実装commit `23e9e6d`で変更したのは次の12件だった。

```text
.github/workflows/ci.yml
README.md
config/stages/dev.yaml
docs/03_architecture.md
docs/05_data_and_interface_contracts.md
docs/06_delivery_plan.md
docs/07_operations_security_and_cost.md
docs/09_decisions_and_backlog.md
docs/11_external_constraints_and_references.md
docs/12_initial_configuration.md
tests/integration/test_itzg_ownership.sh
tests/unit/test_host_runtime.py
```

主要な変更:

- CIに`host-runtime-integration` jobを追加。
- executableなsynthetic integration harnessを追加。
- dev memory targetを`2816MiB / 1G / 2G`へ更新。
- unit/static contract testを追加。
- D-061として一件ownership migration、Provisional memory、RCON Deferredを記録。
- target AL2023 lockがPhase 1 current releaseより古い点をDecision Neededとして記録した。当時は勝手にlock変更しなかった。

### 10.3 Synthetic fixture

fixtureは毎回専用temporary rootへ作成し、実world、実`server.properties`、実RCON password、AWS secretを使わなかった。

概念構成:

```text
temporary-root/
  data/
    eula.txt
    server.properties         # dummy content only
    preexisting/
      ordinary.txt
      nested/
        sentinel.txt          # 4242:4343 / 0600
```

container inputの要点:

```text
UID=993
GID=993
SKIP_CHOWN_DATA=true
VERSION=26.2
TYPE=VANILLA
ENABLE_RCON=false
SETUP_ONLY=true
INIT_MEMORY=1G
MAX_MEMORY=2G
```

`SETUP_ONLY=true`によりMinecraft processを起動せず、configuration realizationだけを検証した。

### 10.4 重要な検証条件

- remote manifestのtop-level digestが固定値と一致。
- exact tag+digestをpull。
- pulled imageのRepoDigestとarchitectureを確認。
- `0:993 / 0640`でsetupが失敗。
- 単なるnon-zeroだけでなく、logに次のいずれかがあることを要求。

```text
AccessDeniedException
Permission denied
```

- migrationでは`server.properties`一件だけを`chown 993:993`。
- migration前後でcontent hash不変。
- 成功後の`server.properties`は`993:993 / 0640 / regular file`。
- symlinkなし、extended ACLなし、inode replacementなし。
- `difficulty=hard`、`enable-rcon=false`がrealize済み。
- preexisting subtreeのpath、UID:GID、mode、typeを前後比較。
- sentinel `4242:4343 / 0600`が不変。
- 同一inputの2回目setupでhash、metadata、inodeが不変。
- RCON disabled時に次が存在しない。

```text
.rcon-cli.env
.rcon-cli.yaml
```

## 11. CIで発生したエラー、原因、修正

Phase 2b-1では、一度でgreenにせず、失敗原因を見えるようにしながらharnessを修正した。重要なのは、必要なtest条件を弱めず、CI環境で正しく観測できるようにした点である。

### 11.1 Commit列

```text
23e9e6d test: validate phase 2b ownership migration
8df8356 fix: verify pulled itzg digest in CI
b454b5b fix: inspect the pinned image manifest
7647b91 test: annotate integration harness failures
01ecb94 fix: inspect protected integration fixtures
576707e fix: clarify protected fixture checks
```

### 11.2 Image digest検証の修正

初期harnessでは、tag+digest指定を使っていても、remote manifestとpull済みimageのどのdigestを比較しているかが曖昧だった。

修正:

- `docker buildx imagetools inspect`でremote top-level manifest digestを検査。
- exact digest referenceをpull。
- pull後のimage metadata/RepoDigestを照合。
- `linux/amd64`を明示。

これにより「tagだけでpullして偶然通った」状態を排除した。

### 11.3 CI log不足への診断追加

GitHub APIでjob failureは見えたが、public APIからraw logを直接得られない場面があった。そのためERR trapからworkflow annotationへ失敗lineを出すようにした。

重要なannotation原文:

```text
Unexpected Phase 2b-1 harness failure at line 72 with status 1
```

この診断追加によって、失敗がitzgのcompatibilityではなくfixture準備にあると特定できた。

### 11.4 Protected fixtureをrunner userが読めない

失敗した行の周辺は次だった。

```sh
sudo chown 993:993 "$data_dir"
chmod 0750 "$data_dir"
```

原因:

- directoryを先に`993:993`へ変更した。
- GitHub runner userはownerでもgroup 993でもない。
- mode 0750なのでrunner userがその後の`chmod`やmetadata inspectionを実行できない。
- これはitzgのfailureではなく、host-side test harness自身の権限問題だった。

修正:

- fixture作成後の`chmod`を`sudo chmod`へ変更。
- `stat`、`find`、`sha256sum`、`getfacl`、`grep`、existence/symlink checkも必要箇所だけ`sudo`経由にした。
- containerのUID/GID、mount、itzg input、test expectationは変更しなかった。

代表的な修正:

```sh
actual=$(sudo stat -c '%u:%g:%a:%F' "$path")
preexisting_before=$(sudo find "$data_dir/preexisting" -xdev \
  -printf '%P|%U:%G|%m|%y\n' | sort)
server_hash_before=$(sudo sha256sum "$data_dir/server.properties" | awk '{print $1}')
```

### 11.5 shellcheck failure

sudo化後、integration jobがcontainer実行前に失敗した。quality jobは成功しており、短い実行時間とworkflow構成からshellcheck段階のfailureと判断した。

曖昧な形:

```sh
sudo test ! -e file1 && sudo test ! -e file2 || fail '...'
```

これは`A && B || C`の制御構造がshellcheckで問題になる。次の明示的な`if`へ変更した。

```sh
if sudo test -e "$data_dir/.rcon-cli.env" || \
   sudo test -e "$data_dir/.rcon-cli.yaml"; then
  fail 'RCON secret artifacts exist while RCON is disabled'
fi
```

symlink checkも同様に明示した。

```sh
if sudo test -L "$data_dir/server.properties"; then
  fail 'server.properties became a symlink'
fi
```

これによりshellcheckを通過し、Docker integration本体へ進んだ。

## 12. 実行した重要なコマンドと目的

### 12.1 Local static validation

```sh
bash -n tests/integration/test_itzg_ownership.sh
```

目的: shell scriptの構文を、Dockerを実行せず確認する。

```sh
.venv/bin/pytest tests/unit/test_host_runtime.py -q
```

目的: Host Runtime static contractとintegration harness contractの対象testを短時間で再確認する。

```sh
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src infrastructure tests
.venv/bin/cdk synth --context stage=dev
git diff --check
```

目的: 既存品質ゲートを弱めず、unit/regression、lint、format、type、IaC synth、whitespace errorを確認する。

ローカルMacにはDockerとshellcheckが存在しなかったため、新規installせず、Docker依存検証とshellcheckはGitHub Actionsへ委譲した。

### 12.2 Commit / push

代表例:

```sh
git add tests/integration/test_itzg_ownership.sh
git commit -m 'fix: inspect protected integration fixtures'
git push origin main
```

目的: failure原因ごとの小さな修正を履歴に残し、同じGitHub Actions環境で再検証する。

### 12.3 GitHub Actions status確認

ローカルに`gh`がなかった。

原文:

```text
zsh:1: command not found: gh
```

そのためpublic GitHub APIをread-onlyで使用した。

```sh
curl -fsSL \
  'https://api.github.com/repos/eash-misoni/wishicraft-server/actions/runs?branch=main&event=push&per_page=5' \
  | jq -c '.workflow_runs[] | {id, name, status, conclusion, html_url, head_sha}'
```

最初はsandboxのnetwork制限で失敗した。

原文:

```text
curl: (6) Could not resolve host: api.github.com
```

これはGitHub側やrepositoryの障害ではなくlocal sandboxのDNS/network制限だった。read-only CI確認として許可を得て再実行した。

job別確認:

```sh
curl -fsSL \
  'https://api.github.com/repos/eash-misoni/wishicraft-server/actions/runs/<run-id>/jobs' \
  | jq -c '.jobs[] | {id,name,status,conclusion,started_at,completed_at}'
```

annotation確認:

```sh
curl -fsSL -H 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/eash-misoni/wishicraft-server/check-runs/<job-id>/annotations' \
  | jq -c '.[] | {path,start_line,end_line,annotation_level,message,title,raw_details}'
```

### 12.4 Final repository確認

```sh
git rev-parse HEAD
git status --short
git status --branch --short
git log --oneline 34759b4..HEAD
```

目的: 最終HEAD、clean worktree、`origin/main`との一致、Phase 2b-1 commit列を確認する。

## 13. 検証結果

### 13.1 Local

```text
pytest:             189 passed
Ruff lint:          success
Ruff format check:  success (56 files)
mypy:               success (35 source files)
shell syntax:       success
CDK synth dev:      success
git diff --check:   success
Docker integration: local未実行
```

### 13.2 GitHub Actions

最終run:

```text
Run ID:      32581277132
Head SHA:    576707eb788d2c0b6deac24b04b4ad467177a3e5
Conclusion:  success
```

job結果:

```text
quality:                   success
host-runtime-integration:  success
```

Docker integrationによって実証したこと:

- fixed release tag+digest、linux/amd64が一致。
- `0:993 / 0640`はproperties update permission failureになる。
- `993:993 / 0640`への一件migration後はrealization成功。
- owner/group/mode/regular-file/inode/ACL条件を維持。
- `SKIP_CHOWN_DATA=true`でsentinelを含む既存subtreeのrecursive ownership変更なし。
- 同一inputの再setupがidempotent。
- `ENABLE_RCON=false`時に不要なRCON client secret artifactなし。

## 14. 技術的に理解しておくべき内容

### 14.1 Numeric identityはfilesystem contract

container内のusernameではなく、bind mount上ではnumeric UID/GIDが権限判定に使われる。したがって`993:993`はtarget hostでも明示的に作成・collision確認すべきidentityである。

### 14.2 Readできることとwriteできることは別

`0:993 / 0640`はgroup 993からreadできるがwriteできない。既存設定を読むだけなら通っても、itzgが値をrealizeしようとした瞬間に失敗する。integration testでは「更新が必要な入力」を意図的に与える必要がある。

### 14.3 SKIP_CHOWN_DATAはpermission migrationではない

`SKIP_CHOWN_DATA=true`は安全な既存EBS利用のためrecursive chownを止める。一方、個別fileの不整合はそのまま残るため、厳格なpreflightと限定migrationが必要である。

### 14.4 Inode、mode、ACLもcompatibilityの一部

ownerだけを確認すると、helperがtemporary file renameでinodeを置換したり、modeやACLを変えたりする可能性を見落とす。今回のfixtureはowner/group/modeに加え、regular file、symlink、ACL、inode、content hashも確認した。

### 14.5 Desiredとappliedを混同しない

Control Planeが要求を受理したらdesired revisionは進む。runtimeが失敗してもdesiredを旧値に戻してはいけない。rendered/appliedを別に持つことで未収束を明示できる。

### 14.6 Timeoutは大小比較だけでなくscopeと直列和を見る

save 60秒とstop 180秒が直列なら、両方を包むwrapperは少なくとも240秒超とmarginが必要である。各timeoutが何を内包するかをsequenceとして定義しなければ、上位が下位のgraceful shutdownを途中で殺す。

### 14.7 Phase 1 observationはPhase 2 targetを証明しない

Phase 1 hostで観測したmemory、kernel、stop時間、filesystem metadataはmigration inputとして有用だが、target kernelでのDocker、Compose、itzg、OOM、shutdown挙動はtarget hostで別途検証が必要である。

### 14.8 Integration harness自身にもpermission modelがある

fixtureをcontainer UIDへchownすると、CI runner userがfixtureを読めなくなることがある。test対象のpermissionを緩めるのではなく、host-side oracleだけを必要最小限の`sudo`で実行するのが正しい。

## 15. セッション終了時点のrepository状態

```text
HEAD: 576707eb788d2c0b6deac24b04b4ad467177a3e5
branch: main
remote: origin/mainと一致
worktree: clean
CI: success
```

このセッション中、Phase 2b-1のrepository実装以外では、AWS resource、EC2、SSM、secret、実data EBSへ変更を加えていない。filesystem preflight時の一時的なSG 25565 revoke/restore、EC2通常起動/停止、SSM read-only observationは、その依頼で明示許可された安全sequence内で実施し、終了時にinstance stoppedとSG復元を確認した。

## 16. セッション終了時点の残作業

Phase 2b-1終了時点で、次が残っていた。

1. Phase 2 target AL2023 release lockを、target EC2作成前に再確認する。
2. target host上でUID/GID 993 collisionがないことを確認し、明示identityを作る。
3. target hostへDocker/Composeを導入し、version/checksum/NEVRAを観測・記録する。
4. fixed itzg imageのdigestとlinux/amd64をtarget hostでも検証する。
5. 実data EBS attach前にsynthetic dataでsetup/READY/memory/lifecycle/graceful stopを検証する。
6. Phase 1 Minecraft完全停止後だけ実data migrationへ進む。
7. 実`server.properties`がpreconditionどおり`0:993 / 0640`、regular file、non-symlink、ACLなしであることを再確認する。
8. contentを変更せず一件だけ`993:993 / 0640`へmigrationし、postflightする。
9. Phase 1 runtimeとPhase 2 Composeの同時起動をinterlockする。
10. existing worldでREADY、永続性、graceful stop、rollbackを検証する。
11. RCON integration前に`RCON_PASSWORD_FILE`、file mode、`.rcon-cli.*`、secret injection境界を決定・検証する。
12. desired/rendered/applied revisionの永続化とControl Plane reconciliationは後続Phaseで実装する。

次の明示許可が必要だった操作は、target EC2作成/deploy、Docker/Compose install、image pull/run、data EBS attach/mount、実`server.properties` ownership migration、Minecraft起動、SSM Run Command、snapshot、rollback操作である。
