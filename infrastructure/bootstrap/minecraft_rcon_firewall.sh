#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
m(){ printf 'WCRF:%s\n' "$1" >&2; }
f(){ m "FAIL:$1"; exit "${2:-1}"; }
: "${RCON_PORT:?RCON_PORT is required}"
r="${WISHICRAFT_RCON_NFT_RULES_PATH:-/etc/nftables/wishicraft-rcon.nft}"
d="$(dirname "$r")"
[[ "$RCON_PORT" =~ ^[1-9][0-9]{0,4}$ ]]&&((RCON_PORT<=65535))||f RCON_PORT 20
if ! command -v nft >/dev/null 2>&1;then
 command -v dnf >/dev/null 2>&1||f DNF_LOOKUP 21
 dnf install -y nftables||f DNF_INSTALL 22
fi
command -v nft >/dev/null 2>&1||f NFT_LOOKUP 23
if [[ -e "$d" || -L "$d" ]];then
 [[ -d "$d" && ! -L "$d" ]]||f DIRECTORY_TYPE 24
 [[ "$(stat -c '%U:%G:%a' "$d")" == root:root:700 ]]||f DIRECTORY_META 25
else install -d -o root -g root -m 0700 "$d"||f DIRECTORY_CREATE 26
fi
canonical(){
 local o p="$RCON_PORT"
 o="$(nft list table inet wishicraft_rcon 2>/dev/null)"||return 1
 q(){ [[ "$(grep -Ec "$1"<<<"$o")" == "${2:-1}" ]]; }
 q '^table inet wishicraft_rcon \{$'||return 1
 q '^[[:space:]]*chain input \{'||return 1
 q 'type filter hook input priority (filter|0); policy accept;'||return 1
 q "tcp dport $p ip daddr != 127.0.0.1 drop"||return 1
 q "tcp dport $p ip6 daddr != ::1 drop"||return 1
 q "tcp dport $p" 2||return 1
 [[ "$(grep -Ec ' (accept|drop|reject|dnat|snat|masquerade|redirect|jump|goto)( |;|$)'<<<"$o")" == 3 ]]
}
rs=absent
if [[ -e "$r" || -L "$r" ]];then
 [[ -f "$r" && ! -L "$r" ]]||f RULES_TYPE 27
 [[ "$(stat -c '%U:%G:%a' "$r")" == root:root:600 ]]||f RULES_META 28
 rs=present
fi
ts=absent
if nft list table inet wishicraft_rcon >/dev/null 2>&1;then canonical||f TABLE_CONFLICT 29;ts=canonical;fi
compgen -G "${r}.*" >/dev/null&&f TEMP_CONFLICT 30
t=
cleanup(){ [[ -z "${t:-}" ]]||rm -f "$t"; }
trap cleanup EXIT
t="$(mktemp "${r}.XXXXXX")"||f TEMP_CREATE 31
cat >"$t" <<RULES
create table inet wishicraft_rcon {
 chain input {
  type filter hook input priority 0; policy accept;
  tcp dport $RCON_PORT ip daddr != 127.0.0.1 drop
  tcp dport $RCON_PORT ip6 daddr != ::1 drop
 }
}
RULES
chown root:root "$t"||f TEMP_OWNER 32
chmod 0600 "$t"||f TEMP_MODE 33
[[ "$(stat -c '%U:%G:%a' "$t")" == root:root:600 ]]||f TEMP_META 34
[[ "$rs" != present ]]||cmp -s "$t" "$r"||f RULES_CONFLICT 35
if [[ "$ts" == absent ]];then
 m STEP:NFT_CHECK;nft --check --file "$t"||f NFT_CHECK 36
 m STEP:RACE_CHECK;! nft list table inet wishicraft_rcon >/dev/null 2>&1||f TABLE_RACE 37
 m STEP:NFT_APPLY;nft --file "$t"||f NFT_APPLY 38
 canonical||f LIVE_VERIFY 39
fi
if [[ "$rs" == absent ]];then
 m STEP:PERSIST_FINALIZE;mv "$t" "$r"||f PERSIST_FINALIZE 40;t=
else rm -f "$t";t=
fi
trap - EXIT
m COMPLETE
