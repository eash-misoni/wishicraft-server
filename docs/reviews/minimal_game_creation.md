# D-105 Minimal Game Creation

Repository implementation delegated 2026-09-13. Production **not applied**; approval is a separate gate.
This is D-101's third implementation unit. D-096/097/098/102/103/104 remain applicable.

## Registration and identity

Admin uses the existing authenticated manage Web. The form contains display name, initial numeric
seed, and RESET capability (default disabled). Confirmation explains persistent metadata and the
absence of deletion. Runtime is the existing pinned Vanilla 26.2 / itzg Java 25 configuration;
there is no selector, new Package/Preset/Template system, environment editor, or runtime extension.

Display name is NFC, trimmed, 1–80 characters, without control characters, `<`, `>`, slash or
backslash. It never becomes a path or resource identifier. Duplicate names are permitted;
manage controls distinguish them with an opaque Game handle suffix. There is no name uniqueness index.

Seed crosses JSON as a decimal string to preserve Java's full signed 64-bit range. No string-seed
generalization, floats, exponents, booleans or out-of-range numbers. Blank is represented by null
and deterministically resolved once in the registration transaction. Explicit zero is numeric zero.
For RESET-enabled Games, fixed seed equals this initial seed. New mode retains D-098's
Operation-derived signed 64-bit seed. Retain-previous=3 and minimum-free=4 GiB are the existing
defaults; these are not form controls.

The existing actor-bound Web request key is retained. `SHA256("wishicraft-create-v1|" + key)`
supplies the stable Game and CREATE Operation suffix. Domain-separated hashing supplies a random
initial seed when blank. Same actor/request/payload replays one result; a different payload
conflicts. Different actors have different keys. Idempotency and terminal Operation records have
no cleanup TTL. Browser storage keeps the pending request across reload and re-login; transport
uncertainty never authorizes a replacement request.

## Shared Admission and atomicity

The existing Web session determines actor/Guild/roles. The shared authorization policy makes CREATE
Admin-only at both Web and Admission. Discord OAuth role freshness remains the 900-second session.
No `/mc create` is introduced. IAM-authenticated adapters are the same trust boundary as D-104;
browser actor/role fields are rejected. Existing CSRF, exact Origin, no-store, host-only cookie and
old execute-api rejection remain in force.

One DynamoDB transaction writes Game, terminal SUCCEEDED Operation, Idempotency and membership in
the existing Games table's small `registry-game-creation-v1` item. It contains only a string set of
dynamic Game IDs. Legacy A/B membership comes from their existing catalog. Missing registry item
means no dynamically registered Games. Atomic ADD preserves concurrent registrations; no scan,
new table, name registry, or A/B rewrite is needed. DynamoDB item/transaction size limits remain
fail-closed limits; this slice does not promise unlimited registry/descriptor size.

CREATE does not acquire or publish a runtime lease and does not change SystemState. Lease records
now carry operation_type. A CREATE ConditionCheck permits absence or a known non-BACKUP runtime
lease. It rejects BACKUP and unknown legacy lease types. BACKUP therefore sees stable membership
through descriptor freeze and Snapshot creation; CREATE may coexist with START/STOP/SWITCH/RESET.
Registration does not stop or delay these workflows by owning their lock. A transaction conflict
returns conflict; uncertain AWS outcomes retain the same request for read-back.

CREATE dispatches no EC2, Docker, SSM, DNS, Snapshot, queue, Step Functions or host command.
Existing Operations Stream consumers skip Web CREATE's absent Discord delivery metadata.

## Minimal Game and first materialization

Existing Game schema/lifecycle, package/runtime reference, world.generation=1, timestamps and
UNMATERIALIZED are reused. New `creation` records creator, CREATE Operation identity, fixed runtime
digest and optional RESET policy. `world.seed` stores the resolved numeric initial seed. A/B keep
their existing records, seeds, policies, world references, generations and paths.

`UNMATERIALIZED` means registered / never successfully READY. It is not evidence of an existing
stopped world. Preparation or a failed first start may have left owned files; the registration stays.
The selected data source is `/srv/minecraft/games/<server-generated-ID>/server`, the deterministic
initial anchor. No first-start retry allocates a new Game, generation or directory.

The existing START target path, also used by SWITCH's START half, authorizes the registered Game
and fixed runtime at the backend and host. The host reads canonical Game metadata under its existing
flock after exact Operation/lease validation. Mount identity is checked before preparation; the
normal filesystem preflight follows it. Stale Operation/lease/runtime protections and exact
container/run observation remain mandatory.

`games/<Game>.initial-owner.json` is root-owned, outside the Minecraft-writable directory. It stores
the immutable creation/seed/path plan, initial file hashes and preparing/prepared/initialized phase.
An owner record is fsynced before new files. Retry accepts matching owned files; unknown directories,
symlinks, hard links, wrong content, wrong owner or another device fail closed. Initial configuration
uses the existing default whitelist and online-mode/whitelist enforcement. It never copies another
Game's world, OP/ban state or mutable files. Existing runtime machinery supplies secrets.

The server directory is the same permanent initial anchor already understood by RESET. There is
no fabricated RESET source or fake prior world. READY remains an observed runtime/endpoint fact;
only the existing successful START/SWITCH completion path marks Game MATERIALIZED, under lease
ownership. STOP/restart use the ordinary exact-target paths. Initialized-world disappearance is
corruption and cannot become permission to regenerate.

## Failure, RESET and recovery

Registration survives first-start failure. A preparing owner may resume only with the same plan
and exact initial files. A prepared world can finish first generation at the same path. A receipt
or SSM outcome that remains unknown uses the existing owned/stale recovery boundary; a replacement
run cannot conceal it. Unknown data is preserved. No automatic Game delete, other-Game rollback,
replacement directory, or manual guessed cleanup is part of recovery.

RESET rejects unmaterialized and reset-disabled Games. For a materialized dynamic Game, canonical
creation policy is reused by Admission, Web, CP plan preparation and host authorization. D-098's
fixed/new seed, capacity gate, configuration inheritance, root owner chain and retention cleanup
remain the same. Initial server data stays the protected legacy anchor. Old managed generations
are retained/cleaned by the existing contract; no new cleanup implementation is introduced.

Shared-v2 Snapshot tags, physical volume protection and durable provenance tables are unchanged.
Recovery description schema 2 adds the creation configuration and permits N registered Games,
including unmaterialized ones. Each Game retains its materialization state, seed, creation policy,
world/current reference and deterministic data_source. Legacy runtime manifest membership remains
A/B; dynamic records must reference that exact fixed manifest digest. The default initialization
configuration accompanies it for recovery of never-started Games. Owner records and actual files
are protected in the same EBS Snapshot, not duplicated into a new manifest service.

Old schema-1 recovery JSON/digests are validated unchanged. New schema-2 descriptions are frozen
before Snapshot intent and persisted in the existing provenance. An unmaterialized Game is normal,
not a backup anomaly. Metadata after the last Snapshot is not retroactively in older provenance;
EBS loss still loses progress after the latest external backup. Restoring one Game remains isolated
extraction, not a whole-volume rollback of other Games.

RETENTION stays volume-wide newest seven, dry-run-only. DeleteSnapshot is not released. Snapshot
count is not a release criterion. No Game delete/archive/purge, whitelist editor, OP/ban management,
runtime selector, Package/Preset/Template or public publication workflow is added.

## Web, infrastructure and rollback

Manage lists the operational registry and shows detail, initial seed, RESET capability, registered
versus materialized status, selection and last observed running state. START/SWITCH remain separate
explicit actions. Public `web/games.yaml` and the 13-page guide remain independently authored.
Creating a Game never publishes client requirements or adds a guide page.

Web reuses GetItem and exact Admission invocation; no business writes or new AWS action is granted.
CP readers gain Games GetItem where needed; START gains its narrow materialization UpdateItem;
Admission's existing transaction permissions cover registration. Target gains Games GetItem only.
No new EC2/SSM/EBS/Snapshot/DNS/workflow permission or provisioned resource is needed for CREATE.
The host upgrade changes its contract file/wrapper and adds the first-preparation helper, preserving
the existing Compose/runtime.env/manifest digest and all A/B files.

No new always-on resource cost. CREATE consumes bounded request/transaction/storage usage; worlds
use existing shared EBS only after first materialization, and stopped Games add no EC2 compute.
Normal future workload can grow shared disk usage; creation does not reserve unlimited disk.

Before any dynamic Game exists, rollback can restore the captured CP/Web/Target configurations and
verified predecessor host artifacts. After registration, retain dynamic registry/recovery readers
and host support: `create_disabled=true` suppresses new registration without hiding existing Games.
Do not roll back to an A/B-only recovery writer, raw-delete metadata, move worlds, or erase owners.
Use a forward fix for runtime failures; unknown owner/data and result-unknown deployment stop release.

[Release procedure and approval boundaries](../runbooks/minimal_game_creation.md).
