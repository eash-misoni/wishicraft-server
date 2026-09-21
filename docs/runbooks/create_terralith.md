# Create + Terralith + Tectonic

Production server-side qualification completed, 2026-09-21 UTC (2026-09-22 JST).
The additive host migration, guarded Control Plane/Web release, real Admin Web
CREATE, fresh generation-1 materialization/worldgen, and normal STOP succeeded.
Existing A/B/create-survival were preserved. Actual Minecraft client login remains
unverified and is explicitly delegated to the user. See the closeout below and
[machine-readable evidence](../evidence/create_terralith_production_2026-09-21.json).

Local qualification: 1,513 tests passed; Ruff lint/format and mypy (218 source
files) passed; package-enabled Control Plane CDK synth passed. Real Docker
qualification runs on the existing Linux CI because this checkout has no Docker
CLI. These were intermediate local results; final release commit `e87994a` passed
standard CI `35619255358` and real NeoForge Docker CI `35619255294` before release.
The release CI ran 1,515 tests, Ruff (292 formatted files), mypy (218 source files),
Web qualification and the configured CDK synth variants successfully.
Closeout local revalidation also passed all 1,515 tests (99.31 s), Ruff/format and
mypy. Its first sandboxed run had 8 failures/47 setup errors because the pinned
Lambda bundler could not resolve PyPI DNS; a focused check confirmed this cause.
The failed evidence was retained and a fresh network-enabled test root passed,
without implementation changes or treating the blocked run as successful.

First Docker attempt, run `35617068544`: existing Create passed; new package
reached health/RCON with all verified artifact hashes. The test incorrectly
required a separately named Terralith pack; NeoForge reported `mod_data` and
`tectonic` enabled. This fixture assertion is corrected; the actual Terralith
biome lookup remains required. No package/version or production change followed
this test failure. Original failed-run evidence is retained.
Second attempt `35617665677` passed the actual Terralith biome lookup, then
failed another fixture assumption: the integrated overworld JSON does not need
to contain a literal `tectonic:` reference. The replacement assertion checks
the actual `neoforge:overlays` activation condition (`terralith` loaded), the
integrated noise/surface definition and its hash. No candidate version changed.

The user also explicitly authorized the existing Web stack shared Lambda code
asset update. Its old package validator rejects `client_required=false` while
projecting a newly created Game. Both Create packages now have Web CREATE /
capabilities / idempotency / immutable-record regression coverage. Web IAM,
authentication, URLs and resource structure must remain unchanged in ChangeSet.
Additional focused provenance regressions passed (9 transition tests): an
initialized initial-owner file retains exact bytes/mtime and the world retains
its inode/content when preparing the new runtime; both historical predecessor
and mixed old/new-creation-provenance backup descriptions validate without edits.

## Fixed package and isolation

`create-terralith`, package version `1`, uses Minecraft 1.21.1 / NeoForge 21.1.219,
Create 6.0.10, Farmer's Delight 1.3.4, Terralith 2.6.2, Tectonic 3.0.26 and
Lithostitched 1.7.12. JEI is not in the package. Only upstream defaults are used;
no increased height, extreme terrain or custom preset is enabled by Wishicraft.
This is a new Game, fresh generation 1, with an independent Game-private world,
cache and config. Never copy, upgrade, regenerate or modify create-survival's world.
Existing NeoForge config/defaultconfigs and RESET contracts remain unchanged.

The exact URLs, filenames, byte lengths, IDs and SHA-256 are fixed in
`src/wishicraft/artifacts/game-packages.json`. On 2026-09-21, each exact mod version
was checked against the official Modrinth v2 project/version API, the bytes matched
the upstream size/SHA-512, and SHA-256 was recomputed. The installer bytes matched
the official Maven SHA-256 and its install profile selects Minecraft 1.21.1.

| Mod | Project / version / file ID | Bytes | SHA-256 |
|---|---|---:|---|
| Create | LNytGWDc / UjX6dr61 / V876RuGl | 19123767 | ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a |
| Farmer's Delight | R2OftAxM / XTVZDOol / xb3oJkla | 3160490 | 139ad7696462c89c03eea463f805abffa552526c5dadaadae221dd9624cb197c |
| Terralith | 8oi3bsk5 / IY93YaEe / bpzstSor | 2814865 | d38bd304897731b42f6c013cdc07e082e74411e80c74aabcee385251beb3b546 |
| Tectonic | lWDHr9jE / vNrkxC3z / M6o3EcFY | 461675 | 36aa9b4a8c399c9943460a7a58d91402b6d671c10ab11b099c2ee1d75af232ea |
| Lithostitched | XaDC71GB / vioNV2Gt / XcMWYHUv | 852287 | e18cae8aaef95f7058a16c05705c6e78a4b33a00bcf9189e96ed8a8785fb9647 |

NeoForge installer: 6961236 bytes, SHA-256
`140df0fa17fd438848051ecfa3d091081515ad12bfe34fa126405037ba01de44`.
No jar is committed, mirrored, uploaded as CI evidence, or redistributed.
Terralith's project license is Stardust Labs License even though loader metadata
says MIT; that loader field does not authorize a mirror. The existing Create
code/assets license distinction also remains in force.

## Dependency and client boundary

All exact distributions list Minecraft 1.21.1 / NeoForge. Create and Farmer's
Delight require at least NeoForge 21.1.219 in their jar metadata; the chosen
runtime remains exactly 21.1.219. Terralith's jar requires Lithostitched at least
1.7.7. Tectonic's exact version API also declares Lithostitched required. The
candidate fixes 1.7.12; declared compatibility is not a substitute for boot tests.
Create's bundled Registrate MC1.21-1.3.0+67, Flywheel 1.0.6 and Ponder
1.0.82+mc1.21.1, and Tectonic's bundled Apollib 1.1.5-neoforge-21.1, are pinned
by their outer jar hashes, without adding a transitive download resolver.

Required clients: Minecraft 1.21.1, NeoForge 21.1.219, Create 6.0.10 and Farmer's
Delight 1.3.4. Exact version metadata reports Terralith and Lithostitched as
server-only, Tectonic as server-only/client-optional. Their `client_required=false`
is represented using the existing field; only strict JSON booleans are accepted.
No recommended-client metadata is introduced. JEI remains optional outside this
Game package. Actual client connection without worldgen mods must be recorded
separately; until performed it remains unverified, even when server Docker passes.
The user elected to perform this real-client login check later; it is not a
claim made by this server qualification or a blocker for the approved server release.

## Limited immutable catalog transition

Appending a package changes the COMPLETE common manifest digest. It does not
change either existing package definition/digest:

| Identity | SHA-256 |
|---|---|
| Vanilla package | 75426f4a2b9368269b3e8d14bfb14974464eaecb7e4eb5b2f9c15eb9784ac78e |
| create-survival package, unchanged | 720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b |
| create-terralith package, new | 5f653900b7438059311f25e3f296e2260f10717e83f9374619b7bb7cb0026c35 |
| Common predecessor | 64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c |
| Common successor | 9554899af2f2e70a53cf71518a50c80607f414ce3dae44f3d59377bf98e28975 |

`catalog-transition.json` contains both FULL manifests. Compatibility requires
their exact hashes, byte-equivalent existing package definitions in the same
order, exactly one new package ID appended, and equality of EVERY non-catalog
field, including Compose/runtime.env hashes, image, games, reset policy and
platform/runtime settings. No field is removed from manifest hashing. The new
package cannot claim predecessor provenance. Reverse/unknown transitions and
altered existing definitions are rejected.

This only permits immutable Game **creation provenance** to remain at the
reviewed predecessor. New Operations still pin the CURRENT exact runtime digest;
host manifest/config, lease, receipt, container labels, package and mount checks
remain mandatory. Old Operations cannot execute under the new digest. No Game,
creation digest, initial owner, package owner, historical Operation, stopped
receipt, snapshot or provenance record is rewritten during migration. Backup
recovery validation uses the same bounded compatibility check, preserving old
descriptor validation and immutable Game data.

The old A/B migration and helper-only migrations are not generalized. A separate
`wishicraft.catalog_migration` prepares a six-file plan using the existing
inactive installer: manifest, runtime-contract, game_package.py, initial_game.py,
operation-v2 and the new complete transition file. The captured runtime config
must match the recorded deployed SHA-256; executable predecessors come from
reviewed commit 866f6ca and are verified again on the host. Whole-plan validation,
ownership/mode, exact stopped/save/removal receipt, verified Game cache, mount,
no container/unit/listener, backup and atomic replacement are retained. Partial
installation accepts only exact predecessor/target bytes; retry preserves already
canonical files. No Data EBS layout or IAM changes are introduced.

## Production gate and release sequence

1. Qualify fixed jars and real Docker (both existing Create and new worldgen),
   full regression/lint/format/type/synth, standard and NeoForge CI. Record failed
   fixture attempts without overwriting their evidence. Check actual client
   compatibility separately; never claim a protocol ping proves a client login.
2. Authenticate `wishicraft-dev`; compare STS account to dev YAML. Freshly inventory
   Games/whitelist, snapshots/provenance, selected/current Operation, lock,
   workflows, EC2/SSM, queues, DNS and alarms. If running, use canonical normal
   STOP, never direct container/EC2 stop. Close and record original ingress
   concurrency settings using the existing maintenance procedure.
3. At STOPPED/HEALTHY, perform the established maintenance boot, verify Minecraft
   inactive, capture exact stopped receipt/runtime config and full registry.
   Inventory all existing Game trees/owners/cache and installed artifact hashes.
   Generate a new offline bundle with `python -m wishicraft.catalog_migration
   --output <new-root> --receipt <json> --inventory <complete-Items-json>
   --host-config <exact-captured-bytes>`. Review six targets and bundle hash.
4. Under existing inactive installation controls, install/read-back/retry that
   exact bundle. Verify old Game trees, records and receipts unchanged. Finish
   maintenance through its existing stop route. Deploy necessary Control Plane
   assets/environment using all current contexts and the Case D five-State-Machine
   semantic-no-op guard. Reject IAM/resource/layout changes or ASL semantic drift.
5. Through D-105 Admission CREATE, register one `create-terralith` Game with fresh
   seed/generation 1. Verify ACTIVE/UNMATERIALIZED, full definition/new package and
   runtime digests, idempotent retry and absence of Game-specific whitelist.
   Preserve Common policy; do not copy/add membership.
6. Canonical START: verify exact artifact hashes/mod recognition, fresh world,
   READY/heartbeat/Reconcile/MATERIALIZED, generation 1 and whitelist projection.
   Read active packs plus worldgen evidence (Terralith biome and Tectonic's
   integrated Terralith overlay), and record startup/memory/CPU/tick/OOM baseline.
   Do not resize or enable custom terrain settings.
7. Canonical STOP through save, graceful stop, stopped receipt, cleanup, EC2 stop
   and DNS removal. Verify STOPPED/HEALTHY, no stale ownership/workflow/SSM, empty
   queues and normal alarms before restoring ingress to its recorded settings.
   A separate production bug requires safe stop and reporting, not hot patches
   or repeated STARTs. After a new Game exists, blanket old-runtime rollback is
   prohibited; preserve its immutable registration/world and review recovery.

## Qualification evidence

### Docker and immutable migration

Release implementation HEAD `e87994a35cd9e8d4463526b5dff7418510140142` was clean and
equal to remote main. Both CI runs above succeeded. The Linux Docker tests cover
Vanilla, existing Create and the new package, fresh generation, RCON/health,
save/graceful stop/restart, registered blocks, Terralith biome-source lookup and
the exact Tectonic integrated overworld definition. No candidate version changed.

The six-file host migration completed in the preceding maintenance session.
Post-install and same-bundle no-op retry preserved existing files' canonical
bytes/mtime and old Game trees/owners. Final real-host observation was SSM
`6290733e-bc4e-4f11-b09e-2c387891613a`, 15:59:06 UTC. The intentional maintenance
state (desired STOPPED / EC2 RUNNING / Minecraft stopped) triggered
DesiredStoppedEc2Running, RuntimeObservationUnknown and DesiredActualDivergence.
After explicit approval, ordinary non-forced EC2 StopInstances closed maintenance;
scheduled Reconcile restored HEALTHY and all 45 alarms were OK by 16:06:31 UTC.
No alarm suppression or monitoring setting change was performed.

On resumption the user accepted this stopped-host evidence as the handoff basis.
CloudTrail checks found only that last read-only SSM and the approved StopInstances,
not subsequent start, SSM/session or EBS mutation. This is not a filesystem-wide
write audit. **Migration was not rerun and no inspection-only boot was added.**
Normal first START passed existing host integrity checks; subsequent live SHA-256
readback reconfirmed all six targets, unchanged Compose/runtime.env and the current
heartbeat producer. Complete old/new manifests differ only by the appended package;
existing canonical package bytes, historical creation digests and A/B resolution
remain unchanged. Exact old/new/current file hashes are in the evidence JSON.

### Guarded release and authenticated CREATE

Fresh ChangeSets `terralith-resume-cp-20260921-v1` and
`terralith-resume-web-20260921-v1` were reviewed and executed through CloudFormation.
CP changed eleven existing Lambda code assets plus the necessary runtime/defaults
environment values. The five explicitly allowed Case D State Machine Definition
entries passed raw/resolved/live ASL equality, unchanged roles/configuration and
referenced physical identities; all six post-release ASLs remained identical.
Web changed existing Web/Auth shared code assets only. Auth's inclusion did not
change OAuth, session rules, IAM, environment, URL or resource topology.
No resource addition/removal/replacement or Target/Data stack update occurred.
Both stacks reached UPDATE_COMPLETE. Actual downloaded Lambda ZIPs matched service
CodeSha256, repository source and resolved template environment. Both deployed
Admission/Web validators resolved all three existing Games with unchanged digests.

The CREATE-only window was 16:24:16–16:27:36 UTC: Web/Admission concurrency 1,
Discord 0. The user logged into a dedicated Edge using real Discord Admin OAuth.
Formal Web CREATE returned accepted; identical request replay returned the same
SUCCEEDED Operation. Consistent reads verified its deterministic request,
idempotency, Operation and Game identity. No cookie/token was exported.

- Game: `game-0cd3c61636d7ba2acb3f99bc9d0edbf6b2fcffa63e64e9d4dde8372b569ef5b4`
- CREATE: `op-0cd3c61636d7ba2acb3f99bc9d0edbf6b2fcffa63e64e9d4dde8372b569ef5b4`
- Created ACTIVE / UNMATERIALIZED, generation 1, independent fresh seed/world.
- Exact package digest `5f653900b7438059311f25e3f296e2260f10717e83f9374619b7bb7cb0026c35`.
- Game-specific policy absent/empty; no membership copied or added. Existing Common
  revision 2 had one member and was projected unchanged (effective count 1).

Web/Admission were immediately reclosed. CLI qualification used the existing
Admission service and WorkflowLauncher with canonical live configuration, not
direct State Machine starts or manual Game/Operation writes.

### First START, worldgen and performance

START `op-ddbab77a-928f-4937-9e91-07e33b67dd70` succeeded at 16:33:20.781053 UTC.
All six cache artifacts (installer plus five mods) and all five deployed mod jars
matched exact filenames, sizes and SHA-256. Logs recognized NeoForge 21.1.219,
Create 6.0.10, Farmer's Delight 1.3.4, Terralith 2.6.2, Tectonic 3.0.26 and
Lithostitched 1.7.12. Receipt/container labels/bind matched the new Game/run and
current runtime/package digests. New level.dat and matching seed were observed;
RCON and mc-health succeeded, DNS was published, Reconcile recorded HEALTHY and
MATERIALIZED, generation stayed 1, and fresh heartbeat reported this Game/run,
protocol ready and zero players. Online mode and whitelist enforcement remained true.

Worldgen evidence (SSM `e54c8396-6ed1-4118-a651-394cbccd52c2`): enabled `mod_data`
and `tectonic`; real biome-source query located `terralith:yellowstone` at
`[1296, 65, 656]`, 1889 blocks away. The exact active Tectonic jar contains the
Terralith-conditioned `overlay.terratonic` integrated overworld noise/surface
definition with SHA-256 `a194b8bcc0a5c98c4f7c2b5343373dc7fa4d361ff046d50fc1e8a1ccd670ecf5`.
This correlates an actual biome-source result with active packs and integrated
worldgen resources, not merely mod-list presence. It does not claim client visual
inspection or persisted chunks at that distant coordinate. No terrain preset,
height tuning, teleport, block edits or bulk chunk generation was performed.

At 0 players, m8a.large / Xms 1G / Xmx 4G / container 6 GiB unchanged:

| Observation | Result |
|---|---|
| Container memory / CPU sample | 1.92 GiB / 6 GiB; 2.49% |
| Host CPU busy, 1-second sample | 0.51% |
| JVM RSS / lifetime-average CPU | 1,839,532 KiB (about 1.75 GiB) / 20.7% |
| Host available memory | 5,562,060 KiB |
| Tick target / mean | 20 TPS / 0.1 ms; P95 0.2 ms, P99 0.4 ms, 100 samples |
| Memory pressure / OOM | PSI some/full zero; OOMKilled false; no OutOfMemoryError |
| Container start → Minecraft Done | 16:30:30.174 → 16:31:20.711 UTC, about 50.5 s |
| Minecraft reported startup | 25.183 s (not the full EC2/Admission lifecycle) |
| Biome lookup | 2.05 s; one warning at that time: 2005 ms / 40 ticks behind |

The lookup briefly stalled the server thread; no sustained overload was observed.
These are short samples, not a multiplayer or chunk-generation throughput benchmark.
No host resize was performed. An upstream Create update-check labelled its same
base version outdated; Wishicraft did not resolve latest or replace any fixed jar.

### Normal STOP and final production

STOP `op-49153de4-38c3-46d8-aab6-2769b3ce3330` succeeded at 16:41:00.701333 UTC.
The normal host path executed save-all flush, persisted save proof, graceful
service stop and exact stopped-container cleanup. Workflow Reconcile at
16:39:48.619960 observed matching target/run with receipt phase stopped and
container not-found **before** StopEc2. Raw receipt was not separately fetched
after shutdown; success of the verified host path and this live probe are the
stop evidence. EC2 stopped, DNS deletion/INSYNC and final healthy Reconcile followed.

Final held preflight 16:41:41 UTC: STOPPED/HEALTHY, EC2 stopped, 45/45 alarms OK,
no Current Operation/Lock/workflow/active SSM/session/DNS, all three queues empty.
Existing Game/whitelist records, nine snapshots and sixteen backup/provenance
records were unchanged. While the new Game was running, all old Game trees and
create-survival's initial owner matched the stopped baseline exactly. No final
inspection boot was added; normal STOP was bound only to the new Game's container.
Data EBS identity/attachment/layout were preserved; its new-Game contents are an
expected addition. Registry gained only the new Game. Historical evidence was not edited.

All three ingress functions were restored to recorded ordinary UNSET concurrency
at 16:42:11 UTC, only after these gates passed. A full readback at 16:43:29 UTC
confirmed the same safe final state and all three ordinary concurrency settings.
Actual client connection is next:
Minecraft 1.21.1, NeoForge 21.1.219, Create 6.0.10 and Farmer's Delight 1.3.4 are
required. Terralith 2.6.2 / Tectonic 3.0.26 / Lithostitched 1.7.12 are server-side,
client-not-required by fixed metadata; omission on a real client remains to be
tested by the user. JEI is outside the Game package. The server is stopped, so use
a normal authorized START for that test; do not bypass whitelist policy.

Official exact versions:
[Create](https://modrinth.com/mod/create/version/UjX6dr61),
[Farmer's Delight](https://modrinth.com/mod/farmers-delight/version/XTVZDOol),
[Terralith](https://modrinth.com/mod/terralith/version/IY93YaEe),
[Tectonic](https://modrinth.com/mod/tectonic/version/vNrkxC3z),
[Lithostitched](https://modrinth.com/mod/lithostitched/version/vioNV2Gt).
