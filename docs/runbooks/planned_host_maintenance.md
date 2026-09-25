# Planned host maintenance

> Current coverage follow-up (2026-09-25): [two DLQ alarms and Web Errors SNS actions](monitoring_coverage.md). All four are always-notify; the three maintenance suppression paths are unchanged. Historical no-notification evidence below remains the record of its original date. Dev qualification is tracked separately in that runbook.

D-111 Accepted / dev deployed and qualified, 2026-09-22. Execution evidence is below.
[Architecture, exact 45-alarm classification and deployment contract](../reviews/planned_host_maintenance.md).
Use for host/runtime migrations, controlled Data EBS maintenance, resize inspection and
IMPORT staging while Minecraft Desired remains STOPPED. A lease does not authorize extra
AWS writes, runtime installation, world replacement or arbitrary recovery.

## Begin / status / end

Use the canonical account/profile; do not substitute placeholder prod configuration.
Choose a unique non-secret maintenance id/reason and a new evidence directory per invocation.
An actor is obtained from STS, not accepted as a user-supplied impersonation field.

```sh
tools/dev-env run -- uv run python -m wishicraft.maintenance_operator status --stage dev --profile wishicraft-dev
tools/dev-env run -- uv run python -m wishicraft.maintenance_operator begin --stage dev --profile wishicraft-dev --id host-maintenance-EXAMPLE --reason paper-world-import --duration-seconds 3600 --execute --evidence-root /private/tmp/wishicraft-maintenance-EXAMPLE-begin
tools/dev-env run -- uv run python -m wishicraft.maintenance_operator end --stage dev --profile wishicraft-dev --id host-maintenance-EXAMPLE --execute --evidence-root /private/tmp/wishicraft-maintenance-EXAMPLE-end
```

`status` is read-only. `begin` and `end` invoke ordinary Reconcile before their conditional
write; they never start/stop EC2, run shell commands or modify Game/world data. Both require
actual EC2 stopped, fresh STOPPED/HEALTHY, absent DNS/Current/Lock, no running workflow or
active SSM command/session, and safe selected Game. On a stopped EC2 no container can execute;
dormant container absence must be inspected during the subsequent approved host access.
Duplicate begin and attempts to replace expired/unclosed leases are rejected. On ambiguous
transaction responses inspect status plus `maintenance#<id>#begin|end|incident` audit items;
do not blindly reissue with a new id. No lease renewal is supported.

Maintenance fences all normal mutating Admission paths across Discord/Web/operator,
including START, even after notification expiry. STATUS/read-only status and scheduled
Reconcile continue. Existing per-function reserved concurrency closures are retained if a
specific migration's release guard requires them, with exact original values restored later.
A maintenance lease does not automatically change or restore Lambda reserved concurrency.

## Approved host maintenance sequence

1. Confirm deployed maintenance-capable Admission, reviewed notification wiring and all
   existing relevant alarms healthy. Capture existing alarm configuration and caller identity.
2. `begin` with enough time (normally 60 minutes, maximum 4 hours). Wait for a fresh
   MaintenanceActive=1, eligible=1 and `wc-dev-maintenance-suppressor` ALARM. Confirm the
   three notification composites reference that suppressor and have the existing SNS action.
3. Resolve the actual target from canonical tags/CloudFormation and compare it with SystemState.
   Start **only EC2** using the individually approved migration/inspection path. Never call
   ordinary Minecraft START or directly launch a workflow during maintenance.
4. Obtain a fresh canonical host probe (ordinary Reconcile). Confirm current-boot heartbeat,
   expected Data EBS/mount, inactive host runtime, container not-found, no Game, DNS absent.
   Suppression requires this positive evidence. While EC2 is pending or observations are
   missing/unknown, notifications can remain enabled; do not mask that uncertainty.
5. Execute only the approved SSM/migration/hash-readback/IMPORT staging work. Keep the lease
   id in evidence. Observe the **unchanged** base metrics and base ALARM states. The expected
   three are DesiredStoppedEc2Running, RuntimeObservationUnknown, DesiredActualDivergence.
   For each composite capture `ActionsSuppressedBy=Alarm`, suppressor identity and history.
   Absence of email alone is not proof of suppression. Check SNS action history explicitly.
6. Existing SNS-connected Lambda Errors/Throttles, workflow failure, heartbeat/identity,
   Data EBS/disk and all other connected alarms continue notifying. Dedicated DLQ alarms
   and Web Errors SNS actions are absent in the baseline and explicitly deferred. If any is ALARM, investigate; do not broaden suppression.
   A running/stopped/unknown container, game mismatch, failed SSM, mount or DNS mismatch
   removes suppression eligibility even with an ACTIVE lease.
7. Before normal EC2 stop, verify no Minecraft container/process and terminal SSM commands;
   close SSM sessions. Use normal StopInstances (no force), and verify actual stopped.
8. Invoke ordinary Reconcile and wait for base alarms to recover naturally. `end` repeats
   the stopped/no-work safety gate and records end time/actor atomically. Verify subsequent
   MaintenanceActive=0, suppressor OK, composites/base alarms OK, STOPPED/HEALTHY and no
   Current/Lock/workflow/SSM/DNS. Normal admission reopens only after successful end.

Suppression uses five-minute samples and CloudWatch asynchronous evaluations. The absolute
expiry expression has a conservative ten-minute margin: notifications can resume up to ten
minutes before expires_at. Plan work and closeout before that cutoff. Do not treat ACTIVE
status alone as proof that actions are suppressed. Delayed/missing observer samples open
notifications. The metrics/state continue to show the true abnormal condition throughout.

## RESTORE-scoped recovery candidate

The repository-only D-113 revision adds `restore_operator recover-maintenance` for
an existing RESTORE journal and exact expired/INCIDENT lease. It atomically installs
a separately approved new lease and retains the previous lease in an audit, while
Admission stays closed. No general auto-renewal or forced host stop is introduced.
[Recovery matrix and separate dev approval](game_restore.md#expiry--interruption-matrix-separate-execution-approval-required).
The separately approved [D-113 limited dev execution](../evidence/game_restore_prepared_2026-09-23.md)
exercised one VOLUME_CREATED / stopped-host INCIDENT → same-RESTORE recovery lease
transition, retaining the same volume and unchanged Game selection. Other interruption
cases remain repository evidence. The historical D-111 execution evidence below is unchanged.

## Expiry and failed closeout

At `expires_at <= now`, the record remains auditable but is inactive; observer publishes
MaintenanceActive=0. CloudWatch's deadline check and missing-data zero prevent indefinite
suppression if observer stops. No DynamoDB TTL cleanup, DisableAlarmActions or manual
EnableAlarmActions is involved. A very short lease (<=10 minutes) never grants suppression
but can verify application expiry and inactive-record handling without starting EC2.

If work fails, first stop/finish SSM, positively verify no Minecraft execution, normally stop
EC2, Reconcile, then safe `end`. Do not erase the lease or claim success while resources are
unknown. If safe closeout is impossible, explicitly record incident:

```sh
tools/dev-env run -- uv run python -m wishicraft.maintenance_operator incident --stage dev --profile wishicraft-dev --id host-maintenance-EXAMPLE --reason host-validation-failed --execute --evidence-root /private/tmp/wishicraft-maintenance-EXAMPLE-incident
```

Incident disables eligibility without clearing the mutation fence or pretending resources
are safe. Normal notifications resume through the next observer/CloudWatch evaluation.
Recovery is a separately scoped operator action; no automatic force stop, cancellation,
Lock deletion, lease extension or world repair. After recovery, run the same safe `end`.

## Codex and migration use

Codex follows begin → verify suppressor → approved EC2/SSM work → normal stop → Reconcile /
base recovery → end → final read-back. Existing host capacity, runtime migration and IMPORT
runbooks link here; their artifact/data/predecessor/read-back and approval gates still apply.
No Discord maintenance command or Admin Web interface is introduced.

## Validation and release evidence

Repository qualification (2026-09-22): 1,671 tests passed, Ruff check/format and
no-incremental mypy (224 source files) passed. Phase1/Target/current-feature Control Plane/Web
synth passed. Baseline comparison proves 40 Control Plane alarms wholly unchanged and three
with only AlarmActions removed; their evaluations are identical. Four new alarm resources,
zero IAM/State Machine definition changes, zero resource removal. [Machine-checked evidence](../evidence/planned_host_maintenance_repository_2026-09-22.json).

Earlier runs are retained: initial focused tests detected expected fixture/count updates and
sandbox PyPI failure; focused v2 passed 201 tests. Full v3 had 1,658 passes and one historical
Phase7 alarm-count assertion failure, corrected to the explicit new count and notification
paths in v4. No failures were converted to skips. Docker and shellcheck are unavailable locally;
CI runs their existing checks. At that repository checkpoint CI, ChangeSets and actual maintenance were pending.
The completed qualification below supersedes that checkpoint, without treating repository
tests alone as CloudWatch delivery evidence.


Implementation `ab15481` passed CI quality/Web and Paper integration, but NeoForge and
standard Docker CREATE fixtures failed because they had never initialized SystemState.
Both fixtures now seed an ordinary initialized state with no maintenance intent; the
production condition remains unchanged. A missing-state CREATE regression proves the
refusal, and the focused 99 tests plus lint/format/no-incremental type (including Web) pass.
The failed CI runs are retained; `0010270` and the final implementation `f6280ee` passed
all three CI workflows, including both repaired Docker fixtures.


## Dev release and real maintenance — 2026-09-22 UTC

[Machine-readable release, alarm actions, expiry and final-state evidence](../evidence/planned_host_maintenance_dev_2026-09-22.json).
Implementation began at `ab15481`; deployed source is `f6280eed973eedc061eca2428001888084777b90`.
[CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35710569214),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/35710569234) and
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/35710569300) all succeeded.
CI: **1,672 tests**, Ruff check, 309-file format check, mypy 231 files, all synth variants,
shellcheck, real Docker/runtime integrations and Chromium checks passed. Local Docker and
shellcheck remain unavailable; CI supplied those checks.

The initially synthesized deadline used unsupported `TIME`. Read-only CloudWatch
GetMetricData rejected it before any deployment. `f6280ee` uses the documented
[EPOCH function](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/using-metric-math.html),
accepted by the actual API; focused maintenance tests passed 57/57 and CI requalified it.
A sandbox-only PyPI DNS failure was rerun with network access, not converted to a skip.

The canonical caller account matched dev `385526546525` in `ap-northeast-1`.
This is the existing live dev workload; the separate placeholder prod stage was not deployed.
Preflight found actual target stopped, STOPPED/HEALTHY, no Current/Lock/running workflow/
active SSM/DNS, three empty queues, 45 OK alarms and one confirmed SNS subscription.
Admission, Discord Command and Web concurrency were captured as UNSET, temporarily set to
zero for release, and restored exactly after the formal lease fenced ordinary mutations.
Observer and Reconcile remained enabled throughout.

Two exact reviewed ChangeSets were executed:

| ChangeSet | Reviewed actual change |
|---|---|
| `maintenance-prepare-f6280ee` | Four alarm additions; 11 Lambda code assets, Admission schema-version environment. Existing SNS actions retained. |
| `maintenance-active-f6280ee` | Only three base AlarmActions removed as substantive change, after the composite paths existed and were verified. |

Both ChangeSets also displayed five existing State Machine Definition modifications.
All six live parsed ASL definitions matched the candidates, with the existing exact five-ID
Case D allowlist and Definition-only/Replacement=false checks. These were semantic no-ops;
no lifecycle change was introduced. The first active review stopped because its helper
allowed that known no-op only in prepare; a new version independently repeated the full
live comparison before execution. No deletion/replacement/IAM/SNS/KMS policy change or
unrelated monitoring update was accepted. Final template exactly matched the active synth;
all prior physical IDs remained, 11 Lambdas were Active/Successful, Web resources unchanged.

The first wiring helper expected a name-based AlarmRule, while CDK correctly emitted the
actual base AlarmArn. A new evidence version verified the exact ARN rather than changing
AWS. Initial history collection defaulted to metric alarms; the subsequent version explicitly
requested MetricAlarm and CompositeAlarm. Earlier incomplete snapshots were retained, and
only the complete history version is used for the suppression proof.

| UTC checkpoint | Observed result |
|---|---|
| 09:47:37 | Formal begin, 60-minute lease, expires 10:47:37; immutable begin audit. |
| 09:51:03 | Maintenance suppressor naturally ALARM; Active and eligible metrics 1. |
| 09:51:49 | Only existing EC2 started; no Minecraft START or workflow invocation. |
| 09:52–10:07 | Fresh probe: SSM online, expected Data EBS identity/mount, no container/Game/runtime, DNS absent. Desired STOPPED and actual DEGRADED retained. |
| 09:56 / 10:01 / 10:06 | DesiredStoppedEc2Running, RuntimeObservationUnknown, then DesiredActualDivergence naturally ALARM under unchanged evaluation rules. |
| 10:07:01 | All three base metrics 1, all three bases and composites ALARM, each composite ActionsSuppressedBy=Alarm. Each SNS action history says Successfully suppressed, actionState=Suppressed, publishedMessage=null, error=null. Other 42 alarms OK. |
| 10:07:49 | Fresh no-container/no-work gate passed; normal EC2 StopInstances, Force=false. |
| 10:09:24 | Actual stopped; ordinary Reconcile STOPPED/HEALTHY; real metrics return to 0. |
| 10:12:16 | All base/composite alarms naturally OK; lease/suppressor still active. |
| 10:12:51 | Formal end repeats external safety checks, records ended_at/actor and immutable end audit. |
| 10:14:45 | Suppressor OK, all 49 alarms OK, STOPPED/HEALTHY. |

Every snapshot compared all 45 original alarm evaluations. Forty existing SNS-connected
alarms kept all properties/actions, two Web Errors alarms kept their absent actions, and
only the three documented base actions moved to their one-to-one composites. ActionsEnabled
remained true. No metric fabrication, alarm-state forcing, DisableAlarmActions, threshold/
period/missing-data relaxation, alarm deletion or subscription change was used.
No unexpected failure was deliberately injected to test always-notify; preserved settings,
regression tests and real unchanged alarm configuration are the evidence. Dedicated DLQ
alarms and Web Errors SNS actions remain the explicitly deferred monitoring gaps.

### Retained-record expiry and final closeout

A second formal lease was created at 10:15:16 for 120 seconds, with EC2 continuously stopped.
At 10:16:00 formal status was active=true, admission_closed=true. At 10:17:40, after the
10:17:16 expiry, the same stored ACTIVE record remained but status was active=false;
admission_closed stayed true until safe end. The real observer produced CloudWatch
MaintenanceActive Minimum=Maximum=1 at 10:16 and Minimum=Maximum=0 at 10:17, before end.
No DynamoDB deletion or forced clock was involved.

This short lease never grants action suppression because of the conservative 600-second
cutoff. Thus this proves application expiry and metric publication with a retained record;
it does **not** claim a real ALARM-to-SNS resumption at expiry. EC2 was not deliberately left
running until the long lease expired. Deadline/configuration tests and AWS documented
current-state action resumption cover that path; normal end's real suppressor release was
separately observed above.

The expired lease safely ended at 10:18:45. Final alarm snapshot at **10:19:00: 49/49 OK**.
Final safety/audit read-back at 10:19:46: Desired STOPPED / actual stopped / HEALTHY, DNS absent,
Current/Lock/running workflow/active SSM command/session absent. All three ingress concurrency
settings were the original UNSET. Four durable begin/end audit events exist in the original
SystemState table; both leases retain who/why/stage/start/expiry/end. Ordinary mutations are
open again. No Minecraft container was started during this qualification.

Host capacity, runtime migration, runtime memory, IMPORT and monitoring runbooks now require
the deployed formal maintenance path for subsequent EC2-only maintenance. Their separate
artifact/data/safety permissions remain applicable. UI/Discord maintenance commands, new
IAM, lifecycle states, data migration and deferred notification-coverage additions are absent.
