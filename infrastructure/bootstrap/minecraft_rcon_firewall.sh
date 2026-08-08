#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${RCON_PORT:?RCON_PORT is required}"

fail() { printf '%s\n' "wishicraft RCON firewall: $*" >&2; exit 1; }

readonly rules_path="${WISHICRAFT_RCON_NFT_RULES_PATH:-/etc/nftables/wishicraft-rcon.nft}"
readonly rules_directory="$(dirname "$rules_path")"
[[ "$RCON_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && ((RCON_PORT <= 65535)) || fail "invalid RCON port"

if ! command -v nft >/dev/null 2>&1; then
  command -v dnf >/dev/null 2>&1 || fail "DNF is unavailable"
  dnf install -y nftables || fail "could not install nftables"
fi
command -v nft >/dev/null 2>&1 || fail "nft is unavailable"

install -d -o root -g root -m 0700 "$rules_directory"
temporary_rules="$(mktemp "${rules_path}.XXXXXX")"
trap 'rm -f "${temporary_rules:-}"' EXIT
cat > "$temporary_rules" <<RULES
destroy table inet wishicraft_rcon
table inet wishicraft_rcon {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport $RCON_PORT ip daddr != 127.0.0.1 drop
    tcp dport $RCON_PORT ip6 daddr != ::1 drop
  }
}
RULES
chown root:root "$temporary_rules"
chmod 0600 "$temporary_rules"
[[ "$(stat -c '%U:%G:%a' "$temporary_rules")" == "root:root:600" ]] || fail "invalid rules file permissions"
nft --check --file "$temporary_rules" || fail "nft rules validation failed"
nft --file "$temporary_rules" || fail "nft rules application failed"
nft list table inet wishicraft_rcon >/dev/null || fail "nft table verification failed"
mv "$temporary_rules" "$rules_path"
unset temporary_rules
trap - EXIT
