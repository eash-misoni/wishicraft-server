# Operator Game RESTORE

[D-113 contract and candidate inventory](../reviews/game_restore.md).
Production qualification is pending. Do not treat repository tests as a mounted
snapshot, successful START or final cleanup proof.

## Execution checkpoints

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
7. Run `attach` until attachment is ATTACHED; transition states are observations,
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
   the failed command before permitting the same plan's next copy attempt. Timeout,
   cancellation and outcome unknown require investigation, not automatic retry.
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
    Lock/Current/workflow/SSM/DNS absent, both queues empty, previous generation
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
CI and real dev evidence remain to be recorded.
Docker CLI is unavailable locally; do not label mocked mount/EC2 tests real integration.
