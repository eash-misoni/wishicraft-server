# Interrupted old-run stop recovery

Accepted scope: explicit operator recovery of the retained D-109 failed first START.
Repository qualification and production execution are separate checkpoints below.
This is not a new START, a successful READY observation, or Game materialization.
SSM READY probe code, normal Admission/workflows, installed runtime files and all
package/manifest identities remain unchanged.

## Incident and evidence boundary

Old run/START: `op-76571b92-0fe6-47a9-b31e-00a0e0048e36` (FAILED).
Game: `game-eb068843cb6ca81759cb6dd9544ee6b6bd228307a0e8d0e065d879bf19f3312f`,
ACTIVE / UNMATERIALIZED / generation 1. Container:
`83896a0ff67b05067bcd01a408b5c0f1bcb85b5dca1bc12c459d9e92a288ad9e`.
The target data source is `/srv/minecraft/games/<Game>/server`; `world/level.dat`
already exists. The initial owner contains `plan`, `files`, `phase=prepared`.
Its immutable plan includes creation provenance, seed, Game and data source.

The complete old runtime receipt has only `target` and `phase=running`. Target
contains instance_id, game_id, data_source, config_digest and run_id. It has no
`stop` member. The old container exited 0, without OOM/error, at
`2026-09-15T11:02:22.110025226Z`; original StartedAt is
`2026-09-15T10:50:07.386407986Z`. The previous canonical SSM result and Minecraft
logs show explicit save and graceful termination, but the out-of-band containment
never wrote the canonical durable save intent. These logs, filesystem mtimes and
the current exited state are supporting evidence, not a replacement save receipt.

`finish_stop` requires `phase=stopping`, `stop.save_confirmed=true`, exact
`stop.container_id` and `stop.started_at`, plus normal physical exit, runtime unit
inactive/success, no listeners, exact package/config/mounts and retained world.
Every missing stop field makes the present running receipt insufficient.
`removal_ready=true` is written only after those checks, before exact container rm;
the final receipt becomes stopped only after absence is observed again.
D-074 only closes owned/stale Control Plane Operations; it cannot manufacture host
save proof. D-096's old-v1 cleanup expressly rejects an existing v2 receipt.

## Limited contract

`wishicraft.interrupted_stop_recovery.recover` is an operator library, not a Lambda
or a host command admitted by normal operations. Transport a reviewed copy to a
new private root with its SHA-256 and immutable plan. Import only the independently
hash-verified installed operation-v2 and its installed helpers. Do not install a
new common runtime or use repository copies as evidence of installed bytes.

The plan has exactly schema_version=1, target, container_id, original_started_at,
game_sha256, prepared_owner_sha256, package_digest and world_directory_inode. The
world directory inode is captured on the verified retained filesystem and must
remain the same across recovery/retry. Record digests use sorted
JSON; package digest retains its existing canonical representation. The owner
hash normalizes only its phase to prepared, permitting the existing canonical
initialized transition without changing the immutable plan/files.

Before **every invocation**, the operator must verify canonical AWS caller, three
closed ingress functions, Desired STOPPED, no Current Operation, no active workflow,
no active SSM/session, empty queues, no DNS, stable instance/volumes and unchanged
records. During execution the only allowed active SSM is this recovery invocation.
Hold this exclusive maintenance window; do not run another operator action.
The production transport's operator_gate must enforce a bounded, fresh preflight
authorization for this exact plan, never a permissive default callback. Host IAM
does not permit reading SystemState; do not broaden IAM or pretend the host directly
verified those controller-side conditions. Host checks under its usual flock
independently re-read the absent lease, exact FAILED old START and unchanged Game.

The host validates actual instance, manifest/config/Compose/env digests, verified
mount, root-owned initial owner and existing world. There must be exactly the
reviewed container across the complete Docker inventory, with unchanged Game/run,
package/mount/env identity, persistence and restart policy=no. Unknown data,
another container, active lease, different Game/generation/package or failed
observation stops the operation before lifecycle effects.

Recovery stores `/var/lib/wishicraft/runtime/interrupted-stop.json`, a root-owned
0600 sidecar containing the exact plan and reacquiring/saved/finalized phase.
It is a stop-recovery proof, not Game metadata, a generic event journal or permission
to adopt another run. Retain it with the terminal receipt; a different plan conflicts.

1. An existing canonical stopping receipt may be finalized after all current checks.
   A recovery sidecar whose fresh save completed before receipt publication may
   also resume. A running receipt plus logs alone never grants finalization.
2. If proof is absent, persist the same-target recovery intent before effects.
   Restore only the old run's volatile runtime context and canonical ephemeral
   secret inputs. `docker start <exact existing ID>` retains container/run/world;
   no Compose up, replacement container, new Game/run/generation or world preparation.
3. Verify that same container/package, healthy runtime and exact zero-player RCON
   response. Send canonical `save-all flush`; require successful exit and the known
   success response, then recheck the same StartedAt. Persist fresh save proof in
   the sidecar before publishing canonical `phase=stopping` with that proof.
4. Gracefully stop that exact ID using the existing 150-second Docker timeout.
   Abnormal exit, OOM, remaining listeners or an unproven process never permits rm.
   Invoke unchanged `finish_stop` for persistence validation, removal intent, exact
   non-force/non-volume rm, ephemeral cleanup and terminal stopped receipt.
5. Keep DB UNMATERIALIZED and generation 1. Existing `finish_stop` may advance the
   initial owner's phase from prepared to initialized after checking level.dat;
   its plan/files remain unchanged. This physical-world protection is distinct
   from Control Plane MATERIALIZED, which still requires successful READY.

An actual restart/save can update logs, session/save timestamps and normal world
files. Preserve the same directory/world identity; do not claim byte-identical
world contents across a Minecraft execution. A/B must remain byte/metadata unchanged.

## Interruption and retry

| Checkpoint | Same-plan retry |
| --- | --- |
| Restart reply lost | Reobserve the same ID; do not create another container |
| Save reply lost / proof not persisted | Obtain a fresh save response; never infer success |
| Sidecar save proof durable, receipt still running | Verify same process, publish stopping proof |
| Stopping proof durable, container running | Graceful stop the same ID |
| Graceful stop done | Existing finish_stop validates actual normal exit |
| Removal intent/rm reply lost | Existing removal_ready permits same-ID absence convergence |
| Receipt stopped, sidecar final write interrupted | Matching proof plus no container is success |
| Already finalized | Same plan and terminal proof validate as a lifecycle no-op |

An EC2 interruption does not bypass process matching or exit checks. If the saved
proof's StartedAt differs from the container's current process, preserve all data
and stop for review. No fresh save means no fabricated terminal state.

## Already-stopped STOP and follow-up

The existing EC2-already-stopped branch intentionally converges Desired/DNS without
inventing a target or booting the host. Its success proves infrastructure stop,
not that an inaccessible host receipt is terminal. This is a known visibility gap,
not evidence that the receipt was finalized. A future local hardening should expose
unresolved host lifecycle separately when known; automatic boot, new durable state
or normal STOP redesign is outside this recovery. Do not label the previous shortcut
as successful running-host STOP qualification.

## Release / closeout gates

Unit tests exercise proof absence, canonical proof reuse, fresh proof, identity and
concurrency rejection, reply loss and each durable checkpoint. Real NeoForge Docker
qualification starts the old container again, saves/finalizes it and verifies the
UNMATERIALIZED record and same world directory before normal lifecycle tests resume.
Production execution requires full tests, lint/format/type/synth and both CIs success.

No CloudFormation deployment, IAM change, new AWS resource, installed runtime change
or digest migration is needed. Production runtime digest remains
`64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`; package digest remains
`720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`.
After proof/container cleanup, normally stop EC2, observe STOPPED/HEALTHY, 45 alarms OK,
no Lock/Current/workflow/SSM/session/DNS and empty queues. Verify A/B, Game records,
volume identity, nine snapshots and sixteen provenance records. **Keep ingress closed.**
No SSM READY fix, new START, materialization commit or client connection in this slice.

## Observation checkpoint — 2026-09-15

12:12:21 UTC preflight: STOPPED/HEALTHY, 45 OK, no concurrency/DNS, queues empty,
9 snapshots/16 provenance. Read-only maintenance inventory at 12:15:10 UTC found
the exact old container, restart policy=no, static runtime unit and no Java/listeners.
Game tree hash `502f37de99fdb5e38cb41c525303021686d04a82480b5cf2a1ab44dbe645a4cf`
and A/B hash `f2c62614f20c6b18b399a73d0f129d99bb3ab47ac0f36b963c84cb812cf8696c`
matched the previous stop. Receipt and ownership were not changed. EC2 was normally
stopped. The maintenance DesiredStoppedEc2Running alarm naturally returned OK on
the subsequent zero datapoint. This was the observation-only checkpoint; execution is recorded separately below.


## Production recovery — 2026-09-15

Qualified implementation `e0c25c17caeb1cd1721fc76b121279800942fa9a`, fixture correction
`ab15312d813ffe36e5ec25aa5b23e934db4ec428`. Full local suite: 1436 passed;
new recovery unit cases: 18; lint, 281-file format check, 209-file type check,
production-context Control Plane synth and Python 3.9 syntax check passed.
Local Docker daemon was unavailable. Both release CIs passed:
[standard 34969679378](https://github.com/eash-misoni/wishicraft-server/actions/runs/34969679378),
[real NeoForge 34969679392](https://github.com/eash-misoni/wishicraft-server/actions/runs/34969679392).
The earlier Docker run 34969252275 failed because the test config had mode 0644;
the fixture was corrected to canonical 0600, without weakening host validation.
Successful Docker evidence includes
`OLD_RUN_FRESH_PROOF_FINALIZED_WORLD_AND_UNMATERIALIZED_GAME_RETAINED` and
`HOST_NEOFORGE_START_SWITCH_RESET_WHITELIST_PASSED`.

12:43:31 UTC fresh stopped preflight passed. Maintenance reinspection verified the
same exited container, full receipt/owner, Game tree, A/B tree and all eleven
installed runtime artifacts. A bounded 15-minute operator gate at 12:52:02 UTC
rechecked closed/drained ingress, no active work and all unchanged durable records.
The reviewed operator source SHA-256 was
`c563e9f9d3ff089a22ab551d85494a0871b0423827e19b74c8317686a5c91514`;
immutable plan SHA-256 was
`9e3faf29b1d75f1d0c07e64058cfd78c772ca7166a3b1b899ebcbb5c5c0f8c33`.
The temporary root-owned transport also rechecked installed hashes and the runtime
unit before each gate; it did not install/replace any host artifact or deploy a stack.

Recovery SSM `f0f8ccf9-4bef-4166-a59d-69f1b48a6445` succeeded at 12:57:39 UTC.
Because no existing durable save proof was available, it restarted only the exact
old container with the same old run identity. Fresh process StartedAt was
`2026-09-15T12:57:05.448260585Z`. Zero-player RCON and canonical save-all flush
succeeded; fresh durable proof was stored before graceful stop. Unchanged
`finish_stop` validated normal exit, set removal_ready and removed that exact
container without force or volume deletion. No new START/STOP Operation was created.

| Evidence | Before | After |
| --- | --- | --- |
| Runtime receipt | running; target only, no stop proof | stopped; same target; exact container_id, fresh started_at, save_confirmed=true, removal_ready=true |
| Recovery sidecar | absent | finalized, exact plan and fresh canonical proof |
| Physical container | exited old container | absent after canonical lifecycle cleanup |
| Initial ownership | prepared | initialized by existing finish_stop; immutable plan/files unchanged |
| World directory | existing saved world, inode 4316448 | same path/inode; normal restart/save updates permitted |
| Game DB | ACTIVE / UNMATERIALIZED / generation 1 | unchanged; no materialization commit |
| Package/cache/mods | verified existing files | identities, hashes and mtimes unchanged |

Same-plan retry SSM `1d1013d7-1e80-485a-a50e-bbbb4b078672` succeeded as a lifecycle
no-op: receipt_before equals receipt_after. Readback SSM
`7504efde-79f4-435d-9a13-1b2507d034fd` confirmed terminal receipt/finalized sidecar,
no container/Java/listener, empty whitelist JSON, unchanged A/B tree hash and all
installed artifact hashes/modes/mtimes. Package owner/projection remained identical.
No world deletion, regeneration, generation increment or Game/Operation rewrite occurred.
The prepared world remains available for the separately reviewed future START.

DesiredStoppedEc2Running and RuntimeObservationUnknown alarmed during maintenance;
the latter's 12:46/12:51 datapoints preceded the recovery command. Neither alarm was
suppressed or manually set OK. EC2 normal stop followed successful finalization and
readback. Ingress remains closed; SSM READY import correction and new START remain
separate work. This recovery does not establish client readiness.

Post-stop readback at 13:04:40 UTC confirmed EC2 stopped and the 13:03:04 UTC
canonical observation STOPPED/HEALTHY with no discrepancies. All seven Game/registry/
policy records, 79 historical Operations and sixteen provenance rows were identical
to baseline; nine snapshot metadata entries, volume metadata and all four live
CloudFormation templates were unchanged. Current Operation/Lock/workflow/SSM/session/
DNS were absent and all three queues were empty. The three ingress functions retained
reserved concurrency zero. No stack deployment occurred.

Final stopped gate at **13:06:50 UTC** passed with **45/45 alarms OK**, HEALTHY,
EC2 stopped, unchanged records and no active work/DNS. All maintenance alarms
recovered naturally. Production recovery is complete; ingress stays closed.
Next slice may review/fix SSM READY resolution and formally START the retained
prepared world. This slice did not perform either action.
