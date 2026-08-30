#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${MOUNT_PATH:?MOUNT_PATH is required}"
: "${GAME_DIRECTORY:?GAME_DIRECTORY is required}"
: "${EXPECTED_UID:?EXPECTED_UID is required}"
: "${EXPECTED_GID:?EXPECTED_GID is required}"

readonly COMPOSE_FILE=/etc/wishicraft/host-runtime/compose.yaml
readonly COMPOSE_PROJECT=wishicraft-host-runtime
readonly COMPOSE_SERVICE=minecraft
readonly RCON_RUNTIME_DIR=/run/wishicraft
readonly RCON_PASSWORD_SOURCE="$RCON_RUNTIME_DIR/rcon-password"
readonly RCON_PASSWORD_DESTINATION=/run/secrets/rcon-password
readonly RCON_CLI_ENV_SOURCE="$RCON_RUNTIME_DIR/rcon-cli.env"
readonly RCON_CLI_ENV_DESTINATION=/data/.rcon-cli.env
readonly RCON_CLI_YAML_SOURCE="$RCON_RUNTIME_DIR/rcon-cli.yaml"
readonly RCON_CLI_YAML_DESTINATION=/data/.rcon-cli.yaml

fail() { printf '%s\n' "wishicraft Host Runtime preflight: $*" >&2; exit 1; }

[[ "$EXPECTED_UID" =~ ^[1-9][0-9]*$ ]] || fail "numeric UID observation is required"
[[ "$EXPECTED_GID" =~ ^[1-9][0-9]*$ ]] || fail "numeric GID observation is required"
[[ "$MOUNT_PATH" == /* && "$MOUNT_PATH" != / ]] || fail "mount path is invalid"
[[ "$GAME_DIRECTORY" == "$MOUNT_PATH"/games/*/server ]] || fail "game directory is outside allowlist"

validate_metadata() {
  local path="$1" expected_uid="$2" expected_gid="$3" expected_mode="$4" expected_size="$5"
  [[ -f "$path" && ! -L "$path" ]] || fail "managed RCON artifact is not a regular file"
  [[ "$(stat -c '%u:%g:%a:%s:%h' -- "$path")" == \
    "$expected_uid:$expected_gid:$expected_mode:$expected_size:1" ]] || \
    fail "managed RCON artifact metadata mismatch"
}

validate_mount_contract() {
  local container_id="$1" mounts line source destination rw type matched
  local password_count=0 env_count=0 yaml_count=0

  [[ "$(docker inspect --format '{{index .Config.Labels \"com.docker.compose.project\"}}' "$container_id")" == \
    "$COMPOSE_PROJECT" ]] || fail "unexpected container project"
  [[ "$(docker inspect --format '{{index .Config.Labels \"com.docker.compose.service\"}}' "$container_id")" == \
    "$COMPOSE_SERVICE" ]] || fail "unexpected container service"
  mounts="$(docker inspect --format \
    '{{range .Mounts}}{{printf "%s\t%s\t%t\t%s\n" .Source .Destination .RW .Type}}{{end}}' \
    "$container_id")" || fail "cannot inspect container mounts"
  while IFS=$'\t' read -r source destination rw type; do
    [[ -n "$source" ]] || continue
    matched=false
    if [[ "$source" == "$RCON_PASSWORD_SOURCE" || \
      "$destination" == "$RCON_PASSWORD_DESTINATION" ]]; then
      [[ "$source" == "$RCON_PASSWORD_SOURCE" && \
        "$destination" == "$RCON_PASSWORD_DESTINATION" && "$rw" == false && "$type" == bind ]] || \
        fail "RCON password mount contract mismatch"
      password_count=$((password_count + 1)); matched=true
    fi
    if [[ "$source" == "$RCON_CLI_ENV_SOURCE" || \
      "$destination" == "$RCON_CLI_ENV_DESTINATION" ]]; then
      [[ "$source" == "$RCON_CLI_ENV_SOURCE" && \
        "$destination" == "$RCON_CLI_ENV_DESTINATION" && "$rw" == true && "$type" == bind ]] || \
        fail "RCON CLI env mount contract mismatch"
      env_count=$((env_count + 1)); matched=true
    fi
    if [[ "$source" == "$RCON_CLI_YAML_SOURCE" || \
      "$destination" == "$RCON_CLI_YAML_DESTINATION" ]]; then
      [[ "$source" == "$RCON_CLI_YAML_SOURCE" && \
        "$destination" == "$RCON_CLI_YAML_DESTINATION" && "$rw" == true && "$type" == bind ]] || \
        fail "RCON CLI yaml mount contract mismatch"
      yaml_count=$((yaml_count + 1)); matched=true
    fi
    if [[ "$matched" == false && \
      ( "$source" == "$RCON_RUNTIME_DIR"/* || "$destination" == /data/.rcon-cli.* ) ]]; then
      fail "unexpected RCON mount"
    fi
  done <<<"$mounts"
  [[ "$password_count:$env_count:$yaml_count" == 1:1:1 ]] || \
    fail "required RCON mounts are missing or duplicated"

  validate_metadata "$RCON_PASSWORD_SOURCE" "$EXPECTED_UID" "$EXPECTED_GID" 400 "$(stat -c '%s' -- "$RCON_PASSWORD_SOURCE")"
  [[ -s "$RCON_PASSWORD_SOURCE" ]] || fail "RCON password source is empty"
  validate_metadata "$RCON_CLI_ENV_SOURCE" "$EXPECTED_UID" "$EXPECTED_GID" 600 "$(stat -c '%s' -- "$RCON_CLI_ENV_SOURCE")"
  validate_metadata "$RCON_CLI_YAML_SOURCE" "$EXPECTED_UID" "$EXPECTED_GID" 600 "$(stat -c '%s' -- "$RCON_CLI_YAML_SOURCE")"
}

validate_placeholder() {
  validate_metadata "$1" 0 0 644 0
}

"$MOUNT_GUARD" --verify
[[ -d "$GAME_DIRECTORY" && ! -L "$GAME_DIRECTORY" ]] || fail "game directory is not a real directory"
if [[ -n "$(find "$GAME_DIRECTORY" -xdev -type l -print -quit)" ]]; then
  fail "symlink is not allowed in game directory"
fi

container_id="$(docker compose --file "$COMPOSE_FILE" ps --status running --quiet "$COMPOSE_SERVICE")" || \
  fail "cannot resolve Host Runtime container"
[[ -z "$container_id" || "$container_id" =~ ^[0-9a-f]{12,64}$ ]] || \
  fail "Host Runtime container identity is ambiguous"
for placeholder in "$GAME_DIRECTORY/.rcon-cli.env" "$GAME_DIRECTORY/.rcon-cli.yaml"; do
  if [[ -n "$container_id" ]]; then
    [[ -e "$placeholder" || -L "$placeholder" ]] || \
      fail "managed RCON mountpoint is missing while container is running"
    validate_placeholder "$placeholder"
  elif [[ -e "$placeholder" || -L "$placeholder" ]]; then
    validate_placeholder "$placeholder"
  fi
done
[[ -z "$container_id" ]] || validate_mount_contract "$container_id"

while IFS= read -r -d '' path; do
  if [[ "$path" == "$GAME_DIRECTORY/.rcon-cli.env" || \
    "$path" == "$GAME_DIRECTORY/.rcon-cli.yaml" ]]; then
    validate_placeholder "$path"
    continue
  fi
  [[ ! -L "$path" ]] || fail "symlink is not allowed in game directory"
  [[ -d "$path" || -f "$path" ]] || fail "unexpected file type"
  uid="$(stat -c '%u' -- "$path")"
  gid="$(stat -c '%g' -- "$path")"
  if [[ "$uid" != "$EXPECTED_UID" || "$gid" != "$EXPECTED_GID" ]]; then
    [[ -f "$path" && "$uid" == 0 && "$gid" == "$EXPECTED_GID" ]] || fail "unknown owner"
  fi
  if command -v getfacl >/dev/null 2>&1; then
    getfacl -cp -- "$path" | awk '
      /^$/ { next }
      /^(user::|group::|other::)/ { next }
      { exit 1 }
    ' || fail "extended ACL is not allowed"
  fi
done < <(find "$GAME_DIRECTORY" -xdev -print0)
