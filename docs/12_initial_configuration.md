# 12. Initial Configuration

- **文書状態:** Canonical
- **対象:** Phase 0開始時点の初期設定
- **最終更新:** 2026-07-29

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
```

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

dev用RCON passwordはSecureStringへ登録済みである。実値は取得・表示・Gitへの保存を行わない。Minecraft 26.2の公式server.jar URLとSHA-1は`config/stages/dev.yaml`へ固定した。server.jarの取得、checksum検証、`eula=true`の設定、Minecraft初回起動は、人間が別途明示承認するまで実行しない。

`mc-dev.wishicraft.net`のAレコードはPhase 0で手動作成しない。Phase 1でEC2起動後に現在の動的パブリックIPv4へUPSERTし、EC2停止完了後に削除する。

Phase 7前:

- `config/stages/dev.yaml`のGuild/channel/role/Application ID/Public KeyがDiscord Developer Portalと実際のGuild設定に一致することを確認する
- dev ApplicationへGuild commandを登録する
- Discord Bot Tokenをdev用SecureStringへ登録する

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
