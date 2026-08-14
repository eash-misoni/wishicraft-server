#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

m() { printf 'WCRF:%s\n' "$1" >&2; }
f() { m "FAIL:$1"; exit "${2:-1}"; }

readonly MODE="${1:-normal}"
case "$MODE" in normal|--recover-empty-v15|--classify-table) ;; *) f MODE 18;; esac
: "${RCON_PORT:?RCON_PORT is required}"
readonly RULES_PATH="${WISHICRAFT_RCON_NFT_RULES_PATH:-/etc/nftables/wishicraft-rcon.nft}"
readonly RULES_DIR="$(dirname "$RULES_PATH")"
[[ "$RCON_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && (( RCON_PORT <= 65535 )) || f RCON_PORT 20
command -v python3 >/dev/null 2>&1 || f PYTHON_LOOKUP 21

read -r -d '' NFT_JSON_PARSER <<'PY' || true
import json, sys
port=int(sys.argv[1])
def stop(v): print(v); raise SystemExit
try:
    items=json.load(sys.stdin).get("nftables")
except (AttributeError, TypeError, ValueError):
    stop("fail:JSON_PARSE")
if not isinstance(items,list): stop("fail:JSON_PARSE")
obj={k:[] for k in ("table","chain","rule")}
for i in items:
    if not isinstance(i,dict) or len(i)!=1: stop("fail:UNEXPECTED_OBJECT")
    k,v=next(iter(i.items()))
    if k=="metainfo": continue
    if k not in obj or not isinstance(v,dict): stop("fail:UNEXPECTED_OBJECT")
    obj[k].append(v)
t,c,r=(obj[k] for k in ("table","chain","rule"))
if len(t)!=1: stop("fail:TABLE_IDENTITY")
t=t[0]
if (t.get("family"),t.get("name"))!=("inet","wishicraft_rcon"): stop("fail:TABLE_IDENTITY")
if set(t)-{"family","name","handle"}: stop("fail:UNEXPECTED_OBJECT")
if not c and not r: stop("empty")
if len(c)!=1: stop("fail:CHAIN_COUNT")
c=c[0]
if set(c)-{"family","table","name","handle","type","hook","prio","policy"}: stop("fail:UNEXPECTED_OBJECT")
want=("inet","wishicraft_rcon","input","filter","input",0,"accept")
if tuple(c.get(k) for k in ("family","table","name","type","hook","prio","policy"))!=want: stop("fail:CHAIN_META")
if len(r)!=2: stop("fail:DUPLICATE" if len(r)>2 else "fail:RULE_COUNT")
found={"ip":0,"ip6":0}
for r in r:
    if set(r)-{"family","table","chain","handle","expr"}: stop("fail:UNEXPECTED_OBJECT")
    if tuple(r.get(k) for k in ("family","table","chain"))!=("inet","wishicraft_rcon","input"): stop("fail:UNEXPECTED_OBJECT")
    e=r.get("expr")
    if not isinstance(e,list) or len(e)!=3: stop("fail:UNEXPECTED_EXPRESSION")
    if not isinstance(e[-1],dict) or set(e[-1])!={"drop"}: stop("fail:VERDICT")
    family=None; address=False; dport=False
    for x in e[:-1]:
        if not isinstance(x,dict) or set(x)!={"match"} or not isinstance(x["match"],dict): stop("fail:UNEXPECTED_EXPRESSION")
        x=x["match"]
        if set(x)!={"op","left","right"} or not isinstance(x["left"],dict): stop("fail:UNEXPECTED_EXPRESSION")
        p=x["left"].get("payload")
        if not isinstance(p,dict) or set(p)!={"protocol","field"}: stop("fail:UNEXPECTED_EXPRESSION")
        protocol,field=p["protocol"],p["field"]
        if (protocol,field)==("tcp","dport"):
            if x["op"]!="==": stop("fail:PORT_PREDICATE")
            dport=x["right"]==port
        elif protocol in found and field=="daddr":
            if x["op"]!="!=": stop("fail:ADDRESS_PREDICATE")
            family=protocol; address=x["right"]==("127.0.0.1" if protocol=="ip" else "::1")
        else: stop("fail:UNEXPECTED_EXPRESSION")
    if not dport: stop("fail:PORT_PREDICATE")
    if family not in found or not address: stop("fail:ADDRESS_PREDICATE")
    found[family]+=1
if found["ip"]!=1: stop("fail:DUPLICATE" if found["ip"]>1 else "fail:IPV4_RULE")
if found["ip6"]!=1: stop("fail:DUPLICATE" if found["ip6"]>1 else "fail:IPV6_RULE")
print("canonical")
PY

json_state() {
  local output parsed
  if ! output="$(nft -j list table inet wishicraft_rcon 2>/dev/null)"; then
    if nft list tables >/dev/null 2>&1 && ! nft list tables | grep -Fx 'table inet wishicraft_rcon' >/dev/null; then
      printf absent
      return 0
    fi
    printf 'fail:JSON_QUERY'
    return 0
  fi
  parsed="$(printf '%s' "$output" | python3 -c "$NFT_JSON_PARSER" "$RCON_PORT" 2>/dev/null)" || { printf 'fail:JSON_PARSE'; return 0; }
  printf '%s' "$parsed"
}

fail_semantic() {
  case "$1" in
    fail:JSON_QUERY) f JSON_QUERY 41;;
    fail:JSON_PARSE) f JSON_PARSE 42;;
    fail:TABLE_IDENTITY) f TABLE_IDENTITY 43;;
    fail:UNEXPECTED_OBJECT) f UNEXPECTED_OBJECT 44;;
    fail:CHAIN_COUNT|fail:RULE_COUNT) f CHAIN_COUNT 45;;
    fail:CHAIN_META) f CHAIN_META 46;;
    fail:IPV4_RULE) f IPV4_RULE 47;;
    fail:IPV6_RULE) f IPV6_RULE 48;;
    fail:PORT_PREDICATE) f PORT_PREDICATE 49;;
    fail:ADDRESS_PREDICATE) f ADDRESS_PREDICATE 50;;
    fail:VERDICT) f VERDICT 51;;
    fail:DUPLICATE) f DUPLICATE 52;;
    fail:UNEXPECTED_EXPRESSION) f UNEXPECTED_EXPRESSION 53;;
    *) f JSON_PARSE 42;;
  esac
}

if [[ "$MODE" == --classify-table ]]; then
  json_state
  exit 0
fi

if ! command -v nft >/dev/null 2>&1; then
  command -v dnf >/dev/null 2>&1 || f DNF_LOOKUP 22
  dnf install -y nftables || f DNF_INSTALL 23
fi
command -v nft >/dev/null 2>&1 || f NFT_LOOKUP 24
if [[ -e "$RULES_DIR" || -L "$RULES_DIR" ]]; then
  [[ -d "$RULES_DIR" && ! -L "$RULES_DIR" ]] || f DIRECTORY_TYPE 25
  [[ "$(stat -c '%U:%G:%a' "$RULES_DIR")" == root:root:700 ]] || f DIRECTORY_META 26
else
  install -d -o root -g root -m 0700 "$RULES_DIR" || f DIRECTORY_CREATE 27
fi

rules_state=absent
if [[ -e "$RULES_PATH" || -L "$RULES_PATH" ]]; then
  [[ -f "$RULES_PATH" && ! -L "$RULES_PATH" ]] || f RULES_TYPE 28
  [[ "$(stat -c '%U:%G:%a' "$RULES_PATH")" == root:root:600 ]] || f RULES_META 29
  rules_state=present
fi
compgen -G "${RULES_PATH}.*" >/dev/null && f TEMP_CONFLICT 30
table_state="$(json_state)"
case "$table_state" in canonical|empty|absent) ;; *) fail_semantic "$table_state";; esac
if [[ "$table_state" == empty && "$MODE" != --recover-empty-v15 ]]; then f EMPTY_TABLE_UNAPPROVED 54; fi
if [[ "$MODE" == --recover-empty-v15 ]]; then
  [[ "$table_state" == empty && "$rules_state" == absent ]] || f EMPTY_V15_STATE 55
fi

temporary=
cleanup() { [[ -z "${temporary:-}" ]] || rm -f "$temporary"; }
trap cleanup EXIT
temporary="$(mktemp "${RULES_PATH}.XXXXXX")" || f TEMP_CREATE 31
cat >"$temporary" <<RULES
create table inet wishicraft_rcon
add chain inet wishicraft_rcon input { type filter hook input priority 0; policy accept; }
add rule inet wishicraft_rcon input tcp dport $RCON_PORT ip daddr != 127.0.0.1 drop
add rule inet wishicraft_rcon input tcp dport $RCON_PORT ip6 daddr != ::1 drop
RULES
chown root:root "$temporary" || f TEMP_OWNER 32
chmod 0600 "$temporary" || f TEMP_MODE 33
[[ "$(stat -c '%U:%G:%a' "$temporary")" == root:root:600 ]] || f TEMP_META 34
[[ "$rules_state" != present ]] || cmp -s "$temporary" "$RULES_PATH" || f RULES_CONFLICT 35

if [[ "$table_state" == absent ]]; then
  m STEP:NFT_CHECK
  nft --check --file "$temporary" || f NFT_CHECK 36
  m STEP:RACE_CHECK
  [[ "$(json_state)" == absent ]] || f TABLE_RACE 37
  m STEP:NFT_APPLY
  nft --file "$temporary" || f NFT_APPLY 38
elif [[ "$table_state" == empty ]]; then
  recovery="$(mktemp "${RULES_PATH}.recovery.XXXXXX")" || f RECOVERY_TEMP 56
  cat >"$recovery" <<RULES
create chain inet wishicraft_rcon input { type filter hook input priority 0; policy accept; }
add rule inet wishicraft_rcon input tcp dport $RCON_PORT ip daddr != 127.0.0.1 drop
add rule inet wishicraft_rcon input tcp dport $RCON_PORT ip6 daddr != ::1 drop
RULES
  chown root:root "$recovery" || f RECOVERY_OWNER 57
  chmod 0600 "$recovery" || f RECOVERY_MODE 58
  [[ "$(stat -c '%U:%G:%a' "$recovery")" == root:root:600 ]] || f RECOVERY_META 59
  m STEP:RECOVERY_CHECK
  nft --check --file "$recovery" || f RECOVERY_CHECK 60
  m STEP:RECOVERY_RACE_CHECK
  [[ "$(json_state)" == empty ]] || f RECOVERY_RACE 61
  m STEP:RECOVERY_APPLY
  nft --file "$recovery" || f RECOVERY_APPLY 62
  rm -f "$recovery"
fi

verified="$(json_state)"
[[ "$verified" == canonical ]] || fail_semantic "$verified"
m STEP:LIVE_VERIFY
if [[ "$rules_state" == absent ]]; then
  m STEP:PERSIST_FINALIZE
  mv "$temporary" "$RULES_PATH" || f PERSIST_FINALIZE 63
  temporary=
else
  rm -f "$temporary"
  temporary=
fi
trap - EXIT
m COMPLETE
