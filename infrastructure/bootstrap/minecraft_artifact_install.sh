#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${ARTIFACT_URL:?ARTIFACT_URL is required}"
: "${ARTIFACT_SHA1:?ARTIFACT_SHA1 is required}"
: "${ARTIFACT_SHA256:?ARTIFACT_SHA256 is required}"
: "${ARTIFACT_SIZE:?ARTIFACT_SIZE is required}"
: "${ARTIFACT_PATH:?ARTIFACT_PATH is required}"

fail() { printf '%s\n' "wishicraft Minecraft artifact: $*" >&2; exit 1; }

verify_artifact() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c '%s' "$path")" == "$ARTIFACT_SIZE" ]] || return 1
  [[ "$(sha1sum "$path" | awk '{print $1}')" == "$ARTIFACT_SHA1" ]] || return 1
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$ARTIFACT_SHA256" ]] || return 1
}

"$MOUNT_GUARD"
[[ "$ARTIFACT_URL" == https://* ]] || fail "artifact URL must use HTTPS"
[[ "$ARTIFACT_SIZE" =~ ^[1-9][0-9]*$ ]] || fail "invalid artifact size"

if [[ -e "$ARTIFACT_PATH" ]]; then
  verify_artifact "$ARTIFACT_PATH" || fail "existing artifact failed verification"
  chown root:root "$ARTIFACT_PATH"
  chmod 0644 "$ARTIFACT_PATH"
  exit 0
fi

install -d -m 0755 "$(dirname "$ARTIFACT_PATH")"
temporary_path="$(mktemp "$(dirname "$ARTIFACT_PATH")/.server.jar.XXXXXX")"
trap 'rm -f "$temporary_path"' EXIT
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  --connect-timeout 20 --max-time 300 --retry 2 --output "$temporary_path" "$ARTIFACT_URL"
verify_artifact "$temporary_path" || fail "downloaded artifact failed verification"
chmod 0644 "$temporary_path"
chown root:root "$temporary_path"
mv "$temporary_path" "$ARTIFACT_PATH"
trap - EXIT
