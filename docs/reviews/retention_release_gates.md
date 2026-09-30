# D-115 retention live-release preparation

> 2026-09-30 deployment checkpoint: PR #12 and canonical dev Stage A are merged;
> provision=true/enabled=false is deployed with no DeleteSnapshot grant. Code/config/IAM
> read-back passed, but the single disabled-gate diagnostic failed on a missing `yaml`
> import before _get_runtime. **PARTIAL, not release qualification complete.** No fix or
> retry was performed. [Execution and remaining boundary](../evidence/retention_disabled_stage_a_2026-09-30.md).
> The false/false and undeployed statements below describe the original preparation checkpoint.

This continues the [disabled execution core](retention_execution.md) after actual merge
`29cff405d83efb25ef67fb98de8b03e7ee9568f6`. Repository preparation only: no deployment,
ChangeSet, DeleteSnapshot (including DryRun), snapshot/hold/journal change or D-114 pause.
The [bounded preflight](../evidence/retention_release_preflight_dev_2026-09-28.json) is evidence,
not deletion authority. Current dev remains provision=false/enabled=false and NO_DELETE.

## Authority selected from actual preflight

All three adopted FAILED records remain. The release bundle therefore includes a narrow
`retention_historical_authority.json`, independently pinned by a SHA-256 revision in
`retention_authority.py`. This is proposed **runtime consumption of previously adopted facts**,
reviewed with this PR; the historical PROPOSED evidence files are not changed or loaded as
operator-provided authority. The bundle records the adoption commit and digests of the terminal,
exact CloudTrail and reconciliation evidence. Tests verify these source identities.

Only exact account/region/system/stage/volume, operation/type, timestamps, FAILED status,
terminal error structure, Game, execution ARN/name and expected creation reservation can match.
The remaining reservation's original recovery digest must still validate in memory. Unexpected
result, snapshot reference, new snapshot tagged with the operation, provenance or a current
reference to that operation blocks it again. New FAILED operations always block. Inaccessible,
modified or unknown authority blocks. Missing Operations need no exception. The bound reader
verifies the table/caller/region; old records do not themselves contain account/system fields.

Raw collector FAILED findings remain. Execution inventory separately records FAILED and whether
this exact reconciliation matched; its predicate includes the release authority revision. This
is not a general resolved flag, automatic failure suppression or inventory completeness waiver.
No failure is converted to SUCCEEDED, and the retained creation reservation is not removed.

No static hold registry is needed for the current inventory:

| Asset | Binding that prevents ordinary candidacy |
| --- | --- |
| Migration anchor | strict migration classifier exclusion |
| Paper source/protection | non-TTL RESTORE journal, including ROLLED_BACK |
| Vanilla source/protection | non-TTL journal, independent of old PLANNED |
| Old PLANNED source/protection | live PLANNED journal remains a reference |
| Current success/intent | current backup_protection and matching provenance |
| Legacy five | strict legacy exclusion, outside the normal seven |

The hold revision names this live-reference/classifier contract; fresh reference revision includes
journal plans/revisions, Game/import references and current protection. Static historical prose
is not a runtime registry. Removing a journal or releasing a historical hold is not authorized.
A future change to reference lifecycle requires its own review before it can replace these holds.

## Provision versus enablement

Canonical input is `config/retention-execution-<stage>.json`; missing files default to false/false.
Non-booleans, unknown fields/schema and false/true are rejected. The CLI reports source and both
flags without printing environment values. Validation context requires explicit synth and is
rejected for deploy or non-Control-Plane targets. CI retains both canonical and explicit future
A/B synths. The new canonical dev file is false/false.

| Flags | Runtime and permissions |
| --- | --- |
| false/false | Existing DRY_RUN handler; event DELETE_ONE returns NO_DELETE before constructing clients; no new env/IAM/ASL properties |
| true/false | Future Stage A: read/journal/recovery prerequisites, enabled=0; no DeleteSnapshot grant; DELETE_ONE rejected |
| true/true | Future Stage B: server-owned formal workflow payload explicitly selects DELETE_ONE; task also requires enabled=1; least-privilege delete grant |

DRY_RUN continues to mean DRY_RUN even if enabled. Stage B adds only the explicit execution_mode
constant to the existing RETENTION task payload; it does not add a workflow, task, schedule,
retry, resource, Game operation or D-114 change. Existing state names remain for compatibility.
No arbitrary operator event supplies flags, holds, completeness or historical authority.

The future runtime binds canonical tables/volume, exact admitted ADMIN/CLI RETENTION and lease,
original execution identity and current Lambda ARN/revision/timeout. It retains healthy/fresh
Reconcile and source-volume checks. Unknown inventory blocks before reservation. Zero candidates
is a successful no-op. The core uses the existing global lock, durable pending bit and one-target
journal. Successful request still needs two later active-absence observations and Recycle Bin
reads. Incomplete result returns MANUAL_REVIEW_REQUIRED and preserves pending; existing failure
cleanup cannot remove that fence. Recovery is explicit, never a scheduled retry.

## Real adapter, one SDK send

`retention_delete_adapter.py` constructs a dedicated standard-retry client with
`total_max_attempts=1`, connect timeout 5s and read timeout 10s. Configured endpoint overrides are
ignored. The adapter rejects a client with other retry/region settings. With local botocore
1.43.91, mocked transport timeout and HTTP 500 tests exercise the **actual SDK send loop** and
observe exactly one send, not merely a mocked delete method call.

2xx SDK transport response is EXPLICIT_SUCCESS (EC2's Boto shape has no Return field). Explicit
service AccessDenied/Unauthorized is denial. Transport/decode loss and all other service errors,
including InvalidSnapshot.NotFound **after** DeleteSnapshot, are OUTCOME_UNKNOWN. It never emits
NOT_FOUND_BEFORE_REQUEST; that belongs only to pre-request inventory. No exception body, request
payload, environment, credential or player data is returned, printed or journaled.

## Future IAM, not current grants

AWS's EC2 Service Authorization Reference explicitly supports snapshot resources and resource-tag,
Owner, ParentVolume, Region and SnapshotID keys for DeleteSnapshot. Snapshot ARN is accountless:
`arn:aws:ec2:REGION::snapshot/SNAPSHOT`. Owner is an account ID; ParentVolume is a **volume ARN**.
The proposed shared-v2 policy uses StringEquals for Owner/Region and Project/Stage/category=backup,
schema=2/scope=shared-volume/protected=false/source-volume tags, plus ArnEquals on ParentVolume.
No Game split. SnapshotID condition is redundant with an exact resource and is not added.

`shared_delete_policy(snapshot_id=...)` can narrow qualification to an exact snapshot. Future
Stage B synth uses region-scoped snapshot/* plus all those independent conditions; it is never
Resource `*`. Selecting an exact naturally eligible target for initial qualification and further
narrowing its resource is a next-release review item, not an approval to delete any current ID.
Canonical and future Stage A have **no DeleteSnapshot statement**. No tag/lock/AMI/sharing mutation
is granted. Future Stage A grants required reads to the existing task, scans only four canonical
tables, limits deletion journal Put/Get/ConditionCheck to DELETION#/RETENTION# keys, and adds the
condition checks required by the transaction. Original BACKUP records cannot be overwritten by
that journal grant. Existing state/Operations/Locks permissions are preserved.

Official schema and synthesized policy conditions are checked; no IAM simulation or live
DeleteSnapshot permission evaluation was performed. Synth is not proof of effective live IAM.
Future readback and separately approved qualification must establish effective permissions.

## Explicit stuck-pending recovery

The journal still uses the non-TTL DELETION#snapshot / RETENTION#operation pair. Optional immutable
execution ARN, dispatcher Lambda ARN/revision/timeout and original lease bind new runtime records; older core-only
records remain readable but cannot establish dispatcher quiescence automatically. Existing BACKUP
provenance is untouched. Phase, attempt, request/reconciliation/observation timestamps remain CAS.

`read_quiescence` uses exact execution description before/after, bounded complete history, one
matching synchronous Lambda run task and its end, and current matching Lambda configuration.
Async/callback, truncated/ambiguous history, redrive, nonterminal execution, identity drift or
missing facts returns MANUAL_REVIEW_REQUIRED. No CloudTrail absence inference is used.
A $LATEST revision change (including a disable deployment) deliberately needs manual review;
this reader does not invent historical configuration or bypass its identity requirement.

Recovery additionally waits until **both execution termination and the last observed lease expiry
are at least 900 seconds + 60 seconds old**. This deliberately uses Lambda's supported maximum,
even though live RETENTION timeout is 120s. Expiry alone is not quiescence. A worker that passed an
old lease check must have exhausted its maximum lifetime; a newly redriven invocation cannot pass
that expired lease. Renewal changes expiry and defeats the exact CAS. The implementation assumes
the reviewed synchronous dispatcher, no background task or external lease edits. Changing that
execution model requires a new proof; time elapsed is not proof that AWS completed a sent request.

`read_recovery` requires fresh complete current references, current hold revision, exact provenance,
active/Recycling observation and the same journal pair/revision/phase/attempt/pending Lock. Two
reads must agree on relevant membership and execution revision. This supplements the still-held
formal-writer fence; reads alone do not establish exclusion of external AWS administrators.

`resume` transaction only changes ownership to a new lease of the **same** retention operation,
CAS-updates that journal to reconciliation and keeps the exact pending snapshot. It does not
clear the lock, modify provenance or dispatch. Unknown request + missing remains unknown.
An explicit success can later use normal corroborated reconciliation; active/unknown remains
pending. The Python recovery entry is an explicit operator integration contract, not a new
unauthenticated Lambda action/CLI. Operator binding and invocation must use trusted read adapters;
an arbitrary JSON proof is not accepted by the deployed handler. A separate invocation/operational
approval is required before using it in AWS. No automatic retry or second-snapshot recovery path
is added. Existing same-target retry remains explicit, max once, with fresh predicate and lease.

Before a live recovery window, exclude code/IAM updates, manual redrive and out-of-band reference
writers; verify the reviewed dispatcher is still the one bound to the record. If this cannot be
proved, preserve pending for manual review. No repair-by-deleting-lock runbook is introduced.

## Deletion meaning and remaining release gates

FORMALLY_DELETED means an exact successful Wishicraft DeleteSnapshot plus sufficiently verified
removal from active inventory. It **does not mean physical erasure**. RECYCLE_BIN_RETAINED and
ACTIVE_ABSENT remain separate facts; bin absence is not a physical-erasure certificate. Unknown
response, missing-without-record, reappearing active snapshot or new current reference is never
normalized. Collector retains NO_DELETE / false / [] / 0 as execution output.

Next: review this Draft; fix canonical Stage A settings in a separately approved release commit,
run its actual ChangeSet guard/readback, verify authority and IAM/runtime identities, then seek
separate Stage B/one-delete qualification approval. No previous D-114 Case D exception applies.
Freeze out-of-band AWS reference writers during qualification; global Wishicraft Lock does not
fence independent AMI/sharing/tag administrators. Candidate zero is normal: do not manufacture a
candidate, weaken seven/14 days, release holds or clean legacy. Routine scheduling and production
retention remain outside this slice.

## Official references

- [EC2 actions, snapshot resources and condition keys](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html).
- [Botocore retry configuration](https://docs.aws.amazon.com/botocore/latest/reference/config.html).
- [DeleteSnapshot API](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DeleteSnapshot.html).
- [Lambda timeout maximum](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html).
- [Synchronous and asynchronous Step Functions Lambda integration](https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html).
