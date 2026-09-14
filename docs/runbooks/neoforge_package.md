# Pinned NeoForge Game package (D-109)

Repository/runtime support only. **No production deploy, CREATE, materialization or Minecraft START**
is authorized by this slice. Production remains D-108; A/B records, worlds, whitelist, snapshots,
instance, volumes, DNS and memory configuration are unchanged. Qualification evidence is recorded
below; enabling the capability is a separate release.

## Existing boundary and minimal extension

Schema 1 already stores `package.package_id/package_version`, `runtime.class=default`, world
`generation/current_id/seed` and the Game lifecycle. Legacy A/B use `vanilla/initial-fixed-version`.
Before D-109, Minecraft 26.2 and TYPE=VANILLA belong to common runtime.env/manifest; Operation freezes
that complete digest and D-105 CREATE/initial-owner retain it. The probe also expects 26.2.

The opt-in CDK context `game_packages=true` requires `two_games=true`, `reset=true` and
`game_creation=true`. Its manifest contains the complete reviewed package catalog from
`src/wishicraft/artifacts/game-packages.json`. The default context remains byte-compatible with
D-108. Image, Java, Compose policy, UID/GID, RCON and Xms 1G / Xmx 4G / 6144MiB remain common.
TYPE, Minecraft version and explicit NeoForge installer/version move to the verified Game
projection. Compose requires those variables and a package digest label; missing projection fails.
No field is excluded from the manifest digest. The catalog ships inside the existing Lambda asset;
there is no additional AWS resource or mutable package service.

New CREATE accepts optional `creation.package_id` (`vanilla` or `create-survival`); absence selects
Vanilla. Package selection is rejected until enabled. It copies the exact definition under
`Game.package.definition` and its canonical SHA-256 under `creation.package_digest` in the same
existing transaction. `creation.config_digest` still binds the complete deployed runtime. Retry
uses the existing actor/request identity and immutable payload. Game schema stays 1, runtime class
stays `default`, generation starts at 1 and CREATE remains metadata-only/UNMATERIALIZED. There is
no package update endpoint. A different package needs a separately reviewed new package version;
never edit the meaning of an existing package version.

Only two loader shapes exist: `{type: vanilla}` and `{type: neoforge, version, installer}`.
The definition contains Minecraft version and a bounded list of mods with exact version, upstream
project/version/file IDs, filename, canonical HTTPS URL, size, SHA-256 and `client_required=true`.
Floating versions, unknown loaders, ranges, path traversal, duplicate mods and alternate sources
are rejected. Both Create and Farmer's Delight are required on server and client for this package.
DynamoDB List serialization is supported without changing existing scalar/map representation.

## Qualified first package

`create-survival` package version `1` (sample display name **Create Survival**):

| Component | Fixed selection | Exact upstream identity |
| --- | --- | --- |
| Minecraft | 1.21.1 | Loader installer Minecraft target |
| NeoForge | 21.1.219 | Official Maven `neoforge-21.1.219-installer.jar` |
| Create | 6.0.10 | Modrinth project `LNytGWDc`, version `UjX6dr61`, file `V876RuGl` |
| Farmer's Delight | 1.3.4 | Modrinth project `R2OftAxM`, version `XTVZDOol`, file `xb3oJkla` |

Both exact mod jars declare NeoForge >=21.1.219 and Minecraft 1.21.1. Their common minimum was
qualified, rather than selecting the latest Maven release. The existing
`2026.7.2-java25@sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77`
itzg image runs Java 25.0.3+9 with this combination. No image/memory/JVM flag change is introduced.

| Artifact | SHA-256 |
| --- | --- |
| `create-1.21.1-6.0.10.jar` | `ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a` |
| `FarmersDelight-1.21.1-1.3.4.jar` | `139ad7696462c89c03eea463f805abffa552526c5dadaadae221dd9624cb197c` |
| `neoforge-21.1.219-installer.jar` | `140df0fa17fd438848051ecfa3d091081515ad12bfe34fa126405037ba01de44` |

At review, downloaded mod bytes matched Modrinth SHA-512 before computing the committed SHA-256;
the installer matched its official Maven SHA-256. Create embeds Registrate MC1.21-1.3.0+67,
Flywheel 1.0.6 and Ponder 1.0.82+mc1.21.1, pinned by the outer jar hash. Wishicraft verifies the
three inputs; the pinned NeoForge installer resolves its own fixed dependency graph through its
normal upstream integrity checks. This is not an offline mirror or a promise of byte-identical
logs/generated caches. Removal of an upstream URL fails closed; no latest/fallback URL is resolved.

No jar enters Git, release assets or CI artifacts. Create distinguishes MIT code from All Rights
Reserved assets; do not assume the entire jar is MIT or offer a Wishicraft mirror. Farmer's Delight
declares MIT. Private retained-volume caches serve that Game's runtime, not client downloads.
Clients obtain the exact files from upstream. Metadata is not a redistribution license.

## Materialization, isolation and recovery

Retained Data EBS layout reuses the current Game root and generation layout:

```text
games/<Game>.initial-owner.json          existing immutable first-materialization owner
games/<Game>/package-owner.json          root-owned exact Game/package plan
             package-cache/mods/*.jar   root-owned, verified private cache
             package-cache/*installer.jar
             package-projection.json    initial generation projection owner
             server/                    selected initial /data
               mods/                    verified copies, Minecraft UID/GID
               libraries/, config/, defaultconfigs/, world/, generated loader files
             worlds/<Reset>/package-projection.json
             worlds/<Reset>/server/     selected Reset /data
             worlds/<Reset>.owner.json  existing Reset owner/receipt
```

Under the existing verified mount, host flock, no-container proof and live lease, START validates
Game registration against the full manifest. Initial materialization retains its existing owner
protocol. The root-owned package owner precedes cache writes; the generation projection owner
precedes `mods/` writes. Exact valid files are reused. Downloads are bounded, size/SHA-256 checked,
written to `.partial`, fsynced and atomically renamed. Retry discards only owned regular partials;
unknown files, symlinks/hardlinks, conflicting owners and corrupt final files fail closed. A corrupt
final file requires explicit diagnosis/removal of that exact inactive cache/projection file before
retry; automatic recovery never deletes unknown data. World files are never removed by this code.
The lease is checked again after network acquisition and before runtime start.

`/data` is the selected Game/generation only. Its private package cache is mounted read-only at
`/wishicraft-package`; there is no common mutable mods/loader/config volume. NeoForge receives
TYPE=NEOFORGE, fixed VERSION/NEOFORGE_VERSION and an explicit verified installer path, with
NEOFORGE_FORCE_REINSTALL=true. Installer failure stops that start; it never falls back to Vanilla.
No MODRINTH_PROJECTS/latest resolver is configured. Missing/tampered jars, mismatched runtime
variables, package label or mounts are rejected by container verification and protocol observation.
The protocol version expectation comes from that verified package (legacy remains 26.2).

SWITCH/RESET require an exact zero-player RCON list response. Qualified NeoForge adds one trailing
ANSI reset (`ESC[0m`); only a verified NeoForge package accepts that observed suffix. Positive
counts, player names, extra lines and unknown controls remain rejected. Vanilla parsing is unchanged.
SWITCH saves, stops and removes the source container before destination projection. STOP reads
source Game registration when its Operation targets another Game. The destination gets its own
mods and generated libraries/configs; nothing from the source is copied or cleaned globally.
A/B with no creation provenance remain valid only as their known legacy Vanilla packages.

RESET remains new world generation in the same Game. It preserves the existing five baseline
server files and, for NeoForge only, UTF-8 files recursively in that Game's `config/` and
`defaultconfigs/`. Symlinks, hardlinks, devices and binary configuration fail closed. Empty config
directories need not survive. Source-file hashes are recorded by the existing preparation owner;
interruption retries converge only if the source still matches. `world/serverconfig`, players,
world contents, mods, libraries and generated server artifacts are not copied. The new world
creates its own serverconfig, including the retained defaults where the mod supports them. The
same Game package is re-materialized from its cache. No gamerule or custom settings migration is
implemented. Existing generation retention deletes only eligible old generations, not Game cache.

Whitelist projection remains authoritative Common + Game membership before start; mod configs
are not Global settings. BACKUP still snapshots the retained Data EBS and freezes complete Game
metadata plus complete runtime recovery content. That includes package owner/cache, selected and
retained generations, mod configs and world/serverconfig on disk. Recovery descriptor schema 2
and snapshot provenance remain unchanged; the complete definition participates in integrity
verification. Compressed Lambda recovery configuration is lossless and verified after decoding,
keeping the expanded catalog within Lambda's environment budget. RETENTION semantics are unchanged.
An isolated recovery must restore the Game root AND its existing sibling initial-owner record;
include package owners/cache and generation owners, not merely `world/`. Never use an older Vanilla
runtime to open a NeoForge world. A missing cache may require the exact upstream sources again.

`Game.package.definition` provides client requirements. Authenticated `/api/capabilities` also
returns `client_requirements` for new definitions (Minecraft, loader/version, exact mods/versions,
filenames/hashes and upstream links). Existing Web creation/detail rendering remains unchanged;
package selector/display and client installation guidance can be a small follow-up. No launcher,
automatic client installer or arbitrary modpack import is implemented.

## Separate future production release

This slice performs **none** of these production steps. User authorization and fresh preflight
are required for the future release:

1. Close Admission/CREATE using the existing D-108 maintenance procedure. Verify canonical caller,
   Desired STOPPED, EC2 STOPPED, no active workflow/lock/SSM, empty queues, no DNS, healthy EBS,
   backup/provenance and alarms. Use the established maintenance boot without normal Minecraft
   START to inspect no container/listener and capture the exact stopped receipt and full registry.
2. Generate a new review directory offline with
   `tools/dev-env run -- python -m wishicraft.game_package_migration --output <new-directory> --receipt <captured.json> --inventory <full-scan.json>`.
   This reuses the D-108 predecessor reconstruction and inactive-only installer. Only the exact
   legacy A/B + whitelist inventory is accepted; any D-105-created Game stops migration review.
   No durable record or data path is written by the bundle. Review actual host predecessor hashes,
   complete bundle transport hash, eight destination files, new common digest and preserved receipt.
3. Install the reviewed bundle under the existing maintenance procedure. Each file accepts only
   exact predecessor or exact target bytes; saved predecessors and atomic replacement support retry
   after any partial cutover. Package projection variables let preflight parse either old or new
   Compose during retry; they do not start or materialize any Game. Re-run until all eight hashes
   match before deploying/reopening any controller. Never invoke a historical migration bundle
   built from a newer HEAD as an unreviewed shortcut.
4. Deploy the existing control-plane stack with existing contexts plus `game_packages=true`,
   keeping CREATE closed until postflight. Inspect the CloudFormation change set: no replacement,
   new persistent resource or state-machine redesign. Host and all Lambda runtime digest/defaults/
   recovery content must agree. A/B registration and historical Operations/receipts remain untouched;
   retain old runtime artifacts and predecessor backups for their provenance/rollback.
5. Before any new Game exists, rollback can restore the exact eight predecessor states (the new
   helper was previously absent) and prior control-plane release under the same stopped gate. Keep
   all saved predecessors; do not rewrite old Operations. After a NeoForge Game has been registered
   or materialized, a blanket rollback to D-108 is no longer the same safe operation: keep its data
   and immutable registration, leave it stopped, and review a package-aware recovery/release plan.
6. Close maintenance STOPPED/HEALTHY. In a separate explicitly authorized usage step, perform the
   first D-105 positive CREATE with `package_id=create-survival`, verify immutable registration,
   prepare matching clients, then START and assess real 8GiB host load/player behavior. Qualification
   is a synthetic no-player server test, not proof of capacity for an arbitrarily large Create world.

## Validation evidence

- Candidate Docker qualification [34833169029](https://github.com/eash-misoni/wishicraft-server/actions/runs/34833169029)
  passed on `a725a3d`: exact image/three jar hashes, NeoForge 21.1.219, health/RCON, save-all flush,
  graceful exit 0/no OOM, restart, Xms1G/Xmx4G via Java argfile and container 6GiB.
  Logs identify Create 6.0.10 and Farmer's Delight 1.3.4; RCON resolves
  `create:andesite_casing` and `farmersdelight:stove` block IDs.
- Initial candidate run 34832636634 reached READY but failed the fixture's inline-JVM-argument
  assumption. NeoForge uses `@user_jvm_args.txt`; that failed run is retained, not counted as passing.
- `tests/integration/neoforge_host_docker.py` exercises real operation-v2/Compose with synthetic
  AWS/systemd/mount boundaries: metadata CREATE, first materialization, retry, Vanilla→NeoForge,
  NeoForge RESET, return to Vanilla, preserved scoreboard, mod isolation and whitelist projection.
  Final integrated CI results are added at closeout.
- Unit tests cover strict schema, complete manifest hashing, registration/serialization, partial
  artifacts, cache/projection corruption, world preservation, RESET retry, installer interruption
  at each of eight file replacements, legacy compatibility, recovery compression/resource parity.
  Local Docker is unavailable; real Docker qualification runs on disposable Linux CI with full
  production memory limits. No reduced-memory production contract is substituted.

## Sources

- [Create exact release](https://modrinth.com/mod/create/version/UjX6dr61)
- [Farmer's Delight exact release](https://modrinth.com/mod/farmers-delight/version/XTVZDOol)
- [Create license](https://github.com/Creators-of-Create/Create/blob/mc1.21.1/dev/LICENSE.md)
- [NeoForge installer](https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.219/)
- [Pinned itzg NeoForge entrypoint](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/scripts/start-deployNeoForge)
