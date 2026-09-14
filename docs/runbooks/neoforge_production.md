# D-109 production qualification — interrupted before materialization

**Runtime/Control Plane/Web deployment and positive CREATE succeeded. First START failed before
EC2 start. Production qualification is NOT complete.** The package-enabled release remains
installed; the Game is retained UNMATERIALIZED. Admission, Discord command and management Web
are held at reserved concurrency zero to prevent further affected operations. Do not attempt
another START or roll back to the A/B-only predecessor. [Package contract](neoforge_package.md).

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

## Required next slice

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
   Only when READY and DNS are present, connect to `mc-dev.wishicraft.net`. The failed first START
   did not change the selected Game from A, so an unqualified `/mc start` currently does not mean
   this new Game. The future successful targeted START must establish that selection first.

No actual client installation or connection was performed by Codex in this slice.
