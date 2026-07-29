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
preferred_domain: wishicraft.net  # 取得前の予定値
minecraft_fqdn: mc.wishicraft.net
region: ap-northeast-1
architecture: x86_64
instance_type: t3a.medium
operating_system: amazon-linux-2023
java_runtime: corretto-21-headless
java_xms: 1G
java_xmx: 3G
root_ebs: gp3 16 GiB
data_ebs: gp3 30 GiB
```

dev用Discord Guild/channel/role/Application ID/Public Keyは`config/stages/dev.yaml`へ反映済みとする。Application IDとPublic Keyを含むDiscordの公開IDは秘密情報ではないが、文書へ重複記載せずstage設定を正本とする。

Minecraftの具体的version、Availability Zone、Minecraft port、AWS Account ID、Hosted Zone IDは、確定するまで該当stage設定で`null`を維持する。prod用Discord Guild/channel/role/Application ID/Public Keyも、prod環境を準備するまで`config/stages/prod.yaml`で`null`を維持する。

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

- AWS Account ID。CDK bootstrap/profileから安全に解決する方式を採る場合は、設定の`null`を維持してよい。

Phase 1前:

- `wishicraft.net`の取得結果
- Route 53 Hosted Zone ID
- Minecraftの具体的version
- Minecraft port
- Availability Zone
- RCON passwordを生成し、dev用SecureStringへ登録する
- RCON passwordをEC2へ安全に配布する方式
- Minecraft EULAへの同意手順とserver配布元

Phase 7前:

- `config/stages/dev.yaml`のGuild/channel/role/Application ID/Public KeyがDiscord Developer Portalと実際のGuild設定に一致することを確認する
- dev ApplicationへGuild commandを登録する
- Discord Bot Tokenをdev用SecureStringへ登録する

最初のprod deploy前:

- prod Discord Guild/channel/role/Application ID/Public Keyを確定し、`config/stages/prod.yaml`へ反映する
- prod Discord Bot Tokenをprod用SecureStringへ登録する

未確定値があってもPhase 0のrepository bootstrap、validation、dev向け`cdk synth`は開始できる。未確定値が必要なstageのsynth、deploy、integration testは開始しない。
