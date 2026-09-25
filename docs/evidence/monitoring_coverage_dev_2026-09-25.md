# Monitoring Coverage dev closeout — 2026-09-25

**Completed for the four specified targets.** Implementation
`e233e9f2fe6ac8d7d0aeb722886f7b273398013f`, baseline
`f938ba6cdeea74f91e878a687df7e6044b33e227`.
[Structured release / properties / hashes / action histories](monitoring_coverage_dev_2026-09-25.json),
[operator runbook and limits](../runbooks/monitoring_coverage.md),
[repository comparison](monitoring_coverage_repository_2026-09-25.json).
This is not completion of all monitoring or a real-failure end-to-end exercise.

## Repository and immutable execution input

HEAD and fetched origin/main matched the baseline. The original checkout already had
Terralith client-observation edits in README, delivery plan, decisions and the Terralith
runbook, plus two untracked evidence files. They were neither committed nor discarded.
Implementation was committed and pushed separately; release used clean detached worktree
`/private/tmp/wishicraft-monitoring-release-e233e9f` at that exact commit.
Only development-tool symlinks were temporarily supplied for synth, then removed;
source was committed and clean, and every staged asset was verified free of bytecode.
Assemblies were generated into a dedicated output root with PYTHONDONTWRITEBYTECODE=1.
The execution source differs from the intentionally dirty original checkout.

Local verification: **1,824 tests**, Ruff, 341-file format check, mypy 252 files passed.
Actual synth comparison covered Phase 7, Phase 8, current-feature Control Plane, and
independent Web with/without current features. Existing Control Plane resources were
identical; only two alarms were added. Web changed only the two AlarmActions relative
to the repository baseline. Actual release synth used two_games/reset/game_creation/
whitelist_management/game_packages and canonical Web context.
[Standard CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/36097378887),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36097378888),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36097378895) all succeeded,
including Docker, browser and shellcheck validation unavailable locally.
Earlier helper/test failures remain recorded; none was converted into a success.

## Exact release and the separately authorized display exception

Canonical caller matched account 385526546525, region ap-northeast-1, profile wishicraft-dev.
Before execution: selected vps-survival, STOPPED/HEALTHY, EC2 stopped, no Current/Lock/
running workflow/active SSM/DNS/unclosed maintenance, three empty queues, 49 OK alarms.
Admission, Discord Command and Web reserved concurrency were recorded as UNSET, set to
zero, and existing maximum 30-second invocation timeout was allowed to elapse before
rechecking no in-flight work. Observer/Reconcile continued; no maintenance lease was created.

The following exact ChangeSet ARNs were frozen with candidate templates, unchanged
parameters, artifact hashes and fully paginated raw/evaluated responses **before execution**:

- Control Plane: `arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/monitoring-coverage-cp-e233e9f/e986bbd3-60f3-4f7f-a432-e96cf1019a24`
- Web: `arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/monitoring-coverage-web-e233e9f/7543299d-6c68-41b6-a3a4-cbc366fe2d42`

CP template SHA-256: `9046b96445aafad3ad9ba6ad5790ad1a482f593552788456f9a469a2b19f89bb`.
Web template SHA-256: `dddaf94e1a136745ff7c87aa288e8c2f325c0996c5bb279d4644495ee662306b`.
Both parameter snapshots SHA-256: `471ac6445235139e0565926e16028b3d0aeeb7597f04bf245a9619efe19c0a31`.
File asset manifests and all source-file hashes are pinned by the structured evidence.

**Existing Case D condition 3 was not satisfied:** there is no evidence of an updated
Control Plane dependency. The user separately approved only this exact CP ChangeSet,
based on the equality checks below. This is not a permanent guard relaxation or automatic
permission for future releases. The internal display cause remains unknown; it is **not
classified as dependency propagation**.

| View | Observed changes |
|---|---|
| CP IncludePropertyValues=false | Two DLQ alarm additions only |
| CP IncludePropertyValues=true | Same additions plus BackupStateMachine, ResetWorkflow, StartStateMachine, StopStateMachine and SwitchWorkflow: Modify, Replacement=False, Scope=Properties, Definition-only, RequiresRecreation=Never |
| Web evaluated | Existing AuthErrors/WebErrors AlarmActions; existing Auth/Web Code and asset metadata |

All six State Machines, including Retention, had identical deployed/candidate raw
Properties, actual-ARN-resolved ASL, live parsed ASL and canonical ASL. Role, logging,
tracing, type, name, Tags and referenced identities were checked before and after.
All CP Lambda Code/configuration, IAM, SNS/KMS, queues, event mappings and existing alarm
properties were unchanged. Retention never appeared in the evaluated change list.

Web raw dependency candidates also mentioned IntegrationUri and Lambda Permission
FunctionName through Auth/Web ARN references. They disappeared from the evaluated list;
templates and actual referenced ARNs matched. Actual post-release policies/integrations/
routes/stages and physical IDs were identical, with no such resource update events.
No extra permission, replacement, URL or auth/OAuth update was made.

Web's existing full-source bundle necessarily included eight previously committed RESTORE
operator/host files and changes to reset_worlds.initialized, world_import.expected_level,
maintenance_repository.transition/recovery, plus an added maintenance.check_restore_lease.
Both deployed ZIPs were compared before release. Web/Auth entrypoints, OAuth/auth,
Operation admission, CREATE body, maintenance admission and import validation were unchanged.
This was the originally authorized, reviewed shared-asset update; no monitoring runtime or
new handler was introduced. After release, both ZIPs exactly matched the clean candidate
asset `1b17d29603ac8a13e3099719a92ba7f2de773aaee8b461479e594e5e0d974fcd`.
CP Lambda Code had no update.

Both exact ChangeSets reached EXECUTE_COMPLETE and both stacks UPDATE_COMPLETE.
Actual CP resource events list only the two new alarms; Web events list only Auth/Web
Lambda and AuthErrors/WebErrors. No State Machine resource update event was returned.
Returned Backup/Stop revision IDs were unchanged; four APIs did not return a revision ID.
These observations prove semantic/configuration equality, **not the absence of every
UpdateStateMachine API call**. No hotswap, manual UpdateStateMachine or template editing was used.

## Alarm and notification read-back

49 → **51 alarms**: 48 metric (including the existing suppressor) and three composites.
Both added DLQ alarms use AWS/SQS ApproximateNumberOfMessagesVisible, exact existing
QueueName, Maximum, 300 seconds, >=1, one evaluation period, one datapoint to alarm,
notBreaching, existing monitoring SNS for ALARM only; no OK/INSUFFICIENT_DATA actions.
They are independent and do not reference the retry queue.

Existing AuthErrors8D0EDC3D and WebErrorsC4BB781A retained physical IDs, Lambda dimensions,
AWS/Lambda Errors/Sum/300 seconds/>=1/one period/notBreaching and all other properties;
their previously absent ALARM actions now reference the same existing SNS ARN.
All remaining **47 baseline alarm configurations matched exactly**. All four targets are
always-notify; the three maintenance composites, suppressor and SUPPRESSIBLE set are unchanged.
No continuous/repeated notification behavior was added and maintenance was not started.

The existing topic policy permits CloudWatch sns:Publish and the enabled existing KMS
key permits CloudWatch encryption/decryption/data-key use. One confirmed email subscription,
no pending subscription, filter or redrive was verified. Topic/key/subscription remained
unchanged. Web/Auth Lambda received no SNS/KMS grants. No email address, token or unsubscribe
link is retained in this public evidence.

## Exactly two notification-action tests

| Test ID | Planned ALARM UTC | SNS action success UTC | Natural OK UTC | Final email |
|---|---|---|---|---|
| mcov-dlq-20260925T053541Z | 05:36:03.441 | 05:36:03.541 | 05:36:08.860 | User supplied matching received email |
| mcov-web-20260925T053629Z | 05:36:59.546 | 05:36:59.604 | 05:38:28.777 | User supplied matching received email |

Targets were the new Discord Message DLQ metric alarm and the existing WebErrors metric
alarm. Each was normally OK before the single SetAlarmState(ALARM), with only the approved
SNS action enabled and empty queues/no real Web error datapoints. Actual name, ARN and
unique ID were displayed first. StateReason included WISHICRAFT PLANNED NOTIFICATION TEST,
the ID and explicit non-incident wording. Both histories show Succeeded to the canonical
SNS topic and the natural ALARM→OK transition; configuration before/after is identical.
The DLQ recovered on a real zero datapoint. **Web recovered under its existing
notBreaching missing-data rule, not a measured Lambda Errors zero.**

SNS's 05:36 UTC aggregate was published=2, delivered=2, failed=0. This is corroborating
aggregate evidence, not individual email proof. Individual receipt is separately established
by the user's matching messages. Queue metric samples were zero; Web/Auth Errors had no
datapoints in the observation window. Missing data is not represented as measured zero.
No message injection/ReceiveMessage/delete/purge/redrive, deliberate Lambda error,
PutMetricData, SNS direct Publish, action disabling or SetAlarmState(OK) occurred.
Status Executor DLQ and AuthErrors were configuration-verified only.

These tests do not prove real DLQ transfer→metric detection→notification or real Web
exception behavior. They also do not test a maintenance-active positive failure; the
always-notify claim is based on independent live wiring and unchanged suppression settings.

## Final state and remaining scope

At **2026-09-25T05:39:58Z**, vps-survival remains selected, STOPPED/HEALTHY, EC2 stopped,
no Current Operation/Lock/running workflow/active SSM/DNS/unclosed maintenance, three queues
empty and all 51 alarms normally OK. All three ingress settings returned exactly to UNSET.
Game records, world references, packages and Common/Game policies match the captured baseline.
No pending/executing ChangeSet or release remains. No Minecraft lifecycle, Game/world write,
BACKUP/RESTORE, new SSM, EC2 lifecycle, prod or VPS operation was performed.
World bytes were not modified by this work; full world-byte hashes were not remeasured.

Retry queue backlog, HTTP 4xx/5xx, normal authentication denials and broader notification
observability remain separate backlog in the runbook. Implementation commit and subsequent
documentation closeout commit are separate; this document records the release of e233e9f.
