# Wishicraft Phase 0 完了から Phase 1 基盤までの作業記録

> 記録対象: このセッションの開始（2026-07-29）から、2026-08-15 の再開直前まで。  
> 作成日: 2026-08-15  
> 目的: 後から設計判断、実装順、検証境界を学び直せるようにする。  
> 秘密情報: RCON password、AWS credential、SSO role、ローカル profile の具体値は記載しない。公開設定の具体的 ID も必要最小限にとどめる。

## 1. 全体像

この期間は、空のリポジトリを Phase 0 の「設定を安全に読める CDK プロジェクト」へ整え、その後 Phase 1 の手動 Minecraft EC2 基盤を段階的に実装・検証した期間である。

重要な進め方は次のとおりだった。

1. 未確定値は `null` のまま保存し、schema validation と「この操作に必要な値」の validation を分離した。
2. Phase 0 は AWS account/profile に依存しない environment-agnostic synth を成立させた。
3. Phase 1 ではネットワーク、EC2 role、EC2、data EBS、mount、Java、固定版 Minecraft artifact、RCON 配布/firewall、手動 DNS 操作を小さな commit に分割した。
4. 秘密値を CDK、CloudFormation、Git、fixture、ログへ載せず、EC2 role が実行時に対象 SSM SecureString を取得する設計にした。
5. AWS の実操作や host 上のセキュリティ変更は、明示承認と runbook を前提にし、ローカルの test-only harness と本番操作を分離した。

## 2. 時系列

### 2026-07-29: Phase 0 の計画と実装

#### 利用者の依頼・質問

- 最初はリポジトリ全体を読み、実装はせずに Phase 0 の計画だけを作るよう依頼された。
- 最低限読むべき設計文書、設定、Phase 0 が明示された。
- Phase 0 を 3〜5 個程度の小さな作業単位に分け、目的、要件 ID、変更予定、新規ファイル、テスト、完了条件、依存関係を示すよう求められた。
- 文書や設定の矛盾、欠落、`null`、`TO_BE_CONFIRMED` は推測せず報告するよう求められた。

#### Codex の判断と理由

- Phase 0 は「クラウドを作る段階」ではなく、設定・CDK・品質ゲートを作る段階として切り分けた。
- dev の初期 synth に account ID、Availability Zone、Minecraft port/version、Route 53 Hosted Zone ID を要求すると、未確定設定だけで開発を開始できなくなる。そのため、構造を読む schema validation と、各 Phase/処理に必要な required validation を分離する方針にした。
- prod は placeholder を読むことは許可し、prod synth では `null` をパス付きで列挙して停止する安全ゲートにした。これは「現在 `null` の全項目が永久に必須」という意味にはしない。

#### 実装・commit

`6a9b8c0 feat: implement Phase 0 project foundation`

- Python 3.12 / uv / Ruff / mypy / pytest / CDK v2 の土台を追加。
- `src/wishicraft/config.py` に YAML 読み込み、schema validation、Phase/action ごとの required validation を追加。
- 空の `MinecraftStack` と CDK entry point を追加。
- GitHub Actions CI、`.gitignore`、unit tests、README を追加。
- `config/project.yaml`、dev/prod stage YAML、`config/secrets.example.yaml` を正本として扱う構造を確立。

主な変更ファイル:

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`
- `cdk.json`、`package.json`、`pyproject.toml`、`uv.lock`
- `infrastructure/app.py`、`infrastructure/stacks/minecraft_stack.py`
- `src/wishicraft/config.py`、`src/wishicraft/logging.py`、`src/wishicraft/naming.py`
- `tests/unit/test_config.py`、`test_logging.py`、`test_naming.py`、`test_stack.py`

#### 検証

Phase 0 完了記録で確認された結果:

- pytest: 11 件成功
- Ruff: 成功
- mypy: 成功
- dev の environment-agnostic CDK synth: 成功
- prod synth: `null` の不足パスを列挙して意図的に失敗
- GitHub Actions CI run #1: 成功

この段階では deploy、`cdk diff`、AWS credential/profile 設定、Phase 1 実装は行わなかった。

### 2026-07-29: Phase 0 の完了記録と Java runtime 設定の更新

#### 利用者の依頼

- Phase 0 の実装・検証を確認し、Git status/diff の最終確認、秘密値や生成物の非追跡確認、commit/push、GitHub Actions 確認を依頼した。
- 続いて、Phase 0 完了状態が文書へ反映されるよう更新し、`docs: record Phase 0 completion` で commit するよう依頼した。
- dev 設定の Java runtime を Corretto 25 headless、Minecraft version を 26.2 に変更したことを共有し、Java 21 前提の文書修正を依頼した。

#### 実装・commit

`b48671c docs: record Phase 0 completion`

- README、Delivery Plan、Decision、初期設定文書に Phase 0 完了、CI、未実行の AWS 操作を記録。

`e57ec22 chore: configure dev runtime`

- `config/stages/dev.yaml` と関連文書の runtime 前提を Java 25 / Minecraft 26.2 に揃えた。

技術的な要点:

- Minecraft version と Java major version は独立に見えても runtime 互換性がある。version を上げる場合は、server artifact、OS package、起動 script、runbook、文書のすべてを横断して確認する必要がある。

### 2026-07-29: ドメイン、RCON Parameter、Phase 1 準備

#### 利用者の依頼・確定事項

- `wishicraft.net` を取得済みであること、dev の Hosted Zone ID が設定済みであることを共有した。prod YAML は引き続き `null` のままとした。
- `mc-dev.wishicraft.net` の A レコードは事前作成しない。Phase 1 で、EC2 起動中は現在の public IPv4 へ更新し、停止後は削除する方針を確定した。
- dev 用 RCON password は Parameter Store SecureString に登録済みと共有された。ただし Codex は値を表示・取得しないよう求められた。
- Phase 1 に進む前の残作業を確認し、AWS CLI profile、接続 account/region、STS 照合、RCON 実行時配布、固定版 server.jar の checksum 検証、EULA 承認 gate を明確にした。

ここで確定した安全条件:

- AWS CLI/CDK の手動操作ではローカル profile を明示する。ただし profile 名は CDK application code や stage 設定の必須値へハードコードしない。
- deploy 前に STS caller account と stage 設定の account を照合し、不一致なら停止する。
- EC2 role は対象の SecureString にだけ read 権限を持ち、復号済み password は stdout/log/CloudFormation/Git に出さない。
- RCON のインターネット向け Security Group ingress は作らない。
- Minecraft 26.2 は公式配布元の固定 URL と checksum を stage 設定に固定し、`latest` は使わない。
- EULA の明示確認前は server.jar download、`eula=true`、初回起動を行わない。

#### Codex の判断と理由

- 「設定を読める」ことと「deploy できる」ことを分けた。dev の設定には確定値を追加したが、Phase 0 の synth 要件は後方互換で軽いままとした。
- URL と checksum は公開情報なので設定に置ける。一方、RCON password は公開設定へ入れず、Parameter 名だけを `config/secrets.example.yaml` に置く。
- checksum は配布物改ざん、URL の可変化、意図しない version 追従を検出するために必要である。SHA-1 は公式 metadata との照合、SHA-256 は取得物のより強いローカル検証に使う構造へ発展した。

#### 実装・commit

`42ec858 feat: prepare Phase 1 dev configuration and validation`

主な変更:

- dev stage に確定済みの AWS/compute/network/Route 53 設定と固定 artifact URL/SHA-1 を追加。
- `minecraft_distribution` を optional mapping として schema に追加し、Phase 1 synth/deploy に必要な値だけを `REQUIRED_PATHS` へ追加。
- `infrastructure/app.py` に `phase` と `validation_action` context を追加。profile はアプリコードに保存しない。
- RCON の runtime secret 配布、artifact 検証、EULA 承認 gate を architecture/security/Decision/runbook に記録。
- `docs/runbooks/phase1_dev_manual_validation.md` を新規追加。
- Phase 0 の未完了を示す古い表現を README で最小限修正。

主な変更ファイル:

- `config/stages/dev.yaml`
- `src/wishicraft/config.py`
- `infrastructure/app.py`
- `tests/unit/test_config.py`、`tests/unit/test_stack.py`
- `docs/03_architecture.md`
- `docs/05_data_and_interface_contracts.md`
- `docs/06_delivery_plan.md`
- `docs/07_operations_security_and_cost.md`
- `docs/09_decisions_and_backlog.md`
- `docs/11_external_constraints_and_references.md`
- `docs/12_initial_configuration.md`
- `docs/runbooks/phase1_dev_manual_validation.md`

#### 重要コマンドと目的

次はこの時点で実行・確認された代表例である。環境 activate は実行文脈を整えるだけで、password や credential を表示しない。

```sh
source /Users/nishiyamaharuya/Documents/coding/wishicraft-server/.venv/bin/activate
```

```sh
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src infrastructure tests
.venv/bin/cdk synth --context stage=dev --context phase=1
git diff --check
```

目的は、unit test、静的解析、format、型、Phase 1 dev の template synth、patch の whitespace error を独立に確認することだった。

追跡対象の安全確認には、概ね次の意図の Git command を使った。

```sh
git ls-files
git check-ignore -v .venv cdk.out .env
git status --short
git diff --check
```

確認内容:

- `.venv`、`cdk.out`、`node_modules`、`.env`、local config、実 secret、`server.jar` は Git 追跡対象に含まれない。
- RCON password は一度も取得・表示せず、Parameter 名だけを扱う。

#### 検証結果

- pytest: `16 passed`
- Ruff check: 成功
- Ruff format check: 成功（29 files）
- mypy: 成功（14 source files）
- Phase 1 dev synth: 成功。empty CDKMetadata stack の synth であり AWS への接続はしない。
- `git diff --check`: 成功
- push 後 GitHub Actions: 成功

commit/push の最終結果:

```text
42ec8584f66f76357af65cb6739071535238151b
feat: prepare Phase 1 dev configuration and validation
```

ブランチは `main`、push 先は `origin/main`。Phase 0 の `6a9b8c0` は amend しなかった。

GitHub Actions の状態確認には GitHub API を使った。最初の応答はエラーではなく、正常な実行中状態だった。

```json
{"id":30445375425,"status":"in_progress","conclusion":null,"html_url":"https://github.com/eash-misoni/wishicraft-server/actions/runs/30445375425"}
```

poll 後の最終結果:

```json
{"id":30445375425,"status":"completed","conclusion":"success","html_url":"https://github.com/eash-misoni/wishicraft-server/actions/runs/30445375425"}
```

最終 status:

```text
## main...origin/main
42ec858 feat: prepare Phase 1 dev configuration and validation
```

### 2026-07-29: Phase 1 の AWS 構成を小さく分割して実装

Phase 1 を一括で実装せず、construct ごとに commit を分けた。これは CDK template の差分と IAM/network の影響を局所化し、失敗時の原因追跡を容易にするためである。

| commit | 作業 | 主な内容 |
|---|---|---|
| `8d6c78f` | network | VPC/security group と Minecraft port の最小公開。RCON ingress は作らない。 |
| `8fa426c` | instance role | EC2 instance role/profile と SSM/対象 Parameter の最小権限。 |
| `0253f94` | EC2 instance | Amazon Linux 2023 上の Minecraft EC2 construct。 |
| `2b85bb1` | data volume | root と分離した、暗号化・retain の data EBS。 |
| `7786d2e` | data volume bootstrap | XFS 初期化と UUID mount、mount 不成立時 fail-closed。 |
| `54d853d` | Java | Corretto 25 headless installation。 |
| `51767b9` | Minecraft runtime | 固定 artifact download/checksum、server setup。 |

関連する主なファイル:

- `infrastructure/constructs/network.py`
- `infrastructure/constructs/minecraft_instance_role.py`
- `infrastructure/constructs/minecraft_instance.py`
- `infrastructure/constructs/minecraft_data_volume.py`
- `infrastructure/constructs/data_volume_bootstrap.py`
- `infrastructure/constructs/java_runtime.py`
- `infrastructure/constructs/minecraft_artifact.py`
- `infrastructure/bootstrap/data_volume_mount.sh`
- `infrastructure/bootstrap/java_runtime_install.sh`
- `infrastructure/bootstrap/minecraft_artifact_install.sh`
- `infrastructure/bootstrap/minecraft_game_setup.sh`
- `tests/unit/test_data_volume_mount_script.py`
- `tests/unit/test_java_runtime.py`
- `tests/unit/test_minecraft_artifact.py`
- `tests/unit/test_minecraft_bootstrap_scripts.py`

技術的に理解しておくべきこと:

- data EBS は instance replacement や stack 削除の副作用で消えないよう retain とする。world data は root volume に置かない。
- mount script は「空の正しい volume」のみ初期化する。filesystem 種別や partition/signature が想定外なら消去せず失敗する。これはワールド破壊を避ける fail-closed 設計である。
- `nofail` は boot を止めないための設定であり、Minecraft を root volume で起動してよいという意味ではない。Minecraft service 側で mount guard を必須にする。
- Secret の取得権限は対象 Parameter ARN だけに絞る。security group で RCON が閉じていても、host firewall を含めた実効到達性を確認する。

### 2026-08-08: Phase 1 bootstrap、RCON、手動 DNS 操作の完成

#### 実装・commit

`c56df94 feat: complete Phase 1 server bootstrap and DNS operations`

追加・更新された中心的な要素:

- `bootstrap_runner.sh`: bootstrap artifact の順序と実行を統制する runner。
- `minecraft_rcon_configure.sh`: SSM SecureString を EC2 実行時に取得して設定へ渡す。値を stdout に出さない。
- `minecraft_rcon_firewall.sh`: RCON port への non-loopback traffic を host firewall で拒否。
- `src/wishicraft/route53_cli.py`: Phase 1 の管理用 CLI として、動的 IPv4 に対する A record UPSERT/DELETE を扱う。CDK の固定状態に DNS record を入れない。
- bootstrap bundle construct と、runbook/architecture/security/Decision の更新。
- bootstrap runner、RCON firewall、Route 53 CLI の unit tests。

ここでの境界:

- これは実装とローカル検証であり、AWS deploy、EC2 作成、DNS 変更、server.jar の実ホスト取得・起動とは別である。
- EULA 同意や実ホストでの Minecraft 初回起動は runbook の明示手順に残し、意図せず実行しない。

### 2026-08-08〜08-15: bootstrap/firewall の不具合修正と検証契約の強化

#### 発生したエラー・原因・修正

この期間の commit は、検証で見つかった具体的な故障を安全な migration 契約へ落とし込んだものだった。元の端末出力すべては会話記録には残っていないため、以下は commit と test 名から復元できる事実であり、存在しない生のエラー文は補完していない。

| commit | 問題/原因 | 修正 |
|---|---|---|
| `f5e027b test: isolate RCON firewall mocks from host tools` | firewall test が実行 host の `nft` 等の有無に影響され、fixture が host tool を参照していた。 | mock/stub を isolation し、host 依存を除去。 |
| `fb1466a fix: correct data volume blkid queries` | mount 判定で使う `blkid` query が期待する情報を正しく取得できないケース。 | query を修正し、regression test を追加。 |
| `28abc8f fix: pass mount guard environment to game setup` | game setup が mount guard に必要な environment を受け取らない経路。 | construct から必要 environment を渡し、stack test を追加。 |
| `266ae01 fix: preserve canonical bootstrap artifacts` | migration/resume 時に canonical bootstrap artifact を不用意に上書きし得る。 | runner が metadata と canonical artifact を保存・照合するよう変更。 |
| `d7c567d fix nftables 1.0.4 firewall migration` | nftables 1.0.4 で firewall migration に互換性問題。 | version を考慮した migration に直し、runbook と大量の unit test を更新。 |
| `211b30e fix: resume RCON firewall migration safely` | 中断・再実行時に firewall migration の安全な resume 条件が不足。 | idempotent resume と migration metadata の安全条件を実装・テスト。 |

関連 commit:

- `afb2a67 docs: define autonomous local validation boundaries`
- `ece7b78 docs: record idempotent firewall migration contract`
- `131c1aa test: cover bootstrap metadata conflicts`
- `d8a3701 docs: define canonical systemd enable links`
- `16478d2 docs: clarify live firewall postflight`

#### 判断と理由

- firewall や mount は「失敗しても再実行すればよい」だけでは不十分である。途中まで適用された状態、既存 metadata と artifact の不一致、systemd enable link の差異を検出して安全側に停止する必要がある。
- test harness は実機や実 host firewall に触れない専用 temporary root を使う。過去の証跡を上書きせず、fixture failure は新しい version/root で診断する。
- production wrapper、payload、oracle、selection logic の変更が必要になった場合は、自律的に拡張せず根拠と影響を示して停止する、という working agreement を文書化した。

#### 重要コマンドと目的

ソースや script の syntax を確認する代表例:

```sh
bash -n infrastructure/bootstrap/data_volume_mount.sh
bash -n infrastructure/bootstrap/java_runtime_install.sh
sha256sum infrastructure/bootstrap/java_runtime_install.sh
sha256sum infrastructure/bootstrap/minecraft_game_setup.sh
sha256sum infrastructure/bootstrap/minecraft_rcon_firewall.sh
```

これらは artifact 本文の差分・shell syntax・テスト証跡の整合確認であり、EC2 や AWS を操作しない。

CI 状態・job/annotation の確認には GitHub API、`gh run list`、`gh run view`、`jq` を使った。CI failure が出た場合、成功を装わず job/step/annotation を確認してから test を追加・修正する方針だった。

## 3. 設計上の重要ポイント

### 設定 validation の二層化

- **schema validation**: YAML の型、必須の構造、Parameter Store 名などを検証する。`null` は埋めない。
- **required validation**: stage、Phase、action（例: synth/deploy）に必要な path だけを要求する。

この分離により、prod placeholder を正常にロードしつつ、誤った prod 操作は不足パスを示して止められる。また、将来 Phase が進んだときに「今 `null` だから恒久必須」という誤設計を防げる。

### CDK の environment-agnostic synth

Phase 0 の dev synth は AWS Account ID、profile、credential を要求しない。これは CI で CloudFormation template を再現可能に作るための性質であり、deploy 可能性や AWS 認証の確認を意味しない。

### AWS identity の扱い

- account/region の正本は stage YAML。
- ローカル profile は credential 取得の手段にすぎず、アプリケーションコードの設定値ではない。
- 初回 dev deploy の直前に、STS caller identity の account と stage YAML の account を照合する。
- 不一致なら deploy 前に止める。

### RCON の防御層

1. Security Group に RCON ingress を作らない。
2. Vanilla の socket bind に過度に依存せず、host firewall でも loopback 以外を拒否する。
3. password は EC2 role が runtime に SSM SecureString から読む。
4. password を CDK context、user data、CloudFormation、Git、fixture、stdout/log に出さない。
5. `server.properties` は Minecraft service user が必要な最小権限で読む。

### 固定 artifact の検証

- version、公式 URL、checksum、size を stage 設定の正本に固定する。
- `latest` や可変の配布 URL を使わない。
- download 後に checksum/size を照合し、不一致は起動前に失敗させる。
- EULA 設定と初回起動は、実行を許可された別の手順でのみ行う。

## 4. 検証のまとめ

少なくとも Phase 0/Phase 1 準備時点で確認したローカル品質ゲート:

```text
pytest: 16 passed
Ruff check: passed
Ruff format --check: passed
mypy: passed
Phase 1 dev CDK synth: passed
git diff --check: passed
GitHub Actions: success
```

Phase 1 の後続 commit では、mount、Java、artifact、bootstrap runner、RCON firewall、Route 53 CLI、stack の unit test を追加し、fixture isolation と migration resume の regression test を拡充した。

検証結果を読む際の注意:

- unit test/synth 成功は AWS deploy 成功ではない。
- GitHub Actions 成功は、AWS credential、SSM value、EC2 host、DNS propagation、Minecraft client 接続を確認したことにはならない。
- 反対に、実 AWS 操作を行っていないことは未完了ではなく、承認境界を守った結果である。

## 5. セッション終了時点の状態と残作業

### 実装済み・記録済み

- Phase 0 foundation と CI。
- dev/prod 設定を扱う validation gate。
- Phase 1 network、instance role、EC2、data EBS、mount guard、Java 25、固定 Minecraft artifact、bootstrap runner、RCON runtime configuration/firewall、手動 Route 53 CLI。
- Phase 1 runbook、Decision、working agreement の更新。
- firewall migration の idempotency/resume/canonical artifact/systemd link に関する修正と document。

### まだ実行していない AWS/運用操作

- CDK bootstrap
- `cdk diff`
- deploy
- STS caller account 照合
- EC2、EBS、IAM、Security Group、SSM、Route 53 の実 AWS resource 作成/変更
- Parameter Store の RCON password 実値の取得・表示
- EC2 上での server.jar download/checksum verification
- `eula=true` 設定
- Minecraft 初回起動、client 接続、world 永続化の実機確認
- DNS A record の UPSERT/DELETE

これらはすべて、該当 runbook を確認し、AWS/host/deploy/DNS/secret の操作直前で明示承認を得てから行う。

### 後続 Phase の残作業

- Phase 1 の実 AWS deploy と runbook による手動 acceptance（承認後）。
- Phase 2: EC2 内部操作スクリプト（probe/start/stop）と SSM Run Command 経由の検証。
- Phase 3: Reconcile と実測 status。
- Phase 4: Operation、idempotency、lease lock。
- Phase 5/6: 安全な start/stop workflow と DNS 自動化。
- Phase 7: Discord MVP。
- Phase 8: backup、復元テスト、無人自動停止、監視。

## 6. 学びとしてのチェックリスト

- [ ] `null` は「わからない」であり、デフォルト値を選ぶ許可ではない。
- [ ] synth と deploy、schema validation と required validation、公開設定と secret、control plane と host bootstrap を混同しない。
- [ ] IAM 最小権限、Security Group、host firewall、filesystem permission は重ねて設計する。
- [ ] data volume や firewall migration は idempotency と partial failure を先に考える。
- [ ] unit test の mock が host tool に依存していないか確認する。
- [ ] runbook は設計の補足ではなく、実 AWS 操作の承認境界・確認項目の一部である。
- [ ] 実行していない AWS 操作を、local test や CI 成功から推測して「確認済み」と書かない。
