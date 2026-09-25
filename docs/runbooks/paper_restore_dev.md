# Paper RESTORE: separately authorized limited dev proof

2026-09-25. **Pre-execution qualification; AWS RESTORE not yet performed.**
Use the existing [D-113 contract](../reviews/game_restore.md) and
[operator checkpoints](game_restore.md). The first Vanilla B proof and its
restriction against vps-survival remain historical authority for that first run.
This is a separate user-authorized Paper run, not a new RESTORE implementation.

## Fixed scope

Baseline `8a12b2a3aaac2aa5ab5dd8602c66a35ee1d5ac23`, dev / account 385526546525 /
ap-northeast-1 / wishicraft-dev / wishicraft-main. Re-resolve ownership, not names alone.
Candidate target `i-04fc0629dc4ea466e`, Data EBS `vol-03ac9f534326c345c`.
Game vps-survival:
`game-bfd8409b3f8a4d1b591231c3490d9b646f546294ca11837cad74616ed33eaf21`.
Same immutable Paper 26.1.2/build 53 package, existing image/Java and access policies.
Source `snap-0aac363f3ce09e05a`, formal BACKUP
`op-4236596e-a436-4c99-833b-33b39f89dab8`; independently verify durable provenance pair.
Source is the dev snapshot, not the live VPS or original IMPORT archive.

Before AWS writes, qualify fixtures/reader, freeze commit/CI and clean execution
worktree, and record the baseline diff and all generated payload hashes. A core
RESTORE/validator/runtime defect stops this slice before AWS changes. No IAM,
deployment, helper upgrade, snapshot deletion, Data EBS replacement, other Game
operation or VPS access is authorized.

## Paper-specific content and authority

Use `wishinkaiwai` intact, including `dimensions/minecraft/{overworld,the_nether,the_end}`
and `players/{data,stats,advancements}`. Never convert to older Paper split-world paths.
The source initial-owner must match source creation/Game/path. Current package and
creation remain authority; source Game metadata never replaces the current record.
An absent current_id stays absent when rollback restores previous_world; no invented
legacy identifier. Restore allocation advances generation_counter; rollback does not lower it.

The world tree includes dimension `paper-world.yml`, player data, datapacks and
saved game rules/borders. The existing Paper copy allowlist additionally preserves
`config/paper-global.yml`, `config/paper-world-defaults.yml`, `bukkit.yml`, `spigot.yml`.
Current server security properties and OP/ban files remain current, and ordinary
START projects current whitelist. Only the existing IMPORT gameplay-property
allowlist is transferred from source server.properties, never the whole file.

## Frozen supplemental reader scope

The existing reader keeps its 100,000-entry / 16-GiB / depth-32 traversal,
20,000-byte output and 600-second process bounds (maximum 900 seconds). Use its
exact compressed `python3 -c` execution form, with Python 3.9 roundtrip coverage.
It writes no bytecode, world, owner, receipt or DB. Never expose Docker environment,
server.properties or raw player records. Each invocation has its own evidence root.

For Paper, record each dimension's existence, terrain-region count and first two
lexically selected region fingerprints separately. All three player groups get
counts, canonical filename-set hashes and aggregate filename/content hashes.
All player `.dat` files are parsed with the unchanged NBT parser: selected inventory,
ender chest, position and dimension are represented only by aggregate semantic
hashes and presence counts. Integer canonicalization uses decimal strings, never
JavaScript Number. Opaque NBT array bytes remain opaque hashes, not coordinates.
Missing fields stay missing; a readable file is not proof every field was decoded.

Dimension and world `data/minecraft/*.dat` metadata have a complete aggregate hash;
game-rule/border/world-generation files also retain exact relative paths and
content hashes. Compare observed filenames without inventing a layout.
Datapack trees and the seven fixed Paper config paths have separate fingerprints.
Live fingerprints that change during reading are explicitly unstable, not equality proof.

Predefine two selections per checkpoint if needed for output size: target content
(original and prepared paths, at most two targets) and protection-only hashes
(other four Games plus Vanilla B's retained restored world). Select the latter with
`content=false`; never duplicate their NBT or full plans. Preserve owner/receipt
digests separately. No ad-hoc unlimited diagnostic SSM loop.

Before copying, capture original target content/tree, other/retained Game hashes,
helper hashes and free capacity. After prepare unmounts source, supplemental content
is **restored-path observation**, linked by the formal receipt's source/copy world
hash; it is not a new source snapshot measurement. Do not remount for this reader.

## Authorized execution sequence

1. Revalidate caller/CF ownership, selected Game, STOPPED/HEALTHY, stopped EC2,
   no Current/Lock/workflows/active SSM/DNS/unclosed maintenance/unfinished RESTORE,
   empty three queues, 51 normal alarms, package/creation/world/policies, retained
   journals/worlds and existing narrow host SystemState GetItem permission.
2. Request exactly one protective BACKUP through Admin Admission with a fixed key.
   Verify SUCCEEDED/completed/provenance/current world/package, newer than Desired
   transition and within one hour at planning. Do not bypass or expand IAM.
3. Record and restrict approved ingress; keep Observer/Reconcile active. Formal
   maintenance begin with 7200 seconds; observe existing suppression eligibility.
   Create one unique Paper RESTORE request/plan while stopped. Create/attach exactly
   one journal-owned temporary EBS using the existing operator. Boot only target EC2.
4. Check SSM Online/fresh idle observation, mount/NVMe identity, no Minecraft/listener,
   capacity and all baseline hashes. Helpers must already equal candidate bytes;
   formal payload verification is a no-op. Unknown hash stops, not an upgrade.
5. Formal prepare/collect: block read-only and XFS ro/nouuid/norecovery, exact
   source-owner/package, bounded staging, full world equality, receipt and unmount.
   Require terminal Success/0, PREPARED and protected-tree equality.
6. Normally stop idle maintenance EC2, conditional commit, exact temporary-volume
   cleanup through DELETED/NotFound; keep source/protection snapshots and both worlds.
   Formal maintenance end, then ordinary restored START/content/STOP through Admission.
   Check bound path/receipt, same package, READY, fresh heartbeat/Reconcile/run,
   dimensions/player/config/policy evidence. Explain normal tick/config writes separately.
7. New formal 7200-second maintenance, EC2-only boot, check-rollback/collect-rollback
   proving previous_tree under current lease, normal EC2 stop, formal rollback.
   End maintenance; original normal START/content/STOP. Keep allocation counter and
   restored directory. Initial-path equality is required before this original START,
   not after legitimate original-world saves.
8. Verify selected original path, all retained data/policies, temporary cleanup,
   STOPPED/HEALTHY, maintenance ENDED, no work/SSM/DNS, empty queues, 51 naturally
   normal alarms and exact original ingress restoration. Record closeout separately.

Unknown identity/hash/layout/core failure stops forward execution. Preserve artifacts
and use only authorized normal STOP/idle EC2 stop/owned cleanup/formal rollback when
their existing gates hold. No force, hand-edited state, blind retry or alarm changes.
The user's single extra read after a terminal reader-output-only failure requires
local validation, fixed commit/hash, unchanged safety gates and sufficient lease time;
it does not permit RESTORE retries or omission of mandatory content checks.

No client login/load/exploration, NeoForge RESTORE, arbitrary plugins/builds/upgrades,
all failure patterns, disaster recovery, prod publication or automated BACKUP is proved.

## Repository qualification before execution

1,826 full tests passed; Ruff, 344-file format and mypy 253 files passed. Configured
Control Plane and independent Web synth passed. Python 3.9.6 and 3.12 executed the
generated reader form through JSON reloading. Existing Paper CI remains IMPORT
integration evidence; the new unit fixture covers IMPORT-origin source selection,
initial owner mismatch refusal, prepare/world equality, current access files,
reference rollback without current_id and counter retention, and initial-path replay
without an available archive. This is not real Docker RESTORE/START evidence.

A new private fixture used selected files from the saved historical IMPORT test,
not VPS access or the chosen snapshot. All observed player groups were included;
the number of players is not a gate or fixed constant. Two target summaries used
13,728 bytes, below the unchanged 20,000-byte cap before host/owner evidence. Fixed
host reads additionally report Python version, filesystem capacity, mount and block
identities; they do not change devices or mounts. Separate protection-only payloads
avoid duplicating unrelated content. Actual command/output hashes belong to execution
evidence; CI and live RESTORE qualification are recorded separately when completed.

Local fixture diagnostics retained: missing synthetic provenance.project, DynamoDB
Decimal normalization in the test (the real host decodes integers), and macOS /var
symlink rejection before rebuilding under its resolved /private/var path. Initial
lint and the changed host-read call-count assertion were corrected in test/reader
scope. No failed run was relabeled; no RESTORE safety guard was relaxed.
