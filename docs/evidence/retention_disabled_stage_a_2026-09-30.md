# D-115 disabled Stage A release — 2026-09-30

Release preparation; deployment and read-back are not yet completed.

PR #12 reviewed HEAD `e65b0ca3b4024460d8906be4f412928bc39bef73`, synthetic merge
`1d31eaef9577a12fc954c4ca5841fd6d802c95d7`, and actual merge
`181eb22d534e7c22489234f3472fd55f6e71c279` share tree
`aeff217e7a2eb706b197ef2f35d6024d2e8c6b41`. All five PR checks succeeded;
actual-main CI is independently checked before release. Historical review corrections
and their 2,256-test result remain in [the review record](retention_release_review_2026-09-28.md).

This configuration-only release sets canonical dev retention provision=true/enabled=false.
D-114 remains enabled. Deployment uses a clean finalized commit and canonical shared
context, without retention_validation or daily_backup_validation. Other stages are unchanged.

## Execution gates

Before AWS reads, exercise positive-projection and exception-output canaries. Collect a fresh
stopped/healthy, PROTECTED baseline, including current references, snapshots, queues, DNS,
workflow/SSM/maintenance, ingress, alarms, deployed code/IAM and all six State Machines.
If used or unresolved, do not create a window through STOP or manual BACKUP.

Compare immutable candidate assembly to actual deployment, not only main. Permit reviewed
shared-source Code updates for the 13 Control Plane Lambdas, retention Stage A environment
and narrowly scoped read/journal IAM only. No DeleteSnapshot grant, new resource, schedule,
alarm or DRY_RUN ASL change. Web source assets remain undeployed. Review all pages of both
ChangeSet detail forms. Any State Machine display must satisfy every existing Case D condition;
the D-114 Stage B exception does not apply. Pin the same complete ARN before execution.

Restrict normal ingress only as necessary, preserving UNSET versus numeric values, and restore
it after safety checks. Never stop D-114/Observer/Reconcile. Immediately recheck the window and
stack identity before one execution. Read back code, public flags/bindings, authority pin,
all attached/inline IAM and six workflow identities; no broad grant may authorize deletion.

After successful read-back only, the separately authorized single RequestResponse diagnostic
may exercise the existing DELETE_ONE early-disabled gate with unregistered diagnostic IDs.
First prove the same fixed payload returns before _get_runtime locally. No formal operation,
Lock, journal, snapshot target or retry is allowed. Expected NO_DELETE /
DELETE_ONE_NOT_RELEASED / false / [] / 0 is only disabled-gate qualification.

Observe at least one natural D-114 PROTECTED evaluation and compare meaningful retained data.
Do not infer live delete permission, journal transaction or pending recovery success. Stage B,
actual deletion and recovery remain separately approved future work. If a gate fails, record
the partial boundary, remove unused ChangeSet, restore intake safely, and do not improvise a fix.
