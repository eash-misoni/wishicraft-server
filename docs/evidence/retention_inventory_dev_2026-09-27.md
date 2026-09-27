# D-115 dev read-only retention inventory — review candidate

Base main: `d3e04d6457073699fb553ac76ca12d177b847461`.
Collector execution commit: `9ec0b1671ea5d6c4cc97eb64f8523648fa6e2ad4` (committed collector in dedicated worktree; only evidence/docs were pending).
Collection: **2026-09-27T07:33:50.579956+00:00 → 2026-09-27T07:33:53.378523+00:00**.
Fixed policy evaluation: **2026-09-27T07:33:53.381923+00:00**. UTC day is exactly 24 hours.

Account `385526546525`, region `ap-northeast-1`, profile `wishicraft-dev`,
system `wishicraft-main`, canonical Data EBS `vol-03ac9f534326c345c`.
STS/canonical configuration, Control Plane table membership and exact table ARNs,
and actual configured volume/AZ were checked. No alternative target was inferred.

## Result and review boundary

**NO_DELETE**, `deletion_authorized=false`, `planned_delete_ids=[]`,
`delete_action_count=0`. Collector-created snapshots: **0**. AWS mutation calls: **0**.
No deploy, formal RETENTION/BACKUP, Game/EC2/SSM operation, lock/maintenance,
intake restriction, schedule change or tag change. D-114 automatic BACKUP continues.
This branch remains a Draft review candidate; no merge or deletion authority is claimed.

[Value-minimized JSON](retention_inventory_dev_2026-09-27_v4.json) contains all per-API
page/time/target audits, per-snapshot UTC/JST acquisition/age/tier/encryption/lock,
provenance result, journal identities/revisions, multiple holds, policy ranks and gaps.
[Proposed historical holds](retention_holds_dev.proposed.json) remain **PROPOSED**.
[Collector contract and replay](../runbooks/retention_inventory.md).

## Inventory and provenance

Owner-wide unfiltered DescribeSnapshots: **14**, all **14** from the canonical volume;
other volume/project scope count **0** by volume (the historical migration anchor has
non-current ownership tags, so no normal-BACKUP classification is inferred from its tags).
All are completed, encrypted, standard tier. There are **13 valid immutable provenance
pairs / 26 Backups rows**, including five legacy schema-1 backups and eight shared backups.
The migration anchor has no normal BACKUP pair and is separately retained by historical
identity; it is not a falsely verified normal backup. Pair-only/snapshot-only anomalies:
none among the 13 claimed BACKUPs. Operations TTL was not used as ownership proof.

Snapshot lock pages: **0 records**. Recycle Bin rule pages: **0 rules**; Recycle Bin
snapshot pages: **0 records**. These were successful reads, not permission-failure defaults.
No Recycle Bin restoration guarantee is asserted. Broader AMI/service/sharing deletion
constraints are not certified by this collector and remain future pre-deletion work.

Five Game records, one creation registry and three Whitelist policy records were read;
policy member values, archive hashes/content and player data were not saved. Paper's
`creation.import` is represented as presence only, not an EBS snapshot reference.
The Games and immutable provenance records matched across reads.

## Snapshot-by-snapshot disposition

Rank is within the **new hold-aware normal shared-volume group**, never per Game.
PROTECTED and legacy/migration groups do not consume its minimum seven.
Acquisition time is EC2 StartTime verified against provenance, not completion time.
All rows still require collector/manifest review and fresh deletion-time coordination.

| Snapshot | Acquired UTC | Age days | Conservative class | Normal rank | Retain reasons |
|---|---|---:|---|---:|---|
| `snap-0212d6f8613b684ac` | 2026-09-27T05:27:20.322000+00:00 | 0.088 | PROTECTED | — | backup_protection.intent; backup_protection.last_success |
| `snap-0e5941ab3b8e0e6ff` | 2026-09-25T08:21:18.683000+00:00 | 1.967 | PROTECTED | — | Paper journal:pre-restore-protection; proposed-historical-hold:explicit-retention |
| `snap-0aac363f3ce09e05a` | 2026-09-24T11:17:26.669000+00:00 | 2.845 | PROTECTED | — | Paper journal:source; proposed-historical-hold:explicit-retention |
| `snap-0d2407a5af78afa82` | 2026-09-23T08:38:21.444000+00:00 | 3.955 | PROTECTED | — | Vanilla journal:pre-restore-protection; proposed-historical-hold:provisional-review |
| `snap-0a1da731e1fe40f44` | 2026-09-22T16:32:10.626000+00:00 | 4.626 | PROTECTED | — | old PLANNED journal:pre-restore-protection; proposed-historical-hold:provisional-review |
| `snap-07106a22069868738` | 2026-09-12T12:49:47.313000+00:00 | 14.781 | KEEP | 1 | retention-owned |
| `snap-0be8e05ab05d70e84` | 2026-09-12T10:31:35.625000+00:00 | 14.877 | PROTECTED | — | Vanilla journal:source; old PLANNED journal:source; proposed-historical-hold:provisional-review |
| `snap-021079b3e3843652f` | 2026-09-12T03:31:02.313000+00:00 | 15.169 | KEEP | 2 | retention-owned |
| `snap-0bc776ec580afd4ac` | 2026-09-12T02:38:39.124000+00:00 | 15.205 | EXCLUDED | — | legacy-scope-protected |
| `snap-005ce340d03a42340` | 2026-09-11T10:16:48.543000+00:00 | 15.887 | EXCLUDED | — | legacy-scope-protected |
| `snap-0989e090822d69d1e` | 2026-09-08T13:06:56.332000+00:00 | 18.769 | EXCLUDED | — | legacy-scope-protected |
| `snap-0762ec7637f489d5b` | 2026-09-07T13:50:38.944000+00:00 | 19.738 | EXCLUDED | — | legacy-scope-protected |
| `snap-079c0aa0c06935d8f` | 2026-09-07T08:49:24.460000+00:00 | 19.948 | EXCLUDED | — | legacy-scope-protected |
| `snap-0b1d9536e9c476c0f` | 2026-08-23T08:27:58.717000+00:00 | 34.962 | PROTECTED | — | proposed-historical-hold:explicit-retention |

## Live references versus historical promises

Three valid non-TTL RESTORE journals were read:

- Vanilla `op-8639e35589a158e5e45fc2ccf68fcec06681aac6e8eeaf2b1507495e35224730`,
  ROLLED_BACK / revision 20: source `snap-0be8e05ab05d70e84`, protection `snap-0d2407a5af78afa82`.
- Paper `op-a09fec85b92d5620351ef556b7d47d4dff6f6d62e0042fc0a3f0e5c28b519f42`,
  ROLLED_BACK / revision 18: source `snap-0aac363f3ce09e05a`, protection `snap-0e5941ab3b8e0e6ff`.
- Old unused plan `op-c049a9e8ca40dd4dda1fa71b246e484ff6164c1f16a00ca774ea8f5d95f7fdcd`,
  PLANNED / revision 1: same Vanilla source, protection `snap-0a1da731e1fe40f44`.

Phase does not release a hold. Existing journals and source/protection snapshots were not
edited. The historical manifest adds six conservative proposed holds: migration anchor,
two explicit Paper holds, and three provisional Vanilla/old-plan holds. Four further
entries document ownership-only or historical non-deletion without adding permanent holds.
No recorded expiry permits automatic release. Reviewer judgment is still needed, particularly
for historical Vanilla obligations; the live journal holds independently remain effective.

`backup_protection`: boundary **2**, protected_boundary **2**, same successful intent and
last_success `op-80573487-0ca4-450d-b57a-e9160a3b17f9` / `snap-0212d6f8613b684ac`.
Acquired `2026-09-27T05:27:20.322Z`, verified `2026-09-27T05:31:22.833615Z`.
Its current reference adds a hold; successful provenance alone is not a permanent hold on
all backups. Original acquisition and later verification were not conflated.

## Old and new reference calculations

The old deployed classifier's eight shared normal backups, without these new reference
exclusions, put **`snap-021079b3e3843652f` outside seven**. This is historical arithmetic,
not a proposed deletion or the old workflow's executable one-delete plan.

After independent holds, the normal group has only two: `snap-07106a22069868738` and
`snap-021079b3e3843652f`. Both old-seven and new-14-days-OR-seven arithmetic retain both;
**new outside-policy count is 0**. Being older than fourteen days alone is insufficient.
The new seven-count group is not reduced by treating held snapshots as normal backups.
No timestamps were advanced, holds removed, or completeness flags forged to produce candidates.

## Remaining uncertainty and historical failures

The collector conservatively lists three failed management Operations for review:

- BACKUP `op-433438bf-d775-4799-8016-ff0bdcb361a7`, requested
  2026-09-07 08:38:29.797365 UTC, terminal 08:38:35.736752. The historical Phase 8B
  [delivery record](../06_delivery_plan.md) records explicit CreateSnapshot denial and zero
  snapshot creation. This is not a new D-115 failure or permission-expansion request.
- RETENTION `op-7592d65c-3173-4b98-9036-a03a1ce8008a`, requested
  2026-09-08 13:14:55.289968 UTC, terminal 13:15:06.307775. Its terminal status alone
  is not promoted to fully reconciled deletion history; separate review remains.
- BACKUP `op-d0383b17-8783-43fd-a7aa-b47fcd299a2a`, requested
  2026-09-22 16:20:11.302008 UTC, terminal 16:20:23.148398. The preserved
  [RESTORE pause evidence](game_restore_pause_2026-09-23.md) records explicit snapshot-create
  denial and no matching snapshot. Do not reinterpret that historical pause as a current
  automation incident or modify the Operation to resolve this inventory report.

No actual snapshot/provenance/journal mismatch was found. NO_DELETE remains mandatory because
this collector and manifest are unreviewed, historical failure reconciliation is conservative,
additional AWS deletion constraints are not certified, and fresh deletion-time reference
checks/concurrency protection are not implemented or authorized. A matching collection does
not certify a future point in time. Cost is unmeasured; fourteen-day retention has no count cap.

## Collection consistency, corrections and privacy

Two rounds completed in the first bounded attempt; all relevant domains matched. All API
pages reached the last page without access denial, duplication or token cycles. Strong
DynamoDB scans are not a transaction across tables/pages/services. No snapshot was added or
completed during the observed endpoints. This does not assert that ongoing normal automation
cannot change the inventory after collection.

The initial 3dfdc20 projection is retained locally as `inventory-v1.json`; it reported formal
Games policy/registry rows as malformed and an old TIMED_OUT lifecycle test as unresolved.
The collector-only correction 5126d86 was reproduced with synthetic records and tests;
`inventory-v2.json` is also retained. The 6365ba3 projection adds explicit historical
old-policy arithmetic and known management type/times. The final 9ec0b16 collector also preserves malformed-authority and protected-metadata anomalies; its v4 read has the same inventory/reference classifications. Prior local collection outputs were not overwritten.
No runtime schema, protection boundary, IAM or deployed code was repaired in this task.

Original recovery bytes and derived hashes were validated in memory; the saved projection
omits them. Synthetic valid shared recovery tests include mock environment/Compose/hash values,
DynamoDB wire format, embedded JSON, and exception paths. Saved evidence can replay arithmetic
at its fixed evaluation time; it cannot reauthenticate removed original provenance bytes.
Its file hash only identifies saved bytes, not the completeness/truth of AWS data.

## Validation and unchanged runtime

Local full suite at collector qualification: **2004 passed**; focused final collector tests:
**32 passed**. Ruff lint/format and strict mypy passed (270 project source files plus explicit
four-file collector checking). All **10 existing CI CLI synth contexts** passed: frozen Phase 1,
Target, legacy Control Plane variants, canonical stage shared Control Plane, explicit enabled
validation, and independent Web variants. Docker/shellcheck are unavailable locally; normal,
NeoForge and Paper GitHub CI remain required and are recorded against the final Draft HEAD.

Canonical Control Plane template SHA-256 remains
`3e06496b97d694a90018f4000d172778d6c0a5da910ca7aba2162ca1a9c3b8bb` (155 resources),
byte-identical to D-114 stage B. Shared Lambda asset remains
`0ffe413b74738bd4a102eb4d72f892d29c5da1941c4d5b191b088f8705816a1e`, other asset
`fa87978b04eb784c5b6b4cbc57c3995dde73af8833e981e023d0175a59218549`.
No src/infrastructure/config/dependency/workflow differences from d3e04d6. No AWS release
or live IAM/stack revalidation was needed or claimed. Canonical enabled dev configuration
and CI validation-input separation remain unchanged.

## Handoff

Review collector, hold manifest judgments and this read-only evidence in the Draft PR.
Actual delete adapter/permissions/schedule and specific snapshot authorization are separate
future work. Keep automation operating and every snapshot/reference intact. Primary checkout
unrelated modifications remain separate from the dedicated execution worktree. Learning Wiki
sync targets the finalized PR HEAD and explicitly distinguishes it from unmerged main.

## Follow-up (original collection retained)

PR #8 was adopted without authorizing deletion/hold release. See the separate
[historical failure and hold-condition review](retention_failure_holds_dev_2026-09-27.md).
The original raw FAILED findings and this collection are unchanged; new judgment is a
review proposal, not a rewritten successful Operation or completeness certification.
