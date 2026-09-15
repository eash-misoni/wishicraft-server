# D-109 production qualification — server starts, observation blocked

The next separately authorized unit is [old-run stop recovery](interrupted_stop_recovery.md).
It does not fix the READY probe, commit Game materialization or start a new run.

**The optional-whitelist reader fix is deployed. NeoForge, Create and Farmer's Delight started
successfully, but the production SSM observation transport cannot import `game_package` and
first START timed out before Control Plane READY/DNS. Qualification is NOT complete.**
The existing Game record remains ACTIVE/UNMATERIALIZED, generation 1, while an owned, saved world
now exists. Operator explicit save/graceful stop and an EC2-stopped formal STOP returned the
control plane to STOPPED/HEALTHY. Admission, Discord and Web remain closed.
A stopped container and the unchanged running receipt are intentionally retained; the next slice
must review that interrupted state before any START, cleanup or migration. Do not delete/re-CREATE
this Game, normalize records, force old-runtime rollback or treat the absent-policy issue as pending.
Current results: [reader fix production follow-up](#reader-fix-production-follow-up--observation-transport-failure).
Earlier incident sections below are historical. [Package contract](neoforge_package.md).

## Approved scope and initial state

On 2026-09-14 the user explicitly authorized the D-109 stopped migration, necessary existing
stack deployments, one real `create-survival` CREATE, first START/materialization, observation,
and normal STOP. Existing A/B, snapshots/provenance, instance/volumes and memory were protected.
The user required stopping after a major post-CREATE failure, keeping all data and avoiding an
old-runtime rollback. This failure boundary was reached; no implementation hotfix was deployed.

Canonical `wishicraft-dev` SSO initially expired. After the user's real reauthentication, STS
matched account 385526546525 / ap-northeast-1. Fresh inventory at 12:25 UTC: Desired/Observed/EC2
STOPPED, HEALTHY, no Current Operation/Lock/running workflow/active SSM/session/DNS, three empty
queues, 45 alarms OK. Target remained m8a.large with the same root and retained Data EBS. Data
volume status was OK. Registry contained A/B and three whitelist policies, no dynamic Game.
Nine snapshots remained completed; eight normal snapshots matched their 16 paired provenance
records, plus the retained anchor. Both permanent stack policies matched canonical JSON.
An initial alarm-name-prefix query omitted the two automatically named Web alarms; the complete
inventory verified all 45. The incomplete 43-alarm inventory was not used as the release gate.

## Stopped migration and deployment

All three admission concurrency settings were captured, set to zero, and drain was rechecked.
An inspection-only maintenance boot did not start Minecraft: no container, Java process, gameplay/
RCON listener or runtime start timestamp. Exact stopped/save-confirmed/removal-ready receipt,
mount UUID/volume, canonical inactive unit, artifact predecessors and the 920-entry Game tree
matched the previous release. Free data space was approximately 29.14 GiB.

`wishicraft.game_package_migration.prepare` reproduced the predecessor and invoked the existing
inactive installer for eight files. Transport compression was lossless, checked by the complete
bundle SHA-256 before execution; it introduced no alternative installer or migration semantics.
The installer succeeded once. Read-back verified all eight new hashes and unchanged stopped
receipt and A/B tree (including content, owner/mode and file mtimes):
`f2c62614f20c6b18b399a73d0f129d99bb3ab47ac0f36b963c84cb812cf8696c`.

| Runtime identity | SHA-256 |
| --- | --- |
| Applied D-108 predecessor | `373dfb9c768b8d4b0b318793551212e0de5d5fe07b8ae4dc31791226e9ba5048` |
| Applied D-109 common runtime | `64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c` |
| Registered Create package | `720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b` |

Maintenance EC2 was normally stopped before deployment. Only WishicraftControlPlaneStack-dev and
WishicraftWebStack-dev were deployed from the reviewed assemblies at `f12eb03693b755b90d7a5fa00a441c985f8a6b36`.
Live diff contained existing 11 CP Lambda code assets, package/runtime/recovery environment values,
and the two existing Web/Auth code assets. No IAM, state-machine, permanent resource, Target or
Frozen Data change. Full templates, physical identities and actual Lambda code hashes matched
read-back; package digest/defaults and compressed recovery content matched the assembly.

Postmigration Reconcile returned STOPPED/HEALTHY; all 45 alarms returned OK before concurrency
restoration. A/B records, three policies, all 73 prior Operations and backup/provenance were
unchanged. The maintenance DesiredStoppedEc2Running alarm naturally recovered; no alarm state,
threshold or action was overridden.

## Real CREATE and authenticated metadata

A dedicated Edge used the user's actual Discord OAuth Admin login. No session/role was fabricated.
The formal authenticated `/api/operations` request used display name `create-survival`, package
`create-survival`, random initial seed and default RESET disabled. No whitelist membership was
copied or added. CREATE request ID: `2cf97f27-f04e-4cf6-86ab-6a0951bc61c1`.

- CREATE Operation: `op-eb068843cb6ca81759cb6dd9544ee6b6bd228307a0e8d0e065d879bf19f3312f`.
- Game ID: `game-eb068843cb6ca81759cb6dd9544ee6b6bd228307a0e8d0e065d879bf19f3312f`.
- CREATE completed SUCCEEDED at 12:39:34 UTC. Same request replay returned HTTP 200 / the same
  recorded success; consistent read confirmed exactly one additional CREATE Operation and Game.
- Schema 1, ACTIVE, UNMATERIALIZED, world generation 1, resolved seed `5198826396941673327`,
  runtime class `default`, immutable full package definition and both digest identities matched.
- The registered path is the canonical initial Game-ID-based `server/` anchor; CREATE itself
  performs no filesystem/EC2/SSM operation. The dynamic registry gained only this Game.
- Authenticated `/api/capabilities` returned MC 1.21.1, NeoForge 21.1.219, Create 6.0.10 and Farmer's
  Delight 1.3.4, exact filenames/SHA-256/upstream URLs matching the catalog. No Web selector added.
- Common membership and new-Game-specific/effective membership were all empty. No user is currently
  authorized through this Game's whitelist; existing A/B membership remains unchanged.

## First START failure and containment

The formal Web START request `3cd0c9cb-70e1-4567-833f-93519b079924` created Operation
`op-4fd5ae02-8c8f-4356-921b-20f2c5af470f`. The Step Functions execution failed at 12:42:42 UTC with
`START_CLEANUP_FAILED`. Persisted history entered exactly:

1. InitializeWorkflow
2. ReconcileBeforeStart
3. SetDesiredRunning — failed during `runtime_catalog.bind_operation`, before the action
4. SetPreconditionFailure
5. ReconcileAfterFailure
6. RecordFailure — failed in the same pre-action binding
7. UnrecoverableFailure

`bind_operation` used `backup_provenance._decode_map` on the complete Game. That decoder supports
List/Boolean but omits DynamoDB NULL. Valid nullable fields (including created_from template,
reset_policy, timestamps and world difficulty/hardcore) therefore raised `unsupported DynamoDB
attribute`. Read-only local reproduction with the captured full new Game **and both A/B records**
reproduced this failure. This is a production code defect, not an artifact download or NeoForge
compatibility failure. Failure recording traverses the same binding and leaves PENDING/ADMITTED
plus owned Current Operation/Lock although the workflow has already failed.

No EC2-start or SSM/materialization state was reached. Desired stayed STOPPED and selected A;
EC2 stayed STOPPED. No package jar/cache, new world, container or loader was generated in production.
No production JVM, mod-loaded, tick/CPU/GC or runtime-memory baseline can be claimed. No normal STOP
Operation was submitted because this START had no runtime side effects and still owned admission.
The Start workflow failure alarm and the two Start Lambda errors correspond to these failures.

The three existing admission settings were closed again. The dedicated browser was closed.
No Game deletion, snapshot action, forced runtime rollback, raw DynamoDB/receipt patch, deadline
shortening or decoder hotfix was performed. The registered Game remains intact.

## Conditional recovery and release hold

Existing D-074 `OperationRepository.recover_stale` requires a fresh Reconcile strictly after the
stored Operation deadline, **2026-09-14 13:12:32.426965 UTC**. Lease expiry alone is insufficient.
Before invoking it, verify terminal failed execution, no active workflow/SSM/session/queues/DNS,
EC2 STOPPED, exact failed Operation/lease/current ownership and fresh STOPPED/HEALTHY observation.
It atomically records this Operation FAILED and removes only its owned Lock/Current Operation,
with the exact stored deadline and observation timestamp conditions. Preserve Game and all prior
Operation/provenance records. Do not substitute guessed timestamps or raw delete operations.

Recovery succeeded at 2026-09-14T13:13:11.345713+00:00. The existing conditional transaction recorded the
failed START as FAILED with START_PRECONDITION_FAILED, removed its owned Lock/Current Operation,
and preserved Desired STOPPED. No deadline, lease identity, Game or prior historical record was
manually changed. Final inventory at 13:17:26 UTC confirmed STOPPED/HEALTHY, EC2 STOPPED,
no Current Operation/Lock/workflow/SSM/session/DNS, three empty queues and all 45 alarms OK.
ExpiredOperationLock naturally returned OK; no alarm override was used. All five prior Game/policy
items, all 73 prior Operations, the nine snapshots and 16 provenance items matched initial inventory.
The new Game exactly matched its pre-START registration. No post-failure filesystem read is claimed:
EC2 never started again after the verified migration tree baseline.
Keep admission closed after cleanup until a separately reviewed forward fix is deployed. The hold
means normal Discord operations and Web-Lambda routes (including the public guide and authenticated
management pages) are temporarily unavailable;
it does not change persistent IAM, networking, alarms or world data.

## Forward fix: full Game decoding and owned failure closure

The follow-up slice is explicitly authorized to fix the shared boundary, deploy only the necessary
CP code, and resume START/STOP for the **existing** registered Game. Keep the three admission
concurrency settings at zero until successful materialization, READY/mod evidence, normal STOP and
all final health/data gates pass. Another production defect requires safe containment and stopping.
No Game normalization, schema migration, re-CREATE or host artifact change is part of this fix.

| Boundary | Existing representation and follow-up decision |
| --- | --- |
| Initial A/B Game write | `game._attribute_map(Game.to_item())`; explicit nested nullable fields |
| D-105 CREATE / Operation / whitelist transaction write | `operation._attribute_map`; S/N/BOOL/NULL/M/L, integer numbers |
| Runtime Game binding | Reuse `operation._decode_attribute`, the matching Game/Operation contract; remove provenance-decoder dependency |
| Operation read | Same decoder; require exactly one AttributeValue type key, recursively including Map/List |
| Registry | Dedicated `registry_ids` validates exact SS structure; unchanged, no NS consumer added |
| Whitelist read | Exact two-field record plus `policy_json` string and policy validation; unchanged |
| Backup / retention provenance | Dedicated narrower decoders; recovery descriptors are JSON **strings**, optional absent fields are omitted; no full Game AttributeValue map is consumed here |
| Web/API read | `web_status.decode` already handles NULL and has distinct Decimal/fractional display semantics; unchanged |
| Host read | Standalone targeted runtime decoder already handles NULL; unchanged to preserve D-109 artifact bytes |
| Fixtures | Add complete `Game.to_item()` records, reset-world current reference, NeoForge immutable definition and nullable creation metadata; compare AWS TypeSerializer output with the real writer |

Canonical integer-valued decoding preserves S/N/BOOL/M/L and maps exactly `{"NULL": true}` to
None at every depth. False/non-boolean NULL, malformed nested attributes and multiple type keys
are rejected. SS remains the registry's dedicated contract, not silently converted to List.
No SDK TypeDeserializer substitution changes integer/Decimal semantics or canonical serialization.
Provenance validation and all package/manifest digest checks remain intact.

START and STOP `fail` actions now skip Game/catalog binding. They need only invocation identity,
existing Operation repository configuration and the existing `complete_owned` transaction. That
transaction still conditions on non-terminal Operation, exact resource/Operation/lease identity,
unexpired lease and exact Current Operation. It records FAILED and removes the owned Lock/current
atomically. Desired and Game are untouched. Success and all runtime-changing actions still bind
and validate the Game. SWITCH/RESET use these same START/STOP handlers; no state-machine change.
A duplicate terminal-task invocation remains conditionally rejected; retrying the admission request
returns the same recorded Operation and cannot reopen a lease. Lost/expired ownership still needs
the existing D-074 recovery review and actual deadline, not relaxed failure conditions.

`tests/unit/test_full_game_binding.py` directly covers complete Vanilla A/B and registered NeoForge
wire records through `bind_operation` and START preparation. Intentional non-NULL package class
failure is raised by the actual START handler; both failure handlers then close via the real
OperationRepository without another Game read. A foreign lease cannot close it, and original
request replay preserves identity after FAILED. The test-only AWS transaction boundary checks the
actual ownership conditions and applies all writes only after validation. It does not replace an
AWS integration test. Recursive valid NULL and malformed attributes are separately covered.
Before the fix, this suite reproduced eight failures; after it, all 12 pass. The previous package-
fragment tests missed nullable complete Game fields, while Docker fixtures exercised host runtime
without this Control Plane boundary. The new tests run in ordinary CI.

Repository validation: 1,399 full tests passed, lint/format/type passed; package-enabled CP synth
passed. Initial live diff has 22 changed paths: only Code/S3Key and asset-path metadata for the
11 existing CP Lambdas. Runtime digest, environment, IAM, resources and workflow definitions are
identical. Both fix CI runs succeeded; the observed production follow-up below reached a separate host failure.

Formal maintenance START/STOP uses the existing Admission handler/service and WorkflowLauncher
with canonical live configuration and a fresh explicit CLI idempotency key while public ingress
remains closed. It must not directly start a State Machine or manually write Game/Operation records.

## Original follow-up requirements (before the fix)

Fix complete-Game NULL decoding at the actual runtime binding boundary and add regressions using
full legacy and newly registered DynamoDB records, not only a package fragment. The existing generic `operation._decode_attribute` and host decoder already handle NULL; prefer
reusing the appropriate Game decoder rather than broadening provenance validation or editing records.
Cover failure
recording/cleanup as well as START/STOP/SWITCH/RESET binding. Existing 1,387 tests and the D-109
Docker qualification passed while missing this boundary: their success does not qualify production
materialization. Keep full manifest/package verification; do not remove NULL metadata to make it
pass. Review the forward-only code diff, run all relevant quality/synth/CI checks and deploy the
matching existing CP code under the hold. Reobserve and reopen exact prior concurrency only after
verification. Resume the **existing registered Game**, without another CREATE or new world path,
using a new formally admitted START; retain this failed Operation as provenance.

Then complete first materialization, all three downloaded artifact hashes, installer, loader/mod
recognition, RCON/health/READY/DNS, actual 1G/4G/6GiB and idle host observations, followed by formal
normal STOP and final data/inventory checks. Do not infer these results from CI or from CREATE.
Client preparation can proceed separately with MC 1.21.1, the exact NeoForge 21.1.219 client installer,
and the two exact mod jars linked by package metadata. Use a separate client game directory. Before
connection, the user must choose real membership through the existing whitelist policy; no identity
is inferred. Actual connection/player load, backup of the newly generated world and practical
capacity assessment remain future user operations. This slice creates no additional snapshot.

[Sanitized machine-readable deployment/CREATE/failure evidence](../evidence/neoforge_package_production_2026-09-14.json) records observed facts separately from completed conditional recovery and unexecuted runtime checks.

The first incident-docs NeoForge CI [34845856136](https://github.com/eash-misoni/wishicraft-server/actions/runs/34845856136) failed at the synthetic block-placement response assertion after server Done/RCON/heap checks. The response was not logged, so its cause is unconfirmed. This is separate from the production NULL boundary and is not counted as a passing run. Retain the failed logs and investigate fixture placement/readiness during the next regression slice.

## Client preparation while the release is held

These steps prepare only the user's client; they do not authorize another production START.
Following the [official NeoForge client instructions](https://docs.neoforged.net/user/docs/client/):

1. Close Minecraft Launcher. Run the fixed [21.1.219 installer](https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.219/neoforge-21.1.219-installer.jar), choose `Install client`, then `Proceed`.
2. In Launcher, create a separate installation using Minecraft 1.21.1 / NeoForge 21.1.219 and a
   separate game directory. Boot it once and close the game to initialize that directory.
3. Put only the reviewed [Create file](https://cdn.modrinth.com/data/LNytGWDc/versions/UjX6dr61/create-1.21.1-6.0.10.jar)
   and [Farmer's Delight file](https://cdn.modrinth.com/data/R2OftAxM/versions/XTVZDOol/FarmersDelight-1.21.1-1.3.4.jar)
   into its `mods/` folder. Verify SHA-256 against the immutable package catalog / recorded
   authenticated client requirements. Do not select a floating recommended/latest release.
4. After the forward fix and successful server START/STOP qualification, explicitly add the real
   player through the existing whitelist UI. Keep Common versus Game-specific scope intentional.
5. Once maintenance is lifted, select/start `create-survival` through the existing formal controls.
   Only when READY and DNS are present, connect to `mc-dev.wishicraft.net`. The second START
   selected `create-survival`, and recovery STOP preserved that selection. Public admission remains
   closed; selection does not mean materialization or connection has succeeded.

No actual client installation or connection was performed by Codex in this slice.

## NULL fix production follow-up — second host failure

Fix commit `0f3f7d7e7dc4b95a31983e99636d995ac1f58ff2` passed standard
[CI 34851093571](https://github.com/eash-misoni/wishicraft-server/actions/runs/34851093571)
and [NeoForge Docker CI 34851093621](https://github.com/eash-misoni/wishicraft-server/actions/runs/34851093621).
The earlier synthetic block-placement failure did not recur; its test was not changed or bypassed.
Local Docker was unavailable; these are CI Docker results, not a claimed local server run.

Fresh production at 13:37:59 UTC was STOPPED/HEALTHY, 45 alarms OK, with no Current Operation,
Lock, active workflow/SSM/session, queued messages or DNS. Repeated predeploy and pre-START checks
matched. The three public ingress functions stayed at zero throughout this follow-up.

Only `WishicraftControlPlaneStack-dev` was deployed. The 22 live-template differences were the
11 existing Lambda Code/S3Key and corresponding asset-path metadata changes. At 13:59:06 UTC,
postdeploy template matched the candidate exactly, all physical resource identities matched and
all 11 deployed code SHA values matched their assets. No IAM, environment, state-machine,
Target/Data/Web, resource or host artifact change occurred. Runtime digest remained
`64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`.

At 14:00 UTC, the fixed canonical binding function read all three complete live Games through a
read-only SDK proxy using their existing historical Operation context. Before/after reads matched.
This was local execution of the verified deployed code path against actual AWS records, not a
new Lambda dry-run endpoint. No A/B START or durable binding write was performed.
The actual nullable fields were `created_from.template_id/template_version`, `last_backup_at`,
`last_started_at`, `world.difficulty/hardcore`, plus `world.seed` on A/B and
`creation.reset_policy` on the NeoForge Game. None were rewritten.

### START result and bounded diagnosis

New formally admitted START `op-961a0756-5b60-4cf6-b828-9c619e905dd6` selected the existing
Game and started EC2. Replaying the same admission request returned the same Operation with
`created=false`. It reached SSM `RunStartScript`, then FAILED with `HOST_RUNTIME_FAILED`;
host command `87cb16c4-fbe0-4ce6-80de-f724328681f5` returned `TARGETED_RUNTIME_FAILED`.
Unlike the first incident, `ReconcileAfterFailure → RecordFailure → StartFailed` succeeded:
the ordinary owned transaction finalized FAILED and removed Lock/Current immediately, without
D-074 deadline recovery. The task/workflow failure alarms reflect this real START failure.

Read-only host inspection at 14:05 and 14:10 UTC confirmed:

- No container, Java process, gameplay/RCON listener or systemd runtime start timestamp.
- Initial owner phase `prepared`; server properties and initial whitelist baseline written.
- NeoForge installer and both mods cached, both mods projected; all five jar copies matched the
  pinned filename, size and SHA-256. No partial artifact was deleted or reacquired manually.
- Package owner/projection files exist. No `world/level.dat`, loader installation, generated
  config/defaultconfigs, runtime READY, DNS or actual JVM memory measurement was reached.
- Common policy read succeeds with revision 1 and zero members. The Game-specific policy record
  is legitimately absent; calling the deployed host `item()` reader for that key reproduces
  `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

The host reader applies `json.loads` directly to successful AWS CLI `get-item` stdout. An absent
item can produce empty stdout, so the caller never reaches its existing `if specific else empty()`
policy behavior. This is a distinct absent-record transport boundary, not the CP AttributeValue
NULL bug. Production command output has only the generic failure code; the bounded read-only
reproduction and materialization checkpoint identify the corresponding next host read. Do not
claim a captured exception stack from the original START. Common=0, specific=0, effective=0 remain
unchanged. The initial on-disk whitelist is a preparation baseline, **not a completed empty-policy
projection**; no server consumed it and no membership was added.

Changing this reader would change the protected D-109 runtime artifact. The user's additional-bug
stop boundary was honored: no host patch/migration, forced retry, policy workaround, Game deletion,
Vanilla fallback or old-runtime rollback was performed. Future work must distinguish an absent
item from malformed nonempty output and CLI/API failure, retain fail-closed checks, and cover the
real AWS CLI empty-response boundary as well as first materialization with no specific policy.
It needs separately reviewed artifact migration and CP digest alignment before another START.

### Safe containment and data outcome

The stopped receipt still identifies the previous saved A run; it was not rewritten to claim
that the new Game ran. A running-host formal STOP cannot adopt a mismatched prior receipt.
Following the existing D-096 maintenance containment pattern, fresh checks found no workload,
Lock/workflow/SSM/session, DNS or queued request. Normal, non-forced EC2 stop was requested after
save/removal proof and no-container/listener checks; EC2 STOPPED was confirmed at 14:12:41 UTC.

Then new formally admitted STOP `op-4cba0b3b-5ba0-46ce-9b10-308bd0b2d1c5` succeeded via
`SetDesiredStopped → AlreadyEc2Stopped → ... → MarkSucceeded`. It did not execute RunHostStop
or StopEc2. Admission-request replay returned the same Operation. This proves recovery STOP,
**not** graceful stopping of a running NeoForge JVM. At 14:13:20 UTC Desired/EC2 were STOPPED,
HEALTHY, with Current Operation absent. `create-survival` stays selected.

All seven Game/registry/policy records, 75 prior Operations, nine snapshots and 16 provenance
records equal the initial baseline. Instance type/ID, both EBS identities and attachment remain
unchanged; volume status is OK. A/B tree inventory (920 entries, including content, ownership,
mode and file mtime) remains SHA-256
`f2c62614f20c6b18b399a73d0f129d99bb3ab47ac0f36b963c84cb812cf8696c`.
No snapshot was created. The new Game's only data additions are its initial owner/baseline,
package owner/projection, cache and projected jars. Its record is still generation 1,
ACTIVE/UNMATERIALIZED with the same immutable package digest
`720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`.

The 14:14 UTC inventory confirmed no DNS, Lock, Current, active workflow/SSM/session or queue
messages. Three alarms still reflected pre-stop observations/failure events at that checkpoint;
all 45 alarms naturally returned to OK at 14:21:06 UTC, recorded in the [follow-up evidence](../evidence/neoforge_null_fix_production_2026-09-14.json).
No alarm threshold, notification, metric or state was manually changed. Ingress remains closed
regardless of alarm recovery because first NeoForge READY is unproven. JVM Xms/Xmx/container
configuration remains 1G/4G/6GiB, but no process memory/CPU/GC/tick baseline was measurable.
The user cannot connect yet; client preparation is possible separately, and intentional real
whitelist membership plus a successful forward-fix qualification remain required.

## Optional policy reader forward fix — 2026-09-15

The authorized next slice preserves D-106: absent Game-specific policy means revision 0 / empty
membership; Common absence is an incomplete migration and fails closed. CREATE does not write an
empty policy to hide absence. No member is added and no existing Game or historical Operation is
rewritten. The following is the reviewed release procedure; production results are recorded after
execution, not inferred from tests.

### Reader and integrity boundaries

`targeted_runtime.item` is the shared host GetItem boundary for Operation, Lock, Game and whitelist.
It requests a consistent full response using `--output json`, without `--query`. The existing
heartbeat producer already normalizes successful blank output as absent. The host reader now
applies that same absence semantics: only a successful command with no stderr diagnostics may
normalize blank/whitespace output or an empty response envelope to no Item. Nonzero exit, stderr,
malformed JSON, null/list/unexpected envelopes, explicit empty/invalid Item, wrong key identity and
invalid AttributeValue shapes fail closed. Required callers still require their records; absence
is not permission to proceed without an Operation, Lock, Game or Common policy. Whitelist record
shape and membership validation precede projection. State/receipt are local JSON files, not
optional AWS CLI reads. No host Query reader or new shared AWS access framework is introduced.

The runtime manifest digest covers Compose/runtime.env plus configured runtime/package metadata;
it does **not** contain the `operation-v2` executable bytes. Executable installation has its own
exact predecessor/new SHA-256 contract. This separation already existed and is unchanged. No
field is removed from manifest/digest verification for this fix.

Both before and after common runtime digest are:
`64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`.
Manifest, Compose, runtime.env, package catalog, MC/loader/mod versions and mod hashes do not change.
The immutable NeoForge package digest remains
`720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`.
The one installed file changes from SHA-256
`724c5a2a7c9eea473531fad6bc4601412a1e622d8cb6baca3d0120c923d18a8d`
to `912c45c3248a99335f1cf3f0883600a1584353c46f48cd9e4c10b2b82287a61f`.

`creation.config_digest` is actively checked by CP binding, package registration, host selection
and initial owner preparation. A genuinely changed manifest would fail these checks and require
a separate compatibility decision; this slice does not relax any of them. New Operations pin the
same common runtime digest with fresh request/Operation identities.

### Guarded helper-only installation

`game_package_migration --reader-fix` reuses the exact `runtime_install.py`; it does not call or
weaken the D-108 A/B-only cutover guard. It rejects changed platform/config/manifest/package/other
host sources against baseline `0889609`, requires the known runtime digest and complete registry,
checks A/B plus one ACTIVE, schema-1, generation-1 UNMATERIALIZED registered NeoForge Game, exact
package definition/creation digest and valid optional policies. Its one-file plan has the known
installed predecessor, current file hash, mode and exact stopped/save-confirmed/removal-ready
receipt. It preserves every Game/registry/policy record and all preparation/cache files.

Before applying: close all ingress, verify STOPPED/HEALTHY, no Current/Lock/workflow/SSM/session,
empty queues, no DNS, alarms OK, unchanged instance/volumes and snapshots/provenance. Use one
maintenance boot with Minecraft inactive, capture A/B and new Game file inventories, verify the
installed host files/manifest/catalog and exact receipt, then build a fresh private bundle.
Transport verifies bundle hashes before invoking the existing installer with `BUNDLE` pointing to
that fresh directory. The installer retains flock, host identity, filesystem preflight, no unit/
container/listener, receipt, owner/mode, whole-plan validation and atomic replacement checks.
Run the same bundle again to prove canonical files are reused without rewriting. An interrupted
run retains the old/new hash classification and predecessor backup; unknown content stops before
mutation. No unverified file or world is deleted to recover.

After read-back and maintenance EC2 stop, deploy only necessary existing CP code assets if live
diff agrees; expected runtime digest remains unchanged. Verify all three real Game bindings
read-only, then formally admit a new START for existing `create-survival` and replay its request.
Require preserved cache hashes, empty effective projection, installer/mod/READY/DNS evidence and
0-player memory observations. Then formal STOP and all final health/data gates precede ingress
restoration. Another production bug ends the slice after safe containment; no chain of hotfixes.

Rollback before START is the reverse exact-hash inactive installer operation, with unchanged
manifest and records. It restores the known absence bug and therefore cannot justify reopening
admission. After first materialization or an ambiguous runtime failure, keep data and use existing
failure/recovery procedures; do not blindly roll back, delete or re-CREATE the Game.

Tests cover blank/whitespace/envelope absence, present empty/nonempty membership, Common absence,
command/stderr/JSON/shape failures, actual empty whitelist file projection, same-manifest bundle,
registration/digest/materialization guards and existing installer interrupted retry/idempotency.
The NeoForge Docker host fixture now passes AWS wire envelopes and successful absent stdout
through the actual host reader rather than replacing `host.item` with decoded Python records.


## Reader fix production follow-up — observation transport failure

On 2026-09-15, fix `d766901` plus CI-only fixture corrections through `ba23f49` passed
[standard CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/34957906404)
and [NeoForge CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/34957906159).
The standard suite passed 1,418 tests, lint/format, mypy (207 files), synth and existing Docker
lifecycle/whitelist/reset checks. The actual NeoForge host fixture exercised successful blank
Game-specific GetItem output through the reader and projected `[]`, then passed START/SWITCH/RESET.

Two CI fixture gaps were diagnosed without changing production behavior: the candidate block
probe failed with `That position is not loaded`, so the disposable CI world now force-loads its
probe chunk with bounded waiting; the older whitelist/reset mock omitted the real `game_id`
record key, which is now present. Failed runs remain evidence, not passing checks. No block
placement was performed in production.

### Applied release and preserved identity

Fresh inventory at 10:09, 10:32 and 10:37 UTC proved STOPPED/HEALTHY, 45 alarms OK, no Current/Lock/
workflow/active SSM/session/DNS, three empty queues, all ingress closed, unchanged Games, same
instance/root/Data volume, nine snapshots and 16 provenance records. Maintenance-only EC2 boot
then proved no Minecraft container/Java/listener, the exact saved predecessor receipt, all 11 host
artifacts and the A/B tree hash. The fresh `--reader-fix` bundle matched the offline review.

Only `operation-v2` changed using the existing inactive installer. Both manifest/runtime digests
remain `64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`; package digest remains
`720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`.
Same-bundle retry preserved the new helper SHA and mtime. Read-back preserved every other host
file, receipt, A/B tree and prepared/cache file, including mtime. D-108's migration guard and
all creation/Operation digest checks remain unchanged; no durable record migration occurred.

Maintenance EC2 was stopped before deploying only `WishicraftControlPlaneStack-dev`.
Fresh live diff was exactly 11 existing Lambda Code/S3Key changes plus their asset metadata;
there were no IAM, new resource, state-machine, Target/Data or Web changes. Read-back verified
UPDATE_COMPLETE, physical IDs, code archive hashes, expected runtime/catalog configuration and
closed ingress. All three Games bound read-only through canonical code without record changes.
The maintenance DesiredStoppedEc2Running alarm naturally returned to OK before the 10:48 UTC
complete pre-START gate. Alarm state/thresholds were not overridden.

### Actual first startup and new failure boundary

Formal START `op-76571b92-0fe6-47a9-b31e-00a0e0048e36` reused existing `create-survival`;
request replay returned the same Operation with `created=false`. The host reused the three
verified cached artifacts and two projected mod jars without changing hashes or mtimes.
Empty whitelist projection succeeded without creating a policy record. NeoForge's installer ran,
the generation-1 server/world was generated, and the server logged `Done` at 10:50:42 UTC.
Production loader evidence contains:

- `NeoForge 21.1.219 (neoforge)`
- `Create 6.0.10 (create)`
- `Farmer's Delight 1.3.4 (farmersdelight)`

Read-only RCON list/health and tick query succeeded with zero players. No test blocks were placed.
The mods' upstream version-check messages do not install updates; the pinned files remained exact.

However, `ssm_probe._canonical_probe_command` streams the standalone probe to `python3 -`.
`host_runtime_probe.package_version` falls back to `import game_package`, but this execution context
does not place `/usr/local/libexec/wishicraft` on the module search path. The verified installed
module exists; the SSM probe exits 1 with `ModuleNotFoundError: No module named 'game_package'`.
Control Plane observation stays UNKNOWN and cannot publish READY/DNS. Docker fixtures imported
the repository modules directly and did not exercise this exact deployed stdin/import boundary.
This is a distinct defect; no production import-path workaround or follow-on implementation was
made. START reached the existing READY deadline and closed FAILED/MINECRAFT_READY_TIMEOUT,
releasing Lock/Current normally. No stale-record/deadline repair was needed.

### Zero-player observation, not a capacity claim

At 10:55:06 UTC, before containment:

| Observation | Value |
|---|---:|
| Host MemTotal / MemAvailable | 7,944,160 / 5,811,400 KiB |
| Container current / peak | 1,911,500,800 / 1,912,983,552 bytes |
| Container configured limit | 6,442,450,944 bytes (6 GiB) |
| JVM arguments | Xms 1G / Xmx 4G |
| Java RSS | 1,588,236 KiB |
| Host CPU / container CPU | 0.30% / 2.29% of one core, ~5-second sample |
| Java `ps` CPU | 14.8%, process lifetime average including startup |
| Tick query | target 20/s, average 0.0 ms; P95 0.2 / P99 0.3 ms, 100 samples |
| Kernel OOM / cgroup OOM / memory pressure | none / zero / zero |
| Obvious GC errors | none observed in logs; no full GC profiling performed |

These are idle observations, not player-load capacity validation. Memory settings were unchanged.

### Safe containment and retained incomplete state

Formal running-host STOP requires an observed target; the broken probe prevents that precondition.
After START was terminal and no Lock/Current/workflow/active SSM remained, the existing fixed
explicit `save-all flush` and systemd graceful stop were used as operator containment. The exact
container/run/data binding and installed stop script hash were checked first. At 11:02:22 UTC,
save succeeded, container exited 0 without OOM, listeners disappeared, and world data was retained.
This is operator graceful-stop evidence, not a claim that the normal running-host STOP workflow
passed. No force stop, Game deletion, container removal, receipt fabrication or code patch occurred.

A/B tree hash remained `f2c62614f20c6b18b399a73d0f129d99bb3ab47ac0f36b963c84cb812cf8696c`.
The post-stop new Game tree contained 405 entries including the saved world. Its three cache jars
and two server mods still matched their original bytes, size, ownership, mode and mtime. EC2 was
then normally stopped; the existing EC2-stopped formal STOP
`op-dd421ed4-6e99-4fef-8e0d-449e7c694403` succeeded and its request retry was idempotent.
Desired/EC2 became STOPPED/HEALTHY with no Current Operation. No snapshot was created.

The important retained state is:

- DynamoDB Game/registry/creation/package are unchanged: ACTIVE/UNMATERIALIZED, generation 1.
- The physical server, six generated config files and saved `world/level.dat` now exist.
  No files were observed under `defaultconfigs`; `world/serverconfig/readme.txt` was present.
- The initial owner still reports `prepared`; completion was never committed by Control Plane.
- One verified exited container is retained. Receipt still has phase `running` and the failed
  START's run identity, unchanged rather than rewritten to manufacture normal STOP completion.
- Common/specific/effective membership remain 0/0/0; no Game-specific policy record was inserted.
- All 77 prior Operations are unchanged; only this START and recovery STOP were added.

The next slice must cover the deployed probe transport/import contract and review safe convergence
of this owned world/container/receipt state. Do not blindly retry START or apply the earlier
inactive installer: its stopped-receipt guard is not satisfied. Preserve world and provenance;
use no Game re-CREATE, arbitrary receipt rewrite, Vanilla fallback or forced rollback. Only after
an eventual full START/READY/STOP and all closeout gates may ingress reopen. Client connection is
not available while ingress/DNS are closed and effective whitelist is empty.

[Sanitized release, failure, containment and final inventory evidence](../evidence/optional_whitelist_reader_production_2026-09-15.json)
records the final alarm recovery separately from earlier alarm checkpoints.


Final inventory at **2026-09-15 11:17:22 UTC** confirmed STOPPED/HEALTHY, EC2 STOPPED,
all 45 alarms OK, no DNS/Current/Lock/running workflow/active SSM/session, and three empty queues.
The final Game/registry/whitelist records and 77 pre-existing Operations were byte-semantically
unchanged; the nine snapshots and 16 provenance records were unchanged. Target/Data/Web templates
and all resource identities were preserved; CP matched the reviewed deployed assembly.
Ingress remained reserved concurrency zero for Admission, Discord Command and Web. Alarm recovery
was natural; no alarm settings or metric values were changed. Production work ended at this
checkpoint. Repository evidence does not mark the incomplete first START as successful.
