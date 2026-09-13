# Existing Operations via Web release / rollback

D-104 production release approved at `bfc63c4` on 2026-09-13; execution in progress.
Base `2d05437` remains the last completed
Web URL stabilization release. [Review and contract](../reviews/existing_operations_web.md) owns design.

## Local verification

```sh
tools/dev-env check
tools/dev-env run -- uv run python -m web.local --scenario stopped
# Other synthetic scenarios: players, conflict, rejection, failure, player-role.
tools/dev-env run -- node web/operations-browser.mjs --chrome
```

Loopback only. Fake OAuth and in-memory Dynamo/workflow are outside the production asset and have no
production environment toggle. Every invocation creates a new temporary root. Browser tests exercise
all five operations, confirmation, unsupported RESET, role-based visibility, duplicate click, page
refresh, terminal success/failure and rejection. Fake workflow outcomes are not real host evidence.
The HTTP integration suite uses the real Admission Lambda parser, canonical authorization, domain
Admission transaction serializer, duplicate lookup and safe read projection; launcher effects are mocked.
Existing workflow/host/Discord suites remain necessary regressions.

## Read-only preflight

2026-09-13: canonical `wishicraft-dev` STS Account `385526546525` matches dev YAML; origin/main and local
base HEAD match. Web/CP/Target stacks UPDATE_COMPLETE; Frozen CREATE_COMPLETE. Selected A, Desired
STOPPED, HEALTHY, Target stopped, current Operation absent and Lock absent. Both registry Games ACTIVE;
A uses original world, B retains D-098 managed current world. All 9 existing Data EBS Snapshots completed.
Root: `wishicraft-web-operations-preflight-v1-qaa8zi_c`. No secret value was retrieved.

## Approved release scope (2026-09-13)

Approval covers only this finalized reviewed release, its bounded normal corrections and closeout:

1. Recheck canonical caller, CI commit, stopped/healthy state and no Operation/Lock. Record baseline
   exact Game/world references, existing Snapshots/provenance, Data EBS attachment and stack templates.
2. Create fresh immutable Web and CP assemblies from finalized HEAD. Contexts are `stage=dev phase=8`,
   Web `deployment=web`, CP `deployment=control-plane two_games=true reset=true`.
   Run `cdk diff --change-set=false` with the canonical profile. No changeset creation in preflight.
3. Deploy **only** `WishicraftControlPlaneStack-dev` first (reviewed code + Admission role config), verify Discord ingress/delivery/config read-back, then
   **only** `WishicraftWebStack-dev` (reviewed Web/Auth code, exact invoke/read IAM and configuration).
   Do not use `--all`, deploy Target/Frozen, register Discord commands, or modify Guild/OAuth/secrets.
4. Read back deployed template, code/config, IAM, API routes, canonical guard and alarms. Unknown deploy
   result requires stack-event diagnosis; do not blindly retry or roll back an unobserved transition.
5. Establish real Discord OAuth in a controlled browser. The user may need to perform the actual login;
   no session cookie/token/code is copied into chat, logs, fixtures or an evidence file. Keep browser
   credentials in its session; never fabricate a Web session/actor using AWS writes for E2E.
6. Through the actual authenticated Web UI: START A; observe acceptance, progress, RUNNING/heartbeat,
   player semantics and selected/observed Game. Do not manufacture duplicate submissions; natural
   timeout/retry uses the same request identity and read-back. Recheck fresh healthy/zero-player
   safety conditions before SWITCH A→B and B→A; stop if those conditions fail. Finally Web STOP A
   and verify terminal convergence.
   A pending Operation must finish before the next request. This is normal existing lifecycle use;
   do not connect a real Minecraft player or run a separate long E2E.
7. Safe RESET check uses A/non-supported capability rejection only (no world mutation). The current
   Web adapter rejects this capability before shared Admission; do not claim downstream execution. BACKUP has
   repository integration and existing production backend proof; do not create a new Snapshot solely
   for route coverage. Real RESET, Snapshot/world deletion and recovery edits are not in this approval.
8. Check public 13-page guide, unauthorized/API/old-host guard, auth/logout/session, private projection
   nonleakage, single Operation/workflow per request, Web delivery absent, and Discord stream source
   filter unchanged. Use repository/CI for role permutations and Discord command/progress CAS regression;
   do not change real Guild roles or invoke RESET via Discord for a regression test.
9. Final stopped/healthy, A selected, no Lock/current/running execution, DNS absent, original data
   attachment/world references and 9 Snapshots retained. Verify alarm/queue health and record sanitized
   evidence. Include transition/RUNNING observation at actual event checkpoints, not inferred success.
10. Commit closeout docs/evidence, verify CI and local/origin/remote match, run the learning Wiki skill
    on finalized HEAD in the primary checkout, leave working tree clean. Completed only after this E2E.

Normal test fixes, fresh evidence roots, exact reviewed IAM/code corrections, and deployment retries
with a known non-ambiguous result do not introduce new approval gates. Stop for auth/CSRF bypass,
duplicate operation, spoofing/leak, new secret/broad IAM, weaker safety/authorization, unexpected
CP/Target/Frozen changes, undeclared deletion/RESET, ambiguous deploy, irreversible migration or
unexpected recurring cost.

## Rollback

First stop new Web submissions by returning the Web stack to the previous successful `2d05437` Web
assembly. Keep the new CP code while admitted work converges; do not roll back a running workflow.
Read back current Operation/execution/Lock before any next action. After no admitted work remains,
CP may return to its recorded pre-release template/assets using the approved exact stack deployment.
Optional added fields are backward compatible; never delete Operation/Idempotency/history or rewrite
Game/world/Desired/Lock to make rollback appear successful. Existing terminal Web records survive;
read-only legacy Web simply does not present their request API. No data migration needs reversal.
Signing-key rotation/session revocation is an incident action, not a routine rollback requirement.

## Validation checkpoints

- Focused pre-existing Web/Admission/Discord suites: 133 passed.
- New real HTTP/Admission/serializer/security suite: 39 passed.
- Real Chrome Foundation 6-state regression successful: `wishicraft-foundation-browser-P5V2EY`.
- Real Chrome five-operation + failure/role/confirmation scenarios successful:
  `wishicraft-operations-browser-wG1McQ` (10 scenarios, mobile/desktop).
- Initial full run: 5 failures/47 setup errors from existing Discord dependency network/bundling;
  1,147 tests passed. Root `wishicraft-web-operations-validation-v1-bq142msi`.
  Lint/format/mypy passed. CP synth v1 failed on that same dependency acquisition; Web synth passed.
  Official hash-locked `tools/setup-dev-tools bundling-cache` then succeeded; v2 verification follows.
- Full validation, CI and exact live diff are recorded below before readiness. No production write yet.

### Repository validation and live diff

- v2 full suite **1,199 passed** (67.33 seconds), Ruff lint/format and mypy **185 source files** passed.
  Web and current two-Game + RESET CP synth passed. Root `wishicraft-web-operations-validation-v2-2u29nyh8`.
- Public guide real Chrome **13 pages × 3 viewports**, links/copy/keyboard/reload successful,
  no overflow or console errors: `wishicraft-web-browser-H5yslr`.
- `cdk diff --change-set=false` succeeded for both exact Web and CP assemblies. Root
  `wishicraft-web-operations-live-diff-v1-xy5uzjlg`. Web: Web/Auth Code, Web environment and exact IAM
  policy additions only (3 resources modified). CP: 11 Lambda Code assets, Admission environment
  only. No resources added/removed; no State Machine definition, CP IAM, table, Target or Frozen change.
- Safety preflight v1 had only the first CloudFormation resource page. A separate v2 root used full
  pagination: all **6 workflows have 0 running executions**, 3 queues have visible/inflight/delayed 0,
  **45 alarms OK**. Root `wishicraft-web-operations-safety-preflight-v2-xts6hxf2`.
  Earlier attachment read confirms encrypted 30 GiB Data EBS attached to the existing Target,
  `DeleteOnTermination=false`; Admission and Discord ingress concurrency both UNSET.
- Local Docker CLI is absent; actual Docker regression runs in CI. No local Docker test is claimed.
  CI must succeed on finalized repository HEAD before production approval readiness.

### Approved production execution checkpoints

- User GO at `bfc63c4` on 2026-09-13 accepts the 15-minute role snapshot tradeoff and exact
  START A → SWITCH B → SWITCH A → STOP E2E. No real RESET or new Snapshot/BACKUP is authorized.
- Fresh baseline at 09:58 UTC: correct caller/account/region; STOPPED/HEALTHY, no Lock/current,
  6 workflows idle, 3 queues empty, 45 alarms OK, 9 completed Snapshots, 16 BACKUP records.
  Game/world records and backup provenance retained in isolated evidence root
  `wishicraft-web-release-v1-a_vis9ee`.
- CP first deployment completed; deployed template exactly matches the approved assembly, all
  11 Lambdas Active/Successful. Discord signature-free ingress returns 401; DISCORD-only progress
  stream filter remains Enabled. Real slash-command invocation is not claimed by this smoke.
- Web deployment completed; deployed template matches its assembly. Public/read-only/unauthenticated
  and old-host security checks pass. No Game lifecycle request has been submitted at this checkpoint.
- Direct IAM read-back caught an incorrect Lambda ARN separator (`function/` instead of `function:`).
  The previous synth assertion checked the function name but missed ARN syntax. This is a denied
  invoke configuration, not expanded authority. A bounded correction uses `COLON_RESOURCE_NAME`,
  and the regression assertion now checks the complete synthesized ARN. The corrected deployment
  remains restricted to the single existing Admission function. Full validation/CI and fresh diff
  precede that correction. Evidence root `wishicraft-web-release-invoke-fix-v2-jtliy_13` preserves
  the correction separately; initial failed verification is not relabelled as successful.

- ARN correction committed as `0e70cf9`; full **1,199 tests** passed (71.02 seconds), Ruff lint/format,
  mypy **185 files**, Web synth and single-policy live diff passed. CI **34751123815** succeeded in
  all three jobs, including actual Docker and Web browser scenarios.
- Corrected Web deployment completed around 10:14 UTC. Deployed template exactly matches the corrected
  assembly; IAM GetRolePolicy confirms `arn:aws:lambda:ap-northeast-1:385526546525:function:wc-dev-admission`
  and only the existing `web:*` conditional Idempotency GetItem. Web/Auth code was unchanged by this fix.
- Canonical public guide **13 routes** returned 200 with no raw internal identity markers. An initial
  test used the standalone fixture `/guide/` prefix and correctly received 404; the corrected v2
  check uses production root routes. No public routing change was needed.
- Real OAuth E2E is awaiting the user's login in the controlled headed browser. No production Web
  lifecycle Operation, RESET or BACKUP has been submitted. Do not mark this slice Completed or claim
  RUNNING/transition evidence until the approved START/SWITCH/SWITCH/STOP run is actually observed.
