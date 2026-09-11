# Targeted runtime contract / inactive-only migration

**状態: Proposed — repository実装・検証段階。production未適用。**
基準は `30b029295c3cd94d00fbfe1aacd0f60094d2f011`。Phase 8およびBACKUP安全性／隔離復元sliceのCompletedを変更しない。
D-096の承認対象はこの単一Game START/STOP契約と移行だけである。

## 選択と正本

| 情報 | 正本・今回の扱い |
|---|---|
| Game | 既存Games item `game-vanilla-main`。Admissionの既存認可・lifecycle検証を維持 |
| 保存対象 | 元Data EBS上の `/srv/minecraft/games/game-vanilla-main/server` 全体。移動・生成・新world参照なし。world内のファイル内容はEBSが正本 |
| 実行構成 | Git stage `host_runtime`。同じrendererがCompose/runtime.env/manifestを生成し、manifest SHA-256をCP環境とhost設定へ配布。Gameへ設定を複製しない |
| `runtime_id` | 既存の固定Compose実行枠 `wishicraft-host-runtime`。一回の起動ではない |
| `run_id` | 最初のSTART Operation ID。同Operation再送・途中起動の再開では維持。新しいSTARTが残存runtimeへ収束する場合も観測済みrunを採用する |
| `process_id` | 実container IDとDocker StartedAtのhash。再起動で変化する観測値で、別の永続管理台帳は作らない |
| 実行要求 | 既存Operationの追加 `runtime_target`。instance/Game/data_source/config_digest/run_idを条件付きで一度だけ固定。lease、status、timeoutは既存fieldを再利用 |
| host進行状態 | root EBSの `/var/lib/wishicraft/runtime/receipt.json`。targetとstarting/running/stopping/stopped。実現結果の証跡であり、Game選択の第二の正本ではない |

`runtime_target`はSTARTのset_desiredでEC2操作前に固定する。既存recordがあれば再選択せずconsistent readする。
RUNNINGの観測を採用する場合はreceiptのtargetを使用し、Git由来のGame/path/configと一致しなければ拒否する。
既にEC2 stoppedのSTOPでは架空の起動IDを発行せず、従来どおりDesired/DNSを収束させる。
STOP中の生存hostでは観測済みtargetが必須。resolverが別instanceを返した場合は再選択しない。

新world ID、generation変更、Package管理、new table、workflow、汎用event journalは追加しない。
単一保存directoryのままなので独立world IDはまだ必要ない。既存GameのgenerationやPackage fieldを今回の物理起動IDへ読み替えない。

## host境界と観測

SSM命令は `operation-v2 <base64 JSON>` の固定入口だけを使う。JSONはschema/action/operation_id/lease_idのみ。
任意shell、path、Minecraft commandを受け取らず、対象はOperationから読む。base64は認証ではない。認可は既存SSM IAM、固定host入口、現lease照合である。

hostはIMDSv2の実instance、root-owned設定、manifestと実artifactのhash、既存filesystem preflightを確認する。
`flock`を保持したままOperationとLocksをconsistent readし、RUNNING、type、対象Game、lease、timeoutを照合してから実containerのrun/Game/bind/image/environmentを検証する。
検証とsystemd/RCON操作は同じ排他区間に置く。待機中にleaseが変わった古いSSM命令は排他取得後の再照合で拒否する。
既に効果が始まった命令をlease喪失で遡って取り消す保証はない。後続host操作は同じlockを待ち、未解決receiptとsystemd遷移状態を越えて新runを始めない。
手動systemctl/docker操作による排他の迂回は通常契約の外であり、復旧時も実状態観測と個別承認が必要。

STARTはstartingをdurable記録してから起動する。Composeにrun labelを渡し、実container照合後にrunningとする。
START成功/DNS公開には従来のREADY/endpointに加え、観測receiptとOperationのtarget一致が必要。
STOPはexact containerへsave-all flushし、応答成功後にstoppingを記録してsystemdを正常停止する。
containerなし、unit inactive、25565/25575 listenerなしを確認してstoppedを記録する。確認前にEC2停止へ進まない。

heartbeatはrun_idとprocess_idを含む。既存instance/bootと合わせて無人時間の連続性を判断する。
新producerは実行receipt/process identity不明ならunknown/count不明にし、古い0人を維持しない。
AutoStopIntentとintent IDにもrun/processを含め、最終直接観測と照合する。旧recordの読み取りは可能だが、切替中の旧warningを新runへ引き継がない。

## 失敗・再開

| 失敗地点 | 残る状態・続行条件 |
|---|---|
| Operation target更新の応答喪失 | consistent readで完全一致した値だけを再利用。未確認ならSSM送信しない。別targetへの上書き禁止 |
| SSM送信の応答喪失・再送 | 同じOperation/targetを使用。hostで排他と現lease照合。新run IDで帳尻を合わせない |
| 起動途中・起動応答喪失 | startingとcontainer labelを観測。systemd activating中は待つ。正しいcontainerが稼働すれば同targetで収束できる。unknown artifact/bindは停止して診断 |
| 保存応答喪失 | stoppedとは扱わない。同じcontainerへのsave再試行は可能。stopping記録前なら停止済みと断定しない |
| 正常停止後の応答喪失 | stoppingが残る。同targetでcontainer/unit/listenerを再観測し、すべて停止していればstopped確定。force操作不要 |
| receipt書込み失敗・未知container | 外部効果の成否不明を保持。新runへの切替を止める。実container、systemd job、journal、receipt、Operation/leaseを照合してから限定復旧を判断 |
| root EBS紛失 | receiptを失うため通常操作はfail closed。Data EBSやSnapshotがあるだけで実行証跡を復元したとはしない。別hostへの自動採用はしない |

復旧ではまず同OperationがRUNNING/lease所有なら通常task再開で観測する。terminalなら旧命令を再送しない。
既存D-074 recoveryが必要なstale Operationはfresh observationと旧execution/SSM完了確認の後に扱う。
raw DynamoDB/receipt編集、予約削除、強制停止、別world生成は通常復旧手順に含めない。
未知の実データ損失を許容して成功扱いする経路はない。退避が必要な実データは削除せず保持する。

## 移行計画（未実行・GO対象）

1. caller/account/region、承認HEAD/CI、元Target/EBS、Game、Desired、Lock、Current Operation、関連workflow/SSM inventoryを再観測する。新旧のSTART/STOP/BACKUP作成処理が残存していれば切替しない。
2. STOPPED/HEALTHYで**normal BACKUPを一回**実行する。host変更後の初回STARTは実worldを書き得るため、移行直前の復旧点を確保する。今回未実証の新BACKUP経路も同時に実AWSで確認する。Snapshot completed/source/tag/provenance/Operation一致まで待つ。結果不明・provenance不明なら追加作成せず既存runbookに従い停止する。9月8日の復元済みSnapshotで代用しない。
3. Admission Lambdaを一時的にreserved concurrency 0にして新規操作の受付を止め、元設定を記録する。既存executionが全てterminal、SSMがterminalかつhost job完了であることを確認する。定期Reconcileの自然なObserved更新は許容する。受付停止は短い移行窓だけで、恒久maintenance基盤は作らない。
4. Target stackの**既存role policyのみ**を更新する。追加はOperations/Locks二tableのGetItem。instance/UserData/EBS/SG/attachment差分があれば停止する。続いて元Targetを保守目的でEC2起動し、Minecraft unit非自動起動を確認する。Desired STOPPEDとの一時不一致は保守証跡へ残す。公開DNSは変更しない。
5. `./tools/dev-env run -- python -m wishicraft.runtime_migration --instance-id <再確認済みexact Target ID> --output <新規directory>` で承認HEADからbundle生成。全ファイルhashとinstall.jsonを保存し、exact Targetの `/var/tmp/wishicraft-targeted-runtime-v1` へSSMで配送・read-back照合する。installerを実行する前にsource/owner/mode、旧artifact hash、unit inactive、全container/listenerなし、元EBS/mount一致を確認する。
6. 固定installerを実行。旧operation-v1を拒否入口へ先に置換し、他artifactをatomic replaceする。旧ファイルはroot上のpredecessor copyへ保持する。途中中断は同bundleの旧/新hashを照合して前進再開できる。未知hashを上書きしない。receiptが既に作成されていればinstaller再実行せず診断する。新operation-v2とheartbeat/probe、unit、runtime configの全hashを読み戻す。heartbeat timerは既存設定を維持する。
7. runtime inactiveのまま元Targetを正常EC2停止する。Control Planeだけをdeployする（code assetsとSTART/STOP環境設定）。既存BACKUP安全性修正を含む新しい基準からdeployし、旧BACKUPコードへ戻さない。definition/IAM/Lambda更新/環境allowlist/stack/alarmをread-backする。秘密を含む全environment dumpは禁止。
8. Admissionの元concurrencyを復元し、通常認可のSTARTを一回実行する。Operation frozen target、host receipt、実bind/image/run/process、READY、DNS、fresh heartbeatを照合する。通常STOPで保存・正常停止・EC2停止・DNS削除・STOPPED/HEALTHY・Lock/Current Operation解放を確認する。公開SWITCH/RESET、強制replay、長時間auto-stop E2E、隔離復元の再実行は含めない。

既存Targetを用いる理由は既存worldを移さず通常START/STOP契約を検証するため。今回のrepository準備では上記AWS writeを一切実施していない。
費用は通常BACKUPの30GiB EBS Snapshotと短時間の既存t3a.medium起動が増える。新host/volume、恒久service、Budget変更は不要。実請求はSnapshot増分と起動時間に依存する。

## 新旧混在と戻し方

| 組合せ | 扱い |
|---|---|
| 旧CP＋旧host | 移行前のAccepted実装 |
| 新CP＋旧host | v2入口がないため拒否。旧命令へのfallbackなし |
| 旧CP＋新host | operation-v1を明示拒否。新runtimeを旧STOPで停止しない |
| 新CP＋新host、旧heartbeat履歴 | 読み取りは可能。新producerの不明観測／新run/processによって無人連続性を断つ |
| 新receiptあり＋旧installer/codeへの戻し | 禁止。旧コードはtarget/receiptを理解しないため、コードだけ戻して完了にはできない |

最初の新runtime起動前であれば、受付停止・旧命令drain・unit/container停止を確認し、保存したpredecessorと承認済み逆差分で戻す選択肢がある。ただし自動rollbackはしない。
新target記録／receiptが生じた後は新契約のまま観測・正常STOPへ前進修復する。元worldを書き戻す必要がある場合は停止し、最新保護Snapshotから隔離copyを作る別の承認計画を作る。9月8日へ黙って巻き戻さない。

## 検証範囲と残る判断

boundary testsは本物のrenderer、Dynamo属性serializer、SSM payload、host authorize/apply、atomic receipt、heartbeat encode/decode、CDK環境からの実handler初期化を通す。process/AWS境界はsyntheticであり、本番のSSM/systemd/Docker/E2E実証ではない。
local DockerはCLI未導入。CIの既存固定runtime integrationは従来の保存／所有権境界の回帰を担い、新v2 host移行の実証とは区別する。
本番確認は手順8の通常START/STOPとidentity read-backに限定する。途中失敗試験、旧命令／process切替の否定系は境界testsで検証する。

承認対象はD-096、新host read権限、受付停止を含む上記移行と新BACKUP／通常START/STOP検証。
whitelist、Reset認可・同席player、cleanup保持policy、共有backup形式、Game/world拡張、SWITCH/RESET順序、管理Webは引き続き独立したProposed／未決事項である。

## Repository準備の証跡（2026-09-11）

[機械可読証跡](../evidence/2026-09-11-targeted-runtime-preparation.json)にpreflight時点、検証source hash、template比較を保存した。
最終local検証は896 tests、ruff check/format、mypy、Phase 1/Target/Control Planeの3 synthが成功。
比較は実deployed templateのread-only取得とlocal synthの構造比較であり、ChangeSet作成やdeployではない。
Control Planeは11 Lambda codeとSTART/STOPの2環境変数追加、Targetは既存role policyの二table GetItemのみ。追加／削除／instance更新なし。
preflightは2026-09-11 05:44:29 UTC、元Target stopped、元EBS attachment維持、SystemState STOPPED/HEALTHY revision 15、Lock/Current Operation/未終了Operationなし。
DNS absentは保存済みSystemStateからの確認であり、このpreflightでRoute 53を直接再照会したとは扱わない。
途中の中断後にprocess残存なしとログ完了を確認し、停止receiptと要求targetの不一致拒否を追加して最終validationを行った。
AWS write、v2実機試験、新BACKUPは未実行。CIと最終HEADはGitHubの当該commitを参照する。
