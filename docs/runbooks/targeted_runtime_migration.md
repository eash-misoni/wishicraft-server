# Targeted runtime contract / inactive-only migration

**状態: Completed — D-096 Accepted。2026-09-11 UTC、限定STOP復旧・前進修正・通常START/STOP二巡・受付復元・最終STOPPED/HEALTHYを実機確認済み。**
以下の途中BLOCKED／未実施記録は当時のcheckpointとして保持し、現在の結果は末尾のcloseoutを正本とする。
基準は `30b029295c3cd94d00fbfe1aacd0f60094d2f011`。Phase 8およびBACKUP安全性／隔離復元sliceのCompletedを変更しない。
D-096の承認対象はこの単一Game START/STOP契約と移行だけである。

## 現在の契約

対象・host境界・失敗再開の正本は[Data and Interface Contracts §0](../05_data_and_interface_contracts.md#0-production適用済みruntime契約d-096)。本書は移行手順と時刻付き実行証跡を所有する。以下の初期移行手順は実行履歴であり、次の二Game移行へ無条件に再実行しない。

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

## Production部分適用 — 2026-09-11 UTC、BLOCKED

[機械可読証跡](../evidence/2026-09-11-targeted-runtime-production.json)が今回の実測記録。適用sourceは `9635073232f9addbd240a55d99e0d1de841d73c7`（CI `34588237412` success）。承認基準f89c869からは承認記録のdocs差分だけで、bundleは承認時hashと一致した。以下は準備時の未実測事項を更新する実行結果であり、移行Completedではない。

- 最新normal BACKUPは一回成功。Operation `op-22df4706-b2b1-4758-a86d-5dace4334f8a`、Snapshot `snap-005ce340d03a42340`、復旧点 `2026-09-11T10:16:48.543Z`。completed・source/owner/metadata・SUCCEEDED・provenance二record一致を実SDK decodeと既存verify_sourceで確認。新BACKUP安全性経路の実AWS正常系を確認したが、応答喪失／replay／このSnapshot自体の復元試験は未実施。
- Admission元設定はUNSET。reserved concurrency 0とし、function timeoutを超えるdrain待ちとworkflow/SSM/Operation terminalを確認。BACKUP後の別STARTなし。現在も0を維持し、受付復元は未実施。
- 実productionからのTarget差分は既存roleのOperations/Locks二table限定GetItemだけ。deploy UPDATE_COMPLETE、実IAM/templateを照合済み。EC2/UserData/EBS/SG/attachment変更なし。CP予定差分は11 Lambda Code＋START/STOPのRUNTIME_CONFIG_DIGEST/RUNTIME_DATA_SOURCEであるが、**CP deployは未実施**。
- 元Targetを保守起動し、10:24:18にSSM `48c508e4-4137-4a44-8529-660bbbb98711` が旧artifact preflightでexit 1（UNKNOWN_ARTIFACT）。`/etc/wishicraft/host-runtime/manifest.json` は承認bundleでABSENTを期待したが、実際にはroot:root 0600の通常fileがあり、SHA256は `58218d144da8eb85fcda0bdf7383c6127896db11a7c5e93f3a781828f3bd300d`。他の照合artifactは一致。由来未確定のため、predecessor追加・上書き・installer実行へ進まなかった。
- 旧停止container `b7e7d79eb38e54f7b1b78a25dc27060f9f68f315f86dfe2fc83168a614983b62` は実在。固定image・Game/data bind、exited/ExitCode 0/OOMなし、unit inactive/static、listenerなし、新receiptなしを観測。9月10日のSAVE_CONFIRMED/GRACEFUL_STOP_CONFIRMED journalを保存した。world/player inventoryと書込み層の最終分類までは完了しておらず、**削除していない**。本番world保持の二巡検証は未実施。
- host上は `/var/tmp/wishicraft-d096-20260911/legacy-host.json` の診断証跡のみ保存。bundle配送／host更新なし。runtime inactive・SSM terminalを確認して10:25:55に通常EC2停止、10:26:46にcontrolled Reconcile。Target STOPPED/HEALTHY、DNSなし、Lock/Current/未終了Operationなし。元Data EBS identity/attachment/encryption・Game参照、元4 Snapshot/provenance不変、追加Snapshotは上記一件だけ。二table IAMは適用済みのまま残す。
- DesiredStoppedEc2Runningは保守起動に伴い10:25のmetricが1、10:26:53 ALARM。正常停止後10:30のmetricが0、**10:31:53 UTCに自然OK復帰**。ユーザーへの通知はこの保守期間の評価に対応する。alarm無効化・閾値変更・fake metricは行っていない。

再開には、既存manifestの安全な内容照合と過去適用artifactの対応を確定し、exact predecessorと更新bundle／testsをレビューする必要がある。観測hashだけを許可値へ追加しない。現在の受付0、旧host＋旧CP、追加済みIAMと新Snapshotを起点に再preflightし、BACKUPを別requestで再作成しない。受付再開・逆方向rollbackを手順の終了だけで実行しない。Phase 8 Completed、Phase 9未着手、その他再設計Proposedは維持する。

## Conditional GO / 旧manifest由来確認 — 2026-09-11 UTC

基準c44f20dの停止に対し、ユーザーが旧manifestの独立再現・実機照合、exact predecessor訂正と関連tests、条件成立後の既承認移行続行を承認した。無条件hash追加ではない。

`b3e27e1`のrendererと同commitのproject/stage設定（UID/GID 993、publish_minecraft_port=False）を独立に実行し、canonical JSON全byteのSHA256 `58218d144da8eb85fcda0bdf7383c6127896db11a7c5e93f3a781828f3bd300d` を再現した。portありの生成物とは一致しない。配置の根拠はPhase 2実データ移行runbook手順9のportless artifact導入、rendererのwrite_newによるmanifest生成、およびb56516fの実データ移行完了記録。Phase 5 upgradeは旧Compose `08c5cee…`を更新し、Phase 6 upgradeはruntime.env `271ce8be…`を`62c9bda…`へ更新するが、双方ともmanifestを置換しない。旧start/stopはCompose/envを使用し、既設v1.3 probeにもmanifest参照はない。このfileは生成時点の履歴artifactであり、現在Composeとのhash不一致をv2部分適用と扱わない。

10:50:52 UTC、exact TargetのSSM `04692e81-2d5e-4cf5-ba46-fa98d537bb80` で通常file・非symlink・root:root・0600・全byte・全schema/fieldの一致を確認した。全文を無条件出力せず、既知再構成値との一致だけを記録した。全15対象artifactの旧配置一致（新v2二fileは不存在）、新receiptなし、unit inactive/static、停止container同一、listenerなしを一度に照合した。Admission 0、未終了Operation/workflow/SSMなし、成功済みBACKUP以後の新Operationなし、Game/EBS attachment不変を再確認。Targetの実IAMも既適用policyと一致し、再deployしない。

manifest predecessorだけをABSENTから証明済みexact hashへ訂正する。新runtime semantics、bundle内新artifact内容、IAMは変えない。未知／欠損／owner／mode／symlink拒否、全件検証後の置換、旧file保存、部分適用後の同bundle再開、新receipt拒否、新manifestと新Compose/env対応を実installer境界で回帰検証する。既存BACKUP `snap-005ce340d03a42340` を再利用し、新BACKUPは作らない。host更新／container整理／本番二巡の成功はこの訂正だけでは主張しない。

### 一巡目STARTのpreflight失敗と同契約内の前進修正

修正HEAD e503530のCI成功後、旧container一件を削除し108 file不変を確認、host installer／旧file保存／11 Lambda codeとSTART/STOP設定deploy／受付UNSET復元まで完了。一巡目START `op-f662ecac-c9ce-4b97-9416-ffea7f16633f` は11:08:14 UTCにFAILED。新Composeの必須WISHICRAFT_RUN_IDをfilesystem preflightへ渡す前にCompose psが評価されたためで、実mount guard自体は成功した。receiptなし、containerなし、listenerなしをSSMで確認し、結果不明とは区別した。失敗Operationのreplayや別runによる成功偽装は行わない。

認可・対象固定後の同じrun IDをpreflight subprocessへ明示的に渡す限定修正を行う。Composeの必須値条件や対象照合を緩めず、新しいruntime semantics/IAMは加えない。実Docker fixtureも本番と同じ必須interpolationへ合わせ、未設定拒否とSTART/STOP各preflightでの解決を検証する。受付0へ再停止し、同一契約内の限定前進修正を検証後に適用する。

### 最終checkpointと再開承認対象 — 11:17 UTC

旧manifestは解決済み。productionはe503530の新host＋新CPであり、旧host/旧CPへの復帰は行っていない。旧停止containerは削除済み、旧fileはrootのpredecessor copyへ保存済み。STARTはFAILED、receipt・新container・listenerは存在しないことを確認した。安全な通常EC2停止後にReconcileを実施し、**実EC2 stopped／Desired RUNNING／Health DEGRADED／Admission 0**で停止する。DNS、Lock、Current Operation、未終了Operationなし。元EBS identity/attachment/encryption、全5 Snapshot/provenanceは不変。保守中の3 alarmは11:17時点でOKへ復帰し、START task/workflow失敗の2 alarmは同時点ALARMとして残る。閾値や通知を変更していない。

repoの前進修正は `daeb538e61ac260c5b790dc30444209b9b5cd319`。local 921 tests・ruff/format/mypy・CP synth、CI 34593137552のquality／実Docker／3 synth成功。最初のlocal環境ではwheel取得DNS失敗5件を916成功と分離し、その5件を再検証して成功した。修正後のfull 921 testsも成功。新Composeの必須run値欠落拒否と、認可済みrunによる実Compose ps、保存・STOP・新STARTをsynthetic Dockerで確認した。本番に修正を適用した証明ではない。

現行select_targetはEC2 stoppedならSTOPのruntime targetを要求しないため、通常STOPでDesiredを正規に収束できる。一方、受付0ではshared Admissionを呼べず、今回GOの「STOPPED/HEALTHYになるまで受付復元しない」と両立しない。これをraw Desired編集、terminal Operation replay、旧コードへのdowngradeで迂回しない。**この例外となる限定STOP受付を追加承認する必要がある**。これはmanifest調査の再承認ではない。

具体的な再開案（未実施）:

1. 元Target stopped、FAILED START、receipt/containerなし、元EBS、DNS/Lock/未終了処理なしを再照合。Discord Command Lambdaの元concurrencyを記録し一時0＋drainとして、shared Admissionの限定受付中にDiscordから別STARTが入らないようにする。この追加の受付制御も承認対象とする。
2. Admissionを元UNSETへ一時復元し、shared AdmissionのADMIN経路からcanonical STOP一回だけを実行。EC2 already-stopped分岐でDesired STOPPED/HEALTHYへ収束させる。FAILED STARTを再利用しない。結果不明なら再送・別Operationを行わない。完了後はhost修正窓のためAdmission 0へ戻す。
3. 既存Targetの保守起動、全artifact・receipt不存在・unit/container/listenerを確認。配布済み新hashをexact predecessorとするreviewed-forward-bundleで、operation-v2だけを `abecc64c…` から `aaf0233b…` へ更新する。新manifest/config/Compose/worldは変更しない。installerのCompose preflightには記録済みfailed STARTのrun値を環境として渡すだけで、そのOperationを実行・再送しない。旧v2 file保存・全件照合・atomic replaceを維持する。bundle全hashは既存JSON証跡のpreflight_fix_not_appliedへ保存済み。
4. 保守停止後、CPの11 Lambda codeだけを同じ修正HEADへ更新（現在e503530から環境/IAM差分なし）。read-backとReconcileでSTOPPED/HEALTHYを確認してAdmission UNSETとDiscord Commandの元設定を復元する。
5. 失敗一件を履歴に残したまま、新Operationによる通常START/STOP二巡を検証する。今回まだ一巡も成功していない。新BACKUP／Snapshot作成・raw修復・逆方向rollbackは不要。

この案の受付例外を未承認のまま実行しない。旧host/旧CPへ戻して受付だけ再開する案は、既に新runtime_targetが保存され旧containerも削除済みのため、単純なコード差し戻しでは採用しない。

## Production closeout — limited STOP / forward migration

2026-09-11の追加GO（基準 `d6f3b67adf828e56a3460d1ab0c4002d19b22af4`）で、11:17 checkpointの限定受付例外を承認された。適用codeは `daeb538e61ac260c5b790dc30444209b9b5cd319` と同一で、基準HEADまでの後続差分は文書のみ。旧manifest調査や旧container削除、BACKUP、Target IAM deployは繰り返していない。

### 復旧STOPと受付

11:38 UTCにcanonical caller/account/region、実EC2 stopped／Desired RUNNING／DEGRADED、FAILED START、DNSなし、Lock/Current Operation/未終了workflow・SSMなしを再観測した。適用済みe503530のSTOP code hashとdefinitionを照合し、`AlreadyEc2Stopped → RenewBeforeDnsDelete` がhost STOP／EC2 Stopを呼ばないことを確認した。

Discord Commandの元concurrencyはUNSET。11:40:12に0へ変更し、Command 10秒／Admission 30秒のtimeoutを越えてdrainした。直前8分の両LambdaにSTART記録なし、Evaluatorは各呼出しのEND/REPORTと `CONTROL_PLANE_UNSAFE` を確認。heartbeat stale/unknown、empty_sinceなしで非eligible、既存intentはterminalまたは過去のSTOP_REQUESTEDであり、未確定なAdmission要求はなかった。既知の通常呼出し元はDiscord CommandとEvaluatorの同期RequestResponse、今回のoperator ADMIN。Admissionを開くこと自体がSTOP-only制限になるとは扱っていない。

11:40:52にAdmissionだけUNSETへ限定復元し、固定key `d096-d6f3b67-forward-recovery-stop` でADMIN STOPを一回送信した。Operation `op-796eca37-a1ff-457f-9d74-b74904c1d391`、execution `arn:aws:states:ap-northeast-1:385526546525:execution:wc-dev-stop:op-796eca37-a1ff-457f-9d74-b74904c1d391` がSUCCEEDED。fresh Reconcile、owned Desired STOPPED、既停止分岐、DNS不存在処理、最終Reconcile、Lock解放まで進み、RunHostStop／StopEc2は実行していない。限定窓の新Operationはこの一件だけ。11:42:06にAdmissionを0へ戻した。

### 前進修正

11:42:31に同じTargetを保守起動し、全10 artifactのexact predecessor、root owner/mode/type、receipt/container/listenerなし、unit inactiveを照合した。旧inventoryの108ファイルについてhash・owner・mode・mtimeが変わっておらず、既存BACKUP `snap-005ce340d03a42340` を継続使用した。

承認bundleを新規 `/var/tmp/wishicraft-targeted-runtime-forward-v1` へ配送し全hashを検証。旧配送directoryは保持した。byte同一のinstaller moduleへ今回のbundle directoryだけを渡し、過去FAILED STARTのrun値はCompose解決用の環境contextだけに使用した。Operation再送・receipt作成は行っていない。

`operation-v2` は `abecc64cbb007c699451bb4c120760d4b33d0909c23de0af3ef0f29f730bc7f4` から `aaf0233b0d4ad73c49aea3d7525413de62de27f2df880423a8f692569f9f61ee` へ更新し、旧fileを `predecessor-9.artifact` に保存した。他artifactはcanonicalとして不変。install.json hashは `beccd97de65fdf6cc62a0c7d7d9b10f9d8f88b9c6533b41e03af33e731b0e847`。同じhost排他、全件事前検証、atomic replace、receipt不存在条件を維持した。

11:45:26の保守正常停止後、Control Planeを保存済み検証assemblyからdeploy。実production差分は11 Lambda Codeと対応するCDK asset-path metadataだけで、IAM/config/State Machine/resource lifecycle差分なし。UPDATE_COMPLETE、全11 Lambda Active/更新成功・実code SHA・target設定・template全一致をread-backした。Target IAMは既存heartbeat権限と区別してOperations/Locks限定GetItemを確認し、再deployしなかった。

両Lambdaのconcurrency 0はdeploy中・後も維持した。11:48:22のfresh STOPPED/HEALTHY・DNSなしを確認後、11:48:45にAdmission、11:48:51にDiscord Commandを元UNSETへ復元した。

### 通常二巡の実証

| 巡 | START Operation / run | 実container | STOP Operation |
|---|---|---|---|
| 1 | `op-1af2bda9-4227-47d4-9d65-26cc4fb89482` | `9620d3a51b75e4574eb09d9805d0bf3b1b51c355a5ebec36bcc0435d865b455f` | `op-d843a03a-d7ef-4a72-b4cc-8a19afb5e2c5` |
| 2 | `op-2f5287ab-b435-46e8-b415-46f9c5320c05` | `dfcfecebb08fd49c35ba76d057ac3d67edea26b8b4f3689359f1f7dc84cff224` | `op-76445f1a-8c4b-4ca4-b9e7-baa9e8f137d1` |

四Operationともshared Admission ADMIN経路でSUCCEEDED。target、receipt、実Compose project/service、Game/run label、固定image、data bind、RUN_ENV、READY、DNS、fresh heartbeatを照合した。preflightの必須run条件を緩和せず、認可済みrunをsubprocessへ渡す修正を通って起動した。

二巡とも既存 `world/level.dat` とplayer dataを確認し、同じGame/data pathを使用した。player file hashは二巡で一致。通常起動・保存で更新されるworld/log全体のbyte一致や、人間による建築物・所持品の目視確認は主張しない。本番へ試験値を追加していない。

STOP時には別のread-only SSM観測で、同じtargetの `running → stopping → stopped`、exact container/StartedAt、save_confirmed、removal_ready、unit inactive/Result=success、container/listener不存在、world残存を保存した。force/volume/pruneは使用せず、その後通常workflowがEC2停止・DNS削除・最終HEALTHYまで収束した。

二巡目の新bootでは旧stopped receiptが観測できたが、process/empty_sinceはnull。その後新run/processへ変わり、empty_sinceは11:58:27から始まった（一巡目は11:51:32）。AutoStopIntentsは全件不変で旧予告の採用・新規予告・SCHEDULE STOPはなかった。長時間自動停止の再実証とは区別する。

### 最終状態・失敗・限界

12:02:13 UTC最終観測: STOPPED/HEALTHY、DNS/Lock/Current Operation/unfinished Operation/running execution/nonterminal SSMなし。元Data EBS identity/attachment/encryption、Game参照、既存5 Snapshot/provenanceを保持。今回のcontinuationで新BACKUP/Snapshotは0。移行全体の新保護Snapshotは先行取得済みの一件のみ。両受付UNSETとhistorical FAILED START `op-f662ecac-c9ce-4b97-9416-ffea7f16633f` の完全不変も確認した。

41 alarmは全件OK。保守中のDesired STOPPED/EC2 runningとruntime unknown、実START失敗のtask/workflow error、その後のDesired RUNNING/EC2 stoppedの不一致を別原因として記録した。START failure alarmは11:24、DesiredRunningNotReadyは11:46:22、最後のDesiredActualDivergenceは11:56:31 UTCに自然復帰。閾値・通知・metricを変更していない。

今回の開始時SSO期限切れは人間の再ログインで解消した。read-only補助parserではCDK asset metadataと既存heartbeat GetItemを区別するassertion不足を修正したが、deploy差分やIAMを変更して通したものではない。実host修正／通常二巡には新しい失敗や強制処理はなかった。前のmanifest停止とFAILED STARTの履歴・証跡は保持している。

実装validationは921 tests、ruff/format/mypy、3 stack synth、実Dockerの必須run・保存・STOP・新run起動を含むCI成功。local Docker CLIは未導入でCI実証と分離する。強制replay、故障注入、30分auto-stop E2E、隔離復元再実行、managed Lambda SDK version実測は今回行っていない。Phase 8 Completedを維持し、Phase 9全体、SWITCH/RESET、その他Proposed再設計へ進んでいない。

完全なidentity・SSM command・execution・hashと時刻は[既存production evidence](../evidence/2026-09-11-targeted-runtime-production.json)の `limited_stop_forward_continuation` を参照する。前のcheckpointはhistoricalとして残す。
