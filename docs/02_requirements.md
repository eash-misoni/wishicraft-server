# 02. Requirements

- **文書状態:** Canonical
- **最終更新:** 2026-08-22

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

### DIS-002 署名検証 `MUST / MVP`

Discord Interactionの署名を検証し、不正なリクエストを拒否する。

### DIS-003 初期応答 `MUST / MVP`

長時間処理はDiscordの期限内にDeferred Responseを返し、受付後に非同期ワークフローを開始する。

### DIS-004 進捗メッセージ `MUST / MVP`

start、stopのInteraction初期応答は短時間でDeferred Responseを返す。受付後、Bot Tokenで操作チャンネルへ通常の公開メッセージを作成し、その`message_id`をOperationへ保存する。主要進捗、完了、利用者向け失敗はこの通常メッセージを更新して表示する。

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

初期権限を次とする。

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

ロックには`expires_at`を持たせる。長時間operationは待機ループ中に定期的にリースを延長する。

EC2 start/stop、SSM command、Desired State更新等の副作用直前にロック所有権を確認し、所有権を失っている場合は`LOCK_LOST`として新しい副作用を実行しない。

### OPR-004 TTL非依存 `MUST / MVP`

DynamoDB TTLによる物理削除をロック解放条件に使わない。取得時に`expires_at`を評価する。

### OPR-005 所有者付き解放 `MUST / MVP`

ロック解放は、保存された`operation_id`が解放者のoperationと一致する場合だけ行う。


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

最低限次を保存する。

- ワールドとdimensionデータ
- Game定義スナップショット
- server.properties
- config、defaultconfigs
- package ID/version
- Minecraft/Java要件
- generation
- 作成日時とchecksum

### BAK-003 成功判定 `MUST`

次を確認してバックアップ成功とする。

- Minecraft保存処理成功、または停止中の整合したデータ
- アーカイブ生成成功
- 非ゼロサイズ
- checksum生成
- S3アップロード成功
- S3上のオブジェクト情報確認
- backup manifest保存

### BAK-004 復元可能性 `MUST`

利用者向けrestore UIが未実装でも、管理者が手順に従って手動復元でき、定期的に復元テストできなければならない。


### BAK-005 停止中の不要起動禁止 `SHOULD`

定期backupだけを目的として停止中のMinecraft EC2を毎日起動しない。停止処理中または稼働中に整合したbackupを作成し、前回backup以降に変更がない停止中Gameはscheduled backupをskipできる。Pre-reset、Pre-upgrade、Pre-deleteは別途必須とする。

### BAK-006 S3保護 `MUST`

backup bucketはdev/prodで分離し、Block Public Access、server-side encryption、最小権限IAM、明示的removal policy、lifecycleを設定する。versioningやObject Lockは復旧要件と費用を評価してDecisionへ記録する。

## 10. 複数ゲーム・Package要件

### GAME-001 管理単位 `LATER`

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

`/mc create`はGameメタデータを作成し、原則としてEC2を起動しない。初回start時にmaterializeする。

### RESET-001 世代交換 `LATER`

resetはGameを削除・再作成せず、同じ`game_id`とサーバー構成を維持したままgenerationを増やす。

### RESET-002 事前保護 `LATER`

reset前に最終バックアップを作成・検証し、旧世代を保持する。backup失敗時は旧ワールドを移動しない。

## 11. 管理Webページ要件

### WEB-001 実装時期 `LATER`

Discord MVPと運用保護が完成した後に実装する。

### WEB-002 初期方式 `LATER`

最初はDiscord OAuth2、HTTP API、数秒間隔のポーリングを使用する。WebSocketは必要性を確認してから追加する。

### WEB-003 表示 `LATER`

最低限次を表示する。

- Desired State
- 各Observed State
- active game
- player count
- 最終実測時刻
- current operation
- 直近エラー
- Game一覧と詳細
- operation履歴

## 12. OP・チャット要件

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

Phase 8の検証済みS3 backupが完成するまでは、Phase 7を試験運用として扱い、初回利用前および重要変更前に管理者用EBS snapshot runbookを実行できる状態にする。

### NFR-010 設定の単一正本 `MUST`

同じ設定値をGitとDynamoDB等へ独立に保存して二重に正本化しない。deploy/基盤固定値、運用中desired state、secret、Minecraft runtime dataの所有者をschema上で明示する。Wishicraftとitzgが同じMinecraft実ファイルを双方から直接編集してはならない。

### NFR-011 EULA operator gate `MUST`

itzg採用後もMinecraft EULA同意をoperator policy/gateとして扱い、人間の承認済み事実がある場合だけruntimeへ同意入力を渡す。runtime入力の存在だけを承認記録の代替にしない。
