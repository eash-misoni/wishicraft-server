# D-115 continuation: historical FAILED reconciliation and hold conditions

> Review correction, 2026-09-27: the original CloudTrail match booleans used request-wide substring searches and were insufficient to prove exact target identity. The original read artifacts remain unchanged. The [fresh exact-field recheck](retention_cloudtrail_exact_match_dev_2026-09-27.json) and the appended correction below supersede that comparison method only.

**Review candidate; no AWS mutation, hold release or deletion authorization.**
PR #8 adopted the read-only collector and investigation, not the proposed manifest
judgments or deletion completeness. Original FAILED Operations, create reservations,
journals, snapshots and provenance are unchanged. D-114 automation was not paused.

## Repository and collection identity

- Reviewed PR #8 HEAD: `0d6fc660d3a03f368695adf720cddf356be2c629`.
- Base: `d3e04d6457073699fb553ac76ca12d177b847461`.
- CI synthetic merge: `782ebce838218a161dfb7d9f22c166c08ebe7a62`.
- Actual ordinary merge: `a182a2953830fdb675926011149cd449c8664afb`,
  `2026-09-27T10:11:10Z`. All three trees equal
  `2532077b3ffa9fe3d5659e4884439b53109b5608`; no unexpected source changes.
- Actual merge CI succeeded: [normal](https://github.com/eash-misoni/wishicraft-server/actions/runs/36311724151),
  [NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36311724165),
  [Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36311724164).
- New collector execution commit: `a90c982` (full identity in proposed JSON).
- Historical reads: `2026-09-27T10:20:01.907263Z`–`10:20:03.187106Z`.
- Fresh inventory evaluated `2026-09-27T10:15:18.915128Z`; API start/end and
  two-round reference comparisons are in the attached projection. Its collector
  is unchanged from merged PR #8. This and the historical reads are not one atomic read.
- Canonical dev / `385526546525` / `ap-northeast-1` / `wishicraft-main`,
  `vol-03ac9f534326c345c`; STS, table ARN, canonical stack membership and volume/AZ verified.

Evidence (positive projections, **not raw AWS responses**):

- [Exact historical reads](retention_failed_operations_dev_2026-09-27.reads.json)
- [Terminal-code supplement](retention_failed_operations_dev_terminal_2026-09-27.json)
- [Proposed reconciliation judgments](retention_failed_operations_dev.proposed.json)
- [Fresh inventory and current references](retention_reconciliation_inventory_dev_2026-09-27.json)
- [Proposed hold conditions, one entry per independent reason](retention_hold_conditions_dev.proposed.json)

## Three failures and side effects

All three Operation IDs/types/accepted/completed times match the requested historical
records. All corresponding execution ARNs match and are FAILED. Complete histories have
25, 20 and 25 events respectively, one page each; no retry/redrive or second entry into
CreateSnapshotOnce / RunRetentionDryRun is present. Normal terminal failure cleanup is
visible. Absence of a current snapshot is corroboration, not the historical proof.

| Operation | Confirmed failure | Snapshot side-effect conclusion and evidence |
|---|---|---|
| `op-433438bf-d775-4799-8016-ff0bdcb361a7` | CreateSnapshotOnce, event 15: ClientError / explicit UnauthorizedOperation; historical IAM snapshot ARN was incorrectly account-qualified | No snapshot created. CloudTrail event `79df13b0-e4a9-4d98-b471-a8be51ea2c10` at 08:38:35Z is an explicit denial with exact Operation tag and source volume. One request in the execution interval ±60 seconds, no returned snapshot. [Historical Phase 8B](../06_delivery_plan.md) independently recorded zero creation. |
| `op-7592d65c-3173-4b98-9036-a03a1ce8008a` | RunRetentionDryRun, event 10: TypeError, `unsupported operation value` | No DeleteSnapshot request/deletion. Historical implementation `40651ba8b211676c1a5a1b5864f225b077debbc4` passed list-valued plan evidence to the scalar/map serializer at terminal completion. It had a dry-run-only task, no delete path or attached delete permission. Historical [D-091 closeout](../09_decisions_and_backlog.md) and [delivery](../06_delivery_plan.md) explicitly record this deployment/failure and no mutation. Exact time-window CloudTrail DeleteSnapshot lookup completed with zero events; this absence is not the sole proof. |
| `op-d0383b17-8783-43fd-a7aa-b47fcd299a2a` | CreateSnapshotOnce, event 15: BackupCreateRejected, explicit EC2 rejection | No snapshot created. CloudTrail event `2604ca5a-c8ba-40d2-9d74-9311a5471269` at 16:20:22Z is an explicit denial with exact Operation tag/source volume. One request, no returned snapshot. [Pause evidence](game_restore_pause_2026-09-23.md) records create-terralith versus then-A/B-only IAM; historical source `569504933fda8220342a38d5daf5cbe833256bd0` maps definitive 400/403 rejection to BackupCreateRejected. |

A later read from collector commit `45f58dd` supplements exact terminal codes without
replacing the v3 history: BACKUP_SNAPSHOT_CREATE_FAILED for both BACKUPs,
RETENTION_DRY_RUN_FAILED for RETENTION (execution RETENTION_WORKFLOW_FAILED).
Identity, request/end times, reservations and history lengths match the previous read.
Supplement start/end are preserved in its JSON; no AWS mutation was retried.

The later BACKUP has `backup_create_intent` present and no `backup_snapshot_id`.
That reservation is preserved; it is not erased to make inventory appear clean.
The earlier BACKUP and RETENTION have neither field. Current durable provenance has
13 valid pairs (26 records), with no pair for any of these three Operations. No snapshot
reference was extracted from their Operation/execution results. Original status remains
FAILED; historical Admission, Lock and terminalization writes did happen. “No snapshot
mutation” does not mean “no control-plane side effects.”

**Judgment proposal:** historical failures with confirmed no snapshot mutation; retry is
not needed to reconcile them. The raw inventory still lists all three as unresolved
management-operation findings. This PR does not suppress those findings or teach the
collector to trust a `resolved=true` file.

Limits: historical Lambda ZIP and then-effective IAM were not independently retrieved.
For RETENTION, the historical source/closeout + real state/error + bounded CloudTrail
corroborate the conclusion; this is not a byte-for-byte historical runtime attestation.
For the first BACKUP the exact initial deployed commit was not recovered. Current main/IAM
are not used as proof of historical permissions. No Lambda log search was needed; log
absence/retention is not claimed as evidence. CloudTrail lookups cover the recorded
execution interval ±60 seconds in this account/region, not every possible later request.
No retry/redrive or failure reproduction was performed.

## Hold recommendations and separate release conditions

Every hold remains effective in this investigation. A historical “not deleted” fact (A)
is different from an explicit promise (B), live reference (C), ownership-only provenance
(D), or unresolved release terms (E). The machine-readable proposal distinguishes them.
Provenance authenticity does not itself impose permanent retention, and protection does
not waive integrity validation.

| Snapshot / reason | Current evidence and recommendation | What a separate release review must establish |
|---|---|---|
| `snap-0b1d9536e9c476c0f` migration anchor | **Continue.** Explicit “never use for cleanup” commitment in the [isolated restore runbook](../runbooks/backup_safety_isolated_restore.md). No expiry recorded. | Explicitly retire original migration rollback purpose and revise the commitment with history retained. A recent daily backup alone does not replace that original state. |
| Paper `snap-0aac363f3ce09e05a` source; `snap-0e5941ab3b8e0e6ff` protection | **Continue.** Exact journal `op-a09fec85b92d5620351ef556b7d47d4dff6f6d62e0042fc0a3f0e5c28b519f42`, ROLLED_BACK rev18, and explicit keep-both promise. | Decide the qualification/recovery purpose is retired; confirm no remaining recovery/rollback use and make any resume retirement enforceable before releasing references. Separate authorization for each promise/reference, not just a phase check. |
| Vanilla `snap-0be8e05ab05d70e84` source; `snap-0d2407a5af78afa82` protection | **Continue.** Journal `op-8639e35589a158e5e45fc2ccf68fcec06681aac6e8eeaf2b1507495e35224730`, ROLLED_BACK rev20; successful restored/original runtime qualification and retained worlds documented. | Accept final recovery experiment closeout and explicitly retire its snapshot-dependent purpose/resume path. No automatic expiry inferred from ROLLED_BACK. Source additionally has the old PLANNED reference. |
| Old PLANNED `snap-0be8e05ab05d70e84` source; `snap-0a1da731e1fe40f44` protection | **Consider release under separate approval**, after retirement; keep now. Journal `op-c049a9e8ca40dd4dda1fa71b246e484ff6164c1f16a00ca774ea8f5d95f7fdcd` stays PLANNED rev1. Pause record proves no prepare/volume/SSM/world creation. The different successor journal completed real qualification and rollback on September 24. | Owner declares this exact unused plan non-resumable, accepts successor proof and separately approves retirement. Absence of current maintenance is not retirement. Preserve original journal, plan, audit and reasons. |
| Current `snap-0212d6f8613b684ac` | **Continue dynamic reference.** Current last_success matches `op-80573487-0ca4-450d-b57a-e9160a3b17f9`, protected boundary2; intent is the same SUCCEEDED Operation. | Resolve current last_success/intent afresh. If superseded, evaluate other references and normal retention; do not create a permanent hold for every historical success. |
| Five legacy snapshots | **Remain EXCLUDED**, as in adopted collector. | Separate legacy recovery/ownership review; age alone does not admit them into ordinary retention. |

The old PLANNED plan is **unused and retained**, not proven formally abandoned. Recommended
minimal future retirement design: an explicit, reviewed retirement decision bound to the
exact journal key/revision/immutable plan/source/protection identities, retained as audit,
and honored by **all** formal resume entries. Until a separately reviewed enforceable gate
exists, a documentary assertion alone must not remove the hold. No new RESTORE phase,
schema, state machine or retirement registry is implemented here. Even retiring that plan
would not release the Vanilla source while the successor journal still references it.
Snapshot-wide keep is the union of independent reasons, not a single boolean per journal.
Hold release and actual deletion are separate decisions requiring separate approval.

## Future reconciliation consumption (proposal only)

Keep the raw finding beside the reviewed historical judgment. Any future consumer must
match account/region/system, exact Operation/type/target, request/end time, terminal
status/error, execution identity and reservation/snapshot/provenance/reference set against
reviewed evidence. Review identity and evidence availability must be independently checked.
A new Operation, changed result, newly discovered snapshot/ref, missing proof or unreviewed
judgment returns NEEDS_REVIEW. No general exception flag, ID-only allowlist, automatic TTL
closure or promotion of inventory completeness is proposed. This slice implements no such
consumer, so changed/new records remain raw findings without suppression.

## Inventory, privacy and validation boundary

Fresh collection: 14 owner snapshots, all on canonical volume; 13 valid provenance pairs,
three valid journals; zero observed snapshot locks, Recycle Bin rules or binned snapshots.
All pages completed and both rounds matched relevant references. Normal cohort2 remains
KEEP; six snapshots are separate PROTECTED (five distinct RESTORE refs plus current success),
migration anchor separately PROTECTED, legacy5 EXCLUDED. Both hold-aware old7 and 14-day OR7
reference calculations have zero outside IDs. Historical pre-hold old arithmetic still
places `snap-021079b3e3843652f` outside seven; this is not a deletion recommendation.
No hold-removal hypothetical is substituted for the normal calculation. Runtime outputs
remain `NO_DELETE`, `deletion_authorized=false`, `planned_delete_ids=[]`, `delete_action_count=0`.
The old `collector-and-manifest-not-reviewed` raw reason remains unchanged; PR #8 adopted
the collector, but manifest/complete-delete safety and this new judgment remain unapproved.

Mock tests cover nested JSON/DynamoDB wire, environment/credentials, exception text,
identity mismatch, changed snapshot refs, pagination cycles and absent history. Only
enumerated diagnostic facts and non-secret IDs/times pass storage projection. Original
recovery validation is in memory; saved projections cannot reproduce original digest
verification. No raw response, execution payload, CloudTrail credential or recovery body is
saved in the new evidence. **Handling deviation:** an overly broad search of existing
historical JSON printed an environment-bearing line to tool output. It was not copied into
new evidence; subsequent searching was restricted to paths/projections. This is not claimed
as a perfectly clean display path. No secret value/hash was intentionally extracted.

Initial local full tests/synth failed because the new worktree lacked pinned cffi in its
offline dependency cache. Failures remain in a separate temporary log; retry uses the
existing validated dependency cache, with a new output directory, not relaxed assertions.
Canonical enabled-stage Control Plane synth matches prior template SHA256
`3e06496b97d694a90018f4000d172778d6c0a5da910ca7aba2162ca1a9c3b8bb` (155 resources).
Lambda assets remain `0ffe413b74738bd4a102eb4d72f892d29c5da1941c4d5b191b088f8705816a1e`
and `fa87978b04eb784c5b6b4cbc57c3995dde73af8833e981e023d0175a59218549`.
No runtime/IAM/stage/CI-selection changes. Local full tests: **2013 passed**; Ruff lint/format and mypy (271 source files plus
explicit tools check) passed. Canonical enabled Control Plane and independent Web synth
succeeded. Final normal/NeoForge/Paper CI results are recorded in the
continuation Draft PR; it remains unmerged. Primary checkout unrelated changes are preserved.

Before real deletion, still separately required: reviewed hold releases where applicable,
fresh inventory/provenance/current references, AMI/sharing/other AWS dependency checks,
concurrency fencing, separately reviewed deletion adapter/IAM and explicit snapshot-specific
approval, followed by result reconciliation. None is implemented or authorized here. Cost
was not measured; 14-day retention has no count cap.


## PR #9 review correction: exact CloudTrail target fields

Fix commit `48345b52638b638049f5adc873b909b18fb7621b` replaces request-wide
`operation_id in json.dumps(requestParameters)` and volume substring checks.
Observed CreateSnapshot requests both use `requestParameters.volumeId` and
`requestParameters.tagSpecificationSet.items`, containing one `resourceType=snapshot`
entry with a list of `{key,value}` tags. Only the exact `WishicraftOperationId` key and
its exact value are accepted. Description, unrelated tags and other fields do not count.
Unknown/missing structures have no fallback; duplicate specifications, duplicate tag keys
(including identical duplicates), missing/invalid tag values and type errors leave reasons
and cannot produce `target_matches=true`. Account/region and exact
`eventSource=ec2.amazonaws.com` / `eventName=CreateSnapshot` are also required.
Individual field booleans are diagnostic; only the aggregate target result represents a
complete target match. DeleteSnapshot does not use this CreateSnapshot matcher.

Fresh read-only EventId lookup, `2026-09-27T11:01:06.782321Z`–`11:01:07.763942Z`:

| Event ID | Operation | Result |
|---|---|---|
| `79df13b0-e4a9-4d98-b471-a8be51ea2c10` | `op-433438bf-d775-4799-8016-ff0bdcb361a7` | One event, final page, envelope/body EventId exact; volume/tag/API/account/region exact; explicit denial; no unknown reason |
| `2604ca5a-c8ba-40d2-9d74-9311a5471269` | `op-d0383b17-8783-43fd-a7aa-b47fcd299a2a` | One event, final page, envelope/body EventId exact; volume/tag/API/account/region exact; explicit denial; no unknown reason |

[New positive-projected evidence](retention_cloudtrail_exact_match_dev_2026-09-27.json)
records the fix commit, method and read times. Raw CloudTrail contents were compared in
memory; no raw request/environment/credential/exception text was persisted. The old
`.reads.json`, terminal supplement and inventory were not rewritten. Earlier matching
booleans alone are not revalidation evidence. Both historical BACKUP conclusions remain
PROPOSED and unchanged on the strengthened evidence; the historical artifact limitations
above remain. RETENTION was not recollected or rerun; inventory was not recollected.

Regression coverage includes correct fields, ID-only descriptions, wrong tag keys,
wrong volume with matching text elsewhere, prefix/suffix values, missing/malformed/duplicate
structures, API/account/region mismatches, collector integration and safe normal/exception
persistence. Focused helper + existing inventory tests: 81 passed. Runtime, IAM, stage config,
original FAILED records/reservations, journals, provenance, holds and raw collector findings
are unchanged. AWS mutation/creation/deletion/hold release: zero; D-114 was not stopped.
NO_DELETE / deletion_authorized=false / planned_delete_ids=[] / delete_action_count=0 remain.

The correction's initial full-suite run used a new `/private/tmp` fixture root whose
files inherited GID 0, while strict owner checks expected the caller's GID 20. It produced
71 failures / 1982 passes. A retained failing record was UID 501 / GID 0 / mode 0600 /
nlink 1, isolating the mismatch. A new system-user temporary root (GID 20) is used for
revalidation; the previously failing ownership checkpoint passes without any source or
assertion change. Full-suite and final HEAD CI results are recorded in PR #9. Original
failed fixtures/logs are retained; this is an environment failure, not waived coverage.
