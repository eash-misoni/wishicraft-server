#!/usr/bin/env bash
set -euo pipefail

: "${MOUNT_GUARD:?MOUNT_GUARD is required}"
: "${GAME_SETUP:?GAME_SETUP is required}"
: "${RCON_PARAMETER_NAME:?RCON_PARAMETER_NAME is required}"
: "${RCON_PORT:?RCON_PORT is required}"
: "${SERVER_PROPERTIES:?SERVER_PROPERTIES is required}"

fail() { printf '%s\n' "wishicraft RCON configuration: $*" >&2; exit 1; }

"$MOUNT_GUARD"
"$GAME_SETUP" --verify
command -v aws >/dev/null 2>&1 || fail "AWS CLI is unavailable"
command -v python3 >/dev/null 2>&1 || fail "Python 3 is unavailable"
[[ "$RCON_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && ((RCON_PORT <= 65535)) || fail "invalid RCON port"
[[ -f "$SERVER_PROPERTIES" && ! -L "$SERVER_PROPERTIES" ]] || fail "server.properties is invalid"
umask 077
rcon_password="$(
  timeout 30 aws ssm get-parameter --name "$RCON_PARAMETER_NAME" --with-decryption --output json |
    python3 -c '
import json
import re
import sys

try:
    parameter = json.load(sys.stdin)["Parameter"]
    value = parameter["Value"]
except (KeyError, TypeError, json.JSONDecodeError):
    sys.exit("invalid RCON parameter response")
if parameter.get("Type") != "SecureString":
    sys.exit("RCON parameter is not SecureString")
if not isinstance(value, str) or not value or len(value) < 16:
    sys.exit("RCON password does not meet requirements")
if "\x00" in value or "\n" in value or "\r" in value:
    sys.exit("RCON password does not meet requirements")
if re.fullmatch(r"[A-Za-z0-9!#$%&()*+,./:;?@\[\]^_{}~-]+", value) is None:
    sys.exit("RCON password does not meet requirements")
sys.stdout.write(value)
'
)" || fail "could not retrieve RCON parameter"
trap 'unset rcon_password; rm -f "${temporary_properties:-}"' EXIT

expected=("enable-rcon=true" "rcon.port=$RCON_PORT" "rcon.password=$rcon_password" "broadcast-rcon-to-ops=false")
for entry in "${expected[@]}"; do
  key="${entry%%=*}"
  count="$(awk -F= -v key="$key" '$1 == key { count++ } END { print count + 0 }' "$SERVER_PROPERTIES")"
  if [[ "$count" != 0 && "$count" != 1 ]]; then fail "RCON configuration drift"; fi
  if [[ "$count" == 1 ]] && ! grep -Fqx "$entry" "$SERVER_PROPERTIES"; then fail "RCON configuration drift"; fi
done
verify_permissions() {
  [[ "$(stat -c '%U:%G:%a' "$SERVER_PROPERTIES")" == "root:minecraft:640" ]] || fail "server.properties permissions differ"
}
if grep -qE '^(enable-rcon|rcon\.port|rcon\.password|broadcast-rcon-to-ops)=' "$SERVER_PROPERTIES"; then
  [[ "$(grep -Ec '^(enable-rcon|rcon\.port|rcon\.password|broadcast-rcon-to-ops)=' "$SERVER_PROPERTIES")" == 4 ]] || fail "RCON configuration drift"
  verify_permissions
else
  temporary_properties="$(mktemp "${SERVER_PROPERTIES}.XXXXXX")"
  cat "$SERVER_PROPERTIES" > "$temporary_properties"
  printf '%s\n' "${expected[@]}" >> "$temporary_properties"
  chown root:minecraft "$temporary_properties"
  chmod 0640 "$temporary_properties"
  [[ "$(stat -c '%U:%G:%a' "$temporary_properties")" == "root:minecraft:640" ]] || fail "temporary server.properties permissions differ"
  mv "$temporary_properties" "$SERVER_PROPERTIES"
  unset temporary_properties
  verify_permissions
fi
unset rcon_password
trap - EXIT
