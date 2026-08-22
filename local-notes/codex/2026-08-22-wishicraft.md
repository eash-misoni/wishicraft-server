# Wishicraft Phase 1 実機検証・完了記録

> 記録対象: RCON firewall migration のF11診断から、Minecraft 26.2の初回起動、whitelist修復、world永続化、DNS公開、正常停止、Phase 1正式完了まで。  
> 記録日: 2026-08-22  
> 用途: 実装・運用・失敗診断を後から学び直すためのローカルノート。  
> 機密保護: AWS credential、SSO token/cache、RCON password、SecureStringの値、properties/environment本文、接続元IPは記載しない。

## 1. このセッションの全体像

このセッションでは、ローカルtest harnessの診断から始まり、段階的に次を完了した。

1. RCONをlocalhost限定にするnftables firewall migrationを安全に完成させた。
2. Minecraft Java Edition 26.2をdata EBS上で初回起動した。
3. whitelist UUIDのJSON表現を修正し、クライアント接続を成功させた。
4. Minecraftの通常停止、world保存、EC2停止・再起動後のworld永続化を実証した。
5. `wishicraft.net`の登録、メール確認、TLD委任、public DNSを確認した。
6. 動的Aレコードを削除し、MinecraftとEC2を安全に停止した。
7. Phase 1を正式完了として正本文書へ記録した。

一貫して守った原則は次のとおりである。

- frozen artifactと過去の失敗証跡を上書きしない。
- Run Commandは明示承認された回数だけ送信し、失敗・通信断・応答不明でも再送しない。
- host上の未知artifactを削除・上書き・chmod・chownしない。
- process、listener、mount、world、firewallを複数条件で確認し、単一のexit codeだけで安全判定しない。
- secret値をstdout、stderr、Git、temporary evidenceへ出さない。
- Minecraftの変更とread-only診断を別payloadに分ける。
- AWS変更前にaccount、region、instance、artifact hash、repository、競合operationを確認する。

## 2. 利用者が依頼・質問したこと

### 2.1 RCON firewall migration

利用者はF11静的診断結果を承認し、v6の正式結果を次として凍結した。

```text
v6正式結果: 421 PASS / 9 FAIL
主因: B（test-only nft mock/instrumentationの契約不一致）
副次原因: D（runnerのF11証跡不足）
production wrapper defect: 未証明
oracle defect: 未証明
```

その後、次を段階的に依頼した。

- test-only mock、runner、F11 comparatorの修正。
- 既設artifactを`absent / canonical / conflict`として扱うidempotent migration。
- 部分適用状態を安全に再開するv11以降のcandidate作成。
- 固定payloadを使うRun Commandを毎回1回だけ送信。
- failure checkpointごとにread-only診断し、原因が確定してから次versionを作る。
- nftables 1.0.4、systemdの依存集合、enable symlink、JSON semanticsを実機仕様に合わせる。

### 2.2 Minecraft初回導入

firewall完了後は、dev EC2をread-only診断し、次の固定要件でMinecraft 26.2を導入するcandidate作成を依頼した。

- Corretto 25 headless
- Xms 1G / Xmx 3G
- Minecraft port 25565
- RCON port 25575
- data mount `/srv/minecraft`
- Game ID `game-vanilla-main`
- 固定server.jar URL、size、SHA-1、SHA-256
- online mode、whitelist、RCON、Management Protocol無効化の安全predicate
- worldとlogsをdata EBS上に作成
- RCON secretを表示しない

### 2.3 Whitelist拒否の修正

`NEWISHIN_`本人が「ホワイトリストに登録されていない」と拒否されたため、公式profile照会とread-only実機診断を依頼した。UUID値自体は正しかったが、Minecraft JSON境界ではhyphen付き形式が必要だった。

正しい永続表現:

```text
e912ab95-758e-4b7f-b32e-292eda293104
```

設定正本ではMojang API互換のhyphenなし32桁lowercaseを維持し、JSON生成時だけ決定的にhyphenを付ける契約へ整理した。

### 2.4 world永続化、DNS、最終停止

利用者は次を順に依頼した。

- Minecraftを通常停止し、world保存完了を確認してEC2を停止する。
- 再起動後、同じdata EBS上のworld変更が保持されていることを確認する。
- `mc-dev.wishicraft.net`のAレコードを現在のPublic IPv4へ設定する。
- `wishicraft.net`の登録状態、料金、メール確認、TLD委任をread-onlyで調べる。
- メール確認後、public DNSが解決することを確認する。
- ユーザー自身がFQDNで接続し、world変更保持を目視確認する。
- 最終的にAレコードを削除し、MinecraftとEC2を停止してPhase 1を正式完了する。

## 3. Codexが行った主な判断

### 3.1 artifact mismatchとtest-only mismatchを分離した

F11失敗ではproduction defectを推測せず、wrapper本体、payloadからbinary-safeに復元した本文、runner comparatorを独立比較した。通常の`jq -r`は末尾LFを追加し、shell command substitutionは末尾LFを除去するため、正本比較には使わなかった。

安全な比較例:

```sh
jq -j -r '.Parameters.commands[0]' payload.json > restored.sh
cmp wrapper.sh restored.sh
sha256sum wrapper.sh restored.sh
```

Python JSON parserによる復元も別fileへ直接書き、2方式が同じbytesになることを確認した。

### 3.2 systemdの複数値を文字列全体で比較しなかった

`systemctl show ... -p Requires --value`は複数unitを空白区切りで返し、順序や既定dependencyが変わり得る。次のような全体一致は不適切である。

```text
Requires == wishicraft-rcon-firewall.service
```

正しい契約は、空白区切りtoken集合に対象unitが完全な1 tokenとして含まれることである。substringや類似名は拒否する。

### 3.3 enable symlinkはraw文字列ではなく解決先で判定した

systemdは絶対symlinkまたは相対symlinkを作り得る。`readlink`のraw targetと期待絶対pathを直接比較するとcanonical linkを誤拒否する。

そこで次を区別した。

- canonical absolute
- canonical relative
- dangling
- wrong target
- regular file
- directory
- query failure

canonical判定は、期待link pathがsymlinkであり、解決後targetが正確なcanonical unit fileに到達することとした。

### 3.4 nftables 1.0.4との互換性を実機versionへ合わせた

AL2023の実機は次だった。

```text
nftables-1.0.4-3.amzn2023.0.3.x86_64
```

`destroy table`は新しいnftablesで追加された構文で、1.0.4ではparseできなかった。また、nested object形式のbatchはstatus 0でもempty tableだけを作り、chain/ruleを作らなかった。

v16ではtop-level commandだけのtransactionへ変更した。

初回構築:

```text
create table inet wishicraft_rcon
add chain inet wishicraft_rcon input { ... }
add rule inet wishicraft_rcon input <IPv4 predicate> drop
add rule inet wishicraft_rcon input <IPv6 predicate> drop
```

v15由来empty tableのforward recovery:

```text
create chain inet wishicraft_rcon input { ... }
add rule inet wishicraft_rcon input <IPv4 predicate> drop
add rule inet wishicraft_rcon input <IPv6 predicate> drop
```

どちらも`nft --check --file`後、単一の`nft --file` transactionで適用した。`delete table`、`flush table`、`flush ruleset`は使わなかった。

### 3.5 firewallのcanonical判定をJSON semanticsへ移した

human-readable nft出力はversionによってpriority名、空白、quote、expression順序が変化する。安全判定は`nft -j list table`を解析し、次を厳密に検証した。

- table family/name
- chain count/name/type/hook/priority/policy
- IPv4/IPv6 ruleが各1件
- TCP、RCON port、loopback除外、drop verdict
- duplicate、unexpected expression/objectが0件
- set/map/flowtable/counter/comment/unknown objectが0件

### 3.6 既設artifactはapproved predecessorだけをatomic upgradeした

任意のcontent mismatchを「古い版」とみなさず、bytes、SHA-256、owner、group、mode、file type、非symlink、親directory、race再確認がすべて一致する既知versionだけを`approved_predecessor`として受容した。

これにより、部分適用から前進できる一方、不審なfileや人手変更を無断で上書きしない。

### 3.7 Minecraft停止は単一のsystemd statusで判定しなかった

現行unitでは通常のSIGTERM停止後に次が残った。

```text
ActiveState=failed
SubState=failed
Result=exit-code
ExecMainCode=1
ExecMainStatus=143
MainPID=0
```

143だけでは正常停止とせず、次を組み合わせて安全な停止済み状態と判定した。

- Java process 0
- service cgroup process 0
- 25565 / 25575 / 25585 listener 0
- NRestarts 0
- mount guard PASS
- XFS rw mountとvolume serial一致
- world、logs、level.datがdata EBS上
- level.datが通常file・非空
- I/O error、OOM、exception、restart loop 0

意図的停止をsystemd上でもsuccessにする方法はPhase 2前のbacklogとし、起動wrapper、終了コード伝播、`SuccessExitStatus=143`を比較検討する。

## 4. 実行した重要なコマンドと目的

### 4.1 Repositoryとartifactの固定確認

```sh
git rev-parse HEAD
git rev-parse main
git rev-parse origin/main
git status --short
git diff --check
```

目的:

- 承認されたcommitと作業treeが一致すること。
- unrelated changeを混ぜないこと。
- 文書・source差分にwhitespace errorがないこと。

```sh
stat -f '%N %z %Sp %HT' <artifact>
shasum -a 256 <artifact>
cmp wrapper.sh restored.sh
```

目的:

- path、regular file、mode、bytes、SHA-256を固定値と比較する。
- payloadから復元したwrapperがbyte-for-byte一致することを証明する。

### 4.2 AWS identityとEC2/SSM preflight

```sh
aws sts get-caller-identity \
  --profile wishicraft-dev \
  --region ap-northeast-1
```

目的: 操作対象accountをstage設定と照合する。credentialやSSO cache本文は表示しない。

```sh
aws ec2 describe-instances \
  --instance-ids i-021eaa7f33ddaf0a6 \
  --profile wishicraft-dev \
  --region ap-northeast-1

aws ssm describe-instance-information \
  --profile wishicraft-dev \
  --region ap-northeast-1
```

目的: Instance state、Public IPv4、EBS attachment、SSM Onlineをread-onlyで確認する。

### 4.3 SSM Run Command

```sh
aws ssm send-command \
  --cli-input-json file://<fixed-payload.json> \
  --profile wishicraft-dev \
  --region ap-northeast-1
```

目的: 固定済みpayloadを再構築せず、承認された1回だけ送信する。

```sh
aws ssm get-command-invocation \
  --command-id <command-id> \
  --instance-id i-021eaa7f33ddaf0a6 \
  --profile wishicraft-dev \
  --region ap-northeast-1
```

目的: 同じCommand IDのStatus、ResponseCode、stdout/stderrをread-onlyでterminalまで追跡する。

### 4.4 Route 53 Aレコード管理

```sh
.venv/bin/python -m wishicraft.route53_cli UPSERT \
  --stage dev \
  --profile wishicraft-dev

.venv/bin/python -m wishicraft.route53_cli DELETE \
  --stage dev \
  --profile wishicraft-dev
```

目的: repositoryのallowlist済みCLIだけを使い、設定に固定されたHosted Zone/FQDN/A recordだけを変更する。IP、zone、record名を利用者入力で差し替えない。

最終DELETE結果:

```json
{"account":"385526546525","action":"DELETE","change_id":"/change/C0913277USIZSISJV2BD","changed":true,"final_status":"INSYNC","hosted_zone_id":"Z077818024BJUAUBFMTKV","instance_id":null,"public_ipv4":null,"record_name":"mc-dev.wishicraft.net","record_type":"A","region":"ap-northeast-1","stack":"MinecraftStack-dev","stage":"dev","ttl":60}
```

### 4.5 Domain登録・委任のread-only確認

```sh
aws route53domains get-contact-reachability-status \
  --domain-name wishicraft.net \
  --profile wishicraft-dev \
  --region us-east-1

aws route53domains get-domain-detail \
  --domain-name wishicraft.net \
  --profile wishicraft-dev \
  --region us-east-1 \
  --query '{DomainName:DomainName,StatusList:StatusList,Nameservers:Nameservers}'
```

目的: contact個人情報を出力せず、reachability、hold status、登録側NSだけを確認する。

```sh
dig NS wishicraft.net @a.gtld-servers.net
dig DS wishicraft.net @a.gtld-servers.net
dig A mc-dev.wishicraft.net
dig +short @<authoritative-ns> A mc-dev.wishicraft.net
```

目的: TLD親委任、想定外DS、public resolver、Hosted Zone authoritative回答を別々に確認する。

### 4.6 EC2の通常停止

```sh
aws ec2 stop-instances \
  --instance-ids i-021eaa7f33ddaf0a6 \
  --profile wishicraft-dev \
  --region ap-northeast-1

aws ec2 wait instance-stopped \
  --instance-ids i-021eaa7f33ddaf0a6 \
  --profile wishicraft-dev \
  --region ap-northeast-1
```

目的: Minecraft停止確認後にforce/hibernateなしで1回だけ通常停止し、read-only waiterで`stopped`まで確認する。

## 5. 発生した主なエラー、原因、修正

### 5.1 v6 F11 failure

```text
421 PASS / 9 FAIL
```

原因: test-only nft mock/instrumentation契約と証跡比較の不一致。production wrapper defectやoracle defectは証明されなかった。

修正:

- mockがwrapper内部で取得する完全表現を返すようにした。
- runner comparatorとF11内部比較を同じ対象へ揃えた。
- frozen v6は失敗結果のまま保存し、新versionで検証した。

### 5.2 第4回: script既設部分適用

```text
FAIL:P12_SCRIPT_ABSENT
```

原因: bootstrapがcanonical firewall scriptを配置済みだったが、migrationは「不存在のみ」を期待していた。

修正:

- regular file、非symlink、固定bytes/hash、root:root、0755、構文正常なら既設canonicalとして無変更受容。
- 任意の不一致はconflictとして変更前停止。
- unit、drop-in、rules、enable linkにも同じ分類を適用。

### 5.3 第6回: systemd Requires predicate

```text
FAIL:C13_DROPIN_REQUIRES
```

原因: `Requires`全体を単一unit名と比較するpredicate。systemdは`sysinit.target`等の複数dependencyを返し得る。

修正: 空白区切りの正確なtoken membershipへ変更し、順序違い・追加dependencyを許容、substringや類似名を拒否した。

### 5.4 第7回: enable symlink predicate

```text
FAIL:C17_ENABLE_LINK
```

原因: systemdが作ったsymlinkのraw target表現と期待targetを文字列比較していた。相対／絶対表現の違いをcanonical差異と誤認した。

修正: symlinkを解決し、最終targetがcanonical unit fileへ完全一致するか確認した。

### 5.5 第8回: nftables 1.0.4で`destroy`非互換

```text
FAIL:C18_START
systemd ExecMainStatus=1
```

原因:

```text
destroy table inet wishicraft_rcon
```

`destroy`は実機nftables 1.0.4で利用できなかった。

修正: `destroy`、推測的delete、flushを除去し、`create table`をrace guardにした単一transactionへ変更した。

### 5.6 第10回: status 0だがempty tableだけ作成

```text
table inet wishicraft_rcon {
}
```

```text
ExecMainStatus=39
```

原因: nftables 1.0.4ではnested chain/rule構文が期待どおり適用されず、tableだけ作成された。human output差ではなく実semantic差だった。

修正:

- top-level 4-command batchへ変更。
- empty v15 partial専用の3-command recovery batchを追加。
- JSON semantic verifierをproduction判定の正本にした。

### 5.7 Whitelist UUID serialization

現象:

```text
ホワイトリストに登録されていない
```

原因: UUID値は正しかったが、`whitelist.json`でhyphenなし表現を使っていた。Minecraft 26.2のJSON境界ではcanonical hyphen付き表現が必要だった。

修正:

- 設定比較はhyphen除去32桁lowercaseへ正規化。
- JSON永続化時は`8-4-4-4-12`形式へ決定的変換。
- 既知predecessorに一致するwhitelist/environment/game setupだけをatomic upgrade。

### 5.8 非致命的なproperties書込み警告

原文:

```text
Failed to store properties to file: server.properties
```

原因: `server.properties`をroot管理・Minecraft user読取専用として保護しているため、Minecraft自身の書戻しが拒否された。

判定: 読込・parse失敗ではなく、service、listener、world、RCON設定は正常だったため単独ではblockerにしなかった。

### 5.9 正常停止markerの過剰な期待

旧wrapperは次の一般文字列を必須にした。

```text
Stopping server
Saving players
Saving worlds
```

Minecraft 26.2の実測では代わりに次が確認された。

```text
Saving chunks for level
All chunks are saved
All dimensions are saved
```

修正: versioned実測markerを保存完了証跡として扱った。markerだけでなくprocess/listener消滅、world/level.dat、mountも確認した。

### 5.10 最終停止のsystemd status

原文:

```text
FAIL:STOP_STATE
```

診断結果:

```text
SYSTEMD:LoadState=loaded
SYSTEMD:ActiveState=failed
SYSTEMD:SubState=failed
SYSTEMD:Result=exit-code
SYSTEMD:ExecMainCode=1
SYSTEMD:ExecMainStatus=143
SYSTEMD:MainPID=0
SYSTEMD:NRestarts=0
PROCESS:java=0:cgroup=0
LISTENER:25565=0:25575=0:25585=0
MOUNT:guard=pass:target=pass:fstype=pass:rw=pass:serial_match=pass
DATA:world=pass:level_dat=pass:logs=pass:root_divergence=pass
ERROR:io_error=0:oom=0:exception=0:restart=0
```

原因: Java processはSIGTERMで終了コード143を返し、現行systemd unitはそれをsuccessとして定義していない。

判定: process、cgroup、全listenerが0、restart 0、data EBS/world正常、I/O/OOM/exception 0なので安全な停止済み状態と判断した。

### 5.11 read-only診断scriptの`set -euo pipefail`

最初の診断はJava process不存在を示す`pgrep` status 1がpipelineへ漏れ、途中終了した。

```text
failed to run commands: exit status 1
```

原因:

```sh
set -euo pipefail
pgrep ... | awk ...
```

0件が正常な`pgrep`でもstatus 1となり、`pipefail`と`set -e`の組合せでscript全体が終了した。

修正:

- read-only診断では`set -e`を外した。
- 各predicateのPASS/FAILを収集し、最後にaggregate判定した。
- 0件が正常なcommandは件数へ変換し、非zeroを即時終了にしなかった。

## 6. 変更した主なファイル

### Production source / generator

- `infrastructure/bootstrap/minecraft_rcon_firewall.sh`
- `infrastructure/migrations/minecraft_initial_migration.sh`
- `infrastructure/migrations/minecraft_whitelist_repair.sh`
- `tools/build_minecraft_initial_migration.py`
- `tools/build_minecraft_whitelist_repair.py`

### Tests

- `tests/unit/test_minecraft_rcon_firewall.py`
- `tests/unit/test_minecraft_initial_migration.py`
- `tests/unit/test_minecraft_whitelist_repair.py`
- `tests/unit/test_route53_cli.py`
- 関連fixture、runner、mock、oracle

### Configuration / documentation

- `config/project.yaml`
- `docs/06_delivery_plan.md`
- `docs/09_decisions_and_backlog.md`
- `docs/10_codex_working_agreement.md`
- `docs/12_initial_configuration.md`
- `docs/runbooks/phase1_dev_manual_validation.md`
- `AGENTS.md`

### 最終Phase 1完了commit

```text
486373627367da9e998c6e7eea482c10b3ef2d3d
Complete Phase 1 manual validation
```

## 7. 今回理解しておくべき技術的内容

### 7.1 Idempotencyは「既存なら何でも受容」ではない

安全なmigrationでは既設物を次のように分類する。

```text
absent
canonical
approved predecessor
conflict
query failure
race
partial state
```

`approved predecessor`は固定bytes/hash/metadataへ完全一致する既知versionだけである。任意の古いfileを上書きする仕組みではない。

### 7.2 preflight、race check、postflightは役割が違う

- preflight: 現在状態が変更可能かを判定する。
- race check: preflight後に状態が変わっていないことを副作用直前に確認する。
- postflight: 実際の完成状態とnon-target不変を証明する。

preflight成功だけでは変更成功を意味しない。

### 7.3 nftables batchはsyntax成功とsemantic成功を分ける

`nft --check`や`nft --file`のstatus 0だけでは、期待chain/ruleが存在するとは限らない。適用後にJSON semanticsでobject countとpredicateを検証する必要がある。

### 7.4 systemdの表示は集合・解決結果・process状態として読む

- `Requires`や`After`は集合であり、順序付き文字列ではない。
- enable symlinkはraw文字列ではなく解決先で判定する。
- `ActiveState=failed`だけでprocessが残っているとは限らない。
- 正常停止判定にはMainPID、cgroup、process、listener、restart、保存状態を合わせる。

### 7.5 DNSはHosted Zone内の成功だけでは公開完了しない

次を別々に確認する。

1. Registered Domain側nameserver
2. contact reachabilityとhold status
3. TLD親ゾーンのNS delegation
4. DS/DNSSEC整合
5. Hosted Zone authoritative回答
6. public resolver回答

今回、Hosted Zone直接照会は成功していたが、登録者メール未確認による`clientHold`中はTLDがNXDOMAINを返した。メール確認後、status `ACTIVE`、親NS、public Aが揃った。

### 7.6 動的Public IPv4とDNS lifecycle

dev EC2はElastic IPを持たないため、起動ごとにPublic IPv4が変わり得る。

- 起動後: 現在IPへAレコードUPSERT
- Minecraft接続確認
- 停止前: AレコードDELETE
- Minecraft正常停止
- EC2通常停止

次回起動時は新Public IPv4へのUPSERTが必要である。

## 8. 検証結果

### RCON firewall

- production migration completion marker: 成功
- script/unit/drop-in/enable link/persistent rules: canonical
- `inet wishicraft_rcon`: JSON semantic canonical
- IPv4/IPv6 non-loopback RCON drop rule: 各1件
- unexpected target object/rule: 0件
- non-target nft state: 不変

### Minecraft

- Minecraft Java Edition 26.2: 起動成功
- Corretto 25: 使用
- service/process: 稼働確認後、最終的に停止
- Minecraft listener 25565: 稼働時1件、停止後0件
- RCON listener 25575: 稼働時1件、停止後0件
- Management listener 25585: 0件
- whitelist: `NEWISHIN_`とcanonical UUID表現
- ユーザーによるFQDN接続: 成功
- world変更の停止・再起動後保持: 成功
- root filesystem側world逸脱: 0件
- secret露出: 0件

### DNS

- `wishicraft.net`: Registered Domainで`ACTIVE`
- contact reachability: `DONE`
- parent NS: Hosted Zoneの4 NSと一致
- unexpected DS: なし
- public resolver: 稼働時に期待Aを返却
- Phase 1終了時Aレコード: DELETE済み、`INSYNC`

### EC2 / EBS

- EC2最終state: `stopped`
- Public IPv4: Instance情報から消滅
- data EBS: attachment維持
- data EBS DeleteOnTermination: `false`
- detach/delete/terminate/force stop: 0件

### Repository / CI

- Phase 1完了commit: `486373627367da9e998c6e7eea482c10b3ef2d3d`
- HEAD = main = origin/main
- worktree clean（このノート作成前）
- `git diff --check`: PASS
- GitHub Actions run `32571313558`: completed / success

## 9. 残っている作業

### Phase 2前の必須backlog

- 意図的SIGTERM停止をsystemd上でもsuccessとして表現する契約を決める。
- 起動wrapperでのexit code変換、Java終了コード伝播、`SuccessExitStatus=143`の妥当性を比較する。
- 自動停止workflowでは、process/listener/world/mountのsemantic postflightを維持する。

### 次回dev起動時

- EC2起動後にstatus checksとSSM Onlineを確認する。
- data EBS mount guardとMinecraft READYを確認する。
- 新しいPublic IPv4を取得する。
- repositoryの限定Route 53 CLIでAレコードをUPSERTする。
- 停止時はAレコードDELETE、Minecraft正常停止、EC2通常停止の順序を守る。

### 今後のPhase

- Phase 2以降のSTART/STOP/STATUS自動制御。
- lock、idempotency、observed state、failure recovery。
- backup workflowとdata EBS保護。
- Discord command連携。

Phase 1で作ったmigration用temporary artifactや過去のfailure evidenceは、正本sourceではない。今後の実装判断はrepositoryの最新source、test、Decision、runbookを優先する。
