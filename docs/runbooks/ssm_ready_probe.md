# SSM READY probe execution boundary

> 2026-09-18 production: the Game-authority and stdin-import corrections are deployed.
> `create-survival` completed START → READY → ordinary scheduled Reconcile → MATERIALIZED
> → normal STOP using its existing world (generation 1). The explicitly approved Case D
> release retained all State Machine semantic identities. A separate runtime-heartbeat
> monitoring inconsistency was observed after READY; ingress remains closed and no further
> START/fix was attempted. See the production closeout below; earlier release holds are historical.

Scope: D-109 observation transport fix and the existing create-survival prepared
world's first successful formal START/READY/materialization/STOP. Production
qualification below is separate from repository qualification. No new CREATE,
world regeneration, package/version change, timeout extension or relaxed READY.

## Root cause and minimal correction

Control Plane previously transported the exact packaged probe through
`printf ... | base64 --decode | python3 -`. The probe imports the Game package
observer from the repository when available, otherwise the installed adjacent
`game_package.py`. Direct installed helper execution supplies its script directory;
stdin execution supplies the shell working directory instead. Repository-import
unit/Docker tests did not cover that shell boundary.

Read-only production maintenance on 2026-09-18 measured root (uid 0), cwd `/usr/bin`,
`/usr/bin/python3`, Python 3.9.25, unset PYTHONPATH/PYTHONHOME. sys.path was the empty
entry (cwd), `/usr/lib64/python39.zip`, `/usr/lib64/python3.9`, its `lib-dynload`,
`/usr/lib64/python3.9/site-packages`, `/usr/lib/python3.9/site-packages`.
Installed game_package.py is root:root 0644 in `/usr/local/libexec/wishicraft`.
There was no installed wishicraft Python distribution supplying that module.

The transport now retains exactly the same probe bytes and runs its stdin from
`/usr/local/libexec/wishicraft`, with `python3 -E -s -B -`: ignore inherited Python
environment overrides and user site, avoid bytecode writes, and use the same
adjacent module location as installed host helpers. Missing directory stops the
shell; missing module or failed observation never establishes READY. This is a
fixed deployment path, not user input or a production-only exception.

READY predicates, parser, package validation, expected run/Game/data source,
health/protocol checks and workflow deadlines are unchanged. No host file changes
or migration are required. Common digest remains
`64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`; package digest remains
`720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`.
Minecraft 1.21.1 / NeoForge 21.1.219 / Create 6.0.10 / Farmer's Delight 1.3.4 stay pinned.

## Regression boundaries

- A subprocess `/bin/sh` test uses the generated pipeline/interpreter flags from an
  unrelated cwd with hostile PYTHONPATH. Only fixture path/payload are replaced;
  it imports the real installed-style module, verifies the pinned catalog and
  rejects missing module/directory. The production payload remains byte-identical.
- Real NeoForge Docker executes the unmodified generated command and probe bytes
  in canonical absolute runtime layout. Real package files, Docker and Minecraft
  protocol are observed; disposable CI substitutes systemd and lacks production
  IMDS/retained mount, so this alone does not claim full EC2 READY.
- Wrong package/loader/version/hash/Game/generation path/run and malformed probe
  responses remain rejected. Health/RCON alone do not substitute for READY.
- Recovery fixture leaves initialized ownership, UNMATERIALIZED DB, saved world,
  terminal old receipt and no container. New host START uses another container/run,
  retains world inode and verified cache bytes/mtime, and observes the expected
  package via the exact stdin command before fixture materialization completion.
  The production Control Plane's existing READY-gated commit remains authoritative.

## Production gates and status

Beginning preflight 2026-09-18 11:36:49 UTC: stopped, 45 alarms OK, queues empty,
no Lock/workflow/SSM/session/DNS, nine snapshots and sixteen provenance records.
Canonical caller matched configured account. All seven Game/registry/policy records
and 79 historical Operations matched the previous closeout.
Read-only maintenance SSM `f5420519-64f9-4144-bd8b-9ca7056ad278` confirmed complete
Game tree, A/B tree, world inode, initialized ownership, stopped receipt, finalized
recovery sidecar, cache/projection and all installed artifact hashes/metadata equal
to the previous terminal closeout. No container/Java/listener existed. Minecraft
was not started; maintenance EC2 normal stop was requested after inspection.

The initial import-only release gate required both CIs, stopped healthy preflight and
Control Plane Lambda code only. The later explicit Case D approval below supersedes
that gate only for its five named semantic-no-op Definition updates. IAM/resource,
Target/Data/unrelated Web or other State Machine changes still stop release. Re-read retained disk identities immediately before formal
START. Use a new admitted request and verify its retry returns the same Operation.
Only successful READY may commit MATERIALIZED, generation 1 and the same world path.
Then use normal STOP, canonical save proof and container cleanup, and verify final
STOPPED/HEALTHY, 45 OK, no active work or DNS, unchanged A/B and backup provenance.
Only after all gates pass may the three ingress functions return to their prior
settings. Another production bug stops this slice after safe containment.

**Production code deployment and new START are not yet performed at this checkpoint.**

Repository checkpoint: 1,443 full tests passed with dependency network access, plus
2 later READY-gated commit regressions passed. Lint/format/type and production
context synth passed. Initial sandbox-only tests/synth failed on PyPI DNS during
hash-locked bundling, not application assertions. Local Docker CLI is unavailable;
real Docker qualification is required in CI. Synth versus current live template
shows only Code changes to the eleven existing Control Plane Lambdas sharing the
bundle, with no new resources or IAM/state-machine/configuration changes.


## Release blocked before deployment — second observation defect

The import correction is insufficient for end-to-end READY. Review of the next
Control Plane boundary found `probe._parse_protocol` independently checking
`version_match` against global `EXPECTED_MINECRAFT_VERSION = "26.2"`. The host's
integrity-checked NeoForge package correctly reports Minecraft 1.21.1 and true,
but the parser rejects this as `protocol version comparison is inconsistent`.
`status.py` calls this parser without a Game-specific expected version input.

A local reproduction uses the existing complete running probe fixture, changes
reported_version to 1.21.1 and protocol_version to 767, preserves ready=true and
version_match=true, then calls parse_host_runtime_probe with its exact instance.
It raises ProbeContractError with the above message. Read-only retrieval of the
currently deployed Reconcile S3 code asset confirmed probe.py is byte-identical
to the repository parser, including the fixed 26.2 predicate. This is a separate
pre-existing production defect, discovered before another production START.

The current Docker fixture verifies real host package/protocol observation but
cannot certify Control Plane acceptance: CI lacks production IMDS/mount context.
The previously separate host/protocol and parser tests covered different expected
versions. Green transport/Docker tests must not override this release blocker.

**No production code deploy, host migration, new START or materialization commit
was performed.** Keep all three ingress functions closed. Existing initialized
world, stopped old receipt and absent container remain intact. Do not change this
parser within the import-only slice or trust host-supplied version_match blindly.
The next separately scoped correction must supply the Control Plane parser with
an independently validated expected version from the bound Game/package identity,
preserve wrong-version/Game/run/generation rejection, and test the full transported
response through Status/Reconcile before retrying formal START.

Final production observation **2026-09-18 11:51:00 UTC**: STOPPED/HEALTHY,
EC2 stopped, 45 alarms OK, no Current Operation/Lock/workflow/SSM/session/DNS,
three queues empty. Seven Game/registry/policy records, all 79 Operations,
16 provenance rows, nine snapshot metadata entries, volume metadata and four
CloudFormation templates matched beginning baseline. The maintenance-only
DesiredStoppedEc2Running alarm recovered naturally; no alarm suppression occurred.
Ingress remains closed. There are no new START/STOP Operation IDs for this slice.


## Repository qualification complete; production remains blocked

Fix commit `f95fb02328961a99b8ddb2319f72918877e95603` passed
[standard CI 35341251311](https://github.com/eash-misoni/wishicraft-server/actions/runs/35341251311)
and [NeoForge Docker CI 35341251322](https://github.com/eash-misoni/wishicraft-server/actions/runs/35341251322).
The final suite has 1,445 tests; lint, format, type, synth, Web and real Docker
lifecycle checks passed. At 11:50:40 UTC Docker recorded
`INITIALIZED_PREPARED_WORLD_REUSED_NEW_RUN_READY`; the unmodified stdin command
observed create-survival and Vanilla in six checkpoints, followed by
`HOST_NEOFORGE_START_SWITCH_RESET_WHITELIST_PASSED` at 11:53:01 UTC.
These qualify the import correction and host reuse, not the blocked production
parser/READY/materialization boundary. No new production capacity sample or normal
START/STOP proof exists in this slice. Whitelist remains 0/0/0; client access is
not ready and ingress was not restored.

## Immutable Game authority correction (repository qualification in progress)

The subsequent review selected **Game authority**, not a new Operation package pin.
D-109 registration is immutable in the supported application contract: CREATE's
conditional Put is the only package writer; bootstrap GameRepository.register also
requires absence. There is no Game/package edit endpoint. START completion updates
materialization/timestamps; SWITCH changes selection; RESET changes world.current_id;
whitelist has separate records. Backup recovery and interrupted-stop recovery read
and validate packages. Stopped runtime migrations validate existing identity and do
not rewrite Game packages. Local restore/fixtures are isolated test authorities,
not production package update paths. Root/operator direct DynamoDB writes are outside
this contract; this design does not claim to defeat a privileged out-of-band rewrite.

`game_package.canonical` sorts keys, uses compact JSON plus newline; SHA-256 covers
all definition fields, including exact Minecraft, loader/installer, mods, versions,
URLs, upstream IDs, sizes, hashes and client requirements. `registered` resolves the
exact package ID/version in the fixed deployed catalog, checks definition equality
and creation.package_digest; common runtime compatibility remains independently
checked. Legacy A/B have no creation/definition: only configured legacy Game IDs
and a canonical Vanilla catalog reference qualify. No record migration is required.

| Concern | Immutable Game authority (selected) | Operation package pin |
| --- | --- | --- |
| Durable fields | None | New pin for new runs |
| IAM/config | Existing Games GetItem | Reconcile Operations GetItem/table setting |
| Legacy A/B | Existing allowlist + Vanilla catalog | Same resolution then new pin |
| TOCTOU | Package has no mutation operation | Per-run frozen package |
| Reconcile | Existing Game reads | Extra Operation lookup |
| Future package edits | Must review run authority before introducing | Can distinguish old/new runs |
| Failure/retry | Missing/invalid authority stays unknown | Also needs missing-pin compatibility |

The CP `package_authority` reader checks the returned Game ID/schema/active status,
uses canonical registration validation and the fixed catalog, and returns the exact
package identity. Observation binds receipt target Game/instance to active Game and
probe instance, and compares dynamic registration's runtime provenance with the
receipt target. START's existing assert_observed still compares the complete target
with its frozen Operation before DNS/success; no pin, lease or target check is removed.
For SWITCH source observation the observed Game may differ from selected destination:
its immutable package is validated, while existing status/Game matching prevents it
from satisfying destination READY. Generation/path comparisons remain at their
existing host, target and Reconcile boundaries.

Reconcile factory supplies this authority to TargetStatusObserver whenever
GAME_PACKAGES=1. Both workflow ReconcileReady and normal scheduled Reconcile share
this exact path. The parser no longer has a 26.2 constant or implicit fallback;
successful protocol observations require an independently supplied expected version.
The existing exact numeric version-token comparison is unchanged (no prefix/range
matching); host version_match must equal the CP comparison, and false cannot become
READY. Pre-package deployments explicitly select the canonical legacy Vanilla
catalog identity. Missing Game/module/digest/version or malformed observations fail
closed, never health/RCON-only READY. Loader/mod/environment/hash verification stays
in the unchanged integrity-checked host package observer; the existing response
has no separate loader field, so this change does not invent independent loader
telemetry or accept an unvalidated host package assertion.

Future application writes MUST NOT mutate package or creation.package_digest after
CREATE. A package update feature requires a separate reviewed version/run authority
contract and regression updates before release. CREATE retry mutation and unsupported
Web PUT/PATCH regression preserve this boundary. No generic update API is added.

Common runtime `64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`
and package `720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`
remain unchanged. No host migration, IAM/config, durable schema or state-machine
change is intended. Real Docker now feeds the exact stdin probe result through
Game authority and CP parser. CI substitutes only unavailable IMDS/XFS observations;
actual package/protocol/run values are retained. This is repository evidence, not
production READY. Existing initialized-world/cache reuse regression remains intact.

Local qualification on 2026-09-18: 1,462 tests passed, ruff lint/format and mypy
passed, full production-context CDK synth passed. Live template comparison permits
only Code and corresponding asset-path metadata on the eleven existing shared-bundle
Control Plane Lambdas. Runtime digest equals the installed value above; no IAM,
configuration, resource identity or state-machine changes. Initial live observation
12:27:09 UTC was STOPPED/HEALTHY, 45 OK, drained and ingress closed. CI and production
START/READY/Reconcile/STOP are still pending at this implementation checkpoint.

## Qualified Game authority; production change-set gate held

Fix `c59d94ab03b30f97a78bf0c9c2ca901d2174bf3c` passed
[standard CI 35345075443](https://github.com/eash-misoni/wishicraft-server/actions/runs/35345075443)
and [NeoForge Docker CI 35345075632](https://github.com/eash-misoni/wishicraft-server/actions/runs/35345075632).
Actual Docker logs recorded `EXACT_SSM_PACKAGE_AUTHORITY_PARSER_READY` for
create-survival 1.21.1 and Vanilla 26.2, initialized-world reuse at 12:35:38 UTC,
and the complete host START/SWITCH/RESET/whitelist sequence at 12:38:03 UTC.
These are CI results, not a production START/READY claim.

Read-only production maintenance SSM `6af7e198-343a-4c55-97bf-1676ca3bbf50` found
world tree/inode 4316448, initialized ownership, package/cache bytes and metadata,
old stopped receipt, absent container, A/B tree, and all installed artifact files
identical to the previous inventory. Minecraft/Java/listeners were absent. EC2 was
normally stopped after inspection; no host migration or receipt edit was performed.

Although candidate/live template objects compare equal outside eleven Lambda
Code/asset-path changes, the actual CloudFormation change set additionally flags
Definition updates on **five** resources: StartStateMachine, StopStateMachine,
SwitchWorkflow, ResetWorkflow and BackupStateMachine. With IncludePropertyValues,
CloudFormation reports differing truncated Definition signatures. Read-only
DescribeStateMachine plus actual Lambda ARN resolution proves all six candidate/live
ASL objects (including unchanged Retention) semantically equal. This does not prove
why CloudFormation reports different signatures, or authorize extra resource writes.
The requested release gate permits only Lambda Code for branch A. Therefore the
change set was **deleted without execution**, rather than silently accepting those
additional updates or switching to an unreviewed direct-code/hotswap deployment.
No production Lambda code changed; the SSM import fix is also still undeployed.
Before resuming, separately review the deployment representation/signature difference
and a release method or scope that explicitly covers the resulting change set.
No runtime/application workaround, timeout change or package pin was added.

Final read-only production observation **2026-09-18 12:50:50 UTC**:
STOPPED/HEALTHY, EC2 stopped, 45 alarms OK, no Current/Lock/workflow/SSM/session/DNS,
three empty queues and three closed ingress functions. All seven Game/registry/policy
records, 79 historical Operations, sixteen provenance rows, nine snapshots, volume
metadata and four stack templates match the initial baseline. create-survival stays
ACTIVE/UNMATERIALIZED/generation 1 with its preserved initialized world. Whitelist is
still 0/0/0; no client access is enabled. There is no new START/STOP Operation, no
production READY/Reconcile qualification and no materialization commit in this slice.

Candidate code also resolved captured complete production records read-only: A/B
Vanilla 26.2 (package digest `75426f4a2b9368269b3e8d14bfb14974464eaecb7e4eb5b2f9c15eb9784ac78e`),
create-survival 1.21.1 / NeoForge 21.1.219 with unchanged `720deb9f…122f0b`.
This is candidate-code verification on captured records, **not deployed-code readback**.
[Machine-readable qualification and hold evidence](../evidence/game_package_authority_2026-09-18.json).

## Case D release guard — explicit dependency-propagated semantic no-op

The user accepted **Case D**, distinct from the earlier A/B/C classification.
CloudFormation's dependency evaluation can list a Definition update even when the
submitted and deployed State Machine properties are byte-identical. Do not reverse
engineer opaque truncated signatures as a release requirement, and do not treat a
matching ASL hash alone as authorization. The following are all required:

1. Explicit release-specific logical-ID allowlist; all changes fully paginated and saved.
2. Deployed/candidate raw State Machine Properties byte-identical, intrinsic-resolved
   ASL identical, canonical ASL identical; no DefinitionSubstitutions value difference.
3. Non-property-evaluated Details identify the updated dependency's intrinsic reference;
   independently read back referenced resolved identities (here unqualified Lambda ARNs).
4. In the property-evaluated final change set: Modify, Replacement=False,
   Scope=[Properties], Target.Name=Definition, RequiresRecreation=Never only.
5. No Role/IAM, logging, tracing, type, name, Tags or other property changes. Updated
   dependencies must retain their physical identity; here only Lambda Code/asset metadata.
6. Immediately before executing that same reviewed ChangeSet: ingress closed, no active
   workflow, Current Operation or Lock, empty queues, STOPPED/HEALTHY and EC2 stopped.
7. After completion: read back ARN, ASL hash, Role/configuration and referenced identities;
   record revision separately. A revision change alone is not an ASL change.

This release's exact allowlist: `BackupStateMachine`, `ResetWorkflow`,
`StartStateMachine`, `StopStateMachine`, `SwitchWorkflow`. Retention or a sixth State
Machine in the **property-evaluated final** change list must stop execution.
The non-property-evaluated dependency listing does include Retention; retain both API
responses, do not silently conflate them. Conditions outside this guard stop release.
No manual UpdateStateMachine, hotswap, template manipulation, resource recreation,
new alias/version or host migration is an alternative to this reviewed CF route.

## Production release and first materialization — 2026-09-18

Release HEAD `53491920057d427db605be0bb76655490d5371dc` matched freshly fetched origin/main,
with clean working tree and successful standard CI `35347044601` and NeoForge CI
`35347044712`. Implementation commits were `f95fb023` (import) and `c59d94ab` (authority).
Fresh synth matched the preceding deterministic candidate exactly:
`433c39d0ddf75048e3b1544102975a58b834b5cd2f94bafd74da2ead6cb17d08`.

Preflight at 13:25:12 UTC confirmed stopped/healthy, 45 alarms OK, all admission closed,
no active work/Lock/SSM/session/DNS, three empty queues, nine snapshots and sixteen
provenance records. Inspection-only maintenance found the initialized owner, old canonical
stopped receipt, no container, identical world inode/tree/cache and identical A/B tree.
Minecraft was not started by maintenance. EC2 was stopped again before deployment.

New ChangeSet `case-d-release-20260918T132834Z` was fully reviewed and executed through
CloudFormation. Its property-evaluated changes were exactly eleven existing Lambda
Code/asset metadata updates plus the five allowlisted Definition updates, no replacements.
The stack reached UPDATE_COMPLETE at 13:32:38 UTC. All physical resource identities,
all six State Machine ASLs/configurations, and eleven Lambda ARNs were unchanged.
The captured stack events contain Lambda updates and no State Machine update events;
reported revision IDs were also unchanged. Distinguish the preview's listed changes
from evidence of actual service updates; no direct Step Functions API update was used.

Hash-verified **deployed** Lambda ZIP code resolved consistent-read production records:
A/B → Vanilla 26.2; create-survival → Minecraft 1.21.1 / NeoForge 21.1.219 / unchanged
`720deb9f…122f0b`. No Game or historical Operation migration occurred.

- START: `op-5e28ed5c-441d-40f2-8928-348f73089901`, SUCCEEDED. Same request retry returned
  the same Operation, created=false. Existing prepared state was reused; no new CREATE.
- Container `8319d152952ac30df6821634ba26782c162454629668a1f44233b1d15ebd4481`
  used the same server/world path and world directory inode **4316448**, generation **1**.
  Three cache artifacts retained exact size/SHA-256/uid/gid/mtime; owner plan stayed initialized.
- Production logs recognized NeoForge 21.1.219, Create 6.0.10 and Farmer's Delight 1.3.4.
  RCON and mc-health succeeded with zero players. Common/Game-specific/effective whitelist
  stayed 0/0/0 (specific policy absent); `whitelist.json=[]`, online-mode/enforcement stayed true.
- Exact SSM transport imported correctly, observed version 1.21.1/protocol 767 and passed
  independent CP Game authority/exact comparison. READY, endpoint/DNS and HEALTHY succeeded.
- Ordinary `scheduled_reconcile` completed observed at **13:41:07.877160 UTC**. Read-back
  retained runtime_ready=true, HEALTHY, the exact new run/Game and present matching DNS.
- Game committed MATERIALIZED. Only materialization_state, last_started_at and updated_at
  changed; creation/package/world/generation and all other Game/registry/policy records did not.
- Xms 1G / Xmx 4G / container 6,442,450,944 bytes. Zero-player memory sample:
  container 1,704,267,776 bytes; host MemTotal 7,944,160 KiB / MemAvailable 5,971,168 KiB.
  Tick P95 0.2 ms, P99 0.3 ms; no kernel/container OOM, memory pressure or obvious GC errors.
- Normal STOP: `op-2a2c90b1-8e7b-4a60-9dd3-90a403226677`, SUCCEEDED. Request retry returned
  the same Operation. The ordinary workflow passed save, graceful stop, cleanup, EC2 stop
  and DNS deletion. No interrupted-stop recovery path was invoked.
- Inspection-only post-STOP read-back found `phase=stopped`, `save_confirmed=true`,
  `removal_ready=true`, exact new container ID/StartedAt and START run target; container absent.
  Existing world inode, initialized owner, verified cache, installed artifacts and A/B tree
  were preserved. The old finalized recovery journal was unchanged. Maintenance did not
  run Minecraft and ended with normal EC2 stop.

## Separate heartbeat incident — keep ingress closed

At **13:40:50.925 UTC**, after Control Plane READY, monitoring logged a **fresh heartbeat
but runtime unknown**. The alarm reported 13:36/13:41 datapoints and entered ALARM at
13:46:26 UTC. A later maintenance observation must not be used to explain away that
running-state inconsistency. START/Reconcile/materialization/normal STOP remain successful;
full operational release and client use remain blocked by this separate monitoring boundary.

Read-only code review found `runtime_heartbeat_producer.produce_once` selects the observed
Game as canonical only from the fixed two-Game host contract. A dynamic registered Game
falls back to GAME_ID (legacy A); `derive_heartbeat` then preserves ready protocol but clears
player_count, and `evaluate_telemetry` reports RuntimeObservationUnknown. An isolated
repository fixture reproduced ready/0 players → ready/null → metric 1. This is a concrete
repository defect consistent with the production log, **not a claim that this slice read
back the installed producer's bytes or the historical running heartbeat row**. The final
row was subsequently replaced by stopped/maintenance observations. Verify the installed
producer and its integrity/migration ownership in the next slice before selecting a fix.

No extra implementation, host artifact update, alarm suppression, membership addition or
second START was performed. Keep all three ingress functions closed even after alarms
naturally recover in stopped state. Next slice: dynamic-Game heartbeat authority and
zero-player continuity, preserving run/package checks and fail-closed behavior. Client
connection additionally requires an explicitly authorized whitelist membership (currently none).

[Machine-readable release evidence](../evidence/case_d_ready_production_2026-09-18.json).

Final read-only closeout at **2026-09-18 13:58:11 UTC**: STOPPED/HEALTHY, EC2 stopped,
45 alarms OK, no Current Operation/Lock/workflow/SSM/session/DNS, three empty queues.
The RuntimeObservationUnknown alarm recovered naturally; no alarm state/threshold change.
All other Game/registry/policy records, historical Operations, Data/root EBS metadata,
nine snapshots and sixteen provenance records matched baseline. All three ingress
functions remain reserved concurrency 0. Client use is **not yet released**.
