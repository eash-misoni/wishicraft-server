# Minimal Game Creation release gate

Repository preparation only. No production write or positive CREATE has been performed.
[D-105 contract](../reviews/minimal_game_creation.md) owns semantics. D-104 production remains Completed.

## Validation and preflight

Validation results and exact finalized HEAD/CI are recorded in the preparation evidence at handoff.
Local Docker CLI is absent; the existing disposable Linux CI runner executes the pinned itzg image.
The creation scenario traverses the real metadata transaction serializer, first START, same-run
retry, first SWITCH to another synthetic registered Game, normal STOP/restart, and A/B data checks.
AWS/SSM/systemd/mount remain simulated in Docker; this is not production E2E.

Read-only preflight v2 at 2026-09-13 11:43 UTC, root
`wishicraft-minimal-game-preflight-v2-ts5e33rr`: canonical dev profile Account matches stage;
Web/CP/Target UPDATE_COMPLETE, A selected STOPPED/HEALTHY, no current/Lock/running workflow,
3 queues empty, 45 alarms OK, 9 Snapshots, 16 durable provenance items. A/B records match D-104
hashes exactly under its canonical JSON serialization. v1 failed table-name lookup before complete
evidence; its directory is retained and is not a successful preflight result.

The deployed physical environment is the existing **dev stage in production use**. prod YAML remains
unconfigured; do not infer prod IDs or deploy it. Target is `i-04fc0629dc4ea466e` from CloudFormation.
Data EBS is the configured existing volume, not a new per-Game volume. EC2 is stopped, so fresh
filesystem capacity and installed host bytes require approved maintenance start/read-back. Do not
claim stopped-host unknown capacity as zero or as a successful live capacity check.

## Approval scope and sequence

First production write requires explicit approval of the finalized release diff and this sequence.
No internal step creates a new approval boundary within a concrete approved scope. Stop for caller
mismatch, unknown artifacts/owners, unresolved execution, broader IAM or unexpected infrastructure.

1. Recheck canonical STS identity against stage; repeat read-only state/registry/lock/workflow/queue/
   alarm/provenance inventory. Capture deployed templates/configuration and Lambda concurrency.
2. Drain Web/Discord/Admission writes using the existing bounded maintenance method. Confirm no
   active workflow/Lock/SSM before continuing. No new Game, BACKUP or RETENTION deletion is required.
3. Deploy reviewed Target role Games GetItem, with no instance replacement, volume or network change.
4. Maintenance-start only the existing stopped Target. The targeted runtime unit requires an owned
   run, so this is not permission to start Minecraft. Check mount/UUID/EBS, free >=4 GiB, no runtime
   container/listener/systemd job, and the exact stopped receipt. Capture its full JSON without secrets.
5. Build the bounded host upgrade with `python -m wishicraft.game_creation_migration --output <new-root>
   --receipt <verified-receipt.json>`. Verify the receipt's target against the latest completed
   Operation, and the generated three destination/hash/predecessor entries against review.
   The generator reproduces D-098's applied configuration and `c124525` wrapper bytes. Any mismatch
   stops before modification. It does not migrate data or rewrite A/B Game records.
6. Stage the exact bundle at `/var/tmp/wishicraft-game-creation-v1`, then execute its existing
   inactive-only installer. It matches complete predecessor bytes/owner/mode and stopped receipt,
   saves predecessor artifacts under `game-creation-v1`, atomically replaces only the contract and
   wrapper, and creates the absent helper. Resume only absent/canonical/exact-predecessor entries.
   Read back hashes, same receipt, stopped runtime and unchanged A/B/world/owner data.
7. Stop the maintenance EC2 without starting Minecraft; confirm stopped and DNS absent.
8. Deploy exact CP assembly with stage=dev, phase=8, deployment=control-plane, two_games=true,
   reset=true, game_creation=true. Confirm function configuration, narrow IAM, unchanged workflow
   definitions and no replacement resources. Then deploy Web with game_creation=true.
9. Restore captured admission concurrency; perform safe unauthenticated/foreign-origin/old-origin
   rejection and authenticated read-only registry/status checks. Negative authenticated CREATE tests
   must use inputs guaranteed rejected; do not send a valid positive payload by accident.
10. Compare A/B metadata, worlds/generations, EBS attachment, Snapshot/provenance inventory and final
    STOPPED/HEALTHY/no Lock/queues/alarms. Save evidence, commit closeout, CI and Wiki synchronization.

Live diff must use `cdk diff --change-set=false` and exact synthesized assemblies. Diff itself does
not authorize deployment or create a changeset. Runtime files outside CloudFormation are separately
reviewed through the generator/installer; a CDK code diff does not prove host upgrade completion.

## Positive production E2E

Preferred: deploy plus safe negative/read-only E2E, then perform positive CREATE when the user first
wants a real persistent Game. This avoids permanent throwaway test metadata. Local/CI/Docker
validation must pass first. Report production positive CREATE/materialization as **not yet exercised**;
do not label the slice fully production Completed until the agreed closeout conditions are satisfied.

Alternative: the user supplies only real display name, initial numeric seed or random, and RESET
on/off. CREATE registers that real Game, then stops for metadata/Operation read-back and A/B/EC2/
filesystem noninterference checks. CREATE approval does not authorize START. A separate explicit
START/SWITCH can be approved for that target after safe state, known player count zero, no Lock,
and sufficient capacity checks. Never raw-delete a production test Game as cleanup.

## Rollback and loss boundary

No database or world migration is needed. Before registration, restore captured CP/Web/Target
configuration and exact saved host predecessor artifacts only under the same inactive/receipt
checks. Do not restore or replace Data EBS. Unknown deploy result requires read-back before retry.

After registration, use reviewed `create_disabled=true` on CP and Web while retaining
game_creation=true. New CREATE stops; dynamic listing/start/recovery remains available. Keep
metadata/owners/worlds and apply a forward fix. A/B-only rollback would omit dynamic Games from
future backups, so it is not an acceptable post-CREATE rollback. Existing snapshots remain protected.
No DeleteSnapshot, Game delete, unknown data cleanup or rollback of another Game is authorized.
