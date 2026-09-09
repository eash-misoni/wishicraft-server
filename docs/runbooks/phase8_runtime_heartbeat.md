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

repositoryの固定7 artifactと`phase8_heartbeat_install.sh`を新しい専用temporary source rootへ転送する。各fileのSHA-256、owner/mode、既存target不存在を確認し、installerを一度実行する。任意payload/pathを受け取る常設interfaceは作らない。

installerはAWS CLI/Python存在を確認し、fixed artifactsをatomic installして`wishicraft-heartbeat.timer`だけをenableする。Minecraft Host Runtimeをstart/stop/restartしない。

## Verification

1. table TTL、key、Retain、index/streamなしをread-backする。
2. Target roleがtable限定GetItem/PutItemとcanonical LeadingKeysだけを持つことを確認する。
3. canonical START後にfirst heartbeat、60秒間隔の複数record、boot/instance/runtime/Game、READY、player count、empty_since、24時間TTLを確認する。
4. service restartはsame boot/fresh zero continuityだけを維持することを確認する。
5. stale/out-of-order fixtureのconditional Putが現recordを変更しないことを確認する。
6. canonical STOP後、EC2 stopped、DNS absent、Lock/Current Operationなしへ戻す。

player出入りが必要な確認はoperatorへ一度だけ依頼する。unknownをzeroへ補正せず、recordをraw repairしない。
