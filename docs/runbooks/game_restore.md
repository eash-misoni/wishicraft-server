# Operator Game RESTORE

> 2026-09-24 follow-up: [dynamic Game BACKUP IAM修正とdev vps-survivalでの正式BACKUP成功](../evidence/dynamic_game_backup_2026-09-24.md)。過去の保護BACKUP IAM blockerは当時の履歴として保持する。今後も保護BACKUPは正式経路で成功することが条件で、D-113実証・自動BACKUP運用とは別の完了範囲。

[D-113 contract and candidate inventory](../reviews/game_restore.md).
Limited Vanilla B dev qualification completed in the
[2026-09-24 retained-PREPARED continuation](../evidence/game_restore_resumed_2026-09-24.md):
conditional commit, restored START/content/STOP, formal rollback, original
START/content/STOP, both worlds retained and final STOPPED/HEALTHY / 49 alarms OK.
The [2026-09-23 execution](../evidence/game_restore_prepared_2026-09-23.md) separately
proved real read-only XFS/copy/PREPARED and one recovery-lease resumption. Real
Paper/NeoForge RESTORE, all failure paths and disaster recovery remain unqualified.
Future AWS commands require their own execution scope. COMMITTED is selection;
actual START/content evidence remains a separate completion state.

## Execution checkpoints

Before generating any real-AWS execution artifacts, create a separate detached
worktree at the exact approved commit and verify its HEAD and empty
`git status --porcelain` output. Generate payloads, helper bytes and CDK assemblies
only from that clean checkout into a new dedicated evidence/output root. Do not
copy dirty primary-checkout files into it. Preserve unrelated primary-checkout
changes; record the approved commit and artifact hashes in the execution evidence.
An unapproved commit or a dirty execution worktree blocks execution.

1. Verify committed source/CI and canonical dev STS identity. Record Game/current
   world, source snapshot/backup timestamp/source world/package. First qualification
   uses Vanilla B and the candidate recorded in D-113, never `vps-survival`.
2. Through existing Admin Admission, request ordinary BACKUP with a fixed
   idempotency key. Wait for SUCCEEDED, completed snapshot and durable provenance.
   No direct StartExecution. The backup must postdate the last Desired transition,
   be at most one hour old, and match current Game world/package.
3. Use [formal maintenance begin](planned_host_maintenance.md) with a new ID,
   sufficient TTL and a fresh evidence root. Observe expected suppression. Existing
   metrics and other alarms are unchanged. No manual alarm disablement.
4. Create the durable RESTORE plan while EC2 is still stopped:

   ```sh
   tools/dev-env run -- python -m wishicraft.restore_operator plan --maintenance-id MAINTENANCE_ID --game-id GAME_ID --snapshot-id SOURCE_SNAPSHOT_ID --pre-backup-snapshot-id PROTECTION_SNAPSHOT_ID --request-id UNIQUE_REQUEST_ID --execute
   ```

   Save the returned operation ID. It is a maintenance-admin RESTORE audit identity,
   not a workflow execution ARN. Same request returns the same immutable plan;
   different Game/snapshot under the same request is rejected.
5. Run `volume` with that operation ID. It records create intent, discovers exact
   prior resources, or creates one encrypted/tagged gp3 volume with ClientToken.
   Repeat/status observes the same volume. Never substitute the production Data EBS.
6. Within the approved maintenance session, resolve and start **only the existing
   target EC2**, wait for SSM and a fresh normal host probe proving no container,
   expected production mount, no listener/Game and absent DNS. This is the D-111
   host-work step, not ordinary Minecraft START or an unleased maintenance boot.
7. After separately approved application of the reviewed host SystemState GetItem
   policy (one table/LeadingKey; no EBS permissions), run `attach` until attachment is ATTACHED; transition states are observations,
   not completion. Run `prepare` once. The fixed SSM payload verifies host/package,
   mount, no Lock/container and unexpired maintenance window. It upgrades only the
   two exact reviewed helper predecessors (`reset_worlds.py`, `world_import.py`),
   preserving hashed predecessor copies and already-applied bytes. It then resolves
   the temporary NVMe serial, enforces block-device read-only and verifies the XFS
   read-only/norecovery mount. It validates source ownership/tree, prepares a new
   generation, compares source/copy hashes and unmounts.
8. Run `collect` to observe the exact command. Only Success/ResponseCode=0 and the
   expected prepared/unmounted receipt allow PREPARED. An ambiguous send is searched
   by exact operation/comment/parameters; absence never authorizes another send.
   `retry-prepare` is allowed only after a known command has definitely Failed with
   a positive exit code, no active SSM, and a fresh idle-host observation. It records
   the failed command before permitting the same plan's next copy attempt. TimedOut/Cancelled require actual EC2 stopped before explicit retry. Running or
   unresolved/ambiguous transport outcomes never authorize automatic redispatch.
9. Verify source and prepared hashes, previous tree and other Games unchanged, no
   active SSM/process, then normally stop EC2 under the same maintenance session.
10. With stopped EC2, run `commit`. The conditional transaction advances only the
    target Game's world reference/counter and RESTORE journal. An exact committed
    replay does not increment again. No host world is overwritten.
11. Run `cleanup` through DETACHING → DELETE_INTENT → DELETING → DELETED. Each call
    revalidates volume ID/tags/snapshot/AZ/encryption/attachment and stopped EC2.
    Recheck no restore-tagged volume remains. Keep failed cleanup in the journal;
    investigate permissions/identity without granting application lifecycle rights.
12. Formal maintenance end must succeed with STOPPED/HEALTHY and all normal safety
    observations. Then use existing Admin Admission for START of the target Game.
    Verify exact new data_source in runtime_target/receipt, READY, fresh Reconcile
    and heartbeat, current access projection and Game MATERIALIZED. Compare retained
    generation files and restored content against saved pre-START copy hashes;
    Minecraft may legitimately change level.dat/chunks during START.
13. Use normal STOP. Record final EC2 stopped, STOPPED/HEALTHY, all alarms normal,
    Lock/Current/workflow/SSM/DNS absent, all deployed queues empty, previous generation
    present, source snapshot unchanged and temporary volume/staging cleanup complete.

Checkpoint syntax after planning:

```sh
tools/dev-env run -- python -m wishicraft.restore_operator status --maintenance-id MAINTENANCE_ID --operation-id RESTORE_OPERATION_ID
tools/dev-env run -- python -m wishicraft.restore_operator volume --maintenance-id MAINTENANCE_ID --operation-id RESTORE_OPERATION_ID --execute
```

Replace `volume` with the documented checkpoint; do not skip prerequisite states.
`status` is read-only. No command sets Observed/Health to manufacture success.
Source snapshot selection is verified provenance plus Game, not an arbitrary snapshot
copy command. Volumes and staged generations remain traceable after interruption.

## Rollback

If first START fails, keep both generations and the failed operation evidence.
Observe and finish the exact interrupted operation/SSM/receipt; never clear Lock or
rewrite host receipts manually. Normally stop a known runtime and reach the formal
maintenance begin preconditions. Use a new maintenance lease and:

Within that lease, boot only EC2 and run `check-rollback`, then `collect-rollback`.
These verify the previous actual tree against the prepared receipt's saved hash.
After confirming idle host and stopping EC2, the same lease may perform selection:

```sh
tools/dev-env run -- python -m wishicraft.restore_operator rollback --maintenance-id NEW_MAINTENANCE_ID --operation-id RESTORE_OPERATION_ID --execute
```

This CAS requires the exact restored world still selected, unchanged package and
stopped/idle environment. It reselects the old path/generation but preserves the
allocation high-water mark and both world directories. End maintenance before any
normal START. Unknown/missing previous world, an unclosed operation, drifted package
or competing selection is a stop condition, not a reason to overwrite data.

## Validation record

Repository focused tests include three runtime trees, source/provenance rejection,
generation allocation, immutable current data, partial retry, hash/owner checks,
explicit rollback transaction, response loss, expired maintenance/active Operation/
Lock/RUNNING rejection, temporary volume lifecycle and cleanup failure, fixed SSM
payload, read-only mount sequencing and exact helper upgrade replay.

Full tests initially hit restricted-network PyPI bundling failures (1656 passed,
12 failed, 47 setup errors); `tools/setup-dev-tools bundling-cache` resolved that
environment issue. The next full run passed 1715 tests. Final repository validation, with hash-locked
cached bundling dependencies and `UV_OFFLINE=1`, passed **1727 tests**, Ruff lint/format,
and mypy (246 source files). Four synth contexts passed: frozen Phase 1 (synth only),
Target, base Control Plane and configured two-Game/RESET/CREATE/whitelist/package Control Plane.
The original implementation CI passed all three workflows (5695049).
The interrupted historical dev attempt reached only PLANNED; see the pause evidence.
The present recovery revision validation is recorded separately below.
Docker CLI is unavailable locally; do not label mocked mount/EC2 tests real integration.


## Expiry / interruption matrix (separate execution approval required)

Never mutate raw maintenance or rollback_dispatch fields. Do not delete world data
merely to make closeout possible. Retain the journal, owner receipts and snapshots.

```sh
tools/dev-env run -- python -m wishicraft.restore_operator recover-maintenance --maintenance-id NEW_UNIQUE_APPROVED_LEASE --previous-maintenance-id EXACT_EXPIRED_OR_INCIDENT_LEASE --operation-id RESTORE_OPERATION_ID --duration-seconds 3600 --execute
```

This records a replacement lease and complete previous lease atomically with fresh
state/Lock fencing; normal Admission stays closed. It does not boot/stop EC2, mount,
copy, select a Game, or silently renew a lease. Capture stdout and new evidence.
On a lost transaction reply, read status and the new lease's recover-restore audit;
also verify the journal's last_maintenance_id equals the new lease ID and its
revision advanced. Do not invent another ID. Verify suppressor eligibility from actual observations.

Recovery leases are limited to their exact restore_operation_id. Using one for
another journal/plan is rejected by operator, transaction and host. Issuance must
match the journal's last_maintenance_id (or original maintenance_id for a legacy
journal) to the actual old lease, with matching operation/system/stage and old
scope. The lease/audit/journal binding advance atomically, so a second legitimate
recovery uses the latest lease, not the initial one. Unrelated history or an
unverifiable binding is a stop condition; never patch it manually. A fresh ordinary
maintenance session remains available after safe closeout for explicit rollback;
its first RESTORE checkpoint records the binding before external side effects.

| Interrupted checkpoint | Resume under a new approved lease | Data/resource protection |
|---|---|---|
| PLANNED / CREATE_INTENT | Recheck Desired revision; volume discovers exact tagged result before stable-token create | Legacy plan lacking revision requires new qualifying BACKUP and new request; never patch old plan |
| VOLUME_CREATED | Observe exact volume, attach after approved idle-host boot | Original Data EBS stays attached and unchanged |
| PREPARE_DISPATCH / copy partial | collect exact command first; definite Failed permits retry-prepare; then prepare uses a new private staging attempt | Existing owner/receipt/hash decides recovery; no overwrite of current server |
| SSM reply lost | collect by exact operation/payload/instance/ID; none or duplicates stop | No blind redispatch |
| TimedOut / Cancelled | Observe terminal SSM, prove Minecraft absent, obtain separate approval for normal EC2 stop if necessary; after actual stopped, explicit retry-prepare/retry-rollback; only then boot under recovered maintenance | Stop is never Force; unknown Minecraft/save state blocks this path. Stopped host proves old process cannot overlap retry |
| PREPARED | Collect success if needed; stop idle EC2; commit only with unchanged protection revision/world/package | Retain old and prepared trees; no recopy is needed for recorded success |
| COMMITTED, volume remains | Stopped host permits cleanup through persisted detach/delete intent/readback | Old/new world remain; COMMITTED is not READY |
| Rollback check Failed | retry-rollback archives reconciled failed command; check-rollback and collect-rollback again | No manual dispatch clearing |
| Rollback check Success, lease expired | collect-rollback accepts exact historical proof for audit; retry-rollback under new lease invalidates it; check/collect again, stop EC2, rollback | Selection requires proof for the current lease |
| Protection revision changed | Stop forward execution; clean temporary resource under valid lease, preserve old audit and owned staged data; new BACKUP/request requires separate approval | Same world ID does not imply unchanged bytes; partial data is retained for review, not silently discarded |

A new recovery lease can be issued on a positively idle running host after terminal
work, or on a stopped host. Therefore cleanup does not require ending the old lease
first. A running host with unknown/timed-out transport must be safely stopped under
explicit recovery approval before this shortcut is eligible. No container/unknown
mount/DNS/Lock/active work can be waived by marking a lease INCIDENT.

## Proposed dev proof (not executed in this review)

Candidate: Vanilla B, historical source `snap-0be8e05ab05d70e84` (2026-09-12
10:31:35.625 UTC, source generation 1, legacy server path). Its schema-2 provenance
and same Vanilla 26.2 package were historically verified. Re-read current state,
source ownership/provenance and availability immediately before approval/execution.
Do not choose vps-survival. Neither candidate inventory nor prior ordinary Vanilla B
START is proof of a restored START.

The approval bundle must name account/profile/instance/Data EBS, source/Game,
new request, temporary-volume tags/AZ/encryption, narrow Target GetItem policy
application (review a no-replacement diff), the two exact host helper updates,
maintenance/recovery TTLs and these specific operations:

1. Fresh qualifying normal BACKUP of current stopped content. The old protection
   snapshot and PLANNED journal from the pause are historical, not fresh authority.
   If current Game cannot use existing BACKUP IAM, stop for a narrow reviewed fix;
   do not secretly switch/start Games as a workaround in this approval.
2. Formal maintenance and positive suppression proof. Capture full tree hashes of
   previous and other Game server directories, metadata and current access policies.
3. Create/discover one tagged temporary EBS, attach, verify device serial and actual
   readonly XFS options. Reject source needing journal replay or filesystem repair.
4. Check source path/owner/package/NBT and record full source world hash plus selected
   content landmarks (seed, known region/player data) before copy. Compare staged
   world hash with source exactly. No snapshot-time whole-world hash is claimed.
5. Observe PREPARED; prove previous/other tree hashes unchanged and source unmodified.
   Normal maintenance EC2 stop, conditional commit, cleanup temporary EBS and close
   maintenance. Verify source snapshot still exists and retained owners are protected.
6. Normal START of restored path; verify runtime bind/receipt, READY, Reconcile,
   heartbeat, materialization and selected saved content. Post-START world files may
   legitimately change, so use the pre-START exact-copy hash plus meaningful landmarks.
7. Normal STOP; demonstrate explicit rollback even after successful START: new formal
   maintenance, check-rollback/collect-rollback, stopped-host rollback CAS, retain both
   directories/high-water counter. End maintenance, normal START of original path,
   verify original content, normal STOP. Do not manufacture a failed Minecraft boot.
8. Exercise one controlled interrupted checkpoint on this test Game under the approved
   bundle; matrix cases not exercised remain repository-only evidence. Capture old/new
   lease IDs and prove old payload refusal without touching current world.
9. Finish STOPPED/HEALTHY, EC2 stopped, maintenance ENDED, alarms normal, no Lock,
   Current Operation, running workflow, active SSM/session or DNS; all queues empty,
   no temporary EBS/mount or disposable staging. Retained generations/owner/validated
   receipts are intentional recovery data. Record scope of any remaining untested cases.

## Repository review validation

Local recovery review: 1766 tests passed, Ruff lint/format and mypy (247 files)
passed. Four local CDK synth contexts passed (Phase 1, Target, base and configured
Control Plane). A local `cdk diff --template` against 5695049 shows one added
GetItem statement on `wc-dev-system-state`, constrained to `wishicraft-main`, plus
CDK path metadata; no resource properties outside that policy change. This is not
a comparison with the deployed stack. IAM deployment is not approved here.

Regression coverage includes exact rollback send-loss reconciliation, failed/stale
proof retry, ambiguous/running/timeout refusal, stopped-host terminal-timeout retry,
all four interrupted phases under stopped/running recovery, revocation at host
boundaries, changed Desired revision, copy interruption in all three runtime trees,
managed previous-world protection through subsequent RESET cleanup, and the exact
one-key IAM allowance. EBS/mount lifecycle remains mocked; temporary filesystem
copy/hash/rename tests use real local files.

Original candidate CI: [CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35752151440),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/35752151394),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/35752151538) all succeeded.
The recovery commit's CI result is reported with its final commit in the handoff.
Initial review tests had three fixture signature failures plus two network-dependent
bundling failures; the former were corrected without changing saved evidence, and
hash-locked cached bundling with UV_OFFLINE resolved the latter. No failure was
relabeled as a pass. No real AWS inspection,
RESTORE, BACKUP, START, reference switch, temporary volume or IAM deployment was
performed during this repository-only review. Mocked EBS/mount tests are not XFS proof.

Scope correction after 632c2f5: **1798 tests passed**, Ruff lint/format, mypy
(247 files), and the same four local CDK synth contexts passed. Added regressions
cover matching/mismatched scoped leases at operator, repository and host boundaries,
unrelated lease/journal rejection before Reconcile, atomic revision/plan/binding
conditions, legacy initial binding, and repeated same-RESTORE recovery without
intervening work. Existing expiry/INCIDENT and rollback retry coverage remains.
CI results are reported with the final scope-correction commit in the handoff.
This is repository evidence only; no AWS inspection or mutation was performed.

## Supplemental reader and retained PREPARED continuation

`wishicraft.restore_reader_payload.command(targets)` generates a read-only SSM
command from the exact checkout, with no host install or Python bytecode. Each
operator-selected target has `game_id`, canonical `server`, package `level`
(`world` or `wishinkaiwai`), and `full_tree`. Resolve these from the current journal,
Games and immutable package; never substitute an arbitrary path. Use fixed command
IDs/intents, preserve payload SHA-256, and collect terminal results before more work.
The generated process has a 600-second alarm (maximum 900); pair it with the SSM
execution timeout. The request allows at most eight targets and emits at most
20,000 UTF-8 bytes. Exhausting a limit is a failure, not silently truncated evidence.

The reader uses the existing IMPORT tree/SHA and unmodified NBT parser. It bounds
traversal to 100,000 entries, 16 GiB per server and depth 32, rejects links/special
files/other devices, and selects at most four terrain region file fingerprints.
It includes `dimensions/<namespace>/<dimension>/region` and legacy region paths;
entities/poi files are not terrain samples. It never emits all NBT, playerdata or
server.properties text. Only stopped roots should request full server/world hashes.
For a running selected world use `full_tree=false`: content fingerprints, runtime
binding and readiness together are evidence; a live whole-tree equality is not.

NBT fields explicitly distinguish `missing`, `null`, `unsupported`, `value`, and
`read_failed`. Array bytes have type/length/SHA only, not invented coordinates.
`Data.spawn` may contain array bytes in 26.2; selected dimension/pos summaries do
not interpret that array. A reported missing `Data.WorldGenSettings.seed` describes
only that legacy field; it does not establish that the world has no seed. Terrain
fingerprints and measured prepared-tree provenance remain independent evidence.
Unknown output types are rejected, never hidden by `default=str`. Region files
changed during a read are marked `changed_during_read`, not stable evidence.
The optional `include_host=true` also reads the two fixed helper hashes/owner/mode,
the runtime receipt phase/target, and Docker image/running state/bind mounts only.
It never emits Docker environment or full runtime receipt. Policy files are hashed,
not printed.
Managed owner/validated metadata is read at fixed paths with root:root/0600 checks;
missing validation on a historical RESET owner is not silently fabricated.

For the separately approved continuation from the 2026-09-23 PREPARED record:

1. Freeze the reader commit after tests/CI and generate all AWS artifacts in its
   clean separate worktree. Do not rerun plan/BACKUP/volume/prepare or deploy IAM/helpers.
2. Re-read the same RESTORE journal, original selected world/package, protection
   provenance and unchanged Desired revision 67. The one-hour BACKUP age was a
   plan-creation gate; elapsed time alone does not invalidate retained PREPARED.
   Revision alone also does not prove unchanged file bytes.
3. With old maintenance ENDED, use a new ordinary maintenance begin, not recovery
   of an ended lease. Boot only the idle host. Recheck original/prepared server trees,
   prepared world tree, root-owned owner/validated receipt, helper hashes and other
   Games against the prior receipt and current baseline. The deleted temporary EBS
   is not needed: the previous source/copy proof links to the retained tree hash.
4. If all gates hold, normally stop the host and use the same journal's `commit`.
   Its existing checkpoint binds the new lease; do not hand-edit revision/lease/phase.
   End maintenance, then normal Admin START/content/STOP on the restored path.
5. New ordinary maintenance, check-rollback/collect-rollback, stopped-host rollback,
   maintenance end, original normal START/content/STOP. Do not apply forward revision
   67 to rollback after the expected normal lifecycle transitions.

A mismatched protection revision/tree/identity is a stop for separate review, not
permission for a new backup/request, recopy or validator relaxation. Preserve the
prepared data. The bounded supplemental-reader-only retry exception in the current
execution approval does not authorize retries of RESTORE or Minecraft failures.

The first resumed supplemental read (2026-09-24) terminated Failed/1 at the fixed
20,000-byte output limit; it did not change trees or fail RESTORE prepare. The
bounded reader selection now accepts optional `content=false` for other Games:
exact server/world tree hashes remain, without unrelated NBT/terrain/policy details.
The target's original and restored worlds retain content evidence. Owner/validated
records retain file hashes, root ownership/mode, phase/protection/tree fields, while
full `plan` and `restore` objects are represented by canonical SHA-256 (same encoding
as `game_package.digest`). Compare these digests with the frozen plans; this is
identity evidence, not a new validator or a decoded content claim. The output limit
is unchanged. Preserve the failed payload and result; the separately approved
single corrected read requires terminal failure, local regression, fixed commit/CI,
current maintenance and sufficient remaining time.
