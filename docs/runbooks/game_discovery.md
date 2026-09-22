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
No live deployment or Discord mutation has yet been claimed by this document.
