# Two-Game SWITCH / BACKUP contract

**Status: Proposed — repository preparation validated; no production writes authorized.**

Baseline: `bb78deacc4daf1ad195887f337b3d4fa6a53c30f`. D-096 remains Completed.
This proposal does not accept the rest of Phase 9, RESET, whitelist synchronization,
Package/Preset/Template management, or different runtime classes.

## Scope and ownership

Two declaratively allowlisted Games share one pinned runtime configuration, one EC2,
and one Data EBS. A stays at its existing path. B uses a distinct Game-derived path.
Paths and commands are not supplied by Discord callers. Games records describe the
registered Games; the Git catalog limits what the host can execute. Distribution of
that catalog is configuration deployment, not synchronization of an active pointer.

`SystemState.desired_game_id` is the selected Game. STOP retains it. The existing `SystemState.game_id` is updated atomically in the same
Desired CAS for legacy consumers; it is not an independently writable selector. A legacy unset
selection resolves to A until the first successful desired update. Actual Game/run
comes from the validated container/receipt, never from the selection. `runtime_id`
continues to name the host runtime slot; `run_id` names one execution.

START can name a Game while stopped. SWITCH freezes source and destination together
in the owning Operation before saving A. The destination run uses that Operation ID;
the source keeps its existing run. One lease owns both halves. Existing normal host
STOP (save, graceful exit, exact container removal) and START are reused. The SWITCH
state graph contains no EC2 start/stop task and no intermediate Operation completion.

A stays selected during its save/stop. Once A is confirmed stopped, the START half
selects B and requests RUNNING. A save failure retains A and its receipt. B start
failure retains both data directories and selects B; unknown/failed runtime is not
HEALTHY. There is no automatic rollback or generation of a replacement world.

Duplicate requests resolve through existing idempotency. An ambiguous host result
requires exact Operation/lease/SSM/receipt/container read-back. No replacement run is
created to conceal an unresolved one. A later ordinary START may resume the selected
unresolved run only under D-096 target validation. Returning to A first requires B
to be confirmed normally stopped. Terminal execution replay is not a recovery API.

## User policy proposed for approval

`/mc start game:<A|B>` retains current START authorization, but cannot stop a running
different Game. `/mc switch game:<A|B> confirm:true` requires Admin authorization.
SWITCH rejects positive or unknown player counts, with a second check at the host
before saving/stopping. This is a last-observed-empty policy: a connection can race
that check. It is not a promise of an atomic player admission fence. Broader player
permission or guaranteed advance notice needs a separate explicit policy decision.

## Backup proposal

New backups protect the shared physical volume and carry a frozen recovery description
in the existing durable provenance. No separate manifest service or archive subsystem.
The description identifies both registered Games, Game-derived paths, runtime image,
manifest, Compose and runtime.env bytes. Game-local properties/whitelist/world/player files
are protected in the Snapshot itself, not copied into a second mutable settings store. Failure to freeze that information must prevent creation;
post-create uncertainty protects the existing Snapshot and reservation until read-back.

Retention remains dry-run-only. New shared-volume normal backups form their own newest
seven group. Old per-Game schema records and migration anchors are preserved separately;
they are not rewritten, counted as new shared records, or silently made deletion eligible.
Execution safety is separate from that retention group: each shared-mode RETENTION task consistently reads its admitted Operation, validates RETENTION/Admin/nonterminal status and the owned lease, and checks its fixed Game against the Git catalog and fresh Reconcile (including current Operation and system). Admission’s atomic ACTIVE Game condition supplies registration evidence; normal Game registration is excluded by the same global lock. The canonical Data EBS attachment/owner/provenance checks remain in force. Reused Lambda clients do not retain a request-selected Game in the volume classification context.

Restoring A alone means extracting A from an isolated restored copy and validating it,
not replacing the shared EBS and rolling back B. Snapshot-time configuration evidence
must be distinguished from configuration reconstructed later.

## Production gate

No BACKUP, Game registration, host directory creation, SSM, command registration,
deploy, IAM, START/STOP/SWITCH, Snapshot/provenance update, or retention execution has
been authorized by this request. The final migration plan must identify fresh protection,
exact deployed predecessors, admission drain, B materialization, compatible host/CP
cutover, A→B→A measurements, failure checkpoints, and final STOPPED/HEALTHY.

The [migration runbook](../runbooks/two_game_switch_migration.md) owns execution ordering and
checkpoints. Validation/CI evidence is finalized separately before readiness; no production
SWITCH or new backup format has been exercised yet.


## Canonical document integration

| 文書 | 今回の扱いと正本の責務 |
|---|---|
| README | 現行D-096契約と未承認D-097の入口を分ける |
| AGENTS / 10 working agreement | 明示された一括承認とローカル委任を再利用。範囲外write・未知identity/outcomeで停止 |
| 01 scope/glossary | 既存runtime slotとrun/processを区別。将来モデルを今回の必須fieldにしない |
| 02 requirements | D-096 START/STOP保証とD-095復元順序を現行本文に統合。GAME LATER計画は見直し対象 |
| 03 architecture | 現行の実行境界と単一Game保護単位を明記。詳細契約は05へ参照 |
| 04 domain/state | Operation targetとhost実観測の責務、選択/観測の区別を説明 |
| 05 data/interface | D-096の対象固定・排他・停止削除・失敗再開の正本をrunbookから移設。CP v1 schemaは引き続き現行 |
| 06 delivery | Phase 9〜16を従来計画として保持し見直し対象と明記。D-095/D-096 Completedを維持 |
| 07 operations/security/cost | 正常STOPのデータ保持、root receiptとData EBSの異なる回復限界、復元実証範囲 |
| 08 human flow | 現行の日常操作と未公開のSWITCH/Resetを区別。正常container cleanupを人間の日常作業にしない |
| 09 Decisions | D-095/D-096の採用履歴を保持、D-097のみProposed。意味変更の採否はproduction gate |
| 11 external constraints | 更新不要。既存EULA/公式仕様の責務を変更せず、Bに適用する初期設定を承認計画で確認 |
| 12 initial configuration | initial Gameとrun IDを区別。新catalog/contextはProposedの明示配布設定 |
| targeted runtime runbook | 詳細契約の重複を05参照へ置換、旧手順/hash/失敗と適用証跡は保持 |
| backup safety runbook/evidence | 更新不要。完了した隔離復元の復旧点・限界・証跡は過去事実として保持 |
| phase8 review | 当時の未承認/未実施と後続D-095/D-096完了を区別し、本提案へ参照 |
| 本提案 / two-Game runbook | 未承認の契約差分と、実行順序をそれぞれ一か所で所有 |

Reset認可/旧world保持削除、共通whitelist反映、異なるruntime/spec、Web/Package管理は未決のまま。
新しい共有BACKUP newest 7は削除releaseではない。既存v1 normalとmigration anchorを数え直さない。


## Preparation result

実装HEAD `b96bf3cd28f2257695631dab5d08843e4f4d1555` の
[CI 34603989495](https://github.com/eash-misoni/wishicraft-server/actions/runs/34603989495)は
quality/host-runtime-integrationとも成功。934 tests、lint/format、Linux型検査、4 context synthを確認。
実Dockerではmissing run拒否、A保存/正常停止/exact removal→B→A、異なるcontainer、A保存値42、
A再起動中のB world不変、rm応答喪失後のreceipt収束を確認した。
IMDS/SSM/systemd/本番mountや実AWS workflowを再現したものではない。準備の完了とproduction適用は別である。
詳細な差分・hash・read-only時点・失敗CIは[準備証跡](../evidence/2026-09-11-two-game-preparation.json)を参照。
採用判断は、Admin限定/観測0人かつ明示確認のSWITCH、Bの初期設定、共有volume保護とv2 newest 7分類。
接続直前raceを完全に防ぐ保証や、実multi-Game単独復元の実証は含めない。


### RETENTION限定是正（production未適用）

前準備HEAD `82bfda8` の初期Game固定をfull handler境界で再現し、
`56124e8ae6537befb63a5c87feaf3b9d1a6e1d7f` でOperation根拠の呼出し別照合へ修正した。
[CI 34609430186](https://github.com/eash-misoni/wishicraft-server/actions/runs/34609430186)で
959 tests、quality、既存実Docker integrationが成功。A/B・同一Runtime A→B→A、共有保持群の同一分類、
不一致拒否・owned failureを確認した。監視の診断ログも判定対象と同じGameに合わせた。
前準備との差分は11 Lambda code assetだけで、IAM/host/workflowの追加変更はない。
B稼働中のcanonical RETENTION dry-runを移行計画へ追加したが、実AWSでは未実施。D-097はProposedのまま。
