# Daily shared BACKUP: repository handoff and separate dev release

Canonical contracts: [D-114](../reviews/daily_shared_backup.md),
[independent D-115 retention dry-run](../reviews/daily_backup_retention.md).
Baseline: `29c3231aa3052d26cce6a153a8c02d04fdc02ebb`, fetched origin/main matched on 2026-09-26.
Implementation is on `feat/daily-shared-backup` in a dedicated clean worktree. Original local
Terralith documentation/evidence changes are not incorporated, discarded or committed here.
No AWS deployment, ChangeSet, metric injection, schedule enablement, BACKUP, snapshot mutation,
IAM application, SSM or real host/Game/world operation is authorized by this preparation.

## Read-only operator status

```sh
tools/dev-env run -- uv run python -m wishicraft.daily_backup_status --stage dev --profile wishicraft-dev
```

This checks caller Account ID against stage YAML, then reads state/Lock/actual EC2. It prints
captured and protected boundaries, oldest/unknown/stopped times, last successful snapshot and
Operation, acquisition versus verification time, current intent/status, reason and intervention
need. Local stage supplement enablement is labelled as local configuration; compare deployed configuration
at release. It does not run evaluator, initialize tracking, publish metrics, or call Admission.
Missing initial authority is explicitly `initialized=false`, historical duration unknown.

On failed/unknown BACKUP use existing [BACKUP safety recovery](backup_safety_isolated_restore.md),
including exact Operation, workflow execution, create reservation, snapshot inventory and both
provenance records. Do not delete locks, create another request, or assume a missing Operation
means no snapshot. Operator reconciliation of disputed authority requires an explicit reviewed
procedure and approval. Ordinary START/STOP remain governed by existing Lock/maintenance safety;
intent alone does not close gameplay. A successful current manual BACKUP shares this authority.

## First automatic-acquisition dev release proposal — separately approve

1. Confirm finalized commit/CI, exact dev caller/account/region and current stack contexts,
   idle STOPPED/HEALTHY actual host, no unfinished Operation/Lock/maintenance/SSM/execution.
   Capture current state, Games, snapshot inventory/provenance and current SNS/alarm configuration.
2. Review the code-only tracking change and optional resources/IAM. Provision with enabled=false;
   inspect template/ChangeSet only under that future explicit approval. Preserve all physical IDs,
   existing alarms and maintenance suppression. Verify env size, function policies and disabled rule.
3. Enable only the dev five-minute evaluator and its alarm actions under the same bounded approval.
   Confirm initial unknown/baseline-required status and real healthy signal without fake metrics.
4. Prefer one necessary formal START/use/normal STOP, followed by **one** automatic BACKUP through
   the existing workflow. Game choice is a real operational need, never based on RESET capability.
   Capture STOP SUCCEEDED independently, one intent/Operation/snapshot, actual completed snapshot,
   source/owner/shared recovery/provenance pair, captured/protected boundary and retained Lock until
   normal completion. Use manual baseline instead if that is safer for the actual initial state;
   do not silently consume an unapproved extra snapshot in the proof.
5. Observe at least two further evaluator periods without new use and confirm no additional
   Operation/snapshot. Confirm existing STOP terminal result unchanged and no Current/Lock left.
6. Read back schedule, IAM, alarms, SNS and final stopped state; preserve evidence and snapshot.
   If normal use or acquisition cannot be demonstrated within the approved scope, record the
   limitation and stop at that external boundary. Do not introduce destructive failure injection.

No synthetic metrics in production to simulate 30 minutes/24 hours. Fixed-clock tests are local;
real long-threshold notifications remain unqualified until naturally observed or separately
approved safe evidence is available. Planned disablement sets enabled=false, retains provisioned
resources/intent/history and lets any accepted workflow finish. Investigate live unknown workflows
under the existing recovery contract, never cancel merely to close this release.

## Independent retention deletion proposal — not part of the above

First capture a complete read-only inventory, both provenance records, snapshot lock/Recycle Bin
state, explicit historical holds, and unfinished IMPORT/RESTORE source/protection references.
Review the machine-readable protection authority/collector and timestamp boundary behavior.
Produce an exact candidate comparison under D-097 and D-115 with every exclusion/hold explained.
Any incomplete hold or reference inventory stays NO_DELETE. No real inventory has been certified
by this preparation. Only after review request a **separate** limited deletion approval, including
exact snapshot IDs, restore evidence, maximum one deletion, immediate ownership/reference checks,
outcome reconciliation and rollback/recovery limitations. No DeleteSnapshot adapter/permission
is introduced here. Acquisition release does not approve retention deletion.

## Evidence and limitations

Local tests and synth results are recorded at closeout. Docker is unavailable locally; normal,
NeoForge and Paper CI are the integration authority. First local full run encountered sandbox
network errors during hash-locked Lambda bundling; failed logs are retained, and subsequent
validation uses the prepared cache in a fresh output root. AWS inventory and live IAM/schedules/
notifications/long-threshold behavior have not been verified by this task.

Snapshots protect only Data EBS at acquisition, not arbitrary changes afterwards, root EBS,
Control Plane configuration or every RESET generation. Recovery JSON authenticates recovery
metadata, not a whole-world hash. SAVE/normal STOP/old-world preservation remain mandatory.
Continuous play and short stop intervals can postpone external protection. Direct operator edits
outside formal maintenance are not fully detected. Thirty minutes and 24 hours are warning
thresholds, not maximum data-loss bounds. Storage costs have not been measured for this policy.


## Repository validation closeout (2026-09-26)

Final local full suite: **1925 passed**. Ruff lint/format and mypy over **266 source files** passed.
Synth succeeded for Phase 1, Target, base/shared/CREATE/Whitelist/package Control Plane, base/current
independent Web (nine configurations), plus the fully enabled shared/package daily configuration.
Default-vs-baseline template comparison: zero resource additions/removals, only eleven shared
Lambda code assets and the three intended environments. IAM, State Machine definitions, existing
alarms and all unrelated properties are unchanged. Enabled configuration adds exactly fifteen
resources (two functions/roles/policies/log groups, one rule/invoke permission, five alarms) with
zero modifications/removals of existing resource properties. CLI-versus-direct-App diagnostic
Metadata is excluded explicitly; all deployable properties are compared without normalization.
All synthesized Lambda environments remain under 4096 bytes.
[Machine-readable comparison and limits](../evidence/daily_backup_repository_2026-09-26.json).

Implementation commits: `279348e` protection boundaries, `43fb774` evaluator/internal Admission/
monitoring, `a9f4d0d` separate retention dry-run. This documentation closeout commit follows them;
its exact HEAD and normal/NeoForge/Paper CI URLs are supplied in the final handoff/PR checks.
The earlier failed full run and the stage-byte migration regression were diagnosed; the fixed
stage supplement preserves historical migration checks. Subsequent full-suite success above is
from a new validation root. No skip/fallback is counted as implementation success.


Final IAM review additionally splits internal Admission DynamoDB actions by their actual tables
and limits evaluator UpdateItem to `system_id` / `backup_protection` attributes on the canonical
system key. Six focused infrastructure/synth cases, targeted mypy, full lint/format passed after
that restriction. Resource counts and unchanged existing-resource contracts remain the same;
the exact final HEAD is covered by the subsequent PR CI, not inferred from the earlier local run.
