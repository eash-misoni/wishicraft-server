#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${MOUNT_PATH:?MOUNT_PATH is required}"
: "${GAME_ID:?GAME_ID is required}"
: "${GAME_DIRECTORY:?GAME_DIRECTORY is required}"
: "${ARTIFACT_PATH:?ARTIFACT_PATH is required}"
: "${MINECRAFT_PORT:?MINECRAFT_PORT is required}"
: "${PROFILE_NAME:?PROFILE_NAME is required}"
: "${PROFILE_UUID:?PROFILE_UUID is required}"

readonly SERVER_DIRECTORY="$GAME_DIRECTORY/server"

fail() { printf '%s\n' "wishicraft Minecraft game: $*" >&2; exit 1; }

ensure_exact_file() {
  local path="$1" content="$2" temporary
  if [[ -e "$path" ]]; then
    [[ "$(cat "$path")" == "$content" ]] || fail "existing $path differs from managed configuration"
    return
  fi
  temporary="$(mktemp "${path}.XXXXXX")"
  printf '%s\n' "$content" > "$temporary"
  chown minecraft:minecraft "$temporary"
  chmod 0640 "$temporary"
  mv "$temporary" "$path"
}

verify_property() {
  local key="$1" expected="$2" path="$SERVER_DIRECTORY/server.properties"
  awk -F= -v key="$key" -v expected="$expected" '
    $1 == key {
      if ($0 != expected) invalid = 1
      count++
    }
    END { exit count == 1 && !invalid ? 0 : 1 }
  ' "$path" || fail "$key differs"
}

verify() {
  local expected_whitelist
  expected_whitelist="$(printf '[{\"uuid\":\"%s\",\"name\":\"%s\"}]' "$PROFILE_UUID" "$PROFILE_NAME")"
  "$MOUNT_GUARD"
  [[ -r "$ARTIFACT_PATH" ]] || fail "verified server artifact is missing"
  [[ -d "$SERVER_DIRECTORY" ]] || fail "server directory is missing"
  [[ -r "$SERVER_DIRECTORY/eula.txt" ]] || fail "EULA file is missing"
  [[ "$(cat "$SERVER_DIRECTORY/eula.txt")" == "eula=true" ]] || fail "EULA is not accepted"
  verify_property server-port "server-port=$MINECRAFT_PORT"
  verify_property online-mode 'online-mode=true'
  verify_property white-list 'white-list=true'
  verify_property enforce-whitelist 'enforce-whitelist=true'
  verify_property management-server-enabled 'management-server-enabled=false'
  grep -Fqx "$expected_whitelist" "$SERVER_DIRECTORY/whitelist.json" || fail "whitelist differs"
}

prepare() {
  "$MOUNT_GUARD"
  [[ "$GAME_ID" =~ ^[a-z0-9-]+$ ]] || fail "invalid game ID"
  [[ "$MINECRAFT_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || fail "invalid Minecraft port"
  [[ "$PROFILE_UUID" =~ ^[0-9a-f]{32}$ ]] || fail "invalid profile UUID"
  getent group minecraft >/dev/null || groupadd --system minecraft
  id -u minecraft >/dev/null 2>&1 || useradd --system --gid minecraft --no-create-home --shell /sbin/nologin minecraft
  install -d -o root -g root -m 0755 "$MOUNT_PATH/games" "$GAME_DIRECTORY"
  install -d -o minecraft -g minecraft -m 0750 "$SERVER_DIRECTORY" "$GAME_DIRECTORY/runtime"
}

if [[ "${1:-}" == "--verify" ]]; then
  verify
  exit 0
fi
if [[ "${1:-}" == "--prepare" ]]; then
  prepare
  exit 0
fi
[[ $# -eq 0 ]] || fail "unsupported argument: $1"

prepare
[[ -r "$ARTIFACT_PATH" ]] || fail "verified server artifact is missing"
ensure_exact_file "$SERVER_DIRECTORY/eula.txt" 'eula=true'
ensure_exact_file "$SERVER_DIRECTORY/server.properties" "server-port=$MINECRAFT_PORT
online-mode=true
white-list=true
enforce-whitelist=true
management-server-enabled=false"
whitelist_content="$(printf '[{\"uuid\":\"%s\",\"name\":\"%s\"}]' "$PROFILE_UUID" "$PROFILE_NAME")"
ensure_exact_file "$SERVER_DIRECTORY/whitelist.json" "$whitelist_content"
verify
