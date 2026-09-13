# 08. Human Operation Flows

> Web Foundation D-102（Accepted・production適用前）: [Web契約・公式仕様比較](reviews/web_foundation.md)、[local / release / rollback](runbooks/web_foundation.md)を参照。

静的参加案内（D-100）: ブラウザで版・Game・権限・注意を確認し、接続先/招待は管理者から個別に受け取る。状態確認と操作はDiscordの指定チャンネルを使用する。[利用案内](discord_user_guide.md)がページ別の説明原稿への入口、[Web準備レビュー](reviews/user_guide_web.md)が公開手順・承認境界を所有する。

利用者向けの現行コマンド・権限・Resetの注意点は[Discord利用案内](discord_user_guide.md)を参照してください。進捗表示改善D-099はAccepted・production適用済みです。実STATUS一回で実行者・到達記録・公開配送を確認しました。

> Resetは[D-098 Accepted](reviews/game_scoped_reset.md)。B限定policyの有効化とPlayer/Adminの日常実行を分離する。二回の隔離復旧後、一般受付を元設定へ復元済み。実行方法と損失境界は同契約、検証範囲は[closeout](runbooks/game_scoped_reset_migration.md#production-closeout)を参照する。


- **文書状態:** Canonical
- **最終更新:** 2026-09-12

## 1. この文書の対象

現在のDiscord入口はstatus/start/stop/backupとD-097のGame選択・switch（2026-09-12適用・E2E完了）。D-096の対象検証・正常STOP後のcontainer整理は内部処理であり、利用者へ手動docker cleanupを要求しない。失敗時は同じ対象のOperation/実観測を確認し、別runやraw編集で帳尻を合わせない。[現在契約](05_data_and_interface_contracts.md#0-production適用済みruntime契約d-096)と[operator移行/失敗証跡](runbooks/targeted_runtime_migration.md)を分けて参照する。

以下のGame作成・Reset等の将来flowは未提供。二Gameの選択・SWITCH command、管理者認可、接続者がいる時の扱いは[D-097 Accepted](reviews/two_game_switch.md)を正本とする。`/mc start game:…`は停止中の対象選択、`/mc switch game:… confirm:true`はadminの明示切替。観測人数がpositive/unknownなら拒否し、0人確認直後の接続raceは残る。状態表示で選択対象と実稼働対象・進行中Operationを分け、切替失敗時は追加操作を連打せず同じOperationの結果と保存状態を確認する。D-095のoperator隔離復元完了は、利用者向けRestore公開を意味しない。

内部実装ではなく、人が何を実行し、何を見て、次に何を判断するかを定義する。

役割:

- 一般利用者
- Discord管理者
- システム管理者
- サーバーパッケージ作成者

## 1.1 Discord実装前の管理者確認

Phase 5、6では、システム管理者が管理CLIまたはadmission Lambda test eventを使用する。

1. 一意なclient request IDを指定する。
2. Operation admission serviceを呼び出す。
3. Operation、Idempotency、Lock、Current Operationが作成されたことを確認する。
4. admission serviceがStep Functionsを開始する。
5. Discord metadataがないため進捗メッセージ処理がskipされたことを確認する。
6. Operation履歴、実状態、Lock解放を確認する。

State Machineを直接開始して受付処理を迂回しない。

## 1.2 Phase 1で固定FQDNを手動確認する

Phase 1では自動workflowがまだないため、システム管理者が管理用runbookまたは管理CLIでDNSを更新・削除する。

1. EC2を起動し、`running`と現在のパブリックIPv4を確認する。
2. SSM接続、data volume mount、`minecraft.service`を確認する。
3. stage別の固定FQDNを現在のパブリックIPv4へUPSERTする。
4. Route 53 changeが`INSYNC`になるまで待つ。
5. DNS解決結果が現在のIPv4と一致することを確認する。
6. 固定FQDNからMinecraftへ接続する。
7. 検証後、Minecraftを保存・停止し、EC2が`stopped`になるまで待つ。
8. Aレコードを削除し、Route 53 changeが`INSYNC`になったことを確認する。
9. 固定FQDNが停止済みEC2の古いIPv4を指していないことを確認する。

Phase 5・6完成後は、この手順を日常操作に使用せずstart/stop workflowへ移行する。


## 2. 初回実用版でゲームを起動する

1. 一般利用者がDiscordのMinecraft操作channelを開く。
2. `/mc start`を実行する。
3. システムが権限、現在operation、実状態を確認する。
4. Interactionへ短時間で受付応答を返す。
5. 受付できた場合、Botがチャンネル全体へ通常メッセージとして操作者名と起動要求を表示する。
6. 同じBot通常メッセージを次の主要段階で更新する。
   - 起動要求受付
   - EC2起動中
   - SSM接続待ち
   - Minecraft起動中
   - 接続確認中
   - オンライン
7. Route 53更新完了後のオンライン表示と固定FQDNを確認する。
8. Minecraftクライアントに一度登録した固定FQDNから接続する。

拒否例:

- 別operationが進行中
- 既に同じゲームがオンライン
- 状態確認不能で安全に起動できない
- 権限不足

権限不足や内部詳細は本人限定。競合中のoperation概要は利用者向けに公開してよい。

## 3. 状態を確認する

1. `/mc status`を実行する。
2. システムは保存済み表示だけでなく、EC2を実測する。
3. EC2 runningの場合はSSMとMinecraftを追加確認する。
4. 次を分けて表示する。
   - EC2
   - SSM
   - public IPv4
   - 固定FQDN/DNS
   - Minecraft service
   - Minecraft response
   - active game
   - player count
   - health
   - 最終実測時刻
   - current operation
5. 確認不能な項目は`UNKNOWN`と表示する。
6. 保存値との不一致がある場合は警告を表示する。

## 4. ゲームを停止する

1. 一般利用者が`/mc stop`を実行する。
2. システムが実状態と競合operationを確認する。
3. 停止要求がチャンネル全体へ公開される。
4. Minecraftへ保存要求を行う。
5. 保存成功後にMinecraftを停止する。
6. Minecraftプロセス停止を確認する。
7. EC2を停止する。
8. EC2が実際にstoppedになった後、固定FQDNのAレコードを削除する。
9. Route 53変更完了後、停止完了を公開する。

保存失敗時:

- 通常停止を成功扱いしない。
- EC2を無条件に停止しない。
- 管理者へ内部情報を通知する。
- 必要なら管理者が調査またはEmergency stopを判断する。


## 5. 初回メンバーをホワイトリストへ登録する

MVPではDiscordからのホワイトリスト編集機能をまだ作らない。システム管理者が初回構築時またはSSM経由で固定メンバーを登録する。

1. Minecraft Java Editionのプロフィール名を確認する。初期登録名は`NEWISHIN_`とする。
2. `online-mode=true`、`white-list=true`、`enforce-whitelist=true`を確認する。
3. 管理コマンドまたは許可済み手順で`whitelist add <profile-name>`を実行する。
4. Minecraftサーバーが名前からUUIDを解決し、`whitelist.json`へ名前とUUIDを保存したことを確認する。
5. 許可されたプレイヤーが接続できることを確認する。
6. 未登録アカウントが接続できないことを確認する。

Discordからの追加・削除、OP、候補表示は後期のプレイヤー管理機能で実装する。

## 6. 起動中に別のstartを実行した場合

1. システムがreconcileする。
2. 同じゲームがREADYなら「すでにオンライン」と表示する。
3. 起動途中なら現在のoperationと進捗を表示する。
4. 別ゲームが起動中なら、別ゲームを止める必要があることを表示する。
5. 新しい競合operationは作成しない。

## 6.1 Backup完成前にsnapshotを取る

Phase 8B/8Cで停止中Data EBSのEBS Snapshot backupは検証済みである。重要変更前の追加snapshot要否はD-090のBACKUP contractと管理者runbookに従う。

1. 通常stopでMinecraftとEC2を停止する。
2. data EBSの対象volumeを確認する。
3. snapshotを作成し、Game、generation、目的、日時をtagへ記録する。
4. snapshot作成開始を確認する。
5. 重要変更後にstart/status/stopを確認する。

これは恒久的なbackup workflowの代替ではない。


## 7. 手動バックアップを取る

Phase 8以降。

1. Discord管理者が`/mc backup`を実行する。
2. Command ingressが署名、Application/Guild、operation channel、admin roleを検証し、ACK成功後だけshared AdmissionへBACKUPを渡す。
3. 公開messageは受付、backup作成・検証中、完了またはsafe failureだけを同一messageで表示し、Snapshot ID、Volume ID、AWS errorを表示しない。
4. BACKUP workflowがfresh STOPPED/HEALTHY/no-discrepancyとcurrent Data EBSを検証する。起動中はfail closedとし、BACKUP自身はSTOP/STARTしない。
5. 一回限りのcreate intentでData EBS Snapshotを作成し、`completed`、source、owner、exact metadataを検証する。
6. Operationをterminal化し、LockとCurrent Operationを所有者条件付きで解放する。Discord delivery失敗はOperation結果を変更しない。

dev Phase 8C E2Eではadmin roleなしrequestがAdmission前に拒否され、role付与後のreal requestはbackend Snapshotまで成功した。初回public deliveryだけがloaderのBACKUP許可漏れでDLQへ隔離されたため、修正deploy後に同Operationの元stream eventsをcontrolled replayした。stale revisionはno-op、terminal revisionだけが固定nonceの単一safe success messageへ収束し、新しいBACKUP/SnapshotやOperation status repairは行っていない。

## 8. 無人自動停止

Phase 8.2以降。D-092/D-093を正本とする。

1. Target heartbeatが同一Game/runtime/bootでREADYかつplayer 0を継続観測し、`empty_since`を維持する。unknown、stale、再接続、identity変更はcontinuityを切る。
2. Game設定のidle timeout（devは30分）の5分前以降、同一empty periodに一件だけ「約5分後に自動停止」のDiscord warningを配送する。
3. STOPはidle timeout到達と実warning delivery成功から5分経過の両方を待つ。warning failureや再接続では当該periodを再利用しない。
4. EvaluatorはSTOP/SCHEDULEをshared Admissionへ渡すだけで、EC2、Minecraft、DNS、heartbeat、SystemStateを変更しない。
5. global Lock所有下でfresh Reconcileを行い、HEALTHY、矛盾なし、canonical Game/Target/Data EBSとfresh trusted-zero heartbeatを再検証する。
6. さらにfixed Host Runtime probeでplayer 0を直接再観測する。unknown、positive、mismatchならDesired変更前にCANCELLEDとしてLock/Current Operationを解放する。
7. final gate成功後だけDesired STOPPEDとsave/stopへ進み、既存通常STOPでgraceful runtime stop、EC2 stop、DNS cleanup、final Reconcileを完遂する。

player countが確認不能の場合やSystemState/Reconcileをfreshかつhealthyと証明できない場合、自動停止しない。historical FAILED/CANCELLED Operationは削除せず、同一empty periodで自動再試行しない。stale Operationのbookkeeping recoveryが必要な場合は専用runbookを使用し、Lockやtableを手動修正しない。

## 9. 新しいゲームを作る

Phase 10以降。

1. Discord管理者が`/mc create`を実行する。
2. 本人限定UIでTemplateを選択する。
3. Game表示名を入力する。
4. Templateが許可するSeed、難易度等を設定する。
5. Package、Minecraft version、必要client、runtime classを確認する。
6. 本人限定の最終確認を行う。
7. 確定後、作成開始をチャンネル全体へ公開する。
8. システムはGameメタデータを作成し、`UNMATERIALIZED`として保存する。
9. 作成完了後、起動ボタンまたは`/mc start`案内を表示する。
10. この時点ではMinecraft EC2を起動しない。

初回start時:

1. Packageを取得する。
2. checksumを確認する。
3. stagingへ展開する。
4. Game設定を生成する。
5. materialize成功後にMinecraftを起動する。

## 10. Gameを選んで起動する

Phase 9以降。

1. `/mc start`を実行する。
2. 本人限定Select MenuでACTIVEなGame一覧を表示する。
3. 対象を選ぶ。
4. MOD/Paperの場合は必要client情報を表示する。
5. 選択確定後、公開起動operationを開始する。
6. 以後は初回実用版と同じ進捗表示を行う。

## 11. ワールドをresetする

Phase 11以降。

1. Discord管理者が対象Gameが停止中であることを確認する。
2. `/mc reset`を実行する。
3. 本人限定UIでGameを選択する。
4. Seedをランダム、前回と同じ、指定から選ぶ。
5. ワールドとプレイヤーデータが新generationへ交換されることを確認する。
6. 最終確認で実行する。
7. reset開始を公開する。
8. システムが最終backupを作成・検証する。
9. 旧generationを保持する。
10. 新generationをstaging生成する。
11. ワールド読込を検証する。
12. MinecraftとEC2を停止する。
13. generationを確定する。
14. 新Seed、generation、backup IDを公開する。
15. 通常の`/mc start`で遊ぶ。

失敗時:

- backup失敗なら旧generationを移動しない。
- 新生成失敗でも旧generationを保持する。
- reset後に自動で遊べる状態へしない。停止状態で完了する。
- 過去へ戻す操作はrestoreとして分離する。

## 12. 初めてPackageを追加する

Phase 12以降。

### 共通

1. 対象Minecraft versionを固定する。
2. server種別とversionを固定する。
3. Java runtimeを確認する。
4. ローカルまたは検証用環境で構築する。
5. 起動、接続、停止、再起動を確認する。
6. backup対象とreset対象を確認する。
7. Package manifestを作成する。
8. archiveとchecksumを作成する。
9. 不変S3 pathへuploadする。
10. 検証Gameを作成する。
11. start/status/stop/backup/restore test/resetを確認する。
12. Templateを有効化する。

### Paper

- Paper buildを固定する。
- pluginsと設定を固定する。
- plugin固有データpathをbackup/resetへ追加する。
- 通常client互換性を記録する。

### MOD

- Fabric/Forge/NeoForge等のloaderを固定する。
- dependency MODを含める。
- client pack情報を記録する。
- server-only/client-requiredを明確にする。
- MODとPaperハイブリッドを初期Packageとして作らない。

## 13. EC2スペックを変更する

Phase 9以降。

1. Discord管理者または管理WebでGame詳細を見る。
2. 許可済みruntime classから選ぶ。
3. Java XmxとEC2 memoryの対応を確認する。
4. Gameが停止中であることを確認する。
5. 設定を保存する。
6. 次回start時、EC2 stopped状態でinstance typeを変更する。
7. READY後にmemory/performanceを確認する。

利用者に生のinstance typeや任意Xmxを入力させない。

## 14. OPを追加する

Phase 14以降。

1. Discord管理者が`/mc op add`を実行する。
2. Gameを選ぶ。
3. 起動中ならonline player、停止中なら過去参加者候補を表示する。
4. 必要ならplayer nameを入力する。
5. UUIDを正規に解決する。
6. OP levelを選ぶ。
7. 本人限定で最終確認する。
8. desired operator設定を更新する。
9. 起動中なら即時反映し、実反映を確認する。
10. 停止中なら次回起動時同期として表示する。
11. 結果を公開し、operation履歴へ保存する。

## 15. チャット連携対応Gameで遊ぶ

Phase 15以降。

1. 対応PackageのGameを通常どおり起動する。
2. Minecraft READY後にチャットsessionを開始する。
3. Game名、同期先、連携状態をDiscordへ表示する。
4. Minecraft内chatや有効イベントをDiscordへ送る。
5. chat bridge失敗時もMinecraft本体は継続する。
6. stop開始時に新規Discord→Minecraft受付を止める。
7. 未送信イベントを処理してsessionを閉じる。
8. Minecraft/EC2停止を継続する。

非対応Packageで無理に有効化しない。

## 16. システム管理者が障害を調べる

1. Discord表示と管理用CloudWatch alarmを確認する。
2. Operation IDを特定する。
3. Step Functions executionとcurrent stepを確認する。
4. SystemStateのDesired/Observedを確認する。
5. Lock ownerとexpiryを確認する。
6. 必要時だけSSM Session ManagerでEC2へ入る。
7. data volume、systemd、journal、runtime state、Minecraft logを確認する。
8. 実状態を修復する。
9. Reconcileを再実行する。
10. 原因と対応をDecision/incident記録へ残す。

DynamoDB値だけを手動で正常値に変更しない。
