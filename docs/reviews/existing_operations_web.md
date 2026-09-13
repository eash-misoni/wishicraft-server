# D-104 Existing Operations via Web — release review

Repository implementation under the 2026-09-13 delegation. Production approved at `bfc63c4` on 2026-09-13; execution in progress;
D-101/102/103 and D-096/097/098 remain Accepted. This document does not claim production completion.
The release unit is the existing five operations, not Game Creation or a new Control Plane.

## Architecture and trust

Browser cookie → Web Lambda → exact existing `wc-dev-admission` Lambda → existing
OperationAdmissionService / atomic repository → existing START/STOP/SWITCH/BACKUP/RESET workflows.
The Web Lambda has no business-table writes, State Machine starts, EC2/SSM commands, or Snapshot API.
Browser fields are an exact allowlist. Web identity/display/roles come only from the authenticated
server-side session. The Admission Lambda independently evaluates the shared operation policy using
stage-owned Guild/role configuration and the assertion from its IAM-authorized Web adapter.
That internal assertion is not a browser API; IAM callers able to invoke Admission remain trusted
operator/adapter principals, as in the existing Discord contract.

OAuth now retains the verified user ID, bounded display name, Guild and member roles in WebSessions.
The grant is still revoked before creating a session. No access/refresh token is persisted.
The hard expiry remains 900 seconds; each write rechecks expiry/revocation/policy and authorization.
Role freshness is bounded by that login session, not refreshed by page activity. A role removed during
those 15 minutes may still authorize writes until expiry. No new Bot Token access or Discord API call
on writes is needed. Legacy identity-less sessions can still read status but must log in again for
manage operations. Signing-key rotation and origin/policy fingerprint invalidation retain their contract.

## Canonical operation mapping

`authorization.operation_authorized` is shared with the signed Discord parser and Web/Admission.
UI visibility is only a convenience, never an authority.

| Operation | Player | Admin | Target / confirmation / backend safety |
|---|---|---|---|
| START | yes | yes | Registered ACTIVE catalog Game selected explicitly; same-game convergence allowed, different running Game cannot be stopped by START; fresh existing Reconcile before effects. |
| STOP | yes | yes | No client target. Admission resolves the selected Game; workflow freezes/validates the actual runtime/receipt. Explicit save, normal exit, exact stopped-container removal, EC2 stopped and DNS convergence remain required. |
| SWITCH | no | yes | Explicit destination + `confirmed=true`; one global lease freezes source/destination. Healthy running Game, known zero players, host zero recheck, no EC2 reboot; no automatic switch-back on failure. |
| BACKUP | no | yes | No client target; selected Game admitted under existing contract, stopped/healthy shared Data EBS Snapshot and durable recovery provenance. No per-Game-only promise, no automatic retry with a new Snapshot. |
| RESET | yes | yes | Enabled catalog Game + `confirmed=true` + fixed/new seed. Selected healthy running same Game, observed zero and host recheck, immutable reset plan; capacity/retention/owner-chain checks unchanged. |

Unauthorized member roles are denied; no policy expansion. Details remain in
[D-097](two_game_switch.md), [D-098](game_scoped_reset.md),
[domain/interface](../05_data_and_interface_contracts.md#0-production適用済みruntime契約d-096).
Initial generation is legacy metadata, not Reset count. UI projects original/managed selected world
and registry update time, never an internal world path or Operation ID. RESET explains fixed/new,
current replacement, retention of three previous managed worlds plus the initial anchor, later normal
cleanup, and loss of progress since the last external backup if the shared EBS is lost.
The confirmation screen is a distinct second step; no typed-name policy was added.

## Request identity, concurrency and delivery

The browser creates a UUIDv4 once, persists only the request body in localStorage before POST,
and retains it through timeout/refresh. CSRF/session credentials are never put there.
The server derives `web:SHA256(actor ID | UUID)`; the ID is a deduplication name, not authority.
A deterministic digest of the validated request body binds type, target handle, confirm and seed.
The initial session is recorded as a SHA-256 fingerprint alongside the actor. Actor-bound lookup
continues after re-login, while every attempt requires a currently authorized session and CSRF token.
Different actors cannot read each other's request keys. Internal identity does not leave private storage.

The existing atomic Idempotency/Operation/Lock/Current Operation transaction remains the single
admission point. The same key returns the existing Operation; changed payload/seed is a conflict,
including racing transactions. Admission rechecks Web duplicates before mutable STOP/BACKUP Game
selection so a completed operation cannot move a retry to a new Game. No automatic stale-lock takeover.
The same request can be explicitly retransmitted after read-back finds no record; it keeps the same
key and cannot create a second Operation. An unknown result never enables a new replacement request.
A user starts a new request only after a definitive rejection or terminal result and another confirmation.

Operation v1 already supports `requested_by.source=WEB`. Optional `web_request_digest` and
`web_session_fingerprint` add audit/deduplication evidence; requested_by holds verified display/ID.
No interaction/channel/token is fabricated; Discord fields remain NULL. Existing progress, timestamps,
terminal status and result are authoritative. Admission additionally sets `SystemState.last_operation_id`
in its existing owned transaction so current/recent results remain available after current is cleared.
No index, table migration, Scan, or generic history/idempotency service is introduced.

Discord delivery still filters `source=DISCORD` in the Dynamo stream and checks that source in its
handler. CAS, retries, progress revision/milestones, public message and actor behavior are unchanged.
Web-origin progress is displayed only in manage; cross-channel notifications are out of scope.

## HTTP and CSRF

| Route | Contract |
|---|---|
| GET `/api/capabilities` | Authenticated registry/policy projection + CSRF token. Game keys are opaque deterministic handles resolving only against the canonical catalog. |
| POST `/api/operations` | Exact `{request_id,type,game,confirm,seed}` JSON; 2 KiB bound, no base64 body, server actor, Origin and token mandatory. |
| GET `/api/operations/request/<UUID>` | Authenticated actor-bound lookup through existing Idempotency, then safe terminal-capable Operation projection. |
| GET `/api/operations/current` | Shared current/last admitted operation, readable by authenticated Player/Admin; safe projection, not raw records. |

Responses use schema_version 1. New acceptance is 202 (`outcome=accepted`), duplicate recorded request
200, invalid input 400, authentication 401, authorization/CSRF 403, conflict 409, unsupported capability
422, uncertain write or unavailable read 503. A 202 means admission, never Minecraft success.
PENDING/RUNNING/SUCCEEDED/FAILED/TIMED_OUT/CANCELLED remain distinct. Known precondition/start-failure
codes are projected; arbitrary AWS/Discord errors, workflow ARN, lease, internal IDs and raw result are not.
Read projection failure is unavailable, not success. Exact legacy status semantics remain unchanged.

CSRF is a domain-separated HMAC of the session identity and policy/origin fingerprint using the existing
signing key, checked with constant-time comparison. It is fetched only from the same-origin authenticated
API and sent in `X-CSRF-Token`; POST also requires the exact canonical Origin and JSON content type.
Missing/mismatch/other-session tokens, expired/deleted sessions and foreign forms fail closed.
A stored random synchronizer token would require new session mutation; HMAC provides session binding
without a second persistence protocol. SameSite alone was rejected as insufficient. CSRF is not an
authentication credential or an XSS defense. Existing same-origin logout contract is retained.

Secure/HttpOnly/host-only/SameSite cookies, CSP, private/API no-store and canonical host guard remain.
No CORS configuration is added. Old execute-api API/write/callback requests fail before authentication;
old manage GET redirects to canonical without serving authenticated content.
Polling is single-flight, pauses in background, uses 5 seconds for the pending request and 15 seconds
for current/recent operations. Existing status remains 60 seconds; no workflow completion HTTP wait.

## IAM and infrastructure impact

Web Lambda adds exactly `lambda:InvokeFunction` on `wc-dev-admission`, plus `dynamodb:GetItem` on
`wc-dev-idempotency` with `LeadingKeys=web:*`. Existing GetItem on SystemState/Heartbeat/Operations/Games,
WebSessions and signing-key GetParameter remain. No business Put/Update, wildcard action/resource,
arbitrary invoke/start, Bot Token, OAuth secret on the Web handler, host or Snapshot privilege is added.

CP Admission receives four nonsecret stage-owned authorization configuration values. CP Lambda Code
assets change because existing packaging shares the source directory; this is an expected release diff,
not permission to alter workflow definitions, IAM, tables, Target or Frozen. Web/Auth Code assets change;
Web environment/IAM changes as above. No new resource, data migration, route exposure, DNS/TLS update,
Session TTL change, or recurring provisioned component is needed. Review exact live diff before deploy.

## Cost, E2E and rollback

No additional fixed resource cost. Polling adds request/compute/read usage; 10 active management hours
at 5-second polling is at most 7,200 operation polls plus existing status calls per browser, with session
expiry still requiring re-login. Each recorded request lookup uses Idempotency, Operation, Game and
session reads; record sizes determine actual RRU. Lambda requests are $0.20/million before allowances;
compute, HTTP API, read units/logs and target runtime are separate usage charges.
[Lambda pricing](https://aws.amazon.com/lambda/pricing/),
[API Gateway pricing](https://aws.amazon.com/api-gateway/pricing/),
[DynamoDB on-demand](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html)
were checked on 2026-09-13. The previous low-usage Web $3/month planning allowance is not a hard cap.
Existing Budget remains unchanged. E2E targets at most 60 minutes of the existing target runtime;
stop and investigate unexpected recurring cost rather than add resources.

[Release runbook](../runbooks/existing_operations_web.md) owns approval scope, E2E, rollback and evidence.
First production write is still gated. Real RESET is not needed to prove this adapter: full existing
backend regression + real boundary serializer tests + safe unsupported-capability rejection are used.
No new Snapshot is proposed; 9 existing completed Snapshots include the D-098 recovery evidence.
No Minimal Game Creation, Whitelist, Restore UI, RETENTION deletion, runtime generalization, public
status, WebSocket, arbitrary command or generic workflow work is included.
