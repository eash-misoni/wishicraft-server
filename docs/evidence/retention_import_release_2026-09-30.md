# D-115 import correction: dev deployment and DRY_RUN completed

**import修正をdevへ配布し、削除無効gateと正式DRY_RUNを確認した。**

This continues the [disabled Stage A PARTIAL](retention_disabled_stage_a_2026-09-30.md),
without rewriting its failed Invoke or alarm history. The subsequent user instruction authorized
PR #15 merge, Code release, disabled-gate qualification, formal RETENTION DRY_RUN, and directly
related artifact-tooling correction/normal merge. No Stage B, deletion or pending recovery.
[Machine-readable evidence](retention_import_release_2026-09-30.json). Times below are UTC.

## Commits and qualification

| Purpose | Commit | Tree |
|---|---|---|
| Reviewed PR #15 | a328572e2dba159eee0eda62f65672262973cbce | dce2416c0b31f1a1c4e95fa899e48502f9f894bb |
| PR #15 actual merge | e7af67980d2243c080c94ded5aec1af4a0eb8cb5 | same |
| Artifact preservation PR #16 | 4373912d831bb7a1bacbaa5deaf8fa3abcd0a7f1 | 79846130db10959d4c88db4159888b20641ee73e |
| PR #16 actual merge / deployed | 601ba1f98f77f1782f5042477da05acc14064e3d | same |

Both PR synthetic merge trees match their respective HEAD/actual merge trees. PR #15 postmerge
[CI 36722884399](https://github.com/eash-misoni/wishicraft-server/actions/runs/36722884399),
[NeoForge 36722884512](https://github.com/eash-misoni/wishicraft-server/actions/runs/36722884512),
[Paper 36722884307](https://github.com/eash-misoni/wishicraft-server/actions/runs/36722884307) passed.
Deployed commit [CI 36725278044](https://github.com/eash-misoni/wishicraft-server/actions/runs/36725278044),
[NeoForge 36725278094](https://github.com/eash-misoni/wishicraft-server/actions/runs/36725278094),
[Paper 36725278444](https://github.com/eash-misoni/wishicraft-server/actions/runs/36725278444) also passed
before execution. Full 2,263 source tests, lint/format/strict types and existing synth matrix remain
required; 19 isolated Linux artifact scenarios passed separately. Local projection tests: 11 passed.

The one local tooling correction was [PR #16](https://github.com/eash-misoni/wishicraft-server/pull/16):
preserve the exact canonical assembly after artifact qualification. Local/CI Discord bundles differed
only in `bin/cffi-gen-src`'s installer-generated Python shebang and its `cffi-2.1.1.dist-info/RECORD`.
No application or dependency version changed. Using the tested CI assembly avoids substituting the
local bundle. PR #16 contains CI archival and documentation only, not another runtime fix.
Its initially rejected automatic merge review was resolved by showing the explicit authorization
for directly related artifact-tooling correction/normal merge; no protection bypass was used.

The deployed assembly was generated in the actual merge's clean CI checkout, from canonical
retention true/false and daily BACKUP true/true, without validation overrides. It was downloaded,
checksum-verified, compared with the clean local worktree and deployed without template editing.

- Archive SHA-256: `3d582cff4feb0477828c6aa1d9dcc24223dae268ba002ab87b9b9158e28faf4c`.
- Template SHA-256: `fde7d5bb2b8d23470db3f1d824a204ffffce363cd326ddee2d9c34062ce5e308`.
- Shared asset: `2b34ff7c33e8d6267edd2418073b0cfa8d13b000de4c99d6d45866e6b8a6a902`.
- Discord asset: `546b16d99bffb11cb7cba79050cd8c6086e716b6ab50c8d46ebd6e8f4ae0f8a0`.

The Linux Python 3.12.14 / boto3+botocore 1.43.91 qualification runtime and image digests are in JSON.
This is not a claim that the managed Lambda runtime/SDK is byte-identical to that container.

## Code release and read-back

Fresh baseline at 13:39:40–13:39:57 confirmed canonical caller/account/region, STOPPED/HEALTHY,
EC2 stopped, PROTECTED 2/2, no Lock/current/running work, 14 snapshots and 56 OK alarms.
No STOP, protective BACKUP, maintenance or host inspection was needed.

ChangeSet (one preparation, one execution):

`arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/d115-import-code-20260930/aeac7af3-1fd9-4f79-b4bc-e77d099a67bb`

Both IncludePropertyValues modes reached their last page. Real property changes: 13 existing
Control Plane Lambda Code properties and corresponding metadata only. The five allowlisted
workflow Definition update displays passed **all Case D conditions, including condition 3**:
non-evaluated Details named updated Reconcile/Start/Stop/Backup Lambda ARN dependencies.
All six raw Properties, resolved/live/canonical ASLs, roles, configuration, tags and identities
matched. No earlier D-114 exception was reused. No IAM/flag/alarm/schedule/resource change.

Normal ingress concurrency was saved as UNSET and temporarily restricted at 14:09:03.
The same reviewed ChangeSet was executed after a second safe-window/template check at 14:09:24;
UPDATE_COMPLETE at 14:10:31.250. All 13 CodeSha256 values match published ZIPs whose file bytes
match the qualified assembly. Handler/role/timeout and all environment values matched in memory;
only public bindings and names were saved. All six workflow identities/configuration stayed equal;
stack events contained no State Machine update event. Revision observations remain separate.
RETENTION inline and attached policy documents remained unchanged, including examination of broad
Allow patterns/NotAction: no DeleteSnapshot grant. Retention remains provisioned=1, delete-enabled=0.
Web was not deployed; its two Lambdas retain their prior CodeSha256 values.

## Disabled gate and formal DRY_RUN

The fixed unregistered diagnostic operation/lease IDs are in JSON. No snapshot/state/valid lease
was supplied. Local early-gate validation preceded the real Code/Revision/role/flag read-back.
One RequestResponse Invoke at 14:11:49 returned FunctionError absent and exactly:

```json
{"status":"NO_DELETE","reason":"DELETE_ONE_NOT_RELEASED","deletion_authorized":false,"planned_delete_ids":[],"delete_action_count":0}
```

Request ID: `60f06afd-9381-4cab-8820-1015b9dd98ea`.
No diagnostic Operation, Lock, deletion journal or snapshot side effect was observed.
No diagnostic retry or second Code deployment was necessary.

Normal Admission was restored to its original UNSET for the approved Admin entry. The existing
`wishicraft.retention_operator.admit_retention` sent fixed key
`retention:d115-import-qualified-20260930`; it did not bypass Admission or fabricate a lease.

- Operation: `op-a98f0ab5-efe4-472d-b0d8-fe7cd33a05f6`, SUCCEEDED.
- Execution: `arn:aws:states:ap-northeast-1:385526546525:execution:wc-dev-retention:op-a98f0ab5-efe4-472d-b0d8-fe7cd33a05f6`, SUCCEEDED.
- Accepted 14:12:39.558212; completed 14:12:50.146525; workflow terminal 14:12:51.560.
- `RETENTION_DRY_RUN`, reason `planned`; inventory 14, KEEP 7, candidate 1, excluded 6,
  anomaly 0, deletion-plan reference count 1, **delete_action_count 0**; Recycle Bin rules 0.

This is the **existing newest-seven DRY_RUN** contract, not the future 14-day OR seven DELETE_ONE
execution/hold authority. A candidate or historical deletion-plan count is not permission to delete.
The handler's unchanged strict inventory/provenance/lock/rule logic ran without import failure;
no validator or retention rule was relaxed. Normal completion released Lock/current operation.

## D-114, final state and limits

Natural evaluation Request ID `74683ae1-bcd0-4f1f-82c8-af63955c4834` completed after deployment:
PROTECTED, heartbeat 1, stopped/interval/operator/unknown metrics 0. No evaluator was manually
invoked. D-114 and Observer/Reconcile remained enabled throughout.

All normal ingress returned to UNSET by 14:14:05. Final capture/verification at 14:15 retained
STOPPED/HEALTHY, stopped EC2, the same selected Game, PROTECTED 2/2 and last success, 14 snapshots,
no deletion records, no active Lock/workflow/SSM/DNS/maintenance, empty queues, and 56 OK alarms.
Alarm configuration/suppression and schedules matched baseline; no alarm state transition occurred
since this execution. The earlier actual import-error alarm remains historical, not reclassified.
No available/unexecuted ChangeSet remained. Targeted configuration and concurrency were checked;
a new full-stack drift detection API was not run.

Deployment/disabled-diagnostic in-memory comparisons preserved Games, Backups, snapshots and RESTORE
journals. Final projections and original surviving Operations were unchanged except the one approved
formal RETENTION record. No world hashing, RESTORE content test or past FAILED reinvestigation.

AWS writes **did occur**: asset publication, ChangeSet/Code application, temporary concurrency and
restoration, and the approved formal Operation/Lock/state lifecycle. Snapshot mutations, hold
releases, new BACKUPs, deletion journals, Stage B and pending recovery: **zero**.
No retention deletion operation, destructive IAM evaluation, response-loss retry, live recovery,
long-duration alert or broad concurrency qualification is claimed. Those remain separately approved.

This closeout is docs-only; the deployed commit remains 601ba1f. Final docs main/CI and learning Wiki
synchronization are recorded in the PR/handoff without another closeout chain. Primary checkout
unrelated edits are preserved; release worktrees are separate.
