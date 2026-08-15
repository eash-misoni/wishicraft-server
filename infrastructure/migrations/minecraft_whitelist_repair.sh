#!/usr/bin/env bash
# One-shot, fail-closed repair for Minecraft whitelist UUID serialization.
set -euo pipefail
set +x
umask 077

checkpoint() { printf '%s\n' "$1"; }
fail() { checkpoint "FAIL:$1"; exit "${2:-1}"; }
pass() { checkpoint "PASS:$1"; }

readonly SERVER=/srv/minecraft/games/game-vanilla-main/server
readonly WHITELIST="$SERVER/whitelist.json"
readonly ENV_FILE=/etc/wishicraft/minecraft.env
readonly GAME_SETUP=/usr/local/lib/wishicraft/minecraft_game_setup.sh
readonly UNIT=/etc/systemd/system/minecraft.service
readonly JAR=/srv/minecraft/packages/vanilla/26.2/server.jar
readonly FIREWALL_SCRIPT=/usr/local/lib/wishicraft/minecraft_rcon_firewall.sh
readonly FIREWALL_RULES=/etc/nftables/wishicraft-rcon.nft
readonly UUID_NORMALIZED=e912ab95758e4b7fb32e292eda293104
readonly UUID_HYPHENATED=e912ab95-758e-4b7f-b32e-292eda293104
readonly NAME=NEWISHIN_
readonly WHITELIST_PREDECESSOR_BYTES=65
readonly WHITELIST_PREDECESSOR_SHA=947d6fe39bce595925e5faf1f2fc677fb1edaba95398e07f4c459e7a08ecc279
readonly WHITELIST_BYTES=69
readonly WHITELIST_SHA=55e225b339b7d3806754eadf6cb568f2eea978a458ef7e26e3b3d1eaed4bac70
readonly ENV_PREDECESSOR_BYTES=856
readonly ENV_PREDECESSOR_SHA=e7e77a6dfc55e7aa697efab7ec6305b58d3e38be92a42175112e29fa549299ac
readonly ENV_BYTES=860
readonly ENV_SHA=423b20860389ce29f8d26f7664983b29bb6ee56496b0b3ff78c9be9cca1a40f5
readonly GAME_SETUP_PREDECESSOR_BYTES=3349
readonly GAME_SETUP_PREDECESSOR_SHA=6d42df504412818f807046afa0c2caa082d3d636d71f035a53de90d4cdab2e9b
readonly GAME_SETUP_BYTES=3765
readonly GAME_SETUP_SHA=e068a6409cee01ab8a84ab9f82cf1dc958a34e8bbbed382fd7e88c771bfc1350
readonly UNIT_BYTES=891
readonly UNIT_SHA=691e0ce8e8005fa07d6d262902ae2c2c96d3d865d116b6391ab912cae7f21f34
readonly JAR_BYTES=60894273
readonly JAR_SHA=cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5
readonly FIREWALL_SHA=e17f38bc39dc88a974c60e0cb3320b0032567c35a0da0a1b10bed89791ab5bb2
readonly FIREWALL_RULES_SHA=f1625836adf67b4297cb7e134abacea53cef84e269e7af4a4ff9e1f1cb2490db
readonly WHITELIST_CONTENT='[{"uuid":"e912ab95-758e-4b7f-b32e-292eda293104","name":"NEWISHIN_"}]'
readonly ENV_CONTENT='MOUNT_GUARD=/usr/local/lib/wishicraft/data_volume_mount.sh
GAME_SETUP=/usr/local/lib/wishicraft/minecraft_game_setup.sh
DATA_VOLUME_ID=vol-03ac9f534326c345c
FILESYSTEM_TYPE=xfs
MOUNT_PATH=/srv/minecraft
GAME_ID=game-vanilla-main
GAME_DIRECTORY=/srv/minecraft/games/game-vanilla-main
ARTIFACT_URL=https://piston-data.mojang.com/v1/objects/823e2250d24b3ddac457a60c92a6a941943fcd6a/server.jar
ARTIFACT_SHA1=823e2250d24b3ddac457a60c92a6a941943fcd6a
ARTIFACT_SHA256=cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5
ARTIFACT_SIZE=60894273
ARTIFACT_PATH=/srv/minecraft/packages/vanilla/26.2/server.jar
MINECRAFT_PORT=25565
PROFILE_NAME=NEWISHIN_
PROFILE_UUID=e912ab95-758e-4b7f-b32e-292eda293104
RCON_PARAMETER_NAME=/wishicraft/dev/secret/rcon-password
RCON_PORT=25575
SERVER_PROPERTIES=/srv/minecraft/games/game-vanilla-main/server/server.properties'
readonly GAME_SETUP_B64='IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgLWV1byBwaXBlZmFpbAoKOiAiJHtNT1VOVF9HVUFSRDo/TU9VTlRfR1VBUkQgaXMgcmVxdWlyZWR9Igo6ICIke01PVU5UX1BBVEg6P01PVU5UX1BBVEggaXMgcmVxdWlyZWR9Igo6ICIke0dBTUVfSUQ6P0dBTUVfSUQgaXMgcmVxdWlyZWR9Igo6ICIke0dBTUVfRElSRUNUT1JZOj9HQU1FX0RJUkVDVE9SWSBpcyByZXF1aXJlZH0iCjogIiR7QVJUSUZBQ1RfUEFUSDo/QVJUSUZBQ1RfUEFUSCBpcyByZXF1aXJlZH0iCjogIiR7TUlORUNSQUZUX1BPUlQ6P01JTkVDUkFGVF9QT1JUIGlzIHJlcXVpcmVkfSIKOiAiJHtQUk9GSUxFX05BTUU6P1BST0ZJTEVfTkFNRSBpcyByZXF1aXJlZH0iCjogIiR7UFJPRklMRV9VVUlEOj9QUk9GSUxFX1VVSUQgaXMgcmVxdWlyZWR9IgoKcmVhZG9ubHkgU0VSVkVSX0RJUkVDVE9SWT0iJEdBTUVfRElSRUNUT1JZL3NlcnZlciIKCmZhaWwoKSB7IHByaW50ZiAnJXNcbicgIndpc2hpY3JhZnQgTWluZWNyYWZ0IGdhbWU6ICQqIiA+JjI7IGV4aXQgMTsgfQoKbm9ybWFsaXplX3V1aWQoKSB7CiAgbG9jYWwgdmFsdWU9IiR7MSwsfSIKICB2YWx1ZT0iJHt2YWx1ZS8vLS99IgogIFtbICIkdmFsdWUiID1+IF5bMC05YS1mXXszMn0kIF1dIHx8IHJldHVybiAxCiAgcHJpbnRmICclcycgIiR2YWx1ZSIKfQoKaHlwaGVuYXRlX3V1aWQoKSB7CiAgbG9jYWwgdmFsdWUKICB2YWx1ZT0iJChub3JtYWxpemVfdXVpZCAiJDEiKSIgfHwgcmV0dXJuIDEKICBwcmludGYgJyVzLSVzLSVzLSVzLSVzJyAiJHt2YWx1ZTowOjh9IiAiJHt2YWx1ZTo4OjR9IiAiJHt2YWx1ZToxMjo0fSIgIiR7dmFsdWU6MTY6NH0iICIke3ZhbHVlOjIwOjEyfSIKfQoKZW5zdXJlX2V4YWN0X2ZpbGUoKSB7CiAgbG9jYWwgcGF0aD0iJDEiIGNvbnRlbnQ9IiQyIiB0ZW1wb3JhcnkKICBpZiBbWyAtZSAiJHBhdGgiIF1dOyB0aGVuCiAgICBbWyAiJChjYXQgIiRwYXRoIikiID09ICIkY29udGVudCIgXV0gfHwgZmFpbCAiZXhpc3RpbmcgJHBhdGggZGlmZmVycyBmcm9tIG1hbmFnZWQgY29uZmlndXJhdGlvbiIKICAgIHJldHVybgogIGZpCiAgdGVtcG9yYXJ5PSIkKG1rdGVtcCAiJHtwYXRofS5YWFhYWFgiKSIKICBwcmludGYgJyVzXG4nICIkY29udGVudCIgPiAiJHRlbXBvcmFyeSIKICBjaG93biBtaW5lY3JhZnQ6bWluZWNyYWZ0ICIkdGVtcG9yYXJ5IgogIGNobW9kIDA2NDAgIiR0ZW1wb3JhcnkiCiAgbXYgIiR0ZW1wb3JhcnkiICIkcGF0aCIKfQoKdmVyaWZ5X3Byb3BlcnR5KCkgewogIGxvY2FsIGtleT0iJDEiIGV4cGVjdGVkPSIkMiIgcGF0aD0iJFNFUlZFUl9ESVJFQ1RPUlkvc2VydmVyLnByb3BlcnRpZXMiCiAgYXdrIC1GPSAtdiBrZXk9IiRrZXkiIC12IGV4cGVjdGVkPSIkZXhwZWN0ZWQiICcKICAgICQxID09IGtleSB7CiAgICAgIGlmICgkMCAhPSBleHBlY3RlZCkgaW52YWxpZCA9IDEKICAgICAgY291bnQrKwogICAgfQogICAgRU5EIHsgZXhpdCBjb3VudCA9PSAxICYmICFpbnZhbGlkID8gMCA6IDEgfQogICcgIiRwYXRoIiB8fCBmYWlsICIka2V5IGRpZmZlcnMiCn0KCnZlcmlmeSgpIHsKICBsb2NhbCBleHBlY3RlZF93aGl0ZWxpc3QKICBleHBlY3RlZF93aGl0ZWxpc3Q9IiQocHJpbnRmICdbe1widXVpZFwiOlwiJXNcIixcIm5hbWVcIjpcIiVzXCJ9XScgIiQoaHlwaGVuYXRlX3V1aWQgIiRQUk9GSUxFX1VVSUQiKSIgIiRQUk9GSUxFX05BTUUiKSIKICAiJE1PVU5UX0dVQVJEIiAtLXZlcmlmeQogIFtbIC1yICIkQVJUSUZBQ1RfUEFUSCIgXV0gfHwgZmFpbCAidmVyaWZpZWQgc2VydmVyIGFydGlmYWN0IGlzIG1pc3NpbmciCiAgW1sgLWQgIiRTRVJWRVJfRElSRUNUT1JZIiBdXSB8fCBmYWlsICJzZXJ2ZXIgZGlyZWN0b3J5IGlzIG1pc3NpbmciCiAgW1sgLXIgIiRTRVJWRVJfRElSRUNUT1JZL2V1bGEudHh0IiBdXSB8fCBmYWlsICJFVUxBIGZpbGUgaXMgbWlzc2luZyIKICBbWyAiJChjYXQgIiRTRVJWRVJfRElSRUNUT1JZL2V1bGEudHh0IikiID09ICJldWxhPXRydWUiIF1dIHx8IGZhaWwgIkVVTEEgaXMgbm90IGFjY2VwdGVkIgogIHZlcmlmeV9wcm9wZXJ0eSBzZXJ2ZXItcG9ydCAic2VydmVyLXBvcnQ9JE1JTkVDUkFGVF9QT1JUIgogIHZlcmlmeV9wcm9wZXJ0eSBvbmxpbmUtbW9kZSAnb25saW5lLW1vZGU9dHJ1ZScKICB2ZXJpZnlfcHJvcGVydHkgd2hpdGUtbGlzdCAnd2hpdGUtbGlzdD10cnVlJwogIHZlcmlmeV9wcm9wZXJ0eSBlbmZvcmNlLXdoaXRlbGlzdCAnZW5mb3JjZS13aGl0ZWxpc3Q9dHJ1ZScKICB2ZXJpZnlfcHJvcGVydHkgbWFuYWdlbWVudC1zZXJ2ZXItZW5hYmxlZCAnbWFuYWdlbWVudC1zZXJ2ZXItZW5hYmxlZD1mYWxzZScKICBncmVwIC1GcXggIiRleHBlY3RlZF93aGl0ZWxpc3QiICIkU0VSVkVSX0RJUkVDVE9SWS93aGl0ZWxpc3QuanNvbiIgfHwgZmFpbCAid2hpdGVsaXN0IGRpZmZlcnMiCn0KCnByZXBhcmUoKSB7CiAgIiRNT1VOVF9HVUFSRCIKICBbWyAiJEdBTUVfSUQiID1+IF5bYS16MC05LV0rJCBdXSB8fCBmYWlsICJpbnZhbGlkIGdhbWUgSUQiCiAgW1sgIiRNSU5FQ1JBRlRfUE9SVCIgPX4gXlsxLTldWzAtOV17MCw0fSQgXV0gfHwgZmFpbCAiaW52YWxpZCBNaW5lY3JhZnQgcG9ydCIKICBub3JtYWxpemVfdXVpZCAiJFBST0ZJTEVfVVVJRCIgPi9kZXYvbnVsbCB8fCBmYWlsICJpbnZhbGlkIHByb2ZpbGUgVVVJRCIKICBnZXRlbnQgZ3JvdXAgbWluZWNyYWZ0ID4vZGV2L251bGwgfHwgZ3JvdXBhZGQgLS1zeXN0ZW0gbWluZWNyYWZ0CiAgaWQgLXUgbWluZWNyYWZ0ID4vZGV2L251bGwgMj4mMSB8fCB1c2VyYWRkIC0tc3lzdGVtIC0tZ2lkIG1pbmVjcmFmdCAtLW5vLWNyZWF0ZS1ob21lIC0tc2hlbGwgL3NiaW4vbm9sb2dpbiBtaW5lY3JhZnQKICBpbnN0YWxsIC1kIC1vIHJvb3QgLWcgcm9vdCAtbSAwNzU1ICIkTU9VTlRfUEFUSC9nYW1lcyIgIiRHQU1FX0RJUkVDVE9SWSIKICBpbnN0YWxsIC1kIC1vIG1pbmVjcmFmdCAtZyBtaW5lY3JhZnQgLW0gMDc1MCAiJFNFUlZFUl9ESVJFQ1RPUlkiICIkR0FNRV9ESVJFQ1RPUlkvcnVudGltZSIKfQoKaWYgW1sgIiR7MTotfSIgPT0gIi0tdmVyaWZ5IiBdXTsgdGhlbgogIHZlcmlmeQogIGV4aXQgMApmaQppZiBbWyAiJHsxOi19IiA9PSAiLS1wcmVwYXJlIiBdXTsgdGhlbgogIHByZXBhcmUKICBleGl0IDAKZmkKW1sgJCMgLWVxIDAgXV0gfHwgZmFpbCAidW5zdXBwb3J0ZWQgYXJndW1lbnQ6ICQxIgoKcHJlcGFyZQpbWyAtciAiJEFSVElGQUNUX1BBVEgiIF1dIHx8IGZhaWwgInZlcmlmaWVkIHNlcnZlciBhcnRpZmFjdCBpcyBtaXNzaW5nIgplbnN1cmVfZXhhY3RfZmlsZSAiJFNFUlZFUl9ESVJFQ1RPUlkvZXVsYS50eHQiICdldWxhPXRydWUnCmVuc3VyZV9leGFjdF9maWxlICIkU0VSVkVSX0RJUkVDVE9SWS9zZXJ2ZXIucHJvcGVydGllcyIgInNlcnZlci1wb3J0PSRNSU5FQ1JBRlRfUE9SVApvbmxpbmUtbW9kZT10cnVlCndoaXRlLWxpc3Q9dHJ1ZQplbmZvcmNlLXdoaXRlbGlzdD10cnVlCm1hbmFnZW1lbnQtc2VydmVyLWVuYWJsZWQ9ZmFsc2UiCndoaXRlbGlzdF9jb250ZW50PSIkKHByaW50ZiAnW3tcInV1aWRcIjpcIiVzXCIsXCJuYW1lXCI6XCIlc1wifV0nICIkKGh5cGhlbmF0ZV91dWlkICIkUFJPRklMRV9VVUlEIikiICIkUFJPRklMRV9OQU1FIikiCmVuc3VyZV9leGFjdF9maWxlICIkU0VSVkVSX0RJUkVDVE9SWS93aGl0ZWxpc3QuanNvbiIgIiR3aGl0ZWxpc3RfY29udGVudCIKdmVyaWZ5Cg=='

regular_meta() { [[ -f "$1" && ! -L "$1" && "$(stat -c '%U:%G:%a' "$1")" == "$2" ]]; }
regular_meta() { [[ -f "$1" && ! -L "$1" && "$(stat -c '%U:%G:%a' "$1")" == "$2" ]]; }
hash_state() {
  local path="$1" meta="$2" bytes="$3" sha="$4"
  regular_meta "$path" "$meta" && [[ "$(stat -c %s "$path")" == "$bytes" ]] && [[ "$(sha256sum "$path"|awk '{print $1}')" == "$sha" ]]
}
upgrade_state() {
  local path="$1" meta="$2" predecessor_bytes="$3" predecessor_sha="$4" canonical_bytes="$5" canonical_sha="$6"
  hash_state "$path" "$meta" "$canonical_bytes" "$canonical_sha" && { printf canonical; return; }
  hash_state "$path" "$meta" "$predecessor_bytes" "$predecessor_sha" && { printf approved_predecessor; return; }
  printf conflict
}
atomic_content() {
  local path="$1" owner="$2" group="$3" mode="$4" content="$5" bytes="$6" sha="$7" tmp
  tmp="$(mktemp "${path}.XXXXXX")" || fail TEMP_CREATE 50
  trap 'rm -f "${tmp:-}"' RETURN
  printf '%s\n' "$content" >"$tmp" || fail TEMP_WRITE 51
  chown "$owner:$group" "$tmp" && chmod "$mode" "$tmp" || fail TEMP_META 52
  hash_state "$tmp" "$owner:$group:${mode#0}" "$bytes" "$sha" || fail TEMP_VERIFY 53
  mv "$tmp" "$path" || fail ATOMIC_PLACE 54
  tmp=; trap - RETURN
}
atomic_game_setup() {
  local tmp
  tmp="$(mktemp "${GAME_SETUP}.XXXXXX")" || fail TEMP_CREATE 50
  trap 'rm -f "${tmp:-}"' RETURN
  printf '%s' "$GAME_SETUP_B64" | base64 -d >"$tmp" || fail TEMP_WRITE 51
  python3 - "$tmp" <<'PY' || fail TEMP_WRITE 51
import pathlib,sys
path=pathlib.Path(sys.argv[1]); data=path.read_bytes()
old=b'  local value="${1,,}"\n'
new=b'''  local value
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
'''
if data.count(old)!=1: raise SystemExit(1)
path.write_bytes(data.replace(old,new,1))
PY
  chown root:root "$tmp" && chmod 0755 "$tmp" || fail TEMP_META 52
  hash_state "$tmp" root:root:755 "$GAME_SETUP_BYTES" "$GAME_SETUP_SHA" || fail TEMP_VERIFY 53
  [[ "$(upgrade_state "$GAME_SETUP" root:root:755 "$GAME_SETUP_PREDECESSOR_BYTES" "$GAME_SETUP_PREDECESSOR_SHA" "$GAME_SETUP_BYTES" "$GAME_SETUP_SHA")" == approved_predecessor ]] || fail GAME_SETUP_RACE 55
  mv "$tmp" "$GAME_SETUP" || fail ATOMIC_PLACE 54
  tmp=; trap - RETURN
}
verify_properties() {
  python3 - "$SERVER/server.properties" <<'PY'
import re,sys
pairs={}; expected={"server-port":"25565","online-mode":"true","white-list":"true","enforce-whitelist":"true","enable-rcon":"true","rcon.port":"25575","broadcast-rcon-to-ops":"false","management-server-enabled":"false"}
for raw in open(sys.argv[1],encoding="utf-8"):
 line=raw.rstrip("\n")
 if not line or line.startswith("#"): continue
 if "=" not in line: raise SystemExit(1)
 k,v=line.split("=",1)
 if k in pairs: raise SystemExit(1)
 pairs[k]=v
if set(pairs)!=set(expected)|{"rcon.password"} or any(pairs[k]!=v for k,v in expected.items()) or not pairs["rcon.password"]: raise SystemExit(1)
PY
}
non_target_fingerprint() {
  nft -j list ruleset | python3 -c 'import hashlib,json,sys
d=json.load(sys.stdin); kept=[]
for item in d.get("nftables",[]):
 if "metainfo" in item: continue
 key=next(iter(item)) if isinstance(item,dict) and item else None; obj=item.get(key,{}) if key else {}
 if isinstance(obj,dict) and obj.get("family")=="inet" and (obj.get("name")=="wishicraft_rcon" or obj.get("table")=="wishicraft_rcon"): continue
 if isinstance(obj,dict): obj={k:v for k,v in obj.items() if k!="handle"}
 kept.append({key:obj} if key else item)
print(hashlib.sha256(json.dumps(kept,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
}
verify_runtime() {
  [[ "$(systemctl show minecraft.service -p ActiveState --value)" == active ]] || return 1
  [[ "$(pgrep -u minecraft -f 'java.*server\.jar' | wc -l | tr -d ' ')" == 1 ]] || return 1
  [[ "$(ss -H -ltn|awk '$4~/:25565$/{n++} END{print n+0}')" == 1 ]] || return 1
  [[ "$(ss -H -ltn|awk '$4~/:25575$/{n++} END{print n+0}')" == 1 ]] || return 1
  [[ "$(ss -H -ltn|awk '$4~/:25585$/{n++} END{print n+0}')" == 0 ]] || return 1
}
verify_stopped() {
  [[ "$(systemctl show minecraft.service -p ActiveState --value)" == inactive ]] || return 1
  [[ "$(pgrep -u minecraft -f 'java.*server\.jar' 2>/dev/null | wc -l | tr -d ' ')" == 0 ]] || return 1
  [[ "$(ss -H -ltn|awk '$4~/(25565|25575|25585)$/ {n++} END{print n+0}')" == 0 ]] || return 1
}
verify_static() {
  findmnt -rn --target /srv/minecraft >/dev/null && [[ "$(findmnt -rn -o FSTYPE --target /srv/minecraft)" == xfs ]] || return 1
  hash_state "$JAR" root:root:644 "$JAR_BYTES" "$JAR_SHA" || return 1
  hash_state "$UNIT" root:root:644 "$UNIT_BYTES" "$UNIT_SHA" || return 1
  regular_meta "$FIREWALL_SCRIPT" root:root:755 && [[ "$(sha256sum "$FIREWALL_SCRIPT"|awk '{print $1}')" == "$FIREWALL_SHA" ]] || return 1
  regular_meta "$FIREWALL_RULES" root:root:600 && [[ "$(sha256sum "$FIREWALL_RULES"|awk '{print $1}')" == "$FIREWALL_RULES_SHA" ]] || return 1
  [[ "$(env RCON_PORT=25575 "$FIREWALL_SCRIPT" --classify-table)" == canonical ]] || return 1
  verify_properties || return 1
  [[ -d "$SERVER/world" && -d "$SERVER/logs" && ! -L "$SERVER/world" && ! -L "$SERVER/logs" ]] || return 1
  compgen -G "$SERVER/*.tmp.*" >/dev/null && return 1
}

checkpoint P00_START
[[ "$(id -u)" == 0 ]] || fail NOT_ROOT 10
verify_static || fail STATIC 12
WHITELIST_STATE="$(upgrade_state "$WHITELIST" minecraft:minecraft:640 "$WHITELIST_PREDECESSOR_BYTES" "$WHITELIST_PREDECESSOR_SHA" "$WHITELIST_BYTES" "$WHITELIST_SHA")"
ENV_STATE="$(upgrade_state "$ENV_FILE" root:root:644 "$ENV_PREDECESSOR_BYTES" "$ENV_PREDECESSOR_SHA" "$ENV_BYTES" "$ENV_SHA")"
GAME_SETUP_STATE="$(upgrade_state "$GAME_SETUP" root:root:755 "$GAME_SETUP_PREDECESSOR_BYTES" "$GAME_SETUP_PREDECESSOR_SHA" "$GAME_SETUP_BYTES" "$GAME_SETUP_SHA")"
[[ "$WHITELIST_STATE" != conflict ]] || fail WHITELIST_PREDECESSOR 13
[[ "$ENV_STATE" != conflict ]] || fail ENV_PREDECESSOR 14
[[ "$GAME_SETUP_STATE" != conflict ]] || fail GAME_SETUP_PREDECESSOR 15
checkpoint "STATE:whitelist=$WHITELIST_STATE"
checkpoint "STATE:env=$ENV_STATE"
checkpoint "STATE:game_setup=$GAME_SETUP_STATE"
if verify_runtime; then
  RUNTIME_STATE=active
elif verify_stopped && [[ "$WHITELIST_STATE" == canonical || "$ENV_STATE" == canonical || "$GAME_SETUP_STATE" == canonical ]]; then
  RUNTIME_STATE=stopped_partial
else
  fail RUNTIME 11
fi
checkpoint "STATE:runtime=$RUNTIME_STATE"
NON_TARGET_BEFORE="$(non_target_fingerprint)" || fail NON_TARGET_QUERY 16
pass P01_PREFLIGHT
verify_static || fail RACE 17
if [[ "$RUNTIME_STATE" == active ]]; then verify_runtime || fail RACE 17; else verify_stopped || fail RACE 17; fi
[[ "$(upgrade_state "$WHITELIST" minecraft:minecraft:640 "$WHITELIST_PREDECESSOR_BYTES" "$WHITELIST_PREDECESSOR_SHA" "$WHITELIST_BYTES" "$WHITELIST_SHA")" == "$WHITELIST_STATE" ]] || fail WHITELIST_RACE 18
[[ "$(upgrade_state "$ENV_FILE" root:root:644 "$ENV_PREDECESSOR_BYTES" "$ENV_PREDECESSOR_SHA" "$ENV_BYTES" "$ENV_SHA")" == "$ENV_STATE" ]] || fail ENV_RACE 19
[[ "$(upgrade_state "$GAME_SETUP" root:root:755 "$GAME_SETUP_PREDECESSOR_BYTES" "$GAME_SETUP_PREDECESSOR_SHA" "$GAME_SETUP_BYTES" "$GAME_SETUP_SHA")" == "$GAME_SETUP_STATE" ]] || fail GAME_SETUP_RACE 55
checkpoint C00_CHANGE_BEGIN
if [[ "$RUNTIME_STATE" == active ]]; then systemctl stop minecraft.service || fail STOP 20; fi
verify_stopped || fail STOP_STATE 21
pass C01_STOPPED
[[ "$GAME_SETUP_STATE" == canonical ]] || atomic_game_setup
[[ "$ENV_STATE" == canonical ]] || atomic_content "$ENV_FILE" root root 0644 "$ENV_CONTENT" "$ENV_BYTES" "$ENV_SHA"
[[ "$WHITELIST_STATE" == canonical ]] || atomic_content "$WHITELIST" minecraft minecraft 0640 "$WHITELIST_CONTENT" "$WHITELIST_BYTES" "$WHITELIST_SHA"
pass C02_ATOMIC_UPDATE
hash_state "$GAME_SETUP" root:root:755 "$GAME_SETUP_BYTES" "$GAME_SETUP_SHA" || fail GAME_SETUP_POST 24
hash_state "$ENV_FILE" root:root:644 "$ENV_BYTES" "$ENV_SHA" || fail ENV_POST 25
hash_state "$WHITELIST" minecraft:minecraft:640 "$WHITELIST_BYTES" "$WHITELIST_SHA" || fail WHITELIST_POST 26
systemctl start minecraft.service || fail START 27
for _ in $(seq 1 120); do verify_runtime && break; sleep 2; done
verify_runtime || fail READY 28
verify_static || fail STATIC_POST 29
[[ "$(non_target_fingerprint)" == "$NON_TARGET_BEFORE" ]] || fail NON_TARGET_CHANGED 30
pass F00_POSTFLIGHT
checkpoint OK:minecraft_whitelist_repair_completed
