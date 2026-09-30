# D-115 RETENTION artifact import boundary (repository review candidate)

[Draft PR #15](https://github.com/eash-misoni/wishicraft-server/pull/15), unmerged and undeployed.

Base main: `cfc48adfdf5f5ea3edbeb5c0c31302868a6f2bc2`.
Deployed code remains `51fa628179c43c2ca1559077d3b196e9797822e9`.
The [Stage A PARTIAL](retention_disabled_stage_a_2026-09-30.md) and diagnostic
`bbb57cd9-c4c2-4e46-b9a4-05047e98db94` remain historical facts, not successful qualification.
No AWS connection, publication, deployment, Invoke, snapshot or hold operation in this slice.

## Local dependency correction

Previously the handler imported retention_runtime even for DRY_RUN and disabled DELETE_ONE.
Runtime, deletion repository and recovery reader imported maintenance_operator.item, which
loaded local stage configuration and PyYAML. The source-only Lambda asset did not include PyYAML.

The consistent read helper now lives in dynamodb_read; maintenance_operator re-exports the same
function for CLI compatibility. ConsistentRead, missing Item -> empty dict, TypeDeserializer
Decimal values and propagated errors are unchanged. Dispatcher timeout/lease normalization and
all reference/quiescence/pending predicates remain in their original boundaries.

Environment flag validation is in the existing standard-library-only retention_release module.
The disabled handler gate no longer imports runtime binding. Enabled binding, deletion repository
and recovery reader also use the shared helper, so this is not just a diagnostic-only workaround.
No PyYAML, CLI, CDK, dependency bundle, Lambda layer or runtime upgrade is added to deployment.

## Artifact qualification contract

The mandatory `lambda-artifact` CI job synthesizes actual canonical Control Plane and Web
assemblies without validation overrides. The host runner maps each Function's S3Key through its
asset manifest to exactly one staged asset; it does not substitute repository src. Each handler
is imported from its own asset, including separately bundled Discord/Web assets.

The old deployed commit is checked out and synthesized with the same canonical source bundling.
This is a **regenerated predecessor**, not a fresh AWS ZIP download. Both its asset identity and
the current template/asset identities are recorded.

Isolation uses the official Docker Python 3.12 slim Linux/amd64 image, resolved to a registry
digest before building an SDK-only image. SDK versions and wheel hashes come from the boto3
closure in uv.lock, not the full project environment. The final image ID, base digest, Python,
boto3/botocore versions and source paths are evidence. This alternative Linux runtime is not
claimed identical to the managed Lambda runtime or its currently supplied SDK.

Every scenario starts a fresh `python -I -B` process. Only the selected read-only asset, standalone
driver and synthetic JSON are mounted. No repository/tests module, developer venv, user site,
credentials or host environment is passed. Docker network=none, read-only root, dropped
capabilities, non-root user and a socket audit denial block external and metadata communication.
Image/package acquisition happens before these executions; it is not an AWS environment read.
The driver verifies PyYAML, pytest and CDK are unavailable and every loaded Wishicraft module
originates in /asset. No application import is mocked or suppressed.

Host-only fixture export reuses the existing synthetic wire fixtures and emits JSON. The
isolated process cannot import its Python tests or pytest. Raw recovery in this fixture is
synthetic canary data only and is not published as CI evidence; output is fixed status/identity.

Scenarios: old diagnostic reproduces missing yaml; revised false/false and true/false reject
before any SDK client; invalid flags reject; real DRY_RUN Runtime/handler/repositories complete
with only external APIs fake; bound wire record/recovery reader/verify and normal reconciliation
exercise Decimal reads and pending-removal predicates; future true/false and true/true binding
execute call-time imports without sending a deletion; all deployed handlers import their assets.
The existing wider wire-format and safety regressions remain required source-level tests.

## Validation and difference record

Source-level verification: **2,263 full tests**, focused 122 tests, lint, format (411 files),
strict mypy (298 files), and all 12 existing quality-job CLI synth configurations passed locally.
The previous DynamoDB wire/numeric and safety regressions remain included. No Docker is installed
on the local macOS host; Linux artifact qualification ran inside GitHub CI, not on that host.

[Isolation evidence](retention_artifact_isolation_2026-09-30.json), CI run
[36717871652](https://github.com/eash-misoni/wishicraft-server/actions/runs/36717871652), records
**19 successful isolated processes**: predecessor diagnostic, new disabled flags, DRY_RUN,
recovery/reconcile/future binding, and 15 handler imports (13 Control Plane + two Web).
Python 3.12.14 / Linux x86_64, boto3 and botocore 1.43.91 from the SDK-only image.
Base image `python@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f`;
local built image `sha256:bda6940ce3eb7293bfc299d7ac710ae4e0674d3d2d8deb884bcfbc71a7300c99`.
These are container qualification identities, not a read-back of managed Lambda's runtime.

The regenerated predecessor shared asset was exactly
`f3eba1d0d9971f79928f14a10e7a8be37b54a736ab893766e31b2a7eefdde90c`, matching the saved Stage A
asset identity, and reproduced missing yaml with the fixed diagnostic payload. Corrected shared
asset `2b34ff7c33e8d6267edd2418073b0cfa8d13b000de4c99d6d45866e6b8a6a902` returned the exact
NO_DELETE / DELETE_ONE_NOT_RELEASED / false / [] / 0 result before any SDK client construction.
DRY_RUN used a valid zero-inventory synthetic case and real Runtime/Lease/Operation repositories;
only SDK methods were fake. Recovery used real wire decoding, pair lookup, ExecutionReads,
read_recovery and verify; normal explicit-success reconciliation required two observations before
pending removal. No EC2 mutation was sent. Future enabled binding constructed an adapter with
fake clients but did not dispatch. This is import/call-path qualification, not live deletion/IAM.

Initial CI run 36717398066 passed old/new diagnostic and DRY_RUN, then failed its final origin
assertion after recovery because a resource namespace has no __file__. The harness was corrected
to require every namespace search location inside the selected asset. It did not relax recovery
or application safety checks, hide a failure or modify the old result. The successful follow-up
record is separate. Final Draft HEAD CI is linked in the PR/handoff; documentation-only updates
do not alter the recorded Code assets.

[Canonical synth/package comparison](retention_artifact_synth_2026-09-30.json): Control Plane
13 Lambda Code properties and Web two Lambda Code properties change. All other deployable
Properties, resource identities, six workflow raw definitions, IAM, alarms, schedules and flags
are identical. Baseline main's src/infrastructure/config/dependency tree is identical to the
saved deployed-commit assembly; that equivalence is checked separately from artifact loading.
The three assets change only seven Wishicraft source paths (one new shared helper); all external
dependency files are unchanged. No runtime dependency, layer, SDK or PyYAML is added to deployment.

Canonical retention remains true/false and D-114 true/true unchanged. The PR is Draft/unmerged.
The deployed import failure remains until a separately approved corrected Code release and
at-most-one disabled-gate qualification; no Stage B, snapshot deletion or live recovery is qualified.

## Approved deployment continuation: qualified assembly preservation

PR #15 was normally merged as `e7af67980d2243c080c94ded5aec1af4a0eb8cb5`, with the
reviewed/synthetic/actual tree `dce2416c0b31f1a1c4e95fa899e48502f9f894bb`.
The user subsequently approved Code deployment, disabled-gate qualification and formal
RETENTION DRY_RUN; the earlier unmerged/undeployed statements describe that slice only.

The local shared source asset matches CI exactly, but separately bundled Discord assets have
different identities. The local bundle includes an installer-generated cffi command with the
local Python shebang; local uv 0.12.0 also differs from CI 0.12.21. This is not evidence that the
entire bundles are equivalent. No unqualified bundle has been published by this continuation.

The artifact job now preserves its exact canonical Control Plane assembly **after all isolated
probes pass**, as a tar archive (including modes/hidden files), with a SHA-256 transport checksum.
A release can download the actual merge's artifact, verify its checksum and manifest/Code
identities against that run's isolation evidence, and deploy that immutable assembly. This
avoids regenerating a different bundle on the operator's host. No source/dependency/flag/IAM
change or template editing is involved. It is an assembly generated in a clean CI checkout at
the finalized commit with canonical stage configuration, without validation overrides.
The archive is a build artifact, not an AWS response or live environment dump. CI has no AWS
credentials; qualification and archive creation neither publish assets nor deploy a stack.
