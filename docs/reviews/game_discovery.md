# D-112 Registry-backed Game discovery

Accepted scope, 2026-09-22. Implements DIS-001/002/003/007/008 and D-084/D-105 discovery.
Dev discovery and the empty-picker cold-start correction are deployed and read-back verified.
Actual post-fix Discord picker delivery remains a separate user observation, not inferred
from SDK/read-back tests. See the cold-start follow-up evidence below.
Repository qualification and deployment evidence are recorded separately in the
[release runbook](../runbooks/game_discovery.md).

## Authority and consumers

Games records are authoritative. Reuse D-105 `registry-game-creation-v1.registered_ids`
plus the existing legacy catalog membership, then consistent GetItem of every Game.
A missing registry item means no CREATE registrations under the existing contract; an
AWS read failure never means legacy-only success. Missing/deleted/inactive records are
excluded. No scan, table, persistent cache or business write is introduced.

The shared reader requires ACTIVE, a valid registered name/identity, known materialization
state (UNMATERIALIZED, MATERIALIZED or MATERIALIZATION_FAILED), and a deployed package
reference. Dynamic records must retain an exact immutable package definition and digest.
Public metadata is deliberately restricted to name, package kind, Minecraft version and
RESET availability. No Game seed, actor, creation provenance, paths, connection details,
AWS identifiers, status/player observation or full Game record is exposed.
There is currently no hidden/internal visibility field. ACTIVE valid records are public by
this explicit user-approved contract; a future visibility field requires updating this filter.

Package versions resolve through `artifacts/game-packages.json` and immutable Game package
metadata, sharing the existing package selector. No second runtime mapping is created.
Vanilla 26.2, NeoForge 1.21.1 and Paper 26.1.2 remain pinned and unmodified.

Names are not unique (D-105). Use the registered display name; only collisions receive a
shortest unique Game suffix (at least eight characters), keeping Discord labels within
100 characters. Discord choice values remain canonical IDs. Public HTML escapes all names.

## Discord

The existing signed interaction Lambda accepts type 4 autocomplete and returns type 8.
Game options on start/switch/reset have `autocomplete=true`, no fixed choices. Command
names, descriptions, option names/types/required, Guild scope and permissions remain unchanged.
Seed fixed/new choices are unchanged. Registration is an explicit D-084 same-ID PATCH;
no create, delete, global registration or bulk overwrite occurs.

Signature, application, Guild, operation channel and operation role checks remain required.
START/RESET are Player/Admin; SWITCH is Admin. Unauthorized autocomplete returns no choices.
Partial nonfocused options may be absent; execution confirmation/seed are not demanded while
selecting. Malformed inputs are rejected. Autocomplete never defers, admits an Operation,
posts a message or touches lifecycle state.

| Command | Discovery eligibility | Execution authority |
|---|---|---|
| START | All valid ACTIVE registered Games | Existing fresh registry, Admission ACTIVE transaction and runtime checks |
| SWITCH | Same destinations as START; current Game not removed | Existing source/destination, zero players, confirmation and workflow checks |
| RESET | Above plus MATERIALIZED and valid non-null reset policy; import excluded | Existing configured policy, selected/running Game, seed/confirmation and safety checks |

Autocomplete eligibility describes the Game, not whether the whole system can execute now.
Maintenance, lock, current Game and other global conditions remain execution-time authority.
Name/ID case-insensitive contains search; exact, prefix, contains then casefolded name/ID order;
maximum 25. Every request rereads registry and records; no membership cache or re-registration.
Reads have a 1.8-second application budget and bounded SDK connect/read timeouts, zero retries.
Failure returns empty choices with a safe structured failure log; no A/B fallback or admission.
Existing execution parser/Admission and Lambda monitoring behavior are preserved.

### Cold-start follow-up

The first live picker test returned empty results. CloudWatch recorded three cold requests
at 3,097–3,157 ms plus 205–226 ms INIT, versus 301 ms for a warm request; one request logged
`unavailable`. Signed local tests and registry projection had not exercised Lambda cold-start
latency and therefore did not qualify actual picker behavior. The user report supersedes
any earlier functional-release qualification for Discord.

Initialize the SDK/service model and read-only reader during Lambda INIT, reusing only its
connection and immutable deployment configuration. No registry or Game read occurs until
signature/authorization succeeds; every autocomplete still rereads current records. Failed
initialization is contained and retried on a later autocomplete request. No provisioned
concurrency, memory increase, extra resource, permission or command update is introduced.
Safe result/count/duration and coarse failure-reason logs omit tokens, user identities,
queries, exception messages and Game records. Cold and warm actual response measurements,
including INIT plus execution, are required before closing this follow-up.

AWS recommends [initializing SDK clients outside handlers](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html).
Moving work to INIT does not exempt it from Discord's end-to-end deadline; live latency must
still be checked, and a failed measurement must not be called success.

Official specifications: [application commands](https://docs.discord.com/developers/interactions/application-commands),
[interaction responses](https://docs.discord.com/developers/interactions/receiving-and-responding).
Discord requires an initial response within three seconds, limits suggestions to 25 and
forbids combining choices with autocomplete. Suggestions do not constrain final user input.

## Public guide

Existing Web Lambda renders the `/games/` (also `/games/index.html`) listing on each GET,
using the shared reader and existing Games GetItem permission. No extra endpoint, API,
Lambda, IAM action, secret retrieval or authentication is needed. HTML is read-only,
login-free, no-store, JavaScript-independent. CREATE appears on the next request. A failed
read produces HTTP 503 with a reload link; offline static build likewise contains no
purported current A/B list. Existing CSP/OAuth/session boundaries remain unchanged.

Legacy authored detail pages are reference guidance, explicitly linked as such. They are
not the current Game inventory. Command pages point to the live list and Discord picker;
legacy command strings remain concrete examples, not a complete list.
This supersedes D-100/D-102/D-105's former explicit-publication requirement **for these
minimal list fields**. Authenticated management metadata and authored client instructions
retain their separate boundaries. CREATE itself, registry schema and package authority do
not change.

## Fixed-assumption inventory

| Location | Finding / disposition |
|---|---|
| `two_game_admin.declaration` | START/SWITCH legacy choices. Retained as migration predecessor; current D-084 artifact passes through `discovery_commands.autocomplete`. |
| `reset_commands.extend` | RESET legacy choices. Retained as predecessor; current artifact removes only Game choices. |
| `web/canonical.py` | A/B stage projection now only for authored reference pages/examples; command schema uses autocomplete. |
| `web/games.yaml`, `web/build.py` listings | Former public inventory. YAML retained for reference page content/routes; current list uses runtime registry slot. |
| command pages `supported-games` | Former A/B complete list replaced by live-list/picker guidance. |
| `config/two-game-dev.json`, project initial Game | Legacy membership/bootstrap, required by current registry contract; not sole discovery authority. |
| `config/reset-dev.json` | Legacy per-Game RESET policy; dynamic policy comes from Game creation metadata. |
| Discord execution `configured_catalog`, `reset_policy.configured` | Already dynamically registry-backed; retained, not replaced by autocomplete. |
| Admin Web `Operations.game_ids`, status selected/observed Game | Already registry/GetItem-backed; no extra consumer fix needed. |
| two-game/reset/runtime-memory/catalog/package/heartbeat migration tools | Exact predecessor identities and history, intentionally retained. |
| historical fixtures, backup/manifest legacy members | Compatibility/regressions, not user listing; no lifecycle or backup scope expansion. |

No new resource/IAM/lifecycle/maintenance changes. Shared source assets may update existing
Lambda code and propagate five known semantic-no-op State Machine Definition dependencies;
Case D review, fresh ChangeSets and exact deployed ASL equality are mandatory.

Cold-start correction release: [dev evidence and limits](../evidence/game_discovery_cold_start_2026-09-22.json).
