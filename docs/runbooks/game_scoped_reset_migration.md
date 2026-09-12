# Game-scoped Reset 適用準備（D-098 Accepted、適用中）

**2026-09-12ユーザーGO。設計・B限定policy・本runbookの操作を承認済み。production適用、二回の隔離復旧、一般公開の成功はそれぞれ証跡で確定する。**
利用者policy・正本の責務は[設計](../reviews/game_scoped_reset.md)。D-097を再実行しない。

## 一括承認で決める対象

- 推奨policyはPlayer/Admin・明示確認・観測0人、外部BACKUPを毎回待たない、旧managed 3個＋永久legacy anchor、free ≥ max(4 GiB, source×2)。last-observed-emptyのraceとEBS喪失時の損失を承認対象にする。
- Aは非対応を維持。試験Gameの第一候補はBだが、既存Bを破棄可能と扱わない。**Bの現在worldを永久anchorとして保持して新領域へResetする許可と、固定seedの具体値 `0` を明示承認する必要がある。** 不承認なら別Game追加を自動で行わず、対象を再決定する。
- `config/reset-dev.json`は空。承認した宣言だけを固定し、host manifest/CP RESET_POLICIES/Discord choicesへ同じ値を渡す。曖昧なdefault seedは使わない。
- cleanupコードのproduction到達は、以下の復旧確認後に限る。未検証を隠してデータ削除へ進まない。

## 事前保護と最小の隔離復旧

保護窓はユーザーGOにより前倒しする。元concurrencyを記録しCommandを0へ、既存要求・他callerをdrainしてからoperator BACKUPを一回実行する。成功後Admissionも0へしてdrainし、隔離復旧へ進む。

まずcanonical caller/account/region、HEAD/CI、元Target/EBS、A/B、受付、Operation/Lock/SFN/SSM、7 Snapshotとprovenanceの現在値を再照合する。準備時の値を将来の実測にしない。
移行直前の停止中shared-volume BACKUPを一回取得し、completed/owner/source/tags/recovery digest/provenance pairを確認する。過去の9月8日/12日Snapshotは最新保護の代替ではない。

既存[隔離復元runbook](backup_safety_isolated_restore.md)の一時stack、exact resource receipt、read-only初期mount、固定runtime、SSM localhost接続、Retain volume cleanupを再利用する。
元EBSやA/Bへの上書き復元はしない。権限に本番table書込み、DNS/Discord/heartbeat経路を含めない。TCP443 egressはdomain allowlistではない。

追加で確認する範囲:

1. source Snapshotとv2復旧JSON/digest、A/Bの定義・path・固定runtimeの対応を確認する。
2. 隔離copyのAだけを別の一時領域へ抽出し、Bの全file inventoryが変わらないことを確認する。元volume全体やSystemStateを戻す方法で代替しない。
3. 固定runtimeで抽出Aを起動・保存・正常停止・再起動する。人間目視と自動のplayer data存在確認を分ける。
4. 別の隔離fixtureへ今回のReset所有記録/current_idを適用し、新world準備、初期化、保存・再起動、owner chainからの復旧を検証する。実A/BをReset試験用に変更しない。
5. この確認が成功するまではproduction Reset/旧world削除へ進まない。失敗copyと証跡は保持する。正常cleanupは保存・正常停止・unmount後、今回のexact IDだけを対象にする。

## 配布順序と中断

1. 最新保護後にCommand/Admissionの元concurrencyを記録し両方0、既送信要求・workflow/SSM/host jobをdrainする。0を完了証明にしない。
2. 承認policyをGitへ固定しvalidation/CIを照合。`python -m wishicraft.reset_migration --policies <固定宣言> --output <新規root>`でexact bundleを生成する。
3. exact Targetを保守起動。Minecraft/DNSは起動せず、実host全artifactとstopped receiptをbundle predecessorへ照合。D-097旧container整理は再実行しない。
4. bundle installerで旧fileを保存しatomic replace。同bundleの部分適用は新/旧hashだけ許容。未知hash、receipt差、container残存では停止する。A/B data directory、whitelist/propertiesは変更しない。
5. 保守停止後、`two_games=true reset=true`のControl Planeだけをdeploy。Reset workflow、限定IAM/code/config/filter/alarmをread-backする。Target stack/IAM、EBS、SGは変更しない。
6. Reset commandは既存D-097 bodyへのpure extensionを生成して明示登録。設定一致、停止/DNSなし、fresh HEALTHY、所有なしを確認してAdmissionだけを限定再開する。Commandは0を維持し、一般利用者からResetが増える窓を作らない。他のAdmission callerが非eligibleで既送信要求がないことを確認する。

新Game参照を書いた後は旧CPへ単純downgradeしない。新hostとの混在中は受付を閉じる。
途中でcommand IDや参照CAS結果が不明なら同じidentityをread-backし、別request/world/seedに置き換えない。
current_id確定後に起動が失敗した場合、選択先は新領域のままである。実runtime/receipt/未終了命令を確認し、通常START/STOPで扱える既知の対象だけに収束させる。
raw Games/receipt/Lock編集や未知領域の削除を復旧手順にしない。既存recovery条件で扱えない状態では保持して報告する。

### 常設probeの配布是正（未適用）

host更新対象は7から8 artifactへ増える。追加先は `/usr/local/libexec/wishicraft/host-runtime-probe.py`、root:root・0755・通常file・symlinkなし。旧hashは `eb85d2d9cc77c818c3d98fb1234e28f37a0f7ec0e239ccf3604708b54ea74c46`。
D-096の適用source `e503530985fcc3099cc21b12cf2a83e9db72ae1c` の生成物を再現し、[適用証跡](../evidence/2026-09-11-targeted-runtime-production.json)の `limited_stop_forward_continuation.host_forward.preflight.proof.all_exact_predecessors` と照合した。D-097 bundleはprobeを変更していない。これは保存済み実測の根拠であり、適用直前の実host照合は省略しない。
新hashと全bundle hashは[準備証跡](../evidence/2026-09-12-reset-preparation.json)のapproval_candidate.bundleを正本とする。欠損・未知hash・owner/mode/type不一致は全artifact置換開始前に拒否する。旧probeはreset-v1/predecessor-7.artifactへ保存し、atomic replace・同bundle再開を使う。
生成installerの保存namespaceもplanの `reset-v1` と一致させる。既存汎用installerの許容namespaceは拡張しない。

Reconcileは同梱probeをstdin実行するだけで常設fileを更新しない。配布後fileの全byte hashをCP artifactの `wishicraft/artifacts/host_runtime_probe.py` と照合する。heartbeat producerとruntime_heartbeat moduleは適用済みソースと現行ソースが同一で、既存のrun/processによる継続性判定が十分なため再配布しない。その他のReset常設helperは既存bundle対象であり、新しい配布経路は追加しない。

## 承認後E2Eとcleanup release

Discord Commandを閉じたoperator限定窓で対象Bを通常STARTし、Game/run/bind/READY/heartbeatを確認する。選択A/別Game稼働・非対応AへのReset、confirmなし・positive/unknown人数の拒否は主にboundary testsを根拠とし、本番故障注入は不要。

承認されたBで`fixed`と`new`を各一回。Operation固定source/target/seed、同じinstance/boot、保存・正常停止・removal、既存B anchor保持、新worldのREADY、新run/processとempty_since/予告非継承を照合する。所要時間はsource停止とdestination READYの実時刻で測る。Aは比較対象として配置/参照を保持し、本番scoreboardを追加しない。

fixed/newの各Reset後に、Reconcile/READYとは別に、**常設producerから実heartbeat tableへの配送**を確認する。同一Game・同一bootのままOperation/receiptの新run/processとfresh heartbeatが一致し、known zeroから新empty_sinceが始まり、次heartbeatでその時刻が継続すること、旧runのAutoStopIntent/予告を採用しないことを確認する。producerの実行結果・時刻と実itemを証跡に残し、fake item・timestamp編集・Reconcile成功だけで代替しない。positive/unknown時は無人判定を成立させない。常設probeの不一致が残れば通常受付を開かず停止する。この確認のための追加ResetやSnapshotは不要。

通常STOP/STARTで最後のnew worldを再利用できることを確認し、Aへの通常SWITCHと最終STOPで締める。
停止後の新BACKUPを一回作成し、新current_id/owner recordを含む復旧情報とSnapshotを確認する。
この復旧点の隔離copyで、新currentとretainedの識別・抽出・保存再起動を確認してから、旧world directoryのproduction cleanup release可否を判断する。
自然なReset回数で保持上限を越えるまで削除試験のためだけにResetを量産しない。release前は別policyで削除を省略するのではなく、削除を含む追加本番Resetを実施しない。
現在の7件が不変で計画したBACKUP二件だけを追加した場合は、legacy normal 5・migration anchor 1・shared v2 normal 3、合計9件が見込み。件数を根拠に削除releaseしない。実inventoryでshared KEEP=3/CANDIDATE=0/ANOMALY=0を照合し、途中に別backupがあれば期待値を再算定する。
RETENTIONは共有形式の既存保持群としてdry-run一回。Game/worldごとにnewest7を分けず、legacy/migrationを件数へ入れない。

新world参照の隔離復旧成功後に初めてCommandを元設定へ復元する。失敗時は閉じたまま、A/Bの保存状態と適用済み範囲を報告する。これは二つ目の承認待ちではなく、一括承認内の検証条件である。

最終状態は選択A・STOPPED/HEALTHY・DNS/Lock/Current Operation/unfinished Operationなし、両受付元設定、A/B anchor/new dataとSnapshot/provenance保持。cleanup未releaseならその事実を残す。

## 権限・費用・停止条件

新恒久table/volume/instanceは作らない。既存Stop taskにGames UpdateItem、Games GetItemをstart/stop/reconcileへ追加し、既存Operations/Locksのtransaction ConditionCheckItemを限定する。SendCommand応答喪失の観測用にStop taskへssm:ListCommands（resource *、read-only）を追加する。Reset workflowは既存のtask invoke roleを再利用する。DeleteSnapshot権限・API・DryRunは追加しない。
一時隔離環境は前回runbookの専用role/SG/host/復元volumeの一括範囲だけ。新しい一時resourceはこの準備では作成しない。
恒久EBSは30 GiBのまま。保持領域増加は既存枠内だが空き容量を消費する。Snapshot課金は変更block量次第で増え、Resetの新world生成は差分を増やす。費用実測は未実施、Budget $15は変更しない。単価・試験時間仮定は準備証跡へ記録する。
一時環境は4時間で時間・費用を見直す。超過だけで診断copyを削除しない。

停止条件は、対象/owner/保存根拠/receipt不一致、未解決mutation、未知artifact/data、new policy/IAM拡大、force操作、元EBS/world repair、新しいrecovery semanticsが必要な場合。安全にできる範囲で受付を閉じ、適用済み/未適用と保護状態を明示する。


### 再開用operator入口（Proposed）

`python -m wishicraft.reset_operator --operation-id <固定ID>`はGet/Describeだけで、元のplan、選択参照、command ID、所有権と再開可否を表示する。
同じexecutionの失敗TaskだけがREDRIVABLEで、Operation RUNNING・lease/deadline有効の場合に限り、明示した固定`--resume-token`と`--execute`で同一executionをredriveする。既に成功したstepを再実行しない。
SSM予約後にID保存を失った場合は、instance/command本文/Operation/lease/commentがすべて一致する一意な既送信commandを観測する。見つからない・複数・本文不一致なら再送しない。
容量不足等でforeground準備processが非zero終了した確定失敗は既存owned failure処理で終端化し、旧選択・旧worldを保持する。partial新領域は診断用として残し、通常STARTで旧対象へ戻せる。timeout/cancel/不明は確定終了とみなさない。cleanupの確定非zero終了はcleanup_pendingとして稼働成功を保持する。
lease期限切れ、終端FAILED後に同じTaskを再開できない状態は、この入口の自動復旧範囲外。データを保持して、既存canonical STOPで安全に収束できるかを確認する。raw repairや新world生成で埋め合わせない。

### 費用根拠

前回の公式Price List取得（2026-09-11、[隔離runbook](backup_safety_isolated_restore.md)）ではTokyo t3a.medium Linuxが$0.049/時、gp3が$0.096/GiB月。[公開IPv4](https://aws.amazon.com/vpc/pricing/)は$0.005/時。
同じ16 GiB root＋30 GiB copy、一時host4時間、月730時間換算なら約$0.2402/回（通信・税・Snapshot追加差分を除く）。二つの復旧点を順次試す場合は約$0.48。停止してvolumeを残す場合46 GiBで約$4.416/月。
これは過去取得単価による準備見積で、今回の費用実測ではない。実行直前に単価を照合し、4時間地点で保持費用と診断継続を見直す。Snapshot追加費用は変更block量が未確定なので固定額を約束しない。
