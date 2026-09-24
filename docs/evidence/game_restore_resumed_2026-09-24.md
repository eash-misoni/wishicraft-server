# D-113 retained PREPARED continuation — limited dev proof

2026-09-24 UTC. **Vanilla B completed retained PREPARED → COMMITTED → restored
START/content/STOP → explicit rollback → original START/content/STOP.** The original
world is selected again; both world directories remain protected recovery data.
[Machine-readable evidence, command/payload hashes and workflow events](game_restore_resumed_2026-09-24.json).
This is limited dev qualification, not general authorization for future operations.

## Execution identity and scope

- Reviewed RESTORE core: `b856dcf06f8564c7c056491ff3b993a3fc828357`.
- Previous PREPARED closeout: `73e19aa66d43acd3a8879aabcd2fd427ace8414e`;
  [historical source/copy and real read-only XFS evidence](game_restore_prepared_2026-09-23.md).
- Initial reader: `ea8c7bf7b260d06cb26caac074f8e6300ba9d133`.
- Corrected reader and successful execution: `5a17b11716830f919dec9d9dcd27e9111923d800`.
  Only reader/tests/runbook changed; RESTORE, IMPORT, NBT, helper and validator bytes
  match the reviewed core (individual SHA-256 values in JSON).
- Each reader commit used its own exact-HEAD, clean detached worktree. Payloads and
  execution evidence were generated into new dedicated output roots, never from the
  dirty primary checkout. Both failed and corrected artifacts remain available.
- Account `385526546525`, profile `wishicraft-dev`, region `ap-northeast-1`, system
  `wishicraft-main`; EC2 `i-04fc0629dc4ea466e`, Data EBS `vol-03ac9f534326c345c`.
- Game `game-vanilla-secondary` / Wishicraft Vanilla B, immutable Vanilla 26.2 package.
- Same RESTORE throughout:
  `op-8639e35589a158e5e45fc2ccf68fcec06681aac6e8eeaf2b1507495e35224730`.

Source `snap-0be8e05ab05d70e84`, BACKUP `op-059abd53-92a6-469a-abb2-6eb8dfe5da8e`,
2026-09-12 10:31:35.625 UTC, source generation 1 / legacy Game server path.
Protection `snap-0d2407a5af78afa82`, BACKUP `op-aa36d4ba-101b-47f1-bd6c-f393234b9509`,
2026-09-23 08:38:21.444 UTC. Both were revalidated against actual EC2 and durable
provenance, and remain completed/encrypted. Protection revision 67 and the original
world/package were unchanged before commit. The old plan's creation-time freshness
was not confused with retained-PREPARED continuation validity; no timestamp/revision
was rewritten and no new backup/request was made.

## Reader correction and evidence boundaries

The local reader handles actual NBT array bytes explicitly as type/length/hash,
walks the 26.2 `dimensions/minecraft/overworld/region` layout, and limits traversal,
runtime and JSON output. It reuses exact IMPORT SHA/tree code and unchanged NBT
parsing. It emits no complete NBT, playerdata, properties, Docker environment or
secrets, installs nothing and disables Python bytecode.

The initial resumed supplemental command `a19a8baf-fabe-405a-b392-e65251d09760`
terminated **Failed/1** at `READER_OUTPUT_LIMIT` (20,000 bytes), with zero stdout.
It was a known read-only output failure, not RESTORE prepare failure. The separately
approved single corrected read was used: full plans became canonical hashes and
other Games kept tree evidence without unrelated content details. The limit and all
RESTORE validators stayed unchanged. A six-target regression uses the saved plans.
After tests/CI and fresh lease/idle-host checks, corrected command
`5679f848-921f-4513-88da-7a9f0fd089e5` returned **Success/0**, 10,174 bytes. No further
reader retry was needed. Later planned lifecycle readers also returned Success/0.
The original failed payload and its result were preserved.

A separate local preflight stdout formatter failed on Decimal **after** all gates
passed and the complete result was saved. That saved result was reread; no AWS
preflight or mutation was replayed to repair display output.

Evidence is deliberately separate:

1. Provenance authenticates the selected snapshot/Game/package, not world bytes.
2. The previous real source/copy proof links to the currently retained prepared
   world through an exact whole-world hash. This run did not remount the snapshot.
3. Actual normal START, runtime binding, protocol READY/heartbeat, region fingerprints
   and current access projection establish usability of each selected world.

Legacy `Data.WorldGenSettings.seed` was missing. Spawn position arrays were compared
as opaque 12-byte fingerprints, not claimed as decoded coordinates or seeds. The
content summaries are measurements of retained trees, not new snapshot measurements.

## Checkpoints and preservation

| UTC | Observed checkpoint |
|---|---|
| 02:52 | PREPARED revision 13, cleanup DELETED, Desired 67; original world selected; stopped/healthy, 49 alarms OK, no work/Lock/SSM/DNS, queues empty. |
| 02:53:27–03:23:28 | New ordinary 3,600-second lease `d113-resume-20260924T024016Z`; actual Active/eligible/expiry/suppressor checked before boot. |
| 03:16:34 | Corrected reader Success/0; original/prepared/other trees, root owners, validated receipt and helper hashes verified. |
| 03:19:03 | Stopped-host conditional COMMITTED, revision 15; new lease bound by checkpoint, cleanup DELETED. |
| 03:26:18–03:30:32 | Restored normal START SUCCEEDED; correct path, READY and fresh matching run/boot heartbeat. |
| 03:31–03:32 | Restored live content/binding/policy reader Success/0; all four sampled regions match retained prepared content. |
| 03:33:02–03:34:45 | Restored normal STOP SUCCEEDED through save/stop, container removal, EC2 stop and DNS cleanup. |
| 03:36:22–03:52:15 | New ordinary rollback lease `d113-rollback-20260924T024016Z`; suppression verified before boot; no lease recovery or fault injection. |
| 03:48:19 | collect-rollback verified original tree and current lease; journal revision 19. |
| 03:50:31 | After normal maintenance host stop, conditional ROLLED_BACK, revision 20. |
| 03:56:15–04:00:29 | Original normal START SUCCEEDED; original path READY and fresh heartbeat. |
| 04:02 | Original content/policy reader Success/0; all four original sampled regions match; inactive restored tree and other Games unchanged. |
| 04:04:57–04:06:37 | Original normal STOP SUCCEEDED through complete endpoint cleanup. |
| 04:10 | Final read-back after exact ingress restoration: STOPPED/HEALTHY, 49/49 OK. |

The initial server hash `60a298ff91447c4956a4131eca3d22797b58b1b2ca12b267bf78d9a32dce91ce`
remained exact through restored START/STOP and the formal rollback proof.
Prepared server `d941e0acc31d6b3bed13fd465ff0ecb040a1cf639bc80eb1f9a33eddd6589cc3` and
prepared/source world `46edae3a5e1aa8457a24c243267bcf32ee970af28f805400c46ac74b3f946ced`
matched the prior receipt exactly before commit. Root-owned 0600 owners and validated
receipt identity/plan hashes/protection were checked; helper hashes remained unchanged.

Normal START installs runtime files and Minecraft saves update level.dat. Restored
world Time advanced 1199→2398, original 4796→5995. These are normal lifecycle writes,
not failed copy hashes. After restored STOP, retained server hash was
`5495929a78316868bae68d00135f013ff239cf7f9083d70d6071dee5c29438c8`, world hash
`6ebff8516cc80538c48c7a4998c86def0b5bc706f71e9b0f36f969e1a5e25e0e`; both remained exact
while the original world ran. All four other Games' server trees remained equal to
both this run's baseline and the previous execution. Each live reader confirmed the
actual container bind and receipt, Vanilla 26.2 content, current effective whitelist
file hash, and unchanged OP/ban files. No existing MATERIALIZED flag alone was used
as restored availability evidence; the restored owner actually reached initialized.

Formal rollback SSM `42a1128a-9d74-4f57-b4ac-7a965a711e76` produced a proof for the
new rollback lease and the exact previous tree. Both worlds remain protected:

- Selected original: `worlds/op-2fc1bd34-b2ab-45a4-b3f8-95a53d828dcf/server`.
- Retained restored: `worlds/op-8639e35589a158e5e45fc2ccf68fcec06681aac6e8eeaf2b1507495e35224730/server`.

Paths are relative to `/srv/minecraft/games/game-vanilla-secondary/`. Selected
generation is 1; allocation counter remains 2. Full Game/registry/creation/package/
access records matched the preflight baseline except the target world reference and
counter. Desired revisions 68/69/70/71 came from the four ordinary lifecycle operations.

| Operation | ID |
|---|---|
| Restored START | `op-930ca474-10f3-4028-8641-c64e78f1fe7a` |
| Restored STOP | `op-dc7e923f-d8f3-449d-ace9-25e04e74e9cc` |
| Original START | `op-2be431f0-6f1f-4781-bc2c-cf88bb028055` |
| Original STOP | `op-3c160d65-59de-4d25-b5f4-70594c15be5b` |

## Final state and repository validation

Original world selected, both protected worlds and validation receipts retained;
source/protection snapshots retained. Old temporary `vol-0adfd2940e3e501ca` remained
NotFound, cleanup DELETED; no same-RESTORE volume or disposable staging remained.
No temporary mount was created this run. EC2 stopped, Desired STOPPED / HEALTHY,
maintenance ENDED; Current Operation, Lock, running workflow, active SSM/session and
DNS absent; all three deployed queues empty. All 49 alarms OK with unchanged
configuration. Admission stayed UNSET; Discord Command/Web were restored from the
approved temporary zero concurrency to their original UNSET. Observer/Reconcile
remained enabled. No alarm state/settings were forced or broadened.

**Not repeated:** IAM application, helper distribution, CloudFormation/Lambda/Web
deploy, BACKUP, new RESTORE request, temporary EBS creation/attachment/mount/deletion,
source extraction/copy/prepare, or the previous planned incident/recovery trial.
No other Game was started/switched/restored, and no VPS/prod operation occurred.
The known dynamic-Game BACKUP IAM limitation remains unchanged; future protection
BACKUP must succeed through the existing authorized path, with no workaround here.

Final reader validation: **1,809 full tests passed**, reader tests on Python 3.9.6
and 3.12, Ruff lint/335-file format check and mypy 250 files passed. A sandbox-only
online run retained 12 failures/47 setup errors from PyPI DNS/bundling (1,750 passed);
hash-locked cached `UV_OFFLINE=1` rerun passed all 1,809. No failed result was relabeled.
Same execution commit CI passed [normal/quality/Web/synth/host integration](https://github.com/eash-misoni/wishicraft-server/actions/runs/35949905125),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/35949905197), and
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/35949905124).
Docker/shellcheck were unavailable locally; real Docker integration evidence is CI.

This closeout is a separate documentation commit from the execution commits; its
final hash/CI and primary local Wiki sync are reported in the handoff. Execution
worktrees remain clean; unrelated primary-checkout changes remain uncommitted.
Real Paper/NeoForge RESTORE, every failure/expiry pattern and full-environment disaster
recovery remain unqualified. Repository tests and the prior partial dev proof retain
their own boundaries. EXPORT, UPGRADE and RESTORE UI were not implemented.
