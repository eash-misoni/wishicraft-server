# D-114 dev release preflight — held before AWS mutation

**Partial: PR #1 merged; dev provisioning and automatic acquisition not released.**
The 2026-09-26 authorization permits the specified dev release but requires stopping on
new implementation/IAM failures without improvising code, CI bypasses or repeated live operations.
[Structured baseline, commit/tree, template/asset and failure evidence](daily_backup_dev_preflight_2026-09-26.json).

## GitHub and immutable inputs

- Reviewed implementation HEAD: `34d9d50135550ff84f4747e862ed9d2be49f5bd4`.
- Reviewed base: `29c3231aa3052d26cce6a153a8c02d04fdc02ebb`.
- PR #1 validation merge: `255f87d79ae86bac990328e3c0f164f71c62400e`.
- Actual normal merge: `01496a09b8332aab074de9a9c354fd47ff7e70fe`, 2026-09-26 08:35:21 UTC.
- All three reviewed/test-merge/actual-merge trees: `fc6a2bc67bf92e6d8ae46fcd03c9717c313e8315`.
- Draft was removed and ordinary merge performed with exact-head matching. No forced merge,
  fabricated review approval, conflict resolution or protection bypass occurred.
- Stage A candidate: `92df5340afa84ce7bb760bd2cace09b530329cfb`; only dev provision=true,
  enabled=false and release-order documentation. [Draft PR #2](https://github.com/eash-misoni/wishicraft-server/pull/2)
  is **held and unmerged**. Main retains provision=false/enabled=false.
- No stage B or deployment commit, ChangeSet ARN, executed assembly or live asset exists for this attempt.

The authorized order is **disabled provisioning → one formal vps-survival START/STOP → enable →
one natural scheduled BACKUP → at least two natural PROTECTED evaluations**. This establishes the
normal-use boundary and proven full STOP before scheduling. It supersedes the earlier proposed
order only for this release; the previous preparation/review records remain intact. No new manual
baseline BACKUP is authorized. On success dev would remain enabled; that success was not reached.

## Read-only baseline

Canonical wishicraft-dev caller matched account 385526546525 / ap-northeast-1.
Control Plane and target identities matched: i-04fc0629dc4ea466e, attached retained Data EBS
vol-03ac9f534326c345c. Selected vps-survival is the original MATERIALIZED world (generation 1,
generation_counter 2, no current_id override), same immutable Paper 26.1.2/build 53 package.
SystemState was STOPPED/HEALTHY; EC2 stopped; no backup_protection yet. A historical snapshot was
not used as evidence that the current boundary was protected.

No Current Operation, Lock, PENDING/RUNNING Operation, running execution across six workflows,
active SSM command/session, DNS record or unended maintenance was found. Three queues had zero
Visible/NotVisible/Delayed messages. All **51 existing alarms were OK**. Admission, Discord Command
and Web concurrency were UNSET; none was restricted. Observer/Reconcile continued normally.
Thirteen pre-existing snapshots, durable provenance, Game/creation/package/access records and
RESTORE journals were captured read-only. Two journals are ROLLED_BACK and one historical journal
is PLANNED; they were preserved without interpretation as deletable or completed. No host reads,
world hashing, mounts or VPS access were performed.

Lambda configuration (environment values omitted), IAM, live State Machines, SNS/KMS, alarm,
queue and template baselines are saved in the dedicated local evidence root. The initial baseline
command was rejected by automatic approval review because raw Lambda environment saving could
persist secrets; it did not execute. The accepted collector omits **all** environment values,
prints none and hashes none. No credential/secret API was used. Full live-value comparison and
ZIP review were not completed because release validation stopped earlier.

## Blocking configuration/validation mismatch

The exact stage A candidate was synthesized from its own clean committed source; temporary
validated tool links were supplied only for execution and removed afterward. Bytecode writes
were disabled. Current shared/package Control Plane synth succeeded: **15 additions, no removals**,
11 existing Lambda Code changes and only Admission/StopTask/BackupTask Environment changes.
Existing template IAM, alarms, SNS/KMS and State Machine Properties were unchanged.
This template comparison is not a completed deployment/Case D approval.

The existing required CI base command fails:

```sh
cdk synth WishicraftControlPlaneStack-dev --context stage=dev --context phase=8 --context deployment=control-plane
```

It raises `ValueError: daily BACKUP requires the shared runtime contract` at
`infrastructure/stacks/control_plane_stack.py:1275`. The app loads the stage-wide provision flag
also for the single-Game validation context, which has no shared Game contract. The guard correctly
refuses that incompatible combination. A release needs an explicitly reviewed way to keep these
validation configurations separate without weakening this safety guard.

Stage A full tests: **1931 passed, 11 failed**. Ten failures are the same shared-runtime requirement;
one historical infrastructure test expects eleven Lambda functions but now observes thirteen.
These failures are not AWS/network failures and are not hidden by the successful current-feature
synth. The [stage A CI run](https://github.com/eash-misoni/wishicraft-server/actions/runs/36230516002)
provides the remote counterpart. The reviewed disabled-by-default implementation previously had
1942 tests and normal/NeoForge/Paper CI passing; that does not certify the changed stage settings.

## Safe stopping point and remaining proof

**No AWS mutation occurred:** no asset upload, ChangeSet, IAM application, deployment, intake
restriction, rule/action change, START/STOP, snapshot creation/deletion or maintenance lease.
New snapshot count is **0**, new provenance count 0, new alarm count 0. Existing data and receipt/
world references were not modified. No emergency DisableRule or planned rollback was necessary.
There is no release ChangeSet or drift to reconcile. The automation is **not operating** in dev.

Stage B assembly/review, deployed ZIP comparison, every Case D condition, live tracking under
disablement, normal START/STOP, natural scheduling, BACKUP/provenance, duplicate suppression and
56-alarm read-back remain unperformed. Real DescribeExecution IAM, notifications, long thresholds,
restore/content proof, idle STOP, races and TTL recovery also remain unqualified by this attempt.
The prior repository fixtures retain their narrower meaning. Snapshot storage cost is unmeasured;
retention hold collection and deletion remain a separate dry-run/release gate.

Next work must first review the stage-configuration/validation separation and affected test
expectations. No implementation fix or further AWS execution is inferred from this stopped attempt.
Original primary-checkout Terralith changes remain untouched. The stage A execution worktree and
the separate docs-only closeout worktree are distinct; only the latter is merged for closeout.
Final closeout HEAD/CI and learning-Wiki synchronization are reported in the handoff/PR.
