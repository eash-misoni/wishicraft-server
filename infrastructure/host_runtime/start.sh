#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${PREFLIGHT:?PREFLIGHT is required}"
: "${COMPOSE_FILE:?COMPOSE_FILE is required}"
: "${MINECRAFT_PORT:?MINECRAFT_PORT is required}"

"$MOUNT_GUARD" --verify
"$PREFLIGHT"
if systemctl is-active --quiet minecraft.service; then
  printf '%s\n' "wishicraft Host Runtime: Phase 1 minecraft.service is active" >&2
  exit 1
fi
[[ "$MINECRAFT_PORT" =~ ^[1-9][0-9]{0,4}$ && "$MINECRAFT_PORT" -le 65535 ]] || {
  printf '%s\n' "wishicraft Host Runtime: invalid Minecraft port" >&2
  exit 1
}
if [[ -n "$(ss -H -ltn "sport = :$MINECRAFT_PORT")" ]]; then
  printf '%s\n' "wishicraft Host Runtime: Minecraft port already has a listener" >&2
  exit 1
fi
docker compose --file "$COMPOSE_FILE" up --detach --no-build --pull never
