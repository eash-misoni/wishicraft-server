# Read-only Restore candidate records — repository slice

Scope authorized on 2026-10-02: authenticated management Web list/detail using existing
Backup provenance, including repository-only Backups-table Scan/GetItem IAM definitions.
This is the demand-driven Restore UI slice in the current roadmap, not a RESTORE execution
release. Deployment, live IAM modification, source Snapshot qualification and runtime work
are separate. D-113 restoration and all existing preservation contracts remain unchanged.

## Source and meaning

Existing non-TTL Backups provenance is the source; no new table, GSI, Game field or history
writer is introduced. Operations expire independently and their retention summaries do not
contain a complete candidate inventory. Game `last_backup_at` is not a candidate history.
The existing table has only a `provenance_key` partition key, so an arbitrary history list
cannot use Query. A bounded Scan is the minimal existing-data read path.

An entry describes a historically verified successful BACKUP record, not a fresh observation
of its Snapshot. Provenance may outlive a deleted Snapshot. Both `snapshot_presence` and
`restorability` are always `unknown`. No EC2, SSM, host, volume mount, Minecraft, restore
workflow or repair call is made. No execute-restore button or action endpoint exists.

`snapshot_start_time` is the acquisition time; `provenance_recorded_at` is a separate record
persistence time. UTC is normalized using the existing timestamp contract. Schema 2 uses
snapshot-time `recovery_json.games`, not only the top-level requested Game, to describe all
Games in the shared-volume record. Positive integer `world.generation`, saved display name
and saved materialization state are projected when known. An UNMATERIALIZED Game record
does not guarantee that its world files were created. Schema 1 only identifies the recorded
Game by its existing opaque Web Game key: name/generation/full coverage remain unknown.
Current Games never fill historical gaps. The source Game key permits comparison across
renames and duplicate names; it uses the same projection as the existing Web capabilities.

The existing BackupProvenanceRecord/recovery validators check saved tags and recovery digest.
The persisted metadata fingerprint, project/stage/verified owner and exact reverse Operation
uniqueness record must also match. Invalid/missing pairs fail the read rather than become
usable candidates. These historical integrity checks do not establish current restorability.
Raw recovery JSON, runtime/configuration, seed, paths, resource IDs, actor IDs and raw errors
are not returned. Candidate keys and cursors are reversible URL-safe encodings of permitted
table keys; they are navigation identifiers, not credentials or access grants.

## HTTP and authorization

Both routes authenticate through the existing Sessions and recheck the existing canonical
Guild / Player-or-Admin Policy server-side using the saved principal. No visibility-only
permission check and no new viewer role. GET only; existing canonical-origin guard, no CORS,
no-store, CSP and session expiry remain in effect. Reader initialization/data access occurs
only after authorization. This does not alter existing write-operation authorization.

- `GET /api/restore-candidates[?cursor=<continuation>]`: schema_version 1, generated_at,
  items, next_cursor, order `page_time_desc`, page_limit 10.
- `GET /api/restore-candidates/<candidate-key>`: schema_version 1, candidate.
- Each candidate: key, acquired_at, recorded_at, provenance_version, coverage
  (`shared_volume` or `legacy_unknown`), games (`key`, `name`, `generation`, `materialization`),
  snapshot_presence `unknown`, restorability `unknown`.
- Authentication failure 401, invalid key/query 400, detail record absent 404, unsupported
  method 405, read/validation failure 503 with a fixed safe error. Missing detail record
  does not mean its source Snapshot is absent. No raw error logging or response.

One list request performs exactly one Scan with Limit 10 evaluated records and
ConsistentRead. Filtering to BACKUP_PROVENANCE happens after DynamoDB evaluates records,
so fewer than ten candidates, even zero with a continuation, is normal. At most ten reverse
GetItem reads follow. Detail uses at most two GetItem reads. All reads address only the same
stage's existing Backups table. Reads are not an atomic whole-inventory snapshot; concurrent
additions can change subsequent pages. The UI replaces each page, never calls it the newest
backups globally and never treats a failed read as no candidates. Empty-page and continuation
messages are distinct. Pagination is manual, with one in-flight candidate request and no
background scan/prefetch. Refresh restarts from the beginning. Detail is fetched afresh.

### Detail placement UX (2026-10-03 repository improvement)

The detail region sits directly below the selected card's button, rather than below the
entire candidate list. Opening a record immediately shows a local loading message and
focuses/scrolls its detail heading into view. Success and failure update the same local
region without moving focus again. The selected button exposes its expanded state and
controls the shared detail region; only one record is expanded at a time. All candidate
buttons, refresh and next-page controls are disabled during the existing single in-flight
read. A failed read clears the previous record and offers a retry with the same button.
Changing selection, refreshing or changing page removes stale details.

This improves discoverability of a functioning detail read on long lists and narrow screens;
it does not change HTTP, authorization, pagination, provenance or restoration contracts.

## Repository IAM / release boundary

Only the Web Lambda role gains `dynamodb:Scan` and `dynamodb:GetItem` on the exact stage
Backups table ARN. No wildcard resource, additional write action, new table/index, IAM grant
to the browser/Auth Lambda or CP role change. Three public config environment values bind
the project, stage and owner; a fourth selects the existing Backups table. Existing Web
resources and routing are reused. The stack template is a code candidate: no AWS IAM change
or publication has been performed by this slice.

## Verification

Tests cover historical shared membership, missing legacy/generation information, saved
materialization, safe projection, bounded pages/continuation, page-local ordering, malformed
provenance and reverse pairs, empty/read-failure distinction, not-found, authenticated Player
and Admin access, invalid-role/expired-session rejection, and non-GET rejection before reads.
The existing synthesized Web IAM test requires the sole Scan grant to be the exact Backups
ARN with only Scan/GetItem. The existing CI Chromium management check includes candidate
list/detail, pagination, escaped DOM text and read failure states.
It also covers ten-record lists at 390/320/1440px widths, detail ownership, actual viewport
visibility and keyboard focus, pending reads and duplicate clicks, switching candidates,
404/503 detail failures and retry, and clearing details on refresh/page change.

Local results and any unavailable CI checks are recorded in the task checkpoint; running
local unit tests is not live Snapshot or restoration qualification. Docker/runtime tests
remain separate because no runtime contract changes here. Repository commit/push and draft PR creation, with ordinary push/PR-triggered CI,
are authorized. Manual workflow dispatch, merge, marking the PR ready for review, deploy
and live environment operations remain outside this task.
