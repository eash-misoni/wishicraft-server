# D-109 production qualification — interrupted before materialization

**CP NULL decoder/failure-finalization fix is deployed. A second START reached EC2 and pinned
artifact materialization, then failed at the host's absent Game-whitelist record read. NeoForge
qualification is NOT complete.** The existing Game is retained ACTIVE/UNMATERIALIZED, generation 1,
with partial owned files/cache preserved. Recovery STOP succeeded; Desired/EC2 are STOPPED and
HEALTHY. Admission, Discord command and management Web remain at reserved concurrency zero.
Do not retry START, create a policy record as a workaround, or roll back to the A/B-only runtime.
The current outcome is in [NULL fix production follow-up](#null-fix-production-follow-up--second-host-failure).
The initial incident sections below remain historical. [Package contract](neoforge_package.md).

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
