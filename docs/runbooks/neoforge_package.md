# NeoForge package qualification (D-109, implementation in progress)

Repository-only slice; no production deployment, CREATE, materialization or Minecraft START.
The first isolated Docker candidate is Minecraft 1.21.1, NeoForge 21.1.219, Create 6.0.10 and
Farmer's Delight 1.3.4. The NeoForge version is a candidate until real Docker qualification passes.
Both downloaded mod jars declare NeoForge >=21.1.219 and exactly Minecraft 1.21.1; choosing their
shared minimum avoids resolving a moving latest version. The existing pinned itzg Java25 image
and host-wide 1G/4G/6GiB memory are retained for the initial qualification.

`config/game-packages.json` fixes exact Modrinth project/version/file IDs, filenames, sizes,
URLs and SHA-256. During review, mod bytes matched Modrinth's SHA-512 before deriving SHA-256.
The NeoForge installer matches its official Maven SHA-256. No jar is committed or published by
Wishicraft. The integration test downloads directly from upstream into an isolated temporary root.

Create's license separates MIT code and All Rights Reserved assets; do not assume the whole jar
is MIT or mirror it. Farmer's Delight declares MIT. Package metadata and links do not grant a
redistribution license. Availability of an exact upstream URL is not guaranteed: a missing URL
must fail closed, never select another version. Private runtime caches are not a download service.
The Create jar embeds Registrate MC1.21-1.3.0+67, Flywheel 1.0.6 and Ponder 1.0.82+mc1.21.1;
the outer jar hash also pins those bytes. Both selected mods require the client in this package.

## Current coupling under review

Game schema 1 stores package_id/package_version and runtime.class=default. Existing A/B refer to
vanilla/initial-fixed-version. Minecraft 26.2/VANILLA are fixed in common runtime.env and manifest.
Operation freezes that complete digest; dynamic CREATE and initial-owner also retain it. The
current protocol probe expects 26.2. RESET copies only the five approved server configuration
files into a separate generation; no mod config inheritance is currently implemented. Shared EBS
backup freezes all registered Game metadata and the complete runtime recovery description.

Game bind mounts already isolate /data per Game/selected generation. Loader libraries, mods,
configs and generated server files must remain inside that boundary. The implementation will
preserve common artifact verification and bind a package selection to immutable registration.
No production readiness is claimed by this initial candidate/test commit.

## Sources

- [Create exact release](https://modrinth.com/mod/create/version/UjX6dr61)
- [Farmer's Delight exact release](https://modrinth.com/mod/farmers-delight/version/XTVZDOol)
- [Create license](https://github.com/Creators-of-Create/Create/blob/mc1.21.1/dev/LICENSE.md)
- [NeoForge installer](https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.219/)
- [Pinned itzg NeoForge entrypoint](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/scripts/start-deployNeoForge)
