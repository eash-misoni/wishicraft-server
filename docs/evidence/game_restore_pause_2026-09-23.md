# Game RESTORE — user-requested pause, 2026-09-23 JST

> Follow-up: [dynamic Game BACKUP IAM alignment](../runbooks/dynamic_game_backup.md) tracks the separate fix/release, now [qualified on dev vps-survival](dynamic_game_backup_2026-09-24.md). The failed Operation and observations below remain historical evidence; D-113 success alone did not fix IAM.

> Historical pause record. The later repository-only recovery review in
> [D-113](../reviews/game_restore.md#recovery-review-against-5695049) supersedes the
> unresolved-code guidance below; it does not change these historical AWS observations.
> Statements about uncommitted files and deferred Wiki describe the pause time.

User requested a safe pause because their usage limit was approaching. This is an
interrupted qualification record, **not a successful dev RESTORE report**.
No further AWS mutation is needed to maintain the observed stopped state.

## Repository checkpoint

- Implementation commit / HEAD / origin/main: `569504933fda8220342a38d5daf5cbe833256bd0`.
- Local: 1727 tests passed, Ruff lint/format passed, mypy 246 files passed,
  four CDK synth contexts passed. Cached pinned bundling dependencies required
  `UV_OFFLINE=1`; initial restricted-network failures were not implementation passes.
- All implementation CI succeeded:
  [CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35752151440),
  [NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/35752151394),
  [Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/35752151538).
- Design and execution: [D-113 candidate](../reviews/game_restore.md),
  [runbook](../runbooks/game_restore.md). Their pending real-qualification status remains correct.
- This pause note is intentionally uncommitted. Existing user changes in README,
  delivery plan, decisions, create-terralith runbook and two create-terralith
  evidence files were preserved and excluded from the implementation commit.
- Learning Wiki synchronization was deferred at this user-requested interruption;
  the RESTORE qualification slice is unfinished. Do not claim it was synchronized.

## Real dev work completed

Account `385526546525`, region `ap-northeast-1`, canonical profile `wishicraft-dev`.
Target EC2 `i-04fc0629dc4ea466e`; original Data EBS `vol-03ac9f534326c345c`.
No CloudFormation deployment, IAM change, runtime-helper update or snapshot mount occurred.

1. Initial protection BACKUP `op-d0383b17-8783-43fd-a7aa-b47fcd299a2a` failed with
   `BACKUP_SNAPSHOT_CREATE_FAILED`. EC2 explicitly rejected creation; no snapshot
   with this Operation tag existed. Both workflow/Lambda error notifications were real.
2. Read-only deployed IAM inspection found CreateSnapshot request-tag Game IDs are
   limited to `game-vanilla-main` and `game-vanilla-secondary`. The selected Game
   was create-terralith. This existing dynamic-Game BACKUP inconsistency remains
   unresolved; do not silently broaden IAM or describe BACKUP as generally fixed.
3. Within existing permissions, selected Vanilla B via normal Admin START
   `op-7a131891-e8b7-4c7a-879e-33c76f9d91af` (SUCCEEDED), then normal STOP
   `op-e6dd3a9f-3e0b-4493-8294-1af6090a0161` (SUCCEEDED).
   This started the existing generation, not a restored generation.
4. Protection BACKUP `op-ecd6c456-7db5-4766-94eb-0004fb4f92cc` SUCCEEDED.
   Snapshot `snap-0a1da731e1fe40f44`, start `2026-09-22T16:32:10.626000Z`,
   completed/encrypted, shared-volume provenance covers all five current Games.
5. Formal maintenance `restore-dev-20260923-v1` began with a four-hour TTL and
   ended safely at `2026-09-22T16:44:51Z` after the pause request. No maintenance boot.
6. Durable RESTORE audit journal created at phase **PLANNED**:
   `op-c049a9e8ca40dd4dda1fa71b246e484ff6164c1f16a00ca774ea8f5d95f7fdcd`.
   Request ID `restore-dev-20260923-vanilla-b-v1`. This is a maintenance-admin
   journal in SystemState, not a running lifecycle workflow or Current Operation.

## Planned source and target — not yet restored

- Game: `game-vanilla-secondary` (Wishicraft Vanilla B).
- Source snapshot: `snap-0be8e05ab05d70e84`.
- Source BACKUP: `op-059abd53-92a6-469a-abb2-6eb8dfe5da8e`.
- Source timestamp: `2026-09-12T10:31:35.625000Z`; source generation 1.
- Source path from provenance: `/srv/minecraft/games/game-vanilla-secondary/server`.
- Current generation remains 1, current ID `op-2fc1bd34-b2ab-45a4-b3f8-95a53d828dcf`.
- Current path: `/srv/minecraft/games/game-vanilla-secondary/worlds/op-2fc1bd34-b2ab-45a4-b3f8-95a53d828dcf/server`.
- Planned target generation 2, using the RESTORE operation ID as the new world ID.
- Both source/current package identities verified as Vanilla Minecraft 26.2,
  package `vanilla/initial-fixed-version`.
- Source actual tree, readonly mount, copy/hash, PREPARED, commit, restored START,
  READY and host initialized state have **not** been verified in dev.
- No temporary volume, restore SSM command, staging directory or new world was created.
  Previous generation selection remains unchanged; no world was overwritten.

## Final observed state

At `2026-09-22T16:46:00Z`: Desired STOPPED / HEALTHY, EC2 stopped, maintenance ENDED,
no Lock or Current Operation, no running workflow, active SSM command/session or DNS.
All three queues (`discord-message-dlq`, `discord-message-retry`, `status-executor-dlq`)
had zero visible/in-flight/delayed messages. No volume carried this RESTORE Operation tag.
Vanilla B remains MATERIALIZED with its original generation 1 selection.
Subsequent alarm readback: **49/49 OK**, including maintenance suppressor and both
BACKUP failure alarms. Notifications were not disabled or forced to OK.

The selected Game changed from create-terralith to Vanilla B through normal START/STOP.
No other Game was started, restored, rewritten or rolled back.

## Resume safely

1. Re-read repository instructions, current status and D-113/runbook. Reuse confirmed
   tools only in the same environment; canonical credentials/account must be checked again.
2. Read current AWS state and Game/provenance; do not assume this pause evidence is fresh.
3. **Re-evaluate the pre-RESTORE protection backup after this interruption.** A stopped
   world may have been started since the journal was created. Existing plan retries
   return the frozen plan before checking backup freshness, and subsequent checkpoints
   do not establish that its backup still protects content changed between leases.
   Review/harden this cross-maintenance resume boundary before advancing the old plan.
   Do not treat identical Game world metadata as proof unchanged world content.
   With the untouched PLANNED request here, a new qualifying BACKUP and a new request
   can establish a fresh plan; leave the old audit record intact and documented unused.
4. Resolve the dynamic-Game BACKUP IAM gap as a separately reviewed narrow change if
   needed; do not repeat the known rejected create-terralith BACKUP or broaden IAM silently.
5. Begin a new formal maintenance lease and observe suppression before host work.
   Continue temporary-volume/create/attach/readonly mount/tree validation/prepared/commit,
   cleanup/closeout, normal START/READY/readback/STOP according to the runbook.
6. Capture other-Game and previous-generation hashes before/after work, exact source
   content proof, rollback availability and complete final safe state. Update accepted
   qualification status only after these pass. Commit final docs/evidence, push/CI and
   sync Learning Wiki against finalized HEAD when the slice is actually complete.

## Local evidence

Fresh exclusive-write evidence root (no secrets):
`/var/folders/8l/yptb5b71055c5cqxbzn5qw300000gn/T/wishicraft-restore-dev-v1-_y86euis`.
Key files: `operation-a7bc557d.json` (protection BACKUP success),
`checkpoint-plan-01199f72.json`, `maintenance-begin/`, `maintenance-end/`,
`pause-final-cdefc28d.json`, `alarms-d3256079.json`.
Temporary observation/checkpoint scripts are diagnostic helpers, not canonical API contracts.
The prepared `host_hash_read.py` was never sent to SSM.
