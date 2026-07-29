# 07. Operations, Security, and Cost

- **文書状態:** Canonical
- **最終更新:** 2026-07-29

## 1. 運用原則

- 日常操作はDiscordで完結させる。
- シェル接続は初期構築、Package検証、障害調査、手動復元に限定する。
- SSM Session Managerを優先し、SSHポートを常設しない。
- 保存状態を手動でREADYやSTOPPEDへ書き換えて障害を隠さない。
- 実状態を修復し、reconcileでObserved Stateを更新する。
- ワールド保護を復旧速度より優先する。

## 2. 環境

### dev

- 開発・統合テスト用。
- 専用prefixとタグを使用する。
- 本番Gameデータを置かない。
- 短いログ保持期間を許可する。

### prod

- 実利用用。
- 破壊的変更前にbackupを取る。
- 手動console変更を避ける。
- CDK diffを確認してからdeployする。

初期は同一AWSアカウント内にdev/prodを作成してよいが、リソース名、table、bucket、secretを完全に分離する。コードと設定schemaはPhase 0から両stageを扱えるようにし、`config/stages/prod.yaml`はplaceholderとしてGit管理してよい。Phase 0〜7の初期deployはdevだけを基本とし、prod AWSリソースは最初の実用リリース直前に作成する。prodの必須値が未確定の間は、prod向けsynth/deployをvalidationで停止する。

## 3. IAM方針

### Command Lambda role

許可例:

- Parameter/Secret読取の必要最小範囲
- Operationsへの作成
- Step Functions `StartExecution`
- Discordログ用CloudWatch

EC2 start/stopやSSM実行権限を直接持たせず、workflow Task roleへ分離する。

### Workflow Task roles

責務別Lambdaに必要な権限だけを付ける。

例:

- EC2状態取得のみ
- 特定instanceのstart/stop
- 特定managed nodeへのSSM command
- 特定table item操作
- 特定Discord secret読取

Resource `*`を避ける。AWS APIの制約でResource制限できないActionはconditionと監査を追加する。

### Minecraft EC2 role

- SSM managed instance
- 必要なS3 backup/package path
- heartbeat用DynamoDBの特定item/table
- CloudWatch logs/metricsの必要範囲

EC2から他instanceのstart/stopやIAM変更を許可しない。

### 管理者

- 日常作業はIAM user access keyではなく、SSO/role等の短期credentialを推奨する。
- root userはMFAを設定し、通常使用しない。

## 4. Network security

### Inbound

- Minecraftポートのみ。
- 利用者IPを固定できる場合はCIDR制限を検討できる。
- SSH 22: 原則なし。
- RCON: なし。
- Query: なし。
- Minecraftは`online-mode`と静的ホワイトリストをMVPから有効にする。
- EC2上の管理Web/API: なし。

### Outbound

- SSM、S3、DynamoDB、CloudWatch、OS更新等に必要なHTTPS。
- 過度に厳密なegress制限は、必要endpointが整理できてから導入する。

### Lambda

- ユーザーVPCへ接続しない。
- NAT Gatewayを使用しない。


### Fixed endpoint

- Elastic IPを初期構成へ含めない。
- Route 53の固定FQDNをMinecraftクライアントへ登録する。
- EC2起動時に現在の動的パブリックIPv4へAレコードを更新する。
- Route 53変更が`INSYNC`となるまでオンライン完了を通知しない。
- EC2停止完了後はAレコードを削除する。
- Route 53権限は対象Hosted Zoneとrecord nameへ限定する。

### Data EBS protection

- data EBSは暗号化し、EC2とは別リソースとして同一Availability Zoneへ配置する。
- CDK removal policyは保持を基本とする。
- filesystemが存在しない場合だけ初期化する。
- filesystem UUIDでmountする。
- mount確認失敗時はMinecraft、backup、resetを実行しない。

## 5. Secret管理

秘密情報:

- Discord Bot Token
- Discord OAuth Client Secret
- RCON password
- Web session signing key

規則:

- Gitへ保存しない。
- `.env`を本番正本にしない。
- Lambda environmentへ平文値を直接埋め込まない。
- CloudWatch logへ出さない。
- Discord errorへ出さない。
- ローテーション手順を用意する。

Discord public key、Guild ID、Channel ID、Role IDは秘密ではないが、環境設定としてParameter Store等へ置く。

### MVPの保存方式

- Discord Bot Token: Parameter Store `SecureString`
- RCON password: Parameter Store `SecureString`
- 暗号化: AWS管理KMS keyを初期値とする
- CDKとアプリケーションへ渡す値: 秘密値ではなくParameter名
- Secrets Manager: 自動rotation等が必要になった場合に再評価

Phase 1では、EC2 instance roleの`ssm:GetParameter`をdev用RCON SecureStringへ限定する。CDK、user data、CloudFormation、Git、通常ログに実値を含めない。EC2内では復号値を標準出力へ出さず、RCONを含む`server.properties`を`root:minecraft`・`0640`で作成する。RCONのインターネット向け受信ルールは作成しない。

推奨Parameter名:

```text
/wishicraft/dev/secret/discord-bot-token
/wishicraft/dev/secret/rcon-password
/wishicraft/prod/secret/discord-bot-token
/wishicraft/prod/secret/rcon-password
```

## 6. ログ

### 構造化ログ

最低限:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "component": "reconcile-lambda",
  "operation_id": "op-...",
  "game_id": "game-...",
  "step": "WAIT_SSM_ONLINE",
  "event": "ssm_state_observed",
  "result": "online"
}
```

### 出力しないもの

- secret/token/password
- AWS credential
- プレイヤーのチャット本文をコアログへ常時保存
- ワールドファイル内容
- Discord Interaction Token

### 保持期間の初期値

- dev Lambda logs: 14日
- prod Lambda/Step Functions関連logs: 30日
- security/critical operation logs: 90日を候補
- Minecraft通常ログ: data volume容量を監視しrotate

保持期間はCDKで明示する。

## 7. 監視とアラーム

### Phase 7の初回実用リリース前に必須

- AWS Budgets通知
- CloudWatch Logs保持期間設定
- start workflow失敗
- stop workflow失敗
- EC2が設定時間を超えてrunning
- Desired STOPPEDなのにEC2 running
- Desired RUNNINGなのに長時間READYでない
- operation lock期限超過
- Lambda error/throttle

### Phase 8の機能導入と同時に追加

- backup失敗
- heartbeat stale
- data volume使用率高騰
- 自動停止失敗

### 通知先

初期は管理者向けDiscord channelまたはSNS emailを使用する。通知経路自体の失敗を考慮し、CloudWatch/Step Functions consoleでも追跡できるようにする。

## 8. コスト保護

### 初期閾値

- 月額Budget: 15 USD
- Budget通知: 50%、80%、100%、予測100%
- EC2長時間running警告: 8時間
- Desired STOPPEDかつEC2 running警告: 15分
- dev log retention: 14日

具体値の正本は`config/stages/<stage>.yaml`とする。Parameter StoreやLambda environmentへ配布された公開値を人間が独立して変更しない。

### 必須対策

- AWS Budgets月額通知
- 予測コスト通知
- Minecraft EC2長時間running alarm
- NAT Gatewayを作らない
- 不要なpublic IPv4、snapshot、volume、Hosted Zoneを棚卸し
- CloudWatch log retention
- S3 lifecycle
- DynamoDB on-demandを基本とする
- 状態変化がない場合の不要writeを避ける

### Cost anomaly候補

- EC2 stop failure
- 高スペックruntime classの停止漏れ
- backup archive急増
- CloudWatch logs急増
- WebSocketまたはGateway Bot導入後の常駐費

### タグ

Cost allocationのため全リソースへProject/Stage/Owner/ManagedByを付ける。

### Backup完成前の試験運用

Phase 7完了からPhase 8の検証済みS3 backup完成までは試験運用とする。

- 初回利用前にdata EBS snapshotを取得するrunbookを用意する。
- 重要なCDK変更、Minecraft version変更、systemd変更前にもsnapshotを確認する。
- snapshot取得を通常stopやbackup workflowの代替として恒久運用しない。


## 9. Backup方針

### 種別

- `MANUAL`
- `SCHEDULED`
- `PRE_RESET`
- `PRE_UPGRADE`
- `PRE_DELETE`

### 初期保持案

Provisionalとして次を採用する。

- Scheduled daily: 14日
- Manual: 90日
- Pre-reset: 90日
- Pre-upgrade/delete: 180日

利用量とS3費用を確認して調整する。重要Gameのbackupを自動で即時削除しない。

### S3 bucket保護

- dev/prodでbucketを分離する。
- Block Public Accessを全面有効化する。
- server-side encryptionを有効化する。
- bucket、prefix、operationへ必要な最小権限だけをIAMへ付与する。
- CDK removal policyを明示し、prod backupをstack削除で自動削除しない。
- lifecycleはbackup typeと保持期間に従う。
- versioningやObject Lockは復旧要件と費用を評価してDecisionへ記録する。


### 実行タイミング

- 停止中Gameをscheduled backupだけのために毎日起動しない。
- 通常stop中、稼働中の整合save後、または明示的manual backupで作成する。
- 前回backup以降に変更がない停止中Gameはscheduled backupをskipできる。
- Pre-reset、Pre-upgrade、Pre-deleteは必ず検証済みbackupを作る。

### 整合性

起動中backup:

1. RCON保存要求
2. 必要に応じてsave-off等の整合方式をPackageごとに定義
3. archive
4. checksum
5. S3 upload
6. verify
7. 通常保存状態へ復帰

実装が安全にできるまでは、停止中backupまたは短時間停止backupを優先してよい。

### 復元テスト

- 利用者向けrestore UIより先に管理者runbookを作る。
- 本番Gameへ直接上書きせずstagingへ復元する。
- checksum、server start、world loadを確認する。
- 少なくとも大きな仕様変更前に復元テストする。

## 10. 自動停止

### 観測

Minecraft EC2上のheartbeat agent/timerが専用`RuntimeHeartbeats` itemへ次を送る。EC2 roleからSystemState、Operations、Locksを直接更新させない。

- active game
- protocol state
- player count
- observed at
- empty since

### 判定

- player countがnullの場合、0人とみなして停止しない。
- 0人の観測が一定時間継続した場合だけ停止候補とする。
- 新しいplayer接続で`empty_since`を解除する。
- stop operation開始前に最新heartbeat/reconcileを再確認する。

### 失敗

自動停止失敗は再試行回数を制限し、無限operationを作らない。管理者へ通知する。

## 11. デプロイ手順

### 通常

1. test/lint/type check
2. dev向け`cdk synth`
3. dev向け`cdk diff`
4. 変更対象と破壊的差分確認
5. dev deploy
6. dev integration test
7. prodの必須設定がすべて確定していることをvalidationで確認
8. prod backup確認
9. prod向け`cdk synth`と`cdk diff`
10. prod deploy
11. smoke test
12. operation/alarms確認

### 破壊的変更

次を含む場合は別作業に分ける。

- DynamoDB key変更
- S3 bucket replacement
- EBS replacement/detach
- EC2 replacement
- Security Group公開範囲拡大
- secret replacement
- state machine behavior大幅変更

Codexは`cdk diff`の結果を確認せず破壊的deployを推奨しない。

### Workflow外のEC2停止とstale DNS

1. EC2 state change eventまたはReconcileで`stopped`/`terminated`を確認する。
2. start operationが進行中でないことを確認する。
3. 固定FQDNのAレコードが残っている場合は削除する。
4. Route 53変更の`INSYNC`を確認する。
5. cleanup失敗は管理者へ通知する。

解放済みパブリックIPv4を固定FQDNが指し続ける状態を放置しない。


## 12. 障害対応runbook

### 状態不一致

1. `/mc status`またはReconcile実行
2. Desired/Observed/current operation確認
3. Step Functions execution確認
4. Lockのowner/expiry確認
5. EC2 API確認
6. 必要時SSM Session Manager
7. data volume mount/systemd/journal/RCON確認
8. 実状態を修復
9. Reconcile再実行
10. operationとincident記録

保存値だけを書き換えて正常化しない。

### EC2 runningだがSSM offline

1. EC2 status check
2. network/outbound確認
3. SSM Agent状態
4. IAM instance profile
5. OS disk/full状態
6. 復旧不能ならMinecraft dataを保護して再構築を検討

### Minecraft応答なし

1. systemd state
2. process/memory/disk
3. latest log
4. RCON設定
5. active game runtime
6. timeout内なら起動継続を待つ
7. 強制停止前にデータ状態とbackupを確認

### Stop失敗

1. save結果確認
2. Minecraft process確認
3. Java hang/child process
4. data flush待機
5. 管理者承認後だけ強制停止
6. 次回起動時world検証

### Lock残留

1. operationの実行状態確認
2. Step Functionsが継続中なら奪取しない
3. operation終了済みかつlease期限切れを確認
4. 条件付きで新operationが取得
5. 手動deleteは最終手段

## 13. Emergency stop

通常stopが失敗し、費用または安全上EC2停止が必要な場合の管理者限定手順。

- ワールド破損リスクを明示する。
- 実行前に可能な限りdisk snapshotまたはcopyを取る。
- Discord公開操作とは分離する。
- 実行者、理由、状態、時刻を記録する。
- 次回起動前にワールド検証する。

通常機能として安易に自動fallbackしない。
