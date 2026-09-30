# D-115 release preparation: bounded dev read-only evidence

Repository preparation only; no AWS deploy/ChangeSet, snapshot request, hold release,
Operation/journal write or D-114 interruption. This is a new continuation record. Prior
investigation/PROPOSED artifacts remain unchanged. [Design](../reviews/retention_release_gates.md),
[positive preflight projection](retention_release_preflight_dev_2026-09-28.json),
[offline synth comparison](retention_release_synth_2026-09-28.json).

## Merge baseline

PR #11 reviewed HEAD `18aae17786bba6d37ec40d7c44289517ef380cb1`, base
`328937ddd8037d0c297089c9ae782b1c730b4bc6`, synthetic merge
`7d74b5cb2d552ad7741e0ac2283dfe37190f894e` and actual merge
`29cff405d83efb25ef67fb98de8b03e7ee9568f6` were checked. Reviewed, synthetic and actual
merge all have tree `4e14040a90c12fc33d0e67e5ede6ac577337f7ea`; normal merge's ID change
is not a content change. Actual merge completed 2026-09-28 10:29:04 UTC after Draft removal.
No required checks were configured; all five existing PR checks were successful, the PR was
clean/mergeable and no protection bypass or review impersonation was used.

Actual merge CI succeeded independently of the synthetic merge:

- [Normal CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/36409975128).
- [NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36409975339).
- [Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36409975321).

New implementation commit: `8a9fa60832f8d169ed8ffcb7672f1116e0c24021`. The continuation
is a separate unmerged Draft, not an AWS release. Its final HEAD/CI are recorded on the PR
rather than making an endless chain of closeout commits.

## Live preflight and blockers

Canonical stage configuration, STS account 385526546525, ap-northeast-1, wishicraft-main and
volume vol-03ac9f534326c345c matched. Individual read start/end, pages and final-page facts are
in JSON. Initial inventory used bounded before/after relevant-state comparison; supplemental
runtime/reference reads took place later. This is not an atomic multi-service snapshot.

Observed:

- 14 owner-wide snapshots, all on the canonical volume; original immutable provenance
  pairs valid. Six held snapshots (including dynamic success), five legacy exclusions,
  one migration anchor and two normal shared-volume backups. Both normal entries KEEP;
  old-seven and 14-day-OR-seven reference calculations each have zero candidates.
- Last success snap-0212d6f8613b684ac / op-80573487-0ca4-450d-b57a-e9160a3b17f9,
  captured/protected boundary 2. Intent SUCCEEDED; no new unresolved operation beyond the
  adopted three FAILED. No deletion records were produced by this work.
- Three non-TTL RESTORE journals remain: Paper and Vanilla ROLLED_BACK; old unused PLANNED.
  Source/protection references are independent and retained. Migration remains excluded
  without a new static registry; all other historical holds also have live references.
- Lock table empty, no current operation, maintenance ended/absent, desired STOPPED/HEALTHY.
  No Game or host operation was performed. No claim is made about an unqueried live EC2 state.
- All 14 candidate-scoped owned-AMI and createVolumePermission reads found no references.
  Initial ID-scoped lock/bin checks were UNKNOWN (the separate bin diagnostic returned
  InvalidSnapshot.NotFound). Those errors were not interpreted as empty results. After a
  local regression, complete owner-wide lock and bin pagination independently established
  zero locks / zero bin entries at 10:55:35 UTC. Initial unknown evidence is retained.
  Recycle Bin rules were zero, so no rule-specific mechanism was added.
- Deployed RETENTION is wc-dev-retention-task, Python 3.12, 120-second timeout, $LATEST only,
  no alias. ARN/role/revision/CodeSha256 are recorded; environment is not saved. The existing
  synchronous Standard workflow has timeout 300 seconds and no task Retry. Its describe
  response did not provide revisionId; null in projection is not proof of a revision.
- Live inline IAM has the original dry-run reads and state/operation/lock writes. Attached
  AWSLambdaBasicExecutionRole was separately read. No DeleteSnapshot permission was found.
  Proposed release env keys are absent. The deployed function is still the earlier D-114
  artifact; PR #11 was not deployed.

Current live release blockers are expected: no provisioned execution binding, no required new
read/journal transaction grants and no delete grant; three non-SUCCEEDED management records need
exact adopted evidence treatment. The proposed authority was tested in memory against fresh
records, owned snapshots, provenance and current state/Game references; all three exact cases
matched. Their raw status stays FAILED, and no historical execution/CloudTrail investigation
was repeated. The authority itself still requires this Draft's review and future release.

No candidate exists today. This is a normal result, not a reason to make snapshots, move time,
weaken the rule, remove holds or enable a schedule. Permission evaluation by the future deployed
role, actual recovery and actual deletion remain unqualified.

## Privacy and completeness

Before AWS, 81 existing collector/projection tests passed, and local normal/exception canaries
checked the supplemental save boundary. Raw service responses stayed in memory. The persisted
fields are necessary public identities, times, enum/boolean results, counts, key names and
existing provenance identity; no environment dump/hash, Compose, recovery body, credential,
player data or raw exception was saved. Lambda CodeSha256 is a code identity, not an environment
hash. New adapter/recovery exception and environment canaries also pass.

The initial collector's full pagination/content/pair/journal/stability facts are separate from
its unreviewed historical-manifest flag. Overall deletion safety remains incomplete. Supplements
are later reads, not a new assertion of global atomicity. The current authority comparison has
its own timestamp; future execution requires fresh reads and the formal fence. No observed
snapshot increase was attributed to this collector. Current inventory count remained 14.

JSON output remains status=NO_DELETE, deletion_authorized=false, planned_delete_ids=[],
delete_action_count=0. No snapshot removal, hold release or completeness promotion occurred.

## Repository validation and infrastructure impact

Local full suite: 2,188 passed. Focused checks cover one real SDK send under timeout/HTTP 500,
exact historical authority and mismatches/new references, disabled/provisioned/enabled inputs,
canonical IAM absence, explicit dry-run compatibility, zero candidates, pending preservation,
quiescence/CAS recovery and unchanged provenance. Lint, format and strict typing passed.
Final PR CI is required for normal/NeoForge/Paper and all existing synth scenarios.

Canonical Control Plane: 155 resources, only 13 Lambda Code asset property changes and matching
asset metadata; no IAM, environment, alarm, schedule, table or State Machine change. All six
ASLs are equal raw, under stable offline reference resolution and canonical comparison.
Independent Web: 26 resources, only Web/Auth source bundle Code changes. These are shared-source
packaging effects, not granted capabilities. Asset contents were compared to the implementation.

Future validation-only Stage A changes the existing RETENTION Lambda release env and its policy.
Stage B adds the enabled flag, tag/owner/parent-volume constrained delete statement and explicit
DELETE_ONE constant in the existing RETENTION task payload. Resource identities/counts remain.
These differences are intentional validation artifacts, **not** the canonical deployment output.
There was no actual ChangeSet; no Case D exception was applied. Hashes/property paths are in the
separate JSON comparison. Synth/read-only evidence does not prove live IAM or deletion behavior.

The primary checkout's unrelated tracked/untracked differences were preserved. Implementation
and validation used a new /private/tmp worktree rooted at the actual merge; baseline synth used
a second detached clean worktree. Wiki synchronization belongs to the finalized Draft HEAD in
the primary ignored Wiki, clearly distinguished from adopted main.
