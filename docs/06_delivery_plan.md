# 06. Delivery Plan

- **文書状態:** Canonical
- **最終更新:** 2026-08-31

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
| 4 | **Completed:** Operationと排他制御 | Games/Operations/Idempotency/Locks、条件付き更新 |
| 5 | **Completed:** 安全なstart | Start Step Functions |
| 6 | **Completed:** 安全なstop | Stop Step Functions |
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
| 7 | DIS-001〜010、NFR-008、NFR-009 |
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

- **状態:** Completed（2026-08-23）

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

Phase 2b real-data migrationは、固定instance/volume/AZ/UUIDを検証する
`infrastructure/migrations/phase2_real_data_migration.sh`と
`docs/runbooks/phase2_real_data_migration.md`を正本とする。既存XFSを初期化せず、
`server.properties`一件だけを`0:993`から`993:993`へ移行する。最初のreal-world
起動後は自動rollbackせず、snapshotとattachmentを保持して停止する。

2026-08-23にsnapshot `snap-0b1d9536e9c476c0f`をrollback anchorとして保持し、
data EBSを独立targetへ移してreal-world READY・正常停止・再起動後の永続性・
再度の正常停止を確認した。終了時は両EC2 stopped、data EBSはtargetへattached、
target ingress 0、DNSなしである。Phase 1 VolumeAttachmentの一時drift解消、RCON、
public ingress、旧host退役は後続単位とする。

### 完了記録

- D-062の固定AL2023 platform、AL2023標準Docker、固定Compose、固定itzg tag/digestをtarget実機で検証した。
- existing data EBSとMinecraft 26.2 Vanilla worldを使用し、2回のREADY、restart persistence、2回のgraceful shutdown、exit 0、OOMなしを確認した。
- `server.properties`一件のownership migrationを完了し、`993:993 / 0640`、content/inode/mode維持を確認した。
- current attachmentをTarget StackへResource Importし、resource drift `IN_SYNC`、target `cdk diff` 0を確認した。
- closeout時はPhase 1 EC2とtarget EC2がstopped、migration snapshotがretained、Phase 1 stackがtermination protection有効のFrozen rollback environmentである。
- Data EBS Volume ownership、stale Phase 1 attachment、Phase 1 EC2/root/stack retirementはD-067のDeferred cleanupとする。RCON、public 25565、DNS automation、Control Plane integrationは後続Phaseへ送る。

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

- **状態:** Completed（2026-08-28）

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

最初のvertical sliceはTarget instance IDを明示inputとするEC2 adapterである。EC2が`stopped`なら到達不能なSSM/Host Runtime/Minecraft probeを実行せず、canonical `not-applicable` / `not-running` stateとUTC `observed_at`を返す。AWS API/schema failureは`unknown`へfail-closedし、DynamoDB、Lambda、running host probe、AWS deployは後続sliceとする。

次のvertical sliceはEC2が`running`の場合だけSSM managed-node状態を取得する。`Online` / `Inactive` / `ConnectionLost`をcanonical `online` / `offline` / `connection-lost`へ正規化し、API/schema failure、missing/duplicate、未知値は`unknown`へfail-closedする。SSMがonlineでない場合はHost Runtime probeへ進まない。Run Command、Host Runtime probe、DynamoDB、Lambda、AWS deployは後続sliceとする。

Host Runtime observation sliceはSSM pagination、固定read-only probe、Run Command transport、strict JSON parser、status normalizationをrepositoryで実装する。probeはmount/systemd/Docker/対象containerだけを観測し、Minecraft内部fileやprotocolを観測しない。protocol-aware observation未実装中は`ready=false`を維持する。repository/CI成功後に限り、停止済みdev Targetを一時起動してruntime-stopped状態を実測し、Targetを通常停止して終端確認する。DynamoDB、Lambda、Route 53、Minecraft起動は対象外とする。

2026-08-27にHost Runtime observation sliceのdev実測を完了した。Targetを一時起動し、SSM Online後の固定probe v1.0.1とstatus経路の両方で、期待data EBS、Docker active、Host Runtime inactive、container stopped、Minecraft not-running、protocol not-applicable、`ready=false`を確認した。直接probeとstatus経路の前後でmount identity/ownership/mode、service/container state、EBS attachment、SGに変化はなく、終了時はTargetを通常停止した。停止後statusはEC2 stopped、SSM not-applicable、Host Runtime not-runningとなり、Run Commandを送信しなかった。

最初の実機試行でprobe v1.0.0はTarget標準Python 3.9に`datetime.UTC`がないためcommand failureとなった。Targetを停止してから、Python 3.9構文/API互換を回帰検査するv1.0.1へ更新し、repository validation/CI成功後に新しい実測として再実行した。v1.0.0の失敗結果は成功扱いしない。

2026-08-28にprotocol-aware READY sliceのdev実測を完了した。固定image integrationでmc-monitor command contractを検証後、Targetだけを起動し、Minecraft未起動時のruntime not-running / protocol not-applicable / ready falseを再確認した。Phase 2 canonical Host Runtime unitから既存Minecraft 26.2 worldを起動し、container runningだがprotocol not-ready / ready falseのstartup中間状態から、localhost:25565のJava Server List Ping成功、reported version 26.2 / protocol 776、runtime ready trueへの遷移をproduction status経路で確認した。

直接観測した固定imageのmc-monitorは0.16.11で、probe v1.1.0はMOTD/player/raw responseを伝播せず必要fieldだけを正規化した。READY時はmount expected、Docker/Host Runtime/container running、health healthy、OOMKilled false、RestartCount 0、restart no、memory 2816 MiB、published portsなしだった。canonical Host Runtime stopはexit 0で、overworld/the_end/the_nether保存と`All dimensions are saved`、process/listener不在を確認した。EC2 running中のpost-stopはprotocol not-applicable / ready falseへ戻り、Target停止後statusはRun Commandを送らなかった。

2026-08-28にrepository-onlyのactive game observation sliceを完了した。`config/project.yaml`のinitial Game IDをControl Plane期待値とし、Host Runtime rendererがcontainerへ明示するGame ID/data source metadataと実`/data` bindをread-only probe v1.2.0で照合する。期待/観測一致、active game mismatch/unknown、runtime bind mismatchをstatusの独立discrepancyとして導出し、protocol runtime READYをgame mismatchでfalseへ書き換えない。

Minecraft running observation、protocol-aware status、runtime READY true、running→not-ready→ready→stopped遷移、protocol failureではREADYにしない契約、active game observation、active game discrepancyをdev実測まで完了した。加えてpublic/private IPv4、Route 53、endpoint discrepancy、Reconcile domain service、current SystemState repository、DynamoDB/Lambda/独立Control Plane stackをrepositoryで実装・検証した。repository実装時点ではAWS deploy/integrationを未完了として分離し、次のcloseout実測後にだけPhase 3を完了とした。

2026-08-28にcredential付きdiffを3 stack別々に実施した。Phase 1はAMI parameter再解決によるEC2 replacement、履歴上のUserData、移行済み旧VolumeAttachmentの既知Frozen差分があるためdeployせず、Targetは差分0だった。Control PlaneはDynamoDB、LogGroup、IAM Role/Policy、Lambdaの新規resourceだけで、read-mostly IAMと特定SystemState table writeに限定されていたため、`WishicraftControlPlaneStack-dev`だけをdeployして`CREATE_COMPLETE`を確認した。

stopped Targetへcanonical Reconcile inputを2回実行した。両方でEC2 stopped、public IPv4 absent、DNS absent、SSM/protocol/active game not-applicable、Host Runtime not-running、runtime ready false、discrepancy/errorなし、health HEALTHYとなった。`observed_at`は`2026-08-28T10:17:07.423850Z`から`2026-08-28T10:17:51.361257Z`へ前進し、DynamoDBは`system_id=wishicraft-main`のcurrent item一件だけを更新した。前後のTarget向けSSM command countは43、latest metadataも同一で、このReconcileによるSendCommandは0件だった。

古いobserved_atの実AWS書込み試験は、production Lambdaがsynthetic state/timeを受け付けず、schema外AWS CLI writeも行わない境界を優先して実施しなかった。repository adapterのolder/equal conditional rejection testと、previous READYからfresh UNKNOWN/ready falseへ更新するtestをcloseout時に再実行して成功した。Lambda logはruntimeのINIT/START/END/REPORTだけで、credential、secret、environment dump、probe/raw Minecraft contentを含まなかった。

終了時はPhase 1/Target EC2 stopped、data EBSはTargetへattachedかつDeleteOnTermination false、snapshot completed、Target ingress 0、DNS absent、Phase 1/Target stackの更新時刻不変である。STA-001〜006のPhase 3 status/reconcile成果物と実測条件を満たしたためPhase 3を完了とする。Operation/Lock、start/stop workflow、Discord、periodic/event-driven reconcileは後続Phaseの範囲である。

Phase 3 closeout後のrepository-only consistency fixとして、probe v1.3.0で既存mc-monitor responseのonline player countだけを追加した。0とunknown/not-applicableを区別し、sample/name/UUID/MOTD/raw JSONを伝播せず、player countをruntime READY条件にしない。AWS/Target再実測を伴わないcontract/test補完であり、Phase 3はCompletedのままとする。

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

**状態:** Completed（2026-08-29 repository / dev AWS integration完了）

D-074でLock logical owner / lease possession、Desired revision CAS、stale recoveryをAcceptedとした。repository実装はGame条件付き登録、4 table construct、versioned admission Lambda、idempotent admission transaction、STATUS short pathと専用terminal更新、lease renew/release/ownership check、Operation step/terminal更新、fresh Reconcileを要求する明示stale recovery、Desired CASを含む。

2026-08-29のdev integrationでは、Phase 1の既知historical diffだけを確認してdeployせず、Target diff 0を確認し、`WishicraftControlPlaneStack-dev`だけを更新した。Games/Operations/Idempotency/LocksはACTIVE、Admission LambdaはActive、既存Reconcile/SystemStateは保持された。初期`game-vanilla-main`を条件付き登録し、同一・異なるpayloadの再登録はいずれも既存itemを上書きせず拒否された。

Admissionは同一idempotency key / 同一payloadで既存Operationを返し、異なるpayloadと競合Lockでは新規Operation/Idempotency/current ownerを残さず拒否した。Lock中のSTATUSはLock/Current Operationを変更せず受付・terminal化できた。owner operation IDとlease ID一致・未期限切れを実AWSで確認し、wrong leaseのverify/renew/release拒否、正しいrenewとowned release、OperationのPENDING→RUNNING→SUCCEEDEDおよびterminal後更新拒否を確認した。

Desired CASはrevision 0→1だけ成功し、古いrevisionを拒否し、Observed `observed_at`を変更しなかった。synthetic stale Operationは通常admissionをblockし、fresh stopped Reconcile後だけTIMED_OUT化・owned Lock削除・`current_operation_id`解除を一transactionで完了し、その後のadmissionが成功した。integration終了時は4件の識別可能なOperation/Idempotency履歴を保持し、Lock 0件、Current Operationなし、SystemStateはSTOPPED / desired revision 1 / fresh stopped observationである。TTLはDeferredのためraw deleteやTTL追加を行っていない。

初回AdmissionはIAMにtransaction内部の`PutItem`等が不足してAccessDeniedとなり、transaction itemは0件だった。Admission roleへ対象5 table限定の`ConditionCheckItem`、`GetItem`、`PutItem`、`TransactWriteItems`、`UpdateItem`だけを追加して再検証した。EC2/SSM/Route 53/EBS/secret権限は追加していない。integration期間のTarget向けSSM Commandは0件で、両EC2 stopped、data EBS attachment、snapshot、Target ingress 0、DNS absent、Phase 1/Target stackは不変だった。

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
- 期限切れロックを通常admissionが自動takeoverせず、fresh Reconcileを伴う明示recoveryまで競合をblockする。
- 他operationのロックを解放できない。
- 同一Operationの古いexecutorは異なる`lease_id`のleaseをrenew、release、または副作用用に使用できない。
- TTL削除を待たずに正しく判断できる。
- 初回GameがGames tableへ登録されている。

## 8. Phase 5 — 安全なstart workflow

- **状態:** Completed（2026-08-29 repository / dev AWS integration完了）

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

### Repository-only実装記録

Operation admissionが新規STARTを作成した場合だけ`operation_id`をStandard execution nameとしてworkflowを開始し、duplicate idempotency retryでは新しいexecutionを作らない。workflowはfresh Reconcile、Desired RUNNING CAS、tagで一意解決したTargetのEC2 start、SSM online待機、固定Host Runtime `operation-v1 START`、protocol-aware READY、active Game一致、限定Route 53 UPSERT、Change ID `INSYNC`、fresh endpoint一致を順に確認する。

待機loopは120秒以下で同一`operation_id` / `lease_id` / 未期限切れ条件によるrenewを行い、EC2 start、SSM command、DNS write、terminal completion直前にcurrent lease possessionを検証する。同一Gameが既にREADYならEC2/Host Runtime side effectをskipしてendpoint収束へ進む。`SetDesiredRunning`後のfailureはDesiredを戻さず、fresh Reconcile後にowned failure completionを試みる。lock lossまたはcleanup observation failureでは他owner stateを変更せずexecutionをfailさせ、通常admissionによるexpired takeoverは行わない。

Host Runtime commandは引数がexactly `START`のversioned wrapperだけを許可し、systemdの固定unitへ変換する。instance ID、shell、path、Minecraft commandをAPI inputにしない。STARTはRCONを必要とせず、RCON有効化、secret取得、管理port publishはこのsliceに含めない。

初回AWS integrationではTarget SGのMinecraft TCP 25565 in-place update、Control Plane stack、固定`operation-v1`配置、AdmissionからのSTARTを適用した。EC2、SSM、Host Runtime、container、protocol READYまでは成功したが、installed Composeがactive Game labels導入前のapproved predecessorだったため`active-game-unknown`でDNS write前にFAILEDとなった。利用上限中のoperator `StopInstances`ではmount unmountがExecStopと競合して`FAIL:MOUNT_SOURCE`となり、この停止のgraceful shutdownは証明できなかった。

D-076 recoveryでは旧Compose/unitのSHA-256をapproved predecessorとして照合し、固定secret-free artifactへatomic upgradeした。適用後はCompose `c92fbbfb8c955e249b39edbd2b2063e0cfa05214d8242bdeb302dd1d996b0770`（root:root/0600）、unit `6de3ea3ecfa68537f804872b467400e1e0316ed6627d50e5ed96fa80af2c1608`（root:root/0644）で、systemdの実生成依存に`Requires/After=srv-minecraft.mount`、boot時Host Runtime/container非起動を確認した。検証bootではprotocol READY、expected/observed active Game `game-vanilla-main`を確認した。controlled systemd poweroffではHost Runtime stop完了 `10:41:51.680530Z`の後にmount unmount開始 `10:41:51.712191Z`となり、Minecraft stop、全dimension保存、runner `Done`、container exit 0、OOM false、restart 0を確認した。

その後、Desired RUNNING revision 2 / actual stopped / DNS absentから新しいAdmissionでconvergence STARTを開始し、revisionを増やさずEC2、SSM、typed Host Runtime START、protocol READY、active Game一致、public IPv4 `52.68.217.91`、Route 53 UPSERT/INSYNC、endpoint一致、HEALTHY、Operation SUCCEEDED、Lock/Current Operation解放まで完了した。executionは`2026-08-29T10:45:05.131Z`から`10:49:08.190Z`まで243.059秒だった。renew taskを5回観測し、900秒leaseには十分なmarginがあったが、Phase 6 STOPの実測前なので900秒/120秒はProvisionalを維持する。同一idempotency key/payloadのretryは同じOperationを`created=false`で返し、新しいexecution、Lock、EC2 boot、Host Runtime START、DNS writeを作らなかった。closeout時はDesired/Actual/ObservedがRUNNING、runtime READY、active Game一致、DNSがcurrent public IPv4と一致しHEALTHYである。SSH、RCON、管理port ingress、secret、Phase 1、Data EBS lifecycleは変更していない。

## 9. Phase 6 — 安全なstop workflow

- **状態:** Completed（2026-08-30）

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

### Repository / integration status（2026-08-29）

STOP専用Standard State Machine、Task Lambda、Admission接続、Desired STOPPED convergence、lease renew/side-effect前verify、fixed Host Runtime STOP、explicit RCON save、graceful stop確認、EC2 stop、DNS DELETE/INSYNC、fresh Reconcile、failure classificationをrepositoryへ実装した。Actual stopped + Desired RUNNING/STOPPED、stale DNSでもEC2を再起動せず収束する。

RCON secretはstage固定Parameter Store SecureString名だけをGit管理し、Target Hostの`/run/wishicraft`へ取得する。password fileに加え、itzgが生成するrcon-cli configもephemeral bindとしてData EBSへのsecret永続化を防ぐ。Phase 5 predecessor checksumからの固定artifact atomic replacementを用意した。

operator停止後の `Desired RUNNING` revision 2 / Actual EC2 stopped / stale DNSという不整合から、fresh ReconcileでStopped observationとDNS discrepancyを保存した後、Control Plane stackだけへPhase 6 STOP resourcesをdeployした。canonical AdmissionからSTOPを実行し、Operation `op-c944e14c-88ee-456f-a221-617d35aa4838`はActual stopped short-circuitを選択して、runtime、RCON、SSM、EC2 start/stopを呼ばず、DesiredをSTOPPED revision 3へCASした。lease ownershipをDNS side effect直前に更新・検証し、stale A recordをchange `/change/C08095151JYYWO3IEW862`でDELETE、Route 53 INSYNC後のfresh ReconcileでEC2 stopped、SSM/protocol not-applicable、Host Runtime not-running、public IPv4/DNS absent、discrepancyなし、HEALTHYを確認して42.316秒でSUCCEEDEDとなった。Lock/current operationはowned terminal transactionで解放された。

同一idempotency key/payloadの再送は同じOperationを`created=false`で返し、STOP executionは1件のまま、Desired revision、DNS、Lock、EC2/SSM side effectを変更しなかった。実行前後のTarget向けSSM command countは71、最新command IDも同一で、CloudTrail上のTarget StartInstances/StopInstancesにもintegration時間帯の新規eventはない。これらはstopped-state convergenceの実AWS証跡であり、repository testsとは区別する。READYからのexplicit save / graceful runtime stop / EC2 stopを含む通常STOP pathは未実証である。

Target secret-read IAM、Phase 6 Host Runtime artifact、RCON SecureString、secret injection、実RCON commandは未適用である。次のAWS writeはこれらの初production適用とSTART→STOP end-to-end検証に対する別の明示承認境界とする。

### Running STOP recovery contract review（2026-08-30）

RCON/Target artifact初適用後のrunning STOPは3回ともexplicit save前にfail closedした。順にsystemd外STOPのpreflight env不足、readonly `COMPOSE_FILE` collision、live Docker nested-bind backing placeholder削除によるRCON authentication lossであり、EC2 stopとDNS deleteへは進んでいない。production topology fixture不足を共通原因としてD-078をAcceptedとし、password ROと生成config exact 2件RWを分離した。filesystem preflightをread-only化し、strict zero-size backing placeholderとDocker inspect identityをknown managed artifact contractへ追加した。repository修正・fixture・testsはproduction実測と区別し、Phase 6はrunning STOP成功まで未完了である。第四hot-patch、STOP retry、AWS writeは別の明示承認境界とする。

D-078の最初のinactive-only full artifact適用とcanonical STARTは成功したが、STOP admission前のlive validationでDocker label用Go templateにshell single-quote内でも不要なbackslashが残り、template parse errorでpreflightがfail closedした。save/STOP/EC2/DNS side effectはなく、Targetはverified maintenance systemd stopで再びHost Runtime inactive、container exit 0、OOM false、restart 0へ戻した。production wrapper bugのためrepository修正・CI後の再適用を新しい承認境界とし、running-state replacementは行わない。

修正版preflight `e2343290fc2aa9113de7630e656df607d59eae872e4fdb343fb660d1b2b5ca33`をapproved predecessorからinactive-only atomic upgradeした。Desired RUNNING revision 6 / Actual inactiveからcanonical START `op-691da46e-6b04-40d0-a635-a8c8335253cf`を実行し、revisionを増やさず243.499秒でREADY、active Game一致、player 0、DNS一致、HEALTHYへ収束した。production live gateは`PASS:RAW_DEVICE_PREFLIGHT`、`PASS:MOUNT_GUARD`、`PASS:D078_DOCKER_NESTED_BIND`、`PASS:RCON_AUTHENTICATION`を順に記録した。password bindはRO、生成config exact 2件はRW、Data EBS backing placeholderはroot:root 0644、size 0、nlink 1、Host sourceはruntime 993:993、0400/0600だった。

canonical STOP `op-cbff4fbd-dbfe-4d32-a4f6-62ea2fa84d57`はDesired STOPPED revision 7へCASし、fixed SSM command `fdab7824-e5c3-4106-b4f5-15af84dc4375`が4.787秒、exit 0でexplicit `save-all flush`とgraceful systemd stopを完了した。Host stop command完了 `02:11:05.757Z`、runtime-stopped Reconcile後、EC2 Stop task開始 `02:11:18.797Z`の順で、running Minecraftへのdirect StopInstancesはない。同一Compose/systemd artifactの直前maintenance stopではcontainer exit 0、OOMKilled false、RestartCount 0を実測しており、product STOPでも同じgraceful path、process/listener消滅、HostStopCompleteを確認した。EC2 stopped後にDNS DELETE、Route 53 INSYNC、fresh Reconcileを行い、93.353秒でSUCCEEDEDした。最終状態はDesired STOPPED revision 7、EC2 stopped、SSM/protocol not-applicable、Host Runtime not-running、public IPv4/DNS absent、HEALTHY、discrepancyなし、Lock/current operationなしである。同一idempotency key retryはsame Operation、`created=false`、execution 1件、side effectなしだった。

STOPは6回renewし、最長poll gapは約30秒、900秒leaseに少なくとも約870秒のrenew後marginがあった。Phase 5 START 243.059秒/5回renew、今回START 243.499秒、STOP 93.353秒/6回renewの実測から、lease 900秒・renew 120秒をAcceptedとする。Phase 1はstopped/Frozen、Data EBSはTarget attached・DeleteOnTermination false、migration snapshotはcompleted/retained、SGはpublic gameplay TCP 25565だけを維持した。

## 10. Phase 7 — Discord MVP

- **状態:** In Progress（Phase 7A〜7F repository implementation completed、Phase 7G next）

### 目的

一般利用者がDiscordだけで固定バニラGameを利用できるようにする。

Discordは新しいMinecraft制御系ではなく、既存Operation Admission、START/STOP、STATUS/Reconcileへの認証・認可済みexternal adapterとuser-facing projectionである。Discord層からDesired、Lock、Current Operation、EC2、SSM、RCON、DNSを直接操作しない。

### Phase 7A — Contract / Decision freeze

- DIS-001〜010と既存Operation/Reconcile contractの接続を確定する。
- Guild、operation channel、player/admin role認可を固定する。
- STATUSの非Lock・非同期fresh Reconcile contractを固定する。
- Operation単位message idempotency、delivery failure分離、Bot Token IAM、command registration ownershipをDecision化する。
- source、infrastructure、AWS、Discord external configurationは変更しない。

### Phase 7B — Discord ingress / signature / authorization

- **状態:** Completed（repository-only、AWS/Discord未適用）
- API Gateway HTTP APIとCommand Lambdaを実装する。
- raw request bodyに対するDiscord signature/timestamp verificationを最初に行う。
- configured dev Guild、operation channel、player role OR admin roleをapplication側で検証する。
- PINGとDeferred Responseを期限内に返し、internal detailを公開しない。
- Bot TokenはCommand Lambdaへ付与しない。
- `config/discord/commands.v1.json`をschema正本とし、PyNaClのhash-locked Lambda bundle、HTTP API v2 raw/base64 body復元、signature-first verification、strict PING/command parseを実装した。
- valid commandを含む全経路でOperation Admission、Reconcile、State Machine、DynamoDB/AWS lifecycle mutationは0である。Phase 7B responseはOperationを受付けたと誤認させないephemeral messageであり、Phase 7CでSTATUS Admissionとdeferred responseへ接続する。
- CDKはPhase 7 contextでHTTP API `POST /discord/interactions`と3秒Command Lambdaを生成する。Lambda roleはCloudWatch LogsとAPI Gateway invoke permission以外のapplication policyを持たず、Bot Token、DynamoDB、Step Functions、EC2、SSM、Route 53権限を持たない。

### Phase 7C — `/mc status`

- **状態:** Completed（repository-only、AWS/Discord未適用）
- Discord Interaction identityを使ってSTATUSを既存Admissionへadmitする。
- Lockと`current_operation_id`を使用せず、fresh Reconcileを非同期実行する。
- 小さいStandard Step Functionsまたはasync Lambdaは、既存Reconcileのtimeout、retry、IAM、追跡性を比較してこのsliceで決定する。
- fresh Observed/Healthの利用者向けprojectionを返す。
- 現行Reconcileがsingle Lambda invocationで完結しdurable waitを持たないため、D-085のOperations Stream駆動async Lambdaを採用した。Admission commitがdispatch sourceとなり、同一Interactionのduplicateは同じOperationを返して新規executor dispatchを作らない。
- Command LambdaはSTATUSだけをAdmissionへ接続してephemeral deferred responseを返す。START/STOPは未受付のまま、executorは既存ReconcileとSTATUS専用unlocked terminalizationを再利用し、安全なprojectionをOperation resultへ保存する。
- Streamはbatch size 1、STATUS INSERT filter、bounded retry、暗号化DLQを持つ。Command LambdaはAdmission Lambda invokeだけ、executorはOperations Get/UpdateとReconcile Lambda invokeだけを持ち、Bot Token、START/STOP State Machine、EC2/SSM/Route 53 direct権限を持たない。
- Phase 7D前なのでprojectionをDiscord APIへ送信せず、実command registration/deploy/E2Eを行わない。

### Phase 7D — Discord message transport

- **状態:** Completed（repository-only、AWS/Discord未適用）
- Bot Tokenを読む独立Message componentを実装する。
- 1 Operationにつき原則1公開messageを条件付きで関連付け、retryでも増殖させず更新する。
- Discord delivery failureをControl Plane Operation resultから分離して観測する。
- Interaction Tokenを永続化せず、secretとinternal error detailをlog/messageへ出さない。
- D-086によりInteraction original response方式は採用せず、通常Bot messageへOperation由来25文字nonceと`enforce_nonce=true`を付ける。create成功・message ID保存前failureは同じStream event/nonceで既存message IDを回収し、30秒の曖昧結果回復窓を越えた場合はduplicate createせずdeliveryだけをfail closedする。
- STATUS terminal MODIFYをOperations Streamのdurable triggerとし、Message Lambdaがoptional delivery metadataを条件付き更新する。retryable metadata transitionをSQS delayへ接続し、429の`retry_after`を尊重する。attemptは最大3回で暗号化DLQへ隔離し、401/403/404と不正responseを分類する。
- Message Lambdaだけがdev Bot Token SecureString一件を`ssm:GetParameter`できる。Command Lambda/STATUS executorはBot Tokenなしを維持し、Message LambdaはEC2、SSM Run Command、Route 53、Step Functions、Desired/Lock mutation権限を持たない。
- Phase 7C safe projectionだけをrenderし、delivery failureはOperation terminal resultへ逆流させない。START/STOPは引き続きAdmission 0であり、AWS deploy、Discord registration/message送信は実施しない。
- dev Bot Token SecureStringはmetadata-only確認で不存在だった。repository completionとは分離し、Phase 7D infrastructure deployまたはPhase 7G E2E前の明示operator secret作成をblockerとする。

### Phase 7E — `/mc start`

- **状態:** Completed（repository-only、AWS/Discord未適用）
- signature/authorization後、既存Admission Lambdaへ`discord:<interaction_id>`でSTARTをadmitし、既存START State Machineだけを利用する。Command LambdaはDesired/Lock/EC2/SSM/DNS/State Machineを直接操作しない。
- D-087の`progress_revision`をAdmission 0から公開step/terminal transitionごとに単調増加させ、Operations Stream INSERT/MODIFYをdurable triggerとする。初回はD-086 nonceで一messageを作り、後続は同じ`message_id`をeditする。
- Stream event revisionとconsistent current Operation revisionを比較してstale eventをno-opにする。delivery metadataだけのMODIFYはrevision不変なので自己再triggerしない。古いrevisionのdelivery FAILED後も新しいrevisionはbounded deliveryを開始できる。
- START Admission成功後は即時ephemeral ACKを返し、長時間progress/finalは通常Bot messageへ分離する。3秒initial response latency、Bot Token作成、deploy、real Discord E2EはPhase 7G release gateで実測する。
- duplicate Interactionは既存payload-aware Admissionから同じOperation/executionへ戻り、新規Operation/Lock/messageを作らない。STOPは未接続のままである。

### Phase 7F — `/mc stop`

- **状態:** Completed（repository-only、AWS/Discord未適用）
- signature/authorization後、実証済みSTOP AdmissionとState Machineを利用する。
- explicit save、graceful stop、EC2/DNS/fresh Reconcileの判定をDiscord層へ複製しない。
- duplicate Interactionでsave/stop/messageを再実行しない。
- `discord:<interaction_id>`をshared Admissionへ渡し、duplicateは同じOperation/lease/executionへ収束する。Command LambdaはAdmission Lambda invoke以外のControl Plane権限を持たず、STOP State Machineを直接起動しない。
- D-087の単調な`progress_revision`とD-086の通常Bot message identityをSTOPにも再利用する。`DESIRED_STOPPED`、Host Runtime停止、EC2停止、endpoint cleanup、terminal transitionを同一messageへ投影し、古いeventとdelivery metadata-only eventをno-opにする。
- Discord delivery failureはD-082どおりSTOP Operation、Desired、Lock、save/graceful stop、EC2/DNS/Reconcileへ逆流しない。既存Phase 6 STOP sourceの安全順序・fail-closed error classification・lease/cleanup contractは変更しない。
- Bot Token作成、AWS deploy、Discord command registration、real status/start/stop E2EはPhase 7G release gateに残す。

### Phase 7G — real Discord + AWS E2E / release gate

- **状態:** In Progress（Phase 7G-1〜7G-2 completed、Phase 7G-3 real E2E前）
- Phase 7G-1では正本dev account/regionとPhase 6 safe stateをread-onlyで再確認し、固定Parameter `/wishicraft/dev/secret/discord-bot-token`をoperator非echo入力からAWS managed keyの`SecureString` Version 1として新規作成した。値・fragmentはrepository、shell引数、environment、transcript、logへ出さず、作成後はmetadataだけを確認した。
- Bot Tokenをprocess memory内だけで使用したDiscord read-only照合ではApplication ID/Public Key、Guild、operation/admin channel、player/admin roleがdev設定と一致し、Botはoperation channelで`VIEW_CHANNEL`、`SEND_MESSAGES`、`EMBED_LINKS`を持つ。HTTP InteractionsとREST messageだけを使うためGateway接続・privileged intentsは不要である。
- credential-backed template diffはTarget差分0、Control PlaneはPhase 7のHTTP API/Lambda/Operations Stream/SQS/DLQ/IAM追加と既存Lambda code更新で、DynamoDB/EC2/EBS/SG/DNS replacementまたは拡張を含まない。Phase 1には既知のhistorical UserData差分とreplacement可能性があるためFrozen/deploy禁止を維持する。Phase 7G-2ではControl Plane stackだけを明示deployし、Discord endpoint設定とcommand registrationはさらに別の明示operator mutationとして扱う。
- Phase 7G-2では`WishicraftControlPlaneStack-dev`だけをexclusive deployし、CloudFormation `UPDATE_COMPLETE`、HTTP API、Command/STATUS/Message Lambda、Operations Stream、暗号化SQS/DLQ、最小IAMを実環境で確認した。Stream mappingは`LATEST`とtype/source filterを持ち、既存19 Operationのreplay、Message Lambda invocation、意図しないDiscord messageはいずれも0だった。unsigned requestは401でfail closedし、Operation/Lock/Minecraft stateを変更しなかった。
- deploy output由来のexact URLをDiscord Interaction Endpointへ設定し、signed PING/PONGをverification round-trip 2.578秒、Lambda処理1.88〜2.13msで確認した。PINGはOperationを作らず、real commandの3秒境界の証拠には数えない。
- Git正本の`/mc` schemaをbulk overwriteでなくGuild POST upsertによりdev Guildだけへ登録した。登録前Guild/global commandは0件、登録後は`mc`一件と`status/start/stop`だけで、global commandは0件だった。Discord仕様で`integration_types`/`contexts`はglobal scope専用のためGuild正本から除き、read-back exact matchを固定する。CDK deployの暗黙side effectにしない。
- real Discordからstatus、start、stop、authorization、duplicate、delivery failure分離を確認する。
- AWS Budgets、log retention、workflow/EC2/divergence/Lock/Lambda alarmと手動snapshot runbookをrelease gateとして確認する。
- Phase 8 backup完成までは試験運用とする。

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
- 同一Operationの公開messageがretryで増殖しない。
- Command LambdaはBot Tokenを読まず、Message componentだけが固定SecureStringを読める。
- command registrationがGit正本と明示operator actionに分離されている。

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

### Phase 3 Control Plane status integration slice

repository実装としてpublic/private IPv4、Route 53 A record、endpoint discrepancy、Reconcile domain service、current SystemState conditional repository、on-demand DynamoDB、薄いReconcile Lambda、独立Control Plane stackを追加した。stopped TargetではSSM/Run Command/Host Runtimeを短絡し、public IPv4 absent + DNS absentを正常化する。focused/full test、Ruff、mypy、shell syntaxとPhase 1/Target/Control Planeの個別synthでrepository validationを行う。

repository validationだけではAWS完了としない。上記のcredential付きdiff、Control Plane-only deploy、stopped Target observationのcurrent SystemState保存を実測してPhase 3をcloseoutした。periodic reconcile、start/stop workflow、Discord/API、operation admission/lock、backupは後続Phaseのままとする。
