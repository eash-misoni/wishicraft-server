# Monitoring coverage: two DLQs and Web Lambda Errors

2026-09-25: accepted narrow NFR-008 / D-111 follow-up; dev release and both bounded
notification-action tests completed, including user-confirmed receipt of both emails.
[Exact ChangeSets, one-off CP exception and closeout evidence](../evidence/monitoring_coverage_dev_2026-09-25.md).
Baseline: `f938ba6cdeea74f91e878a687df7e6044b33e227`, 49 alarms.
No monitoring redesign, application handler, IAM, queue or Minecraft change.

## Configuration and classification

| Target | Alarm / notification change | Classification |
|---|---|---|
| Discord Message DLQ | `wc-dev-discordmessagedlqvisiblealarm` added | always-notify |
| Status Executor DLQ | `wc-dev-statusexecutordlqvisiblealarm` added | always-notify |
| AuthErrors | Existing `AuthErrors8D0EDC3D`, add existing SNS ALARM action | always-notify |
| WebErrors | Existing `WebErrorsC4BB781A`, add existing SNS ALARM action | always-notify |

Each DLQ uses `AWS/SQS / ApproximateNumberOfMessagesVisible`, its existing queue's
exact `QueueName`, Maximum, 300 seconds, >=1, EvaluationPeriods=1,
DatapointsToAlarm=1, TreatMissingData=notBreaching. Only ALARM notifies.
Names follow existing `resource_name(prefix, stage, construct_id.lower())` conventions.
No retry-queue alarm, custom producer, polling Lambda or OR aggregation is added.
Automatic DLQ transfers are not reliably represented by NumberOfMessagesSent;
time-direction Sum of a count gauge is not the backlog count.

Web retains its existing physical alarms and logical IDs: AWS/Lambda Errors,
FunctionName of the respective Lambda, Sum / 300 seconds / >=1 / one evaluation
period / notBreaching. Existing absence of explicit DatapointsToAlarm remains.
Only AlarmActions changes. Resolve physical alarm names from CloudFormation, never
recreate or rename them. Web independently imports the SNS ARN from stack account,
region and stage naming; it does not instantiate Control Plane or create dependencies.

All four publish to existing `arn:aws:sns:ap-northeast-1:385526546525:wc-dev-monitoring`
in dev. CloudWatch is the publisher, not either Web Lambda. Existing SNS topic policy
permits CloudWatch sns:Publish; existing notification-key policy permits CloudWatch
Decrypt/GenerateDataKey (and existing encryption permissions). Check actual policies
and subscription metadata before release; the import alone is not permission proof.
No policy/grant/subscription or email endpoint changes are part of this slice.

Maintenance suppression remains exactly DesiredStoppedEc2Running,
RuntimeObservationUnknown and DesiredActualDivergence, with their existing independent
composites and suppressor. These four coverage targets never enter that path.
Always-notify means ordinary CloudWatch action conditions apply even during maintenance;
it does not introduce repeated or immediate notification. No lease is needed for this test.
Expected total: 49 + two DLQ metric alarms = 51 (48 metric, three composite).

## Limits

SQS counts are approximate. Visible excludes in-flight/invisible and delayed messages.
OK is neither incident resolution nor proof of emptiness across every queue state.
Inactive queues can omit metrics and resume with delivery delay; notBreaching is a
missing-data evaluation policy, not an AWS measurement of zero. A 300-second period
is not an email-within-five-minutes SLA. No extra metric or metric math is added to
hide those limits. [SQS metric semantics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html)
and [inactive-queue reporting](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/monitoring-using-cloudwatch.html).

## DLQ response

1. Record UTC time, alarm, account/stage, queue and associated Operation, if known.
   Resolve ownership from Control Plane CloudFormation before examining a similarly named queue.
2. Use GetQueueAttributes first: ApproximateNumberOfMessages (Visible),
   ApproximateNumberOfMessagesNotVisible, ApproximateNumberOfMessagesDelayed,
   retention/redrive settings. Compare AWS/SQS metric timestamps and existing logs.
3. Identify the failing Lambda/event mapping and delivery path. Status Executor DLQ
   receives failures from the Operations DynamoDB stream mapping (STATUS INSERT,
   batch size 1, bisect enabled, retry attempts 2). Discord Message DLQ receives both
   DynamoDB stream failure destinations and redrive from Discord Message Retry queue
   (maxReceiveCount=3). Correlate Operation/message revision and delivery records with
   `/aws/lambda/wc-dev-status-executor` or `/aws/lambda/wc-dev-discord-message` logs.
4. SQS redrive preserves the delivery queue message; Lambda DynamoDB stream SQS
   failure destinations carry invocation/batch metadata, including stream/shard/sequence
   information, rather than guaranteeing the original complete stream payload.
   Stream records have bounded retention. Inspect the actual path before proposing replay;
   do not send either kind back blindly. [Lambda failure destination contract](https://docs.aws.amazon.com/lambda/latest/dg/services-dynamodb-errors.html).
5. ReceiveMessage changes visibility and receive counts; it is not harmless read-only
   investigation. Do not automatically receive/redrive/purge/delete. Preserve evidence
   and obtain separate authorization for message handling/recovery.
6. A DLQ entry alone does not establish Minecraft lifecycle failure: STATUS processing
   or Discord progress delivery can fail independently. Check canonical Operation state.

## Web response

Correlate AuthErrors with Auth Lambda, or WebErrors with Web Lambda, using
CloudFormation physical IDs, UTC window, Request ID and existing exception logs.
Lambda Errors does not count every HTTP 401/403 or normal authorization rejection;
handled error responses may not count as execution failures. Do not alter auth logic
or infer complete HTTP failure coverage. Notification alone never authorizes Minecraft START/STOP.

## Bounded dev release and action test

Use canonical `wishicraft-dev`, account 385526546525, ap-northeast-1. Record selected
Game and fresh STOPPED/HEALTHY, actual EC2 stopped, absent Current/Lock/running workflows/
active SSM/DNS/unclosed maintenance, all three queues empty and existing alarms OK.
Unknown/running state or pre-existing queue contents/Web ALARM stops release; do not
stop a host or drain queues to satisfy the gate. Keep Observer/Reconcile enabled.
Capture original ingress concurrency. A pure monitoring-only diff does not itself require
closure; this release used the existing stop/no-work/temporary-ingress guard for its
separately approved CP display exception and restored the original values afterward.

Generate actual assemblies from a clean worktree at the finalized implementation commit,
with bytecode disabled and a dedicated output/evidence root. Record template and asset
hashes. Compare baseline templates: only two new alarms and two Web AlarmActions;
queue/event mapping/IAM/SNS/KMS/other alarms and suppression must be unchanged.
Review independent Control Plane and Web ChangeSets. No deletion/replacement/new IAM.
Any unavoidable Lambda Code changes require deployed ZIP comparison. Dependency-only
State Machine changes require the full existing [Case D guard](ssm_ready_probe.md#case-d-release-guard--explicit-dependency-propagated-semantic-no-op),
including exact allowlist, Definition-only, Replacement=False and raw/resolved/canonical
ASL plus role equivalence. Execute exactly the reviewed ChangeSets and read back all properties.

Only after deployment, ordinary OK evaluation, empty queues/no real Web errors and
SNS-only actions, show each actual alarm name/ARN/state and unique test ID to the user.
At most one ALARM SetAlarmState each: Discord Message DLQ, then WebErrors; two total.
StateReason must contain `WISHICRAFT PLANNED NOTIFICATION TEST`, the ID and an explicit
statement that this is not real DLQ backlog/Web failure. Save before/after configuration,
state/action DescribeAlarmHistory, action success/failure and natural metric evaluation
recovery. Do not retry ambiguous responses without history inspection. If the first
notification path fails, hold the second and investigate read-only.

Never SetAlarmState OK; never target composites/suppressor, inject AWS namespace metrics,
send test queue messages, deliberately fail Lambdas or switch/disable actions. Do not
substitute direct SNS Publish. Normal evaluation may take time; retain unconfirmed state
rather than fabricating OK. [SetAlarmState semantics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html).

This proves notification actions, not DLQ transfer → metric detection → notification or
real Web exception behavior. CloudWatch SNS action success is distinct from final email
receipt. SNS aggregate metrics do not prove a particular email reached an inbox.
Status Executor DLQ/AuthErrors get configuration verification only, no positive action test.

Finish by repeating safety inventory, queue counts, all 51 normal alarm states,
47 unaffected baseline configurations and both unchanged Web evaluations, exact SNS/
KMS/subscriptions, ingress concurrency and no unfinished release/ChangeSet. Preserve
Game/world/package/policy; no host start or full world byte hash is needed or claimed.

## Separate backlog

Retry queue backlog, API Gateway 4xx/5xx and normal authentication rejection coverage
remain outside this slice. SNS delivery-path observability beyond existing history/metrics
and periodic real failure-path exercises require separate scope. This is not comprehensive
failure detection or completion of all monitoring.

## Repository qualification

[Machine-readable comparison and test evidence](../evidence/monitoring_coverage_repository_2026-09-25.json): 1,824 tests passed, Ruff and 341-file format check passed, mypy 252 files passed. Five actual synth comparisons preserve every existing Control Plane resource and every Web resource except the two AlarmActions. Docker/shellcheck were unavailable locally; standard/NeoForge/Paper CI all passed for the implementation commit (links in the closeout evidence). Failed local helper/test attempts are retained separately and do not count as success.

## This release's one-off CP exception

Existing Case D guard condition 3 was **not satisfied**: no updated dependency was evidenced.
The user separately approved only the full CP ChangeSet ARN fixed in the closeout, after
both display views and all six raw/resolved/live/canonical definitions, Role/configuration,
Tags and actual identities were compared. Internal display cause remains unknown; do not
label it dependency propagation. This does not relax the existing guard for future releases.
Returned revision IDs and actual CloudFormation events are recorded separately; semantic
equality is not proof that no UpdateStateMachine API was ever called. The existing guard
and future approval boundaries remain unchanged.
