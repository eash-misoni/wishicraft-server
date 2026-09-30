# D-115 RETENTION artifact import boundary (repository review candidate)

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

Validation is in progress on this Draft. Linux artifact results must pass before handoff; local
macOS has no Docker and cannot stand in for Python 3.12/Linux qualification. Source tests and
synth success are reported separately. Final CI identities and comparison will be appended after
verification. Canonical retention remains true/false; D-114 remains unchanged.
