# D-113 limited dev execution — PREPARED, safe stop before commit

This is a partial qualification record, **not a successful end-to-end RESTORE**.
The approved implementation was `b856dcf06f8564c7c056491ff3b993a3fc828357`.
Source extraction, real read-only XFS verification, validated copy and PREPARED
succeeded. A supplemental read-only content-evidence SSM failed while serializing
NBT bytes into JSON. The operator stopped before reference selection or Minecraft
START, following the approved unexpected-failure boundary. No implementation fix,
replacement payload retry or repeated START was attempted.

[Structured evidence and artifact hashes](game_restore_prepared_2026-09-23.json).
Raw evidence is retained in the dedicated local output root
`wishicraft-d113-dev-b856dcf-zrgdjbev/outputs`; it is not a public evidence service.
The closeout documentation commit is separate from the execution commit.

## Execution source and authorization

- Separate detached worktree at exact b856dcf, with empty `git status --porcelain`.
  Code, helper bytes, SSM payloads and CDK assembly came from that checkout.
  Generated artifacts/evidence remained outside it. The primary checkout's existing
  README, delivery plan, decisions and create-terralith changes were preserved.
- Canonical profile `wishicraft-dev`; reauthenticated STS account `385526546525`;
  region `ap-northeast-1`, system `wishicraft-main`.
- EC2 `i-04fc0629dc4ea466e`, original Data EBS `vol-03ac9f534326c345c`.
  Both matched current AWS and canonical resolution. Original EBS stayed attached.
- Only Vanilla B (`game-vanilla-secondary`), same `vanilla/initial-fixed-version`,
  Minecraft 26.2. No Game/package/policy change, VPS operation or other Game start.
- Existing approved-commit CI rechecked successful:
  [CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35825238609),
  [NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/35825238654),
  [Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/35825238704).
  Repository validation was 1798 tests, Ruff lint/format, mypy and synth. No runtime
  source changed in this closeout; its CI is tracked against the closeout commit.

## Source, protection and isolated storage

Source `snap-0be8e05ab05d70e84`, BACKUP
`op-059abd53-92a6-469a-abb2-6eb8dfe5da8e`, timestamp
`2026-09-12T10:31:35.625000Z`, generation 1, legacy path
`/srv/minecraft/games/game-vanilla-secondary/server`.
The formal validator rechecked the durable provenance pair, account/stage,
source volume, completed/encrypted snapshot, Game/world and package identity.
This authenticates the backup selection; it is not a historical whole-world hash.

New ordinary Admin Admission BACKUP, fixed idempotency key
`backup:restore-dev-20260923T083625Z-b856dcf`, succeeded as
`op-aa36d4ba-101b-47f1-bd6c-f393234b9509`. Protection snapshot
`snap-0d2407a5af78afa82` completed, captured `2026-09-23T08:38:21.444000Z`.
Durable provenance matched current world/package, postdated the last Desired
transition and met the one-hour freshness gate at planning. Desired revision 67
remained unchanged throughout. The known dynamic-Game BACKUP IAM problem was not
modified or bypassed; successful Vanilla B BACKUP does not fix that problem.

RESTORE request `restore-dev-20260923T083625Z-b856dcf`, Operation
`op-8639e35589a158e5e45fc2ccf68fcec06681aac6e8eeaf2b1507495e35224730`.
Original selected world ID remains `op-2fc1bd34-b2ab-45a4-b3f8-95a53d828dcf`.
The distinct prepared path is:

```text
/srv/minecraft/games/game-vanilla-secondary/worlds/op-8639e35589a158e5e45fc2ccf68fcec06681aac6e8eeaf2b1507495e35224730/server
```

Target generation 2 exists only in the prepared plan. Current generation remains
1; no generation counter was added or advanced because commit was not performed.
The earlier PLANNED journal and historical backup records were left intact.

## Narrow IAM and host helpers

The exact approved Target assembly was compared against the deployed template.
Removing its one new statement produced an exact match. ChangeSet
`d113-getitem-restore-dev-20260923T083625Z-b856dcf` modified only
`TargetManagedNodeRoleDefaultPolicy7209F5BF`, Replacement=False. The same reviewed
ChangeSet completed UPDATE_COMPLETE; template and actual role policy were read back.
It adds only `dynamodb:GetItem` on `wc-dev-system-state`, constrained by
`ForAllValues:StringEquals` / `dynamodb:LeadingKeys = [wishicraft-main]`.
Permanent stack policy denying Target EC2/attachment replacement or deletion stayed
unchanged. No Control Plane/Web deployment, broad IAM or resource replacement.

Formal prepare verified the two exact predecessor hashes, root:root / 0644, then
installed the reviewed `reset_worlds.py` and `world_import.py` bytes. Their new hashes
matched the approved worktree. Predecessor copies and approved helper updates remain.
Full old/new hashes and the assembly/ChangeSet identity are in the structured evidence.

## Planned interruption and recovery

1. Formal lease `d113-20260923T083625Z-begin`, 3600 seconds. Fresh eligibility and
   suppressor ALARM observed; Observer/Reconcile continued normally.
2. Create exactly one encrypted, tagged gp3 temporary volume
   `vol-0adfd2940e3e501ca`. At VOLUME_CREATED, EC2 was still stopped; no host SSM,
   mount, copy or reference change had begun.
3. Formal INCIDENT reason `approved-volume-created-resume-proof`, then official
   `recover-maintenance` to `d113-20260923T083625Z-recover`, another 3600 seconds.
4. Same RESTORE ID, scoped `restore_operation_id`, old/new lease and immutable audit
   verified. Journal revision 3 → 4 and `last_maintenance_id` advanced atomically.
   The same volume was subsequently attached; no second volume was created.
   Original Game reference remained unchanged. The maintenance record never became
   ENDED in this transition, and the public ingress restriction stayed in place.

Recovery metrics carried the new expiry and eligible=1; suppressor ALARM was checked
before boot. The expected three notification composites retained their suppressor.
History recorded expected base-alarm transitions and no notification action events.
The sampled composites stayed OK, so this run does **not** claim an observed
`ActionsSuppressedBy=Alarm` event on an ALARM composite. No alarm configuration or
notification sensitivity was changed, and no metric/state was forced to normal.

## Real host and data evidence

The maintenance host booted with expected original Data EBS, fresh idle Reconcile,
SSM Online, no container/Minecraft/listener or DNS. A read-only baseline captured
all five current Game server trees before preparation.

Formal prepare SSM `b1bcc5fb-4c1d-4e06-b03b-27d39add592d` completed Success/0.
Its approved payload resolved the EBS serial, required a raw XFS disk, set/read back
block-device RO, mounted with `ro,nouuid,norecovery,nodev,nosuid,noexec`, and checked
actual findmnt source/options before copying. No replay, repair, UUID change or format.
Mount options were enforced by the executed success-path assertions; they were not
separately emitted in the stdout receipt. The subsequent independent readback saw
`nvme2n1`, serial `vol0adfd2940e3e501ca`, XFS, RO=true and no mountpoint.

| Evidence | Result |
| --- | --- |
| Source full server tree, measured during this restore | `89e38cf5af6e2142b94edea7f649342750797f08644dd34a970755ff6e4f260c` |
| Source world = prepared world | `46edae3a5e1aa8457a24c243267bcf32ee970af28f805400c46ac74b3f946ced` |
| Prepared server including current policy files | `d941e0acc31d6b3bed13fd465ff0ecb040a1cf639bc80eb1f9a33eddd6589cc3` |
| Original server before = after | `60a298ff91447c4956a4131eca3d22797b58b1b2ca12b267bf78d9a32dce91ce` |

All other four selected Game server trees also matched their baselines exactly.
Prepared and original root-owned owners both have `protected=true`; the intentional
owner protection update is distinct from world bytes. Receipt validation, NBT version
26.2, region-file existence and independent prepared/world hash readback passed.
Temporary staging was absent; original and prepared directories/owner/validated
receipt were retained. Current policy files were used; no snapshot access authority
or Control Plane metadata was restored.

The initial optional landmark reader assumed older NBT seed/spawn locations and
top-level region paths. For the 26.2 fixture it returned null seed/spawn and zero
top-level regions; those are **not** claims of a missing seed or empty world.
A later recursive read counted nine `.mca` files for each Vanilla B world. Exact
source/copy hashes are established independently of these optional summaries.

## Unexpected supplemental probe failure and safe closeout

The operator-generated additional read-only SSM
`3730aceb-dd34-41d4-8421-7cc60113bcfb` read world file hashes and the current NBT
`spawn` field, then failed at `print(json.dumps(result))`:
`TypeError: Object of type bytes is not JSON serializable` (Failed/1).
This was a diagnostic payload defect, **not a failed formal RESTORE prepare**.
It did not publish usable landmark output and did not write world files.
The failed payload/result were retained. It was not modified or resent on AWS.

After exact result/journal readback, fresh idle/no-active-work checks permitted
ordinary non-force StopInstances. With actual EC2 stopped, formal cleanup advanced
DETACHING → DELETE_INTENT → DELETING → DELETED and verified volume NotFound.
Only the owned temporary volume was deleted; both snapshots and both worlds remain.
The journal retains its historical attachment checkpoint; `cleanup=DELETED` and
actual NotFound are the final resource authority, not that earlier attachment field.

Formal incident recorded the supplemental probe failure on the recovery lease,
then formal maintenance end succeeded while preserving both incident audits.
No Game selection occurred, so rollback was neither needed nor executed.

Final readback after ingress restoration at approximately `2026-09-23T09:13Z`:

- Vanilla B still selects its original world, generation 1, no counter advance.
- RESTORE journal **PREPARED**, revision 13, cleanup **DELETED**.
- Desired STOPPED / HEALTHY; EC2 stopped; maintenance ENDED.
- No Current Operation, Lock, running workflow, active SSM command/session or DNS.
- All three queues empty (visible, in-flight, delayed); **49/49 alarms OK**.
- No temporary restore volumes or disposable staging; both snapshots retained.
- All Games-table records, registry and access policy records equal the initial
  readback. Current world and all other Game bytes had matched their baseline on host.
- Discord/Web reserved concurrency returned from 0 to original UNSET; Admission
  remained at its original UNSET. Observer/Reconcile were never paused.

## Unqualified work and next approval

COMMITTED, restored START/READY/content verification/MATERIALIZED, restored normal
STOP, check-rollback/collect-rollback/rollback, original START/STOP were **not run**.
The pre-existing Game MATERIALIZED field is not restored-generation proof.
No Paper/NeoForge real RESTORE or other interruption matrix case was exercised.

Before another AWS attempt, review a bounded read-only content-evidence payload that
handles the actual NBT types without inventing null seed values. Validate it locally;
do not weaken the reviewed RESTORE validator. Approve the resumed limited execution
separately, including retained PREPARED receipt/tree verification under a new formal
lease, conditional commit, normal restored START/content/STOP, explicit rollback,
original START/content/STOP and safe closeout. Build artifacts from the exact approved
clean checkout again. The narrow IAM and reviewed helper updates already applied
should be checked and treated as no-ops, not redeployed without need.

Re-read current Game, package, Desired revision, receipt and backup protection.
If revision 67 or protected content changed after reopening normal ingress, this
old preparation is not fresh protection: stop and review a new ordinary BACKUP/request
under the existing contract, preserving this world and audit. Do not recreate the
deleted temporary volume merely to continue a valid retained PREPARED checkpoint.
Do not silently substitute a source snapshot or hand-edit any lease/journal/dispatch.
The dynamic-Game BACKUP IAM limitation remains a separate prerequisite, not a fix
included in this slice. EXPORT and general disaster recovery remain out of scope.
