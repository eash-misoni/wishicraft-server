#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_ROOT=/var/tmp/wishicraft-phase6-runtime-v1
readonly COMPOSE_PATH=/etc/wishicraft/host-runtime/compose.yaml
readonly HOST_ENV_PATH=/etc/wishicraft/host-runtime.env
readonly RUNTIME_ENV_PATH=/etc/wishicraft/host-runtime/runtime.env
readonly RCON_ENV_PATH=/etc/wishicraft/rcon.env
readonly OPERATION_PATH=/usr/local/libexec/wishicraft/operation-v1
readonly STOP_PATH=/usr/local/libexec/wishicraft/stop-v1
readonly SECRET_PATH=/usr/local/libexec/wishicraft/rcon-secret-v1

readonly COMPOSE_PREDECESSOR=c92fbbfb8c955e249b39edbd2b2063e0cfa05214d8242bdeb302dd1d996b0770
readonly RUNTIME_ENV_PREDECESSOR=723b6ebf352b7bd731eb9b69a3e318b398b9109f76be928d1d3aa1ef116beb93
readonly BROKEN_HOST_ENV_PREDECESSOR=62c9bda48163ed1089e88f2d0bb52692372b003e225145a36512589ec6230dce
readonly CONTAINER_ENV_PREDECESSOR=271ce8bea4effa701c90c35c9ff3e93266437cfa76a84ed917d6381900d26837
readonly SECRET_PREDECESSOR=6200012f402cd7927b1eb6c51c47f38dd11db3af09ea4557f1fdf54d88ceb930
readonly STOP_PREDECESSOR=eb960d9d9a187d095848bf8b373519bbb821ee7759396046e3632074ba8acaeb
readonly OPERATION_PREDECESSOR=eb8ce78e784b9b0eb9d4b85ce26372b35441b8b43ff5ee2375344140b6a1bdf6

sha256() { sha256sum "$1" | cut -d ' ' -f 1; }

fail() { printf 'FAIL:%s\n' "$1" >&2; exit "${2:-70}"; }

replace_existing() {
  local source="$1" target="$2" predecessor="$3" expected="$4" mode="$5"
  local current temporary
  [[ -f "$source" && ! -L "$source" && "$(sha256 "$source")" == "$expected" ]] || \
    fail SOURCE_MISMATCH
  [[ -f "$target" && ! -L "$target" && "$(stat -c '%U:%G' "$target")" == root:root ]] || \
    fail TARGET_IDENTITY
  current="$(sha256 "$target")"
  if [[ "$current" == "$expected" ]]; then
    [[ "$(stat -c '%a' "$target")" == "$mode" ]] || fail TARGET_MODE
    return
  fi
  [[ "$current" == "$predecessor" ]] || fail UNAPPROVED_PREDECESSOR
  temporary="$(mktemp "$(dirname "$target")/.phase6.XXXXXX")"
  trap 'rm -f -- "${temporary:-}"' RETURN
  install -o root -g root -m "$mode" "$source" "$temporary"
  [[ "$(sha256 "$temporary")" == "$expected" ]] || fail TEMPORARY_MISMATCH
  [[ "$(sha256 "$target")" == "$predecessor" ]] || fail PREDECESSOR_RACE
  mv -f -- "$temporary" "$target"
  trap - RETURN
}

install_new() {
  local source="$1" target="$2" expected="$3" mode="$4"
  local temporary
  [[ -f "$source" && ! -L "$source" && "$(sha256 "$source")" == "$expected" ]] || \
    fail SOURCE_MISMATCH
  if [[ -e "$target" || -L "$target" ]]; then
    [[ -f "$target" && ! -L "$target" && "$(sha256 "$target")" == "$expected" ]] || \
      fail UNAPPROVED_EXISTING_TARGET
    [[ "$(stat -c '%U:%G:%a' "$target")" == "root:root:$mode" ]] || fail TARGET_IDENTITY
    return
  fi
  temporary="$(mktemp "$(dirname "$target")/.phase6.XXXXXX")"
  trap 'rm -f -- "${temporary:-}"' RETURN
  install -o root -g root -m "$mode" "$source" "$temporary"
  [[ ! -e "$target" && ! -L "$target" ]] || fail TARGET_RACE
  mv -- "$temporary" "$target"
  trap - RETURN
}

main() {
  [[ "$#" -eq 0 && "$(id -u)" -eq 0 ]] || fail INVOCATION 64
  [[ "$(systemctl is-active wishicraft-host-runtime.service 2>/dev/null || true)" != active ]] || \
    fail HOST_RUNTIME_ACTIVE 65
  [[ -z "$(docker ps --quiet --filter label=com.docker.compose.project=wishicraft-host-runtime)" ]] || \
    fail CONTAINER_RUNNING 66
  [[ -z "$(ss -H -ltn 'sport = :25565 or sport = :25575')" ]] || fail LISTENER_PRESENT 67

  # New helpers first and the public operation entrypoint last. Every artifact is
  # fixed by repository SHA-256 and installed by same-directory atomic rename.
  replace_existing "$SOURCE_ROOT/stop-v1.sh" "$STOP_PATH" \
    "$STOP_PREDECESSOR" aa216797eab831c06c330c52cfe8c0ddb7bb65597b2273da3800693eb0102647 755
  replace_existing "$SOURCE_ROOT/rcon-secret-v1.sh" "$SECRET_PATH" \
    "$SECRET_PREDECESSOR" f9cdcf814fc6697ca60e079a4964b39956048049c7143d8ec7ffa84652af67c9 755
  install_new "$SOURCE_ROOT/phase6-rcon.env" "$RCON_ENV_PATH" a8fa649d7312f54502b4c04483ff9842c29024432a4f67c7eef120f494a5af53 600
  replace_existing "$SOURCE_ROOT/phase6-compose.yaml" "$COMPOSE_PATH" \
    "$COMPOSE_PREDECESSOR" 1e8368222fccdc70e4738bbdabedb8aaf4028e79a2499b04377cc0553a05105a 600
  replace_existing "$SOURCE_ROOT/phase2-real-data.env" "$HOST_ENV_PATH" \
    "$BROKEN_HOST_ENV_PREDECESSOR" "$RUNTIME_ENV_PREDECESSOR" 600
  replace_existing "$SOURCE_ROOT/phase6-runtime.env" "$RUNTIME_ENV_PATH" \
    "$CONTAINER_ENV_PREDECESSOR" 62c9bda48163ed1089e88f2d0bb52692372b003e225145a36512589ec6230dce 600
  replace_existing "$SOURCE_ROOT/operation-v1.sh" "$OPERATION_PATH" \
    "$OPERATION_PREDECESSOR" 33ff20dda9575ca1a3df27edcaf19d397e5f67eef441173ad621f8aefa742744 755
  printf 'PASS:PHASE6_RUNTIME_CONTRACT_UPGRADE\n'
}

main "$@"
