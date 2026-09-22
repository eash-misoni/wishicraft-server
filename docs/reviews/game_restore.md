# D-113 Game RESTORE

Status: implementation candidate; production qualification has not run.
Requirements: BAK-002/003/004/006, OPR-001/004/007/010, EC2-007/012 and the
2026-09-23 RESTORE request. This is one operator-assisted restoration slice.

## Existing authority and layout

BACKUP snapshots the encrypted Data EBS, currently owned by the frozen Phase 1
stack and attached by the Target stack. Root EBS, receipt and live control-plane
tables are not snapshot contents. Never replace, detach, format or roll back that
production volume. Snapshot creation belongs to BACKUP, not CloudFormation.

The non-TTL Backups table retains a create-only `SNAPSHOT#id` evidence record and
an `OPERATION#id` uniqueness record. Schema 2 adds `recovery_json` and its SHA-256,
bound to the snapshot tags. It contains the snapshot-time Games, world references,
package/runtime metadata and renderer output. That digest authenticates the
description, **not the bytes of a world**. No pre-existing per-world tree digest is
claimed. The original Operation may expire; the durable verified pair remains.
RESTORE revalidates the pair, full metadata, account, project/stage, source volume,
timestamp, completed state, encryption and standard tier against EC2.
Legacy schema 1 lacks adequate shared Game/package evidence and is rejected.

`world.current_id` resolves through `world_reference.data_source`: absence selects
`games/<Game>/server`; an ID selects `games/<Game>/worlds/<ID>/server`. Numeric
`world.generation` historically stayed 1 across RESET. Therefore numeric generation
alone cannot identify a historical world. RESTORE records both it and the full
validated current_id/path. Managed source owner metadata must be initialized and
match the exact Game/path; dynamic initial owner must match snapshot-time creation.

Copy the package-defined level directory in its entirety, including all dimensions,
players, inventories, advancements, datapacks, scoreboard and mod world state.
NeoForge additionally preserves `config`/`defaultconfigs`. Paper preserves the four
reviewed IMPORT config files; its fixed level is `wishinkaiwai`, not `world`.
World-generation/gameplay properties reuse IMPORT's allowlist. Unknown trees,
links, hardlinks, other mounts and special files fail closed. NBT version must
match the immutable package. No version migration or cross-Game clone is allowed.

## Contract

RESTORE makes a new prepared generation from historical content. RESET generates
a new world. RESET enablement does not authorize or prohibit administrator RESTORE.
Current Game, registry, package, creation and access policy stay authoritative.
The snapshot Game record is evidence, never a replacement Game item.
The selected world's seed/content may be historical; the CREATE configuration is
not rewritten. Package identity includes the full definition/digest and runtime
version. Historical fixed Vanilla identity can be reconstructed only from its
explicit snapshot manifest and fixed package reference.

No snapshot whitelist, OP/ban file, Discord or Web permission is copied. Current
server security properties and OP/ban files are preserved; current whitelist is
projected through the existing normal START path. Current server files are never
included in operator output. RCON and other secrets remain local existing files.

The initial operator path uses canonical AWS credentials and the D-111 maintenance
admission fence. There is no new application Lambda, role, state machine or UI.
This is not an unadmitted START: BACKUP/START/STOP always use ordinary Admission.
RESTORE itself is a durable maintenance-admin operation recorded under
`SystemState.system_id=restore#<operation>` with `record_type=RESTORE`. It is not
silently inserted into the existing workflow Operation enum. Ordinary players have
no RESTORE route. This choice avoids holding a workflow Lock during maintenance,
which would invalidate D-111 suppression eligibility.

Begin requires fresh STOPPED/HEALTHY, actual EC2 stopped, no Current/Lock/workflow/
SSM/DNS. Host work requires maintenance-controlled EC2, no container/listener and
the normal host flock and Data EBS mount guard. Every journal/selection transaction
checks the exact active maintenance lease, Desired STOPPED and no Current/Lock.
Host payloads are fixed, authenticated operator SSM commands with expiry, instance,
runtime/package and current-world checks; they never accept arbitrary source paths.
The maintenance end procedure refuses active SSM. Expiry stops new mutations and
restores notification eligibility semantics; it does not discard recovery records.

Require a successful pre-RESTORE BACKUP no more than one hour old, newer than the
last Desired transition, and matching current Game world/package. This permits a
proven unchanged stopped-state backup, not an age-only assumption. Otherwise run
one ordinary BACKUP before maintenance. Do not embed BACKUP in a new state machine.

## Preparation, commit and recovery

The durable request ID derives one operation identity. Reusing it with another
Game/snapshot is a conflict. The immutable plan stores source snapshot/backup/time,
Game/path/generation, package identity, previous selection, destination and time.
Journal revisions use CAS. No TTL can make a request allocate again.

Temporary encrypted gp3 EBS is created in the host's configured AZ using a stable
CreateVolume ClientToken and inline project/stage/system/Game/operation/snapshot
tags, after journaling intent. Discovery and reuse require exact identity; duplicate
or unknown volumes stop the operation. No persistent CloudFormation resource or
application CreateVolume/AttachVolume/DeleteVolume permission is added.
See [AWS CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html).

Resolve the Nitro device by exact EBS serial. Set block-device read-only and mount
XFS `ro,nouuid,norecovery,nodev,nosuid,noexec`; verify the actual mount. Never format,
repair the filesystem, change UUID or replay the source journal. A snapshot whose
tree cannot be read without recovery is rejected.

Reuse IMPORT SHA-256/tree hashing and prepared receipt/rename/fsync pattern, plus
RESET's safe tree and root-owned owner helpers. Archive extraction is unnecessary.
Each copy attempt has a fresh private staging directory. Validate source and copy,
compare full world tree hashes, fsync data/directories, persist validation receipt,
rename only into an absent destination, then persist prepared owner. Exact receipt
and hash recover rename response loss. Source/current content is unchanged.
Only recorded partial attempts may be cleaned. Unknown residual directories stop
cleanup rather than being deleted by a broad name match.

After host preparation and normal EC2 stop, one DynamoDB transaction moves the
Game world reference and journal to COMMITTED. It compares the old world and current
package and requires ACTIVE/MATERIALIZED. Before that transaction selection is
unchanged. The destination number is N+1, or the next unused number after rollback;
source generation numbers are never adopted. `world.generation_counter` records
the allocation high-water mark. It is not a snapshot-restored counter.

Clean up the exact temporary volume only with EC2 stopped: non-force detach,
describe convergence, durable delete intent, delete, then NotFound read-back.
Errors persist `cleanup=FAILED`; existing ID/tags/intent stay available. Missing
volume without prior delete intent is an anomaly. Do not end maintenance with
unresolved resources. Cleanup and selection are separate checkpoints.

Close maintenance, then ordinary START selects the restored path. READY/Reconcile/
heartbeat and the existing Game MATERIALIZED record must agree; a prepared owner
alone is not successful gameplay proof. Normal STOP must complete afterwards.
The separate START Operation's runtime_target links its execution to the restored
generation. Do not call COMMITTED evidence READY or mark RESTORE qualified early.

On START failure, observe/finish the exact interrupted operation and normally stop
before any rollback. Under a new formal maintenance lease, explicit rollback CAS
selects the preserved previous world. It does not delete the restored generation,
decrement the allocation high-water mark, start Minecraft or hide the failed START.
Unknown runtime/unfinished SSM prevents rollback. Automatic rollback is excluded.

RESTORE never runs generation cleanup. Its destination and previous managed owner
are protected; the legacy server remains the permanent anchor. Existing RESET
cleanup respects protection. Removal of this recovery protection is a future
explicit retention decision. Snapshot retention remains dry-run-only/newest-seven
shared group. During maintenance ordinary RETENTION is fenced. After successful
copy, historical provenance may outlive its source snapshot; RESTORE does not
permanently pin snapshots or authorize their deletion.

## Read-only candidate inventory (2026-09-23 JST)

Caller account matched dev configuration. Three normal shared snapshots were
confirmed completed/encrypted, owned by the configured account and sourced from
the configured Data EBS. All contain both legacy Vanilla Game records.

| Snapshot | Backup time UTC | B source | B current |
|---|---|---|---|
| `snap-021079b3e3843652f` | 2026-09-12 03:31:02.313 | generation 1, legacy server | generation 1, managed RESET path |
| `snap-0be8e05ab05d70e84` | 2026-09-12 10:31:35.625 | generation 1, legacy server | generation 1, managed RESET path |
| `snap-07106a22069868738` | 2026-09-12 12:49:47.313 | generation 1, current managed path | generation 1, managed RESET path |

Preferred test Game: `game-vanilla-secondary` / Wishicraft Vanilla B. Preferred
source: `snap-0be8e05ab05d70e84`, BACKUP `op-059abd53-92a6-469a-abb2-6eb8dfe5da8e`.
Current world ID: `op-2fc1bd34-b2ab-45a4-b3f8-95a53d828dcf`. Proposed target generation
2; new operation-derived path. This inventory is not mounted-tree proof.
The three newer dynamic Games, including `vps-survival`, are absent from these
historical shared records and are ineligible sources from these snapshots.

## EXPORT boundary

Future EXPORT can consume the same package-defined, validated durable-content tree
and tree receipt, then create a bounded archive. Export must separately decide
secret/config/access-policy exclusion and point-in-time capture. No EXPORT or
generic archive endpoint is implemented here.
