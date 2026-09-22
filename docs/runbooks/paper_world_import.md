# D-110 Same-runtime Paper world import

Status: repository implementation in qualification; **not deployed or imported**.
Source mutation, final archive and production release require the separate concrete
execution boundary below. Current roadmap: D-101 demand-driven Runtime Extension.

**IMPORT preserves package/runtime identity. Version changes are performed by a future explicit UPGRADE operation.**

## Confirmed source and scope

[Read-only inventory evidence](../evidence/paper_source_inventory_2026-09-22.json) on 2026-09-22 identified `/opt/minecraft2/wishinkaiwai`.
The user corrected and approved this exact identity, replacing the initial 26.1 recollection:

| Item | Observation |
|---|---|
| Host/service | `162.43.29.104`, `minecraft-25566.service`, active/running |
| Working directory / command | `/opt/minecraft2`; `/usr/bin/java -Xms1G -Xmx3G -jar server.jar nogui` |
| Minecraft / Paper | `26.1.2` / `26.1.2-53-39a1aa5` |
| Paper commit | `39a1aa5c7fa9742accf82c247a0ea18014788b5f` |
| Source JAR | `/opt/minecraft2/server.jar`, 52,926,064 bytes |
| SHA-256 | `6934188878fc351e1be5bfba5f2b8c4591224886e4b34e3de09dbec68a351caf` |
| Java | Amazon Corretto `25.0.3+9-LTS`; process exe matches Java 25 installation |
| level-name / online-mode | `wishinkaiwai` / `true` |
| DataVersion / level Version | `4790` / `26.1.2` |
| Actual saved seed | `-3498469689692331574` in overworld `data/minecraft/world_gen_settings.dat` |
| Size at inventory | 3,515,768,253 logical bytes; 1,541 files; running observation, not frozen archive |
| Last level.dat update | 2026-09-22 01:14:39 UTC |
| Free filesystem space | 72,696,311,808 bytes at initial inventory; must recheck |
| Players online | 0 at status probe; must recheck immediately before stop |

The outer Paperclip metadata, runtime JAR manifest, version_history.json and live
Minecraft protocol response agree. Official [build 53 metadata](https://fill.papermc.io/v3/projects/paper/versions/26.1.2/builds/53)
reports the same SHA-256 and size. The immutable official object is pinned in
`game-packages.json` as `vps-survival`, package version `1`. Downloaded bytes must
also pass size/hash verification. No latest lookup, range or fallback version.

The two ~1.44 GB `world` directories under `/opt/minecraft` and `/opt/minecraft2`
have January 2026 level timestamps. Other small worlds also exist. They are not
selected. The active service's cwd, level-name, current timestamp and populated
world contents identify the selected world, independently of its greater size.

## Source state and configuration

Preserve the entire `wishinkaiwai` tree without normalization. Its three dimensions
are `dimensions/minecraft/{overworld,the_nether,the_end}`. Inventory counted 1,085,
62 and 119 `.mca` files respectively across region/entities/poi. `players/data`,
`players/stats` and `players/advancements` hold the player state. No custom dimension
namespace was found. `datapacks/bukkit/pack.mcmeta` is the sole datapack file;
level metadata enables vanilla, file/bukkit and paper. Keep it, along with maps,
world border, gamerules, chunks/entities, structures and Paper persistent data.
Never move overworld `data/minecraft` to the root.

Twelve current `.dat` player files are present; fourteen stats and advancements
JSON files include historical identities. The owner's UUID matches the existing
Wishicraft profile. Its NBT reads inventory=26 items, ender chest=22 items and a
valid overworld position. This is source-side inspection, **not target login**.
Some saved players still have DataVersion 4671 while current ones have 4790.
Same-build Paper may perform its normal lazy reads/saves of old records; there is
no `--forceUpgrade`, newer runtime or explicit full conversion. Preserve original
bytes before boot and distinguish normal saves from unexpected differences.

No externally installed plugin JAR or plugin descriptor was found. `.paper-remapped`
contains implementation cache; `spark` has bundled-profiler config/temporary files;
`bStats` has telemetry settings. These are not demonstrated gameplay/worldgen
plugin dependencies and are not imported. The pinned Paper runtime owns its bundled
components. Reinventory before final capture; a newly required/unknown plugin blocks
production. This is not a plugin-upload framework.

Preserve four reviewed server-local configs inside only this new Game:
`config/paper-global.yml`, `config/paper-world-defaults.yml`, `bukkit.yml`, `spigot.yml`.
Their exact hashes are part of import provenance. Nonempty secret/password/token
settings are refused; resolve them separately without recording secret values.
The source has Velocity disabled and Spigot bungeecord false. Per-dimension
`paper-world.yml` contains only `_version: 31` and remains within the world tree.
The runtime uses `SKIP_DOWNLOAD_DEFAULTS=true`, preventing remote default replacement.
No common Wishicraft config is overwritten.

Source properties: difficulty=easy, gamemode=survival, hardcore=false,
generate-structures=true, level-seed empty, level-type=`minecraft\:normal`,
generator-settings=`{}`, view-distance=10, simulation-distance=10. Saved world
metadata currently says difficulty=normal; preserve both facts rather than deriving
world difficulty from properties. The importer projects only these allowlisted
properties plus fixed level-name, online-mode=true and enforced whitelist.
Port/RCON and runtime operational authority remain Wishicraft-owned. Never import
source server.properties, whitelist.json, ops.json or either ban list. Initial
Game-specific whitelist is empty; ordinary Common ∪ Game-specific projection follows.

`/opt/minecraft/backup/{auto,manual}` were empty. No Minecraft backup timer or ubuntu
backup cron was found. Provider backups/manager backup behavior are **not established**.
Source unit has Restart=on-failure, SIGTERM, TimeoutStopSec=90 and null stdin.
RCON is disabled. A final stop procedure must establish a reliable save/stop channel and capture actual
save/exit evidence; it may not assume an interactive console or tolerate forced kill.

## Registration, staging and prepared commit

Reuse D-105 CREATE with `package_id=vps-survival`, explicit saved numeric seed,
`reset=false` and an `import` provenance object. This is operator-assisted; no upload
UI, new operation/state machine, table, bucket or IAM expansion is introduced.
Existing CREATE authorization, actor-bound idempotency and immutable creation/package
records apply. A Paper CREATE without import provenance is rejected, preventing
accidental empty-world generation. Existing Games are never IMPORT destinations.

The provenance schema is validated by `world_import.validate`: exact source runtime,
Java, DataVersion, seed, level-name/online-mode; archive SHA-256/size/count/expanded
size/tree digest; captured UTC timestamp; save/stopped/sync proof assertions; reviewed
config hashes; allowlisted properties; and target package digest. Build/artifact/version
must be identical, not merely numerically compatible. These assertions are operator
attestations linked to separately retained save/stop evidence, not remote measurements
performed by CREATE. Do not manufacture them for a live copy.

CREATE yields ACTIVE/UNMATERIALIZED, generation 1. Stage the validated immutable
archive copy at `/srv/minecraft/imports/<archive-sha256>/source.tar`, root-owned,
read-only. Directory ownership/mount and free space are rechecked. Final archive
metadata may be prepared before CREATE; no Game is created until its source identity
and provenance are known. Archive/security validation and isolated real-world boot
must succeed before production first START.

An operator can run `tools/dev-env run -- python -m wishicraft.import_archive
--archive <copy> --manifest <provenance-json> --output <new-temporary-directory>`
for offline security/NBT validation. This does not perform runtime boot, CREATE or
any Game/AWS mutation; it retains the extracted copy and private validation evidence.

Normal START's existing host lock, mount and lease path prepares the imported world
**before launching Minecraft**. It writes an initial preparing-owner record, extracts
to a new staging attempt, checks exact tree/config/world identity, adds authoritative
server.properties and empty whitelist, fsyncs files/directories, and records validation.
A fresh Operation/lease read immediately before rename guards the prepared commit.
Rename into the absent initial server directory is the visibility boundary. Then the
same root-owned initial-owner becomes prepared. The new Game remains UNMATERIALIZED
until ordinary START/READY completion. No generation increment or fake RESET is used.

The runtime selects the root-owned, read-only verified Paper JAR using
`TYPE=PAPER`, `PAPER_CUSTOM_JAR`, exact VERSION/PAPER_BUILD and LEVEL=wishinkaiwai.
The pinned itzg 2026.7.2 script supports this local JAR path without build discovery.
Package cache/hash, container environment/digest/mount and READY checks remain active.
Normal STOP's persistence check recognizes the imported name only through the matching
root-owned initial-owner; other Games retain `world`.

## Archive security and retry

The first format is **uncompressed USTAR**, no PAX/GNU extension records or compression.
A fixed-size raw-header pass rejects dangerous extensions before tarfile can expand
metadata. Only regular files/directories are accepted. Absolute paths, empty/dot/dotdot
components, backslashes, control characters, non-NFC names, case collisions (including
implicit parents), duplicate entries, symlinks, hardlinks, devices, FIFO, sparse records
and nonzero trailing content are rejected. Maximum 100,000 files, 200,000 members,
16 GiB archive/expanded bytes, path depth 32; reserve 4 GiB free at extraction.
The archive root permits only wishinkaiwai and the four named configuration files.
The importer validates level.dat's exact version/name/DataVersion, actual seed,
three dimensions and readable playerdata no newer than the runtime. Unknown custom
dimensions require review. Hashes are recorded relative to the unchanged tree layout.

| Interruption | Retry |
|---|---|
| Archive staged | Verify same archive hash/size and immutable CREATE provenance |
| Extraction interrupted | Preserve failed attempt; extract into a new unique attempt |
| Validated | Reuse only exact owned validation receipt and matching tree |
| Before rename | Fresh lease check; target must be absent |
| Rename complete, owner not prepared | Candidate absent and target exact tree prove the same commit; finish owner |
| Prepared/initialized | Require matching plan and existing level.dat; never regenerate missing world |

Different archive, Game, package, unknown target directory, changed validation candidate,
lease loss or version mismatch fails closed. Do not erase failed evidence to force retry.

## Existing Game protection and release

A/B/create-survival/create-terralith definitions, worlds, generations, whitelists,
creation/owner and historical Operations/backups/provenance are unchanged. The new
complete manifest is `0aa138990a89bad00ccdeeb339ded8e90680c8745ef1a82c9b882abc0c130c1a`.
The frozen `paper-transition.json` contains full historical/predecessor/successor
manifests and has its entire file SHA pinned in executable code. It permits only known
creation-provenance identities into this exact successor; no digest fields are dropped.
Existing package definitions are identical. Compose gains four Paper inputs with legacy
values/defaults, while runtime.env, memory, image, platform and resource ownership stay
unchanged. Old Operations still cannot run against a different current manifest.

`python -m wishicraft.paper_import_migration --output <new-root> --receipt <json>
--inventory <json> --host-config <file>` builds the stopped-host review bundle offline.
It checks exact production predecessor config/hash, complete Game registry and package
identity, saved stopped receipt and unchanged canonical renderer; the existing installer
rechecks installed bytes/absence, unit/container state before replacement. It never writes
Game records/worlds or replays the completed Terralith migration. CP/Web code and current
manifest release require a guarded ChangeSet, unchanged persistent resources/IAM and
existing workflow semantic no-op review. No deployment is authorized by this document.

## Separate production/source mutation boundary

Before asking for GO, supply finalized commit/CI, exact affected host/CP/Web artifacts,
existing Game/whitelist/provenance snapshots, approved transport/staging path, isolated
runtime capacity, failure handling and expected downtime. Source downtime cannot be
estimated confidently before the actual transfer/isolated-validation path is measured.
No bucket creation or broader IAM is an implicit fallback for archive transport.

1. Recheck current players=0, health, actual build/hash, world/config/plugin identity,
   latest successful save and current backup. Confirm save/stop channel, no forced-kill
   fallback, capacity and downtime. **Pause before stopping VPS.**
2. Under separate GO, perform normal save, graceful stop and verify terminal exit/save,
   filesystem sync. Stop on uncertainty; no retrying new versions or forceUpgrade.
3. Create an immutable USTAR archive from the stopped source, record size/file count,
   exact tree hashes and source metadata; hash and retain an independent rollback copy.
   Never modify original source world. Exclude credentials and access-control files.
4. Use copies for safe staging validation and isolated same-build real-world startup,
   all three dimensions, datapacks, player NBT, spawn/save/stop/restart and tree-difference
   evidence. The immutable archive itself is never booted or altered.
5. Through normal authorized CREATE, register only the new Game. Stage validated archive
   on the existing Data EBS, then existing START prepares generation 1, READY and
   MATERIALIZED. Recheck existing Game invariants, perform normal final STOP and health
   observation. A separate bug stops this sequence; no chained fixes/restarts.
6. Rollback is to the retained stopped-source archive/original, not to a world previously
   opened in a different version. Avoid simultaneous source/target gameplay after cutover.
   Client verification is delegated only after server-side release gates pass.

## Verification and future boundaries

Repository qualification checkpoints (2026-09-22 UTC): implementation commit
`8e2466af518b13aa595dbd5456b7f13fcaed14d4`; isolated fixture correction
`e70dc5f390470ded4f3de4b586322e1765052dff`.
[Paper integration run 35683472535](https://github.com/eash-misoni/wishicraft-server/actions/runs/35683472535)
passed: synthetic source READY, three dimension markers, vanilla/bukkit/paper datapacks,
save/normal stop, identical prepared generation 1 tree, target READY twice with retained
markers and normal save/stop each time. Source archive hash remained unchanged.
The earlier failed run used a broadcast-command response as its assertion; the corrected
fixture directly tests the saved block. The NeoForge fixture separately excludes Paper
from ordinary CREATE because Paper requires explicit import provenance.

The first full CI unit suite passed 1,565 tests; local full suite passed 1,563 before the
last two focused cases, and the subsequent focused suite passed 49. Local lint/format,
type checking and four dev CDK synth targets passed. CI exposed one integration-only
JSON return annotation missing under its fresh type check; this is fixed explicitly.
The final commit's complete CI result must also pass before release. Local Docker is
absent; the Paper runtime evidence above is from the isolated Linux CI runner.

Production status remains unchanged: no VPS stop, final source archive/hash, AWS release,
new Game, real-world first START/MATERIALIZED or final target STOP. Therefore there is
no new production rollback archive yet, and client verification is not ready. Existing
A/B/create-survival/create-terralith production state has not been modified by this work.

Unit tests cover archive paths/types/collisions/limits, runtime pinning and mismatch,
source freeze assertions, generation 1, owned retry/rename crash, lease loss, missing-world
refusal, empty access projection and existing data preservation. Dedicated Linux Docker
CI generates a synthetic source with the exact Paper artifact, saves/stops/archives it,
uses the real importer and verifies dimension marker blocks across target start/restart.
Synthetic qualification does not prove the real VPS archive loads. Local Docker is
unavailable; do not call static/unit checks a successful local Paper boot.

UPGRADE/package revisions are not implemented. A future explicit UPGRADE must separately
design pre-upgrade durable backup, target revision, world upgrade, READY validation and
rollback from the pre-upgrade backup. Ordinary package updates remain prohibited.
RESTORE/EXPORT may reuse bounded archive inspection, tree hashing, provenance and staging
validation; replacement/selection, retention and export privacy require separate contracts.


Backup Lambda transport additionally uses `catalog-zlib-v1`: the code-distributed
fixed catalog is a zlib preset dictionary, not an omitted portion of the recovered
manifest. Decompression yields the full original bytes; existing digest validation
remains unchanged. Unknown codec, incomplete/trailing compressed data or >256 KiB
output is rejected. Old plain zlib environments remain readable. This addresses
the 4 KiB Lambda environment limit without new storage, IAM or persistent resources.
