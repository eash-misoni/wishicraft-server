# D-115 PR #12 review corrections — repository only

Reviewed baseline: `f168dd14f6bba7b650e6512a159d12ff4d15c1da`, base main
`29cff405d83efb25ef67fb98de8b03e7ee9568f6`. The PR was OPEN/Draft with all five checks
successful before this correction. No merge, AWS connection, read-only refresh, mutation,
snapshot action, hold release or D-114 change was performed. Prior preflight is historical
and was not recollected or relabeled as current.

Implementation is split into `66cca04` (numeric read boundaries and wire tests) and `db5e67b`
(canonical/legacy verification inputs). Final docs HEAD and its CI are recorded on PR #12.

## Numeric boundaries and regression evidence

DynamoDB's low-level N response becomes Decimal under TypeDeserializer. The strict internal
binding required an int but parse() previously normalized only schema/attempt/revision. The
same missing conversion affected Lock expiry arithmetic (float timestamp minus Decimal).

The parser adds dispatcher_timeout to exact Decimal normalization with its existing 1–900
range checked before int conversion. Missing binding fields still serialize without additions.
The recovery reader validates expiry locally before LeaseProof construction: finite integral
Decimal or strict int, positive UTC Unix seconds through 253402300799. No shared decoder or
all-field float conversion; no inferred expiry or defaults. Existing safety predicates are
unchanged. Invalid input remains INVALID_DELETION_RECORD or MANUAL_REVIEW_REQUIRED.

`test_retention_dynamodb_numbers.py` contains 57 passing cases. Fake AWS APIs return low-level
Item N values; the real item()/TypeDeserializer, DeletionRepository.read_operation/read_snapshot,
DeletionRecord.parse, RetentionExecution.reconcile, ExecutionReads.inventory/observe and
read_recovery/RecoveryRead.verify execute. The recovery reader is not replaced by a finished
RecoveryRead. Workflow history/config responses are fake; original identity and quiescence
validation runs. Normal reconcile persists and reads a bound record, retains pending until two
valid absence observations, and then verifies the same-target/owned/unexpired pending-clear
transaction. EC2 deletion uses only the existing fake adapter.

The tests cover old unbound records, integral endpoints, fractional/bool/nonfinite/wrong-type/
out-of-range inputs, expiry not reached or only just elapsed, insufficient quiescence,
nonterminal execution, changed dispatcher/owner/target, new hold and a new live RESTORE journal.
Read-only recovery changes no wire rows; canary environment/exception values never appear in
returned evidence. No pending condition was removed to make tests pass.

For independent negative reproduction, each reviewed faulty source file was restored in a new
isolated source copy. The bound round-trip test failed against the old parser. Separately, with
the corrected parser but old recovery reader, the valid full recovery read failed. Both pass
with the corrections. Initial test-fixture account mismatch and missing copied CLI dependencies
were fixture failures; corrected fixtures were rerun in new result versions, not counted as
implementation proof.

## Configuration isolation

The existing synth-only retention_validation input is reused; no new configuration framework.
Historical build_app scenarios explicitly select disabled and retain their old resource/IAM
assertions. Four legacy Control Plane CI commands also select disabled. The independent daily
BACKUP enabled scenario selects retention disabled; canonical shared CI still reads actual
stage settings without either override. Future retention A/B checks remain mandatory.

11 new configuration tests cover separate temporary stage copies for false/false, true/false,
true/true via both build_app and actual CLI, canonical source/flag reporting, unchanged legacy
11 Lambda assertions, actual canonical binding and IAM presence/absence, single-Game guard,
missing-file default and invalid combinations/types. Existing tests cover synth-only override
restrictions. No tracked dev config or global test environment is edited. Configuration
provenance output now gives the actual path or missing-stage default, plus effective flags.

## Validation and infrastructure

Numeric focused tests: 57 passed. Configuration focused tests: 11 passed. Final local full suite: 2,256 passed. Lint,
format and strict type (293 files) passed. Final normal/NeoForge/Paper CI results are recorded
at the finalized PR HEAD. These synthetic checks do not establish live DynamoDB/IAM/deletion qualification.

Canonical Control Plane, future A/B, explicit legacy single/shared Control Plane, independent
Web and Target synths succeeded. [Comparison JSON](retention_release_review_synth_2026-09-28.json)
compares to the reviewed HEAD: same 155 Control Plane / 26 Web resources, only Code assets
and corresponding asset metadata change (13 Control Plane and 2 Web Lambdas bundle the shared
source). All six State Machine definitions match raw, offline resolved and canonical forms.
No canonical IAM/environment/alarm/schedule/table/resource change, no DeleteSnapshot grant or
DELETE_ONE enablement. Future A/B also differ from their reviewed counterparts only in Code.
Offline comparison is not live ASL or ChangeSet verification; no ChangeSet was created.

The primary checkout's unrelated tracked and untracked changes remain intact. A new detached
clean worktree based on the reviewed HEAD, with a new temporary validation root, was used.
Commits are added to the same PR branch without force push. The PR remains Draft/unmerged;
Stage A is not resumed. Learning Wiki is synchronized only after finalized commits and keeps
adopted main distinct from this unmerged release-preparation work.
