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
