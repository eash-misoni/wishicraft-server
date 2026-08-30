# 12. Initial Configuration

- **文書状態:** Canonical
- **対象:** Phase 0開始時点の初期設定
- **最終更新:** 2026-08-30

## 1. 目的

Codexが未確定値を推測したり、秘密情報をGitへ保存したりしないように、初期設定の正本、実行時への配布方法、秘密情報の扱いを定義する。

## 2. 確定済み設定

```yaml
display_name: Wishicraft
discord_bot_name: "ゐしクラくん"
repository_name: wishicraft-server
project_slug: wishicraft
resource_prefix: wc
system_id: wishicraft-main
initial_game_id: game-vanilla-main
initial_game_display_name: Wishicraft Vanilla
initial_minecraft_profile_name: NEWISHIN_
preferred_domain: wishicraft.net
minecraft_fqdn: mc.wishicraft.net
region: ap-northeast-1
architecture: x86_64
instance_type: t3a.medium
operating_system: amazon-linux-2023
java_runtime: corretto-25-headless
java_xms: 1G
java_xmx: 3G
root_ebs: gp3 16 GiB
data_ebs: gp3 30 GiB
data_ebs_filesystem: xfs
minecraft_version: "26.2" # dev stage only
minecraft_server_jar_size: 60894273 # dev stage only
minecraft_server_jar_sha256: cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5
initial_minecraft_profile_uuid: e912ab95758e4b7fb32e292eda293104
```

Minecraft profile UUIDの設定正本は、Mojang profile APIと同じhyphenなし32桁lowercase形式とする。`whitelist.json`などMinecraftの永続JSON境界では、`8-4-4-4-12`のhyphen付きlowercase形式へ決定的に変換する。比較時はhyphenを除去した32桁形式へ正規化し、表現差とUUID値の差を区別する。

上記の`java_runtime`、server.jar checksum、初期profileのMinecraftファイル表現はPhase 1 as-builtの設定である。itzg移行後も履歴として残すが、host Javaや独自artifact downloaderを今後のtargetとしない。

dev用Discord Guild/channel/role/Application ID/Public Keyは`config/stages/dev.yaml`へ反映済みとする。Application IDとPublic Keyを含むDiscordの公開IDは秘密情報ではないが、文書へ重複記載せずstage設定を正本とする。

devのAWS Account ID、Availability Zone、Minecraft port/version、Route 53 Hosted Zone IDは`config/stages/dev.yaml`へ反映済みとする。prodを含む未確定値は該当stage設定で`null`を維持する。prod用Discord Guild/channel/role/Application ID/Public Keyも、prod環境を準備するまで`config/stages/prod.yaml`で`null`を維持する。

## 3. 設定ファイルの責務

### `config/project.yaml`

project全体で共通する公開設定の正本とする。

- 名称とbranding
- 内部IDとresource prefix
- 固定FQDN
- toolchain
- 共通resource tag

### `config/stages/<stage>.yaml`

stageごとの公開設定の正本とする。

- AWS Account、Region、Availability Zone
- compute、runtime、storage
- data EBSのfilesystem種別とmount path
- Route 53
- Discordの公開ID
- timeout、lock、monitoring、cost設定

未確定値は`null`とし、Codexやコードが推測で補完してはならない。

### `config/secrets.example.yaml`

秘密値そのものではなく、Parameter Store `SecureString`へ保存するParameter名だけを定義する。

Git管理されたYAMLを設計・デプロイ時の正本とする。CDKがLambda environment、SSM Parameter Store、EC2設定等へ値を配布しても、それらを人間が独立して編集する第二の正本にはしない。変更はYAMLまたはCDK定義へ戻してdeployする。

Phase 2以降は設定所有権をさらに分離する。

| 種別 | 唯一の正本 |
|---|---|
| itzg image、Docker/Compose、基盤policy、immutable default | Git管理の`host_runtime`設定 |
| Discord等から運用中に変更するdesired state | SystemStateの`desired_revision` CAS。Observed `observed_at`、Operation `current_operation_id`とは分離する（D-074） |
| RCON等のsecret | AWS secret store |
| world、Minecraft実ファイル | data EBS上のruntime data。desired stateの正本ではなくrealization結果 |

同じ設定キーをGitとDynamoDBへ重複して正本化せず、Wishicraftとitzgが同じMinecraft実ファイルを双方から直接編集しない。

CDKが作成したinstance ID、table名、ARN等の実行時resource identifierは、CloudFormation output、Lambda environment、必要なParameter Store String等へ配布してよい。これらは手入力する設計設定ではなく、deploy結果から生成される値として扱う。

## 4. 秘密情報

次をGit、Markdown、Issue、Pull Request、通常ログ、Discordメッセージへ保存しない。

- Discord Bot Token
- Discord OAuth Client Secret
- RCON password
- Web session signing key
- AWS access key、secret access key、session token

Codexへ実値を渡さない。

## 5. 秘密情報の保存先

MVPではAWS Systems Manager Parameter Storeの`SecureString`を基本とする。

```text
/wishicraft/dev/secret/discord-bot-token
/wishicraft/dev/secret/rcon-password
/wishicraft/prod/secret/discord-bot-token
/wishicraft/prod/secret/rcon-password
```

コードやCDKには実値ではなくParameter名だけを渡し、実行時IAM roleで取得する。自動rotation等が必要になった場合だけSecrets Managerを検討する。

## 6. AWS credential

設定ファイルへ保存しない。人間の開発環境はAWS IAM Identity CenterまたはAWS CLI profileを使用する。GitHub Actionsからdeployする場合はOIDCによる短期credentialを使う。

devのローカル認証はIAM Identity Centerの`wishicraft-dev` profileを使用する。このprofileは認証取得専用であり、Account IDとRegionの正本ではない。AWS CLIおよびCDKの手動コマンドでは`--profile wishicraft-dev`を明示し、deploy前にSTS caller identityのAccount IDと`config/stages/dev.yaml`の`aws.account_id`を照合する。不一致ならdeployを中止する。profile名やSSO roleをstage YAMLやCDKアプリケーションコードへ保存しない。

## 7. ローカル専用ファイル

以下は`.gitignore`へ追加する。

```text
.env
.env.*
!.env.example
config/local.yaml
config/stages/*.local.yaml
secrets.yaml
*.secret.yaml
```

`.env`やlocal YAMLを本番秘密情報の正本にしない。

## 8. Codexルール

- `null`や`TO_BE_CONFIRMED`を推測で埋めない。
- secretの実値を要求しない。
- Lambda environmentへsecret値を平文で入れない。
- Parameter名またはSecret IDだけを設定として扱う。
- deploy先のParameter Store StringをYAMLと別個に手動更新しない。
- secretをtest fixture、snapshot、logへ含めない。
- Phase 0では秘密情報をAWSへ登録しない。

## 9. 後で入力する値

最初のdev deploy前:

- AWS profileの解決方式。AWS Account IDは`config/stages/dev.yaml`へ反映済みである。

Phase 1前:

- RCON passwordをEC2へ安全に配布する方式
- Minecraft EULAへの同意手順とserver配布元

dev用RCON passwordはSecureStringへ登録済みである。実値は取得・表示・Gitへの保存を行わない。Minecraft 26.2の公式server.jar URL、SHA-1、SHA-256、sizeは`config/stages/dev.yaml`へ固定した。初期GameのEULA同意は明示済みであるが、server.jarのEC2取得、checksum検証、Minecraft初回起動はdeploy後の別途手動確認として扱う。

`mc-dev.wishicraft.net`のAレコードはPhase 0で手動作成しない。Phase 5 START workflowがruntime READY、active Game一致、current public IPv4を確認した後にUPSERTし、Route 53 `INSYNC`とendpoint一致を成功条件にする。Phase 5以降のSG baselineはgameplay TCP 25565だけであり、SSH/RCON/管理portは公開しない。停止後のDNS cleanupはcanonical workflow/operator procedureだけで行い、Desired/Observedとの不一致をraw Route 53/DynamoDB mutationで隠さない。

itzg採用後もEULA同意はoperator policy/gateとして維持する。承認主体と事実はWishicraft/operator側で管理し、承認済みの場合だけitzgへ同意入力を渡す。itzgの`EULA`入力自体を人間の承認記録の代替にしない。

Phase 2開始前に、itzg image tag/digest、Docker Engine / Compose固定方法、container UID/GID、memory/JVM heap、lifecycle ownerとrestart/stop timeout、command path、secret injection、desired/applied schemaをDecisionとして確定する。既存値や`null`から推測しない。

Phase 2aではD-060により、devのAL2023 release、architecture、Compose release/checksum、itzg Java 25 release tag/digest、Minecraft 26.2、initial memory、停止timeoutを`host_runtime`へ記録した。既存data EBSのnumeric UID/GIDはObservation Requiredとして`null`を維持する。Docker packageは固定AL2023標準repositoryを正本とし、RPM NEVRAを独立したユーザー設定として二重管理せず、導入時の検証結果として記録する。Phase 1 `compute`と`minecraft_distribution`はas-built値として維持する。

Phase 2b-1ではD-061により、dev current memory targetをcontainer `2816MiB`、Xms `1G`、Xmx `2G`へ更新した。これはminimal Vanilla用Provisional tuningであり、Phase 1 `compute.java_xmx=3G`とは別のtarget値である。既存EBS identityは`993:993`と観測したがstage設定のUID/GID `null`は、実機apply artifactへ観測値を明示入力する現行契約を維持するため自動補完しない。

Phase 2 target Host Runtimeのstage設定は、その後のtarget platform lockとroot-only
実機validationでnumeric identity `993:993`を正本化した。real-data migrationでは
この固定値を使用し、自動採番や再帰的ownership変更を行わない。

D-062でPhase 2 target platform lockを最終確定した。targetはAL2023 `2023.12.20260803`、kernel 6.18、ap-northeast-1の公式x86_64 AMI `al2023-ami-2023.12.20260803.3-kernel-6.18-x86_64` / `ami-0b4d2909a55ed2c78`である。Phase 1 as-built `2023.12.20260803.3` / kernel 6.1は履歴として変更しない。固定releaseの標準repositoryで確認したDockerは`docker-25.0.16-1.amzn2023.0.3.x86_64`だが、RPM NEVRAは独立した設定正本にせず実機install時にも記録・照合する。

D-063でdev target hostは`MinecraftTargetStack-dev`へ分離した。既存VPC `vpc-0c3cca1e65696ed8e` / ap-northeast-1a subnet `subnet-0a70e5682ea8d0bd3`を明示inputとし、target EC2は`t3a.medium`、暗号化gp3 16 GiB root、public IPv4、専用SSM role/profileを使用する。Phase 2 deploy時の専用SG ingress 0はhistorical stateであり、Phase 5適用後のbaselineはMinecraft gameplay TCP 25565だけを許可する。SSH/RCON/管理portは公開しない。target stackはdata EBS、Phase 1 IAM/SG、secret、DNSを参照しない。Phase 2 identityは観測済み`993:993`を使用する。

Phase 7B production適用前:

- `config/stages/dev.yaml`のGuild/channel/role/Application ID/Public KeyがDiscord Developer Portalと実際のGuild設定に一致することを確認する
- Discord Bot Tokenのdev用SecureStringが存在することを値を表示せず確認し、未登録なら別の明示承認付きoperator actionで登録する
- `phase=7` Control Plane synthでGit正本command schemaとDiscord Command Lambda assetがhash-locked Linux wheelを含めて再現可能にbundleされることを確認する

Phase 7G E2E前:

- Git管理の`/mc status`、`/mc start`、`/mc stop` schemaを正本としてdev ApplicationへGuild commandを明示operator actionで登録する
- command registrationをCDK deployの暗黙side effectにしない

最初のprod deploy前:

- prod Discord Guild/channel/role/Application ID/Public Keyを確定し、`config/stages/prod.yaml`へ反映する
- prod Discord Bot Tokenをprod用SecureStringへ登録する

未確定値があってもPhase 0のrepository bootstrap、validation、dev向け`cdk synth`は開始できる。未確定値が必要なstageのsynth、deploy、integration testは開始しない。

## 10. Phase 0完了時点のvalidation

Phase 0は2026-07-29に完了した。設定schema validationは、YAMLの型・必須構造・Parameter Store名だけを検証し、`null`を補完しない。required validationはschema validationと別に、stage・Phase・処理ごとに適用する。

- devのPhase 0空stack synthはenvironment-agnosticであり、AWS Account IDやAWS profileを要求しない。Phase 1以降で必要になるAWS Account ID、Availability Zone、Minecraft port/version、Route 53 Hosted Zone IDも要求しない。
- prod設定はplaceholderとして読込可能に維持する。Phase 0のprod synthは現在の全`null`値をパス付きで表示して拒否する。
- このprod拒否は、現在の全`null`を将来も必須とする定義ではない。Phase 1開始前にstage・処理・Phaseごとのrequired settingを定義する。
- AWS Account IDはstage設定の正本とし、local profileの利用・STS照合方針はD-050と本書のAWS credential節へ確定済みとして記録する。実際のIAM Identity Center認証とSTS照合は最初のdev deploy直前に実行する。
