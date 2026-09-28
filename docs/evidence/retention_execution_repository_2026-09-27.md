# D-115 repository execution qualification — 2026-09-27

Implementation `e554403012a9a04765ee923f9dd9f4a2f0890b72`, based on main
`328937ddd8037d0c297089c9ae782b1c730b4bc6`. This is a Draft PR review candidate,
not a release or execution authorization. Final docs HEAD and CI runs are recorded in the PR.

The [execution contract](../reviews/retention_execution.md) defines the normal-only planner,
fresh validation, existing global lock with persistent pending fence, at-most-one snapshot,
separate non-TTL deletion journal and conservative response reconciliation. The original
investigation/FAILED/hold artifacts were not modified. No retrospective AWS collection occurred.

## Local qualification

- Focused new engine/repository/read/projection tests: **82 passed** (fixed synthetic clocks).
- Full suite: **2136 passed**. The initial run exposed two strict existing terminal-lock fixture
  expectations; these now include the pending condition while preserving owner/lease/expiry
  checks. A regression proves pending prevents terminal cleanup. No test was skipped/xfail'd.
- Ruff lint passed; format check **389 files**; strict mypy **282 source files** passed.
- Canonical dev Control Plane synth (stage=dev, phase=8, control-plane, two_games/reset/
  game_creation/whitelist_management/game_packages=true), **without validation override**, passed.
- Independent Web synth with creation/whitelist context passed.
- Existing legacy/target/phase1/other synth contexts and Docker integration are covered by the
  unchanged normal/NeoForge/Paper CI definitions. Local Docker/shellcheck are unavailable; no
  local Docker success is claimed. Final PR CI results supplement this record.

All tests used new dedicated temporary roots. Failed synthetic runs were preserved separately,
then corrected and rerun; no stored historical result was rewritten. Test failures in early new
fixtures (API keyword/initial protection state) were fixture issues, not live AWS observations.

## Synth comparison against exact main

[Machine-readable comparison](retention_execution_template_2026-09-27.json):

- Baseline template SHA256: `3e06496b97d694a90018f4000d172778d6c0a5da910ca7aba2162ca1a9c3b8bb`.
- Candidate template SHA256: `374ee130f6882283e814edd1f9b32fbda923052e05f1bec0fb22683f23aebc5b`.
- **155 resources**, no additions/removals. All deployable Properties are equal except Code
  on the 13 listed Lambda resources; only their associated asset-path metadata also changes.
- Shared-source asset: `0ffe413b74738bd4a102eb4d72f892d29c5da1941c4d5b191b088f8705816a1e`
  -> `5366c24912a4e5e1c9c68298969898b4e0c19daff28b1132aae2f3423782d0ea`.
- Bundled Discord-command asset: `fa87978b04eb784c5b6b4cbc57c3995dde73af8833e981e023d0175a59218549`
  -> `f544b652e091b375a5737c8cef437a6bf4ae28f25833e9b02f9d3892cbc64e06`.
- Reason: shared source now includes the execution modules, extracted pure validators and
  two guarded lock-removal conditions plus disabled RETENTION mode handling. This packaging
  changes D-114 Lambda Code assets too; D-114 source/configuration/permissions are not changed.
- All six State Machine definitions, roles/IAM, tables, environment/configuration, 56 alarms,
  schedules, outputs/parameters and other resource metadata remain equal. The synthesized
  template contains **no ec2:DeleteSnapshot grant**. No template hand edits were used.

These are local synth/asset comparisons, not deployed IAM, workflow, API or notification
qualification. Neither assembly was published or deployed; no ChangeSet was created.

## Remaining live-release gates

The real EC2 delete adapter and server-side runtime binding are deliberately absent. Formal
DELETE_ONE is unconditionally disabled, and the existing collector remains NO_DELETE / false /
[] / 0. Fake deletion calls are synthetic only. New non-TTL keys and pending Lock attribute are
schema contracts and fixture records, not data written to AWS.

Before separately approved live qualification: review authoritative hold binding, exact treatment
of unresolved references, external AWS-writer exclusion, minimum IAM, SDK retry controls and
stuck-dispatcher quiescence/recovery. Real API eventual consistency, permissions, response-loss,
Recycle Bin behavior, competing live operations and restore contents are unproven. The old
dry-run runtime intentionally remains fail-closed on future deletion record types until its
future binding is reviewed. Do not present this preparation as enabled automatic retention.

All migration/RESTORE/PLANNED holds, independent references, legacy exclusions and dynamic
last_success/intent protections remain. No candidate was manufactured. AWS connections,
mutations, snapshot creations/deletions and hold releases: **0**. D-114 was not stopped or changed.
The primary checkout's unrelated edits were preserved; only the dedicated branch holds this work.
