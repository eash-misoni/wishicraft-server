# Existing Operations via Web release / rollback

D-104 production Completed on 2026-09-13. Approval baseline `bfc63c4`, final implementation `5dfbf32`.
Base `2d05437` is the preceding read-only Web URL stabilization release. [Review and contract](../reviews/existing_operations_web.md) owns design.

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
- The user's real OAuth login then reached a 503 on manage/capabilities before any operation submit.
  Production session persistence encoded `principal.roles` as a DynamoDB List, while the imported
  Operation decoder did not support Lists. The Web session adapter now uses the existing Web decoder
  that supports that same serializer output. No identity/role/session record or policy is rewritten.
  The HTTP/Admission suite now uses the actual `DynamoSessions` codec for every role/CSRF/idempotency
  case; only AWS transport is synthetic. A new authenticated manage/capabilities/status regression
  reproduced 503 before the fix, then the focused 81 tests passed after it. Fresh full verification
  and immutable assets are retained under `wishicraft-web-session-fix-v3-esjvzas2`.
- Session decoder fix `5baae3a`: **1,200 tests**, lint/format/mypy, both synth/live diff and CI
  **34751723035** all passed. CP→Discord read-back→Web deployment completed; only Code assets changed.
  The existing real OAuth session then successfully read capabilities. CSRF missing/mismatch,
  foreign Origin/form returned 403; forged actor/role fields returned 400; unsupported RESET A
  returned 422 in the Web adapter. Logout returned 303 and replaying that deleted session cookie
  with its old CSRF token returned 401. No RESET Operation or Snapshot was created.
- After a local Chrome problem reported by the user, production browser evidence continued in
  installed Microsoft Edge with a fresh real OAuth login. No cookie/profile was copied. Root
  `wishicraft-web-edge-e2e-v4-8pa8tlxt` preserves UI screenshots and allowlisted responses.
- Web START A succeeded (`op-697ab4c0-a4df-410c-b7e9-46c67345f436`, completed 10:39:46 UTC).
  Initial HTTP result was unknown; the same request read back the sole existing Operation and
  tracked it through terminal success. Actor display was the verified Web user, source WEB,
  actor-bound key and normalized digest matched, Discord interaction/message fields stayed NULL.
  RUNNING/READY, HEALTHY, fresh heartbeat, identity match and known zero players were observed.
- Web SWITCH A→B succeeded at 10:44:42 UTC, then a fresh authoritative zero-player/healthy/no-lock
  check permitted B→A. That second SWITCH returned **202 accepted** before its running progress.
  All transition observations keep player counts unknown until terminal convergence.
- Admission REPORT metadata showed successful calls taking 3.126–3.834 seconds, exceeding Web's
  shared 3-second read timeout during the first two requests. Both unknown outcomes reconciled to
  single Operations without client resubmission. A limited transport correction gives only the
  Admission Lambda client a 10-second read timeout, 2-second connect timeout and no automatic SDK
  retry. It remains below the browser's 15-second request budget and never waits for workflow
  completion. Other AWS reads retain their prior timeouts. Same-request reconciliation is unchanged.
  Focused 41 tests and full **1,201 tests** passed; lint/format/mypy passed after removing an unused
  test-only type-ignore. Production application waits until the approved lifecycle E2E converges.


## Production closeout (2026-09-13)

The approved Existing Operations via Web slice is **Completed**. Minimal Game Creation remains
unstarted. [Sanitized evidence](../evidence/existing_operations_web_2026-09-13.json) records the
four request/Operation/workflow mappings without Discord user IDs, cookies, tokens or raw exceptions.

| Web action | HTTP admission | Terminal result (UTC) |
|---|---|---|
| START A | Unknown → same-request read-back | SUCCEEDED 10:39:46 |
| SWITCH A → B | Unknown → same-request read-back | SUCCEEDED 10:44:42 |
| SWITCH B → A | 202 accepted | SUCCEEDED 10:48:46 |
| STOP A | 202 accepted | SUCCEEDED 10:50:56 |

All four requests mapped to exactly four successful Operations and four successful workflows.
Actor/source, actor-bound idempotency key and normalized payload digest matched; Discord interaction,
channel and message metadata stayed NULL. No client resubmission was needed. Both SWITCH safety
checks observed HEALTHY, READY, fresh heartbeat, known zero players, matching selected/observed Game,
no current Operation and no Lock. B saved normally and A returned through its original data identity.
The browser showed confirmation, acceptance/running/result, progress milestones and terminal success.

RUNNING/transition evidence outstanding from the read-only slice is now recovered: selected vs observed
Game, fresh/stale heartbeat, identity matching, unknown player counts during transitions, known zero
when stable and not-expected after STOP. The server-side session naturally expired during STOP tracking;
an explicit old-cookie write and read returned 401. After the user's fresh OAuth login, the same saved
request read back STOP SUCCEEDED without creating another Operation. Logout/revoked-cookie rejection
was also observed separately before expiry. CSRF/Origin/spoof/capability negatives passed again after
the final code deployment. The E2E browser was logged out and closed at completion.

No real RESET or BACKUP was performed solely for Web route testing. Unsupported RESET A safely
returned 422 at the Web adapter, before shared Admission; downstream production RESET execution is
not claimed. Actual HTTP/session/Admission serializer integration, capability/seed/confirmation/role
cases and existing D-098 backend production evidence cover RESET. BACKUP uses the same tested Admission
wiring and existing backend production evidence; no new Snapshot was justified. Other-session CSRF,
role permutations and command/delivery failure cases use synthetic integration/regression evidence;
no real Discord Guild role or extra identity was created. Discord production smoke was signature-free
request rejection (401) plus deployed code/config and DISCORD-only stream filter read-back; real
slash-command invocations are not claimed. The full command/progress/CAS/retry suites passed in CI.

Final preflight at 10:55 UTC (`wishicraft-web-final-preflight-famd7nr9`): STOPPED/HEALTHY, A selected,
DNS absent, no Lock/current, all 6 workflows idle, all 3 queue depths zero, all 45 alarms OK. Both
complete Game records/world/generation pointers, the Data EBS identity/attachment, all **9 Snapshots**
and **16 BACKUP records/provenance** matched the pre-release baseline. Target/Frozen templates were
unchanged. Expected lifecycle saves and SystemState revisions are the only runtime changes.

Final implementation `5dfbf32` passed **1,201 tests**, lint/format, mypy **185 files**, Web/CP synth,
code-only live diff and CI **34752735303** (all three jobs, including actual Docker and Web browsers).
The final timeout-only correction was applied CP→Discord read-back→Web after all four lifecycle
Operations converged. Templates and Lambda states matched immutable assemblies; no CP IAM, workflow,
schema, Target/Frozen or additional Web privilege change occurred. Final Web IAM read-back confirms
exact Admission invoke and `web:*` conditional GetItem. A new lifecycle run was not added solely to
retest the timeout value: measured Admission latency, configured deadline regression, successful
202 evidence and post-deploy authenticated read/rejection tests define that validation boundary.

No standing resources were added in this slice, no new secret boundary or recurring service cost was
introduced, and Snapshot storage count did not increase. E2E used transient existing EC2/public IPv4
runtime and normal on-demand API requests. Rollback remains Web→prior read-only first, accepted work
converges, then optional CP asset/config rollback; no raw Operation/Lock/Game/world editing or data
migration is required. Rollback was reviewed, not production-executed. No unresolved product decision
remains; role freshness of at most 15 minutes is the explicitly accepted security tradeoff.

Final closeout documentation is committed separately; its GitHub commit checks identify final CI.
Learning Wiki synchronization runs from that finalized HEAD in the primary checkout, without publishing
or committing Wiki output.
