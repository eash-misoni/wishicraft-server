# Paper dev RESTORE: partial proof and safe rollback

2026-09-25 UTC. **The requested full proof is incomplete.** Existing D-113 reached
PREPARED → COMMITTED → restored normal START/content/STOP → formal ROLLED_BACK.
The original world was reselected and retained without starting it. After the
restored STOP, a metadata aggregate changed without per-file attribution; forward
qualification stopped rather than labeling every change normal. No RESTORE core
failure or source/copy mismatch was observed.

See the [machine-readable record](paper_restore_dev_2026-09-25.json),
[Paper runbook](../runbooks/paper_restore_dev.md), and
[D-113 contract](../reviews/game_restore.md). Prior first-Vanilla-B authorization
and evidence remain unchanged. This is a separately authorized Paper slice.

## Execution identity and qualification

- Baseline: `8a12b2a3aaac2aa5ab5dd8602c66a35ee1d5ac23`.
- Implementation/execution: `00679608ebaa837768673dfd765d45242c4111e5`.
- Clean detached execution worktree: `/private/tmp/wishicraft-paper-restore-0067960`.
  All formal/reader payloads came from this commit with frozen hashes.
- Only reader, fixtures/tests and Paper runbook changed from baseline; no RESTORE
  core, validator, runtime, helper, lease or infrastructure change.
- Dev / account 385526546525 / ap-northeast-1 / wishicraft-dev / wishicraft-main.
  Canonical configuration, STS and CloudFormation ownership were cross-checked.
- EC2 `i-04fc0629dc4ea466e`; Data EBS `vol-03ac9f534326c345c` stayed attached.
- vps-survival: `game-bfd8409b3f8a4d1b591231c3490d9b646f546294ca11837cad74616ed33eaf21`.
  Same immutable Paper 26.1.2/build 53 (`26.1.2-53-39a1aa5`), package, Java/image.

Execution validation: **1,826 full tests**, Ruff, 344-file format, mypy 253 files
and configured Control Plane/independent Web synth passed. Generated reader
Python/JSON roundtrip passed locally on Python 3.9.6 and 3.12; actual host was
3.9.25. Exact execution-commit CI succeeded:
[CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/36111340729),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36111340778),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36111340744).
Existing Paper CI is IMPORT integration, not real RESTORE. New local fixtures
covered IMPORT-origin source/initial-owner handling, separate prepare, missing
original archive, previous-world rollback without invented current_id and counter
retention. These fixtures are distinct from the real execution below.

The primary checkout retained unrelated README, delivery/backlog, Terralith runbook
and untracked Terralith evidence changes. “Clean” describes the execution worktree,
not the primary checkout. Private evidence uses a new dedicated temporary root;
old fixtures/results were not overwritten. Recipient/unsubscribe information, raw
players/inventory/coordinates and secret values are excluded from public evidence.

## Snapshot, plan and real checkpoints

Source `snap-0aac363f3ce09e05a` belongs to formal BACKUP
`op-4236596e-a436-4c99-833b-33b39f89dab8`. The formal validator confirmed completed,
encrypted canonical-volume snapshot and durable provenance pair, Paper Game,
source creation/world and immutable package. Other Games in the shared snapshot
were not extracted.

One new protective Admin BACKUP, `op-3315c971-8f8a-40bd-9268-fd52a32305d9`, succeeded
08:21:11–08:23:19. Snapshot `snap-0e5941ab3b8e0e6ff` was completed, captured
08:21:18.683, newer than the Desired transition, with matching provenance/world/
package and within one hour when planned. It did not replace the historical source.

Request `paper-restore-20260925-0067960` produced one RESTORE:
`op-a09fec85b92d5620351ef556b7d47d4dff6f6d62e0042fc0a3f0e5c28b519f42`.
Previous path is the Game's initial `server`; target is
`worlds/<RESTORE operation>/server`. Protection used Desired revision 73.

| UTC checkpoint | Result |
| --- | --- |
| 08:27:13 | First formal maintenance began, 7200 seconds; normal suppression observed. |
| Before prepare | Original and other four Games plus retained Vanilla B hashed; approximately 22.08 GB free. |
| 08:40:44–08:48:40 | Formal prepare SSM Success/0 within unchanged 900-second limit. |
| After collect | PREPARED; source/copy world equality, owner/validated identities, source unmounted, no staging. |
| After idle EC2 normal stop | Conditional COMMITTED; generation/counter 2; only target world selection changed. |
| Before first end | Official temporary EBS cleanup DELETED/NotFound and empty operation-tagged volume set. |
| 08:59:53 | First maintenance ENDED. |
| 09:01:00–09:05:15 | Restored normal START `op-5088ccaf-f567-4900-9d06-fd340b3283b4` SUCCEEDED. |
| 09:06:33–09:07:02 | Fixed live reader Success/0; selected content and policies equal PREPARED. |
| 09:09–09:10 | Fresh READY/HEALTHY Reconcile and heartbeat, same Game/run/process/boot, restored path, observed zero players. |
| 09:11:17–09:12:57 | Restored normal STOP `op-36b96ad3-0db9-458c-8d6a-9a14800c7056` SUCCEEDED; EC2 stopped/DNS absent. |
| 09:14:44 | New rollback maintenance began, 7200 seconds; normal suppression observed. |
| Before rollback | Original tree exact; restored post-save aggregate difference identified. Forward proof stopped. |
| 09:23:12–09:23:16 | Formal check-rollback Success/0 and collect-rollback, previous_tree matched under current lease. |
| 09:28:08 | After normal idle-host stop, ROLLED_BACK; original reference restored, counter 2 retained. |
| 09:33:04 | Child alarms had converged; rollback maintenance ENDED. |

Temporary EBS `vol-08ccfa5f07923ad13` was the only clone, owned through formal
ClientToken/tags. NVMe serial distinguished it from original Data EBS. Unchanged
formal payload enforced block read-only, XFS ro/nouuid/norecovery, no repair/replay,
and unmount. Supplemental content was observed on the **restored path after source
unmount**, linked to source by formal full-world hash equality; it was not a new
snapshot measurement after unmount.

Applied helper hashes matched execution commit before/after; the formal helper
check was an identical-bytes no-op. Existing host GetItem policy was verified for
the SystemState table and one system LeadingKey. No IAM/helper deployment occurred.

## Content proof and unresolved difference

Formal source/copy world: 1,541 files, 3,515,790,017 bytes,
`133e616c3bcf4482fe7df5851adab7970d81ecca549789c45973078ffe4ae7a3`.
Original server: 1,670 files, 3,680,766,267 bytes,
`9258f8ff8f2a773c318635df4248c690faf1e90bf0145060126cf683766005d8`.
Prepared server: 1,550 files, 3,515,810,898 bytes,
`db48749641f2df3d8c65c1a22326d0fa5bf229e3b02746688ea126627d84cef1`.
Source server includes runtime files outside the copy allowlist; server-wide source
equality with the prepared world-plus-selected-config tree is not claimed.

Restored live observations matched PREPARED:

- `wishinkaiwai/dimensions/minecraft`: overworld 402, nether 33, end 90 terrain
  region files; two independently selected region hashes per dimension.
- All player saving groups: data 27 files, stats 14, advancements 14. Twelve
  `.dat` files decoded; selected inventory/ender chest/position/dimension presence
  and canonical semantic aggregate hashes matched. File counts are not player counts.
- Datapack group, complete 33-file modern metadata aggregate, nine selected
  game-rule/border/world-generation files, and seven Paper config hashes.
- Current access file hashes, Game/package/IMPORT creation, registry and Common/
  Game-specific policies; no snapshot whitelist/OP/ban or whole properties rollback.
- Runtime receipt and actual container `/data` bind used the new generation,
  with unchanged immutable image and READY. No archive re-expansion/empty world.

After normal STOP, retained restored world: 1,541 files / 3,515,790,036 bytes,
hash `1e02ace2a3e4f15ec8925632220f9a666c0c53f6f7a5d0a50eb9fa018f4c5bf9`.
The 33-file metadata filename set/count stayed equal, but aggregate changed from
`b35cb28b5de9306e317c4c0a973b4089a59a08d1cbc05a66f57fc052b05572cb` to
`238895a8fd0e5f86b6d8a92408dcc5e574049f3f45b36185ada2cb9ace98d1f1`.
Decoded level.dat Time advanced 30367857 → 30378472. Player groups, datapack,
dimension samples, nine selected metadata files and seven configs remained equal.

Normal saves can change world/runtime files. However, the reader recorded only an
aggregate for the remaining metadata, so **exact changed files and their individual
semantics remain unverified**. Time advancement does not prove all changes normal;
aggregate inequality does not prove corruption. No baseline was rewritten or
ad-hoc diagnostic SSM sent. The output-failure retry exception does not cover this
situation. Original-world START/content/STOP was therefore not performed.

Original server/world and other four Game trees, including retained Vanilla B,
were exact through final protection reads. Original was never started in this
attempt. Restored world changed during its own lifecycle and is retained; no
end-to-end byte immutability is claimed for it. NBT array bytes remain opaque;
there is no invented coordinate/seed interpretation or JavaScript integer rounding.

## Two actual monitoring notifications

The user confirmed receipt of RuntimeObservationUnknown and DesiredActualDivergence
composite emails. Complete metric/composite state/action histories and existing
metrics/logs were saved read-only, excluding recipient/unsubscribe information.

- Child ALARMs at 08:41:49 and 08:46:31 were initially successfully suppressed.
- Eligibility was 1 through idle-host observations at 08:50. Logs showed fresh
  heartbeat, runtime unknown (Minecraft absent), filesystem observed.
- At 08:55 actual EC2 was stopped and eligibility was 0 with an unexpired lease.
  Monitoring logged heartbeat/runtime/filesystem “not-expected”.
- Suppressor returned OK at 08:56:46 while both composites remained ALARM;
  CloudWatch successfully sent both existing SNS actions. Child alarms returned
  OK at 08:56:49 and 09:01:31 respectively.
- Formal maintenance end was later, 08:59:53. It did not cause the earlier release.
  EC2/observation convergence is consistent with the eligibility guards, but the
  individual historical SystemState predicate at 08:55 was not logged.
- Alarms subsequently converged naturally. No metric/state injection, action change,
  suppression extension or policy modification occurred.

Backlog: review planned-host shutdown observation convergence and notification
release while base alarms retain ALARM, preserving unknown-state fail-open behavior.
This slice does not fix or broadly requalify monitoring. Rollback closeout observed
base-alarm convergence before ending maintenance; this is not a future guarantee.

## Closeout and continuation boundary

Original initial path selected, generation 1, **current_id absent**, counter 2.
Both worlds and both snapshots retained. Temporary volume NotFound and empty
operation-tagged volume set; no restore mount/staging in final idle-host observation.
Both maintenance sessions ended. Discord Command/Web concurrency returned from 0
to original UNSET; Admission, Observer and Reconcile were not disabled. Final
read-back at **09:40:02 UTC** confirmed STOPPED/HEALTHY, EC2 stopped, no Current
Operation/Lock/running workflow/active SSM/session/DNS, three empty queues and all
51 alarms naturally OK. All 51 alarm configurations, host IAM and function
concurrency matched baseline. The rollback session added no SNS notification
action; its RuntimeObservationUnknown composite remained suppressed until OK.
Machine-readable safety checks accompany this record. The dormant historical
PLANNED request without volume/dispatch is retained unchanged, not an active
workflow or this request.

No VPS/prod access, other Game lifecycle, RESET/IMPORT/CREATE, Data EBS replacement,
world/snapshot removal, IAM/CloudFormation/Lambda/Web deploy, package/plugin/Java
update, force stop, lease/Lock hand-edit or alarm manipulation occurred. No client
login/load/exploration. NeoForge, arbitrary plugins/builds/upgrades, all failures,
disaster recovery and automated backup are unqualified.

Continuation needs a reviewed, bounded read-only per-file comparison of retained
trees, anchored to original saved hash, with fixed commit/payload/limits. Do not
repeat BACKUP/request/volume/prepare/commit, remount snapshot just for inspection,
or silently start original. Resolve the unlocalized difference and preserve the
completed checkpoints before further dev work.

Diagnostics retained: local fixture/environment corrections in the runbook,
initial stale read-only preflight, and local evidence-comparator fixes for DynamoDB
StringSet, optional Current Operation absence and mixed result types. These were
not RESTORE failures or extra SSM reader retries. Every actual formal/supplemental
reader completed Success/0 without output-limit failure. Closeout docs validation
and CI are separate from execution validation.

Closeout local checks: 13 focused reader/Paper tests, Ruff, format (345 files),
mypy (253 files), JSON/privacy/local links and diff checks passed. Source and
infrastructure did not change in closeout; execution synth results remain distinct
from the closeout CI synth. Exact closeout commit and its CI outcomes are reported
in the handoff, not inferred from execution-commit CI.
