# Targeted runtime contract / inactive-only migration

**状態: Accepted — 2026-09-11ユーザーGO。production移行・実機検証は未完了。**
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
Compose stopは停止済みcontainerを残すため、その後に**確認済みexact IDだけを `docker rm <64桁ID>`** で削除する（Accepted A案）。
保存成功後のstopping receiptにcontainer ID、StartedAt、save_confirmedをfsync保存する。同じhost排他下でproject/service、Game/run/bind、固定image/env、同じStartedAt、exited/ExitCode=0/OOMなし/errorなし、unit inactive/Result=success、listenerなしを再照合する。
固定vanillaの `/image/scripts/start`、WorkingDir `/data`、追加commandなし、実world/level.dat、server.propertiesの `level-name=world`、data外へ向くsymlinkなしを確認する。`/data`配下の別mountは既存の2 RCON一時file bind以外を拒否する。world/player/configはData EBSのbindに残し、書込み層を保存先にする構成は削除しない。
削除直前に同receiptへremoval_readyをdurable記録し、削除後にcontainerなし、unit/listener停止を再確認してstoppedへ進む。保存・停止・削除・receipt更新を同じflock内で行う。停止済みcontainerがあるのにstopped receiptだけをprobeが報告することも拒否する。
停止container保持案Bは次回STARTで旧run削除とその再開状態が必要になるため採らない。STOPで完結させれば次のSTARTは新Operation/runのcontainerを作れる。停止途中のreceiptからSTARTで再起動することは禁止する。
force removal、volume削除、prune、world削除、identity不明containerの自動cleanupは行わない。root権限で排他を迂回する操作まで防ぐ保証ではない。確認前にEC2停止へ進まない。

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
| 正常停止後の応答喪失 | stoppingとsave済みexact ID/StartedAtが残る。同じ停止containerの終了結果・bind・unit/listenerを再観測して削除へ進む。異常exitや別processなら保持して診断 |
| 削除前／削除応答喪失 | removal_readyとexact IDが残る。存在すれば同じ全検証後にそのIDだけrmを再試行。不存在ならdurable removal_readyを根拠に停止状態を再確認しstoppedへ収束。単に検索で見つからないだけで、削除意図のないstoppingを成功にしない |
| receipt書込み失敗・未知container | 外部効果の成否不明を保持。新runへの切替を止める。実container、systemd job、journal、receipt、Operation/leaseを照合してから限定復旧を判断 |
| root EBS紛失 | receiptを失うため通常操作はfail closed。Data EBSやSnapshotがあるだけで実行証跡を復元したとはしない。別hostへの自動採用はしない |

復旧ではまず同OperationがRUNNING/lease所有なら通常task再開で観測する。terminalなら旧命令を再送しない。
既存D-074 recoveryが必要なstale Operationはfresh observationと旧execution/SSM完了確認の後に扱う。
raw DynamoDB/receipt編集、予約削除、強制停止、別world生成は通常復旧手順に含めない。
未知の実データ損失を許容して成功扱いする経路はない。退避が必要な実データは削除せず保持する。

## 移行計画（承認済み・実行結果は別記）

1. caller/account/region、承認HEAD/CI、元Target/EBS、Game、Desired、Lock、Current Operation、関連workflow/SSM inventoryを再観測する。新旧のSTART/STOP/BACKUP作成処理が残存していれば切替しない。
2. STOPPED/HEALTHYで**normal BACKUPを一回**実行する。host変更後の初回STARTは実worldを書き得るため、移行直前の復旧点を確保する。今回未実証の新BACKUP経路も同時に実AWSで確認する。Snapshot completed/source/tag/provenance/Operation一致まで待つ。結果不明・provenance不明なら追加作成せず既存runbookに従い停止する。9月8日の復元済みSnapshotで代用しない。
3. Admission Lambdaを一時的にreserved concurrency 0にして新規操作の受付を止め、元設定を記録する。既存executionが全てterminal、SSMがterminalかつhost job完了であることを確認する。定期Reconcileの自然なObserved更新は許容する。受付停止は短い移行窓だけで、恒久maintenance基盤は作らない。
4. Target stackの**既存role policyのみ**を更新する。追加はOperations/Locks二tableのGetItem。instance/UserData/EBS/SG/attachment差分があれば停止する。続いて元Targetを保守目的でEC2起動し、Minecraft unit非自動起動を確認する。Desired STOPPEDとの一時不一致は保守証跡へ残す。公開DNSは変更しない。
5. `./tools/dev-env run -- python -m wishicraft.runtime_migration --instance-id <再確認済みexact Target ID> --output <新規directory>` で承認HEADからbundle生成。全ファイルhashとinstall.jsonを保存し、exact Targetの `/var/tmp/wishicraft-targeted-runtime-v1` へSSMで配送・read-back照合する。installerを実行する前にsource/owner/mode、旧artifact hash、unit inactive、元EBS/mount一致を確認する。旧STOPの停止containerがあれば下記「移行専用の旧container整理」を先に実施し、全対象container/listenerなしにする。未知containerでは停止する。
6. 固定installerを実行。旧operation-v1を拒否入口へ先に置換し、他artifactをatomic replaceする。旧ファイルはroot上のpredecessor copyへ保持する。途中中断は同bundleの旧/新hashを照合して前進再開できる。未知hashを上書きしない。receiptが既に作成されていればinstaller再実行せず診断する。新operation-v2とheartbeat/probe、unit、runtime configの全hashを読み戻す。heartbeat timerは既存設定を維持する。
7. runtime inactiveのまま元Targetを正常EC2停止する。Control Planeだけをdeployする（code assetsとSTART/STOP環境設定）。既存BACKUP安全性修正を含む新しい基準からdeployし、旧BACKUPコードへ戻さない。definition/IAM/Lambda更新/環境allowlist/stack/alarmをread-backする。秘密を含む全environment dumpは禁止。
8. 新host／CPのhash/config一致、実EC2 stopped／DNSなし、必要なcontrolled Reconcileでfresh STOPPED/HEALTHYを確認した後、Admissionの元concurrencyを復元し（元が未設定なら未設定へ戻す）、通常認可のSTARTを一回実行する。Operation frozen target、host receipt、実bind/image/run/process、READY、DNS、fresh heartbeatを照合する。通常STOPで保存・正常停止・exact container削除・stopped receipt・EC2停止・DNS削除・STOPPED/HEALTHY・Lock/Current Operation解放を確認する。続けて新Operationで通常START→STOPをもう一巡し、異なるrun/containerでも同じworldが維持されることと最終STOPPED/HEALTHYを確認する。公開SWITCH/RESET、強制replay、長時間auto-stop E2E、隔離復元の再実行は含めない。

既存Targetを用いる理由は既存worldを移さず通常START/STOP契約を検証するため。今回のrepository準備では上記AWS writeを一切実施していない。
費用は通常BACKUPの30GiB EBS Snapshotと短時間の既存t3a.medium起動が増える。新host/volume、恒久service、Budget変更は不要。実請求はSnapshot増分と起動時間に依存する。

## 移行専用の旧container整理（承認済み・実在時のみ）

実hostに停止containerが残っていることは今回未実測。installerの「`docker ps --all`で対象projectが空」というpreconditionは維持する。旧run label/receiptを省略するv2 fallbackは作らない。

受付停止・旧execution/SSMの完了確認後、exact Target上でinstallerと同じ `/var/lib/wishicraft/runtime/lock` をflockし、次の一回限りのoperator整理を行う。新しいv2 receiptがあればこの旧host手順を適用しない。

1. `docker ps --all --no-trunc`でinventoryを採取。対象はproject `wishicraft-host-runtime` / service `minecraft` の**一個の64桁ID**を固定する。全host inventoryに説明できないcontainerがあれば止める。旧operation-v1/stop-v1、Compose、runtime.env、unit、mount guardのhash/owner/modeを既存Phase 6・8.1適用証跡と照合する。生成した新artifactを旧artifactの根拠にしない。
2. exact IDのinspectをメモリ内で検証する。期待image digest、旧Game/data labels、`/data`の元Game bind、固定 `/image/scripts/start` / WorkingDir `/data`、command overrideなし、未知のnested mountなし、新run labelなしを要求する。旧STOP Operationの成功と `wishicraft-stop` journalのSAVE_CONFIRMED/GRACEFUL_STOP_CONFIRMED、該当containerのStartedAt/FinishedAtを照合し、保存・正常停止の根拠がなければ削除しない。unit inactive、Result success、container exited/ExitCode=0/OOMなし/errorなし、25565/25575 listenerなしを要求する。
3. Data EBS/mount identity、world/level.dat・playerdata・設定の存在を確認する。固定vanillaの保存先がbind内にあり、外向きsymlinkがないこと、`docker diff <exact ID>`に保存すべき未知データがないことを確認する。必要データが書込み層だけにある疑いは診断へ戻す。推測で不要分類しない。必要なworld/playerはEBSに残し、safe inspect projection（ID/image/labels/mounts/stateのみ）、STOP journal/log、diff、data inventory/hashをroot-owned 0600の新しい証跡directoryへ保存する。Config.Env全文やRCON設定の内容は出力しない。
4. 同じ排他内でID・全preconditionを再観測し、削除予定ID・image・StartedAt/FinishedAt・証跡hashをcheckpointへfsync保存してから、**`docker rm <照合済みexact ID>`だけ**を一回実行する。`--force`/`--volumes`/Compose down/pruneは禁止。実行直前にcontainerがrunningなら通常rmも拒否する。完了後、exact IDとprojectの不存在、unit/listener停止、元data inventory不変を照合してcheckpointを完了にする。その後だけinstallerへ進む。

削除応答が不明なら新しい対象を選び直さない。記録したexact IDを`docker ps --all --no-trunc`の成功応答で再照合し、存在すれば同じpreconditionで再開、不存在なら削除予定checkpointと全停止条件を確認する。inspect通信失敗を不存在にしない。別ID出現、identity不一致、保存根拠不足、削除範囲拡大は停止して報告する。cleanup対象はこの実行containerだけであり、image、Docker volume、Data EBS、world、Snapshot、診断証跡を削除しない。

この手順のexact container削除と、通常v2 STOP内のexact container削除、および二巡目のSTART/STOPが前回計画から追加されるproduction承認対象である。今回のrepository修正では実行しない。

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
local DockerはCLI未導入。CIの既存固定runtime integrationはSETUP_ONLYによる所有権／設定境界の回帰であり、v2停止・再起動の実証ではない。
追加の `tests/integration/targeted_runtime_docker.py` は同じ固定imageでsynthetic Minecraftを実起動し、本物のhost apply/inspect/対象検証/RCON/save/Compose stop/rmを接続する。Compose stop直後に同IDが非稼働で残ること、STOPの削除とreceipt、新run起動後のscoreboard値42、world/sentinel保持、実rm後の応答喪失からの収束を確認する。AWS/IMDS/filesystem guard/secret配送とsystemd本体は代替境界であり、実AL2023 unit/SSM/本番移行の証明ではない。人間playerの接続確認ではない。
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

CI初回（541e55b）は895 tests成功／bundle test 1件失敗。浅いcheckoutに基準commitが存在しなかったため、quality jobでGit履歴を取得する設定へ修正した。predecessor照合やtestをskipする変更はしていない。移行bundle生成には基準commitを保持したcheckoutを使用する。Dockerの既存固定runtime integrationは初回CIでも成功した。

## 停止container限定是正（2026-09-11、Proposed）

承認前レビュー基準 `b836f022fd3f9dbccf1ab93b4ffa44fdd01348d1` に対し、stop stubを「非稼働だが残存」へ直すと既存testがSTOP_RESULT_UNKNOWNで失敗した。旧stubのcontainers.clear()はDockerのstop semanticsを再現していなかった。過去896 tests成功と旧Docker integration成功を、新v2停止契約の実証として扱わない。
根拠は [Docker Compose stop公式仕様](https://docs.docker.com/reference/cli/docker/compose/stop/) と [container rm公式仕様](https://docs.docker.com/reference/cli/docker/container/rm/)。stop.sh/serviceはそのまま維持し、adapterだけがsave/終了証拠を所有して削除する。

bundleは旧Compose/runtime.envのPhase 6適用済みhashを直接固定する。加えて、D-094で「既設v1.3 probeは更新しない」とした実配置と、基準Gitにあるv1.4 probeの相違を訂正した。既設probe predecessorはPhase 8.1 commit `884247c0ad00bd4d410634b1b77d33f20f7dec99` の `2d431e56…` であり、CP転送用v1.4の `0efcf7e4…` ではない。installerは実hostの完全hash照合で未知配置を拒否する。現在のhostを今回read-backしたという意味ではない。
新bundleと基準bundleの全hashは限定是正の機械可読証跡に記録する。新config_digest/Compose/runtime.envは本是正では変えない。IAM、workflow、runtime image、Game/data配置も本是正による追加変更なし。CPがpackageするprobeのcode assetは新hashになるため再synth結果を承認HEADへ合わせる。

限定是正の[機械可読証跡](../evidence/2026-09-11-targeted-runtime-stop-remediation.json)に全bundle hashと比較を保存した。local full validationは913 tests、ruff check/format、mypy、3 synth成功。前案からのtemplate差分はControl Planeの11 Lambda code assetのみ、Target/Phase 1は差分なし。今回AWS照会・writeは実施していない。CIの実Docker結果は当該commitのjob結果で確認する。

実Docker初回CI `705d8c3` はCompose stop後の同ID残存まで確認し、PERSISTENCE_UNPROVENで削除前に停止した。追加した永続化検証が旧shim `/start` をentrypointと仮定していたためで、固定releaseの[公式Dockerfile](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/Dockerfile)の `/image/scripts/start` に一致させた（許可対象を広げるfallbackではない）。synthetic player directoryも、既存復元証跡で確認済みの26.2配置 `world/players/data` を使用する。失敗したCIを成功へ補正せず、新commitの実Dockerで再検証する。

訂正後commit `52ac771` の[実Docker CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/34578767884/job/103197230256)は成功。異なる2 containerでCompose stop直後の残存、ExitCode=0/OOMなし、adapterによる削除、stopped receipt、新runで保存済みscoreboard値42、worldとsentinelの保持、実rm後の応答喪失からの収束を確認した。local修正後full validationも913 tests、lint/format/mypy、変更対象Control Plane再synth、新bundle生成が成功した。未変更のTarget/Phase 1 synthは直前成功結果を再利用する。これはsynthetic data上のDocker境界の実証であり、実systemd/SSM/production移行は未実施である。

実装commit `52ac7717371c5db1c0c93b90b24dbe3299545073` のCI `34578767884` はquality／host-runtime-integrationともsuccess。以降の証跡確定commitに対するCIはGitHubの当該HEADと照合する。D-096はProposedのまま、上記追加container操作を含む移行GO前で停止する。

## Production実行承認 — 2026-09-11

ユーザーは基準HEAD `f89c869cc613e9530e0e16c4d455feb3073c571a` のD-096と停止container A案をGOした。上記手順をそのまま実行正本とし、設計Acceptedを移行Completedとして先取りしない。
BACKUP後に別のSTART／書込みが入っていれば最新保護と断定しない。受付停止は既存命令取消しではなく、workflow/SSM/host jobの完了を別に観測する。CP deploy前後もconcurrency 0をread-backし、新旧整合とfresh STOPPED/HEALTHY確認後だけ元設定へ戻す。
二巡はshared Admissionを通し、正規起動・保存によるファイル更新を許容しつつ同じ既存worldの保持を確認する。本番scoreboard変更、強制replay、故障注入、長時間auto-stop／隔離復元再試験は追加しない。実行中のcheckpointと最終証跡で結果を確定する。
