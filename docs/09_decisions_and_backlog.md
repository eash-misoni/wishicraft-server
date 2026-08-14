# 09. Decisions and Backlog

- **文書状態:** Canonical
- **最終更新:** 2026-08-14

## 1. Decision logの使い方

設計判断を変更する場合、既存決定を削除せず、`Superseded by D-xxx`として履歴を残す。

## 2. 採用済み決定

### D-001 新規実装として開始

- **状態:** Accepted
- 旧コード、旧AWS構成、旧データモデルの互換性を要件としない。
- 既存ワールド移行も初期計画へ含めない。

### D-002 サーバーレス制御面

- **状態:** Accepted
- API Gateway、Lambda、Step Functions、DynamoDB、EventBridgeを中心とする。
- 常駐コントローラーEC2を置かない。

### D-003 Minecraft EC2だけをオンデマンド起動

- **状態:** Accepted
- Minecraft本体のEC2だけを必要時に起動する。
- EC2停止中もEBS、Route 53 Hosted Zone、S3等の費用は残るため監視する。

### D-004 初回実用版は単一バニラGame

- **状態:** Accepted
- `/mc status`、`/mc start`、`/mc stop`だけを最初に完成させる。
- create、MOD、Paper、Webを先に作らない。

### D-005 PythonとAWS CDK v2

- **状態:** Accepted
- Backend、Lambda、CDK、EC2 control scriptsをPython中心にする。
- OS bootstrap等だけShellを許可する。

### D-006 Step Functions Standard

- **状態:** Accepted
- start/stop/backup/resetの長時間処理に使用する。
- Lambda内で待機ループし続けない。

### D-007 状態を複数軸へ分離

- **状態:** Accepted
- Desired、Observed infrastructure、Observed Minecraft、Operation、Healthを分ける。
- `WAITING_FOR_SSM`等をSystemの単一state enumへ入れない。

### D-008 DynamoDBは実状態の正本ではない

- **状態:** Accepted
- EC2 API、SSM、systemd/process、RCON、runtime情報から実測する。
- 保存値は最新観測スナップショットと要求状態。

### D-009 複数テーブル方式

- **状態:** Accepted
- 初期はSystemState、Games、Operations、Idempotency、Locksへ分ける。
- 単一テーブル設計の最適化を優先しない。

### D-010 条件付きリースロック

- **状態:** Accepted
- DynamoDB conditional writeで取得・延長・解放する。
- TTL物理削除をロック解放として使わない。

### D-011 SSM管理、SSH非公開

- **状態:** Accepted
- Session ManagerとRun Commandを使用する。
- VanillaにはRCON専用のbind address設定がないため、socketがwildcard bindし得ることを前提にする。Wishicraft専用host firewall tableでIPv4の`127.0.0.1`およびIPv6の`::1`以外へ宛てたRCON port通信を拒否し、Security GroupにもRCON ingressを設けない。「localhost限定」はsocket bindではなく実効的な到達性を意味する。

### D-012 LambdaをVPCへ接続しない

- **状態:** Accepted
- EC2操作はAWS APIとSSM経由。
- NAT Gatewayを初期構成へ作らない。

### D-013 root/data volume分離

- **状態:** Accepted
- OSと再配備可能コードをroot、Gameデータをdata EBSへ置く。

### D-014 初期CPUアーキテクチャ固定

- **状態:** Accepted
- 最初は1種類のCPUアーキテクチャだけを使用する。
- ARM/x86混在は後期に再評価する。

### D-015 Discord長時間処理

- **状態:** Accepted
- 期限内にDeferred Responseを返す。
- operation進捗はBot Tokenで公開メッセージを更新する。
- Interaction Tokenだけへ依存しない。

### D-016 start/stop前にReconcile

- **状態:** Accepted
- 保存状態だけで開始可否を判断しない。

### D-017 backupを拡張機能より先に実装

- **状態:** Accepted
- 複数Game、reset、MODより先にbackupと手動復元テストを完成させる。

### D-018 Package/Preset/Template/Gameを分離

- **状態:** Accepted
- 複数ゲームフェーズで導入する。
- Gameは具体的Package versionへ固定する。

### D-019 Package version不変

- **状態:** Accepted
- 同一versionを上書きしない。
- 内容変更時は新versionを作る。

### D-020 createとstartを分離

- **状態:** Accepted
- createはGameメタデータを作成し、EC2を起動しない。
- 初回start時にmaterializeする。

### D-021 WebはHTTP pollingから

- **状態:** Accepted
- Discord MVP後に管理Webを作る。
- 最初はHTTP snapshot/polling。
- WebSocketは必要性を確認してから追加する。

### D-022 OPはGame単位・UUID正本

- **状態:** Accepted
- 起動中は即時反映、停止中は次回起動時同期。
- Discord管理者権限を認可根拠とする。

### D-023 Chat bridgeはPackage能力

- **状態:** Accepted
- 専用MOD/PluginがあるPackageだけ対応する。
- 純バニラのlog解析は行わない。
- 障害をMinecraftコアから分離する。

### D-024 MODとPaperのハイブリッドを初期対象外

- **状態:** Accepted


### D-025 固定FQDNと動的パブリックIPv4

- **状態:** Accepted
- Elastic IPを初期構成へ含めない。
- Route 53の固定FQDNを共通接続先とし、EC2起動時に現在の動的パブリックIPv4へAレコードを更新する。
- EC2停止完了後はAレコードを削除する。
- Minecraftクライアント側は固定FQDNを一度登録すればよい。

### D-026 Operation admission transaction

- **状態:** Accepted
- 競合operationの受付時にIdempotency key予約、Operation作成、Lock取得、SystemState.current_operation_id設定をDynamoDB Transactionで一体として行う。
- Transaction失敗時は新しいOperationやStep Functions executionを作成しない。

### D-027 Discord進捗はBot通常メッセージ

- **状態:** Accepted
- Interactionへは期限内にDeferred Responseを返す。
- 受付後、Bot Tokenで操作チャンネルへ通常メッセージを作成し、そのmessage IDをOperationへ保存する。
- 長時間更新にInteraction Tokenを保存・依存しない。

### D-028 MVP静的ホワイトリスト

- **状態:** Accepted
- 公開Minecraftポートを使用するため、MVPから`online-mode`と静的ホワイトリストを有効にする。
- Discordからのホワイトリスト管理は後期機能のままとする。

### D-029 Data EBS保持とUUID mount

- **状態:** Accepted
- data EBSはEC2とは別リソースとして同一Availability Zoneへ配置し、暗号化・保持する。
- filesystem UUIDでmountし、mount未確認時はMinecraftや破壊的処理を実行しない。

### D-030 SystemState部分更新

- **状態:** Accepted
- Desired、Current Operation、Observed/Health、Last Errorを別repository操作で更新する。
- ReconcileはObserved属性群だけを更新し、SystemState全体のPutItem置換を行わない。

### D-031 RuntimeHeartbeat分離

- **状態:** Accepted
- Minecraft EC2のheartbeatは専用table/itemへ書き込み、SystemStateを直接更新させない。
- 自動停止前にはReconcileを再実行する。

### D-032 初回実用リリース前の最低限監視

- **状態:** Accepted
- Budgets、ログ保持、start/stop失敗、EC2長時間running、Desired STOPPED不一致、Desired RUNNING未達、Lock期限超過、Lambda error/throttleの通知をPhase 7のrelease gateへ含める。
- backup失敗、heartbeat stale、data volume使用率はPhase 8の機能導入時に追加する。

### D-033 初期は1 stack・dev deploy

- **状態:** Accepted
- stageごとに1つの`MinecraftStack`を使用し、constructで責務を分ける。
- 初期からFoundation/ControlPlane/Monitoringを別stackへ固定しない。
- Phase 0からdev/prodの設定schemaを扱い、`config/stages/prod.yaml`はplaceholderとしてGit管理する。
- Phase 0〜7のsynth/deployはdevを基本とし、prod AWSリソースは最初の実用リリース直前に作成する。
- prodの必須値が未確定の間はprod向けsynth/deployをvalidationで停止する。

### D-034 Python toolchain固定

- **状態:** Accepted
- Python 3.12、uv、Ruff、mypy、pytest、AWS CDK v2を使用する。

### D-035 Step Functions AWS SDK統合優先

- **状態:** Accepted
- EC2、SSM、DynamoDB、Route 53の単純API操作はStep Functions AWS SDK統合を優先する。
- Lambdaはdomain logic、Reconcile、admission transaction、Discord、複雑な正規化へ限定する。

### D-036 Scheduled backupで停止中EC2を起動しない

- **状態:** Accepted
- scheduled backupだけを目的に停止中EC2を毎日起動しない。
- 通常stop時、稼働中の整合save後、または明示操作でbackupを作り、変更のない停止中Gameはskipできる。

### D-037 Wishicraft naming and identifiers

- **状態:** Accepted
- 利用者向け名称を`Wishicraft`、Discord Bot表示名を`ゐしクラくん`とする。
- repository名を`wishicraft-server`、project slugを`wishicraft`、AWS resource prefixを`wc`とする。
- System IDを`wishicraft-main`、初期Game IDを`game-vanilla-main`、表示名を`Wishicraft Vanilla`とする。
- 初期Minecraft Javaプロフィール名を`NEWISHIN_`とする。

### D-038 初期runtimeとstorage class

- **状態:** Accepted
- Regionは`ap-northeast-1`、CPU architectureは`x86_64`、初期instance typeは`t3a.medium`とする。
- Amazon Linux 2023、Corretto 25 headless、Xms `1G`、Xmx `3G`を初期値とする。
- root EBSはgp3 16 GiB、data EBSはgp3 30 GiB、暗号化・保持とする。
- devのAvailability Zoneは`ap-northeast-1a`、Minecraft versionは`26.2`として`config/stages/dev.yaml`へ確定した。Minecraft 26.2はJava 25を要求する。
- 公式server.jar URLとSHA-1は同stage設定へ固定し、`latest`追従を行わない。prodは設定確定までplaceholderを維持する。

### D-039 設定ファイルを具体値の正本とする

- **状態:** Accepted
- `config/project.yaml`をproject共通値、`config/stages/<stage>.yaml`をstage別値の正本とする。
- `docs/12_initial_configuration.md`で設定と秘密情報の扱いを定義する。
- `null`や`TO_BE_CONFIRMED`をCodexや実装が推測して埋めない。

### D-053 Data EBSのXFS初期化とfail-closed mount

- **状態:** Accepted
- data EBSはpartitionを作らずvolume全体をXFSとして使用する。filesystemがない空volumeだけを初回formatし、既存XFSは再利用する。
- XFS以外、partition table、その他のsignatureは消去・変換せず停止する。Nitro上の実deviceはEBS volume IDとNVMe serialの一致で特定する。
- `/etc/fstab`はUUIDと`defaults,nofail`を使う。mount準備serviceは実volume・UUID・XFSのmountを検証し、失敗時はfailedとする。将来のMinecraft、backup、resetはこのserviceとmount guardを必須依存にする。

### D-054 Phase 1初期vanilla Gameの固定artifactと起動基盤

- **状態:** Accepted
- 初期PackageはMinecraft Java Edition 26.2 vanilla、初期Gameは`game-vanilla-main`とする。Corretto 25 headlessで実行し、公式version metadataのURL・SHA-1・sizeとリポジトリ固定SHA-256をすべて検証する。runtimeで`latest`やmanifestを参照しない。
- 初期Gameはdata EBS上へ配置し、`online-mode`、静的ホワイトリスト、EULA同意を必須にする。Minecraft Management Protocolは無効のままとする。RCONはSecureStringから設定し、Security Group ingressなしとhost firewallによる実効的localhost限定を必須にする。

### D-040 MVP secret store

- **状態:** Accepted
- MVPのDiscord Bot TokenとRCON passwordはParameter Store `SecureString`へ保存する。
- コードとCDKには実値ではなくParameter名だけを渡す。
- Secrets Managerは自動rotation等が必要になった場合に再評価する。

### D-041 Wishicraft固定FQDN

- **状態:** Accepted
- 取得済みドメインを`wishicraft.net`、Minecraft固定FQDNを`mc.wishicraft.net`とする。
- devのHosted Zone IDは`config/stages/dev.yaml`を正本とする。prodはprod設定が確定するまで`null`を維持する。
- `mc-dev.wishicraft.net`のAレコードはPhase 0では作成しない。Phase 1で起動中EC2の現在の動的パブリックIPv4へ更新し、停止後に削除する。

### D-042 公開設定の正本と実行時配布

- **状態:** Accepted
- `config/project.yaml`と`config/stages/<stage>.yaml`を公開設定の正本とする。
- Parameter Store String、Lambda environment、CloudFormation outputはYAMLまたはdeploy結果から生成する実行時配布先であり、人間が独立して編集する第二の正本にしない。
- `config/secrets.example.yaml`にはSecureStringのParameter名だけを保存する。

### D-043 Idempotency専用table

- **状態:** Accepted
- 外部要求の`idempotency_key`を専用tableへ条件付き作成する。
- 競合operationのadmission transactionへIdempotency、Operation、Lock、Current Operationを含める。
- 同じkeyの再送では既存operationを返し、新しいoperation IDやworkflowを作成しない。

### D-044 Operation失敗後のDesired State

- **状態:** Accepted
- Desired State更新前の検証失敗ではDesiredを変更しない。
- Desired State更新後の失敗では利用者の要求を維持し、Observed、Health、Discrepancy、Last Errorで未達を表す。
- failure cleanupがDesired Stateを暗黙に元へ戻さない。

### D-045 Discord進捗は任意adapter

- **状態:** Accepted
- start/stop workflowはDiscord metadataがある場合だけ進捗メッセージを作成・更新する。
- Phase 5、6のCLI operationでは進捗処理をskipできる。
- Discordの失敗をMinecraft operation結果と分離する。

### D-046 STATUSは非ロックOperation

- **状態:** Accepted
- 利用者の明示的statusはOperationへ記録するが、グローバルLockとCurrent Operationを使用しない。
- 定期reconcileやworkflow内部probeはOperationを作成しない。

### D-047 Workflow外停止時のDNS cleanup

- **状態:** Accepted
- EC2がworkflow外で`stopped`または`terminated`となった場合、進行中start operationがないことを確認し、残存Aレコードを削除する。
- 解放済み動的IPv4を固定FQDNが指し続けないことを優先する。

### D-048 Backup完成前は試験運用

- **状態:** Accepted
- Phase 8の検証済みS3 backup完成まではPhase 7環境を試験運用とする。
- 初回利用前と重要変更前にdata EBS snapshot runbookを実行可能にする。

### D-049 Phase 0設定validation gate

- **状態:** Accepted
- 設定schema validationと、stage・Phase・処理ごとのrequired validationを分離する。
- Phase 0のdev空stack synthはenvironment-agnosticとし、AWS Account ID、Availability Zone、Minecraft port/version、Route 53 Hosted Zone IDを要求しない。
- prodのPhase 0 synthはplaceholderを読込可能とした上で、現在の`null`値を全てパス付きで表示して拒否する。
- このprod拒否はPhase 0の一時的な安全gateであり、全ての`null`を永続的な必須項目と定義しない。Phase 1以降はstage・処理・Phaseごとのrequired pathを明示する。

### D-050 dev AWS CLI profileと接続先照合

- **状態:** Accepted
- ローカル開発者はIAM Identity Centerの`wishicraft-dev` profileを認証取得だけに使用する。
- Account IDとRegionの正本は`config/stages/dev.yaml`とし、profile名やSSO roleをstage設定の必須項目にしない。
- AWS CLIおよびCDKの手動コマンドでは`--profile wishicraft-dev`を明示する。CDKアプリケーションコードへprofile名を埋め込まない。
- deploy前にSTS caller identityのAccount IDをstage設定のAccount IDと照合し、不一致なら処理を中止する。

### D-051 Phase 1 RCON secretとserver artifactの安全条件

- **状態:** Accepted
- RCON passwordは登録済みSecureStringをEC2 roleが実行時に取得する。実値をCDK、user data、CloudFormation、Git、ログへ含めない。
- EC2 roleの`ssm:GetParameter`は対象Parameterへ限定し、復号した値を標準出力へ出さない。RCONはlocalhost限定で、インターネット向け受信ルールを作成しない。
- Minecraft 26.2 server.jarは公式version manifestで確認したURLとSHA-1をstage設定へ固定し、取得後に検証する。EULA同意、artifact取得、初回起動は人間の明示承認前に実行しない。
- 初期GameのEULA同意は明示済みである。artifact取得と初回起動はdeploy後の手動確認として引き続き分離する。

### D-052 Minecraft EC2のinstance metadata保護

- **状態:** Accepted
- Minecraft EC2はIMDSv2を必須とし、instance metadata tagsを有効にしない。

### D-053 RCON firewallの部分適用再開

- **状態:** Accepted
- firewall migrationは、既存script、unit、drop-in、rules file、enable symlinkを個別に不在・正本一致・衝突へ分類する。正本一致物は書き換えず再利用し、不一致物は削除・修復・上書きせず、永続変更前に停止する。
- target nft tableが既存の場合は、全persistent artifactとtable ruleが正本一致する完成状態だけを受容する。tableだけ、またはrules fileだけが残る部分適用状態は安全停止する。
- 初期bootstrapは新規instanceの作成経路であり、既存hostの再開は一回限りのmigrationを正本とする。bootstrap再実行を衝突解消手段にしない。

### D-054 RCON firewall dependency verificationとbootstrap既設物

- **状態:** Accepted
- firewall migrationは`systemctl show`の複数unit propertyを全体文字列や順序で比較しない。commandの取得失敗、空値、対象unit欠落を別checkpointでfail-closedし、完全なunit名のtoken membershipだけを確認する。
- `minecraft.service`が`not-found`の部分適用状態では、daemon-reload後に正本hash・metadataのdrop-inが存在することまでを確認して停止境界を越える。Minecraftを起動せず、unitが後から配置された際にsystemdがdrop-inを取り込む。
- bootstrap bundleは既設regular memberを無条件に上書きしない。absenceだけを排他的に配置し、正本content・mode・owner/groupの一致物はmtimeを含め無変更で受容し、不一致またはsymlinkは書込み前に停止する。

### D-055 systemd enable linkの正本判定

- **状態:** Accepted
- firewall migrationのenable linkは、`WantedBy=multi-user.target`に対応する正確な`.wants` pathにあるsymlinkだけを対象とする。
- systemdはunit fileへのlinkを絶対pathまたは相対pathで作成し得るため、`readlink`のraw文字列を固定値と比較しない。symlinkが非danglingであり、解決後targetが正確なcanonical unit fileと完全一致する場合だけ正本として受容する。
- wrong target、類似unit名、dangling link、regular file、directoryは衝突として変更前に停止する。link query失敗、`systemctl enable`失敗、enable成功後のpredicate不一致は別checkpointで記録する。
- 正本linkはraw target形式やmtimeを含め書き換えない。preflightからenable直前までの状態・形式変化はraceとして停止する。


## 3. 却下した案

### R-001 常駐小型EC2コントローラー

- **状態:** Rejected
- 実装は単純になるが、常時固定費が目的に対して大きい。

### R-002 Discordから先に作る

- **状態:** Rejected
- 不具合箇所がDiscord、Lambda、SSM、Minecraft間で切り分けにくくなる。
- EC2内部→status→workflow→Discordの順にする。

### R-003 Web管理画面から先に作る

- **状態:** Rejected
- コアの状態管理と起動停止が固まる前にUIを作ると手戻りが大きい。

### R-004 単一System State enum

- **状態:** Rejected
- 処理step、実状態、healthが混ざるため。

### R-005 DynamoDB TTLによるロック解放

- **状態:** Rejected
- TTL削除は期限直後を保証しない。

### R-006 Lambda内で起動完了まで待機

- **状態:** Rejected
- 長時間実行、再試行、可視性、費用、timeoutの面で不適切。

### R-007 Lambdaをprivate subnetへ置きNAT Gatewayを使用

- **状態:** Rejected
- 現在の要件ではSSMとAWS APIで十分で、固定費を増やす。

### R-008 `latest.log`解析による汎用チャット連携

- **状態:** Rejected
- サーバー種別ごとの差異と誤解析を増やす。

### R-009 create時にEC2を起動

- **状態:** Rejected
- 作成だけで費用と長時間operationが発生する。

### R-010 backupなしでresetを先行

- **状態:** Rejected
- データ損失リスクが高い。


### R-011 Elastic IPの常時保持

- **状態:** Rejected
- 固定IP自体が目的ではなく、Minecraftクライアントで接続先を入力し直さないことが目的である。
- 固定FQDNと起動時DNS更新で要件を満たし、停止中のpublic IPv4固定費を減らす。

## 4. Provisional decisions

### P-001 Backup保持期間

- Scheduled daily: 14日
- Manual/Pre-reset: 90日
- Pre-upgrade/delete: 180日
- Phase 8で実データ量と費用を確認して確定する。

### P-002 初期idle shutdown

- 30分を初期候補とする。
- 利用者のプレイ習慣を見て調整する。

### P-003 初期runtime class

- **状態:** Superseded by D-038
- 初期は1classのみとする方針を維持し、具体値はD-038で確定した。

### P-004 Secrets ManagerとSecureStringの分担

- **状態:** Superseded by D-040
- MVPの保存方式はParameter Store SecureStringへ確定した。

## 5. Current blockers

Phase 0開始前の重大blockerはなく、Phase 0は完了した。Phase 1は準備作業を完了し、AWSリソース実装を開始していない。

dev用Discord Guild/channel/role/Application ID/Public Keyは`config/stages/dev.yaml`へ反映済みであり、blockerではない。Discord Bot Tokenは秘密値としてGitへ保存せず、Phase 7開始前にdev用SecureStringへ登録する。

Phase別に決める事項:

| 項目 | 決定期限 |
|---|---|
| EULA同意、server.jar取得、checksum検証、初回起動の実行承認 | Phase 1 bootstrap検証前 |
| RCON password安全配布方式のEC2実装 | Phase 1 EC2 bootstrap実装時 |
| RCON client/library | Phase 2開始前 |
| dev Discord Bot TokenのSecureString登録とApplication/command設定確認 | Phase 7開始前 |
| prod Discord Guild/channel/role/Application ID/Public Key/Bot Token | 最初のprod deploy前 |
| backup整合方式 | Phase 8開始前 |
| Package manifest最終schema | Phase 9開始前 |
| 最初のPaper Package | Phase 12開始前 |
| 最初のMOD loader/package | Phase 12開始前 |
| Web frontend技術 | Phase 13開始前 |

## 6. Backlog

### 高優先

- backup workflow
- 無人自動停止
- Minecraft EC2停止漏れalarm
- Game/Package/Template一般化
- create/list/info
- reset

### 中優先

- 旧バニラPackage
- Paper Package
- 最初のMOD Package
- 管理Web HTTP版
- OP/whitelist

### 低優先・将来

- WebSocket realtime
- Minecraft→Discord chat
- `/mc say`
- Discord Gatewayによる完全双方向chat
- restore UI
- Game upgrade
- archive/delete
- Package Web upload
- 高度なrole model
- plugin/mod独自権限
- chat履歴長期保存・検索
- sessionごとのDiscord thread

## 7. Decision追加テンプレート

```markdown
### D-XXX タイトル

- **状態:** Proposed | Accepted | Rejected | Superseded
- **日付:** YYYY-MM-DD
- **背景:**
- **決定:**
- **理由:**
- **影響:**
- **代替案:**
- **関連文書:**
```
