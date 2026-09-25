# Planned host maintenance — D-111

> Current coverage follow-up (2026-09-25): [two DLQ alarms and Web Errors SNS actions](../runbooks/monitoring_coverage.md). All four are always-notify; the three maintenance suppression paths are unchanged. Historical no-notification evidence below remains the record of its original date. The linked runbook records dev release, two successful SNS action tests and user-confirmed email receipt; this does not alter the historical D-111 proof below.

Accepted / dev deployed and qualified on 2026-09-22. CI passed 1,672 tests plus
lint/format/type/synth and real Docker integrations. Three real base ALARMs retained,
three SNS actions explicitly suppressed, safe end and retained-record expiry verified.
[Execution evidence](../evidence/planned_host_maintenance_dev_2026-09-22.json) and
[operator closeout](../runbooks/planned_host_maintenance.md#dev-release-and-real-maintenance--2026-09-22-utc).

## Current architecture and inventory

2026-09-22T08:49:31Z read-only inventory: canonical account 385526546525,
ap-northeast-1, stage dev. This is the existing production workload; prod.yaml remains
unconfigured and must not be synthesized/deployed by guessing its null values.
45 metric alarms, zero composite alarms: 43 Control Plane alarms publish directly to
`wc-dev-monitoring`; two Web Errors alarms have no actions. No notification aggregation.
CloudWatch service publishes to the existing KMS-encrypted SNS topic; subscriptions
remain unchanged. CloudFormation/CDK owns alarm actions.

Reconcile and MonitoringObserver run independently every five minutes. Reconcile writes
normalized observation/health/errors monotonically, without changing Desired. Observer
consistently reads SystemState, Locks and RuntimeHeartbeats, directly describes EC2 and
publishes custom metrics. Desired STOPPED/RUNNING is operator lifecycle intent; Actual is
direct resource observation; persisted Observed is timestamped evidence; Health summarizes
that observation. None becomes MAINTENANCE or is repaired by this feature.

Historical evidence: Paper IMPORT on 2026-09-22 explicitly records all three expected
alarms in [the import runbook](../runbooks/paper_world_import.md). Host capacity, common
memory and whitelist migration runbooks also record temporary maintenance alarms.
No dedicated SSM/host-migration/IAM/provenance alarm exists: their failures surface through
existing Lambda/workflow/observation alarms. There are two DLQs but no dedicated queue
alarms in the baseline. The user explicitly deferred these monitoring gaps to another slice. No DLQ alarm is added;
the two Web Errors alarms retain their empty actions. Do not claim existing DLQ/Web
notification delivery was tested or preserved where no such path exists.

## Complete baseline classification (45/45)

All rows are deployed dev alarms. Separate prod resources are **not applicable**: stage
configuration is incomplete, not an additional uninspected set of 45 alarms.
The split is 3 suppressible, 40 always-notify and 2 not applicable to SNS suppression.
The two pre-existing Web notification gaps remain
explicit below and are not represented as working notification paths.

| Existing physical alarm | Classification | Action change |
|---|---|---|
| `WishicraftWebStack-dev-AuthErrors8D0EDC3D-7sFK2J7cGupT` | not applicable（SNS通知なし） | 既存actionなしを維持。補完は別slice |
| `WishicraftWebStack-dev-WebErrorsC4BB781A-MQwCfef3vtzj` | not applicable（SNS通知なし） | 既存actionなしを維持。補完は別slice |
| `wc-dev-admissionfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-admissionfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-auto-stop-evaluator-silence` | always-notify | 既存SNSを維持 |
| `wc-dev-autostopevaluatorfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-autostopevaluatorfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-autostopwarningblockedalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-backuptaskfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-backuptaskfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-backupworkflowfailurealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-datafilesystemobservationunknownalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-datafilesystemusagehighalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-desiredactualdivergencealarm` | maintenance-suppressible（条件付き） | 既存SNS → 一対一Composite → 同じSNS |
| `wc-dev-desiredrunningnotreadyalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-desiredstoppedec2runningalarm` | maintenance-suppressible（条件付き） | 既存SNS → 一対一Composite → 同じSNS |
| `wc-dev-discordcommandfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-discordcommandfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-discordmessagefunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-discordmessagefunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-expiredoperationlockalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-monitoringobservationunknownalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-monitoringobserverfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-monitoringobserverfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-reconcilefunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-reconcilefunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-resetworkflowfailurealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-retentiontaskfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-retentiontaskfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-retentionworkflowfailurealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-runtimeheartbeatunavailablealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-runtimeidentitymismatchalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-runtimeobservationunknownalarm` | maintenance-suppressible（条件付き） | 既存SNS → 一対一Composite → 同じSNS |
| `wc-dev-scheduledstopcancelledalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-starttaskfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-starttaskfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-startworkflowfailurealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-statusexecutorfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-statusexecutorfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-stoptaskfunctionerrorsalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-stoptaskfunctionthrottlesalarm` | always-notify | 既存SNSを維持 |
| `wc-dev-stopworkflowfailurealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-switchworkflowfailurealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-systemstateobservationstalealarm` | always-notify | 既存SNSを維持 |
| `wc-dev-targetrunningtoolongalarm` | always-notify | 既存SNSを維持 |

## Lease and concurrency contract

Existing SystemState current item gains a `maintenance` map; schema_version=1, id,
status=ACTIVE|ENDED|INCIDENT, stage, reason (non-secret identifier), actor (STS ARN),
started_at and expires_at (UTC epoch seconds). End adds ended_at/ended_by; incident adds
incident_at/incident_by/incident_reason. Optional external operation reference is the
operator-selected id. No new DynamoDB table, no TTL deletion, no lifecycle enum change.

Effective active requires a valid ACTIVE lease with started_at <= now < expires_at.
Duration is 60..14400 seconds; no renewal/takeover. An expired stored map is inactive.
Application expiry does not depend on DynamoDB TTL. Each begin/end/incident atomically
writes a create-only audit item `system_id=maintenance#<id>#<event>` in the same table.
Audit retains stage/who/why/times; natural expiry time is the immutable expires_at.
Reconcile only updates its owned attributes and never removes this map or audit.

Begin requires fresh STOPPED/HEALTHY, actual target EC2 stopped, DNS absent, no Current,
no Lock (including expired Lock), no RUNNING workflow, no active SSM command/session,
and ACTIVE selected Game. An EC2 stopped observation proves no executing Minecraft;
it does not inspect dormant containers on disk. On boot, fresh host probe must positively
prove container `not-found` before suppression is eligible. Stopped containers are not
silently accepted as clean maintenance state.

Begin CAS binds desired_revision/observed_at/Desired/no Current and no Lock in a transaction.
START/STOP/SWITCH/RESET/BACKUP/RETENTION add the maintenance condition to the existing
ownership transaction; CREATE and WHITELIST add an atomic condition check. STATUS and
read-only Web remain available. Duplicate begin is rejected (status supplies recovery).
Expired/incident unclosed lease continues to fence normal mutations; only safe end reopens
them. Idempotent old requests may return their existing result but cannot launch new work.
Operator AWS/SSM access is not newly authorized by a lease; existing runbook permissions
and single-operator coordination still apply. Direct admin AWS calls cannot be fenced
atomically with DynamoDB and must follow this runbook.

## Monitoring and notification contract

The existing observer emits MaintenanceActive, MaintenanceSuppressionEligible and
MaintenanceExpiresAt. Existing abnormal metrics are unchanged. Eligibility requires a
valid lease, Desired STOPPED, no Current/Lock, matching target identity, fresh observation,
no observation errors, absent DNS and no observed Game/READY. Running-state eligibility also
requires fresh valid heartbeat with no active Game, unknown protocol, and no heartbeat identity
or filesystem-observation error. Stopped EC2 must have a
HEALTHY/empty-discrepancy observation. Running EC2 requires a post-launch observation,
SSM online, Docker active, expected mount, container not-found, inactive runtime,
Minecraft not-running/protocol not-applicable, DEGRADED health and exactly the expected
`dns-missing-when-required` discrepancy. Unknown/foreign/running container, unexpected
DNS/Game/run/mount/SSM state never authorizes suppression. Boot/stop transitions without
positive evidence may notify; maintenance is not a blanket grace period.

One suppressor metric alarm uses FILL(eligible,0) and absolute-expiry metric math.
`EPOCH(eligible) + 600 < FILL(expiry,0)` provides a conservative two-period deadline margin.
Missing data becomes zero, not reuse of an indefinitely positive sample. Minimum statistics
allow a zero sample to revoke eligibility within a period. WaitPeriod=0 and ExtensionPeriod=0.
The suppression window ends conservatively before lease expiry (up to ten minutes early
at the five-minute metric cadence); it is not an exact wall-clock notification SLA.
Lease active itself remains exact application-time semantics. CloudWatch evaluates and
propagates asynchronously; expiry/end never waits for a TTL delete or operator re-enable.
Short leases of ten minutes or less are useful for expiry tests but never authorize suppression.

Three separate composites each mirror one base ALARM. Only their SNS actions are suppressed;
base and composite state remain visible. One OR aggregation would lose independent alarm
notifications while another alarm is already ALARM, so is not used. All other SNS actions,
thresholds, periods and missing-data treatment remain unchanged. The suppressor has no SNS
actions. Existing observer IAM is unchanged; no new Lambda, table, schedule or runtime role.
Additional resources: 1 suppressor + 3 composites = **4** (45 → 49 total).
Additional custom metrics: 3. Web alarms, DLQs and SNS/KMS policies are unchanged.
No new grants are required.

Composite action suppression is selected because eligibility depends on live observations,
not solely the clock. One-time Alarm Mute Rules have native expiry and could preserve direct
base actions, but cannot by themselves revoke on unexpected runtime/identity conditions.
Implementing an imperative mute-rule controller would need more write IAM and ownership.
Manual DisableAlarmActions/EnableAlarmActions is rejected because cleanup can be forgotten.

AWS semantics: [action suppression](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarm-suppression.html)
and [mute-rule transitions](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarm-mute-rules-behaviour.html).
When suppression ends with the composite still ALARM, CloudWatch executes the current-state
action; a new base ALARM transition is not required. The real integration below proves suppression and normal end. Expiry with an ongoing
base ALARM was not deliberately prolonged on EC2; that resumption path relies on these
AWS semantics, the deployed deadline/configuration and repository expiry tests.

## Release and rollback

1. Verify full tests/lint/format/type/synth/CI, clean committed source, caller and safe state.
2. Save deployed templates/physical IDs/actions; review new prepare ChangeSet with context
   `maintenance_notification_mode=prepare`. This creates composites with SNS while retaining
   all base SNS actions. Check no replacement/deletion/unrelated changes. Execute only that
   reviewed ChangeSet. Confirm all three composite paths, suppressor wiring and topic ARN.
3. Deploy default `active` mode through a second reviewed ChangeSet. Only the three base
   SNS AlarmActions are removed. Two-stage rollout avoids removing a path before its
   replacement exists. Temporary duplicate notifications in prepare are safer than a gap.
4. Web stack is not deployed; its existing empty Errors actions remain unchanged.
5. Verify all remaining baseline alarm properties and actions exactly, including Errors,
   Throttles, workflow failure, storage, heartbeat, identity and auto-stop alarms. Record the
   deferred DLQ notification gap without treating it as a successful notification test. No SNS subscription changes, no metric injection/alarm-state forcing.
6. Perform [the bounded maintenance runbook](../runbooks/planned_host_maintenance.md).

Rollback first restores the three base SNS actions in prepare mode and verifies them, then
rolls back code/suppression infrastructure to saved deployed templates. Never remove the
only notification path. Close out any lease and preserve audit before reverting Admission;
otherwise reverting its fence could admit START against ongoing maintenance. Preserve
existing alarms; do not delete base alarms or relax thresholds. New-resource removal during
rollback requires the same explicit release scope review.

State Machine definitions must remain structurally identical in both deployment stages. Dependency-propagated Case D changes
require existing exact logical-ID/semantic proof; unknown differences stop before execution.
Any unexpected IAM/public boundary, replacement, durable-data mutation or resource change
stops release. Repository completion and production qualification are reported separately.
