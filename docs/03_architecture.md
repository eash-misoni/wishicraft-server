# 03. Architecture

- **文書状態:** Canonical
- **最終更新:** 2026-08-31

## 1. アーキテクチャ方針

制御系をサーバーレスにし、常時稼働するコンピュートを持たない。Minecraft本体を動かすEC2だけを必要時に起動する。

Phase 1はhost上のJava、固定server.jar、`minecraft.service`、host firewallでlocalhost到達性を保証するRCONとして実装・検証し、2026-08-22に正式完了した。この実装とPhase 1 runbookはas-built履歴であり、書き換えない。

Phase 2以降は[itzg責務境界](architecture/itzg-responsibility-boundary.md)を正本とし、Control Plane（Wishicraft）、Host Runtime、Minecraft Runtime（itzg/docker-minecraft-server）の3層へ移行する。Wishicraftはdesired state、policy、認可、状態遷移、AWS resource、mapping/apply orchestrationを持つ。Host RuntimeはAL2023、EBS mount、Docker/Compose、systemd、secret injection、container lifecycleを持つ。Minecraft固有の取得・設定・互換性・起動停止は原則itzgへ委譲する。

Phase 2aはAWS適用前のstatic Host Runtime契約として開始した。D-062で固定したAL2023 release、kernel variant、region固有AMI identity、Compose checksum、itzg release tag/digest、initial tuning値からsecret-free artifactをrenderし、mount/identity/Phase 1 interlockを満たした場合だけ明示的なCompose操作を許す。Phase 1 `minecraft.service`はrollback先として残し、新unitはboot enableも自動restartも行わない。当時Observation Requiredだった既存EBS UID/GIDはPhase 2で`993:993`と観測・固定済みである。

Phase 2b-1では既存EBSのnumeric identity `993:993`を観測済みとし、`server.properties`だけに存在する`0:993` / `0640`を、Phase 1完全停止後の一回限りのHost Runtime migrationで`993:993` / `0640`へ変更する。Minecraft properties本文は編集せず、以後のrealizationはitzgへ委譲する。current dev memory targetはProvisionalなcontainer `2816 MiB`、Xms `1G`、Xmx `2G`である。

Phase 2 target hostはD-063により独立した`MinecraftTargetStack-dev`で作成する。target stackは既存VPC/subnetだけを明示IDで利用し、専用IAM role/profile、ingress 0の専用SG、固定AMIのEC2を所有する。D-066以降は、手動migration済みexisting data EBSの`AWS::EC2::VolumeAttachment`だけをResource Importでtarget stackへ取り込む。data EBSの`AWS::EC2::Volume`本体はPhase 1 stack所有のまま、Phase 1 stackはFrozenとし、DNSやsecretとのCloudFormation referenceは追加しない。

Phase 2 technical migrationはD-068で完了した。Data EBS Volume本体のownership移管とPhase 1 EC2/root/stack退役はrollback window終了後のDeferred cleanupであり、Phase 3の実測status実装を妨げない。Phase 3はTarget EC2を観測対象とし、Phase 1の直接Java `minecraft.service`ではなくHost Runtime、Docker container、itzgの実状態を段階的にprobeする。

初回実用版では、複数ゲームやWeb管理画面を実装せず、単一バニラゲームのDiscord start/status/stopを端から端まで完成させる。

## 2. 初回実用版の全体構成

```text
Discord
  └─ Interactions Endpoint
       └─ API Gateway HTTP API
            └─ Command Lambda
                 ├─ Discord署名検証・認可
                 ├─ DynamoDB TransactionによるOperation受付
                 ├─ Step Functions Standard開始
                 └─ Discord Deferred Response

Step Functions Standard
  ├─ Operation / Lock Lambda
  ├─ Reconcile Lambda
  ├─ EC2 API
  ├─ SSM Run Command
  ├─ Discord Message Lambda
  └─ DynamoDB

EventBridge
  ├─ EC2状態変化イベント
  ├─ 定期reconcile
  ├─ 自動停止判定
  └─ バックアップスケジュール

Route 53
  └─ 固定FQDN → 起動中EC2の動的パブリックIPv4

Minecraft EC2 / Host Runtime
  ├─ systemd / Docker / Compose
  ├─ itzg/docker-minecraft-server
  ├─ container-local management path（管理port非publish）
  ├─ desired state mapping/apply scripts
  ├─ heartbeat agent or systemd timer
  ├─ root EBS
  └─ data EBS

S3
  ├─ backups
  └─ later: immutable packages

Parameter Store
  ├─ public configuration
  └─ SecureString secrets

Later: Secrets Manager
  └─ automatic rotation or advanced secret management

CloudWatch / Budgets
  ├─ logs
  ├─ alarms
  └─ cost alerts
```

## 3. AWSサービスの責務

### API Gateway HTTP API

- Discord Interactionsの公開HTTPSエンドポイントを提供する。
- Command Lambdaへリクエストを渡す。
- Minecraft EC2へ直接接続しない。

初回実用版ではREST APIではなくHTTP APIを基本とする。必要な認証・統合機能で不足が判明した場合だけ再評価する。

### Command Lambda

責務を次に限定する。

1. Discord署名検証
2. Interaction解析
3. stage固定Guild、operation channel、player/admin roleの認可
4. 入力検証
5. DiscordへのDeferred Response
6. 既存Operation Admission serviceの呼出し
7. Admission結果に従う非同期executor開始

Command LambdaはControl Planeのexternal adapterであり、Desired State、Lock、`current_operation_id`、EC2、SSM、RCON、Minecraft、DNSを直接操作しない。START/STOP State MachineをAdmission抜きで開始せず、EC2起動完了、Minecraft READY、Reconcile完了をInteraction request中に待たない。Admission transactionとworkflow開始失敗時のowned cleanupは既存service contractを再利用する。

Phase 7Bのtrust boundaryはHTTP API payload format 2.0を受け、`isBase64Encoded`に従ってraw body bytesを一度だけ復元する。JSON parseや再serializeより先に、`X-Signature-Timestamp`のASCII bytesとraw bodyを連結し、stage設定のDiscord Public KeyでEd25519 signatureを検証する。欠落・不正header、unsupported content encoding、base64不正、署名不一致、Public Key設定不正はfail closedし、下流へ進めない。暗号実装はPyNaClをhash固定してLambda assetへbundleし、独自Ed25519実装を持たない。

署名後はApplication ID、Guild ID、operation channel IDをexact matchし、memberがplayer roleまたはadmin roleを持つことを検証する。Git正本の`/mc` commandとexact 1 subcommand（`status`、`start`、`stop`）以外を拒否する。Phase 7Bでは認証・認可済みcommandもAdmissionへ接続せず、「ingress検証済みだがOperation未受付」のephemeral responseを返す。PINGだけはPONGを返す。Phase 7C以降で同じ境界の後段へAdmissionとdeferred responseを接続する。

通常の`/mc status`、`/mc start`、`/mc stop`はadmin roleでもoperation channelだけを使用する。admin channelはPhase 7 MVPでは使用せず、後続のrecovery/reset/maintenance用に予約する。Discord command permissionはUX補助であり、LambdaのGuild/channel/role認可を代替しない。

### Step Functions Standard

start、stop、backup、reset等の長時間operationを管理する。

採用理由:

- 待機中にLambdaを占有しない。
- ステップ別の実行履歴を確認できる。
- Retry、Catch、Timeoutを明示できる。
- 途中失敗後にどこまで進んだか追跡できる。

初回はstartとstopで別state machineとする。

EC2、SSM、DynamoDB、Route 53の単純なAPI操作はStep FunctionsのAWS SDK統合を優先し、LambdaはReconcile、domain validation、Operation admission、Discordメッセージ、複雑な結果正規化等に限定する。Lambdaをstepごとに機械的に増やさない。

### DynamoDB

DynamoDBは実世界の状態そのものではなく、次を保存する。

- Desired State
- 最新Observed Stateのスナップショット
- Game定義
- Operation履歴
- idempotency keyの一意予約
- Operationロック
- 後期のPackage、Template、WebSocket connection等
- Phase 8以降のRuntimeHeartbeat

初回は複数テーブル方式とし、単一テーブル設計による最適化を優先しない。SystemStateは属性群ごとの部分更新を使用し、ReconcileがDesired StateやCurrent Operationを全項目書き戻しで上書きしない。

### Reconcile Lambda

- EC2 APIでインスタンス状態を取得する。
- running時だけSSM状態を確認する。
- SSM online時だけ、repository固定のversioned read-only Host Runtime probeをRun Commandで実行する。probeはmount、systemd、Docker daemon、Compose labelで一意に識別したcontainerをhost-localに観測し、running container内では固定`mc-monitor status`によるJava Server List Pingだけをlocalhost:25565へ実行する。online player count整数だけを正規化し、Minecraft内部file、environment、log、RCON、MOTD、player sample/name/UUID、raw responseをControl Planeへ取り込まない。transportとschemaを別々に検証してHost Runtime、container、Minecraft状態を正規化する。
- 観測結果を正規化する。
- 保存済みObserved Stateを条件付き更新する。
- 不一致や異常をoperation/logへ記録する。
- EC2がworkflow外で`stopped`または`terminated`となり、start operationが進行していない場合は、古い固定FQDNのAレコードを安全に削除するcleanupを起動する。

### SSM

- Session Manager: 管理者の調査用。
- Run Command: `probe_game`、`start_game`、`stop_game`、`backup_game`等を実行。

任意のユーザー入力をコマンド文字列へ連結しない。Lambdaは許可済みスクリプト名と正規化済みIDだけを渡す。

### Minecraft EC2

- systemdはEBS mount後のHost Runtime起動順序を管理し、container lifecycleはHost Runtimeで一元化する。
- Minecraftプロセス、Java、distribution、Minecraft固有設定はitzg containerに委譲する。
- データEBSを`/srv/minecraft`等へマウントする。
- `active_game_id`等のruntime情報を保持する。
- SSMからhost-local、container-localの順に管理commandを実行し、RCON等の管理portをhostやInternetへpublishしない。
- heartbeatをDynamoDBまたは専用受付先へ送る。

Wishicraftのdesired stateをitzgの公開入力へ変換し、boot-time configurationかrunning serverへのruntime operationかを選択する処理はControl Plane / Host Runtime側に残す。同じ設定をGitとDynamoDBの双方で独立管理せず、Minecraft実ファイルはitzgによるrealization結果として扱う。

### S3

初回:

- ワールドバックアップ
- backup manifest
- checksum

後期:

- 不変Package archive
- package manifest
- client pack情報

### Parameter Store

秘密でない設定の設計上の正本は`config/project.yaml`と`config/stages/<stage>.yaml`とする。Parameter Store Stringを使用する場合は、CDKがYAMLまたはdeploy結果から配布する実行時参照先とし、人間が独立して編集する第二の正本にはしない。

利用例:

- CDKが作成したMinecraft instance ID
- 複数runtimeから共通参照する公開ID
- deploy時に生成されたresource identifier

### Parameter Store SecureString

MVPの秘密情報を保存する。

- Discord Bot Token
- RCON secret
- 後期のDiscord OAuth Client Secret
- 後期のWeb session signing secret

コードやCDKへ秘密値を渡さず、Parameter名だけを設定として保持する。実行時IAM roleで復号して取得する。

Phase 1のRCON passwordは、EC2 roleだけが対象SecureStringの`ssm:GetParameter`を実行時に許可される。CDK、CloudFormation、user data、Git、通常ログへ実値を含めない。EC2内の許可済みbootstrap scriptはtraceを無効化して値を取得し、標準出力へ出さず、`server.properties`を`root:minecraft`所有・`0640`で作成する。Minecraft processは`minecraft` groupによるreadだけを持つ。RCON用のSecurity Group受信ルールは作成せず、Vanillaに専用bind address設定がないためhost firewallでIPv4の`127.0.0.1`およびIPv6の`::1`以外への到達を拒否する。

### Minecraft server artifact

Phase 1の初期vanilla serverは、stage設定に固定したMinecraft version、公式server.jar URL、公式SHA-1、size、リポジトリ固定SHA-256を使用した。これは完了済みas-builtである。Phase 2以降はdistribution取得をitzgへ委譲し、Wishicraft独自downloaderは新経路の同等性確認後の退役候補とする。itzg imageとMinecraft versionは浮動参照にせず、具体的な固定方法をPhase 2開始前Decisionで定める。

### Secrets Manager

自動rotationや高度な秘密管理が必要になった場合に再評価する。MVPの必須サービスにはしない。

### EventBridge

- EC2 state changeを受けてreconcileを起動する。
- workflow外のEC2停止・終了時に古いDNS Aレコードのcleanup判定を起動する。
- running中の定期状態確認を行う。
- 無人自動停止を判定する。
- 定期バックアップを起動する。


### Route 53

- 利用者がMinecraftクライアントへ一度登録して使い続ける固定FQDNを提供する。
- EC2起動後、現在の動的パブリックIPv4へAレコードをUPSERTする。
- Route 53変更が`INSYNC`となり、保存したDNS targetが現在のIPと一致してからオンライン完了とする。
- EC2停止完了後はAレコードを削除し、解放済みの古いIPを指し続けない。
- Hosted Zone ID、record name、TTLは設定として管理する。
- Route 53更新権限は対象Hosted Zoneと対象レコードに限定する。

### CloudWatch

- Lambda、Step Functions、EC2 agentの構造化ログ
- operation失敗
- EC2長時間running
- heartbeat停止
- 自動停止失敗
- backup失敗

ログ保持期間を明示し、無期限を初期値にしない。

## 4. ネットワーク構成

### Minecraft EC2

- Public subnetへ配置する。
- Internet Gateway経由でMinecraftクライアントから接続可能にする。
- EC2起動中だけ動的パブリックIPv4を使用する。Elastic IPは初期構成へ含めない。
- Route 53の固定FQDNを共通接続先とする。
- Security Groupの受信はMinecraftポートだけを基本とする。
- Minecraftは`online-mode`と静的ホワイトリストをMVPから有効にする。
- SSH、RCON、管理Webポートを公開しない。
- outbound HTTPSを許可し、SSM、S3、DynamoDB等へ到達できるようにする。
- EC2はIMDSv2を必須とし、instance metadata tagsを有効にしない。

### Lambda

- 原則としてユーザーVPCへ接続しない。
- AWS API、Discord API、DynamoDB、Step Functions、SSMを公開AWSエンドポイント経由で利用する。
- NAT Gatewayを作らない。

LambdaからEC2へ直接TCP接続せず、SSMを管理経路にすることでVPC接続を不要にする。

## 5. EC2ストレージ構成

### Root EBS

- OS
- Docker Engine / Compose等のHost Runtime（target architecture）
- SSM Agent
- systemd unit
- runtime code
- 再配備可能なスクリプト

### Data EBS

- EC2とは別リソースとして同一Availability Zoneへ固定する。
- 暗号化し、CDK削除やEC2置換で自動削除しない保持方針を設定する。
- filesystemがない場合だけ初期化し、UUIDで`/srv/minecraft`へmountする。
- mountされていない場合、Minecraft serviceと破壊的スクリプトを起動しない。
- mount準備oneshot serviceはEBS volume IDから実deviceを特定し、空volumeだけをXFS化してUUID mountを検証する。`minecraft.service`など後続unitはこのserviceとmount guardへ依存する。
- Gameディレクトリ
- ワールド
- server.properties
- config
- logsの必要部分
- runtime state
- ローカル一時backup
- Package cache

例:

```text
/srv/minecraft/
  games/
    game-vanilla-main/
      game.yaml
      server/
      runtime/
  runtime/
    active_game_id
    current_operation_id
    state.json
  scripts/
    probe_game.py
    start_game.py
    stop_game.py
    backup_game.py
  cache/
  staging/
  archives/
```

ゲームデータをroot volumeだけに置かない。

`server.properties`、whitelist等のMinecraft実ファイルをWishicraftとitzgの双方から直接編集しない。Gitはdeploy/基盤固定値、Control Plane storeは運用中desired state、AWS secret storeはsecret、data EBSはworldとrealization結果の所有者とする。

### Operation Admission service

Discord Command Lambda、管理CLI、integration testは同じOperation admission serviceを使用する。

競合operationでは、idempotency key予約、Operation作成、Lock取得、`current_operation_id`設定をDynamoDB Transactionで一体として行う。Phase 5、6のCLI確認でもState Machineを直接開始して受付処理を迂回しない。

Lockのlogical ownerはOperation ID、現在のacquisition possession proofは一意なlease IDである。renew、release、protected side effect前の確認は両IDと未期限切れを要求する。期限切れLockはstale Operation candidateとして通常admissionをblockし、fresh Reconcile後の明示recovery以外ではtakeoverしない。

Desired mutationは`desired_revision` CAS、Observed更新は`observed_at` freshness、Operation ownershipは`current_operation_id`条件で独立して保護する。

同じidempotency keyが再送された場合は、既存operation IDを返し、新しいOperationやworkflowを作成しない。


## 6. 初回startフロー

```text
Discord /mc start
→ Command Lambdaが署名・権限・入力を検証
→ Deferred Response
→ DynamoDB TransactionでIdempotency予約・Operation作成・Lock取得・current operation設定
→ Start State Machine開始
→ Lock所有権確認
→ Discord進捗先が設定済みならBot通常メッセージを作成しmessage_id保存
→ Discord進捗先がなければ進捗作成をskip
→ Reconcile
→ 起動可能性検証
→ Desired RUNNINGを保存
→ EC2 StartInstances
→ running待機
→ SSM online待機
→ start_game実行
→ Wait、Lock延長、probeを繰り返す
→ Minecraft状態とactive gameを確認
→ 現在のパブリックIPv4へRoute 53 Aレコードを更新
→ Route 53 `INSYNC`とDNS target一致を確認
→ READY条件確認
→ Operation成功
→ Discord公開メッセージ更新
→ Lock解放
```

失敗時はCatchでエラーを記録し、実状態を再観測してからロックを解放する。

Phase 5 repository implementationでは、admission Lambdaだけが新規START executionを開始する。workflow inputはadmission生成のOperation/lease identityだけで、Target instanceはtagによるexactly-one resolverが内部解決する。EC2、SSM、DNSのprotected write前にcurrent lease possessionを検証し、poll loopでrenewする。

Host Runtime write-side境界はD-075の固定`operation-v1 START`であり、systemdの固定Host Runtime unitだけを起動する。STARTにはMinecraft commandが不要なためRCONを有効化せず、secret injection、RCON publish、独自protocol clientを追加しない。既に同一Gameがprotocol-aware READYの場合はEC2/Host Runtime side effectをskipするが、Route 53 `INSYNC`とendpoint一致は改めて収束確認する。

Target SGはPhase 5 public endpointのためMinecraft TCP 25565だけを`0.0.0.0/0`から許可するrepository設計へ進める。online-modeと既存whitelistを前提とし、SSH、RCON、管理portはingress 0を維持する。このSG updateはpublic exposure変更のためcredential-backed diff/update前に明示承認を要求する。

## 7. 初回stopフロー

```text
Discord /mc stop
→ Deferred Response
→ DynamoDB TransactionでIdempotency予約・Operation作成・Lock取得・current operation設定
→ Stop State Machine開始
→ Lock所有権確認
→ Discord進捗先が設定済みならBot通常メッセージを作成しmessage_id保存
→ Discord進捗先がなければ進捗作成をskip
→ Reconcile
→ 停止可能性検証
→ Desired STOPPEDを保存
→ save要求
→ Minecraft stop要求
→ process停止確認
→ EC2 StopInstances
→ Wait、Lock延長、stopped確認
→ Route 53 Aレコード削除と`INSYNC`確認
→ 最終Reconcile
→ Operation成功
→ Discord更新
→ Lock解放
```

保存失敗時は通常停止を続行せず、管理者確認が必要な失敗とする。

Phase 6はSTART State Machineへbranchを混在させず、STOP専用Standard State MachineとTask Lambdaを使用する。Admission、Operation/Lock、Desired CAS、Reconcileは共有し、STOP固有のEC2 StopInstances、DNS DELETE、固定Host Runtime STOP権限だけを専用Taskへ与える。

Host Runtime STOPは固定`operation-v1 STOP`だけを受け付け、container-local `rcon-cli save-all flush`成功後に既存systemd unitを停止する。container/process/listener停止を確認するまでEC2停止へ進まない。RCON passwordはTarget roleがstage固定SecureStringだけを取得して`/run/wishicraft`へ0400で置き、RO bindと`RCON_PASSWORD_FILE`で渡す。itzg `start-configuration`が`HOME=/data`の`.rcon-cli.env`/`.rcon-cli.yaml`を書き込むため、この生成configのexact 2 mountだけはD-078のstrict RW exceptionとし、runtime UID/GID所有0600の`/run/wishicraft` sourceへ閉じ込める。Data EBS側にはroot:root 0644のzero-size backing placeholder以外を許可しない。RCON portはpublishせず、SG ingressも追加しない。

Actual EC2が既にstoppedなら、Desired RUNNING/STOPPEDのどちらからでもEC2やMinecraftを起動せず、Desired STOPPED CAS、stale DNS DELETE/INSYNC、fresh Reconcileへ収束する。canonical orderingは通常経路でsave、runtime stop、EC2 stop/stopped、DNS DELETE/INSYNC、final Reconcileである。

## 8. statusフロー

```text
Discord /mc status
→ 署名・Guild/channel/role検証
→ STATUS Operation admission（Idempotency + Operationのみ）
→ Deferred Response
→ Operations DynamoDB Stream INSERT filter
→ 非同期STATUS executor Lambda
→ Reconcile Lambda
→ EC2 state取得
→ runningならSSM確認
→ onlineならprobe実行
→ runningならパブリックIPv4とRoute 53 targetを確認
→ SystemStateのObserved属性群だけを条件付き部分更新
→ 既存unlocked STATUS terminalizationへ安全なresult projectionを保存
→ Phase 7D Message componentへ引渡し（Phase 7Cでは未送信）
```

利用者が明示的に実行したstatusはSTATUS Operationとして記録するが、operationロック、lease、`current_operation_id`、Desired updateは使用しない。Interaction handlerは既存Admission Lambdaの受付結果だけを待ってDeferred Responseを返し、fresh Reconcile完了まで待たない。現行Reconcileは1 Lambda invocationで完結しdurable waitを持たないため、D-085によりSTATUS executorはStandard State Machineではなくasync Lambdaとする。

Admission transactionが作成したOperations INSERTをStream sourceとするため、Operation commitとdispatch sourceの間に別writeのgapを作らない。同一Interactionは`discord:<interaction_id>`のpayload-aware idempotencyで同じOperationへ戻り、新規INSERTとexecutor dispatchを増やさない。Stream retryは同じoperation_idを再処理し、terminal Operationはfresh Reconcileを再実行せず終了する。永続failureはbounded retry後に暗号化DLQへ送り、未観測のまま捨てない。EventBridgeやworkflow内部のreconcileはOperationを作成しない。

## 8.1 Discord message projection

START/STOPの公開表示は原則1 Operationにつき1つのBot channel messageとし、Operationへ関連付けたmessage identityを条件付きで確定して更新する。Interaction Tokenは長時間更新へ使用・保存しない。Discord create/update failureはdelivery status/logとしてControl Plane operationと分離し、既に成功したMinecraft/AWS operationをFAILEDへ変えない。

Bot Tokenを読むのはDiscord Message componentだけとし、Command LambdaはPublic Keyだけで署名検証する。`/mc` command schemaはGit管理し、Discord API registrationはCDK deployと分離した明示operator actionとする。

Phase 7DのSTATUS deliveryは次の境界とする。

```text
STATUS terminal Operation + safe projection
→ Operations Stream MODIFY
→ Discord Message Lambda
→ delivery metadata CAS / Operation由来nonce
→ Discord channel Create Message (enforce_nonce=true)
→ message_id CAS
```

Interaction original responseはtoken有効期間15分と長時間STARTの不一致、およびtoken非永続化契約のため公開message identityに使わない。create成否不明retryは同じnonceで短い回復窓だけ再試行し、窓を越えればduplicateを作らずdelivery failureへ隔離する。retryable failureはdelivery metadataのdurable transitionからSQS delayへ接続し、Command/STATUS executorからMessage Lambdaをfire-and-forgetしない。

Phase 7EのSTART adapter/deliveryは次の境界とする。

```text
Discord /mc start
→ signature / Guild / channel / role authorization
→ shared START Admission（Operation / Lock / lease / Current Operation）
→ existing START Standard State Machine
→ Operation progress_revision付きstep/status transition
→ Operations Stream
→ initial normal message create、以後同一message edit
```

Command LambdaはAdmission Lambda invoke以外のControl Plane権限を持たない。`progress_revision`はControl Plane transitionと同じwriteで単調増加し、Message componentはevent revisionとconsistent current revisionを照合する。delivery metadataだけの更新ではrevisionが変わらず、古いeventは新しい表示を巻き戻さない。Discord delivery failureはSTART workflowやLock/Desiredへ逆流しない。

## 9. 後期アーキテクチャ

### 複数ゲーム

- Packages、Templatesを追加する。
- GameごとにPackage version、runtime class、generationを固定する。
- EC2停止中に必要なinstance typeへ変更する。
- 初回start時にmaterializeする。

### 管理Webページ

第一段階:

```text
Static frontend
→ Discord OAuth2
→ API Gateway HTTP API
→ Admin API Lambda
→ DynamoDB / Reconcile
```

状態は5〜10秒程度のポーリングで更新する。

第二段階で必要性が確認できた場合のみWebSocket APIを追加する。

### チャット連携

- Minecraft側専用MOD/プラグインをPackage能力として扱う。
- Minecraft→DiscordはWebhookまたはBot APIを使用する。
- Discord通常メッセージ→Minecraftは常駐Discord Gateway接続が必要になるため、別コンポーネントとして後期追加する。
- チャット障害をMinecraftコア運用から分離する。

## 10. IaCと環境

- AWS CDK v2 for Pythonを採用する。
- アプリケーションBackendもPythonを基本とする。
- EC2スクリプトはPython中心とし、OS初期化等だけShellを許可する。
- `dev`と`prod`を別stack名、リソースprefix、タグで分離する。
- 初期は同一AWSアカウント内の環境分離を許可する。
- 手動作成リソースを正本にせず、原則CDKへ記述する。

初期はstageごとに`MinecraftStack` 1つへまとめ、constructで責務を分ける。

```text
MinecraftStack
  NetworkConstruct
  ComputeAndStorageConstruct
  StateStoreConstruct
  WorkflowConstruct
  DiscordConstruct
  MonitoringConstruct

LaterWebStack
  frontend / OAuth / Admin API / WebSocket
```

Webを追加するときに`LaterWebStack`を分離する。初期からFoundation、ControlPlane、Monitoringを別stackへ分割して固定しない。

コードと設定schemaはPhase 0からdev/prod両stageを扱えるようにする。`config/stages/prod.yaml`は未確定値を`null`としたplaceholderとしてGit管理してよいが、これはprod AWSリソースを作成済みという意味ではない。Phase 0〜7の実装・`cdk synth`・deployはdevを基本とし、prodの必須値が未確定の間はprod向け`cdk synth`またはdeployを明示的なvalidation errorで停止する。prodの具体値確定、`cdk synth`、`cdk diff`、deployは最初の実用リリース直前に行う。

具体的なproject名、resource prefix、FQDN、runtime、容量、timeout等は`config/project.yaml`と`config/stages/<stage>.yaml`を正本とする。秘密値そのものは設定ファイルへ保存せず、`config/secrets.example.yaml`にはParameter名だけを記載する。CDKがParameter Store、Lambda environment、CloudFormation output等へ配布した値を、YAMLと独立した手動設定の正本にしない。

### Phase 3 Control Plane status integration

Phase 3ではPhase 1/Targetから独立した`WishicraftControlPlaneStack-<stage>`を追加する。このstackはcurrent SystemState用DynamoDB、薄いReconcile Lambda、専用IAM、LogGroupだけを所有する。TargetはProject/Stage/Purpose tagでexactly oneに解決し、物理instance IDをGitへ正本化しない。

Reconcile domain serviceはdesired context取得、Target解決、EC2/SSM/固定Host Runtime probeの段階観測、public IPv4、Route 53 A record観測、discrepancy/health導出、条件付き永続化を統括する。Lambda handlerはversioned input検証とAWS adapter wiringだけを担当する。Phase 1/Target stack、EC2 lifecycle、EBS、SG、DNS writeはこのstackの責務に含めない。

repositoryでのconstruct実装・test・synthとAWS上のdeploy/integrationは別のdelivery stateとして記録する。repository validatedだけでControl Plane stack、DynamoDB、LambdaがAWSへ作成済みとは扱わない。

2026-08-28にdevのcredential付きdiffでTarget stack差分0、Control PlaneはDynamoDB、LogGroup、IAM Role/Policy、Lambdaの新規resourceだけであることを確認し、`WishicraftControlPlaneStack-dev`だけをdeployした。Phase 1にはAMI parameter再解決、履歴上のUserData、移行済み旧VolumeAttachmentの既知Frozen差分があるためdeployせず、Control Planeからの参照も追加していない。stopped TargetへのReconcileを2回実行し、段階観測のshort-circuit、current SystemStateの単調更新、既存stack/runtime/storage/network境界の不変を確認した。
