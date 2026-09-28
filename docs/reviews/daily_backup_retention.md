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

## D-115 collector review candidate — 2026-09-27

The original offline completeness boundary above is unchanged. A local, read-only
[collector and replay contract](../runbooks/retention_inventory.md),
[proposed historical hold manifest](../evidence/retention_holds_dev.proposed.json) and
[actual dev inventory](../evidence/retention_inventory_dev_2026-09-27.md) now supplement it.
Fourteen snapshots were collected; normal policy projection has no outside-retention entries
after separate holds. This is NO_DELETE, not collector/hold approval or a deletion release.
Daily automatic BACKUP continues; runtime/IAM/stack and deletion capabilities are unchanged.


## Next bounded implementation after investigation

The [investigation closeout](../runbooks/retention_inventory.md#investigation-closeout-2026-09-27)
adopts PR #8's collector and PR #9's limited historical conclusions, not deletion
completeness. Earlier candidate/incomplete-acquisition statements above describe their
preparation checkpoints; saved real inventory is now available, but not fresh deletion proof.

Next candidate: prepare safe retention of **normal BACKUP snapshots only**, retaining all
special holds and legacy exclusions. Keep **14 days OR newest seven**, shared-volume scope,
verified acquisition time, separate protection outside the seven slots and safe tie handling.
The next design/implementation must address:

- Fresh snapshot/provenance/current-reference validation and necessary AWS constraints,
  including AMI and sharing. Unchecked AWS behavior/state remains to be verified then.
- Prevent new RESTORE or other protected references racing a previously prepared plan.
- Reconcile uncertain delete responses and partial completion without blind repeat requests.
- Preserve immutable provenance while distinguishing formally deleted snapshots from
  unexplained absence; no such deletion record/protocol is implemented here.
- Separate a limited first qualification from enabling routine deletion, with distinct approval.

Zero eligible snapshots is a valid result. Do not manufacture candidates by creating
snapshots, advancing time, reducing retention or releasing special holds. Old PLANNED
retirement and wholesale legacy cleanup are not prerequisites for normal-group retention.
Only if an additional retirement/release mechanism is actually needed should it become a
separate reviewed task. No deletion adapter, authority, schedule or new hold judgment is
introduced by this outline.

## Repository execution preparation (following the investigation closeout)

The [D-115 execution contract](retention_execution.md) now prepares a fake-qualified, disabled
DELETE_ONE core, fresh readers, global-lock pending fence and separate durable deletion journal.
The earlier “not implemented here” statements describe the investigation slice. Actual deletion
adapter/IAM, runtime binding, release and qualification remain separate. Existing holds, legacy,
14-day OR seven policy and public NO_DELETE outputs are unchanged.
