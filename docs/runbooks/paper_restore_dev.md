# Paper RESTORE: separately authorized limited dev proof

2026-09-25. **Partial dev proof, formally rolled back; full Paper qualification incomplete.**
The [execution evidence](../evidence/paper_restore_dev_2026-09-25.md) records real
PREPARED, conditional commit, restored START/content/STOP and formal rollback.
Post-STOP metadata changed at an aggregate level without individual-file attribution;
original-world START/STOP was deliberately not performed. Do not report this as the
complete requested proof or repeat completed BACKUP/RESTORE/copy checkpoints.
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

## Retained checkpoint and next review

The original initial path is selected again, with generation 1, no current_id and
generation_counter 2. Both worlds and both snapshots are retained. The RESTORE
journal is ROLLED_BACK with temporary-volume cleanup DELETED. The original tree
remained exact through rollback; it was not started in this execution.

Source/copy whole-world equality and restored live content equality succeeded.
After normal STOP, the 33-file modern metadata group had the same filename set but
a different aggregate hash. The decoded level.dat Time advanced; this explains an
observed time change, not every changed file. Player groups, selected terrain
samples in each dimension, datapacks, the nine selected game-rule/border/world-gen
files and seven Paper configs still matched. Do not infer corruption or complete
normality from the aggregate alone. The fixed reader did not fail or truncate, so
the single output-failure retry exception was not used to add diagnostic SSM.

Before any separately authorized continuation, qualify a bounded read-only
per-file comparison of the retained original and restored trees. Freeze its commit,
payload/hash, changed-file/output limits and local actual-Python execution tests.
First revalidate the original against the saved previous_tree and both identities;
then identify changed metadata files and distinguish decoded changes from opaque
NBT arrays. No source snapshot remount, new BACKUP/RESTORE request, prepare replay,
world editing or helper update is needed merely to review the retained difference.
Original START remains pending until the difference is adequately explained and
the continuation's safety/authorization conditions hold.

Adjacent monitoring follow-up: two previously suppressed composite notifications
were released after the first maintenance-host stop, before their child alarms
returned to OK. Preserve the history and fail-open contract. Review observation
convergence and alarm evaluation timing separately; do not extend suppression,
inject metrics or alter alarms to hide the event. In the rollback session, the
operator observed child-alarm convergence before formal maintenance end. This is
an observation sequence, not a guarantee that future shutdowns cannot notify.

## Separately authorized retained-world continuation

The 2026-09-25 continuation starts from closeout `a11e0f9`, not from a new RESTORE.
The original initial server is already selected; journal
`op-a09fec85b92d5620351ef556b7d47d4dff6f6d62e0042fc0a3f0e5c28b519f42`
must remain ROLLED_BACK, generation 1 / counter 2 / current_id absent. No new BACKUP,
request, clone volume, source mount, prepare, selection commit or rollback is allowed.
Retain both worlds and snapshots. Do not rewrite the earlier partial result.

First verify the saved private evidence hashes against the public JSON and formal
receipt. For this particular run, source_tree and previous_tree were identical.
Only a current original-server/world/metadata match to those saved values permits
using the retained original as the restored world's pre-start comparison baseline.
This is new observation of a retained tree, not inversion of an aggregate hash or
new snapshot measurement. It is not a general property of historical backups.

The supplemental `restore_compare` reader keeps the existing `file_group` encoding
and traversal/output/time limits. It records relative paths, sizes, SHA-256 and
read stability; level.dat is separate from modern data/minecraft metadata.
`level.dat_old`, when present, also retains its own typed record for save rotation;
its absence is explicit and is not invented from the current level.dat.
Whole-world file differences include additions/deletions/changes and unchanged counts,
with complete filename/content aggregates. Repeated full manifests detect changes
during the read; atime is outside the content comparison. Empty directories remain
covered by the formal server/world tree reader, not the file-only aggregate.

The private typed NBT snapshot preserves numeric tag types and exact decimal integer
strings, float hex, compound/list structure and typed opaque array hashes/counts.
It does not interpret arrays as positions/seeds. Unknown types, unstable reads,
oversized input/output or excessive differences fail, rather than normalize away
evidence. Compressed-byte equality, expanded-byte equality and typed-value equality
are separate results. Compound ordering differences can have equal typed values;
that fact alone does not authorize treating any changed saved value as normal.
Any changed opaque value needs independent explanation or leaves the proof pending.

Freeze the command family before AWS: one paired whole-world comparison and three
numbered private metadata/level snapshot parts, plus the existing target-content
and other-Game protection readers. Each private part is at most 18,000 base64
characters inside the unchanged 20,000-byte JSON envelope. XZ is transport encoding,
not a change to world files. All three must have the same decoded length/SHA and
part count, and reassemble/decompress/reload exactly. A missing or disagreeing part
is not a complete snapshot. Maximum decoded private JSON is 1 MiB; the complete
transport is capped at 54,000 characters. Private typed records are never published
as player data, inventories, coordinates or full server properties. This complete
bounded record is fixed before starting original so its later save can be explained.

Qualify exact generated python3 -c on Python 3.9 and current repository Python,
including reassembly. Keep test fixtures and failed qualifications in new roots.
Commit/push, required CI and a clean execution worktree precede real host work.
No supplemental reader is installed as a host helper or changes validator authority.
The existing target-content reader also reports the fixed initial IMPORT owner:
root/root, mode 0600, single regular file, phase, Game/path, complete plan digest
and creation digest. Compare these against the current Game and recorded plan;
absence or mismatch does not authorize inventing an owner or legacy current_id.
Creation contents are hashed rather than expanded into routine output.

The first new ordinary maintenance (at most 7200 seconds) checks both retained
worlds, all identities, other Games and the retained Vanilla world. Original must
match previous_tree/source_world_tree/before metadata; restored must match the
saved post-STOP world/after metadata. Freeze per-file metadata manifests and typed
records privately. Explain changed files and fields using exact-version evidence;
level.dat Time is not an explanation for another metadata file. Unexplained loss,
unknown layout or baseline mismatch stops forward work: normally stop idle host,
formally end and retain all data. No diagnostic source remount is authorized.

Only after those gates pass, normal idle-host stop/end is followed by exactly one
Admin original START/content/STOP. Verify original binding, unchanged package,
READY/fresh same-run observations, current policies and Paper content. The second
ordinary maintenance compares saved original content with the frozen private
snapshot and checks unchanged retained restored/other trees. It then normally
stops idle host and ends. Original lifecycle success and full post-save explanation
are separate outcomes. No second START/STOP is authorized to repair evidence.

Restore ingress exactly, confirm naturally normal 51 alarms and final stopped/no
work/no DNS/empty queues. Investigate any maintenance notification against actual
state/history; do not suppress it by changing monitoring. That race remains an
independent backlog. The earlier completed RESTORE checkpoints are never replayed.

### Proposed supplementary Paper override read

The retained-world comparison identified changes in all three dimensions'
`data/paper/level_overrides.dat`, outside the 33-file Minecraft metadata group.
The original fixed typed snapshot does not include these files. A successful
comparison with insufficient content coverage is not a failed-output retry.
Original START remains gated until their values are explained as well.

The separate `paper-overrides` reader selection reads exactly those three files
in each of the two authorized worlds. It preserves types/opaque arrays, records
individual fingerprints and read stability, and keeps the Minecraft aggregate
unchanged. One bounded private envelope contains all six documents. Repository
qualification does not authorize an additional SSM: freeze its separate commit,
CI and payload hash and obtain explicit approval for one pre-start and one
post-save invocation before using this added selection. No source remount, world
write, RESTORE replay or safety-contract change is involved. If approval is not
available, stop the idle maintenance host normally, end and retain both worlds;
do not silently consume the output-failure exception.
