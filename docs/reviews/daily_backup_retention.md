# D-115 Fourteen days OR newest seven: independent dry-run

Accepted for repository-only dry-run preparation by the 2026-09-26 request. Not a deletion release.
The deployed D-097 shared-volume newest-seven workflow remains unchanged. Select the new
`days14-or-newest7-v1` policy explicitly in the **offline** comparison entrypoint
`python -m wishicraft.retention_daily_operator --input <captured-evidence.json>`.
It never calls AWS or formal RETENTION, creates a deletion plan, or mutates a snapshot.
Automatic acquisition flags have no connection to this policy or snapshot deletion.

`retention_daily.plan` reuses the current ownership/provenance classifier. Shared-volume normal
snapshots are retained if verified EC2 acquisition time >= evaluation time minus UTC 14*24 hours,
**or** in the newest seven normal snapshots. Deletion candidates must meet both opposite tests.
Completion/provenance time cannot rejuvenate an old acquisition. The seventh-position timestamp
ambiguity still makes the entire plan NO_DELETE. Exactly fourteen days is retained; future,
naive/invalid timestamps, duplicate inventory, incomplete inventory or anomalous provenance
cannot certify candidates. Fewer than seven are all retained. Game tags do not split the group.

Separate protections do not consume normal seven slots. Existing migration/legacy/protected/
unclaimed snapshots remain excluded and retained. An explicit `ProtectionInventory.reasons`
map additionally protects referenced source/protection snapshots and historical proof holds,
without assuming the phrase "protection BACKUP" implies a protected tag. Each result reports
KEEP, PROTECTED, EXCLUDED, ANOMALY or CANDIDATE with reasons. A NO_DELETE run retains all otherwise
eligible entries and emits no safe candidates. No immutable tag/provenance edits are proposed.

## Protection authority and deliberate incomplete inventory

A deletion safety proof must combine immutable Backups pairs, complete EC2/snapshot-lock inventory,
explicit reviewed historical holds, and **current** unfinished management references. RESTORE's
non-TTL `SystemState` records (`record_type=RESTORE`, `restore#<operation>`) and their immutable
plan/source/protection/checkpoint fields are authoritative for restoration references. IMPORT
and historical experiments also have operator evidence that must be reconciled into a reviewed
hold manifest; absence of a tag or a prose-only hold is not machine-complete proof.

This preparation has not acquired or certified that complete real inventory. The offline adapter
therefore deliberately supplies `ProtectionInventory.complete=false`, even if a supplied JSON
claims completeness. It can display supplied hold reasons and compare the old policy, but its
new-policy result stays **NO_DELETE**. The pure planner tests exercise a complete synthetic
protection inventory; that fixture is not production authorization. A later destructive release
must separately implement/review the authoritative collector and fresh reference reconciliation.
This is a safety boundary, not a claim that runbook prose makes deletion safe.

The captured input uses policy, evaluated_at (aware UTC), RetentionContext fields, full AWS
DescribeSnapshots objects (`StartTime` encoded RFC3339), DynamoDB wire-format `provenance_items`,
complete-read flags, and `protection_inventory.reasons` (snapshot ID -> list of evidence reasons).
The existing strict pair loader revalidates both durable records and shared recovery metadata.
All EC2 pages and provenance pages must have been acquired read-only; a partial artifact cannot
be promoted by setting a flag. The comparison returns deployed-policy and new-policy projections.
The deployed projection is historical-policy calculation only, never a deletion recommendation.

Fourteen-day retention has no count ceiling. Incremental EBS snapshots can still accumulate
substantial changed-block storage. No unmeasured storage charge or saving is asserted.
