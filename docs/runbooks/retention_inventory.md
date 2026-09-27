# D-115: read-only retention inventory (review candidate)

This local collector is a **Draft review candidate**, not a deletion adapter or an
approved completeness authority. D-114 automatic BACKUP continues unchanged.
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
