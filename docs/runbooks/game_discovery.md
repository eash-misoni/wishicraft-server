# Registry-backed discovery release and operation

Canonical design: [D-112](../reviews/game_discovery.md). Target: existing dev stack/Guild only.
No Game creation, START, SWITCH, RESET, host or Data/Target changes are part of qualification.

1. Check tools/auth and canonical caller account. Capture Games/SystemState, Lambda config,
   alarms, queues, deployed templates and all workflow definitions in a new temporary root.
2. Run unit/integration/full tests, lint/format/type, current-feature CP/Web synth; inspect
   no IAM/resource/monitoring changes. Commit/push and require standard/Paper/NeoForge CI.
3. Create fresh CP and Web ChangeSets. Existing Lambda Code only; allow the five explicitly
   reviewed Case D Definition no-ops only after original Properties, resolved/live ASL,
   physical identities and evaluated change details match. Reject replacement, unrelated
   changes, IAM, auth/OAuth semantics and Target/Data stack changes.
4. Apply the [Case D guard](ssm_ready_probe.md#case-d-release-guard--explicit-dependency-propagated-semantic-no-op).
   Capture/temporarily close ingress using its existing reserved-concurrency controls;
   verify no Current/Lock/workflow, queues empty, EC2 STOPPED/System STOPPED/HEALTHY.
   Execute only the reviewed ChangeSets, read back, then restore exact prior concurrency.
5. D-084 command update is separate from AWS deployment. Render and read back first:

```sh
tools/dev-env run -- python -m wishicraft.discovery_operator render
tools/dev-env run -- python -m wishicraft.discovery_operator status --stage dev \
  --profile wishicraft-dev --evidence "$DISCOVERY_EVIDENCE/discord-before.json"
```

Review the recorded command ID/digest and candidate patch. Only the three Game options
change choices→autocomplete; descriptions/required/permissions/scope stay identical.
Then use that actual reviewed ID/digest (never invent values):

```sh
tools/dev-env run -- python -m wishicraft.discovery_operator update --stage dev \
  --profile wishicraft-dev --expected-command-id "$REVIEWED_COMMAND_ID" \
  --expected-definition-sha256 "$REVIEWED_DEFINITION_SHA256" \
  --evidence "$DISCOVERY_EVIDENCE/discord-update.json"
```

The tool reads Bot Token only in memory from its canonical SecureString, requires global
commands 0, PATCHes the existing ID, verifies read-back and saves public before/after evidence.
A changed predecessor stops before mutation. Never delete/recreate or bulk overwrite commands.
An uncertain update is followed by read-only status before any retry.

6. Verify actual registry-derived START/SWITCH/RESET candidates, name/ID search and public
   guide HTML/browser. Signed fixture tests prove ingress routing; distinguish these from
   actual human Discord picker interaction. Never fabricate Discord signatures or use a
   normal user token to automate the client. No throwaway production Game is required.
7. Compare Games unchanged, System lifecycle/maintenance intent unchanged, no active
   operation/lock/workflow, queues empty, alarms OK and no new Lambda/discovery error logs.
   Commit safe evidence and docs, final CI, clean HEAD=origin/main, then learning Wiki sync.

## Future CREATE and failure

A valid ACTIVE CREATE record automatically appears on the next picker request/page reload;
no code deploy, Discord registration or `web/games.yaml` edit. Package additions themselves
still require the existing reviewed immutable package release; discovery does not relax it.
Same names get disambiguated labels. RESET-disabled/imported/unmaterialized Games never become
RESET suggestions. Suggestions are not authorization and execution always validates again.

Registry outages show empty Discord suggestions and Web 503/reload. Investigate existing logs
and data/API availability; do not restore static A/B lists or write registry rows by hand.
If rollback is needed, first review restoring the saved prior command options on the same ID,
then restore reviewed prior Lambda assets with fresh ChangeSets. Preserve Games and maintenance
state; a known listing regression is not grounds for deleting Games or recreating commands.

## Qualification / deployment evidence

Repository verification: full local suite 1,686 passed; subsequent focused discovery/parser
suite 63 passed, including the added legacy+dynamic membership regression. Ruff check/format
and mypy (235 source files) passed. Current-feature CP/Web synth passed; local template
comparison found unchanged resource sets (138 CP, 26 Web), only 11 CP and 2 Web/Auth Lambda
Code differences. No IAM/environment/alarm/workflow Properties changes. Initial sandbox
bundling failures were network failures; a Web synth invocation with CP-only reset context
was rejected before synth and corrected with the Web-specific contexts.

Read-only preflight: dev STOPPED/HEALTHY, five ACTIVE/MATERIALIZED Games, 49 alarms OK.
Actual legacy names are Wishicraft Vanilla / Wishicraft Vanilla B. Existing Guild command
ID `1544004156543737876`, global commands 0; canonical candidate changes only Game options.

## Dev functional release — 2026-09-22

Implementation `e89132f3ad835a32df2b110a49c6f21543ed2340` passed
[standard CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35723371142),
[Paper CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35723371150), and
[NeoForge CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/35723371131).
CI ran 1,687 tests, lint/format/type, current-feature synth and the real browser/runtime
integration jobs. Local Chrome 153.0.8010.53 guide validation also passed.

Fresh `discovery-cp-e89132f` / `discovery-web-e89132f` ChangeSets were reviewed and executed.
CP: 11 existing Lambda Code updates plus the five permitted dependency-propagated Definition
updates; Web: two existing Lambda Code updates. Resource sets, all IAM, SNS/alarm settings,
Lambda environments and all six workflow ASL semantics/configuration/identities are unchanged.
Read-back verified deployed source bytes in the actual Discord/Web ZIPs. No Target/Data stack,
Game/host/lifecycle action, new resource, auth/OAuth semantic change or permission expansion.

D-084 PATCH preserved command ID `1544004156543737876`. Names, Japanese descriptions,
option types/required, permissions and Guild scope are unchanged; global 0 before/after.
Only Game choices on START/SWITCH/RESET became autocomplete. Seed choices are unchanged.

| Real registry projection | Actual eligible names |
|---|---|
| START / SWITCH | create-survival, create-terralith, vps-survival, Wishicraft Vanilla, Wishicraft Vanilla B |
| RESET | Wishicraft Vanilla B only |
| Search `terr` / `vps` | create-terralith / vps-survival |

The live public guide changed from two Vanilla entries to these five. Actual Chrome verified
1440/390/320px, JS disabled, HTTP 200/no-store, all runtime versions and no overflow/private
identifiers. Future existing-package CREATE is covered by repeated-request fixtures; no test
Game was created. Human Discord picker interaction is **not observed by the agent**; signed
routing fixtures, deployed-source verification and live registry projection are not labelled
as a real Discord client E2E. The user has been asked to verify without submitting commands.

Safety snapshot at 12:10:17 UTC: five Game records byte-equivalent to before, unchanged
maintenance record, STOPPED/HEALTHY, EC2 stopped, DNS absent, no Current/Lock/workflow/SSM,
49 alarms OK, three queues empty, Lambda Errors sum 0 and discovery unavailable logs 0.
Original three ingress concurrency settings restored to UNSET. Metrics are observations
within the recorded window, not a promise that no future errors can occur.

[Machine-readable evidence and qualified limits](../evidence/game_discovery_2026-09-22.json).
Initial review/guard/read-back harness failures remain separate evidence; they were corrected
without relaxing safety predicates. One pre-execution comparison stopped on Decimal-vs-string
serialization; ingress was restored before retry. Raw AttributeValues proved maintenance
unchanged. Post-deployment SDK SSO refresh expired, while canonical CLI credentials remained
valid; caller was reverified, ingress restored through CLI and standard SDK credential_process
reused that provider. No secrets were written to files/logs or permissions changed.

A final guide-copy cleanup removes implementation language from the public page and describes
reload behavior for readers. This does not change discovery logic or the command contract;
its Web-only asset release uses a fresh Code-only ChangeSet and the same CI checks.


## Empty-picker cold-start follow-up (2026-09-22)

The user reported empty choices after the initial release. Pre-release signed tests,
registration read-back and operator projection are insufficient evidence of actual Discord
picker delivery. Three cold Lambda executions exceeded the three-second response limit;
the following warm execution took 301 ms. See the design's cold-start follow-up.

The correction initializes and reuses the read-only SDK client during Lambda INIT, without
caching Game membership. Repeat full qualification, fresh Case D ChangeSets and deployed
read-back. Observe `discord-autocomplete` safe structured logs and Lambda REPORT together:
`result=ok`/counts alone do not prove Discord accepted a late response. Check INIT plus
Duration against the end-to-end deadline and obtain user picker confirmation. No Game
command needs to be submitted and command registration must remain unchanged.


Correction `3380515d1a655ca664ff4c8ff9c68b20ed262604` passed 1,689 CI tests, lint/format/type,
standard CI [35727961766](https://github.com/eash-misoni/wishicraft-server/actions/runs/35727961766),
Paper [35727961803](https://github.com/eash-misoni/wishicraft-server/actions/runs/35727961803),
and NeoForge [35727961622](https://github.com/eash-misoni/wishicraft-server/actions/runs/35727961622).
Fresh `discovery-cold-cp-20260922` / `discovery-cold-web-20260922` ChangeSets passed Case D
review and completed. Source ZIPs, all unchanged Lambda configuration and all six workflow
ASL definitions were read back; ingress returned to its exact prior UNSET configuration.
The earlier pending guide-copy ChangeSet is no longer present after the replacement release.

A deliberately unsigned request was rejected with 401, without authorized Game reads or
mutation. Its Lambda INIT was 603 ms and invocation 2.09 ms. This demonstrates the static
initialization path, **not successful autocomplete delivery**. The first timing harness
incorrectly matched Billed Duration; v2 corrected the parser and reread the same REPORT
without overwriting the original evidence. At the recorded checkpoint, no post-fix signed
picker request had arrived; user confirmation was requested and remains distinct from these
server-side checks. Do not declare the original empty-picker report resolved solely from
this negative authentication probe.

Actual public guide browser checks again passed at desktop/mobile/narrow widths with all
five Games, HTTP 200, no-store and JavaScript disabled. Complete Discord command definition
still matches the initial update exactly (ID `1544004156543737876`, global 0); no second
registration was needed. Final audit: STOPPED/HEALTHY, EC2 stopped, Games and maintenance
unchanged, 49 alarms OK, three queues empty, Lambda errors and discovery failures zero in
the post-release audit window. No resource/IAM/lifecycle/auth change.

[Correction evidence, measurements and observation limits](../evidence/game_discovery_cold_start_2026-09-22.json).


### Actual Discord picker confirmation after correction

After the preceding checkpoint, the user confirmed in the real operation channel (without
submitting a lifecycle command): **START showed five Games; RESET showed only Wishicraft
Vanilla B**. The corresponding signed requests logged START count 5 three times and RESET
count 1 once, all `result=ok`. Lambda execution durations were 347.45, 112.81, 101.24 ms
(START) and 108.33 ms (RESET); discovery itself took 319, 92, 99 and 88 ms respectively.
This closes the user-reported empty-picker symptom for START/RESET.

These positive requests reused the environment initialized by the earlier negative probe.
Therefore a positive cold request's full end-to-end latency was not directly measured; INIT
603 ms and the positive request measurements are separate evidence. SWITCH's actual client
picker was not reported; its eligibility/search/routing are covered by the same registry
projection and signed tests. No ordinary START, SWITCH or RESET was submitted.
