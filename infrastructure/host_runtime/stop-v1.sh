#!/usr/bin/env bash
set -euo pipefail

readonly HOST_RUNTIME_UNIT=wishicraft-host-runtime.service
readonly COMPOSE_FILE=/etc/wishicraft/host-runtime/compose.yaml
readonly HOST_ENV_PATH=/etc/wishicraft/host-runtime.env
readonly FILESYSTEM_PREFLIGHT=/usr/local/lib/wishicraft-host-runtime/filesystem_preflight.sh

[[ "$#" -eq 0 ]] || exit 64

fail() {
  local error_code="$1"
  printf '{"schema_version":1,"operation":"STOP","status":"failed","error_code":"%s"}\n' "$error_code"
  exit "$2"
}

[[ -f "$HOST_ENV_PATH" && ! -L "$HOST_ENV_PATH" ]] || fail MOUNT_GUARD_FAILED 65
[[ "$(stat -c '%U:%G:%a' "$HOST_ENV_PATH")" == "root:root:600" ]] || \
  fail MOUNT_GUARD_FAILED 65
set -a
# shellcheck disable=SC1090 -- fixed root-owned configuration path
source "$HOST_ENV_PATH"
set +a
"$FILESYSTEM_PREFLIGHT" || fail MOUNT_GUARD_FAILED 65
container_id="$(docker compose --file "$COMPOSE_FILE" ps --quiet minecraft)" || \
  fail GRACEFUL_RUNTIME_STOP_FAILED 72
[[ "$container_id" =~ ^[0-9a-f]{12,64}$ ]] || fail RCON_UNAVAILABLE 71

# rcon-cli reads the image-generated /data/.rcon-cli config. No password is
# placed in arguments, environment, stdout, or the host journal.
docker exec "$container_id" rcon-cli list >/dev/null || fail RCON_UNAVAILABLE 71
docker exec "$container_id" rcon-cli save-all flush >/dev/null || fail MINECRAFT_SAVE_FAILED 73
logger --tag wishicraft-stop 'SAVE_CONFIRMED operation=STOP_V1'

systemctl stop "$HOST_RUNTIME_UNIT" || fail GRACEFUL_RUNTIME_STOP_FAILED 74
systemctl is-active --quiet "$HOST_RUNTIME_UNIT" && fail GRACEFUL_RUNTIME_STOP_FAILED 74
[[ -z "$(docker compose --file "$COMPOSE_FILE" ps --quiet minecraft)" ]] || \
  fail MINECRAFT_STOP_TIMEOUT 75
[[ -z "$(docker ps --quiet --filter label=com.docker.compose.project=wishicraft-host-runtime)" ]] || \
  fail MINECRAFT_STOP_TIMEOUT 75
for port in 25565 25575; do
  [[ -z "$(ss -H -ltn "sport = :$port")" ]] || fail MINECRAFT_STOP_TIMEOUT 75
done
logger --tag wishicraft-stop 'GRACEFUL_STOP_CONFIRMED operation=STOP_V1'
