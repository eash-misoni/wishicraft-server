# 11. External Constraints and References

- **文書状態:** Canonical reference
- **最終確認:** 2026-08-23

## 1. 目的

DiscordやAWSの外部仕様に依存する設計上の制約を記録する。

外部サービスの仕様は変更される可能性があるため、該当機能の実装直前に公式資料を再確認する。本文書と公式資料が矛盾する場合、公式資料を確認した上でDecision logと関連文書を更新する。

## 2. Discord Interactions

### 初期応答期限

Discord Interactionは、受信後短時間で初期応答が必要である。長時間処理ではDeferred Responseを使用する。

設計への影響:

- Command Lambdaは署名検証、認可、受付だけを短時間で完了する。
- EC2/Minecraftの起動完了をCommand Lambda内で待たない。
- Step Functionsを非同期開始する。

公式資料:

- [Receiving and Responding to Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [Interactions Overview](https://docs.discord.com/developers/interactions/overview)

### Interaction Tokenの有効時間

Interaction Tokenは長時間operationの永続的な更新手段として扱わない。

設計への影響:

- 公開進捗メッセージの`channel_id`と`message_id`をOperationへ保存する。
- Bot Tokenを使用してメッセージを更新する。
- Bot TokenはSecrets Manager等へ置く。

### Rate limit

Discord APIにはrouteごとのrate limitがある。

設計への影響:

- 状態pollごとに不要なDiscord更新を行わない。
- 進捗が変化した時だけメッセージを更新する。
- 429応答をretry可能errorとして扱い、Discord失敗とMinecraft operation結果を分離する。

公式資料:

- [Rate Limits](https://docs.discord.com/developers/topics/rate-limits)

### Gateway

Discord通常メッセージを受信する完全双方向chatにはGatewayへの常時接続が必要になる。

設計への影響:

- 初回サーバーレス制御面へGateway接続を混ぜない。
- 完全双方向chatは別の常駐コンポーネントとして後期検討する。
- `/mc say`はInteraction/HTTP経由で実装可能。

公式資料:

- [Gateway](https://docs.discord.com/developers/events/gateway)

## 3. AWS Step Functions

Standard Workflowsは長時間、監査可能なworkflow向けであり、実行履歴を保持する。

設計への影響:

- start/stop/backup/resetにStandardを使用する。
- Workflow typeは作成後変更できないため、最初からStandardとして作成する。
- Retryを設定したTaskは再実行され得るため、Task自体を冪等にする。

公式資料:

- [Choosing workflow type in Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/choosing-workflow-type.html)
- [What is Step Functions?](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)


### Execution nameと冪等性

Standard Workflowのexecution nameは一意であり、実行中の同じnameと同じinputに対する`StartExecution`は冪等に扱われる。終了済みexecutionのname再利用には制約がある。

設計への影響:

- 一意な`operation_id`をexecution nameに使用する。
- Operationへexecution nameとARNを保存する。
- Workflow開始失敗時の後始末を所有者条件付きで行う。

公式資料:

- [StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)

## 4. DynamoDB TTL

TTL期限を過ぎたitemは、期限時刻ちょうどに削除されるとは限らず、削除待ちの間もreadへ現れる可能性がある。

設計への影響:

- Lockの有効性は`expires_at < now`で判断する。
- TTLは古いitemの後処理にだけ使用する。
- 期限切れitemをquery結果から除外する必要がある場合はfilterまたはapplication側判定を行う。

公式資料:

- [Using time to live (TTL) in DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
- [Working with expired items and TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ttl-expired-items.html)

## 5. LambdaとVPC

Lambdaは通常、AWS管理ネットワークからpublic endpointへ接続できる。ユーザーVPCへ接続すると、そのVPC側でinternet access経路が必要になる。

設計への影響:

- LambdaをユーザーVPCへ接続しない。
- Minecraft EC2操作はSSMとEC2 APIを使用する。
- Discord APIへ接続するためだけにNAT Gatewayを作らない。
- 将来VPC内resourceへ直接接続する要件が発生した場合だけ再評価する。

公式資料:

- [Giving Lambda functions access to resources in an Amazon VPC](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
- [Enable internet access for VPC-connected Lambda functions](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html)

## 6. SSM Run Command

Run Commandはcommand送信の受付と、EC2上での最終的な処理成功を分けて扱う必要がある。timeout、delivery failure、execution failure等を区別する。

設計への影響:

- command IDを取得し、終了statusをpollする。
- `Success`だけでなくscript JSONの`success`と事後probeを確認する。
- Run Command成功だけでMinecraft READYや停止完了としない。
- stdout/stderrの上限を考慮し、大きいログはCloudWatch/S3へ送る。

公式資料:

- [Understanding command statuses](https://docs.aws.amazon.com/systems-manager/latest/userguide/monitor-commands.html)

## 7. EC2 instance type変更

EBS-backed EC2のinstance type変更は停止中に行う。互換性のあるCPU architecture、virtualization、network要件等を満たす必要がある。

設計への影響:

- runtime classは任意instance type文字列ではなくallowlistとする。
- 初期版は1 architecture、1 runtime classに固定する。
- instance type変更後にSSM、mount、Java、Minecraftを再検証する。

公式資料:

- [Change the instance type](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-resize.html)


## 8. Route 53と動的パブリックIPv4

EC2の自動割当てパブリックIPv4は停止・起動で変わる可能性がある。Route 53のresource record変更は非同期で処理され、change statusを確認できる。

設計への影響:

- Elastic IPを初期構成へ含めない。
- 起動後の現在IPv4へ固定FQDNのAレコードをUPSERTする。
- `GetChange`で`INSYNC`を確認してからオンライン完了とする。
- 停止完了後はAレコードを削除する。
- 低いTTLを設定するが、resolver cacheがTTLどおりでない可能性も考慮する。
- Hosted Zone IDとrecord nameを設定として固定し、IAMを限定する。

公式資料:

- [ChangeResourceRecordSets](https://docs.aws.amazon.com/Route53/latest/APIReference/API_ChangeResourceRecordSets.html)
- [GetChange](https://docs.aws.amazon.com/Route53/latest/APIReference/API_GetChange.html)
- [Amazon EC2 instance IP addressing](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-instance-addressing.html)

## 9. EBS attachmentとmount

EBS volumeは同じAvailability ZoneのEC2へ接続する。Linux上のdevice nameは環境により変化し得るため、filesystem UUID等の安定した識別子でmountする。

設計への影響:

- EC2とdata EBSを同じAvailability Zoneへ固定する。
- data EBSをEC2とは別リソースとして保持する。
- filesystemがない場合だけ初期化する。
- UUIDで`/srv/minecraft`へmountする。
- mount未確認時はMinecraftや破壊的処理を実行しない。

公式資料:

- [Make an Amazon EBS volume available for use](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-using-volumes.html)
- [Attach an Amazon EBS volume to an instance](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-attaching-volume.html)

## 10. Phase 2 Host Runtime artifacts

- Phase 2 targetはAL2023 `2023.12.20260803`へ固定する。AWSのdeterministic repository update modelを使用し、ap-northeast-1 / x86_64 / kernel 6.18の公式AMI name、ID、owner、creation dateもstage設定へ固定する。
- AWSは2026-08-17からkernel 6.18をAL2023 defaultとし、最新kernelとして推奨している。AL2023は6.1、6.12、6.18を同じuserspace packageと互換性でsupportする。WishicraftはFIPS要件や6.1固有kernel依存を持たないため6.18を採用する。
- Docker Engineは固定AL2023 releaseの標準repositoryに含まれる`docker` packageを使用する。20260803で確認したpackageはx86_64対応の`25.0.16-1.amzn2023.0.3`である。20260608の`.0.1`に記録されたmulti-network regression後の更新buildであり、現行Host Runtimeは単一Compose networkを使用する。RPM NEVRAを独立した恒久設定正本にはせず、導入時に実値を記録・照合する。
- Composeは公式CLI pluginを使用する。Phase 2a lockはDocker公式repositoryでも固定値が確認できるv5.4.0 x86_64とSHA-256を使用する。
- itzgは`2026.7.2-java25`のGHCR manifest digestを固定する。Minecraft 26.2はJava 25を要求する。
- 固定releaseのentrypointはrootでUID/GIDを設定し、`SKIP_CHOWN_DATA=true`なら`/data`のrecursive chownをskipした後、`gosu`でruntime UID/GIDへdropする。server.properties setupとmc-image-helperはdrop後に実行される。
- `SETUP_ONLY=true`はserver artifactとconfigurationを準備した後、Minecraft Java process起動前に正常終了する。Phase 2b-1ではこの公式境界をsynthetic ownership testに使用する。

公式資料:

- [AL2023 2023.12.20260803 release notes](https://docs.aws.amazon.com/linux/al2023/release-notes/relnotes-2023.12.20260803.html)
- [AL2023 kernel selection and compatibility](https://docs.aws.amazon.com/linux/al2023/ug/kernel-update.html)
- [AL2023.12 package list](https://docs.aws.amazon.com/linux/al2023/release-notes/all-packages-AL2023.12.html)
- [AL2023 20260608 Docker regression notice](https://docs.aws.amazon.com/linux/al2023/release-notes/relnotes-2023.12.20260608.html)
- [AL2023 repository updates](https://docs.aws.amazon.com/linux/al2023/ug/managing-repos-os-updates.html)
- [Docker Compose plugin installation](https://docs.docker.com/compose/install/linux/)
- [Docker Compose v5.4.0 artifact lock](https://github.com/docker-library/repo-info/blob/master/repos/docker/remote/dind-rootless.md)
- [itzg image versions](https://github.com/itzg/docker-minecraft-server/pkgs/container/minecraft-server/versions?filters%5Bversion_type%5D=tagged)
- [itzg Java image variants](https://docker-minecraft-server.readthedocs.io/en/latest/versions/java/)
- [itzg data directory](https://docker-minecraft-server.readthedocs.io/en/latest/data-directory/)
- [itzg stop duration](https://docker-minecraft-server.readthedocs.io/en/latest/configuration/misc-options/)
- [itzg 2026.7.2 startup identity](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/scripts/start)
- [itzg 2026.7.2 server.properties setup](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/scripts/start-setupServerProperties)
- [mc-image-helper 1.62.1 properties writer](https://github.com/itzg/mc-image-helper/blob/1.62.1/src/main/java/me/itzg/helpers/properties/SetPropertiesCommand.java)

## 11. Amazon Corretto 25 on Amazon Linux 2023

Amazon Linux 2023では標準package managerで`java-25-amazon-corretto-headless`を導入できる。headless variantはserver workload向けで、headful、devel、JModsは初期構成へ含めない。

設計への影響:

- stage設定のlogical runtimeをallowlistで固定package名へ解決する。
- package確認に加え、既定`java -version`がmajor 25かつCorrettoであることを確認する。

公式資料:

- [Amazon Corretto 25 Installation Instructions for Amazon Linux 2023](https://docs.aws.amazon.com/corretto/latest/corretto-25-ug/amazon-linux-install.html)

## 12. Minecraft Java server artifactとEULA

Minecraft Java Edition 26.2のserver artifactは、公式release page、Mojang version manifest、同version metadataを照合して固定する。runtimeでmanifestや`latest`を参照せず、download時にmetadataのSHA-1とsize、およびリポジトリ固定SHA-256を確認する。

EULA同意は人間の明示承認を必要とし、`eula=true`の設定はその承認を受けた初期Gameに限定する。

公式資料:

- [Minecraft Java Edition 26.2](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-2)
- [Minecraft EULA](https://www.minecraft.net/en-us/eula)
- [Mojang version manifest](https://piston-meta.mojang.com/mc/game/version_manifest_v2.json)

## 13. AWS料金・quota

料金、free tier、service quotaは変更される。

実装前・運用前に公式料金ページとService Quotasを確認する対象:

- EC2 instance
- EBS gp3、snapshot
- Public IPv4
- Route 53 Hosted Zone、query、domain registration
- S3 storage/request
- CloudWatch logs
- Secrets Manager
- Step Functions state transitions
- API Gateway requests/connections
- DynamoDB requests/storage

設計上の固定方針:

- NAT Gatewayを作らない。
- Budgetsを設定する。
- log retentionを明示する。
- EC2 running時間を監視する。
- S3 lifecycleを設定する。

## 14. 実装前再確認チェック

各Phase開始時に次を確認する。

### Discord Phase

- Interaction response期限
- token有効時間
- message edit API
- signature verification手順
- application command登録方法
- rate limits

### AWS workflow Phase

- Step Functions Standard quotas
- Lambda runtime support
- SDK retry behavior
- SSM command status
- DynamoDB conditional expression

### EC2 Phase

- 対象regionでのinstance availability
- Hosted Zone、固定FQDN、Route 53 change API
- 動的パブリックIPv4の割当て
- EBSとEC2のAvailability Zone一致
- filesystem UUID mountと保持方針
- AMI/OS support
- Java/Minecraft互換性
- Minecraft EULAの現行条件
- 公式version manifestまたは公式server配布元
- server artifactのversion固定と検証方法
- EBS pricing/capacity
- Public IPv4 pricing

### Phase 1 dev artifact固定値（2026-07-29確認）

- 公式version manifest: `https://piston-meta.mojang.com/mc/game/version_manifest_v2.json`
- Minecraft 26.2 metadata: `https://piston-meta.mojang.com/v1/packages/3457237902814cca3f5c6f20b0c5db1b1f341512/26.2.json`
- server.jar: `https://piston-data.mojang.com/v1/objects/823e2250d24b3ddac457a60c92a6a941943fcd6a/server.jar`
- server.jar SHA-1: `823e2250d24b3ddac457a60c92a6a941943fcd6a`
- server.jar size: `60894273`
- server.jar SHA-256: `cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5`
- metadataのJava runtime major version: 25

これらは公式metadataとartifact照合で確認した固定値であり、server.jar本体はGit管理しない。EC2での取得・検証・初回起動はdeploy後のrunbook手順として実施する。

### Web Phase

- Discord OAuth2仕様
- cookie/session security
- API Gateway authorization
- WebSocketを採用する場合の認証とconnection管理
