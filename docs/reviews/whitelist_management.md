# D-106 Whitelist Management

**Accepted release contract; production execution pending.**
D-101 slice 4. D-105 remains production deployed, positive CREATE/materialization deferred.
This document owns the Whitelist semantics; the [runbook](../runbooks/whitelist_management.md)
owns migration, release evidence and rollback. Production release is authorized against ade0d89 with an empty-Common migration amendment.

## Current implementation audit

The production-supported runtime is the pinned itzg 2026.7.2 Java25 image, Minecraft Vanilla 26.2,
online-mode=true, white-list=true, enforce-whitelist=true, UID/GID 993. Existing runtime.env has
neither WHITELIST nor WHITELIST_FILE. The pinned
[start-setupRbac source](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/scripts/start-setupRbac)
invokes whitelist management only when those inputs are set. Thus existing /data/whitelist.json
is a manually maintained persistent file, not rebuilt from a container environment list.
[itzg's manual-file interface](https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/#whitelist-players)
supports ENABLE_WHITELIST with an externally managed file. This release keeps that existing mode;
no Compose/environment/image/version or runtime digest changes are required.

Each Game has its own current data source selected by Games.world.current_id. A uses its initial
server directory; B uses its selected managed generation. Minecraft's whitelist commands persist
there. Existing START/SWITCH reuse that file; D-098 RESET copies it among Game settings. Shared-v2
Snapshot protects the files across the whole Data EBS, including retained old generations. The
initial configured player was resolved from Mojang in the original setup; configuration is an
initial value, not evidence that the current A/B files still contain exactly that membership.
Current file contents/owner/mode require maintenance inspection while the stopped EC2 is online.

The historical phase8 redesign follow-up proposed file-authoritative per-Game settings. It was
never an Accepted Whitelist contract. It does not meet this slice's stopped editing and live
Common inheritance needs and is superseded as a candidate by this bounded policy model.

## Source of truth and composition

Control Plane is authoritative. Existing Games storage holds a separate
`policy-whitelist-common-v1` item and optional `policy-whitelist-game-v1:<Game ID>` items.
They are policy records, not registry Games, and are never enumerated as Games. Existing A/B
Game records are untouched. Each policy contains canonical JSON with revision and a bounded map
of UUID to last-known Java name. Maximum 256 entries per policy, at most 512 effective entries.
There is no new table, index, directory service, profile hierarchy or always-running worker.

Initial migration sets Common empty and stores each current Game's complete membership as its
Game-specific policy. Shared A/B membership does not imply future-Game permission; Admins must
explicitly add Common membership after release. The intersection migration candidate is superseded.

**Effective = Common ∪ Game-specific.** Common grants access to every registered Game, including
future registrations. Game-specific is additional access for that Game. There is no deny layer.
Deleting a Game-specific duplicate leaves the Common permission effective. To exclude a player
from one Game, remove them from Common and explicitly grant only the desired Games. UUID dedupes
membership; Common's last-known name wins when both sources contain the same UUID.

An absent per-Game policy means empty revision 0. An absent Common policy is an incomplete
migration and fails closed; it never silently becomes an empty access list. UNMATERIALIZED Games
inherit Common logically and need no filesystem, EC2 start or world generation to edit policy.
CREATE remains metadata-only, with no policy list copy or eager materialization.

## In-game changes and application

Strategy A, Web-authoritative, is selected. In-game changes are temporary and never update Common
or Game-specific policy. Graceful STOP does not import them. Crash does not promote the persisted
file to authority. At the next inactive START preparation the policy overwrites runtime membership.
An in-game removal of a Common member is likewise temporary. UI states this limitation explicitly.

Lifecycle import (B) would need an applied-policy baseline and conflict handling when Common or
Game-specific policy changed while the process ran. Common removals also cannot express a Game
deny in the additive model. Explicit import (C) would introduce another write capability and a
separate snapshot/identity validation path. Neither is needed for this first release.

Running edits are **saved, next-start application pending**. No immediate RCON reload, kick,
restart, SSM command or asynchronous apply Operation is dispatched. The existing RCON path is
bound to a lifecycle Operation/lease and exact process identity; online apply would need its own
tracked command/retry owner. The benefit is deferred instead of adding that workflow now.
An access removal therefore does not immediately revoke a running server's permission. Manage
shows desired policy and says runtime application is unverified; it never claims saved means applied.

The common START target path, including SWITCH and RESET's destination START, reads Common and
Game-specific policy under the lifecycle lease/host flock. After mount/path/owner preflight and
confirmation that no runtime container exists, it atomically replaces only target whitelist.json.
The existing file must be regular, single-link, UID/GID 993, non-world/group-writable, same device.
The replacement has ownership/mode before rename and is fsynced, including its directory. Unknown
redirection/ownership fails closed. Disabled or ambiguous online-mode/whitelist/enforcement properties
also fail closed; the helper does not silently run an unprotected server. Same-run retries with an existing exact container do not rewrite
a running file. A failed prepare keeps policy, registration, seed, generation and planned path.

D-105 initial owner and D-098 RESET preparation remain unchanged. RESET may copy the old settings
as preparation input, but that whitelist is only a provisional file: authoritative policy is
projected before destination Minecraft starts. No old-generation import occurs. Fixed/new seed,
capacity gate, owner chain and cleanup/retention are unchanged. Other Game directories are untouched.

## Identity, authorization and transaction

The form accepts Java player names, 3–16 ASCII letters/digits/underscore. Add resolves through the
official `https://api.mojang.com/users/profiles/minecraft/<name>` endpoint. A read-only endpoint
probe returned HTTP 200 during preparation. Lookup uses HTTPS, a fixed host/path, no redirects,
three-second timeout, one attempt, maximum 4096-byte response, strict UUID/name matching. Unknown
profile, provider failure or timeout rejects without mutation. There is no fabricated UUID or
third-party fallback. Accepted transactions store UUID and last-known name; a rename does not
change access identity. Re-adding the resolved identity refreshes its name. Remove uses an opaque
member reference derived from a stored UUID; users never enter UUIDs.

Authenticated manage may read membership. Mutation is Admin-only in Web and shared Admission.
Discord session role freshness remains 900 seconds. Existing exact Origin, CSRF, no-store,
host-only cookie, old execute-api rejection and browser actor-spoof rejection are reused.
Minecraft profile identity is separate from the authenticated Wishicraft admin identity.
Public guide receives no names, UUIDs, counts or access policy. No Discord command is added.

WHITELIST is a short terminal SUCCEEDED Operation. One transaction writes the policy using exact
previous canonical JSON as CAS, actor-attributed Operation and durable idempotency record. It
ConditionChecks absence of the lifecycle Lock, and ACTIVE Game existence for a Game-specific edit.
It never acquires that Lock or changes SystemState. This conservatively rejects edits during any
lifecycle work, including BACKUP's complete freeze interval. A RUNNING idle Game has no lifecycle
Lock, so its policy remains editable. Changes do not wait in a queue.

Same actor/request/payload returns the original result; different payload conflicts. Another actor
has a distinct request key. Lost reply/reload retains the same browser request for read-back; UUID
resolution is not repeated after a transaction is recorded. Revision conflict requires refreshing
the policy and deliberately making a new request. A no-op save records an Operation without
incrementing policy revision or altering membership, suitable for safe production write evidence.

## BACKUP, recovery and extraction

New schema-2 recovery documents add optional `runtime.whitelist_policy`, containing Common plus
an explicit policy (including empty policy) for every captured registered Game. Registry and policy
mutations cannot commit while BACKUP holds the existing Lock. The existing frozen Operation JSON,
digest, Snapshot tags and durable provenance protect the exact policy; no new manifest service or
storage is introduced. Reader validates the complete captured Game set and every policy.
Old schema-1 and old schema-2 documents remain valid without this extension and are not rewritten.

EBS alone does not recover the new policy. Full recovery restores the captured Common and per-Game
records from durable provenance, with a new environment's identities resolved separately. Isolated
extraction exports the selected Game's specific policy and separately the captured global Common
policy. Never infer Common by copying/unioning runtime files, or merge it automatically into a live
environment. An operator must choose whether to restore that global policy or explicitly grant its
members only to the extracted Game, preserving destination access deliberately. Old descriptors
retain their historical file-authoritative recovery boundary and require explicit migration before
enabling D-106. Runtime files in old generations do not supersede captured policy.

Policy changes after the last successful BACKUP can be lost with Control Plane loss. This release
does not add continuous policy backups. Snapshot newest-N, dry-run and unreleased DeleteSnapshot
remain unchanged. D-105 positive CREATE/first materialization remains deferred, and no new Game is
required to release Whitelist Management.
