# 06. Delivery Plan

- **文書状態:** Canonical
- **最終更新:** 2026-08-22

## 1. 開発原則

- 横断的な基盤を一気に作らず、端から端まで動く小さい完成物を積み上げる。
- Discord、AWS制御、EC2内部処理を同時に作らない。
- 状態確認を起動・停止より先に作る。
- backupを複数ゲーム、reset、MODより先に作る。
- WebページをDiscord MVPより先に作らない。
- 各フェーズは人間が実行結果を確認してから次へ進む。

## 2. フェーズ一覧

| Phase | 目的 | 主な完成物 |
|---:|---|---|
| 0 | リポジトリと設計土台 | Python/CDK/pytest、文書、CI |
| 1 | Minecraft EC2手動起動 | EC2、EBS、Route 53、SSM、systemd、バニラ1個 |
| 2 | itzg Host Runtime境界 | migration contract、mapping/apply、probe/start/stop command path |
| 3 | 実測status | Reconcile Lambda、SystemState |
| 4 | Operationと排他制御 | Games/Operations/Idempotency/Locks、条件付き更新 |
| 5 | 安全なstart | Start Step Functions |
| 6 | 安全なstop | Stop Step Functions |
| 7 | Discord MVP | `/mc status/start/stop` |
| 8 | 運用保護 | backup、自動停止、heartbeat、追加監視 |
| 9 | 複数ゲーム抽象 | Package/Preset/Template/Game、runtime class |
| 10 | ゲーム作成 | create/list/info/templates、materialize |
| 11 | reset | generation、最終backup、旧世代保持 |
| 12 | サーバー種別拡張 | 旧バニラ、Paper、MOD |
| 13 | 管理Web | OAuth2、HTTP、ポーリング、必要時WebSocket |
| 14 | プレイヤー管理 | OP、ホワイトリスト |
| 15 | チャット連携 | 一方向、通知、say、必要時双方向 |
| 16 | 高度機能 | restore、upgrade、archive、delete |

## 2.1 Phaseと主要要件の対応

| Phase | 主要要件 |
|---:|---|
| 0 | SYS-004、NFR-005〜007 |
| 1 | SYS-001、SYS-003、EC2-001〜010 |
| 2 | SYS-006、STA-001、START-006、STOP-001〜005、EC2-007/011/012、NFR-010/011 |
| 3 | STA-001〜006 |
| 4 | SYS-002、OPR-001〜010、NFR-002、NFR-003 |
| 5 | START-001〜008、EC2-008 |
| 6 | STOP-001〜005、STOP-007、EC2-008 |
| 7 | DIS-001〜007、NFR-008、NFR-009 |
| 8 | BAK-001〜006、NFR-004、自動停止要件 |
| 9以降 | GAME、PKG、CREATE、RESET、WEB、OP、CHATの各LATER要件 |

各Codex作業では、この表だけでなく対象機能の個別要件IDを明示する。


## 3. Phase 0 — リポジトリと設計土台

- **状態:** Completed（2026-07-29）

### 目的

コードを書く場所、依存関係、テスト、デプロイ単位を確定する。

### 採用技術

- Python 3.12
- `uv`と`uv.lock`
- AWS CDK v2 for Python
- pytest
- Ruff
- mypy

### 推奨構成

```text
repository-root/
  README.md
  pyproject.toml
  cdk.json
  config/
    project.yaml
    stages/
      dev.yaml
      prod.yaml
    secrets.example.yaml
  infrastructure/
    app.py
    stacks/
    constructs/
  src/
    domain/
    application/
    repositories/
    integrations/
    lambdas/
  ec2/
    scripts/
    systemd/
    bootstrap/
  step_functions/
  tests/
    unit/
    integration/
  packages/
  docs/
    01_...md
    ...
    12_initial_configuration.md
```

### 作業

1. Python project作成
2. CDK app作成
3. dev/prodの設定schemaと読込contextを作成し、`prod.yaml`は未確定値を保持するplaceholderとして扱う
4. pytest、lint設定
5. CIでtest/lint実行
6. 設定読込と命名helper
7. dev用の空`MinecraftStack`をsynthできる状態
8. `config/project.yaml`と`config/stages/dev.yaml`、`config/stages/prod.yaml`のschema、読込、validationを作成
9. `project.yaml`、stage別YAML、`secrets.example.yaml`の責務を分離する
10. Git管理YAMLを公開設定の正本とし、Parameter Store Stringを独立した正本にしない
11. `null`や`TO_BE_CONFIRMED`を推測せず検出・報告する
12. 初期deployはdevだけとし、prod AWSリソースは最初の実用リリース直前に作成する方針をREADMEへ記載
13. prodの必須値が`null`の間は、prod向けsynth/deployを不足項目の分かるvalidation errorで停止する

### 完了条件

- clean checkoutから環境構築手順がREADMEにある。
- unit testとlintを実行できる。
- dev向け`cdk synth`が成功する。
- secretの実値がGitへ入らない。
- `config/project.yaml`と`config/stages/dev.yaml`を読み込み、必須値と未確定値を区別できる。
- `config/stages/prod.yaml`をplaceholderとして読み込めるが、必須値が未確定のprod向けsynth/deployは明示的に拒否できる。
- `config/secrets.example.yaml`に秘密値ではなくParameter名だけが記載されている。
- この文書群と`docs/12_initial_configuration.md`がリポジトリ正本として配置されている。

### 対象外

- AWSリソースの本番作成
- Discord接続
- Minecraftインストール

### 完了記録

- `6a9b8c0 feat: implement Phase 0 project foundation`で完了した。
- Python 3.12環境でpytest 11件、Ruff、mypy、dev向けenvironment-agnostic `cdk synth`が成功した。
- prod向けsynthは、現在の`null`値をパス付きで列挙して意図的に拒否することを確認した。
- GitHub Actions CI run #1が成功した。
- deploy、`cdk diff`、AWS credential/profile設定、Phase 1実装は未実行である。

## 4. Phase 1 — Minecraft EC2の手動基盤

- **状態:** Completed（2026-08-22）

### 目的

制御系なしで、AWS上のMinecraftを人間が安全に起動・接続・停止できる状態にする。

2026-08-22時点でdevのRCON firewall migration、Minecraft 26.2初回起動、whitelist修復、正常保存・停止、EC2停止・再起動を完了した。第33回・第34回でworld保存完了とprocess/listener消滅を確認し、再起動後の第35回read-only診断とクライアント目視で、停止前のworld変更が同じdata EBS上に保持されたことを確認した。登録者メール確認後に固定FQDNのDNS公開を検証し、ユーザーが`mc-dev.wishicraft.net:25565`から接続できることを確認した。CI run `32570087910`はsuccessである。終了時はAレコードを正常削除し、Minecraftのprocess/listener消滅、XFS data EBS上のworld保持を確認してEC2を通常停止した。全受入条件が合格したためPhase 1を正式完了とする。

### 最初の作業単位（完了）

- Phase 1 dev synth/deploy用required validationを追加した。
- devのAWS接続先、Java 25、Minecraft 26.2、Hosted Zone、公式server.jar URL/SHA-1を設定の正本へ記録した。
- AWS CLI profile、RCONの実行時配布、artifact検証、EULA承認gateの設計とrunbookを記録した。
- CDK bootstrap、`cdk diff`、deploy、AWSリソース作成、server.jar取得、EULA設定、Minecraft起動は未実行である。

### 作業

1. Public subnetとInternet Gateway
2. Minecraft Security Group
3. EC2 IAM role
4. EC2 instance
5. 起動中だけ使用する動的パブリックIPv4
6. Route 53 Hosted Zone参照と、固定FQDNを更新・削除する管理用runbookまたは管理CLI
7. root EBSと保持対象data EBS
8. data volumeのUUID mount
9. Java
10. 新規バニラserver
11. `online-mode`と静的ホワイトリスト
12. localhost RCONとSecureStringからの安全なsecret配布
13. Minecraft EULA同意手順
14. 公式配布情報からversion固定したserver取得
15. systemd unit
16. SSM Session Manager接続

### Phase 1でのDNS操作主体

Phase 1ではLambdaとStep Functionsをまだ実装しないため、動的Aレコードの更新・削除はシステム管理者が管理用runbookまたはリポジトリ内の管理CLIから行う。動的AレコードをCDKの固定状態として管理しない。

1. EC2を起動し、現在のパブリックIPv4を取得する。
2. 対象Hosted Zoneとstage別固定FQDNを確認する。
3. 固定FQDNのAレコードを現在のIPv4へUPSERTする。
4. Route 53 changeが`INSYNC`になったことを確認する。
5. DNS解決結果とMinecraft接続を確認する。
6. Minecraftを安全に保存・停止し、EC2が`stopped`になったことを確認する。
7. 固定FQDNのAレコードを削除する。
8. Route 53 changeが`INSYNC`になり、古いIPv4を指していないことを確認する。

このrunbookによる操作はPhase 1の検証専用とし、Phase 5のstart workflowとPhase 6のstop workflowで自動処理へ置き換える。

### 手動確認

```text
EC2起動
→ SSM online
→ data volume mounted
→ minecraft.service start
→ 現在のpublic IPv4へAレコードUPSERT
→ Route 53 INSYNCとDNS解決確認
→ クライアント接続
→ ブロック設置等の変更
→ save/stop
→ EC2停止
→ Aレコード削除
→ Route 53 INSYNC確認
→ 再起動
→ ワールド変更が保持
```

### 完了条件

- SSH受信ルールがない。
- RCONが外部公開されていない。
- Minecraftポートだけが必要範囲へ公開されている。
- EC2再起動・停止後もdata volumeが正しくマウントされる。
- data EBSはEC2置換やCDK削除で自動削除されない。
- mountされていない状態でMinecraftがroot volumeへデータを作らない。
- 固定FQDNが現在のEC2パブリックIPv4を指す。
- EC2停止後はAレコードが削除される。
- ホワイトリスト外のプレイヤーが接続できない。
- バニラワールドが永続化される。
- systemdで起動・停止できる。
- EULA同意、server取得元、version、取得物の検証方法がrunbookへ記録されている。
- `t3a.medium`とXmx `3G`でOS、SSM、JVM native memoryを含む余裕を確認し、free memory、JVM RSS、OOM、CPU creditを記録する。

### 対象外

- Discord
- Lambda
- DynamoDB
- 複数Game
- MOD/Paper

## 5. Phase 2 — itzg Host Runtime境界

- **状態:** In Progress（Phase 2 target platform lock確定、実機migration前）

### 目的

AWS制御面から呼び出す安定したHost Runtime interfaceを、itzg/docker-minecraft-serverをMinecraft Runtimeとして作る。Phase 1の直接Java/systemd実装は完了履歴として維持し、このPhaseで無条件に削除しない。

### 実装順

1. Phase 2 Decision Neededを解消する（image tag/digest、Docker/Compose、UID/GID、resource limit、lifecycle owner、timeout、command path、secret injection、desired/applied schema）。
2. Phase 1 runtimeを「維持 / 再設計・置換 / 退役候補」に固定し、rollback可能な移行・同等性条件を定義する。
3. desired stateのsource of truthと、boot-time / runtime operation別のmapping/apply契約を確定する。
4. data EBS mount guard後にのみ起動できるHost Runtime（systemd / Docker / Compose）契約を作る。
5. 管理portをpublishしないhost-local / container-local command pathを作る。
6. itzg最小構成でprobe、start、READY、save、graceful stop、world永続性のinterfaceを検証する。
7. Control Plane向けの`probe_game` / `start_game` / `stop_game`相当adapterとunit testを作る。
8. SSM Run Commandによるdev確認は明示承認を得て別作業で実施する。
9. 新経路で代替済みの独自Minecraft Runtimeだけを個別に退役する。

### Phase 2a scope

AWS適用前のrepository-only単位として、platform/runtime lock、AL2023標準Docker + checksum固定Compose installer、numeric identity/filesystem preflight、restartなしCompose/systemd artifact、timeout scope、secret-free canonical renderer、static/local testを作る。既存EBS UID/GIDはObservation Requiredのまま推測しない。release-specific AMI identityはD-062で確定した。RCON command path、secret injection、desired/rendered/appliedの永続化、旧runtime退役は後続単位とする。

### Phase 2b-1 scope

実data変更前のcompatibility gateとして、GitHub-hosted Linux x86_64 runner上で固定itzg tag+digestを使用するsynthetic Docker integration testを行う。`SETUP_ONLY=true`でMinecraft processを起動せず、既存`server.properties` ownershipの失敗再現、一件migration後の更新、`SKIP_CHOWN_DATA`、restart idempotency、RCON disabled時のsecret artifact不存在を検証する。実world、実properties、AWS、EC2、SSM、secretは使用しない。

Phase 2 target platform reviewはD-062で完了し、AL2023 `2023.12.20260803` / kernel 6.18 / ap-northeast-1公式x86_64 AMIを固定した。Phase 1 instanceのas-built `2023.12.20260803.3` / kernel 6.1は変更しない。

### 実機migration gate

以下を順序どおり個別の承認・検証単位として進める。D-063で1〜5は独立target stack上のroot-only validationとして実施し、Phase 1と実data EBSから隔離する。5の完了後はtargetを停止し、6より前、すなわち実data EBS migration直前で停止する。

1. target EC2作成前preflight
2. target host UID/GID 993 collision確認
3. Docker / Compose install
4. itzg image pull/digest確認
5. Docker/Compose/Host Runtime実動作確認
6. Phase 1完全停止
7. data EBS migration
8. `server.properties` ownership migration
9. itzg最小起動
10. READY / world persistence / graceful stop
11. rollback確認

### Phase 1 migration inventory

| 分類 | Phase 1実装 | Phase 2以降の扱い |
|---|---|---|
| 維持 | VPC / subnet / IGW / Security Group | Control PlaneのAWS基盤。SGはMinecraft接続portだけを公開する。 |
| 維持 | EC2 IAM Role / SSM | Control PlaneからHost Runtimeへの管理経路。権限は最小化を維持する。 |
| 維持 | data EBS / Retain | worldとruntime realizationの永続基盤。container layerを正本にしない。 |
| 維持・強化 | XFS / UUID mount / mount guard | Host Runtimeの前提。container起動前のfail-closed gateにする。 |
| 維持 | Discord whitelist操作 | 認可と許可プレイヤーdesired stateはControl Planeに残す。Minecraft固有反映はitzgへ委譲する。 |
| 維持 | Step Functions / DynamoDB | 状態遷移、排他、operation、desired stateを担当する。Minecraft実状態の正本にはしない。 |
| 再設計・置換 | Minecraft systemd service | Java直接起動からHost Runtime / Compose lifecycle制御へ置換する。 |
| 再設計・置換 | RCON用host firewall | 管理port非publishのcontainer-local設計へ置換し、代替確認後に独自nftablesを退役する。 |
| 退役候補 | Corretto 25 host installer | Java runtimeをitzg imageへ委譲する。 |
| 退役候補 | server.jar URL / SHA-1 downloader | Minecraft distribution取得をitzgへ委譲する。 |
| 退役候補 | whitelist artifact独自配置・修復 | 許可者の正本はControl Planeに残し、Minecraft形式への反映をitzg/runtimeへ委譲する。 |

分類はtarget architectureでの扱いであり、Phase 1の完了事実や証跡を変更しない。退役は新経路の機能同等性とrollback条件をdevで確認した後の別作業とする。

### 確認ケース

- 停止中probe
- 起動中probe
- READY probe
- RCON不応答
- data volume未マウント
- start二重実行
- 別Game ID指定
- stop二重実行
- save失敗
- 同じoperation IDの再実行

### 完了条件

- stdout JSON契約に従う。
- 任意パスを受け取らない。
- 同じoperation IDで破壊的処理を重複しない。
- startは起動要求まで、READY判定はprobeで行う。
- stopは保存成功とプロセス終了を確認する。
- SSM経由で実行できる。
- management portがhost / Internetへpublishされていない。
- boot-time設定とrunning server操作が契約上区別されている。
- lifecycle ownerが一意で、下位restartがControl Planeの停止意図を打ち消さない。
- GitとControl Plane storeに同じ設定キーを二重に正本化していない。

## 6. Phase 3 — 実測status

### 目的

AWS側から実状態を取得し、DynamoDBへ安全に保存する。

### 作業

1. SystemState table
2. EC2 API adapter
3. SSM node status adapter
4. Run Command adapter
5. Route 53/public IPv4 adapter
6. stale DNS cleanup判定
7. probe parser
8. Reconcile domain service
9. Reconcile Lambda
10. unit tests
11. AWS integration test

### 確認ケース

- EC2 stopped
- pending
- running + SSM offline
- SSM online + service inactive
- service active + protocol not-ready
- READY
- active game mismatch
- DNS target mismatch
- Route 53確認不能
- AWS API error
- SSM timeout
- 古い観測結果の競合更新

### 完了条件

- 各状態を分離して返す。
- player count不明を0にしない。
- UNKNOWNを正しく扱う。
- `observed_at`とversionで古い更新を防ぐ。
- Lambda test eventまたはCLIから実行できる。

## 7. Phase 4 — Operationと排他制御

### 目的

start/stopを安全に実行するための履歴とロックを作る。

### 作業

1. Games table
2. Operations table
3. Idempotency table
4. Locks table
5. repository層
6. Operation admission transaction
7. status admission
8. 管理CLIまたはadmission Lambda test event
9. step更新
10. success/failure更新
11. lock acquire/renew/release
12. owner条件付きcurrent operation解除
13. duplicate idempotency tests
14. stale lock takeover tests
15. optimistic locking/部分更新tests

### 完了条件

- 同一operation IDまたはidempotency keyを二重作成しない。
- 同じidempotency keyの再送では既存operation IDを返す。
- CLI確認でもOperation admissionを迂回してState Machineを直接開始しない。
- STATUS OperationはLockとCurrent Operationを使用しない。
- Idempotency、Operation、Lock、Current OperationをTransactionで一体として受付できる。
- 有効ロックがある場合にOperationやworkflowを新規作成せず競合を拒否する。
- 期限切れロックを条件付きで引き継げる。
- 他operationのロックを解放できない。
- TTL削除を待たずに正しく判断できる。
- 初回GameがGames tableへ登録されている。

## 8. Phase 5 — 安全なstart workflow

### 目的

AWS Console/CLIから固定バニラGameを安全に起動する。

### State Machine

```text
VerifyAdmissionAndLock
→ PrepareProgressMessageIfConfigured
→ ReconcileBeforeStart
→ ValidateStart
→ SetDesiredRunning
→ StartEc2IfNeeded
→ WaitEc2Running
→ WaitSsmOnline
→ RunStartScript
→ WaitRenewLockAndProbeMinecraft
→ VerifyActiveGame
→ UpdateDnsRecord
→ WaitDnsInSync
→ MarkSucceeded
→ ReleaseLock
```

Catch:

```text
RecordFailure
→ ReconcileAfterFailure
→ ReleaseOwnedLock
→ Fail
```

### 実装上の注意

- Wait +短いTaskでpollする。
- 各poll周期でLockを延長し、副作用直前に所有権を確認する。
- 各TaskにTimeout/Retryを明示する。
- Retry可能なAWS一時障害と、状態競合を分ける。
- EC2 already runningを正常分岐として扱う。
- 同じGame READYを冪等成功として扱える。
- 別Game activeは失敗。
- Discord metadataがないCLI operationではprogress message作成をskipする。
- `SetDesiredRunning`後の失敗ではDesired `RUNNING`を維持し、再観測結果とDiscrepancyを記録する。

### 完了条件

- CLIからOperation admissionを経由してstart workflowを開始できる。
- EC2 stoppedからMinecraft READYかつ固定FQDN接続可能になる。
- READY状態で再実行して二重起動しない。
- timeout時に実状態を再観測する。
- operation履歴とcurrent stepを追える。
- 失敗後にロックが永久残留しない。

## 9. Phase 6 — 安全なstop workflow

### State Machine

```text
VerifyAdmissionAndLock
→ PrepareProgressMessageIfConfigured
→ ReconcileBeforeStop
→ ValidateStop
→ SetDesiredStopped
→ RequestSaveAndStopMinecraft
→ WaitMinecraftStopped
→ StopEc2IfNeeded
→ WaitRenewLockAndEc2Stopped
→ DeleteDnsRecord
→ WaitDnsInSync
→ ReconcileAfterStop
→ MarkSucceeded
→ ReleaseLock
```

### 確認ケース

- READYから正常停止
- EC2 running/Minecraft stoppedから停止
- EC2 already stopped
- RCON save失敗
- Minecraft stop timeout
- EC2 stop timeout
- operation再実行
- Discord metadataなしのCLI operation
- Desired STOPPED更新後のsave/stop失敗

### 完了条件

- 保存失敗時に通常停止を続行しない。
- Minecraft process停止を確認する。
- EC2 stoppedまで確認する。
- 既停止stopは冪等に扱う。
- stop成功後のDesired/Observedが一致する。
- `SetDesiredStopped`後の失敗ではDesired `STOPPED`を維持し、残存実状態を記録する。

## 10. Phase 7 — Discord MVP

### 目的

一般利用者がDiscordだけで固定バニラGameを利用できるようにする。

### 実装順

1. Discord Application設定手順
2. API Gateway
3. Command Lambda署名検証
4. Guild/channel/user/role認可
5. `/mc status`
6. `/mc start`
7. `/mc stop`
8. Deferred Response
9. Bot Tokenによる公開進捗更新
10. Discord API error handling

### 完了条件

```text
Discord start
→ 受付公開
→ 進捗更新
→ READY公開
→ クライアント接続
→ Discord status
→ Discord stop
→ 保存
→ EC2 stopped公開
```

追加条件:

- 不正署名を拒否する。
- 権限不足は本人限定。
- コマンド連打でoperationを増殖させない。
- 内部error detailを公開しない。
- Discord更新失敗だけでMinecraft操作結果を偽装しない。

このPhase完了を最初の実用リリースとする。ただし次の最低限監視も同時に有効でなければならない。

- AWS Budgets通知
- CloudWatch Logs保持期間
- start/stop workflow失敗alarm
- EC2長時間running alarm
- Desired STOPPEDかつEC2 runningのalarm
- operation lock期限超過alarm
- Desired RUNNINGかつ長時間READYでないalarm
- Lambda error/throttle alarm
- Phase 8 backup完成まで使用する手動EBS snapshot runbook

Phase 8の検証済みbackupが完成するまでは試験運用とし、初回利用前と重要変更前にsnapshot runbookを実行する。

## 11. Phase 8 — 運用保護

### 8.1 Backup

1. `backup_game.py`
2. 停止中Gameをbackupだけのために起動しないscheduled policy
3. dev/prod分離したS3 bucket
4. Block Public Access、暗号化、最小権限IAM、removal policy
5. archive/checksum/manifest
6. backup workflow
7. `/mc backup`管理者コマンド
8. 手動復元runbook
9. 復元テスト

### 8.2 無人自動停止

1. heartbeat agent/timer
2. RuntimeHeartbeats tableとEC2 roleの限定write
3. player count/empty_since
4. EventBridge判定
5. stop workflow再利用
6. 停止予告
7. 再接続時キャンセル条件

### 8.3 追加監視・コスト調整

- Phase 7で導入したBudgets閾値とEC2 running alarmの見直し
- heartbeat stale
- backup failed
- data volume使用率
- Log retentionの見直し
- S3 lifecycle

### 完了条件

- 検証済みbackupをS3へ作れる。
- runbookで別stagingディレクトリへ復元確認できる。
- 無人時間経過で通常stopを開始できる。
- player再接続で停止条件を解除できる。
- 停止漏れを通知できる。

## 12. Phase 9 — 複数ゲーム抽象

### 目的

固定バニラ専用コードを、Package/Preset/Template/Gameモデルへ一般化する。

### 作業

1. Package manifest v1確定
2. Package archive/S3
3. Packages table
4. Preset representation
5. Templates table
6. Game正式schema
7. resolver
8. materializer
9. runtime class
10. stopped時instance type変更
11. Game選択付きstart

### 完了条件

- 既存固定バニラGameを新モデルで起動できる。
- package checksumを検証する。
- package versionを上書きしない。
- Gameごとに具体versionへ固定する。
- 同時起動1Gameを維持する。

## 13. Phase 10 — create/list/info/templates

### createフロー

```text
Discord wizard
→ template選択
→ game名/seed等
→ 確認
→ Game metadata作成
→ UNMATERIALIZED
```

初回start:

```text
Package download
→ checksum
→ staging展開
→ config生成
→ Game directory確定
→ Minecraft初回生成
```

### 完了条件

- createだけでEC2を起動しない。
- display name重複を防ぐ。
- materialize失敗で本番Gameディレクトリを汚さない。
- list/info/templatesで必要な情報を表示する。

## 14. Phase 11 — reset

### 前提

- backup workflowと復元テストが完了済み。
- Package manifestにreset対象が定義済み。

### フロー

```text
AdmitOperation
→ VerifyAdmissionAndLock
→ EnsureGameStopped
→ FinalBackup
→ VerifyBackup
→ ArchiveCurrentGeneration
→ PrepareStagingGeneration
→ StartMaintenanceGeneration
→ VerifyNewWorld
→ StopMinecraftAndEc2
→ CommitGenerationIncrement
→ Complete
```

### 完了条件

- backup失敗なら旧世代を動かさない。
- 新世代失敗時も旧世代とbackupが残る。
- generationを最後に確定する。
- reset後は停止状態。
- restoreとは別機能。

## 15. Phase 12 — サーバー種別拡張

実装順:

1. バニラ旧バージョン
2. Paper Package 1種類
3. 実際に遊びたいMOD構成が要求するloader 1種類
4. その他loader

各Packageで次を検証する。

- materialize
- initial start
- READY
- stop/restart
- backup/restore test
- reset
- Java version
- memory
- client接続
- 固有データpath

## 16. Phase 13以降

### 管理Web

1. Discord OAuth2
2. HTTP Admin API
3. Dashboard
4. polling
5. operation/error詳細
6. 必要性確認後WebSocket

### OP/Whitelist

- desired player settings
- UUID resolver
- 起動時ファイル同期
- 起動中即時反映
- 実反映確認

### Chat

- Package capability
- Minecraft→Discord
- join/leave/death
- `/mc say`
- 必要時Gateway Bot

### 高度機能

- restore UI
- Game upgrade
- archive
- delete
- Package Web upload

## 17. 1回のCodex作業サイズ

良い単位:

- domain enumとtestだけ
- SystemState repositoryだけ
- EC2 state取得adapterだけ
- `probe_game.py`だけ
- lock acquire/renew/releaseだけ
- State Machineの`StartEc2`まで
- Discord署名検証だけ

避ける依頼:

- 「Phase 5を全部実装」
- 「AWS構成を全部作る」
- 「MOD対応まで一気に作る」

## 18. Definition of Done

各作業は次を満たして完了とする。

- 対象要件IDを明示した。
- 正常系と重要な異常系を実装した。
- unit testがある。
- 必要なintegration確認手順がある。
- lint/type/testが成功する。
- secretを含まない。
- CDK synthが成功する。
- 変更した契約・決定・進捗を文書へ反映した。
- 実行していない確認を「確認済み」と記載していない。
