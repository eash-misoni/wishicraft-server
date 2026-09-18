# Phase 8 Runtime heartbeat dev release

- **文書状態:** Canonical Runbook
- **対象:** `dev`

## Safety boundary

D-092のproducer、専用table、Target role、systemd service/timerだけをreleaseする。automatic STOP、EC2/DNS/Snapshot mutation、heartbeat stale alarmはこのsliceに含めない。

## Repository gate

1. full pytest、Ruff、mypy、shell syntax、Control Plane/Target synthを成功させる。
2. Control Plane diffはRetain付きRuntimeHeartbeats table、Target diffは同tableへのGetItem/PutItemだけであることを確認する。
3. replacement/deletion、instance/UserData/attachment/SG変更があれば停止する。

## Host install

Phase 8.3のrepository installerは新規source root `wishicraft-phase8-heartbeat-v2`とprobe v1.4 checksumを使用する。既設v1.3 probeの上書きは引き続き拒否する。Phase 8.3 monitoring適用ではこのinstallerを実行しない。Control Planeの転送型probe v1.4を使い、既設heartbeat producer/probeはそのまま維持する。

repositoryの固定7 artifactと`phase8_heartbeat_install.sh`を新しい専用temporary source rootへ転送する。各fileのSHA-256、owner/mode、既存target不存在を確認し、installerを一度実行する。任意payload/pathを受け取る常設interfaceは作らない。

installerはAWS CLI/Python存在を確認し、fixed artifactsをatomic installして`wishicraft-heartbeat.timer`だけをenableする。Minecraft Host Runtimeをstart/stop/restartしない。

## Verification

1. table TTL、key、Retain、index/streamなしをread-backする。
2. Target roleがtable限定GetItem/PutItemとcanonical LeadingKeysだけを持つことを確認する。
3. canonical START後にfirst heartbeat、60秒間隔の複数record、boot/instance/runtime/Game、READY、player count、empty_since、24時間TTLを確認する。
4. service restartはsame boot/fresh zero continuityだけを維持することを確認する。
5. stale/out-of-order fixtureのconditional Putが現recordを変更しないことを確認する。
6. canonical STOP後、EC2 stopped、DNS absent、Lock/Current Operationなしへ戻す。

STOP/shutdown transition中にprotocol observationがunknownとなったheartbeatはplayer countとempty_sinceをnullへclearする。EC2停止後に残る最後のitemは現在のruntime/player状態ではなく、`observed_at`が5分を超えればstaleである。TTL物理削除を待たず、停止後にproducer更新が止まることを確認する。

AWS CLI v2は存在しないitemへの正常なGetItemで空stdoutを返し得る。producerはこの境界をabsent previous recordとして扱い、それ以外のmalformed responseと区別する。

既存`MonitoringObservationUnknown`はSystemStateの観測鮮度を監視しており、RuntimeHeartbeatの鮮度alarmではない。長時間RUNNING E2Eで発火した場合は両recordの`observed_at`を混同せず、fresh Reconcile後のmetric recoveryを確認する。alarmを手動変更しない。

player出入りが必要な確認はoperatorへ一度だけ依頼する。unknownをzeroへ補正せず、recordをraw repairしない。

## Registered Game heartbeat correction — 2026-09-18

The installed producer was read on the stopped production Target during inspection-only
maintenance. `/usr/local/libexec/wishicraft/runtime_heartbeat_producer.py` was root-owned
0644, SHA-256 `831645ac04e0f8f0affe44dc51e071ec77ca0a2bdb2ddb251796c64b4bce229a`,
and byte-identical to the repository source at release HEAD `57b1ecf`. The enabled
`wishicraft-heartbeat.timer` invokes `wishicraft-heartbeat.service` every 60 seconds;
its exact command is `/usr/bin/python3 -m wishicraft.runtime_heartbeat_producer` with
`PYTHONPATH=/usr/local/libexec`. The dedicated service environment supplies table,
system, legacy Game fallback and region only. Maintenance found no container, a canonical
stopped receipt and the existing world inode 4316448, then stopped EC2 again.

The installed host contract still lists only legacy A/B under `games`, while the D-105
Game-creation contract admits an exact registered `game-<64 hex>` through its authorized
Operation. The producer used the legacy list to choose its canonical heartbeat Game.
For a running registered Game outside A/B, the fixed probe correctly reported its Game
and `player_count=0`, but derivation saw a Game mismatch, cleared the count to null,
and monitoring emitted `RuntimeObservationUnknown`. This explains the fresh-heartbeat
/ unknown-runtime observation after create-survival READY on 2026-09-18.

The producer now chooses the Game from the **running receipt target** only when the
host probe has verified the container's Game label and `/data` bind, exact run ID,
manifest digest/package version and process identity. The producer checks that the
receipt target Game equals the observed Game and has the actual instance identity,
an expected run, digest and Game path. No filesystem scan or A/B list decides the running Game. The legacy `GAME_ID`
is only a fallback while no running identity is trusted; it cannot turn an unknown
observation into a trusted zero. Invalid binding, player observation failure and an
absent target remain unknown/null. Heartbeat schema and 60-second cadence are unchanged.
Monitoring compares the heartbeat Game to the selected Game, treats integer zero as
known and null as unknown; no consumer change or alarm threshold change is needed.

This producer file is separately installed under `/usr/local/libexec/wishicraft`; it is
not a field of the common Compose/runtime.env/manifest hash. The currently installed
manifest digest `64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`
and Game package digest `720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`
remain fixed. No Game/world/Operation/receipt migration, state machine or IAM change is
part of this correction.

### Stopped single-file migration and release gate

1. Keep all three ingress paths closed. Reobserve STOPPED/HEALTHY, EC2 stopped, 45 alarms
   OK, no Current Operation, Lock, workflow, SSM/session or DNS, three empty queues;
   verify Game MATERIALIZED/generation 1, exact package and world, A/B and snapshot /
   provenance baselines. Inspect the installed source hash, unit, timer, manifest,
   receipt and no-container proof before choosing a bundle.
2. Build a fresh output with `python -m wishicraft.heartbeat_game_migration --receipt
   <captured-stopped-receipt.json> --output <new-bundle-root>`. This offline adapter
   reuses the established inactive-only installer: exact old/new source hashes,
   root/mode checks, completed stop proof, filesystem preflight, no container/listener,
   predecessor backup, fsync/atomic rename and retry on old or new hash. It changes
   **only** the producer file. It keeps the predecessor under the exact
   `heartbeat-game-v1` root-EBS namespace for stopped rollback review.
3. Transport the complete reviewed bundle with an exact archive SHA-256, verify it on
   the host, run the bundled installer during maintenance, and read back producer,
   heartbeat service/timer and unchanged common manifest hashes. A failed/partial
   install is retried with the same bundle only after the old/new hash classification;
   unknown hash, receipt or active container stops the release. Return EC2 to stopped.
4. No Control Plane stack deploy is expected for the one-file host correction. If a
   ChangeSet is nevertheless needed, apply the explicit Case D semantic identity guard
   from `ssm_ready_probe.md` and stop on any unrelated property/IAM/resource change.
5. Use the existing create-survival through formal START. After READY and normal
   scheduled Reconcile, observe at least three consecutive 60-second heartbeats
   with the same Game/run/instance/boot/process identity, fresh timestamps and
   `player_count=0`, plus at least two normal five-minute monitoring cycles with
   runtime known and no heartbeat alarm. Do not manufacture or rewrite heartbeat
   records/metrics. STOP through the ordinary save and graceful-stop workflow; confirm
   stopped receipt, container absence, EC2 stop, DNS removal, 45 alarms OK and all
   ingress prerequisites before reopening any of the three paths. A distinct bug
   ends this slice with ingress closed and no second START.
