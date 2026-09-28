# D-115: normal BACKUP retention execution contract

Repository preparation after main `328937ddd8037d0c297089c9ae782b1c730b4bc6`.
This is a review candidate, not a deletion release. Investigation conclusions and historical
PROPOSED artifacts remain as recorded in [the closeout](../runbooks/retention_inventory.md#investigation-closeout-2026-09-27).
No AWS connection, deletion, hold release, deployment or D-114 change is part of this slice.

## Authority and deployment boundary

The deployed formal RETENTION handler remains DRY_RUN. An event requesting DELETE_ONE
returns NO_DELETE / deletion_authorized=false / planned_delete_ids=[] / delete_action_count=0
before constructing AWS clients. No environment override, CLI flag, schedule or EC2 delete
adapter enables it. The new Python execution core accepts dependency injection for synthetic
qualification and a future reviewed server-side binding; it is not an authorization endpoint.
The read-only collector and arbitrary-file offline operator retain their conservative outputs.

No CloudFormation resource, role permission, workflow definition, alarm or stage setting is
added. Shared source packaging changes Lambda assets; it does not grant their functions the
new capabilities. In particular no deployed role gains ec2:DeleteSnapshot or deletion-journal
write permissions. An existing unattached schema-v1 policy helper is not activated or reused
as authority for shared schema-v2 snapshots.

The future binding must validate Admin/CLI authorization through existing Admission, select
canonical account/region/volume/tables, supply reviewed special holds, acquire the formal
RETENTION lease, and bind reads/journal/one-shot adapter. Unknown or unresolved management
records remain blockers. The adopted explanations of three historical FAILED executions are
not converted into an ID allowlist or automatically consumed exceptions. No old failure is
re-investigated here. Live enablement still needs a reviewed exact-evidence treatment of any
remaining blockers; a supplied complete/resolved flag cannot remove them.

## Policy and fresh predicate

`retention_daily.plan` remains the selection authority: verified EC2 acquisition time,
14 x 24 hours inclusive OR latest seven **normal** shared-volume BACKUPs. Separate holds,
protected, migration, legacy and unclaimed entries do not consume seven slots. A tie across
seven/eight blocks selection. The executor also rejects a tied oldest candidate. Zero snapshots
or zero candidates is normal; no reservation or request is produced.

The read adapter is not wired into the Lambda. It verifies STS/account, client region, exact
four table ARNs, strong paginated DynamoDB reads and all owner snapshot pages before selecting
the canonical volume. Strict original BACKUP pair/recovery validation precedes minimization.
It checks snapshot identity, source, encryption, completed/standard state, tags, acquisition,
provenance and current references; failures stay unknown. No TTL Operations assumption substitutes
for durable provenance. RESTORE plan identity/revision and all phases, Games/import snapshot
references, backup_protection last_success/intent, management outcomes and reviewed special holds
are read. Multiple reasons remain independent. Archive paths are not snapshot IDs.

AMI checks use DescribeImages with Owners, block-device-mapping.snapshot-id,
IncludeDeprecated=true and IncludeDisabled=true, following all pages. Any matched image blocks.
DescribeSnapshotAttribute(createVolumePermission) must positively return the exact snapshot
and an empty permission list. DescribeLockedSnapshots must be complete and unlocked/expired.
Recycle Bin ListRules/GetRule and ListSnapshotsInRecycleBin must be complete and understood;
pending/unknown rules block. A rule match is not a promise of recoverability. Reader exceptions
become fixed unknown reasons without raw response/exception persistence.

A plan is in-memory and valid for at most 120 seconds. A read must be at most 30 seconds old,
with a non-future observation time. Immediately before reservation and again before dispatch,
full selection and reference/AWS revisions must still match, and the lease must have at least
60 seconds remaining. Hashes cover public validated predicate/reference identities, not raw
recovery, Compose, environment values/hashes, player data or exception text. The original
recovery digest is retained as an existing immutable identity, not recomputed from redacted data.

## Fence choice and race limits

| Option | Decision |
| --- | --- |
| Read inventory twice | Detects change but does not exclude a new reference after the last read; insufficient alone. |
| New snapshot-specific lock service/table | Requires every current writer to adopt another locking model; not needed here. |
| Existing global RETENTION Lock plus durable pending attribute | Selected: matches Admission and management transactions and survives worker/lease failure. |

Formal START/BACKUP/RETENTION admission requires the global Lock to be absent. RESTORE journal
creation/advance and maintenance transactions also condition on its absence; an expired lock
is not absence. IMPORT uses maintenance. CREATE/whitelist metadata paths do not adopt an existing
snapshot as a recovery source. D-114 may observe or reserve an intent concurrently, but BACKUP
execution/provenance/last_success cannot commit under another formal operation's lock; changed
intent/reference membership rejects the plan. No D-114 code or schedule is changed.

Before a delete request, one transaction checks exact RETENTION operation/actor/current operation,
no active maintenance, current lock owner/lease/type/expiry, and creates:

- `Backups.DELETION#<snapshot>` (non-TTL mutable deletion journal),
- `Backups.RETENTION#<retention-operation>` (non-TTL uniqueness),
- `Locks.retention_delete_pending=<snapshot>` on the existing Lock.

Ordinary completion, cancellation, release and stale recovery may not remove a Lock carrying
this attribute. The Lock table has no TTL. A paused worker or expired lease therefore cannot
allow a formal RESTORE to introduce a new protected reference while a dispatched delete might
still complete. Loss of ownership/lease prevents further requests/record transitions. A future
operator recovery protocol must establish the dispatcher's quiescence before resolving a stuck
reservation; automatic lease stealing, lock deletion or outcome guessing is not provided.
This intentionally sacrifices availability when the result is unknown.

The formal-writer fence is not a fence against independent AWS administrators changing AMIs,
sharing, locks or snapshots. Fresh AWS reads are eventually consistent and cannot atomically
exclude those writers. Before a live deletion release, the approved execution window and
permission/operational controls must exclude such changes, and the hold authority must be
server-owned/frozen for the execution. This is an explicit live-release prerequisite, not a
claim that two reads solve cross-service races. No live delete binding is supplied prematurely.

## Request, durable result and reconciliation

The two journal keys use conditional insert/CAS; duplicate conflict fails closed. The permanent
RETENTION key prevents a restarted execution from selecting a second snapshot even after
Operations TTL. SNAPSHOT#/OPERATION# immutable provenance records are never overwritten.
The journal stores schema/policy, exact account/region/system/volume/snapshot, original BACKUP
and RETENTION operations, actor, acquisition/request/observation/confirmation times, predicate ID,
original recovery digest, bounded attempt/revision and outcome enums. No raw payload is stored.

The initial DISPATCHED reservation is not proof a request was sent and never authorizes replay.
Lost reservation response means no local dispatch. A restart encountering DISPATCHED or an
unconfirmed journal write requires reconciliation, not another request. Recorded outcomes:

| Observation | Result |
| --- | --- |
| First request explicitly denied / target missing before sending | NO_MUTATION; clears only the matching pending attribute atomically. Original absence still needs explanation. |
| API returned success | RESPONSE_RECORDED; not final, keeps fence. |
| Response/exception unknown | OUTCOME_UNKNOWN; no blind retry or automatic unlock. |
| Snapshot still active | STILL_PRESENT; keep fence. |
| Active absent and bin checked | Record ACTIVE_ABSENT or RECYCLE_BIN_RETAINED separately. |
| Explicit success plus two later independent absence observations >=10 seconds apart | FORMALLY_DELETED, confirmed_at, atomic pending removal; immutable provenance stays. |
| Access/identity/read failure or unknown request plus absence | Unconfirmed; neither absence nor elapsed time fabricates success. |

Owned active inventory is fully paginated rather than treating a filtered missing-ID error as
success. Recycle Bin presence means retained there, not physical erasure. EC2 eventual consistency
remains a live qualification limit; two observations are corroboration alongside an explicit
successful exact request, not a general proof from absence alone.

A retry is a separate explicit engine method, not Step Functions Retry. It requires a recorded
unknown response, subsequent positive STILL_PRESENT observation <=30 seconds old, >=30 seconds
since the initial request, unchanged exact candidate/predicate, lease, fresh full validation and
atomic attempt 1->2. At most one retry of the same snapshot; a second retry or new target is
rejected. DISPATCHED without a recorded response is ineligible. Denial on attempt two does not
prove the first unknown attempt had no side effect and cannot clear the fence. A future SDK
adapter must use one SDK attempt (no hidden automatic retries) and distinguish not-found before
sending from an ambiguous request result. This slice provides fake adapters only.

The collector validates both deletion keys and the exact verified shared BACKUP pair. Missing
active inventory is FORMALLY_DELETED only with matching identity, final successful reconciliation,
non-future time and no current hold/reference. Missing without a record remains ANOMALY; unknown
outcome remains DELETION_OUTCOME_UNKNOWN; a final record with a live or newly held snapshot is
anomaly. This descriptive classification never promotes overall completeness or deletion authority.
The old deployed dry-run handler remains fail-closed on future deletion journal types until the
future formal runtime binding is reviewed; no deletion records can be produced by it today.

## Next release, not part of this PR

Preserve all special holds and legacy exclusions. Review binding, authoritative holds, remaining
unknown reference treatment, timeout/quiescence recovery and external-writer exclusion. Prepare
least-privilege IAM separately: only selected snapshot resource/account/region, canonical parent
volume, Project/Stage, category=backup, schema=2, shared-volume and protected=false conditions;
no Game split and no ability to change tags. Validate supported IAM keys in the release review.
Read checks need DescribeImages, DescribeSnapshotAttribute, DescribeLockedSnapshots, bin reads
and rbin rule reads; journal CAS needs only the exact deletion/RETENTION keys and pending Lock
attribute plus formal condition checks. None is granted by this PR.

Only after separate approval should a real adapter, explicit enablement and a bounded Admin
qualification be released. That qualification and routine deletion operation are separate decisions.
Candidate zero remains acceptable. Hold retirement/legacy cleanup is not a prerequisite. No
snapshot is created, aged artificially or unprotected to manufacture a qualification target.

## AWS references checked for this design

- [DeleteSnapshot](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DeleteSnapshot.html)
  and [EBS deletion behavior](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-deleting-snapshot.html).
- [DescribeImages](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeImages.html)
  and [DescribeSnapshotAttribute](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSnapshotAttribute.html).
- [DescribeLockedSnapshots](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeLockedSnapshots.html),
  [DescribeSnapshots](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSnapshots.html),
  [ListSnapshotsInRecycleBin](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_ListSnapshotsInRecycleBin.html).
- [ListRules](https://docs.aws.amazon.com/recyclebin/latest/APIReference/API_ListRules.html),
  [GetRule](https://docs.aws.amazon.com/recyclebin/latest/APIReference/API_GetRule.html),
  [EC2 IAM actions/resources](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html).

Current local botocore service models were inspected without client/API calls. EC2 DeleteSnapshot
SDK output is empty-shaped, so a future adapter must not require a nonexistent Boto response
`Return` boolean. Official API success semantics and SDK transport success must be bound explicitly.
