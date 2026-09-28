# D-115: read-only retention inventory

The read-only collector is adopted via PR #8. The investigation is closed under the
[2026-09-27 adoption record](#investigation-closeout-2026-09-27); it is not a deletion
adapter or an approved completeness authority. D-114 automatic BACKUP continues unchanged.
The formal RETENTION workflow is not invoked: even its dry-run writes Operations/Locks.

## Run and evidence boundary

Use a clean committed checkout, canonical stage/account/region/volume and an explicit
SSO profile. Before the first AWS read, run the collector tests (including synthetic
secret/exception tests). Never dump process environment, raw API responses or exception
messages. No new permissions are required or applied by this tool.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:src tools/dev-env run -- uv run pytest tests/unit/test_retention_inventory.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:src tools/dev-env run -- uv run python -m tools.retention_inventory \
  --stage dev --profile wishicraft-dev \
  --manifest docs/evidence/retention_holds_dev.proposed.json \
  --output /path/to/new-exclusive-evidence.json
```

The output path must not already exist. Use a new temporary root for each investigation;
retain failed local test/collection results rather than overwriting them. The tool first
checks STS account, canonical stack table membership/table ARNs and canonical volume/AZ.
It never derives a different account/volume from inventory tags or scans arbitrary tables.

All owner snapshots are collected, without tag filters. Strong scans cover only canonical
SystemState, Games, Backups and Operations. Snapshot locks, Recycle Bin rules/details and
Recycle Bin snapshots are read with pagination. Each call records start/end, target, page
count, last-page reachability and sanitized error class. Empty intermediate pages continue;
cycles, missing/duplicate identities, partial failures and malformed records stay visible.
Access denial/unsupported APIs are unknown, not confirmed empty.

The original recovery JSON/digest and immutable pair are checked in memory using existing
strict validators. Only a positive projection crosses storage/stdout boundaries. Recovery
runtime.env, its hashes, Compose, arbitrary descriptions/tags, environment values, player
payloads, access members and raw exception bodies are not evidence fields. A retained
snapshot can also have integrity errors; its hold never bypasses verification. Legacy
scope remains excluded; provenance self-reference alone creates no hold.

## Reference authority and concurrency

RESTORE key/type/plan schema/system/stage/project/Game/operation/request/revision are
validated. Both source and pre-restore snapshots are held, including PLANNED and
ROLLED_BACK. A malformed journal still tentatively holds syntactically valid references
and reports the identity error. Temporary-volume cleanup is not snapshot-hold release.
The proposed historical manifest distinguishes explicit retention, provisional review,
historical non-deletion and ownership-only evidence. Only the first two add holds;
none is labelled user-reviewed. Missing manifest snapshots/evidence are unresolved.
Current backup_protection.last_success/intent and unresolved operation snapshot references
add independent holds. IMPORT archive paths/hashes are not EBS snapshot identities.

Two complete collection rounds are compared in memory. At most two attempts (four rounds)
are allowed. Compared domains: full snapshot state/tags/acquisition/tier, locks, resolved
Recycle Bin rules (excluding API ResponseMetadata), bin membership, all immutable Backups,
Games, RESTORE plan/revision/phase, SystemState desired/selected Game/revision/current
operation/maintenance/protection and nonterminal Operations. Periodic observer timestamps
are excluded; protected/dirty boundary, intent and restore revision are not. No service is
paused and no lock is acquired. Page completeness, record validity and matching endpoints
are separate facts, not an atomic cross-service snapshot or a guarantee about later deletion.
Unstable or incomplete reads remain NO_DELETE.

## Three outputs

1. `policy_projection`: unapproved arithmetic on verified normal shared-volume snapshots,
   after separate holds. Old newest-seven and new **14 × 24 hours OR newest seven** are
   compared over that same cohort. This is not an executable plan from the deployed old
   RETENTION workflow and does not reproduce its one-delete cap. Separate protection does
   not consume the normal seven. Exact 14-day boundary stays; a tie across seventh/eighth
   suppresses all projected candidates, preserving existing ambiguity handling.
2. Per-snapshot conservative classification and multiple hold/integrity reasons. Even an
   arithmetic outside-retention result remains retained pending review/completeness.
3. `missing_checks` and per-API audit: missing information and unresolved judgment.

Every execution output is `deletion_authorized=false`, `planned_delete_ids=[]`,
`delete_action_count=0`, `status=NO_DELETE`. There is no force/assume-complete option.
The existing offline operator continues to distrust caller-supplied `complete=true`.

Saved snapshot projections and the single fixed `evaluated_at` can replay
`tools.retention_projection.policy_projection(rows, datetime.fromisoformat(evaluated_at))`.
They cannot revalidate original recovery digests/pairs after value removal; that requires
fresh AWS reads. An artifact hash establishes byte identity, not inventory truth or deletion
permission. Recycle Bin tag-predicate matches do not guarantee future rule application or
recoverability. AMI/service/sharing references beyond this collector remain a separate
pre-deletion investigation, not a claim of completeness.

Before any actual deletion: review this collector/hold manifest, resolve anomalies and
historical release conditions, implement separately reviewed fresh reference/fencing and
AWS dependency checks, authorize specific snapshot deletion and its adapter/permissions.
No such adapter, IAM, schedule or approval is included. Fourteen-day retention has no count
cap; changed blocks affect incremental storage. Cost is not measured as snapshot count ×
volume size and is not measured by this investigation.

## Collector schema qualification during D-115

The first live projection (3dfdc20) conservatively reported Games helper rows and one
historical TIMED_OUT Operation as unresolved. Read-only field-name/known-enum inspection
identified formal Whitelist policy/registry records and `op-phase4-integration-stale-20260829`.
The local parser now validates registry and Whitelist schemas without persisting members,
uses `world.generation_counter` and `creation.import`, and retains non-UUID operation IDs.
TIMED_OUT is a formal terminal status; terminal lifecycle records are not unresolved BACKUPs.
Failed/timed-out BACKUP/RESTORE/IMPORT/RETENTION still require review. Tests reproduce these
shapes; the initial projection is retained and is not rewritten as a successful final result.
Original shared recovery contents and hashes are checked before omission, including pair
identity and exact immutable record reconstruction. No runtime schema/validator was relaxed.

`deployed_old_policy_reference` additionally shows the old classifier's normal cohort
before new journal/manifest exclusions, solely to explain how the deployed historical
seven-count arithmetic differs. Its outside IDs are not deletion recommendations; no
`planned_delete_ids` from the old planner is copied. This is distinct from the like-for-like
old/new arithmetic on the new hold-aware cohort. Failed management Operations include their
known type/status/times for review; failure alone proves neither a snapshot exists nor that
its outcome has been reconciled. The collector does not repair or close historical records.

## Historical FAILED reconciliation after collector adoption

PR #8 was normally merged as `a182a2953830fdb675926011149cd449c8664afb`.
This adopts the collector, not deletion completeness or proposed hold judgments.
[Continuation evidence and recommendations](../evidence/retention_failure_holds_dev_2026-09-27.md)
keep the three raw FAILED findings alongside a separate **PROPOSED** judgment. No records
or references are suppressed/closed, and NO_DELETE remains unconditional.

For the exact three reviewed investigation targets only, the additive local helper uses
strong GetItem, DescribeExecution, complete GetExecutionHistory and bounded CloudTrail
CreateSnapshot/DeleteSnapshot lookup. It does not invoke either operation. Run mock tests
before reads and use a new exclusive output path:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:src tools/dev-env run -- uv run pytest tests/unit/test_retention_failure_evidence.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:src tools/dev-env run -- uv run python -m tools.retention_failure_evidence --output /path/to/new-historical-evidence.json
```

Its fixed scope is canonical dev/profile wishicraft-dev. Output is positive-projected
observation, never an automatic resolution. Empty/failed reads are not proof of no side
effects. Historical Lambda artifacts/permissions require independent historical evidence;
current code cannot prove old behavior. A future review-bound matching consumer is only a
proposal in the linked evidence. The proposed hold-condition file is explanatory and is
not fed back as an executable manifest or used to release any reference.


### Exact CloudTrail CreateSnapshot matching (PR #9 review correction)

Use `match_create_snapshot_event` on original event JSON in memory. It compares the actual
`requestParameters.volumeId` and the unique snapshot specification's
`WishicraftOperationId` tag by complete equality, plus event source/name/account/region.
Never search description, unrelated tags or serialized request text for IDs. Missing,
malformed or duplicate tag/specification data retains `match_issues`; do not interpret
individual field booleans as a complete match without `target_matches`.
For a historical target correction, look up the exact known EventId, verify both lookup
and body identity and complete pagination, and save only non-secret comparison results.
Do not rerun all inventory or management Operations for this check. The two-event
[recheck evidence](../evidence/retention_cloudtrail_exact_match_dev_2026-09-27.json) supersedes
the old substring comparison; original artifacts remain historical, not retroactively
validated. NO_DELETE and independent hold/failed-operation findings are unchanged.


## Investigation closeout 2026-09-27

The user explicitly accepted the following exact historical reconciliation judgments,
including their evidence limits, and authorized normal merge of PR #9. This instruction
is the adoption authority; it is not a fabricated GitHub reviewer approval/action.
Reviewed HEAD `671c9f6edc32eade6263b9b7ba3e287932b45ddc`, CI validation merge
`a8a030e377793ec492023f2a214e4af992d25118`, and actual merge
`a710ce56801cf9f1506be0b21f563c28ba797ac3` have the identical tree
`b4259c34eac700ad2d36bb44475410ed639e4d1f`. Base was
`a182a2953830fdb675926011149cd449c8664afb`; commit identity changed, content did not.
Actual-merge CI is recorded separately from PR checks in the closeout PR/final report.

For dev / account `385526546525` / region `ap-northeast-1` / system `wishicraft-main`:

| Exact Operation | Adopted snapshot-side-effect judgment | Evidence and limits |
|---|---|---|
| `op-433438bf-d775-4799-8016-ff0bdcb361a7` / BACKUP | Explicit CreateSnapshot denial; this execution created/deleted no snapshot | Execution history, historical delivery record and exact-field rechecked CloudTrail event `79df13b0-e4a9-4d98-b471-a8be51ea2c10` |
| `op-7592d65c-3173-4b98-9036-a03a1ce8008a` / RETENTION | Historical dry-run result conversion failure; no deletion request or snapshot mutation | Historical implementation/deployment record and execution history together; an empty CloudTrail search alone is not proof |
| `op-d0383b17-8783-43fd-a7aa-b47fcd299a2a` / BACKUP | Explicit denial from the then-dynamic-Game IAM mismatch; this execution created/deleted no snapshot | Historical evidence and exact-field rechecked event `2604ca5a-c8ba-40d2-9d74-9311a5471269`; existing create reservation remains untouched |

[Investigation and its evidence links](../evidence/retention_failure_holds_dev_2026-09-27.md)
remain the detailed authority. Original Operations remain FAILED; failure is not success,
and no snapshot mutation does not mean no Control Plane writes. Historical Lambda ZIPs
and effective IAM were not independently reacquired. The judgment applies only to these
exact executions and bounded evidence, not arbitrary requests or future safety.
Original PROPOSED JSON, old substring observations, terminal supplement and exact-field
recheck remain unchanged historical artifacts. This dated adoption supplements them;
it does not retroactively rewrite their review status or observation method.

The collector still detects all three raw FAILED findings. These exact findings now have
reviewed explanatory judgments, but no automatic exclusion/resolution consumer exists.
There is no ID-only allowlist, trusted `resolved=true`, completeness promotion or new
execution exception. Absent contradictory new evidence, this investigation does not
require collecting the same CloudTrail, execution or inventory again or retrying operations.

All holds remain: migration anchor; Paper/Vanilla RESTORE source and protection; unused
PLANNED references; each independent journal reason; and all five legacy exclusions.
The old unused PLANNED record has retirement considerations only: no resume prevention,
journal mutation or hold release is implemented. A separate journal's reference survives
any future change to one reason. Current last_success/intent are dynamic references,
not a permanent manifest of every historical success. Adoption of the documented uses
and release considerations neither certifies release conditions fulfilled nor grants
release/deletion or a new permanent-retention promise.

**Investigation complete:** read-only collector adoption; saved real-inventory hold reasons;
three historical failure reconciliations; exact CloudTrail matcher and two-event recheck;
special-hold purposes and potential release conditions.
**Deletion operation incomplete:** fresh references/AWS constraints at deletion time;
concurrency prevention; deletion adapter/permissions/result reconciliation; limited real
deletion qualification and routine enablement. D-115 is not automatic-retention completion.
The [next bounded implementation candidate](../reviews/daily_backup_retention.md#next-bounded-implementation-after-investigation)
keeps existing holds and legacy exclusions intact.

The unconditional execution boundary remains `status=NO_DELETE`,
`deletion_authorized=false`, `planned_delete_ids=[]`, `delete_action_count=0`.
This closeout makes no AWS connection, recollection, configuration change, snapshot/hold
operation or runtime change. D-114 configuration is untouched; its current live state is
not newly observed here. Docs-only validation checks links, unchanged JSON evidence and
content boundaries; ordinary CI also verifies tests, lint/format/types and synth scenarios.

## Prepared execution contract (not released)

See [normal BACKUP execution preparation](../reviews/retention_execution.md) for the disabled
one-snapshot engine and tests. Collector `deletion_history` can distinguish an exact confirmed
deletion pair from unexplained absence; this is descriptive only. Its executable output remains
NO_DELETE / false / [] / 0, and this change creates no deletion records in AWS. Pending deletion
records do not silently suppress orphan/protection anomalies. Do not use a captured JSON,
proposed hold manifest, or historical FAILED explanation as deletion authority.

## Release preparation after PR #11 (2026-09-28, not deployed)

The disabled core was normally merged as `29cff405d83efb25ef67fb98de8b03e7ee9568f6`;
no AWS deploy accompanied the merge. The next [release-gate design](../reviews/retention_release_gates.md)
adds repository-only adapter/authority/two-stage binding and explicit pending recovery. Its Draft
is not approval to enable DELETE_ONE. Canonical dev remains false/false and the offline collector
retains NO_DELETE / deletion_authorized=false / planned_delete_ids=[] / delete_action_count=0.
[New bounded preflight](../evidence/retention_release_preflight_dev_2026-09-28.json) found all three
adopted historical FAILED records still present, 14 owned target-volume snapshots and zero policy
candidates. These are time-bounded observations, not future inventory or deletion authorization.

Future release order: review → canonical Stage A commit/CI → separately authorized deployment
with deletes disabled → runtime/IAM/authority readback → separate Stage B and one-delete
qualification approval. Validation-only `retention_validation=provisioned|enabled` assemblies
are never deployment artifacts. No candidate is manufactured. Do not delete pending Locks or
restart an unresolved request; use the exact-operation reconcile-only contract after quiescence
is proved, or leave MANUAL_REVIEW_REQUIRED. All existing holds, journals and legacy exclusions
remain; D-114 automation is unchanged. The investigation closeout above remains historical fact.

## PR #12 review correction: DynamoDB numbers and verification inputs (2026-09-28)

Repository-only correction, not a release or new AWS observation. `dispatcher_timeout` now
round-trips through DynamoDB N / TypeDeserializer's Decimal into an exact int after finite,
integral and 1–900 validation. Historical records without dispatcher binding remain readable.
The recovery reader normalizes only `lease_expires_at` at its boundary: exact integral Unix
seconds 1–253402300799 (through UTC 9999-12-31 23:59:59). Fractions, bool, float, nonfinite,
wrong types and out-of-range values are rejected, never truncated or replaced. Shared item()
and LeaseProof semantics are unchanged; expiry, 960-second quiescence, ownership and reference
checks remain prerequisites.

Legacy build_app/CI synth scenarios explicitly select `retention_validation=disabled`, alongside
`daily_backup_validation=legacy`. Canonical shared deployment uses **neither override** and reads
the committed stage configuration. Future A/B override synths remain explicit validation only.
Missing-stage defaults are tested against an independent empty fixture; canonical flag values
are not hardcoded as false in regression assertions. Temporary configuration copies cover
false/false, true/false and true/true via build_app and the real CLI. The CLI copy includes its
infrastructure entrypoint so its canonical path resolves to the copied config, not the checkout.
No tracked config is rewritten and no process-wide environment override is used.

The actual dev file remains false/false; daily BACKUP configuration remains unchanged. A future
canonical Stage A/B setting change must still pass the canonical shared synth **and** the
independent legacy checks. Single-Game provision and false/true remain errors. See the
[review correction evidence](../evidence/retention_release_review_2026-09-28.md) for wire-format
reconcile/recovery tests and template comparison. This correction grants no deployment or
snapshot permission; PR #12 stays Draft pending review.
