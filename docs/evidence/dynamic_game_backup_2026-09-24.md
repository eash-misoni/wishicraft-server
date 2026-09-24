# Dynamic Game BACKUP — limited dev release and positive proof

2026-09-24 UTC. **The formal stopped BACKUP succeeded with the CREATE/IMPORT-created
vps-survival Game selected.** One completed encrypted shared-volume snapshot and its
matching durable provenance pair are retained. The same successful request replayed
as the same Operation with `created=false`, without another snapshot/workflow.

[Structured evidence, artifact hashes and checkpoint history](dynamic_game_backup_2026-09-24.json).
[Contract, official AWS references and release procedure](../runbooks/dynamic_game_backup.md).
The [old create-terralith rejection](game_restore_pause_2026-09-23.md) remains evidence
of the previous defect; no rejected BACKUP was repeated to reproduce it.

## Cause, fix and authority

BackupTask's deployed CreateSnapshot condition accepted only `game-vanilla-main`
and `game-vanilla-secondary`. Its application already resolved the registry and
froze all-Game shared-volume recovery data. The policy, not snapshot orchestration,
was out of alignment with D-105 CREATE.

Only CREATE-enabled configurations now match those exact legacy IDs **or `game-`
plus 64 IAM single-character wildcards**. IAM `StringLike` is not a regular expression
or a registry query. A format-shaped unregistered ID may match IAM; the application
rejects it before snapshot creation. Exact hexadecimal ID membership, ACTIVE record,
Operation target, package/creation and recovery consistency remain application gates.
Registry failures never become a fallback to a shorter legacy list.

Unchanged IAM boundaries: exact canonical Data EBS volume ARN; existing region-scoped
snapshot ARN; Project/Stage/category/protected requirements; nonempty matching Game
tag; CreateTags only during CreateSnapshot. No delete/share/copy/volume permissions
were added. Game tags do not limit the contents of this whole-Data-EBS snapshot.

A fixture adds another registered Game in the same process/configuration and runs
the real freeze/create handler without regenerating IAM. This and the generated-policy
pattern test establish future CREATE tracking; no additional AWS test Game was created.

## Execution source and release

- Starting HEAD and remote main: `e18c0d443a7cba5cdf4abef0bcaeaf8ad933ee54`.
- Implementation **and deployed execution commit**:
  `9ba1a33811eef5144d1ea96f0fdbe21057979edb`.
- Runtime application source unchanged by this implementation: infrastructure policy,
  regression tests and docs only. No BACKUP API, validator or safety contract redesign.
- Execution used its own clean detached worktree. Assembly, commands and payloads were
  generated there; unrelated primary-checkout changes were excluded and preserved.
- Dedicated local evidence root: `wishicraft-dynamic-backup-20260924-ju21b3nd/outputs`.
  `assembly-v2` excludes generated Python bytecode; the unused first assembly remains
  diagnostic evidence and was not deployed.
- Template SHA-256: `e05424568f35025bf0bc8a986ce3ea38fbeeb2461044ffcfa0b303055201c6e9`.
- Exact ChangeSet:
  `arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/dynamic-backup-9ba1a33-20260924/92fdc633-2da0-4d25-b843-65e728e9ae98`.
- Evaluation: one BackupTask IAM policy, 11 existing Lambda Code/asset-metadata updates,
  five Case D State Machine dependency updates; all Modify/Replacement=False.
  No additions, deletions, other IAM/configuration/alarm changes or other stack update.
- Case D raw Properties, intrinsic-resolved ASL and canonical ASL matched. The five
  evaluated changes were Definition-only/Never-recreate on Backup, Start, Stop, Switch,
  Reset. Non-property-evaluated dependency listings were preserved separately.
- Shared asset differences were the previously reviewed D-113 modules/helper source;
  they were inventoried against the deployed ZIP. No host helper was redistributed.
  All six actual State Machine definitions/roles/configuration remained unchanged.
- Stack `UPDATE_COMPLETE`; actual BackupTask role policy matched the expected single
  condition change. All 11 deployed Lambda configurations/identities and both unique
  ZIPs were read back; source bytes matched the clean checkout.

CloudTrail independently records this CreateSnapshot under the **BackupTask execution
role**, not the operator's administrator identity. Event ID and sanitized request/
response evidence are in JSON; no credential values were saved.

## Target and formal operations

Dev account `385526546525`, region `ap-northeast-1`, profile `wishicraft-dev`, system
`wishicraft-main`; EC2 `i-04fc0629dc4ea466e`, Data EBS `vol-03ac9f534326c345c` matched
canonical configuration and actual resources.

Target: `game-bfd8409b3f8a4d1b591231c3490d9b646f546294ca11837cad74616ed33eaf21`
(`vps-survival`), the dev imported copy, existing Paper 26.1.2/build 53 package and
existing `.../games/<Game ID>/server` path. **No real VPS was accessed.**

Initial selection was Vanilla B. The explicitly approved single normal START/STOP
pair selected vps-survival; no direct SystemState/Game edit or extra selection cycle.
Formal READY and fresh Reconcile showed the exact target/path/run, running container,
expected Data EBS mount, protocol ready, HEALTHY and zero players. No client test or
exploration was performed. STOP completed save/stop, container cleanup, EC2 stop and
DNS removal before BACKUP.

| Formal operation | Operation ID | UTC interval / result |
|---|---|---|
| Selection START | `op-9d3ae619-241c-40f1-b8bc-bf8a423138df` | 11:08:11–11:12:25, SUCCEEDED |
| Normal STOP | `op-02901e7f-9880-4844-b836-b5659d76847b` | 11:13:53–11:15:34, SUCCEEDED |
| BACKUP | `op-4236596e-a436-4c99-833b-33b39f89dab8` | 11:17:19–11:19:27, SUCCEEDED |

BACKUP used Admin Admission without `target_game_id`, with fixed key
`dynamic-backup-20260924-9ba1a33:backup`. No direct CreateSnapshot, direct task Lambda
invocation or direct workflow start was used. Replay returned that same Operation,
`created=false`, `lease_id=null`.

## Snapshot and provenance

- Snapshot **`snap-0aac363f3ce09e05a`**, start `2026-09-24T11:17:26.669Z`, completed,
  encrypted, correct account/region and canonical source Data EBS.
- Actual Game tag is the target canonical ID; Project=`wishicraft`, Stage=`dev`,
  WishicraftCategory=`backup`, WishicraftProtected=`false`, schema 2, shared-volume.
- Recovery digest:
  `9f4f6d91eefb637c2eaca50474d1f154f5ed6e946c8ca86494571e86d6b4f809`.
- Real snapshot, successful Operation and both provenance records passed the existing
  `isolated_restore.verify_source` validator. Recovery records matched all **five**
  registry Games, including package/creation/world references and current policy data.
- Vanilla B retains its original world selection, generation 1 and generation_counter 2.
  Existing D-113 journals, including the rolled-back journal and prepared-world receipt
  references, were unchanged. No RESTORE or cleanup command ran in this slice.
- Snapshot count 11→12; all 11 existing snapshots' identity/tags/encryption retained.
  No snapshot was deleted and retention remains dry-run-only.

## Final state and limits

Final read-back at 11:23:52–11:24:05 UTC: vps-survival selected, Desired STOPPED /
HEALTHY, EC2 stopped, previous maintenance ENDED, no Current Operation/Lock/running
workflow/active SSM/session/DNS, all three queues empty, **49/49 alarms OK** with
unchanged configuration. Discord Command/Web concurrency restored to original UNSET;
Admission stayed UNSET, Observer/Reconcile remained active.

All Game/registry/package/creation/access records compared unchanged (DynamoDB String
Set ordering normalized). In this implementation, even the target's stored
last_started_at did not change. Normal Paper START/STOP may update saved world files;
this is not a claim of byte-identical target content. No other Game was started or
switched; Vanilla B's two retained worlds were not targeted by host mutations. Their
physical bytes were not rehashed in this slice. Source/protection snapshots remain.

Tests: **1,821 passed**, including 12 new generated-policy/dynamic-boundary tests;
Ruff lint/format (338 files), mypy (251 files), full dev synth passed.
Implementation CI all succeeded: [normal](https://github.com/eash-misoni/wishicraft-server/actions/runs/35989573853),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/35989573884),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/35989573780).
Local Docker/shellcheck were unavailable; real Docker integration was CI evidence.

Local diagnostic failures were retained: resource inventory naming/pagination/scope,
Case D's ResourceAttribute label, and unordered String Set comparison were corrected
in read-only tooling, before their dependent writes or final comparison. An initial
new-worktree offline wheel cache miss used the pinned online dependency path. No AWS
mutation was repeated to repair output or observation tooling.

This proves the limited dynamic-Game BACKUP IAM repair and formal positive BACKUP,
separately from D-113 RESTORE qualification and daily automatic BACKUP operations.
No snapshot mount/full-world hash validation, Paper RESTORE, automatic scheduling,
retention deletion, EXPORT/UPGRADE, new CREATE, host/package change or VPS operation.
Closeout docs are a separate commit; final commit/CI and finalized-HEAD Wiki sync are
reported in the handoff.
