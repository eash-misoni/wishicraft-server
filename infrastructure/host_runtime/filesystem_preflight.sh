#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${MOUNT_PATH:?MOUNT_PATH is required}"
: "${GAME_DIRECTORY:?GAME_DIRECTORY is required}"
: "${EXPECTED_UID:?EXPECTED_UID is required}"
: "${EXPECTED_GID:?EXPECTED_GID is required}"

fail() { printf '%s\n' "wishicraft Host Runtime preflight: $*" >&2; exit 1; }

[[ "$EXPECTED_UID" =~ ^[1-9][0-9]*$ ]] || fail "numeric UID observation is required"
[[ "$EXPECTED_GID" =~ ^[1-9][0-9]*$ ]] || fail "numeric GID observation is required"
[[ "$MOUNT_PATH" == /* && "$MOUNT_PATH" != / ]] || fail "mount path is invalid"
[[ "$GAME_DIRECTORY" == "$MOUNT_PATH"/games/*/server ]] || fail "game directory is outside allowlist"

"$MOUNT_GUARD" --verify
[[ -d "$GAME_DIRECTORY" && ! -L "$GAME_DIRECTORY" ]] || fail "game directory is not a real directory"
if [[ -n "$(find "$GAME_DIRECTORY" -xdev -type l -print -quit)" ]]; then
  fail "symlink is not allowed in game directory"
fi

while IFS= read -r -d '' path; do
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
