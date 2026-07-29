# Phase 1 dev Manual Validation Runbook

- **文書状態:** Canonical
- **対象:** dev Phase 1の手動基盤検証
- **最終更新:** 2026-07-29

## 1. 禁止事項と承認gate

このrunbookは手順を記録するが、CDK bootstrap、`cdk diff`、deploy、AWSリソース作成を自動実行しない。

特に、次は人間が別途明示承認するまで実行禁止とする。

- server.jarのダウンロード
- `eula=true`の設定
- Minecraft serverの初回起動

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

設定の正本は`config/stages/dev.yaml`である。version、URL、SHA-1を手入力で変更したり、`latest`を使用したりしない。

1. 明示承認を記録する。
2. stage設定の固定URLからserver.jarを取得する。
3. `shasum -a 1`でSHA-1を計算し、stage設定の`minecraft_distribution.server_jar_sha1`と完全一致することを確認する。
4. 不一致ならartifactを使用せず、原因を記録して中止する。
5. 一致後にだけ許可済みdata volume pathへ配置する。

## 5. EULAと初回起動（明示承認後のみ）

1. EULAの現行条件を公式情報で再確認する。
2. 人間がEULA同意を明示確認するまで`eula=true`を書き込まない。
3. data volumeがUUIDで期待するmount pathへmount済みであることを確認する。
4. RCON設定ファイルの権限、RCON localhost限定、Minecraftポートだけの受信規則、static whitelist、`online-mode=true`を確認する。
5. systemd経由で初回起動し、journal、memory、CPU credit、data volume、SSM接続を確認する。

## 6. DNS確認

`mc-dev.wishicraft.net`のAレコードはPhase 0では作成しない。Phase 1のEC2起動後に現在のpublic IPv4へUPSERTし、Route 53 changeの`INSYNC`とDNS解決を確認する。EC2停止完了後はAレコードを削除し、再度`INSYNC`を確認する。

## 7. Data EBS mount準備service

1. `systemctl status wishicraft-data-volume.service`と`journalctl -u wishicraft-data-volume.service`で準備結果を確認する。
2. `findmnt /srv/minecraft`、`blkid`、`/etc/fstab`のUUID entryを確認し、XFSと期待するdata EBS volumeがmountされていることを確認する。
3. mount準備serviceがfailedなら、再format、`wipefs`、強制mountを実行しない。SSM Session ManagerでNVMe serialとEBS volume ID、fstab競合、mount pathの内容を調査する。
4. `nofail`はOSとSSMの復旧経路を維持するための設定であり、Minecraftやbackup/resetのmount確認を緩和しない。
