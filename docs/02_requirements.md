# 02. Requirements

> Reset要件（2026-09-12）: RESET-001/002の従来LATER案を[D-098 Accepted](reviews/game_scoped_reset.md)の契約で置換する。毎回の外部BACKUPや連番generationは必須ではない。B限定の適用・復旧・一般公開は[実行証跡](evidence/2026-09-12-reset-production.json)で区別する。


- **文書状態:** Canonical
- **最終更新:** 2026-09-13

## 1. 要件の読み方

- `MUST`: 必須。満たさない実装は不適合。
- `SHOULD`: 原則採用。外す場合は決定ログへ理由を残す。
- `MAY`: 任意。
- `MVP`: 初回実用版で必要。
- `LATER`: 後期フェーズで必要。

## 2. システム要件

### SYS-001 オンデマンド起動 `MUST / MVP`

Minecraft用EC2は、利用者が遊ぶときだけ起動できなければならない。

### SYS-002 単一実行 `MUST / MVP`

同時に起動できるゲームは1つだけとする。起動処理中、停止処理中、materialize中など、競合するoperationが進行中の場合も新規競合操作を拒否する。

### SYS-003 共通接続先 `MUST / MVP`

Minecraftクライアントは固定FQDNを一度登録すれば、EC2の再起動でパブリックIPv4が変わってもアドレスを入力し直さず接続できなければならない。

初期方式はRoute 53のAレコードをEC2起動時に現在の動的パブリックIPv4へ更新し、EC2停止完了後に削除する。Elastic IPの常時保持は初期構成へ含めない。

### SYS-004 新規実装 `MUST / MVP`

旧コード、旧DynamoDB、旧EC2ディレクトリ、旧コマンドとの互換性を実装要件にしない。

### SYS-005 サーバーレス制御 `MUST / MVP`

Discord受付、状態管理、ワークフロー制御は、常駐コントローラーEC2を必要としない構成とする。

### SYS-006 Runtime責務分離 `MUST / MVP`

Phase 2以降はWishicraftをControl Plane、EC2上のDocker/Compose/systemd等をHost Runtime、itzg/docker-minecraft-serverをMinecraft Runtimeとして分離する。WishicraftはMinecraft固有runtimeを再実装せず、desired stateからitzg公開入力へのmapping、apply timing、認可、policy、AWS状態遷移を担当する。

Phase 1の実装と検証記録はas-builtとして維持し、target architectureへの移行を理由に履歴を書き換えない。

## 3. 状態確認要件

### STA-001 段階的実測 `MUST / MVP`

状態確認は次の順で行う。

1. EC2 API
2. SSM接続状態
3. systemdまたはプロセス状態
4. Minecraft管理プロトコル応答
5. 実アクティブゲームID
6. プレイヤー数

到達不能な下位段階を無理に確認しない。

### STA-002 状態分離 `MUST / MVP`

少なくとも次を別属性として管理する。

- Desired State
- EC2 Observed State
- Public IPv4 / Connection Endpoint State
- SSM Observed State
- Minecraft Service State
- Minecraft Protocol State
- Active Game ID
- Operation Status / Current Step
- Health

### STA-003 UNKNOWN `MUST / MVP`

確認不能を`STOPPED`、`READY`、`HEALTHY`へ置き換えてはならない。

### STA-004 観測時刻 `MUST / MVP`

状態表示には最終実測時刻を含める。

### STA-005 保存値との差分 `MUST / MVP`

新しい実測結果と保存済みObserved Stateが異なる場合、条件付き更新で保存値を更新し、差分をoperationまたはログへ記録する。

### STA-006 自動修復制限 `SHOULD / MVP`

初期版では状態不一致を検知しても、無条件のMinecraft再起動やEC2再起動を行わない。通知と正確な状態更新を優先する。

## 4. 起動要件

### START-001 対象検証 `MUST / MVP`

起動前に対象Gameが存在し、起動可能なライフサイクル状態であることを確認する。

### START-002 排他ロック `MUST / MVP`

起動前にグローバルoperationロックを取得する。ロック取得はDynamoDB条件付き書き込みで行う。

### START-003 実状態検証 `MUST / MVP`

保存状態だけを見て起動してはならない。起動前にEC2、SSM、Minecraft、active gameをreconcileする。

### START-004 長時間処理 `MUST / MVP`

EC2起動、SSM待機、Minecraft起動、READY待機はStep Functions Standardで管理する。単一Lambdaを待機させ続けない。

### START-005 READY判定 `MUST / MVP`

次をすべて満たした時点で起動成功とする。

- EC2がrunning
- SSMがonline
- Minecraftサービスがactive
- Minecraft管理プロトコルに応答
- active gameが要求対象と一致
- 固定FQDNが現在のEC2パブリックIPv4を指し、Route 53変更が`INSYNC`

### START-006 冪等性 `MUST / MVP`

同じ`operation_id`が再実行された場合、二重起動を起こさない。

D-096適用済み: instance/Game/data/config/runをOperationへ固定し、再試行で作り直さない。古い命令の拒否と実観測の一致は[実行契約](05_data_and_interface_contracts.md#0-production適用済みruntime契約d-096)による。SDK/host命令を世界全体でexactly-once実行できるという保証ではない。

- 同じゲームが既にREADYなら成功相当として扱える。
- 別ゲームがREADYなら競合として失敗する。
- 同一operationがRUNNINGなら新規operationを開始しない。

### START-007 失敗時再観測 `MUST / MVP`

タイムアウトやSSM失敗時は、推測で`STOPPED`に戻さず、可能な範囲で実状態を再観測する。

### START-008 失敗後のDesired State `MUST / MVP`

`SetDesiredRunning`より前の検証失敗ではDesired Stateを変更しない。`SetDesiredRunning`後に起動が失敗した場合は、利用者の要求として`RUNNING`を維持し、Observed State、Health、Discrepancy、Last Errorで未達を表す。初期版では失敗を理由にDesired Stateを自動で元へ戻したり、無期限に自動再試行したりしない。

## 5. 停止要件

### STOP-001 保存要求 `MUST / MVP`

Minecraftが応答可能な場合、停止前に保存要求を行う。

### STOP-002 段階的停止 `MUST / MVP`

停止は次の順序とする。

1. 新規操作受付制御
2. 保存要求
3. Minecraft停止要求
4. Minecraftプロセス停止確認
5. EC2停止要求
6. EC2 stopped確認

### STOP-003 完了条件 `MUST / MVP`

EC2停止APIを呼び出した時点ではなく、EC2が実際に`stopped`になったことを確認して完了とする。

D-096適用済み: 稼働runtimeを止めた場合は保存・正常exit・永続bind確認後、停止済みexact containerを削除してstopped receiptへ収束させる。world/volume削除やforce removalは含まない。EC2 already-stopped分岐では架空のrun/receiptを作らない。

### STOP-004 保存失敗 `MUST / MVP`

保存に失敗した場合、通常停止として無条件にEC2を停止してはならない。失敗を記録し、管理者判断が必要な状態とする。

### STOP-005 既停止時 `MUST / MVP`

EC2が既にstoppedで、実行中operationや不整合がない場合、stopは冪等な成功として扱える。

### STOP-006 強制停止 `LATER`

強制停止は通常stopと分離し、管理者限定・明示確認・監査記録付きで実装する。

### STOP-007 失敗後のDesired State `MUST / MVP`

`SetDesiredStopped`より前の検証失敗ではDesired Stateを変更しない。`SetDesiredStopped`後に保存、Minecraft停止、EC2停止が失敗した場合は、利用者の要求として`STOPPED`を維持し、実測との差をHealth、Discrepancy、Last Errorへ記録する。保存失敗を理由に通常停止を継続してはならない。

## 6. Discord要件

### DIS-001 コマンド `MUST / MVP`

初回実用版では次だけを実装する。

- `/mc status`
- `/mc start`
- `/mc stop`

Phase 8Cでは運用保護commandとして`/mc backup`を追加する。引数は持たず、DIS-007どおりadmin roleだけを許可する。

### DIS-002 署名検証 `MUST / MVP`

Discord Interactionの署名を検証し、不正なリクエストを拒否する。

### DIS-003 初期応答 `MUST / MVP`

長時間処理はDiscordの期限内に初期応答を返す。Admissionを期限内に完了できるcommandは受付結果を即時ephemeral responseで確定し、fresh Reconcile等を待つcommandはDeferred Responseを返す。いずれも長時間workflow完了をInteraction handler内で待たない。

### DIS-004 進捗メッセージ `MUST / MVP`

start、stopのInteraction初期応答は期限内に受付結果をephemeralで確定する。受付後、Bot Tokenで操作チャンネルへ通常の公開メッセージを作成し、その`message_id`をOperationへ保存する。主要進捗、完了、利用者向け失敗はこの通常メッセージを更新して表示する。

### DIS-005 長時間更新 `MUST / MVP`

長時間operationの進捗更新はInteraction Tokenへ依存しない。Interaction Token自体をDynamoDB、Step Functions input、通常ログへ保存せず、Bot Tokenで作成した通常チャンネルメッセージを更新する。

### DIS-006 公開範囲 `MUST / MVP`

原則公開:

- start/stop受付
- 主要進捗
- 完了
- 状態確認
- 競合拒否
- 利用者向けエラー
- 操作者名

本人限定:

- 権限不足
- 入力エラー
- 内部エラー詳細
- ユーザーID、ロール判定情報
- 破壊的操作の最終確認

### DIS-007 権限 `MUST`

初期権限を次とする。D-098適用後のB限定RESETはPlayer / Adminへ変更済みで、下表の初期reset管理者限定案より[D-098](reviews/game_scoped_reset.md)を優先する。D-097のSWITCHはAdmin限定。現行一覧は[利用案内](discord_user_guide.md)。

| 操作 | 一般利用者 | 管理者 |
|---|---:|---:|
| status | 可 | 可 |
| start | 可 | 可 |
| stop | 可 | 可 |
| list / info | 可 | 可 |
| create | 不可 | 可 |
| backup | 不可 | 可 |
| reset | 不可 | 可 |
| package/template管理 | 不可 | 可 |
| OP管理 | 不可 | 可 |
| runtime class変更 | 不可 | 可 |
| 強制停止 | 不可 | 可 |

Phase 7 MVPの`status`、`start`、`stop`は、stage設定で固定したGuildとoperation channelからの要求だけを受け付け、player roleまたはadmin roleを持つmemberを許可する。Discord側command permissionはUX上の補助であり、application側でもGuild、channel、roleを必ず検証する。admin roleの通常操作もoperation channelを使用し、admin channelは後続のrecovery、reset、maintenance等の管理操作まで予約する。

### DIS-008 Control Plane adapter境界 `MUST / MVP`

Discord ingressは既存Operation Admissionへのexternal adapterとする。Desired State、Lock、`current_operation_id`、EC2、SSM、RCON、Minecraft、DNSを直接操作せず、START/STOP State MachineをAdmission抜きで起動しない。`status`はSTATUS Operationとしてadmitした後にfresh Reconcileを非同期実行し、Interaction handler内で完了を待たない。Discord表示はOperationとObserved Stateのprojectionであり、Control Plane stateの正本にしない。

### DIS-009 Message冪等性とdelivery分離 `MUST / MVP`

公開progress/resultは原則1 Operationにつき1つのBot channel messageを作成し、retry、Interaction再送、workflow retryで増殖させない。同一Operationのmessage identityを条件付きで関連付け、以後は同じmessageを更新する。Discord message create/update失敗はdelivery結果として別に観測し、Minecraft/AWS Operationの成功・失敗を変更しない。

通常message createはOperation単位の決定的nonceとDiscordのnonce重複排除を使用し、create成功・message identity保存前failureを同じlogical messageへ回復できなければならない。create成否不明の安全な回復期間を越えた場合、duplicateの可能性がある新規messageを作らずdeliveryだけをfail closedする。retryはboundedとし、429の`retry_after`を尊重し、permanent認証・認可・not-found failureを無限retryしない。

START/STOP/BACKUP progressにはControl Plane Operationと同じwriteで単調増加するrevisionを用い、古いStream eventが新しい公開状態を上書きしてはならない。delivery metadataだけの更新は新しい公開deliveryをtriggerせず、古いrevisionのdelivery failureはより新しいprogress/terminal revisionを妨げてはならない。

### DIS-010 Token権限とcommand登録 `MUST / MVP`

Interaction署名検証を行うCommand Lambdaは公開設定のDiscord Public Keyを使用し、Bot Tokenを読まない。Bot Tokenのsecret readはDiscord message delivery componentだけに限定する。`/mc` command schemaはGitを正本とし、Discord APIへのregistrationはCDK deployの暗黙side effectではなく、明示operator actionとして行う。

## 7. Operation・ロック要件

### OPR-001 操作記録 `MUST / MVP`

start、stop、status、backup等はoperationとして記録する。ただし高頻度heartbeatはoperationにしない。

### OPR-002 操作情報 `MUST / MVP`

最低限、次を保持する。

- operation ID
- 種別
- 対象Game
- 実行者
- 受付時刻
- status
- current step
- 開始・完了時刻
- timeout
- エラーコード
- Discordメッセージ情報

### OPR-003 ロックリース `MUST / MVP`

ロックには`lease_expires_at`を持たせる。長時間operationは待機ループ中に定期的にリースを延長する。`operation_id`はlogical owner、acquisitionごとに一意な`lease_id`は現在のlease possession proofとする。

EC2 start/stop、SSM command、Desired State更新等の副作用直前にロック所有権を確認し、所有権を失っている場合は`LOCK_LOST`として新しい副作用を実行しない。

### OPR-004 TTL非依存 `MUST / MVP`

DynamoDB TTLによる物理削除をロック解放条件に使わない。所有権確認時に`lease_expires_at`を評価する。Phase 4 MVPの通常admissionは期限切れitemも自動takeoverせず、明示stale recoveryまで競合をblockする。

### OPR-005 所有者付き解放 `MUST / MVP`

ロック解放は、保存された`owner_operation_id`と`lease_id`が解放者の値と一致し、leaseが未期限切れの場合だけ行う。


### OPR-006 Operation受付の原子性 `MUST / MVP`

競合するstart、stop、backup等の受付では、次をDynamoDB Transactionで一体として行う。

1. idempotency keyの一意予約
2. Operationの一意作成
3. グローバルロック取得
4. `SystemState.current_operation_id`設定

Transactionが成立しない場合、新しい競合OperationやStep Functions executionを作成しない。同じidempotency keyが既に存在する場合は、既存operationを返し、新しいoperation IDを作成しない。

### OPR-007 Workflow開始の冪等性 `MUST / MVP`

Step Functions execution nameには一意な`operation_id`を使用し、Operationへexecution nameとARNを保存する。Workflow開始に失敗した場合はOperationを失敗へ更新し、所有者条件付きでLockと`current_operation_id`を解除する。

### OPR-008 所有者付きCurrent Operation解除 `MUST / MVP`

`SystemState.current_operation_id`の解除は、保存されたIDが呼出元`operation_id`と一致する場合だけ行う。古いworkflowが新しいoperationを解除してはならない。

### OPR-009 STATUS operation `MUST / MVP`

利用者が明示的に実行した`status`はOperationへ記録するが、グローバルLockを取得せず、`SystemState.current_operation_id`も設定しない。EventBridgeやworkflow内部の高頻度reconcileはSTATUS operationとして増殖させない。

### OPR-010 CLI/Admin受付経路 `MUST / MVP`

Discord実装前のPhase 5、6では、管理CLIまたはadmission Lambdaのtest eventから、Discordと同じOperation admission serviceを経由してworkflowを開始できなければならない。State Machineを直接開始してOperation、Idempotency、Lock、Current Operationの受付を迂回してはならない。

## 8. EC2・ネットワーク要件

### EC2-001 SSM管理 `MUST / MVP`

日常管理にはSSM Session ManagerとRun Commandを使用する。SSHポートは原則公開しない。

### EC2-002 公開ポート `MUST / MVP`

インターネットから許可する受信は、必要なMinecraftポートに限定する。RCON、管理API、SSHを公開しない。

### EC2-003 Lambda非VPC接続 `SHOULD / MVP`

Lambdaは、EC2へ直接プライベート接続する必要がない限りユーザーVPCへ接続しない。EC2操作はAWS APIとSSM経由とする。

### EC2-004 NAT Gateway禁止 `MUST / MVP`

初期構成にNAT Gatewayを作成しない。必要になった場合は決定ログで費用と代替案を再評価する。

### EC2-005 データ分離 `SHOULD / MVP`

OSと再作成可能なコードはroot volume、ゲームデータはdata volumeへ分離する。

### EC2-006 アーキテクチャ固定 `MUST / MVP`

初期版はCPUアーキテクチャを1種類に固定する。複数アーキテクチャをruntime class間で混在させない。

### EC2-007 任意実行禁止 `MUST / MVP`

game ID、package ID、ユーザー入力をシェルコマンドやパスへ直接連結しない。許可済みIDから内部設定を解決する。


### EC2-008 固定FQDN `MUST / MVP`

EC2起動時に現在のパブリックIPv4を取得し、許可済みHosted Zone内の固定FQDNへRoute 53 UPSERTを行う。変更が`INSYNC`になり、DNSが現在のIPを指すことを確認するまで利用者向けにオンライン完了としない。

EC2停止完了後はAレコードを削除する。Route 53変更権限は対象Hosted Zoneと対象レコードへ限定する。

AWS Consoleからの手動停止、EC2障害、instance置換等でworkflow外にEC2が`stopped`または`terminated`となった場合も、EventBridgeまたはReconcileが古いAレコードを検出し、進行中のstart operationがないことを確認して安全に削除する。

### EC2-009 MVPホワイトリスト `MUST / MVP`

公開Minecraftポートを使用するため、初回実用版から`online-mode`とMinecraftホワイトリストを有効にする。MVPでは固定メンバーを管理者が手動登録してよい。Discordからのホワイトリスト管理は後期機能とする。

### EC2-010 Data EBS保護 `MUST / MVP`

Gameデータ用EBSはEC2とは別リソースとして同一Availability Zoneへ配置し、暗号化し、削除保護方針を明示する。初期構成ではCDK削除やEC2置換で自動削除しない。

filesystemは初回だけ作成し、UUIDでmountする。`/srv/minecraft`が期待するdata volumeへmountされていない場合、Minecraft起動、保存、backup、resetを実行しない。

### EC2-011 管理command path `MUST / MVP`

RCON等の管理portをhostまたはInternetへpublishしない。Control PlaneからのMinecraft commandはSSM等の管理経路からhost-local / container-localに閉じ、認可、secret injection、Minecraft固有実行の責務を分離する。

### EC2-012 lifecycle owner `MUST / MVP`

systemd、Docker/Compose、itzgが独立にrestartを判断してControl Planeの停止意図を打ち消してはならない。container lifecycle owner、restart policy、graceful stop timeout、正常終了判定を明示する。

## 9. バックアップ要件

### BAK-001 実装時期 `MUST`

複数ゲーム、reset、MOD対応より先にバックアップ処理を完成させる。

### BAK-002 対象 `MUST`

Phase 8 MVPはpersistent Data EBS全体のEBS Snapshotを対象とする。root EBSはIaCとrepositoryから再構築可能なため対象外とする。初期単一GameではData EBSと`game-vanilla-main`を一意に対応させる。複数Gameを同一Volumeへ置く場合は、Game単位retentionを有効化する前にstorage modelを再Decisionする。

### BAK-003 成功判定 `MUST`

fresh stateがDesired/Actual/ObservedすべてSTOPPED、HEALTHY、discrepancy/active operationなしであること、expected Data EBS identity、Snapshot `completed`、source volume、owner、必須metadata/tagをすべて確認して成功とする。CreateSnapshot acceptedまたは`pending`だけでは成功にしない。

### BAK-004 復元可能性 `MUST`

SnapshotにはGame ID、source volume ID、category、Operation ID、作成日時、stage、schema version、protected flagを保持する。Restore UI・汎用workflowはPhase 16で扱う。D-095により既存Snapshotのoperator隔離復元確認だけを実データ移行・Resetより前へ配置する。Phase 16前の削除は、D-091の明示的に承認されたRETENTION destructive-operation contractとrelease gateを満たし、durable provenanceで所有を証明できるD-090 v1 normal backupだけに許可する。それ以外のsnapshotは自動置換・削除しない。


### BAK-005 停止中の不要起動禁止 `SHOULD`

BACKUPは停止中だけ許可し、RUNNING/STARTING/STOPPING/unknown/degradedをfail closedで拒否する。BACKUP自身はEC2やMinecraftを停止・起動しない。scheduled backup、STOP連動backup、RUNNING backupはMVP対象外とする。

### BAK-006 Retentionと分類 `MUST`

D-097 Acceptedの移行後は、新形式shared-volume normalだけを共有volume単位のnewest 7群とする。legacy normal/migration/protectedは件数に含めず保持する。移行未完了時の既存v1経路と以下の従来Game単位規則を、新形式へ自動変換しない。実削除は未releaseであり、総Snapshot数8件ではgateを開かない。新保護単位の候補・復旧手順に対応した別承認を必要とする。

通常backupはGameごとにnewest 7を保持する。`backup`、`migration`、将来のcategoryをmetadataで区別し、migration、protected、既知のmanual/operator snapshotは通常retentionから除外する。削除は独立RETENTION Operation、global Lock、positive proof、delete直前再検証、1 Operation最大1件、明示的outcome reconciliationを必要とする。実DeleteSnapshotと権限のreleaseはD-091の別gateとする。

## 10. 複数ゲーム・Package要件

現在の優先順位は[D-101 / Current roadmap](06_delivery_plan.md#current-roadmap)を参照。LATERは要求の保留区分であり、旧Phase番号順の実装義務ではない。Package/Preset/Templateの要求とversion固定方針を維持し、独立管理や汎用wizard/uploadを最小Game作成の前提にしない。現行の対応済み実行構成の正本はD-096/097、詳細な新規作成契約は今後のsliceで決める。


### GAME-001 管理単位 `LATER`

以下のLATERモデルは見直し対象。[D-097 Accepted](reviews/two_game_switch.md)では、同一固定構成の二Game選択・EC2維持切替・共有BACKUP整合を一利用機能として準備する。認可、接続playerの扱い、共有保護/retention単位はD-097の限定範囲で採用・適用済み。Reset等へ無条件に流用しない。

複数ゲーム対応後は、ワールド単体ではなくGameを起動単位とする。

### GAME-002 内部ID `LATER`

Gameはシステム生成の不変`game_id`を持つ。表示名は日本語と空白を許可し、初期版では重複を禁止する。

### GAME-003 Version pinning `LATER`

Gameは具体的なPackage version、Minecraft version、Java runtimeへ固定する。既存Gameに`latest`参照を残さない。

### PKG-001 不変Package `LATER`

同一package ID/versionの中身を上書きしない。

### PKG-002 サーバー種別 `LATER`

将来対応候補は次とする。

- vanilla
- paper
- fabric
- forge
- neoforge

MODとPaper系プラグインを同一Gameで混在させるハイブリッド構成は初期対象外とする。

### CREATE-001 作成と起動分離 `LATER`

Game作成は起動と分離し、Game metadataの登録だけでEC2を起動しない。現在はWebから対応済み実行構成を選び、display name等の必要項目を指定する最小作成を優先する。`/mc create`と初回start時materializeは従来の拡張要求として保持し、汎用wizard・Package/Preset/Template独立管理を先行しない。

作成Gameをpublic guideへ自動掲載しない。掲載は説明とclient要件を揃えた明示的公開登録とする。作成時に必要な初期whitelistと、後から編集するWhitelist Managementは別scopeとする。

### RESET-001 世代交換 `LATER`

resetはGameを削除・再作成せず、同じ`game_id`とサーバー構成を維持したままgenerationを増やす。

### RESET-002 事前保護 `LATER`

reset前に最終バックアップを作成・検証し、旧世代を保持する。backup失敗時は旧ワールドを移動しない。

## 11. 管理Webページ要件

Web Foundation read-only部分の具体契約は[D-102 Accepted](reviews/web_foundation.md)。
保存済みSystemState/heartbeat/Operationを読むだけでSTATUS Operationや観測/repairを起動しない。
unknown/0/not_expected、鮮度/部分失敗と選択/実観測を分離する。public guideはログイン不要、
manage/APIはcanonical Discord Guild/member/player・admin role条件を必要とする。Web write操作は次slice。


### WEB-004 静的利用案内 `MUST / D-100独立slice`

既存のDiscord利用案内を入口に、Game/command別Markdownを各説明の唯一の編集元として、参加条件、Game差分、現行schemaの引数・例・認可、安全条件、失敗/結果不明時の行動を静的HTMLで提供する。Minecraft EC2停止中も読める配信計画とする。機械項目はGame/runtime/schemaから投影し、公開候補fieldと本文範囲を明示する。

公開buildへ内部設定・個人/実行証跡・秘密値・未承認の接続先/招待URLを混ぜない。ローカル実装/CIとhosting作成・インターネット公開を分離し、後者は別承認。実表示・コピー・keyboard・安全な文字列挿入・再現性を検証する。[D-100計画](reviews/user_guide_web.md)を参照。WEB-001〜003は管理Web要求として維持する。D-100の内容・ローカル構成は承認済み公開候補という独立完成物で、Web Foundationのpublic部分へつながる。実公開はWeb全体の配信構成と合わせるのを第一候補とするが、内容承認はhosting・閲覧者・認証・URL・費用・管理Web承認を含まない。

### WEB-001 実装時期 `LATER`

Discord MVPと運用保護の完成を踏まえ、D-101の次の優先sliceをWeb Foundationとする。authenticated管理領域のread-only statusを先にreleaseし、START / STOP / SWITCH / BACKUP / RESETのwrite operationsは別release sliceとする。

### WEB-002 初期方式 `LATER`

D-102ではDiscord OAuth2、HTTP API、約1分間隔のポーリングを使用する。WebSocketは必要性を確認してから追加する。

Web全体のhosting / URL / Discord OAuth / authorizationはWeb Foundationで決め、security boundaryで人間承認を受ける。browserへAWS権限を直接持たせない。write operationsはDiscordと同じAdmission / Operation / workflowを使い、Web専用制御を作らない。UI非表示だけでなくAPI側で既存role/policyに基づき認可する。

### WEB-003 表示 `LATER`

既存Control Planeから次を読む。最初のreleaseはstatus相当（状態・選択/観測・人数・観測時刻・current Operation・主要進捗等）までとし、一覧/詳細・履歴の拡張は後続sliceで扱う。

- Desired State
- 各Observed State
- 選択Gameと観測Game（active gameを選択から推測しない）
- player count
- 最終実測時刻
- current Operationと主要進捗
- 直近エラー
- Game一覧と詳細
- operation履歴

## 12. OP・チャット要件

Whitelist Managementは最小Game作成と実運用の後に、共通 / Game固有 / Minecraft内変更の責務を改めて決める。複雑な双方向同期を既定にせず、作成時の初期whitelistと後からの編集管理を分ける。OP-001/002は維持し、未確定のwhitelist詳細contractをここで採用しない。

CHAT-001〜003は具体的需要と対応runtime/pluginが決まった時のindependent trackとする。以下のchat内部順序は、管理WebやGame作成の前提を意味しない。


### OP-001 Game単位 `LATER`

Minecraft標準OPはGameごとに管理し、UUIDを内部識別子とする。

### OP-002 反映確認 `LATER`

コマンド送信成功だけで完了とせず、実サーバーへの反映を確認する。

### CHAT-001 Package能力 `LATER`

チャット連携は専用MODまたはプラグインを含むPackageだけが利用できる。純バニラのログ解析は実装しない。

### CHAT-002 疎結合 `LATER`

チャット連携障害だけでMinecraft本体を停止しない。

### CHAT-003 実装順 `LATER`

1. MinecraftからDiscordへの一方向
2. join/leave/death
3. `/mc say`
4. 必要時のみDiscord通常メッセージとの完全双方向

## 13. 非機能要件

### NFR-001 安全性

ワールドデータ保護を機能追加より優先する。破壊的処理は明示確認、バックアップ、監査記録を伴う。

### NFR-002 再実行可能性

Lambda、Step Functions Task、EC2スクリプトは、再試行や重複配信を前提に可能な限り冪等にする。

### NFR-003 監査性

誰が、いつ、何を、どのGameへ実行し、どこまで進み、どう終わったか追跡できる。

### NFR-004 コスト制御

- Minecraft EC2停止漏れを検知する。
- AWS Budgets通知を設定する。
- NAT Gatewayを初期構成へ含めない。
- CloudWatch Logs保持期間を明示する。
- S3 lifecycleを設定する。
- 状態変化時のみ不要な書き込み・通知を行わない。

### NFR-005 秘密情報

Bot Token、OAuth Client Secret、RCON secret、セッション署名鍵をコード、Git、Discordメッセージ、CloudWatch通常ログへ出力しない。

### NFR-006 テスト可能性

AWS API、DynamoDB repository、Discord API、SSM呼び出しを分離し、ローカル単体テストでモック可能にする。

### NFR-007 可観測性

ログには`operation_id`、`game_id`、component、step、resultを構造化して含める。秘密情報とワールド内容は含めない。
### NFR-008 初回実用リリースの監視 `MUST / MVP`

Discord MVPを実用リリースとする前に、少なくとも次を有効化する。

- AWS Budgets通知
- CloudWatch Logs保持期間
- start/stop workflow失敗通知
- EC2長時間running通知
- Desired STOPPEDかつEC2 runningの通知
- Desired RUNNINGかつ長時間READYでない通知
- operation lock期限超過通知
- Lambda error/throttle通知

backup失敗、heartbeat stale、data volume使用率はPhase 8の機能導入と同時に追加する。

### NFR-009 Backup導入前の試験運用保護 `MUST / MVP`

Phase 8B/8Cで停止中Data EBSの検証済みEBS Snapshot backupとDiscord adapterは完成した。Restore UI・汎用workflowはPhase 16で扱い、operator隔離復元確認はD-095で先行する。

### NFR-010 設定の単一正本 `MUST`

同じ設定値をGitとDynamoDB等へ独立に保存して二重に正本化しない。deploy/基盤固定値、運用中desired state、secret、Minecraft runtime dataの所有者をschema上で明示する。Wishicraftとitzgが同じMinecraft実ファイルを双方から直接編集してはならない。

### NFR-011 EULA operator gate `MUST`

itzg採用後もMinecraft EULA同意をoperator policy/gateとして扱い、人間の承認済み事実がある場合だけruntimeへ同意入力を渡す。runtime入力の存在だけを承認記録の代替にしない。
