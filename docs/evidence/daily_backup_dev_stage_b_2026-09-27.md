# D-114 stage B continuation — separately authorized display differences

This is the 2026-09-27 user-authorized continuation of the preserved
[stage A / partial closeout](daily_backup_dev_stage_a_2026-09-27.md).
Repository baseline: `a77c2c3a56cb8d1f426276b512a2665770ae84c2`.
Stage A (`f17f5c9`) is already deployed; do not redeploy it or repeat PR #2.
The previous stage B ChangeSet was deleted unexecuted and is not reused.

## Exact approval boundary

Target: dev / account 385526546525 / ap-northeast-1, profile wishicraft-dev,
WishicraftControlPlaneStack-dev, system wishicraft-main, existing vps-survival
`game-bfd8409b3f8a4d1b591231c3490d9b646f546294ca11837cad74616ed33eaf21`.
The canonical dev configuration changes only enabled=false to true, keeping provision=true.
No daily_backup_validation override is used to build deployment artifacts.

The user separately authorizes **one new stage B ChangeSet**, despite Case D condition 3
remaining unsatisfied, only after independent verification of all these conditions:

- Source deployable Properties change only at the eight daily resources / nine paths:
  two DAILY_BACKUP_ENABLED 0→1 values, schedule DISABLED→ENABLED, five ActionsEnabled
  false→true values, heartbeat TreatMissingData notBreaching→breaching.
- Both IncludePropertyValues=false/true responses are fully paginated. Missing raw State
  Machine dependencies are recorded honestly, not labelled Case D compliant.
- Additional evaluated modifications are limited to BackupStateMachine, ResetWorkflow,
  StartStateMachine, StopStateMachine and SwitchWorkflow: Modify, Replacement=False,
  Scope=Properties, Target.Name=Definition, RequiresRecreation=Never only.
- For all six State Machines, deployed/candidate raw Properties, resolved ASL, live ASL
  and canonical ASL independently match. DefinitionSubstitutions, Role, logging, tracing,
  type, name, Tags and referenced identities remain unchanged.
- Lambda code/assets and existing workflow dependencies' configuration, IAM, SNS/KMS,
  queues and the existing 51 alarms are unchanged. The two intended daily flag changes
  are explicitly separated. Retention or any other resource/property change stops release.

This is a **D-114 stage-B-specific separate approval**, not a Case D pass, permanent guard
change, waiver for future releases, or reuse of any historical exception. No template editing,
unnecessary Code update, hotswap, direct UpdateStateMachine or signature reverse engineering.
The complete new ARN, committed source, hashes, parameters and comparisons must be fixed before
START; immediately before execution, recheck the same available ChangeSet and unchanged stack.

## Evidence boundary and local validation

`tools/release_evidence.py` is a local collector helper outside Lambda `src/` assets.
It removes Environment/Variables values before serialization/opening a new evidence file,
including recursively JSON-encoded BeforeContext/AfterContext and environment property values.
It retains variable names, only explicit DAILY_BACKUP_ENABLED string 0/1, non-secret Details,
paths, evaluation kinds and identities. Comparisons use original responses only in memory.
No environment-value hash, raw exception payload or debug dump is persisted. Saved responses
are **value-removed evidence**, not unmodified raw API originals. Canonical committed assembly
templates remain distinct from live evidence; their required artifact hashes are not hashes
of live environment maps. Malformed environment contexts fail closed to a removed marker.

Eight offline regression cases cover Lambda configuration, single/double encoded contexts,
property values, exact allowed flags, malformed input, failed serialization, exception output
no-overwrite behavior, and preservation of the unrelated DynamoDB stage environment field. Local test-only roots are fresh; old evidence is not overwritten.
Collector errors report the exception type only. No AWS API is called by this helper or tests.

## Ordered qualification and safety stop

1. Read-only current caller/stage-A code/config/IAM/identity and original stopped world baseline.
2. Commit/CI/normal merge, canonical immutable assembly, one new ChangeSet and all comparisons.
3. Restrict ordinary Discord/Web intake as necessary, retaining formal Admin Admission and
   Observer/Reconcile. Do not begin a maintenance lease for this proof.
4. With daily automation disabled, one formal original-world START → READY/fresh binding and
   durable boundary → one formal STOP/save/cleanup/EC2 stopped/DNS absent/stopped_at proof.
5. Only then execute the same rechecked ChangeSet once. Observe intents from rule enablement,
   even before stack completion; read back all daily settings and all six workflow identities,
   definitions/configurations, recording revisions separately from definition equality.
6. Natural EventBridge → evaluator → internal Admission → BACKUP creates exactly one snapshot.
   Verify completion, all-Game recovery/provenance pair, captured/protected boundary and
   acquisition versus verification time. Observe at least two further natural PROTECTED
   evaluations without additional intent/Operation/snapshot before reopening ordinary intake.

No manual evaluator/BACKUP, extra START, direct CreateSnapshot, new SSM helper, fake metric,
retention deletion, RESTORE/RESET/SWITCH, other Game, VPS or prod action is authorized.
New mismatch/body defect/IAM shortage/unexplained alarm stops this slice: prevent new automatic
acceptance with the dedicated rule and formally restore enabled=false as needed; safely finish
or reconcile already accepted work. Never edit protection/Lock/Operation or force-cancel work.

Success leaves dev enabled, original world stopped/healthy, one new completed snapshot retained,
old data/provenance/journals preserved, intake restored and no executable leftover ChangeSet.
Response-loss IAM, retries/races/TTL, long notification thresholds and RESTORE contents remain
unqualified by this normal-path proof. Runtime execution results are recorded at closeout;
this approval/preparation record alone does not claim those steps have occurred.

## Execution record — 2026-09-27 UTC

Stage A was inherited without redeployment. PR #6 was normally merged from
`fe3a6d37223845bfc538e3ed2f48806dfb2847a6`; CI test merge
`1349510be9dc580d1340a270a8f24539c765b3e7` and actual main merge/deployment commit
`c3a2cbf514f9c8a64ae532e6fc5757c7e699fd93` share tree
`fa7ff60ffce8fecd6d9e8b2152cf80df5ae26195`. All normal/NeoForge/Paper workflows
passed on both PR and actual main. Main runs: 36295811804 / 36295811788 / 36295811837.

The clean detached release worktree generated canonical stage configuration, without validation
inputs. The immutable template SHA256 is
`3e06496b97d694a90018f4000d172778d6c0a5da910ca7aba2162ca1a9c3b8bb`, byte-identical
to the previously reviewed B template. Shared Lambda asset:
`0ffe413b74738bd4a102eb4d72f892d29c5da1941c4d5b191b088f8705816a1e`; Discord asset:
`fa87978b04eb784c5b6b4cbc57c3995dde73af8833e981e023d0175a59218549`.
BootstrapVersion uses `/cdk-bootstrap/hnb659fds/version`, resolved version 32.
The first local assembly contained ignored bytecode from local Python imports and was rejected;
a fresh clean worktree with bytecode writes disabled reproduced the approved assets. It was
never used to create or execute a ChangeSet; no source/Code change was introduced to pass a guard.

Exactly one new ChangeSet was prepared, independently reviewed before START, rechecked after
STOP, and executed once at 05:19:33.985411:

```text
arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/d114-stage-b-approved-c3a2cbf-20260927/5bb7e41d-3f65-470e-a999-7777aab56e76
```

Both paginated evaluation modes were retained as value-removed evidence. The evaluated plan
contained the eight daily resources and the five explicitly authorized Definition displays.
The non-evaluated plan had no State Machine dependency: **Case D condition 3 remains false**.
Its dynamic daily policy/invoke-permission dependencies disappear in the evaluated plan;
raw permission Conditional/Always is not an authorization for replacement. Permission raw
Properties and live source/function identities matched, as did IAM. Independent raw Properties,
resolved/live/canonical ASL and all six workflow configurations/identities matched. The separate
D-114 approval, not Case D compliance, authorized this one ARN. Stack UPDATE_COMPLETE was
05:22:02.295. Post-deployment code/environment-in-memory/IAM checks passed, and all six
workflow definitions, Roles, Tags and identities matched. Returned revision IDs also matched
(two present; four absent in both responses). Definition equality is not a claim that no update
API was called. No State Machine update events appeared in this stack update's event history.

### Formal use and automatic acquisition

Fresh baseline: original vps-survival/Paper package and world, STOPPED/HEALTHY, EC2 stopped,
no lock/current operation/running workflow/active SSM/maintenance/DNS, empty three queues,
13 existing snapshots, 56 alarms OK. No initial backup_protection was present; this was not
interpreted as proof of protection or a tracking defect. Existing provenance, RESTORE journals,
Game/package/world/creation/access/counters and intake configuration were recorded.
Only ordinary Discord and Web intake were temporarily set to reserved concurrency 0;
original concurrency was unset, including the untouched formal Admin Admission.

- START `op-db5654b2-f467-4ea9-86ce-181266088ba9`: admitted 05:09:28.411734,
  succeeded 05:13:43.478. READY, fresh Reconcile/heartbeat, player 0, original Game/package
  and data binding were confirmed. No client join or auxiliary SSM. Normal workflow/Reconcile
  SSM only. Boundary 2, protected boundary 0; initial unknown_since
  `2026-09-27T05:09:27.681321Z` remained, oldest_at was null (unknown history, not zero age).
- STOP `op-ea11b645-d5b9-46e9-a68f-317add715511`: admitted 05:14:50.460875,
  succeeded with normal save/stop/cleanup/EC2 stopped/DNS absent. Durable stopped_at
  `2026-09-27T05:16:31.157536Z`; boundary 2/protected 0 and initial unknown time unchanged.
  No snapshot had been added. Daily flags/rule were still disabled throughout this pair.
- Natural EventBridge → evaluator → dedicated internal Admission → existing BACKUP:
  `op-80573487-0ca4-450d-b57a-e9160a3b17f9`, admitted 05:27:10.076182.
  Snapshot `snap-0212d6f8613b684ac`, acquired `2026-09-27T05:27:20.322000Z`,
  completed and protection verified `2026-09-27T05:31:22.833615Z`.
  Operation/workflow SUCCEEDED; encrypted canonical Data EBS/owner/region/tags and exact
  provenance pair verified. Raw recovery JSON/digest were compared only in memory against
  Operation and provenance; all five registered Games' world/package/creation/access recovery
  information matched. Captured and protected boundary are 2, with the same last_success IDs
  and separate acquisition/verification times. STOP remains independently SUCCEEDED.
- CloudTrail event `bb2b601f-47ab-401e-88d0-adc03107b719` at 05:27:20 records CreateSnapshot
  by the existing BackupTask role for this volume/snapshot. Only non-secret identity/result
  projection is saved, not raw credentials or the original CloudTrail event.

### Received notification classification

The Heartbeat ALARM at **05:20:23.718** is **initialization/deployment-transition missing data**,
not a fabricated positive test or proof of ongoing evaluator failure. Its breaching-missing
configuration completed at 05:19:40.800, before evaluator update completion 05:20:58.486 and
schedule enablement completion 05:21:58.091. At notification time, the disabled schedule could
not yet supply data. Natural first evaluation at 05:27 emitted Heartbeat=1, all four warning/
unknown/operator metrics=0, Lambda Errors/Throttles=0. Missing datapoints before enablement
remain missing; none were injected or rewritten. Five-minute scheduling is not an exact
execution/notification deadline. The user-delivered SNS email confirms this particular missing-
data notification delivery. Alarm history records ALARM→OK at **05:28:23.717 UTC**, without
manual state changes; other notification thresholds/failure paths are not qualified.

### Collector corrections and evidence limitations

The final helper has **11 offline cases**, including actual nested `Details.Target.BeforeValue`/
`AfterValue`, byte preservation of unrelated immutable JSON strings, and host recovery runtime
redaction. The deployment commit's eight cases were followed by three local collector cases;
these tools/tests are outside Lambda assets and do not change the deployed code.

A collector incident must not be erased: baseline versions 1–3 initially saved legacy public
host runtime/Compose recovery metadata. On discovery, those three local `wc-dev-backups.json`
files were correctively value-removed and the incident recorded. This cleanup is an incident
repair, **not** the approved save-first design. No raw copies were retained; immutable Git/
assembly data were not modified. Future collection (baseline v4 onward) strips runtime_env,
its environment hash and Compose content before opening an evidence file. No Lambda secret
values/environment hashes were collected. Full recovery evidence is validated in memory;
saved value-removed recovery cannot itself be used to recompute the original recovery digest.

Local comparison-only failures (stage-key over-redaction, JSON whitespace comparison and the
observation script's stale Python import path) were corrected without repeating AWS mutations.
The full final local suite passed **1972 tests**; the collector's 11 cases cover normal and
exception output/persistence. Lint/format/type and final closeout CI are recorded with the PR.
Local run evidence root: `/private/tmp/wishicraft-d114-stageb-20260927.98Jgk6`.
The structured companion records durable public results; temporary read-only records are
value-removed observations, not claims of retaining unmodified raw API originals.

### Final qualification and operating state

Natural post-success PROTECTED evaluations: `2026-09-27T05:32:06.859000+00:00`, `2026-09-27T05:37:07.113000+00:00`.
Both have unprotected/stopped_warning/interval_warning=false; the same intent, Operation,
last_success and protected boundary remain. Exactly one new BACKUP Operation and snapshot;
13 existing snapshots plus the new one = 14. The original 24 provenance rows are unchanged,
with exactly the new snapshot/Operation pair added. All five Games and RESTORE journals match.

At final qualification, original world selected, STOPPED/HEALTHY, EC2 stopped, no Current
Operation/Lock/running workflow/active SSM/session/maintenance/DNS, all three queues empty,
56 alarms OK. Existing 51 alarm configurations and maintenance suppression are unchanged;
new five actions target existing SNS and are not maintenance-suppressed. All five real daily
metrics are present: Heartbeat=1, four others=0. Normal Discord/Web reserved concurrency
was restored to its recorded unset configuration at `2026-09-27 05:39:26.263787+00:00`; Admin Admission
was unchanged. Dev remains provision=true/enabled=true. No available ChangeSet, manual
rule drift or other release-related read-back discrepancy remains. Formal stack drift
detection was not invoked. Retention deletion remains disabled/dry-run; no snapshot was
deleted. After intake restoration, future authorized normal usage may create further daily
backups; the one-snapshot limit describes this qualification, not all future operation.

[Structured evidence](daily_backup_dev_stage_b_2026-09-27.json) records exact IDs, timings,
comparisons, actual metrics and notification history. No response-loss/retry/race/TTL or
long-threshold test, RESTORE/mount/full-world-hash validation, unattended STOP wait,
retention deletion/collector-completeness qualification or cost measurement was performed.
Cloud snapshots protect only their captured boundary; prolonged running can postpone the
next point, and root-level arbitrary edits are not fully auto-detectable. Existing manual
management BACKUP/handoff obligations remain. The 14-day OR newest-seven policy is still
an independent dry-run; 14 days has no count cap and storage costs depend on changed blocks.
