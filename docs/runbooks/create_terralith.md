# Create + Terralith + Tectonic

Repository candidate, 2026-09-21. Production migration, CREATE and materialization
are not yet performed. The user authorized qualification and, after its gates
pass, the existing normal STOP, guarded release, new CREATE/START/STOP. They also
explicitly authorized the limited catalog migration described below.

Local qualification: 1,512 tests passed; Ruff lint/format and mypy (218 source
files) passed; package-enabled Control Plane CDK synth passed. Real Docker
qualification runs on the existing Linux CI because this checkout has no Docker
CLI. CI and all production steps remain pending until their evidence is recorded.

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

Pending. Docker and production results must be appended with exact commit/run/
Operation IDs and observations; this section must not imply success in advance.

Official exact versions:
[Create](https://modrinth.com/mod/create/version/UjX6dr61),
[Farmer's Delight](https://modrinth.com/mod/farmers-delight/version/XTVZDOol),
[Terralith](https://modrinth.com/mod/terralith/version/IY93YaEe),
[Tectonic](https://modrinth.com/mod/tectonic/version/vNrkxC3z),
[Lithostitched](https://modrinth.com/mod/lithostitched/version/vioNV2Gt).
