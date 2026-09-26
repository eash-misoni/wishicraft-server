# D-114 Daily shared-volume BACKUP

Status: Accepted for repository preparation (2026-09-26 request). **Not deployed or enabled.**
Requirements: BAK-002/003/004/005/006, OPR-004/007/010, NFR-008.
The user request supersedes Game-specific daily/pre-RESET BACKUP proposals. RESET capability,
package type and Game name never select protection coverage. This is an independent D-101 slice.

## Authority and transaction boundaries

`SystemState.backup_protection` is the sole current authority for the configured shared Data EBS.
No table, index, TTL, world hash scan, Game dirty field or existing provenance schema is added.
The map contains `schema_version=1`, `volume_id`, monotonically increasing `boundary`,
`protected_boundary`, `oldest_at`, `unknown_since`, `stopped_at`, `attempts`, `intent`, `last_success`.
`intent` contains the fixed Operation ID, captured boundary, request time, automatic/manual source,
status and, on failure, error/finish time/safe-retry evidence. `last_success` contains Operation,
snapshot, captured boundary, EC2 acquisition time and successful verification time.
Operations gain additive `backup_boundary`; existing result/provenance/recovery/tag formats remain unchanged.
The map has no TTL. Missing Operation/idempotency records never erase an unresolved intent.
Old successful provenance pairs remain immutable in Backups; no historical tags are rewritten.

`desired_revision` is insufficient: it models Desired changes, not every possible disk mutation,
failed startup, SWITCH/RESET preparation or management write. START/SWITCH/RESET **Admission**
conservatively advances the small volume boundary in the same transaction as Operation,
idempotency, Lock and Current Operation. This precedes EC2 startup, materialization, whitelist
projection and world changes. Even failure before actual disk changes can require a BACKUP;
zero players or a failed START cannot prove a clean volume. An existing idempotent request does
not advance the boundary twice. A rejected admission transaction makes no protection change.
STATUS/Reconcile do not modify protection clocks. No new workflow states or snapshot calls are
inserted into SWITCH/RESET; their existing save, stop, old-world retention and start remain.

The existing normal STOP completion writes `stopped_at` once, atomically with STOP SUCCEEDED
and Lock/Current cleanup. Scheduled idle STOP uses exactly this same completion. Repeated STOP
while dirty does not reset the waiting clock. START/SWITCH/RESET ends the stopped interval but
preserves the oldest unprotected/unknown time. The next normal STOP starts a new stopped clock.
A completed STOP is never rewritten because a later BACKUP fails.

All new manual and scheduled BACKUP admissions capture the boundary and intent under the same
Lock transaction. The workflow still performs fresh Reconcile, actual stopped/source validation,
full shared Game/package recovery freeze, one-way CreateSnapshot reservation, pending polling,
completed/source/owner/exact-tag/storage-tier checks, and recovery/provenance verification.
Only `complete_owned` with successful BACKUP and the provenance pair advances protection,
in the **same DynamoDB transaction** as the existing terminal write and Lock release.
Acquisition is EC2 `StartTime`; confirmation is the later transaction time. Snapshot pending,
partial failure or unknown provenance never advances protection. An old boundary cannot cover a
newer one, and an older completion cannot clear a newer intent. Lock ownership is never released early.

## Periodic route and authorization

There is one five-minute EventBridge route: evaluator -> dedicated internal Admission Lambda ->
existing `OperationAdmissionService` -> existing BACKUP Standard workflow. No STOP event trigger,
queue, direct evaluator StartExecution/CreateSnapshot, forced stop or backup-only EC2 start exists.
The dedicated function is required to keep internal authentication separate from payload fields:
only the evaluator is granted invocation. Existing public Admission rejects BACKUP/SCHEDULE;
Discord/Web authorization is unchanged. Setting `requested_by=SCHEDULE` is not authority.
The internal handler accepts only a version and integer boundary, constructs its own BACKUP
request/source/key and cannot dispatch other operation types.

Evaluator reads SystemState, global Lock, relevant Operation and actual EC2, requires fresh
observations (<=600 seconds), and reports protected/running/maintenance/other-operation/available/
running-backup/failed/unknown/observation-unknown/disabled separately. The workflow retains its
stronger volume binding and complete recovery validation; evaluator prechecks are not final proof.
Admission atomically compares the protection map, stopped/healthy/observed timestamp,
maintenance fence and empty Current/Lock with the fixed Game lifecycle condition. START winning
first invalidates the candidate. BACKUP winning first retains existing exclusion for its entire
execution. A user may receive the ordinary operation-conflict response and retry after BACKUP.
An evaluator read or unaccepted candidate creates no fence or reservation that can block play.

The request key is volume + captured boundary + bounded attempt number, independent of selected
Game. Resolve current durable intent before Game selection. Accepted/unknown intent is never
recreated, even after the underlying Operations/idempotency records expire. Lost Admission or
workflow-start responses cause reconciliation of the same intent; unknown execution is not retried.

Maximum **three automatic accepted attempts per unprotected episode**. After the first proven
safe failure wait >=15 minutes; after the second wait >=60 minutes. A new unresolved snapshot
or exhausted attempts requires operator reconciliation. A new dirty boundary during the same
unprotected episode does not reset attempts. Full protection resets the episode.
Safe retry is limited to workflow-start failure/observation/preflight/source failure with **no
create reservation or snapshot identity**, or the existing explicit EC2 rejection classification
`BACKUP_SNAPSHOT_CREATE_FAILED` with no snapshot identity. Reserved ambiguous CreateSnapshot,
snapshot pending/error, timeout, lost ownership or incomplete provenance is never retried as a
fresh snapshot. Known snapshot error is FAILED with `safe_retry=false`; ambiguous outcomes are
UNKNOWN. Error/timeout without terminalization is reconciled to UNKNOWN by the evaluator once
its Operation is terminal, missing or past deadline. It does not repair locks or invent success.
Operator investigation uses existing BACKUP recovery procedures; resolving a disputed intent is
an individually reviewed operation, never raw state editing to make the alarm disappear.

## Bootstrap, administration and disablement

Absent protection means an initial baseline is required, not that old snapshots cover today.
`oldest_at=null` with `unknown_since` explicitly represents an unobserved prior interval. The
unknown interval may predate first observation; its age is a lower bound, never a zero-loss claim.
An existing successful last STOP plus fresh stopped/healthy/idle observation may establish the
initial waiting point. Otherwise the next normal STOP (or explicit safe manual BACKUP) is required.
The historical snapshot/provenance remains untouched. Deploy only with no unfinished operation;
an old in-flight BACKUP without a captured boundary cannot be retroactively certified.

| Change path | Protection treatment |
|---|---|
| Normal START / STOP, idle STOP | Admission boundary / normal full STOP completion |
| SWITCH / RESET | Dirty at admission; accumulate until full STOP, no external reset point promised |
| CREATE metadata | No Data EBS write; first materialization is covered by START/SWITCH |
| Whitelist Control Plane change | Metadata alone is not an EBS write; next startup projection is covered |
| IMPORT / RESTORE / maintenance | Required explicit management BACKUP/handoff remains; maintenance begin/recovery dirties tracked protection with unknown=true |
| Maintenance end | Does not infer unchanged or protected; does not clear the unknown interval |
| Arbitrary root file edits outside official maintenance | Not automatically detectable; operator must use maintenance and explicit post-change BACKUP |

Maintenance keeps an existing stopped waiting clock; it does not reset an overdue interval.
Its current record is atomically fenced against protection changes. A maintenance session that
began before tracking is also covered by initial unknown state. Management tools must run from
this finalized repository; running an old tool that omits invalidation is not covered.

Stage supplement `config/daily-backup-<stage>.json` fields `provision` and `enabled` default false when absent. Enabled requires
provision and the shared runtime configuration. Defaults add no new evaluator/schedule/alarm.
Tracking is deployed with the existing phase-8 Admission/STOP/BACKUP code even while automatic
acquisition is disabled. Provision=true/enabled=false stages a disabled schedule and disabled
alarm actions. Disablement prevents new automatic acceptance, preserves intent/history and
never cancels BACKUP or removes its Lock. Reenablement uses the preserved dirty boundary.
Deployment of code/config, enabling schedule and real execution require separate dev approval.

## Monitoring

Existing BACKUP workflow/task failure and timeout alarms and SNS topic are retained. Five small
alarms (Stage/SystemId dimensions only) are added when provisioned; none joins maintenance's
three suppressed notifications. Five-minute evaluator metrics include real zero values.

| Metric | Evaluation and interpretation |
|---|---|
| DailyBackupStoppedOverdue | >=1 after >=1800 seconds from saved normal STOP while still unprotected; running/failed/unknown/competition/maintenance reason is in status and structured evaluator log |
| DailyBackupIntervalOverdue | >=1 after >=86400 seconds from oldest dirty or known start of unknown interval, including continuous running; no forced stop |
| DailyBackupNeedsOperator | >=1 for unresolved result or failed/non-retryable/exhausted attempts; existing workflow alarm covers transient safe-retry failure |
| DailyBackupObservationUnknown | >=1 when the evaluator completes but required state is not fresh/safe |
| DailyBackupHeartbeat | Minimum <1, three missing five-minute periods, missing=breaching only while enabled |

Heartbeat is emitted only after reads, required protection persistence, eligible Admission response
validation and metric publication succeed. Exceptions produce no healthy signal. An observed
unsafe state is a measured observation result, distinct from evaluator execution failure; the
observation-unknown metric separates them. Missing overdue/error data is not substituted for a
normal datapoint: those alarms use notBreaching, while heartbeat independently detects absence.
Enabled immediately starts missing-signal evaluation; allow <=15 minutes for the first healthy
scheduled samples before diagnosing deployment. Planned disabled has schedule and actions off;
unexpected absence while enabled raises heartbeat. Normal maintenance still emits signals and
retains all BACKUP warnings. No custom notification delivery or five-minute repeated emails;
SNS is driven by CloudWatch ALARM transitions. Successful protection clears overdue signals;
restart clears only the stopped warning; a healthy signal clears missing/observation alarms.
Failure alarms can overlap overdue warnings because they describe different conditions; operator
status is the consolidation point. Snapshot age alone never warns when no new use exists.

30 minutes and 24 hours are warning thresholds, not completion SLAs or maximum data-loss bounds.
A long run or repeated short stops can postpone a usable external recovery point indefinitely.

## Resources and validation limits

Existing three Lambda environments gain `PROTECTION_VOLUME_ID`; their asset changes include the
shared Python package. Optional resources: two Lambda functions, two log groups/roles/policies,
one EventBridge rule and invoke permission, five CloudWatch alarms. No new workflow/table/queue.
Evaluator: GetItem on state/lock/Operation, system-key-limited state UpdateItem, EC2 DescribeInstances,
namespace-limited metric publication, invocation of only internal Admission. Internal Admission:
existing admission table transaction actions, Games read/condition check, Lock DeleteItem for
existing startup-failure cleanup, DescribeInstances, only BACKUP StartExecution/DescribeExecution.
No Observer role expansion, snapshot rights, secret reads, host/EC2 mutations or deletion rights.

Tests use fixed clocks and serializer/repository/handler boundaries. Synth proves templates,
not real IAM, scheduler cadence, SNS delivery or live 30-minute/24-hour observation.
Validation results and exact release plan are in [the runbook](../runbooks/daily_shared_backup.md).
