# Phase 1 dev Manual Validation Runbook

- **文書状態:** Canonical
- **対象:** dev Phase 1の手動基盤検証
- **最終更新:** 2026-08-08
- **追記:** 2026-08-15 Minecraft初回起動の既知部分適用再開

## 1. 禁止事項と承認gate

このrunbookは手順を記録するが、CDK bootstrap、`cdk diff`、deploy、AWSリソース作成を自動実行しない。

特に、次は人間が別途明示承認するまで実行禁止とする。

- server.jarのダウンロード
- `eula=true`の設定
- Minecraft serverの初回起動

初回起動migrationが`systemctl start`で失敗した場合は、再送前に`Result`とExecStartPreの失敗を分離する。mount／game setup verifierはroot権限のread-only ExecStartPreで動作し、game setup verifierからmount guardの変更経路を呼ばないことを正本hashとunit bytesで確認する。既知のauto-restart部分適用からの再開では、Java processと25565／25575 listenerが0件であることを確認してからserviceをquiesceし、承認済みpredecessorだけをatomic upgradeする。

## 2. AWS接続先の事前照合

1. ローカルでIAM Identity Centerへ認証し、`wishicraft-dev` profileを使用する。
2. AWS CLI/CDKの手動コマンドには常に`--profile wishicraft-dev`を付ける。
3. deploy直前に次を実行する。

   ```sh
   aws sts get-caller-identity --profile wishicraft-dev --region ap-northeast-1 --query Account --output text
   ```

4. 出力を`config/stages/dev.yaml`の`aws.account_id`と比較する。一致しなければ中止する。
5. profile名・SSO roleをstage YAML、CDKコード、ログへ保存しない。
6. Phase 1 deploy前のvalidationは`--context phase=1 --context validation_action=deploy`を指定して実行する。実際のdeployは別途承認が必要であり、このrunbookでは実行しない。

## 3. RCON passwordの実行時配布設計

1. CDKはParameter名だけをEC2 bootstrapへ渡し、秘密値をtemplate、user data、CloudFormation outputへ渡さない。
2. EC2 instance roleには対象SecureStringだけの`ssm:GetParameter`を許可する。広いParameter pathや`*`を許可しない。
3. EC2内の許可済みbootstrap scriptはcommand traceを無効化したまま`--with-decryption`で取得する。復号値をstdout/stderr、journal、例外メッセージへ出さない。
4. `server.properties`は`root:minecraft`所有、mode `0640`とし、Minecraft service userがgroup readだけで参照できるようにする。temporary fileも`umask 077`で作成し、不要になったら削除する。
5. RCONはlocalhost限定で設定する。Security GroupにRCONの受信ルールを追加しない。

## 4. Minecraft 26.2 artifact取得・検証（明示承認後のみ）

設定の正本は`config/stages/dev.yaml`である。version、URL、SHA-1、SHA-256、sizeを手入力で変更したり、`latest`を使用したりしない。

1. 明示承認を記録する。
2. stage設定の固定URLからserver.jarを取得する。
3. `stat -c '%s'`、`sha1sum`、`sha256sum`でsizeと両checksumを計算し、stage設定と完全一致することを確認する。
4. 不一致ならartifactを使用せず、原因を記録して中止する。
5. 一致後にだけ許可済みdata volume pathへ配置する。

## 5. EULAと初回起動（明示承認後のみ）

1. EULAの現行条件を公式情報で再確認する。
2. 人間がEULA同意を明示確認するまで`eula=true`を書き込まない。今回の初期Gameは明示同意済みである。
3. data volumeがUUIDで期待するmount pathへmount済みであることを確認する。
4. RCON設定ファイルの権限、RCON localhost限定、Minecraftポートだけの受信規則、static whitelist、`online-mode=true`を確認する。
5. systemd経由で初回起動し、journal、memory、CPU credit、data volume、SSM接続を確認する。

## 6. Route 53固定FQDN管理

`mc-dev.wishicraft.net`のAレコードはPhase 0では作成しない。Phase 1ではCDK resourceとして固定作成せず、リポジトリの限定管理CLIだけで管理する。CLIの利用前に、EC2が`running`、SSM、data volume、`minecraft.service`が確認済みであることを確認する。

```sh
.venv/bin/python -m wishicraft.route53_cli UPSERT --stage dev --profile wishicraft-dev
```

CLIは`config/project.yaml`と`config/stages/dev.yaml`からrecord type、TTL、Hosted Zone、FQDN、timeout、account、regionを取得する。利用者はIP address、Hosted Zone ID、record name、TTL、stack name、instance ID、timeoutを指定してはならない。CLIはcaller account、固定stack名`MinecraftStack-dev`のCloudFormation output `MinecraftInstanceId`、単一の`running` instance、Project/Stage tag、グローバルなpublic IPv4を確認する。scanやName tag検索は行わない。

Hosted Zoneが設定FQDNの親zoneであること、および対象recordが単純な単一値A recordであることを確認する。Alias、weighted、latency、failover、geolocation、multi-value、CIDR、health check、複数valueのrecordは変更・削除しない。同一のTTLとIPv4を持つrecordへのUPSERTは変更しない成功となる。変更した場合、CLIは`GetChange`で設定値`timeouts_seconds.route53_insync`（devでは120秒）まで`INSYNC`を待ち、最終的にTTLとIPv4が一致することを再読取で確認する。

成功時stdoutはsecretを含まないJSONであり、少なくとも`stage`、`action`、`account`、`region`、`stack`、`instance_id`、`hosted_zone_id`、`record_name`、`record_type`、`ttl`、`public_ipv4`、`changed`、`change_id`、`final_status`を含む。診断はstderrへ出る。非zero終了時は成功JSONとして扱わない。DNS解決結果がCLI出力の`public_ipv4`と一致し、Minecraft接続を人間が確認してからオンライン完了とする。この確認はAWS実地検証であり、CIまたはsynthで完了扱いにしない。

Minecraftを安全に保存・停止し、EC2が`stopped`となったことを確認した後にだけ削除する。

```sh
.venv/bin/python -m wishicraft.route53_cli DELETE --stage dev --profile wishicraft-dev
```

recordが存在しないDELETEは変更しない成功となる。存在する場合は、読み取った完全な単純record setだけをDELETEし、`INSYNC`後に対象A recordが存在しないことを再確認する。古いIPv4のDNS解決がTTLを超えて残らないことも人間が確認する。

### 6.1 管理者の最小IAM policy（dev例）

新しいIAM user、role、長期access keyを作らない。IAM Identity Center等の短期credentialに、次のpolicyと同等の最小権限を付与する。account、stack、Hosted Zone、record nameはdev設定の正本から得た値であり、prodへコピー・推測しない。EC2の`DescribeInstances`はAWSのread API制約によりResourceを限定できないため`*`だが、CLI側でCloudFormation output、instance ID、tagを三重に限定する。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid":"CallerIdentity","Effect":"Allow","Action":"sts:GetCallerIdentity","Resource":"*"},
    {"Sid":"ReadMinecraftStack","Effect":"Allow","Action":"cloudformation:DescribeStacks","Resource":"arn:aws:cloudformation:ap-northeast-1:385526546525:stack/MinecraftStack-dev/*"},
    {"Sid":"ReadResolvedMinecraftInstance","Effect":"Allow","Action":"ec2:DescribeInstances","Resource":"*"},
    {"Sid":"ReadConfiguredHostedZone","Effect":"Allow","Action":["route53:GetHostedZone","route53:ListResourceRecordSets"],"Resource":"arn:aws:route53:::hostedzone/Z077818024BJUAUBFMTKV"},
    {
      "Sid":"ChangeOnlyConfiguredMinecraftARecord",
      "Effect":"Allow",
      "Action":"route53:ChangeResourceRecordSets",
      "Resource":"arn:aws:route53:::hostedzone/Z077818024BJUAUBFMTKV",
      "Condition":{"ForAllValues:StringEquals":{"route53:ChangeResourceRecordSetsNormalizedRecordNames":"mc-dev.wishicraft.net","route53:ChangeResourceRecordSetsRecordTypes":"A","route53:ChangeResourceRecordSetsActions":["UPSERT","DELETE"]}}
    },
    {"Sid":"WaitForOwnRoute53Changes","Effect":"Allow","Action":"route53:GetChange","Resource":"arn:aws:route53:::change/*"}
  ]
}
```

policy適用前に、組織SCP、permission boundary、AWS IAM action/resource/condition supportを確認する。`GetChange`のresource-level制約を組織のIAM検証が受け付けない場合だけ、そのactionを単独statementの`Resource: "*"`へ狭く例外化する。Route 53変更statementを`*`へ拡大してはならない。

## 7. Data EBS mount準備service

1. `systemctl status wishicraft-data-volume.service`と`journalctl -u wishicraft-data-volume.service`で準備結果を確認する。
2. `findmnt /srv/minecraft`、`blkid`、`/etc/fstab`のUUID entryを確認し、XFSと期待するdata EBS volumeがmountされていることを確認する。
3. mount準備serviceがfailedなら、再format、`wipefs`、強制mountを実行しない。SSM Session ManagerでNVMe serialとEBS volume ID、fstab競合、mount pathの内容を調査する。
4. `nofail`はOSとSSMの復旧経路を維持するための設定であり、Minecraftやbackup/resetのmount確認を緩和しない。

## 8. Java runtime確認

1. `rpm -q java-25-amazon-corretto-headless`でheadless packageが導入済みであることを確認する。
2. `java -version`でmajor versionが25であり、Corretto runtimeであることを確認する。異なる既定Javaが選ばれている場合は、Minecraftを導入・起動せず原因を調査する。

## 9. Minecraft service確認

### 9.0 初回起動migrationの停止境界

- 第13回Run Command `1b62638b-8d69-4f4f-8dfb-183496a62449`でRCON firewall migrationは完了済みである。target tableやpersistent rulesを初回起動のために再適用しない。
- Run14 read-only診断 `ccdba675-2ef5-44d1-b917-86e0a5f7c7d1`で、data EBS mount、Corretto 25、固定26.2 jar、account/directory、EULA、properties、whitelistの既設状態と、Minecraft unit/world/logs/process/listenerの不存在を確認した。
- 初回起動candidateは、mount、Java、firewall、process/listenerを最初に検証し、既設artifactを個別分類する。未知world、temporary file、metadata/hash不一致、symlink、raceを検出したらdaemon-reload、enable、start前に停止する。
- server.jarは設定の固定URL・size・SHA-1・SHA-256をすべて確認してからatomic配置する。RCON SecureString値、properties本文、environment本文をstdout/stderrへ出さない。
- start後はREADY marker、service/process、25565/25575 listener、management listener不存在、data EBS上のworld、firewall JSON semantics、non-target nft fingerprintを確認し、completion markerは最終行に1件だけ出す。
- 第15回は`P03_JAVA`後、readonly変数へのenvironment prefix代入により`FAIL:FIREWALL_TABLE`で変更前停止した。後継版では`env RCON_PORT="$RCON_PORT"`でclassifierへ渡す。`C00_CHANGE_BEGIN`が存在しない結果ではMinecraft artifactやserviceを変更済みと扱わない。

1. `findmnt /srv/minecraft`と`systemctl status wishicraft-data-volume.service`を確認してから、`systemctl status minecraft.service`を確認する。
2. `server.properties`で`server-port=25565`、`online-mode=true`、`white-list=true`、`enforce-whitelist=true`、`enable-rcon=true`、`rcon.port=25575`、`broadcast-rcon-to-ops=false`、`management-server-enabled=false`を確認する。RCON passwordの実値は表示・記録しない。
3. Mojang profile APIの正規化UUID `e912ab95758e4b7fb32e292eda293104`が`NEWISHIN_`に対応することを確認する。`whitelist.json`では同じUUIDが`e912ab95-758e-4b7f-b32e-292eda293104`として永続化され、hyphen除去後の比較が一致することを確認する。
4. whitelist serialization修復時は、既知predecessorのwhitelist／environment／game setupだけを受容する。Minecraftを通常停止してworld保存とlistener停止を確認し、atomic更新後に再起動する。world、server.properties、RCON secret、firewallを変更しない。
   第21回は変更開始前の`FAIL:STATIC`で停止し、第22回read-only診断でhost predicateはすべて正常だった。temporary glob不存在時の`compgen` statusを関数失敗へ漏らさず、明示的な正常returnを持つ修正版だけを次回候補とする。
   第26回では通常停止後、Java／listenerは停止済みでもsystemdがSIGTERM status 143を`failed`として保持し`STOP_STATE`になった。再開候補は`inactive`／`failed`のいずれでもMainPID、Java process、全Minecraft関連listenerが0の場合だけ停止完了として受容する。
4. `journalctl -u minecraft.service`、`ps`、listening portを確認する。Management Protocolがlistenしていないこと、RCON portへの非loopback IPv4/IPv6到達がnftablesで拒否され、Security GroupにRCON ingressがないことを確認する。
5. `systemctl stop minecraft.service`で正常停止とワールド保存を実EC2で確認し、再起動後にワールドがdata EBS上で保持されることを確認する。これらはdeploy後の手動確認であり、CIでは検証しない。

### Firewall migrationの再開条件

- AL2023のnftables 1.0.4互換rulesは、top-levelの`create table`、`add chain`、IPv4/IPv6 `add rule`を1つのtransactionにし、`destroy`、nested object定義、`flush ruleset`、推測的なtarget table削除を含めない。
- v15由来のempty tableを再開する場合は、v15 script 2589 bytesと固定SHA-256、root:root 0755、unit/drop-in/link正本、nftables 1.0.4、Result=exit-code、ExecMainStatus=39、rules/temp不在、Minecraft/Java/RCON停止、およびJSON上でchain/rule/set/map/flowtable等がすべて0であることを確認する。条件が1つでも違えば送信しない。
- postflightは`nft -j list table inet wishicraft_rcon`をsemanticに検証し、input chain 1件、IPv4/IPv6 drop rule各1件、loopback例外、port一致、未知object/expression 0件を確認する。persistent rules fileが正本になる前にmigration完了としない。
- live target tableが存在するpostflightでは、先頭が`create table`のboot用persistent rulesを再度`nft --check`しない。fileの固定bytes/hash/metadataとlive JSON semanticsを独立検証し、`nft --check`はtable不存在時のservice適用直前に行う。
- script、unit、drop-in、enable link、rules、live tableを個別分類し、正本だけを無変更で再利用する。tableのみ正本の場合はrulesだけを確定し、rulesのみ正本の場合は同じbytesを検証してlive tableを復元する。
- v15 scriptからの更新は記録済みv15 hash・2589 bytes・root:root・0755・regular/non-symlink・構文正常がすべて一致する場合だけ許可する。不一致物や残存temporary fileは変更せず停止する。
- `WCRF:STEP:*`、`WCRF:FAIL:*`とexit statusで失敗段階を確認する。RCON passwordやEnvironment全体はjournalへ出力しない。
