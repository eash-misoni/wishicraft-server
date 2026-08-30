# Wishicraft Phase 6 STOP workflow・RCON lifecycle学習記録

この文書は、Wishicraft Phase 6で設計・実装・実AWS検証した内容を、後から理解し直すための学習記録である。

canonical specificationではない。現在の要件、契約、Decision、運用手順は、必ずcanonical docsを正本とする。

Phase 6は最終的にCompletedとなった。単にEC2を停止する機能ではなく、Minecraftのデータ安全性、Desired State、公開endpoint、Operation/Lockを一つの収束処理として扱うSTOP workflowを実証したPhaseだった。

## 1. Phase 6の目的

STOPの目的は、`StopInstances` APIを呼ぶことではない。利用者が望む状態を`STOPPED`へ変更し、Minecraftを保存して穏当に終了し、computeとendpointを片付け、最後に実状態を観測し直して、論理状態と物理状態が一致したことを証明することである。

概念的な順序は次のとおりだった。

```text
Desired STOPPEDへの収束
  → explicit Minecraft save
  → graceful runtime shutdown
  → EC2 stop
  → DNS cleanup
  → fresh observation
  → terminal convergence
```

EC2だけを止めると、world dataの保存、Minecraft processの終了理由、DNSの残存、Operationの完了、Observed Stateの鮮度が未確認のままになる。Phase 6では、それらを別々の契約として検証しながら、一つのSTOP operationとして完結させた。

## 2. 最終的なSTOP architecture

最終形のcanonical flowは次のとおりである。

```text
Admission
  → Operation作成・Lock取得
  → Desired STOPPED CAS
  → filesystem/runtime read-only guards
  → RCON authentication
  → fixed save-all flush
  → graceful Host Runtime stop
  → runtime stopped verification
  → EC2 StopInstances
  → stopped wait
  → DNS DELETE
  → Route 53 INSYNC
  → fresh Reconcile
  → terminal Operation
  → owned Lock/current_operation cleanup
```

長時間処理はStandard Step Functionsが進行を保持し、各protected side effectの直前にLock ownershipを再確認する。Host上ではControl Planeから任意shellを受けず、固定されたtyped operationが固定artifactを呼ぶ。Minecraft commandも外部入力にはせず、STOP内部の`save-all flush`だけに限定した。

重要なのは、途中の成功を全体成功と取り違えないことである。RCONが成功してもSTOP成功ではなく、EC2がstoppedでもDNSとObservedが未収束ならSTOP成功ではない。最終Reconcileとterminal Operationまでがworkflowの一部である。

## 3. Desired・Actual・Observed・Operation・DNSを分ける

Phase 6では、次の状態を互いに代用しないことが特に重要だった。

- **Desired**: 利用者が収束させたい状態。revision付きCASで変更する。
- **Actual**: AWSやhostに今存在する物理状態。
- **Observed**: Reconcileがある時刻にpersistしたActualの写像。`observed_at`より新しい観測だけが上書きできる。
- **Operation**: その収束要求の進行・成功・失敗。
- **DNS**: computeとは独立して残り得る公開endpointの状態。

実AWSでは、operatorによる安全停止後に次の不一致が存在した。

```text
Desired: RUNNING
Actual:  EC2 stopped
Observed: 古いRUNNING/READY
DNS:     停止前IPv4を指すstale record
```

ここでActualを根拠にDesiredをraw writeしたり、DNSを手作業で消したりはしなかった。fresh ReconcileでActual stoppedとstale endpointを保存し、その後canonical STOP admissionを通した。STOP workflowはDesiredをSTOPPEDへCASし、既に停止済みであることをfreshに判断して、不要なEC2/RCON/SSM処理をskipし、stale DNSだけをDELETEした。最終的にDesired・Actual・ObservedがSTOPPED、DNS absentへ収束した。

この例は「physical stateが正しい」ことと「system全体が収束済み」であることが別だとよく示している。

## 4. STOPはcommandではなくconvergence

STOPを「shutdown commandを今すぐ実行するAPI」と考えると、開始状態ごとに場当たり的な処理が必要になる。Phase 6では「Desired STOPPEDへ安全に収束させるoperation」と定義した。

したがって、代表的なbranchは次のようになる。

- Desired RUNNING・Actual running: DesiredをSTOPPEDへCASし、saveから通常STOPを行う。
- Desired STOPPED・Actual running: Desired revisionを無意味に増やさず、runtimeをSTOPPEDへ収束させる。
- Desired RUNNING・Actual stopped: DesiredをSTOPPEDへCASし、computeを再起動せずendpointなど残作業だけを収束させる。
- Desired STOPPED・Actual stopped: 不要なside effectなしで、DNSとfresh observationを確認して完了できる。

Actual already stoppedならMinecraftを起動し直してsaveしない。EC2も起動しない。RCONも呼ばない。stale DNSがあれば、そのcleanupだけをworkflowの所有権下で実行する。この設計によりSTOPのretry/resumeが現在のActualから前向きに進めるようになった。

## 5. Operation / Lockとの統合

Phase 4のOperation/Lock contractは、Phase 6の副作用を安全に連結する土台になった。

- `operation_id`は論理的な仕事とLock ownerを表す。
- `lease_id`は、そのLock acquisitionを現在保持するexecutor固有の証明である。
- `current_operation_id`はGameに対する現在のnon-terminal operationを指す。
- Desiredの更新は`desired_revision` CASで行う。
- DNS DELETE、typed STOP、EC2 StopInstancesなどの直前にowner・lease・expiryを確認する。
- workflow中はleaseをrenewし、長いsave/shutdown/wait中にもownershipを保つ。
- terminal化後は、自分が所有するLockと`current_operation_id`だけをconditionalにcleanupする。

expired Lockを通常takeoverする例外は設けなかった。stale operationはfresh Reconcile後のexplicit recoveryを使う。副作用途中の失敗でもDesiredを推測的にRUNNINGへ戻さない。

Idempotencyもpayload-awareである。同じkeyと同じpayloadなら同じOperationを返し、新しいexecution、Lock、Desired revision更新、save、EC2/DNS side effectを発生させない。同じkeyでpayloadが異なればrejectする。最終STOP後のduplicate requestでも、この契約を実AWSで確認した。

## 6. Leaseの実測とAccepted化

最終値は次のとおりである。

- lease duration: 900秒
- renew interval: 120秒

実測は、Phase 5 STARTが約243.059秒・renew 5回、Phase 6最終STARTが約243.499秒、最終STOPが約93.353秒・renew 6回だった。STOPではminimum remaining marginが約870秒確保されていた。

単にworkflow durationが900秒未満だから十分と判断したのではない。Standard Step Functions中のrenewが実際に動作し、STARTとSTOPの双方でprotected side effectを含むend-to-end executionを完了し、renew後の余裕も大きいことを確認した。その実測をもって900秒/120秒をProvisionalからAcceptedへ移した。

renew回数はwall-clock durationだけから直感的に推定せず、execution historyに記録された実測値を使うべきである。

## 7. Explicit saveとRCONの責務境界

systemdやitzgの通常shutdownでもMinecraftはsaveする。しかしPhase 6では、EC2停止へ進む前に保存要求を明示的に成功させる必要があった。graceful shutdownへの期待だけでは、saveを要求・確認した証拠にならないからである。

採用した経路は次のとおりである。

```text
Control Plane typed STOP
  → SSM
  → fixed Host Runtime operation
  → docker exec
  → itzg container-local rcon-cli
  → localhost RCON
  → fixed save-all flush
```

Wishicraft独自のRCON protocol clientは作らず、使用中のitzg imageが提供するcontainer-local `rcon-cli`を使った。Control Planeから任意Minecraft commandを受け付けず、command文字列はartifact内の`save-all flush`に固定した。RCON authenticationやsaveに失敗した場合はfail closedし、graceful stopやEC2 StopInstancesへ進まない。

## 8. RCON secret architecture

passwordは次の経路だけを通る。

```text
AWS managed SecureString
  → Targetの最小ssm:GetParameter権限
  → Host Runtime
  → ephemeral /run/wishicraft
  → read-only container password-file bind
  → itzg / rcon-cli
```

security contractは次のとおりである。

- plaintext passwordをGitへ置かない。
- password本文をSSM command argumentへ載せない。
- Compose environment本文へ埋め込まない。
- stdout、stderr、CloudWatchなどのlogへ出さない。
- hostへRCON portをpublishしない。
- Security GroupへRCON ingressを追加しない。
- IAMは固定parameterへの`GetParameter`に限定する。

secretの取得、ephemeral fileのprepare、owner/mode設定はHost Runtime側の責務である。persistentなData EBSをsecret storeとして使わない。

## 9. D-078: password ROとgenerated config RWを分ける

Phase 6で最も大きかった学びは、upstream imageの内部lifecycleを理解しないままmountのRO/RWを決めてはいけないことである。

itzgのstart-configurationは`HOME=/data`を使用し、runtime UID/GIDへdropして動く。`RCON_PASSWORD_FILE`からpasswordを読み、RCON CLI用に次のファイルを書き込む。

- `/data/.rcon-cli.env`
- `/data/.rcon-cli.yaml`

password inputとgenerated CLI configは、同じ「RCON関連file」でも責務が違う。最終的なD-078 contractは次のように区別した。

### Password file

password sourceは固定された`/run/wishicraft`配下に置き、containerへread-only bindする。containerがpassword inputを書き換える必要はない。

### Generated CLI config

upstream自身が書くため、次の固定2組だけをRW bindとして許可する。

```text
/run/wishicraft/rcon-cli.env
  → /data/.rcon-cli.env

/run/wishicraft/rcon-cli.yaml
  → /data/.rcon-cli.yaml
```

sourceはruntime UID/GID所有、mode 0600、regular file、non-symlinkでなければならない。Docker inspectではcanonical Compose service/container、exact source/destination、bind type、RW、重複や追加mountがないことを検証する。

これはupstream compatibilityのための固定2件限定例外である。「RCON関連mountはRWでよい」や「`/run`からなら任意のRW bindを許す」へ一般化してはいけない。passwordはRO、generated configだけがfixed-RWという境界を保つ。

## 10. Data EBSのzero-size backing placeholder

Docker nested bindのdestinationとして、Game data rootには次のunderlying fileが残ることがある。

- `.rcon-cli.env`
- `.rcon-cli.yaml`

これはbindがactiveな間にcontainerから見えるconfig本体ではなく、mount destinationのbacking placeholderである。最終contractでは、固定2 pathについて次の全条件を満たす場合だけknown managed artifactとして扱う。

- regular file
- non-symlink
- `root:root`
- mode `0644`
- size 0
- link count 1

container running時は、さらにDocker inspectで対応するexact nested bindを証明する。container stopped時も、この厳格なzero-size placeholderなら安全なmanaged artifactとして許容する。

non-zeroならcredential/configがData EBSへ永続化された可能性があるため、security/correctness failureとしてfail closedする。empty mountpoint artifactの存在とsecret persistenceを混同しないことが重要である。実際のgenerated configとcredentialはephemeralな`/run`側にある。

## 11. Preflightはread-only validationである

最終設計では、filesystem preflightを原則read-onlyにした。preflightの仕事は、期待したfilesystem、mount、Docker topologyが成立しているかを観測し、異常なら止めることである。

STOP critical pathで次の操作は行わない。

- `rm` / `unlink`
- `truncate`
- mountpointのreplace
- live bindの修復や再構成

検査前に対象を「きれいにして」しまうと、異常の証拠を消すだけでなく、live runtimeが利用中のfilesystem identityを壊し得る。mutationが必要ならprepare、migration、cleanupなど別責務に分離し、適切なinactive boundaryで行うべきである。

`stop-v1`の責務も、read-only guards、RCON availability、fixed save、graceful systemd stop、stopped verificationまでに限定した。

## 12. Failure historyと得られた教訓

### 12.1 Failure 1: filesystem preflight env不足

**症状:** typed STOPをsystemd外から実行すると、filesystem preflightに必要なcanonical environmentがなく、`MOUNT_GUARD_FAILED`となった。

**fail-closed:** explicit saveより前に停止し、Host Runtime stop、EC2 StopInstances、DNS DELETEには進まなかった。

**根因:** systemd unit経由のinvocation contextを暗黙に前提とし、external typed operationのenvironment sourcingをfixtureが表現していなかった。

**修正:** STOP helperが固定のcanonical host environmentを正しく読み込むcontractを追加した。

**教訓:** 同じscriptでも起動主体が違えばenvironment contractは違う。systemd、SSM、operator pathを別のinvocation fixtureとして検証する。

### 12.2 Failure 2: readonly `COMPOSE_FILE` collision

**症状:** `stop-v1`が`COMPOSE_FILE`をreadonly宣言した後、canonical host envをsourceして同じ変数へ代入し、`COMPOSE_FILE: readonly variable`で終了した。

**fail-closed:** filesystem guardの途中、saveより前に停止した。

**根因:** environmentを「値の集合」だけで考え、shellの代入順序とreadonly属性までcontractに含めていなかった。

**修正:** canonical envを安全な順序とscopeで読み、固定値検証とreadonly化が衝突しないようにした。

**教訓:** shell environment loadingは入力検証、代入順序、export/readonly semanticsまで含めてtestする。

### 12.3 Failure 3: placeholder deletionによるRCON failure

**症状:** filesystem preflightでunknown artifactとされたzero-size `.rcon-cli.env` / `.rcon-cli.yaml`をSTOP前に削除した。ところがそれらはrunning containerのnested bind destinationであり、live mount targetが失われ、`RCON authentication failed`となった。

**fail-closed:** RCON authenticationで停止し、explicit save、graceful stop、EC2、DNSには進まなかった。

**根因:** backing placeholderを単なる不要fileと分類し、Docker mount identityとitzgのgenerated-config lifecycleをfilesystem modelへ取り込んでいなかった。

**修正:** D-078で固定2件をknown managed mountpoint artifactとして定義し、host source、backing metadata、Docker source/destination/mode/container identityを一体で検証するようにした。delete behaviorは廃止した。

**教訓:** live mount topologyをSTOP preflightが変更してはいけない。filesystem pathの意味はstat情報だけでなく、runtime mount graphとupstreamのwrite behaviorを含めて判断する。

### 12.4 Failure 4: Docker inspect Go template parse error

**症状:** D-078を実機確認するDocker inspectのGo templateにsyntax errorがあり、production live validationでparseに失敗した。

**fail-closed:** canonical STOP Admissionより前のvalidationで検出し、save、shutdown、EC2、DNSのunsafe side effectはなかった。

**根因:** shell quotingを含む実際のDocker CLI integrationがrepository fixtureで完全に再現されていなかった。

**修正:** production invocationと同じ形でparseできる固定templateへ修正し、regression coverageを追加した。

**教訓:** unit fixtureがdomain logicを証明しても、shell→CLI→Go templateという境界のescapingまでは自動的に証明しない。productionと同じparserを通すcontract testが必要である。

## 13. Fail-closedをどう評価するか

4件のfailureはいずれも、explicit save、graceful runtime stop、EC2 StopInstances、DNS DELETEより前で止まった。DesiredはSTOPPEDへ変わった場合があっても、Actual runningを推測的に停止済みとは扱わず、DNSもraw cleanupしなかった。

Phase 6はproduction recoveryが多かったが、それは安全機構が無駄だったことを意味しない。逆に、filesystem ownership、environment、RCON authentication、Docker topologyのどれかを証明できない限り、より破壊的な副作用へ進まない設計が本番でも機能した証拠である。

fail closedは「エラーを返すこと」だけではない。失敗地点より後ろのside effectが0件であること、actual/observed discrepancyを隠さないこと、再試行を新しいOperationとして追跡できることまで含む。

## 14. Production fixture不足という共通原因

個々のbugの背後には、production runtime topologyをrepository fixtureが十分モデル化していなかったという共通原因があった。

不足していた代表例は次のとおりである。

- actual systemd invocation context
- host envのsource順序とshell属性
- Docker nested bindのsource/destination/mode
- Data EBS上のmountpoint filesystem metadata
- Docker inspect Go templateとshell quoting

production実測からsecretを除いたfixtureを作り、canonical Game root、zero-size placeholders、runtime-owned `/run` sources、exact Docker mounts、container/service identityを再現した。将来も、mockの理想状態だけでなく、実機で観測した安全なmetadataをsecret-free fixtureへ戻す価値が高い。

## 15. Maintenance bootstrapとhot-patch recovery

途中では、Minecraftがrunningのためartifactを更新できない一方、旧STOP artifactでは正常停止できないbootstrap問題が発生した。

最初のrecoveryでは、running-stateの`stop-v1`だけを3回hot-patchした。いずれもapproved predecessor checksum一致、helper非実行、single file、temporary validation、owner/mode設定、atomic replacementという厳格な限定例外だった。

しかし3回目の後、問題はhelper一つではなく、filesystem preflight、Docker nested bind lifecycle、itzg RCON config placementをまたぐcontract全体にあると判断した。そこでhot-patchの継続をやめた。

最終的には、Phase 5で安全性を確認済みの次のsystemd pathをmaintenance actionとして使った。

```text
systemctl stop wishicraft-host-runtime.service
```

これによりHost Runtime inactive、container stopped、Java/listener 0へ移し、その後は通常のinactive-only、approved-predecessor限定full artifact upgradeへ戻った。

このmaintenance stopは、explicit RCON saveを含むPhase 6 product STOP successではない。artifact upgradeの安全な前提を作るoperator actionである。hot-patchは通常のdeploy方式ではなく、限定されたrecovery手段であり、成功例を一般運用へ広げてはいけない。

## 16. systemdとData mountのshutdown ordering

Phase 5から次のordering contractを引き継いだ。

```text
wishicraft-host-runtime.service stop complete
  before
srv-minecraft.mount unmount start
```

Minecraft processがworldを保存・closeしている間にData EBS mountが先に消えると、graceful stopそのものがdata sourceを失う。`RequiresMountsFor`などのsystemd dependencyは、単なる起動順ではなくshutdown時に逆順のlifecycleを保証するためにも重要である。

最終E2Eでは、Host Runtime stop完了後にmount unmountが始まり、`FAIL:MOUNT_SOURCE`や強制終了がないことを実測した。Dockerのcontainer lifecycleとsystemdのmount lifecycleを別々にせず、一つのdependency graphとして設計する必要がある。

## 17. DNS cleanup ordering

Phase 6のcanonical orderingは次のとおりだった。

```text
graceful runtime stopped
  → EC2 stopped
  → canonical A record DELETE
  → Route 53 INSYNC
```

runtime停止前にDNSを消す設計にも利点はあるが、このPhaseではcanonical requirementを正として、compute停止の確認後にendpointを削除した。DELETE requestを出しただけで成功とはせず、Route 53 changeが`INSYNC`となり、record absentであることまで確認した。

途中failureでstale DNSが残っても、raw Route 53 cleanupはしなかった。DNS discrepancyをObservedへ残し、次のcanonical convergenceが所有権確認付きで片付ける。手作業で見た目だけ整えると、workflow failureとactual stateの証拠を隠してしまう。

## 18. 最終E2Eの実測

### START

- Operation: `op-691da46e-6b04-40d0-a635-a8c8335253cf`
- result: SUCCEEDED
- duration: 約243.499秒
- Minecraft protocol: READY
- active Game: canonical Gameと一致
- DNS: current public IPv4と一致
- Health: HEALTHY

running状態での固定validationは次を通過した。

```text
PASS:RAW_DEVICE_PREFLIGHT
PASS:MOUNT_GUARD
PASS:D078_DOCKER_NESTED_BIND
PASS:RCON_AUTHENTICATION
```

この順序を通過したことで、過去のfilesystem、mount、RCON contractの根因が解消されたと判断できた。

### STOP

- Operation: `op-cbff4fbd-dbfe-4d32-a4f6-62ea2fa84d57`
- result: SUCCEEDED
- duration: 約93.353秒
- Desired: RUNNING revision 6 → STOPPED revision 7
- `save-all flush`: 成功
- graceful Host Runtime/Minecraft shutdown: 成功
- container/process/listener: clean stop
- EC2: stopped
- DNS: DELETE後INSYNC、record absent
- final Reconcile: HEALTHY、discrepancyなし
- duplicate idempotency: 同一Operationを返し、新規side effectなし

save evidence、normal shutdown、container exit code 0、OOMKilled false、RestartCount 0、SIGKILL/137なし、mount orderingも合わせて確認した。EC2停止だけでなく、この一連の証拠が揃って初めてPhase 6 STOP successとした。

## 19. Phase 6終了時の安全状態

最終状態は次のとおりである。

- Actual: STOPPED
- Desired: STOPPED
- Observed: stopped
- DNS: absent
- public IPv4: absent
- Health: HEALTHY
- discrepancy: none
- Lock: none
- `current_operation_id`: none
- Phase 1: stopped / Frozen
- Data EBS: Targetへattached
- migration snapshot: retained

失敗したSTOP Operationsは履歴として保持した。失敗を削除せず、最終成功と並べて追跡できることもOperation modelの価値である。

## 20. 今回覚えておくこと

- lifecycle APIはcommand wrapperではなく、desired-state convergenceとして考える。
- Actual、Desired、Observed、Operation、DNSを混同しない。
- preflightはread-only validationにし、cleanupやrepairを混ぜない。
- destructiveなside effectほどworkflowの後ろへ置く。
- fail closedはproduction debuggingでも、dataと証拠を守る重要な機構である。
- upstream imageのHOME、UID/GID、生成fileを理解せずbind mountを設計しない。
- password ROとgenerated config fixed-RWを明確に区別し、例外を一般化しない。
- secret persistenceとzero-size backing mountpoint artifactを区別する。
- filesystem metadataだけでなくDocker runtime identityも検証する。
- production topologyをsecret-free test fixtureへ取り込む。
- shell environmentとtemplate escapingは実際のinvocation境界でtestする。
- systemd、Docker、mountを一つのlifecycle dependencyとして設計する。
- recovery hot-patchを通常のartifact deployment policyへ一般化しない。
- raw repairでdiscrepancyを隠さず、fresh Reconcileから前向きに収束する。
- STOP successはsave、graceful shutdown、compute、DNS、observation、Operationの全てで定義する。
