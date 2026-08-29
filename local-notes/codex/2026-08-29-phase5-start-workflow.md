# Wishicraft Phase 5 START workflow・Host Runtime recovery学習記録

> 記録対象: Phase 5 repository実装、dev AWS integration、初回START失敗、Host Runtime artifact recovery、systemd shutdown ordering修正、再START、Phase 5 closeout。
>
> 主な作業日: 2026-08-29
>
> ノート作成日: 2026-08-29
>
> 用途: Phase 6へ進む前に、STARTを単なるEC2操作ではなくdesired-state convergenceとして扱う理由と、実AWSで判明したartifact・shutdown・endpointの学びを復習するための教材。
>
> 正本: 本noteは学習用であり、設計・契約の正本ではない。D-074〜D-076、requirements、architecture、domain/interface contracts、delivery planを優先する。
>
> 機密保護: credential、secret本文、生environment、不要なaccount/role識別子は記載しない。将来のsecret配置方式は値ではなく責務境界だけを扱う。

## 1. Phase 5の目的

Phase 5の目的は、Minecraftを安全に「起動するAPI」を作ることではなく、利用者のSTART要求を望ましい稼働状態まで収束させるworkflowを作ることだった。

```text
Admission
→ Operation / Lock
→ Desired RUNNING
→ EC2 start/running
→ SSM Online
→ typed Host Runtime START
→ Minecraft protocol READY
→ active Game一致
→ public IPv4
→ Route 53 UPSERT / INSYNC
→ endpoint一致
→ Operation terminal success
→ Lock / current_operation_id release
```

EC2がrunningになっても、Minecraft processが起動しているとは限らない。MinecraftがREADYでも、違うGameがactiveかもしれない。さらに動的public IPv4へDNSが追従していなければ利用者はcanonical endpointから接続できない。このため、START成功は一つのAWS API responseではなく、Control PlaneからMinecraft protocolとpublic endpointまでを横断する収束として定義した。

この設計では責務境界も維持する。

| 層 | STARTでの責務 |
|---|---|
| Control Plane | Desired、Operation/Lock、AWS orchestration、Reconcile、endpoint convergence |
| Host Runtime | mount guard、固定systemd/Compose操作、container lifecycle |
| itzg | Java/Minecraft process、Minecraft設定realization、protocol runtime |

Control PlaneはMinecraft内部fileを編集・解析せず、Data EBSをworld truthとしてそのまま使用する。

## 2. Desired stateとactual stateは別物

今回の初回START失敗後には次の状態が残った。

```text
Desired = RUNNING
desired_revision = 2
Actual = stopped
Observed = stopped / runtime not ready / DNS absent
```

Desiredは「今どうなっているか」ではなく「何へ収束させたいか」である。Actual stoppedは観測事実であり、DesiredをSTOPPEDへ戻す根拠ではない。

初回workflowはDesired RUNNINGへ更新した後、active Game確認で失敗した。ここで推測的rollbackを行うと、利用者の要求まで消してしまう。そこでDesired RUNNINGを保持し、fresh Reconcileでactualを確定した後、新しいOperationが同じDesiredへ再収束できるようにした。

同一Gameについて既にDesired RUNNINGなら、START retryはdesired valueを変えない。したがって`desired_revision`を2から3へ意味なく増加させず、revision 2のままEC2/SSM/runtime/DNS convergenceを再開した。

学習ポイントは次である。

- DesiredとObservedを一つのstatusに潰さない。
- workflow failureはDesired cancellationを意味しない。
- Actual修復のためにDesiredを一度STOPPEDへ書き換える必要はない。
- revisionは意味のあるDesired変更を表し、retry回数として使わない。

## 3. Phase 4 Operation / Lock foundationとの接続

Phase 5はPhase 4の排他基盤を実際のAWS副作用へ接続した最初のPhaseである。

Successful STARTでは次のidentityを使用した。

```text
operation_id = op-0ee8c401-a918-4893-a881-1d97492731dd
lease_id     = lease-a52df79c-c40e-45ce-844b-e1c139c851e8
```

`operation_id`は論理START要求を識別し、`lease_id`は現在のacquisitionを実行してよいexecutorであることを証明する。EC2 start、Host Runtime START、DNS write、terminal completion等のprotected side effect直前には、次を確認した。

```text
owner_operation_id == operation_id
stored lease_id == caller lease_id
lease has not expired
```

長時間のwait/poll中にはleaseをrenewする。`current_operation_id`はSystemState上で現在のwrite-side ownerを示し、別Operationのadmissionを防ぐ。成功またはowned failure cleanupでは、Operationをterminalへ遷移させるのと同じownership条件でLockと`current_operation_id`を解放する。

Phase 5でPhase 4契約が役立った場面は次である。

- 初回失敗後もOperationはterminal FAILED、Lock 0、current operationなしとして回復できた。
- expired Lockを通常admissionでtakeoverしなかった。
- new convergence STARTはprevious Operationがterminalであることを確認して受付した。
- lease loss後に副作用を続けないstate machine構造にした。
- duplicate requestは新しいOperationを作らなかった。

## 4. Standard Step Functionsの役割

STARTはEC2、SSM、Minecraft、Route 53をまたぎ、数分かかる。Lambda一回の実行でsleep/pollを抱えるより、Standard Step Functionsで状態と待機を明示する方が適している。

Standard workflowが担うものは次である。

- EC2 running、SSM Online、Minecraft READY、Route 53 INSYNCのpolling
- poll間のWait
- task別のretry、timeout、Catch
- lease renewalの挿入
- failure後のfresh Reconcileとowned cleanup
- transition historyと実行時間の証跡

LambdaはReconcileやdomain validation、固定START taskなど、変換・判断が必要な短い処理を担当する。待機そのものをLambdaへ閉じ込めない。

OperationとState Machine executionは同じものではない。

| 概念 | 意味 |
|---|---|
| Operation | 利用者が要求した論理的な仕事、idempotencyとterminal resultの正本 |
| State Machine execution | そのOperationを収束させるorchestration executor |

executionがAWS側で動いているかだけでOperationの意味を決めず、Operation/Lock ownershipと実状態を併せて判断する。

## 5. Typed Host Runtime operation

Control PlaneからHost Runtimeへのwrite-side commandは固定した。

```text
sudo /usr/local/libexec/wishicraft/operation-v1 START
```

wrapperはliteral `START`だけを許可し、固定`wishicraft-host-runtime.service`のsystemd startへ変換する。外部requestからinstance ID、path、shell fragment、Minecraft commandを受け取らない。

任意shellを許すと、Control Planeの入力validationがhost root command executionの安全境界になり、command injection、誤操作、Data EBSへの越権操作が可能になる。typed operationなら、APIが表現できる能力を必要な一種類へ限定できる。

責務は次のように分かれる。

```text
Control Plane: STARTすべきか、ownershipがあるかを判断
Host wrapper:  STARTというtyped intentを固定systemd actionへ変換
systemd:       mount/Docker/Host Runtimeの依存とlifecycleを実行
itzg:          Minecraft processをrealize
```

## 6. protocol-aware READY

START成功をEC2 running、Docker active、container running、container healthだけで判定しなかった。これらは下位runtimeが存在する証拠だが、Minecraft Java protocolが利用可能である証拠ではない。

READY観測ではlocalhost gameplay portへJava Server List Pingを行い、Minecraftとして応答することを確認する。さらに次を独立して確認する。

- expected Minecraft version/runtime契約
- expected active Gameとobserved active Gameの一致
- public IPv4の割当
- canonical DNS A record
- DNS値とcurrent Target IPv4の一致
- discrepancyなしのendpoint health

特にruntime READY、desired convergence、Operation successを同一概念にしない。Minecraftがprotocol READYでもactive GameまたはDNSが不一致なら、START workflowはまだ成功していない。

## 7. 最初のSTARTが失敗した理由

初回AWS integrationは次まで成功した。

```text
EC2 start
SSM Online
typed Host Runtime START
container running
Minecraft protocol READY
player_count = 0
```

しかしactive Game observationは`unknown`だった。そのためDNS副作用前のSTART-005 preconditionがfail-closedし、OperationはFAILEDになった。Route 53 UPSERTには到達しなかった。

これはMinecraftが壊れた事例ではない。Minecraftは実際にprotocol READYだった。原因はproduction Targetへ導入済みのCompose artifactが、Phase 3で追加されたactive-game observation contractより古く、必要なlabelsを持っていなかったことだった。

つまり障害分類は次である。

```text
Minecraft process failure        ではない
world/data corruption            ではない
Control Plane observation bug    ではない
production artifact/version drift である
```

strictなobservationがこのdriftを検出し、正体不明のGameをpublic endpointへ公開する前に停止した。この失敗はREADYを弱める理由ではなく、production artifactをcontractへ追従させる理由になった。

## 8. active-game identityのrealization

修正後のComposeはcontainerへ次を付与した。

```text
com.wishicraft.active-game-id = game-vanilla-main
com.wishicraft.active-game-data-source = /srv/minecraft/games/game-vanilla-main/server
```

probeはさらにDocker inspectで実際の`/data` bind sourceが一意であり、宣言data sourceと一致することを確認する。

```text
explicit logical Game label
+ declared data source label
+ unique actual /data bind
→ observed active Game
```

directory名からGame IDを推測しないのは、path layoutは実装詳細でありlogical identityの正本ではないからである。rename、symlink、誤bind、将来のstorage layout変更があっても、名前がそれらしく見えるだけで正しいGameと判定してはならない。明示metadataと実bindを照合すれば「宣言」と「実体」の両方を確認できる。

## 9. manual StopInstancesで見つかったshutdown race

初回integrationが利用上限で中断した後、Target EC2は手動で停止された。そのjournalでは次が並行していた。

```text
Host Runtime ExecStop開始
/srv/minecraft unmount開始
stop wrapper mount guard
→ FAIL:MOUNT_SOURCE
```

stop wrapperは、world data sourceが期待するData EBS mountであることを確認してからCompose stopを行う。ところがsystemd graph上でHost Runtime serviceと実`/srv/minecraft` mountの直接orderingが不足していたため、shutdown transactionがmount unmountを先行させた。mount guardがfail-closedしたのは正しいが、その結果Minecraft graceful stopは証明できなかった。

「独自mount準備serviceの後にHost Runtimeをstartする」だけでは、shutdown時の実mount unitとの逆順まで保証しないことが学びだった。

## 10. `RequiresMountsFor`とshutdown ordering

Host Runtime unitへ次を追加した。

```ini
RequiresMountsFor=/srv/minecraft
```

systemdはpathへ必要な実mount unitを解決し、Host Runtimeへ`Requires`/`After=srv-minecraft.mount`を生成する。start時はmount確立後にHost Runtimeが始まり、shutdown時は依存の逆順でHost Runtime停止が完了してからmountを外す。

修正後の実測は次だった。

```text
Host Runtime stop complete : 10:41:51.680530Z
mount unmount start        : 10:41:51.712191Z
```

したがって実際の順序は次になった。

```text
Host Runtime ExecStop
→ itzg/Minecraft graceful shutdown
→ container stopped
→ Host Runtime stop complete
→ srv-minecraft.mount unmount
```

worldが存在するfilesystemをMinecraft停止より先に外さないことは、単なるsystemdの美しさではなくsave integrityの前提である。

## 11. graceful shutdown evidenceをどう読むか

修正後のcontrolled systemd poweroffでは次を確認した。

| evidence | 証明すること |
|---|---|
| players/world保存log | Minecraft shutdown pathがsave処理へ到達した |
| all dimensions saved | overworld、Nether、Endを含むchunk保存が完了した |
| runner `Done` | itzg runnerがgraceful stop完了を認識した |
| container exit 0 | runtime processが正常終了した |
| `OOMKilled=false` | memory pressureによる強制終了ではない |
| `RestartCount=0` | stopまでに隠れた再起動がなかった |
| SIGKILL/exit 137なし | timeout後の強制killで終了したのではない |

EC2 `stopped`は、computeが停止したという最終状態しか示さない。Minecraftがsaveしたか、containerが正常終了したか、mountが最後まで利用可能だったかは分からない。そのため「EC2 stopped = graceful shutdown成功」と推測してはならない。

初回manual stopはgraceful shutdown not proven、修正後validationだけがgraceful shutdown confirmedである。この二つの証跡を混ぜないことも重要である。

## 12. approved-predecessor atomic upgrade

production Host Runtime artifactは、単純な上書きではなく次の手順で更新した。

```text
current regular-file / owner / mode確認
→ predecessor SHA-256がapproved set内か確認
→ fixed repository artifactを同一directoryのtemporary fileへrender
→ temporary content / owner / mode検証
→ atomic rename
→ installed SHA-256 / owner / mode再確認
→ systemd daemon-reload / generated dependency確認
```

SSMから任意Compose payloadやpathを渡さず、repositoryでreview/CI済みの固定artifactだけを適用した。

predecessor制限には二つの意味がある。

1. どの既知versionから何へ更新したかを証明できる。
2. 人間変更、別version、partial corruption等の未知artifactを黙って破壊しない。

atomic renameは途中失敗で半分だけ書かれたproduction fileを残さない。post-checksumはrename成功だけでなく、最終配置されたbytesが期待値であることを確認する。

## 13. Phase 5からのpublic endpoint baseline

network baselineはPhase 5で変わった。

```text
Phase 4以前: Target SG ingress 0
Phase 5以降: Minecraft gameplay TCP 25565のみpublic
```

公開しないものは変わらない。

- SSH
- RCON
- management port
- arbitrary administration endpoint

gameplay ingressを開けるだけではendpoint convergenceではない。workflowは次を行った。

```text
current public IPv4 observation
→ canonical A record UPSERT
→ Route 53 change INSYNC待ち
→ fresh Reconcile
→ A record == current Target IPv4
→ endpoint discrepancyなし
```

DNS writeをruntime READY/active Game確認より後に置くことで、正しくないruntimeをcanonical endpointへ公開しない。

## 14. DNSはEC2 lifecycleの一部

TargetはElastic IPを持たないため、stop/startでpublic IPv4が変わり得る。過去のA recordが存在していても、現在のTarget IPv4と一致しなければstale endpointである。

したがって次は別々に観測する。

```text
EC2 state
current public IPv4
DNS record presence
DNS record values
Route 53 propagation state
```

DNSが`present`であるだけでは成功にしない。current Target IPv4との一致とINSYNCを確認して初めて、利用者が固定FQDNから現在のMinecraftへ到達できる。

Successful START後の実測は次だった。

```text
FQDN       = mc-dev.wishicraft.net
Target IPv4 = 52.68.217.91
DNS IPv4    = 52.68.217.91
Health      = HEALTHY
Discrepancy = none
```

## 15. duplicate idempotency

成功後、同じidempotency keyと同じpayloadをAdmissionへ再送した。結果は次だった。

- same Operation
- `created=false`
- new State Machine executionなし
- new Lockなし
- EC2 bootなし
- Host Runtime STARTなし
- DNS writeなし

API retryとworkflow再実行は区別する必要がある。

```text
API retry:
  同じ外部要求が届いたか確認し、既存Operationを返す

workflow convergence retry:
  以前のOperationがterminal failureで、Desiredへ未収束のとき、
  新しいidempotency key / Operationとして収束を再開する
```

同じrequestの通信retryを、新しいMinecraft起動workflowへ変換しないことがidempotencyの役割である。

## 16. leaseの実測

Successful START executionの実測値は次である。

```text
start          = 2026-08-29T10:45:05.131Z
stop           = 2026-08-29T10:49:08.190Z
duration       = 243.059 seconds
lease duration = 900 seconds
renew interval = 120 seconds
renew observed = 5 times
```

243秒に対して900秒leaseは十分なmarginを持ち、EC2/SSM/READY/DNS poll中のrenewも機能した。ただしこの一回のdev STARTだけで恒久値にはしない。

理由は次である。

- cold boot、image/runtime状態、AWS latencyでSTART時間は変動する。
- Phase 6 STOPはsave量、player/world状態、shutdown timeoutという別の時間特性を持つ。
- leaseが長すぎるとstale owner recoveryが遅くなり、短すぎると正常workflowがownershipを失う。

そのため900/120はProvisionalのまま、Phase 6 STOP実測後に両workflowを見て再評価する。

## 17. D-075 RCON Decision

STARTはsystemd Host Runtime起動だけで完結し、Minecraft内部commandを必要としない。そのためPhase 5ではRCONを有効化・使用しなかった。

D-075の境界は次である。

- Wishicraft独自RCON protocol clientを作らない。
- 将来必要なら固定itzg container内の`rcon-cli`を使う。
- secret本文はHost Runtimeだけがmanaged sourceから取得する。
- ephemeral fileをread-only bindし、`RCON_PASSWORD_FILE`でitzgへ渡す。
- RCON portをhost publish/SG ingressへ追加しない。
- APIからarbitrary Minecraft commandを受け付けず、typed allowlist operationだけにする。

Phase 6 STOPでMinecraft-aware save/stop commandが必要になる可能性はあるが、使用方式と初回secret適用はPhase 6で検討・承認すべき事項である。本noteでは設計を確定しない。

## 18. 実AWSから得た学び

### 18.1 EC2 lifecycle

`StartInstances`成功はworkflowの途中にすぎない。running到達後もSSM、runtime、protocol、endpointを待つ。stop/startでpublic IPv4が変わることもendpoint設計へ組み込む。

### 18.2 SSM Online

EC2 running直後にRun Commandを送れるとは限らない。managed-node Onlineを独立pollし、Online後だけ固定Host Runtime operationを送る。

### 18.3 Standard Step Functions

Wait、poll、renew、retry、timeout、Catchを可視化し、約4分のworkflowをLambda timeoutから分離できた。execution historyは各AWS transitionの実測証跡になった。

### 18.4 Lambda orchestration task

LambdaはTarget exactly-one resolution、domain validation、fixed SSM command、Reconcile等の短い責務に限定した。任意command executorにはしなかった。

### 18.5 DynamoDB Operation / Lock

atomic admission、current owner、lease renewal、terminal cleanupが実副作用をfenceした。workflow failure後もDesired/Observed/Operationを別々に保存できた。

### 18.6 Route 53 INSYNC

change requestのacceptだけでなくINSYNCとfresh endpoint observationを待つ必要がある。DNSはwrite-only resourceではなくReconcile対象である。

### 18.7 systemd ordering

service名上の論理依存だけでは実mount shutdown orderingを保証できない。実pathからmount unit dependencyを生成し、journal timestampで逆順停止を証明した。

### 18.8 CloudFormation stack isolation

Phase 1、Target、Control Planeを個別diff/deployしたため、Frozen Phase 1のhistorical replacement差分を誤deployせずに済んだ。Target変更はgameplay SG、Control Plane変更はSTART workflowへ限定できた。

### 18.9 SG gameplay exposure

Phase 5以降の正常baselineはingress 0ではない。TCP 25565だけをgameplay用に公開し、SSH/RCON/managementを0のまま保つ。後続Phaseが古い「ingress 0」を機械的に復元してはいけない。

## 19. 安全設計上の学び

### READYを弱くしない

初回failureはprotocol READY後に起きた。もしEC2/containerだけをsuccessにしていれば、active Game不明のruntimeを公開していた。厳しいsuccess semanticsが事故をDNS write前で止めた。

### observationはartifact driftを検出する

source repositoryが正しくてもproduction artifactが古ければ実状態は契約を満たさない。Reconcileは「動いているように見える」ことではなく、必要なmetadataとbindを実測した。

### actualとdesiredを混同しない

Actual stoppedを理由にDesiredをSTOPPEDへ書き換えず、RUNNINGへ再収束した。Observed freshnessとDesired revisionを別々に扱った。

### AWS副作用後に推測的rollbackしない

EC2 start後のfailureで「元の状態へ戻った」と仮定しない。fresh Reconcileでactual、DNS、Operation/Lockを確認し、Desiredも暗黙に戻さない。

### worldをControl Planeから触らない

Data EBSは唯一のworld truthであり、Phase 5はdetach/attach、format、migration、restore、内部file編集をしなかった。Control PlaneはHost Runtime/itzgへlifecycle intentを渡す。

### Frozen rollback environmentを守る

Phase 1 stackには既知historical diffがあったがdeployしなかった。Phase 5の都合でAMI、UserData、旧attachment、retirementを変更しない。

### management planeをpublicにしない

public exposureはgameplay TCP 25565だけである。SSM、Host Runtime operation、将来のRCONはprivate management pathに留める。

## 20. Successful STARTの最終状態

```text
Operation      = op-0ee8c401-a918-4893-a881-1d97492731dd / SUCCEEDED
Actual         = RUNNING
Desired        = RUNNING revision 2
Protocol       = READY
Active Game    = game-vanilla-main
Player count   = 0
DNS            = mc-dev.wishicraft.net
IPv4           = 52.68.217.91
Health         = HEALTHY
Discrepancies  = none
Lock           = none
Current Op     = none
```

この状態は、EC2だけでなくDesired、runtime、Game identity、DNS endpoint、Operation ownershipが同時に収束したことを示す。

## 21. Phase 6 STOPへの引き継ぎ

Phase 6では少なくとも次を一つのSTOP convergenceとして考える必要がある。

```text
Admission / Operation / Lock
→ fresh Reconcile
→ Desired STOPPED
→ graceful save
→ graceful runtime stop
→ container/process停止証明
→ EC2 stop
→ stopped確認
→ DNS cleanup / INSYNC
→ fresh endpoint observation
→ terminal cleanup
```

検討すべき問いは次である。

- save failure時にどこまで停止を進め、どこでfail closedするか。
- Host Runtime停止、EC2停止、DNS削除、Desired更新の順序とfailure semantics。
- AWS副作用後のfresh Reconcileとowned cleanupをどう組み込むか。
- long save/shutdown中のlease renewと900/120の再評価。
- RCONが本当に必要か。必要ならtyped operation、container-local `rcon-cli`、ephemeral secret fileをどう適用するか。
- STOP成功とoperator emergency stopの証跡をどう区別するか。
- stopped後のstale DNSをどのowner条件で削除するか。

Phase 5の学びから導ける原則はあるが、Phase 6の具体的state machine、RCON/secret初適用、failure compensationはcanonical design reviewで確定する。本noteはそれらを先取り実装・決定しない。

## 22. まとめ

Phase 5で最も重要だったのは、STARTを「EC2を起動する命令」から「利用可能な正しいMinecraft endpointへ収束させるOperation」へ引き上げたことである。

初回失敗は、厳しいactive Game observationがproduction artifact driftを検出した安全な失敗だった。manual shutdown raceは、service dependencyを概念上書くだけでなく実mount unitとのsystemd graphを保証する必要を示した。approved-predecessor atomic upgradeと実機journalにより両方を修正・証明し、Desired RUNNING revision 2を保持したまま再収束できた。

Phase 4のOperation/Lock、Phase 3のReconcile、Phase 2のHost Runtime/itzg境界が、Phase 5で初めて一つのwrite-side workflowとして接続された。Phase 6ではこのfoundationを弱めず、保存・停止・DNS cleanupを同じ精度で扱う必要がある。
