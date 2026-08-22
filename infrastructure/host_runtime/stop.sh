#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${COMPOSE_FILE:?COMPOSE_FILE is required}"

"$MOUNT_GUARD" --verify
# Explicit save is intentionally outside this systemd stop scope. The future
# stop_game adapter must complete its 60-second save contract before systemctl stop.
docker compose --file "$COMPOSE_FILE" stop --timeout 150
