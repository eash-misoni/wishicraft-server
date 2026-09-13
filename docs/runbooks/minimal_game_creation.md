# Minimal Game Creation release gate

**Minimal Game Creation: production deployed, positive CREATE/materialization deferred.**

Explicit GO on `3afa803` authorized the deployment sequence below. No positive CREATE has been
performed; fully production Completed remains pending the first real Game. Preparation notes below
retain their original evidence scope. See the production closeout section for applied results.
[D-105 contract](../reviews/minimal_game_creation.md) owns semantics. D-104 production remains Completed.

## Validation and preflight

Validation results and exact finalized HEAD/CI are recorded in the preparation evidence at handoff.
Local Docker CLI is absent; the existing disposable Linux CI runner executes the pinned itzg image.
The creation scenario traverses the real metadata transaction serializer, first START, same-run
retry, first SWITCH to another synthetic registered Game, normal STOP/restart, and A/B data checks.
AWS/SSM/systemd/mount remain simulated in Docker; this is not production E2E.

Read-only preflight v2 at 2026-09-13 11:43 UTC, root
`wishicraft-minimal-game-preflight-v2-ts5e33rr`: canonical dev profile Account matches stage;
Web/CP/Target UPDATE_COMPLETE, A selected STOPPED/HEALTHY, no current/Lock/running workflow,
3 queues empty, 45 alarms OK, 9 Snapshots, 16 durable provenance items. A/B records match D-104
hashes exactly under its canonical JSON serialization. v1 failed table-name lookup before complete
evidence; its directory is retained and is not a successful preflight result.

The deployed physical environment is the existing **dev stage in production use**. prod YAML remains
unconfigured; do not infer prod IDs or deploy it. Target is `i-04fc0629dc4ea466e` from CloudFormation.
Data EBS is the configured existing volume, not a new per-Game volume. EC2 is stopped, so fresh
filesystem capacity and installed host bytes require approved maintenance start/read-back. Do not
claim stopped-host unknown capacity as zero or as a successful live capacity check.

## Approval scope and sequence

First production write requires explicit approval of the finalized release diff and this sequence.
No internal step creates a new approval boundary within a concrete approved scope. Stop for caller
mismatch, unknown artifacts/owners, unresolved execution, broader IAM or unexpected infrastructure.

1. Recheck canonical STS identity against stage; repeat read-only state/registry/lock/workflow/queue/
   alarm/provenance inventory. Capture deployed templates/configuration and Lambda concurrency.
2. Drain Web/Discord/Admission writes using the existing bounded maintenance method. Confirm no
   active workflow/Lock/SSM before continuing. No new Game, BACKUP or RETENTION deletion is required.
3. Deploy reviewed Target role Games GetItem, with no instance replacement, volume or network change.
4. Maintenance-start only the existing stopped Target. The targeted runtime unit requires an owned
   run, so this is not permission to start Minecraft. Check mount/UUID/EBS, free >=4 GiB, no runtime
   container/listener/systemd job, and the exact stopped receipt. Capture its full JSON without secrets.
5. Build the bounded host upgrade with `python -m wishicraft.game_creation_migration --output <new-root>
   --receipt <verified-receipt.json>`. Verify the receipt's target against the latest completed
   Operation, and the generated three destination/hash/predecessor entries against review.
   The generator reproduces D-098's applied configuration and `c124525` wrapper bytes. Any mismatch
   stops before modification. It does not migrate data or rewrite A/B Game records.
6. Stage the exact bundle at `/var/tmp/wishicraft-game-creation-v1`, then execute its existing
   inactive-only installer. It matches complete predecessor bytes/owner/mode and stopped receipt,
   saves predecessor artifacts under `game-creation-v1`, atomically replaces only the contract and
   wrapper, and creates the absent helper. Resume only absent/canonical/exact-predecessor entries.
   Read back hashes, same receipt, stopped runtime and unchanged A/B/world/owner data.
7. Stop the maintenance EC2 without starting Minecraft; confirm stopped and DNS absent.
8. Deploy exact CP assembly with stage=dev, phase=8, deployment=control-plane, two_games=true,
   reset=true, game_creation=true. Confirm function configuration, narrow IAM, unchanged workflow
   definitions and no replacement resources. Then deploy Web with game_creation=true.
9. Restore captured admission concurrency; perform safe unauthenticated/foreign-origin/old-origin
   rejection and authenticated read-only registry/status checks. Negative authenticated CREATE tests
   must use inputs guaranteed rejected; do not send a valid positive payload by accident.
10. Compare A/B metadata, worlds/generations, EBS attachment, Snapshot/provenance inventory and final
    STOPPED/HEALTHY/no Lock/queues/alarms. Save evidence, commit closeout, CI and Wiki synchronization.

Live diff must use `cdk diff --change-set=false` and exact synthesized assemblies. Diff itself does
not authorize deployment or create a changeset. Runtime files outside CloudFormation are separately
reviewed through the generator/installer; a CDK code diff does not prove host upgrade completion.

## Positive production E2E

Preferred: deploy plus safe negative/read-only E2E, then perform positive CREATE when the user first
wants a real persistent Game. This avoids permanent throwaway test metadata. Local/CI/Docker
validation must pass first. Report production positive CREATE/materialization as **not yet exercised**;
do not label the slice fully production Completed until the agreed closeout conditions are satisfied.

Alternative: the user supplies only real display name, initial numeric seed or random, and RESET
on/off. CREATE registers that real Game, then stops for metadata/Operation read-back and A/B/EC2/
filesystem noninterference checks. CREATE approval does not authorize START. A separate explicit
START/SWITCH can be approved for that target after safe state, known player count zero, no Lock,
and sufficient capacity checks. Never raw-delete a production test Game as cleanup.

## Rollback and loss boundary

No database or world migration is needed. Before registration, restore captured CP/Web/Target
configuration and exact saved host predecessor artifacts only under the same inactive/receipt
checks. Do not restore or replace Data EBS. Unknown deploy result requires read-back before retry.

After registration, use reviewed `create_disabled=true` on CP and Web while retaining
game_creation=true. New CREATE stops; dynamic listing/start/recovery remains available. Keep
metadata/owners/worlds and apply a forward fix. A/B-only rollback would omit dynamic Games from
future backups, so it is not an acceptable post-CREATE rollback. Existing snapshots remain protected.
No DeleteSnapshot, Game delete, unknown data cleanup or rollback of another Game is authorized.

## Repository preparation validation (2026-09-13)

Implementation CI [34755576680](https://github.com/eash-misoni/wishicraft-server/actions/runs/34755576680)
on `5d9d850` passed all three jobs: 1,230 tests, lint/type checks, public Web checks and real Docker.
Docker logs contain both CREATE_FIRST_MATERIALIZED checkpoints and the terminal metadata CREATE /
first START / first SWITCH / retry / STOP / restart / A-B noninterference PASS. The offline restore
source audit additionally removed an A/B-only lookup: historical shared Snapshot recovery now checks
its captured descriptor, including dynamic triggering Games, through real provenance verification.
Final handoff reports the final commit's CI separately; preceding evidence is not relabeled as a
successful run of a later HEAD.

Local Chromium validation passed 11 operations scenarios including CREATE confirmation, duplicate
submit and reload, plus 13 public pages at 3 widths (39 checks) and Foundation browser regression.
Local Docker and shellcheck are unavailable; Docker validation is the Linux CI run, not a local pass.
CP/Web/Target synth and read-only live diffs pass. Changes are 11 CP Lambda functions, 2 Web Lambda
functions and 4 narrow IAM policies; no added/replaced resource. Web has no new Games write grant.
Start gains Games UpdateItem / Locks ConditionCheckItem, two existing readers gain Games GetItem,
and Target gains Games GetItem. Host upgrade is the separate three-file reviewed bundle above.
Existing schema-1 recovery JSON in all three saved shared-v2 Snapshot descriptors still validates.

[Preparation evidence](../evidence/minimal_game_creation_2026-09-13.json) records evidence roots and
limits. No production deployment, Game CREATE, runtime command, filesystem change or Snapshot write
was performed. First production positive CREATE should wait for a real Game the user wants to retain.

## Production deployment closeout (2026-09-13)

The user's GO on `3afa803` accepted D-105 and explicitly deferred valid production CREATE. Target,
Control Plane and Web stacks reached UPDATE_COMPLETE with the reviewed resources. Target changed
only its Games GetItem policy; CP/Web Lambda code and narrow IAM match the approved assemblies.
Live CP workflow definitions are unchanged. Downloaded code from Admission, START, BACKUP, RETENTION
and Web matches eight relevant source modules byte-for-byte, including dynamic registry, initial
materialization, RESET policy and recovery readers. BACKUP creation configuration parses correctly
and matches the unchanged runtime manifest digest.

Bounded maintenance captured and set Web/Discord/Admission concurrency to zero, verified drain,
applied Target IAM and started only existing EC2. Host mount `/srv/minecraft`, XFS UUID and physical
EBS serial matched. Free capacity was 31,289,032,704 bytes. No Minecraft container/listener/runtime
job existed, and service start/exit timestamps were empty. This measurement is maintenance evidence,
not capacity reservation: the future first START/SWITCH must execute its fresh capacity gate.

The exact stopped receipt matched the previous successful SWITCH target and STOP Operation. All
eight predecessor artifacts matched bytes/hash/root ownership/mode. The reviewed generator produced
and the inactive-only installer applied exactly three changes (SHA-256):

| Destination | Applied hash |
|---|---|
| `/etc/wishicraft/runtime-contract.json` | `536d153ab39a449e86f1805542eb5138c37f7c780d8469db42108ed9b556682e` |
| `/usr/local/libexec/wishicraft/operation-v2` | `afa1ba874bd2ca96979524ddf7929894a28db6d4d0025400b193f565db26cd9b` |
| `/usr/local/libexec/wishicraft/initial_game.py` | `4ca7fc75dd1d47b6063c078284ad41d60dd4d9fbfba66db9f7a9ef7401defb54` |

Transport digest, final owner/mode/hash and stopped receipt read-back passed. The successful
installer preserved verified predecessor bytes under its dedicated backup namespace. The complete 920-entry Game tree retained digest
`f2c62614f20c6b18b399a73d0f129d99bb3ab47ac0f36b963c84cb812cf8696c`.
Only A/B directories exist. Compose/runtime.env/manifest, A/B metadata/path/world/generation/seed/
policy, Snapshot and durable provenance were not changed. No Game was created or world materialized.
The instance was normally stopped before CP/Web deployment; DNS remained absent.

DesiredStoppedEc2Running entered ALARM at 12:26:53 UTC during approved maintenance and naturally
returned OK at 12:31:53. The user received its existing notification. Neither alarm policy nor raw
SystemState was changed to hide it. Final read-only postflight at 12:41:14 UTC confirmed STOPPED /
HEALTHY, selected A, revision 45, no current/Lock/running workflow/active SSM, three empty queues,
45 alarms OK, nine identical Snapshots, 16 identical provenance items and exact A/B records.
SystemState's normal observation and observed_at refreshed; all desired/selection/request fields
were unchanged. All three admission concurrency settings returned to their captured UNSET values.

Real Edge OAuth login showed the two Games and Admin CREATE UI. Safe invalid requests verified
CSRF missing/invalid and foreign Origin 403, empty display name/invalid seed/forged actor 400,
unauthenticated 401 and old execute-api 421 with no-store. Every POST payload was intrinsically
invalid; no valid CREATE was sent. Public 13 pages exactly match the integrated Foundation build.
Player denial remains synthetic boundary/CI evidence; Discord roles were not changed for testing.
No cookie, token, OAuth code or browser session was saved to evidence.

The first HTTP comparison used the static guide builder without Foundation's existing manage link;
it was diagnosed and rerun with build_foundation in a new v4 root. A postflight comparator initially
mixed SDK datetime and captured JSON strings; serialized attachment records were identical, and a
new v2 postflight passed. These were evidence-harness corrections, not production code changes.

[Production evidence](../evidence/minimal_game_creation_production_2026-09-13.json) records host
proofs, exact code read-back, negative results and local roots. Baseline CI 34756279204 passed 1,230
tests, lint/type/synth/browser and actual Docker first START/SWITCH, retry, STOP/restart and A/B
noninterference. Docker's AWS/SSM/systemd/mount are stand-ins; production wiring/read-back is separate
from those positive integration results. Final handoff identifies the documentation closeout HEAD
and its CI. Local Docker/shellcheck remain unavailable; CI executes both.

### Future positive E2E and final completion

Ask only display name, numeric seed or random, and RESET on/off when a real Game is needed. Phase A
approves CREATE alone, checks metadata/Operation/stable ID/resolved seed/UNMATERIALIZED/manage list
and A/B/EC2/runtime/filesystem noninterference, then stops. Phase B separately approves START/SWITCH
after exact target, player zero, no Lock, current runtime and fresh capacity checks. Verify first
READY/MATERIALIZED, owner/path/seed, selected/observed identity, heartbeat, STOP/restart and other-Game
noninterference. Only then record fully production Completed. No throwaway Game, raw delete,
retention deletion or Whitelist Management is part of this closeout.
