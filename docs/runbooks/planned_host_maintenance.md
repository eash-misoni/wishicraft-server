# Planned host maintenance

D-111 repository procedure; real release/maintenance evidence is recorded separately below.
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
CI runs their existing checks. CI, ChangeSets and actual maintenance are pending. Repository
tests do not by themselves prove CloudWatch action delivery or real suppression.


Implementation `ab15481` passed CI quality/Web and Paper integration, but NeoForge and
standard Docker CREATE fixtures failed because they had never initialized SystemState.
Both fixtures now seed an ordinary initialized state with no maintenance intent; the
production condition remains unchanged. A missing-state CREATE regression proves the
refusal, and the focused 99 tests plus lint/format/no-incremental type (including Web) pass.
The failed CI runs are retained; a new commit/CI must qualify the repaired fixtures.
