# D-115 disabled Stage A — deployed, diagnostic failed (2026-09-30)

**PARTIAL.** The reviewed Control Plane code, disabled Stage A configuration and scoped IAM
were deployed and read back successfully. The one authorized diagnostic returned FunctionError
instead of NO_DELETE. No fix, redeployment, second Invoke, formal RETENTION or rollback was
performed. This is **not** completed disabled-gate qualification, Stage B, deletion operation
start, live pending recovery or live DeleteSnapshot permission qualification.

[Machine-readable evidence](retention_disabled_stage_a_2026-09-30.json) separates the successful
release/read-back from the failed diagnostic. Previous repository-only and failed records remain
historical; this does not rewrite their observations.

## Commits, trees and validation

| Checkpoint | Commit | Tree |
| --- | --- | --- |
| Reviewed PR #12 HEAD | e65b0ca3b4024460d8906be4f412928bc39bef73 | aeff217e7a2eb706b197ef2f35d6024d2e8c6b41 |
| PR #12 synthetic merge | 1d31eaef9577a12fc954c4ca5841fd6d802c95d7 | same |
| PR #12 actual merge | 181eb22d534e7c22489234f3472fd55f6e71c279 | same |
| Stage A PR #13 HEAD | 0bf9300252f1082d63e6a652157a8a95c33c6881 | e88e72da8cbe333a8424dcd8f76ad79673c24d6b |
| PR #13 synthetic merge | 9332408720a3fcb3a630fe3bd90eb2f0e818b9bb | same |
| **Actual deployed merge** | **51fa628179c43c2ca1559077d3b196e9797822e9** | same |

Both PRs were normally merged after all five checks succeeded. Actual PR #12 merge CI:
36703133696 / 36703133816 / 36703133778; actual Stage A merge CI:
36704872556 / 36704872471 / 36704872464 (normal / NeoForge / Paper), all successful before
execution. The Stage A PR checks used 36703591606 / 36703591729 / 36703591547.

Actual canonical true/false tree: 2,256 local tests, lint, format, strict type (293 files), and
all 12 CI CLI synth configurations passed, including canonical shared, legacy, Web, Target,
future A/B and daily BACKUP validation. Initial local offline bundling lacked a populated cache:
38 failed / 47 errors / 2,171 passed; a separate first-failure run identified missing cffi cache.
This environment failure was preserved, not counted as success. Reusing the existing verified
cache produced the complete passing run without source/test changes. Privacy regression: 11
passed, plus local projection/exception canaries before AWS collection.

## Immutable artifact and ChangeSet

Canonical assembly came from a clean worktree at the actual release commit. No validation
context was used. Template SHA-256:
`458a778b5bc0b54e61defb2e377b8e4f6bcb7e5f9378f56dc7c9afa43c8c2c16`.
Shared source asset: `f3eba1d0d9971f79928f14a10e7a8be37b54a736ab893766e31b2a7eefdde90c`;
Discord bundled asset: `803300173a71d6bc2a141314eb421835ae857a9f54e902024178b0f6aac6306b`.
Asset/assembly identities, published ZIP checks and parameters are in the JSON.

Exact ChangeSet, created and executed once:

`arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/d115-disabled-stage-a-20260930/6f31b20c-c8eb-4c0b-9666-06117d7e185a`

Both IncludePropertyValues forms were fully read. Actual Properties differences from deployed
state: Code for 13 existing Control Plane Lambdas; three RETENTION environment additions;
one reviewed retention role inline policy update. GAMES_TABLE already existed and remained
identical (the initial local comparator expected four additions and was corrected, without
changing the candidate). No added/deleted/replaced resource, alarm/schedule/table, D-114,
SNS/KMS, Game/runtime or Web deployment change.

Five additional Definition-only displays were Backup, Reset, Start, Stop and Switch, all Modify /
Replacement=False / Scope=Properties / RequiresRecreation=Never. **Case D condition 3 passed:**
non-evaluated Details identify updated Reconcile/StartTask/StopTask/BackupTask `.Arn` references.
All six raw Properties, resolved/canonical/live ASL, roles and referenced identities matched.
RETENTION was not a property-evaluated update. The D-114 exception was not reused.

Normal Discord/Web/Admission ingress was saved as UNSET, temporarily set to zero, and the
stopped PROTECTED window rechecked before execution at 11:02:38 UTC. CloudFormation reached
UPDATE_COMPLETE at 11:04:05.675 UTC. D-114, Observer and Reconcile were never stopped.

## Read-back and diagnostic failure

All 13 CodeSha256 values matched the published ZIP bytes and immutable assembly. Handler,
role, timeout, all environment values (compared only in memory) and selected public bindings
matched. RETENTION_PROVISIONED=1, RETENTION_DELETE_ENABLED=0, canonical tables/volume and
RETENTION_WORKFLOW_NAME=wc-dev-retention. Historical authority pin and both reviewed numeric
normalization sources matched the deployed ZIP. All three original FAILED records remained
and matched the release-owned authority, without repeating historical CloudTrail investigation.

Actual inline and attached policies were inspected, including wildcard/NotAction possibilities:
no DeleteSnapshot Allow. Journal grants retain the DELETION#/RETENTION# leading-key restriction.
All six workflow ASL/config/role/tag identities matched; RETENTION remains DRY_RUN. Definition
identity does not imply that AWS made no update API calls. Web's two Lambdas remain on their
previous deployed Code; shared repository source changes are deliberately not deployed there.

The fixed diagnostic payload contained only schema_version=1, action=run, execution_mode=DELETE_ONE,
operation_id `op-diagnostic-526cca31-87f1-46be-b717-59a40298ee0b`, and lease_id
`lease-diagnostic-c57244c0-442b-4487-bbca-4c944cbe595f`. No registration, real lease, state or
snapshot ID. Local source returned expected NO_DELETE before _get_runtime. After live code/role/
flag recheck, one synchronous Invoke with SDK total_max_attempts=1 returned HTTP 200 but
**FunctionError**, Request ID `bbb57cd9-c4c2-4e46-b9a4-05047e98db94`, at 11:05:46 UTC.
HTTP transport success is not handler success. There was no retry.

The same existing log event confirms ModuleNotFoundError for `yaml`. The deployed handler line
93 imports retention_runtime, which imports maintenance_operator, which imports config/PyYAML,
**before** environment_release can return the disabled-gate response. _get_runtime and business
API/journal work were not reached. Raw exception messages, full logs and recovery/environment
values were not stored. The successful local test had developer dependencies available and did
not prove the deployed ZIP's import closure. Source inspection also shows DRY_RUN traverses this
import; it may fail for the same reason. No formal DRY_RUN was invoked to test that inference.

The existing `wc-dev-retentiontaskfunctionerrorsalarm` entered ALARM at 11:06:37.808 UTC;
SNS action succeeded at 11:06:37.900 UTC. Real AWS/Lambda Errors=1 and Invocations=1 correspond
to the diagnostic. Classification: **actual diagnostic failure**, not maintenance, migration or
an unexplained notification. The user forwarded the matching email during closeout, confirming
receipt; email address and subscription link were not saved. Natural alarm recovery, if recorded
below, does not repair the missing dependency. No metric injection or alarm/threshold change.

## Preservation and remaining boundary

Before/after deployment, full Game records (including package/creation/access), Backups records,
RESTORE journals and snapshot metadata matched in memory. After the diagnostic, the positive
projections still matched: 14 snapshots, 13 valid immutable provenance pairs, three RESTORE
journals, no new Operation/Lock/deletion record. Existing holds and five legacy exclusions remain.
The original world of vps-survival stayed selected; STOPPED/HEALTHY and actual EC2 stopped.

D-114 naturally completed PROTECTED after deployment at 11:07:09 UTC, Request ID
`1c51b227-1272-4d5d-8c89-05499b8e2739`. Real metrics: Heartbeat=1; StoppedOverdue,
IntervalOverdue, NeedsOperator and ObservationUnknown=0. Boundary/protected_boundary remains
2/2 with last_success snap-0212d6f8613b684ac. No manual evaluator invocation or new BACKUP.

The live release was not rolled back merely to hide failed qualification. Deletion remains
disabled, without DeleteSnapshot permission. No emergency retention concurrency seal was
required because neither unexpected enablement nor destructive permission was found.
No actual deletion, snapshot creation, hold release, formal business operation, pending recovery,
host/EC2/SSM operation, Stage B or production action occurred. The one diagnostic did generate
normal Lambda logs/metrics and an actual failure alarm. Asset publication, ChangeSet execution,
scoped IAM/config/code deployment and temporary ingress changes **were AWS mutations**.

Next separately reviewed slice: correct the RETENTION runtime import/dependency boundary and
validate the actual Lambda artifact with developer-only dependencies absent. Do not repeat the
old historical FAILED investigation. A new code release and another live qualification require
a separate approval; Stage B, DeleteSnapshot, real pending recovery and deletion operation remain
unqualified. No fix or new retention authority is included in this docs-only closeout.

## Final state and closeout

Final read-only verification completed at 11:25:01 UTC. STOPPED/HEALTHY, actual EC2 stopped,
original vps-survival world and package/access records retained; no current operation, Lock,
running workflow, active SSM, DNS or open maintenance; all three queues empty. Snapshot/provenance/
journal/hold identities and protection boundary are unchanged. All 56 alarm configurations,
actions, maintenance suppression and four schedule settings match baseline. D-114 stays enabled.

The diagnostic Errors alarm naturally changed ALARM→OK at 11:21:37.808 UTC. No new invocation,
metric injection, threshold/action change or code fix caused this recovery. Its 11:01-start
300-second Errors=1 aggregate matches the 11:05 one-minute Errors=1 diagnostic sample, not a
second error. The dependency bug is still present.

The first local restoration guard had stopped while that actual alarm was active. The final
restoration rechecked all other safety conditions and was prepared to report only that exact
known diagnostic alarm; by the actual mutation all 56 alarms were already OK. At 11:23:06 UTC
Discord/Web/normal Admission were restored to their recorded UNSET values. The local helper's
missing constant import was corrected before any restoration API call; no restoration mutation
was repeated. The deployment-time Case D gate was not relaxed.

The exact ChangeSet is EXECUTE_COMPLETE; no AVAILABLE/in-progress ChangeSet remains. Managed
code/config/IAM/workflows and the deployed canonical template match, and intentional concurrency
drift is restored. A full CloudFormation drift-detection job was not run; no unverified global
no-drift claim is made. The docs-only closeout is not deployed and its actual final main/CI/Wiki
identity is recorded on the closeout PR and handoff. The original checkout's unrelated changes
remain untouched; release and documentation work used separate worktrees.

## Subsequent repository correction candidate

[Artifact import-boundary correction](retention_artifact_imports_2026-09-30.md) prepares a
separately reviewed source fix and isolated artifact qualification. It does not change this
PARTIAL result, repair the deployed code, or authorize another Invoke/deployment/Stage B.
