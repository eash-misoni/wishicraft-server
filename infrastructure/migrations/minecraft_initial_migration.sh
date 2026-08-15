#!/usr/bin/env bash
# One-shot, fail-closed Wishicraft Minecraft 26.2 initial-game migration.
set -euo pipefail
set +x
umask 077

checkpoint() { printf '%s\n' "$1"; }
fail() { checkpoint "FAIL:$1"; exit "${2:-1}"; }
pass() { checkpoint "PASS:$1"; }

readonly MOUNT_PATH=/srv/minecraft
readonly GAME_ID=game-vanilla-main
readonly GAME_DIR="$MOUNT_PATH/games/$GAME_ID"
readonly SERVER_DIR="$GAME_DIR/server"
readonly RUNTIME_DIR="$GAME_DIR/runtime"
readonly JAR="$MOUNT_PATH/packages/vanilla/26.2/server.jar"
readonly JAR_URL=https://piston-data.mojang.com/v1/objects/823e2250d24b3ddac457a60c92a6a941943fcd6a/server.jar
readonly JAR_BYTES=60894273
readonly JAR_SHA1=823e2250d24b3ddac457a60c92a6a941943fcd6a
readonly JAR_SHA256=cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5
readonly DATA_VOLUME_ID=vol-03ac9f534326c345c
readonly MINECRAFT_PORT=25565
readonly RCON_PORT=25575
readonly RCON_PARAMETER=/wishicraft/dev/secret/rcon-password
readonly PLAYER=NEWISHIN_
readonly PLAYER_UUID=e912ab95758e4b7fb32e292eda293104
readonly UNIT=/etc/systemd/system/minecraft.service
readonly ENABLE_LINK=/etc/systemd/system/multi-user.target.wants/minecraft.service
readonly ENV_FILE=/etc/wishicraft/minecraft.env
readonly FIREWALL_SCRIPT=/usr/local/lib/wishicraft/minecraft_rcon_firewall.sh
readonly FIREWALL_SHA=e17f38bc39dc88a974c60e0cb3320b0032567c35a0da0a1b10bed89791ab5bb2
readonly FIREWALL_RULES=/etc/nftables/wishicraft-rcon.nft
readonly FIREWALL_RULES_SHA=f1625836adf67b4297cb7e134abacea53cef84e269e7af4a4ff9e1f1cb2490db
readonly RCON_DROPIN=/etc/systemd/system/minecraft.service.d/wishicraft-rcon-firewall.conf
readonly MOUNT_GUARD=/usr/local/lib/wishicraft/data_volume_mount.sh
readonly MOUNT_GUARD_SHA=31a74e772514846a6646ca7efba632eab283d29de01992cb6d8010a235b90a3f
readonly GAME_SETUP=/usr/local/lib/wishicraft/minecraft_game_setup.sh
readonly GAME_SETUP_SHA=6d42df504412818f807046afa0c2caa082d3d636d71f035a53de90d4cdab2e9b
readonly GAME_SETUP_BYTES=3349
readonly GAME_SETUP_PREDECESSOR_SHA=8836bd8a6c5fb123de397c5fdab255c80fd5ce92b3f678447c82e368432f78c6
readonly GAME_SETUP_PREDECESSOR_BYTES=3340
readonly UNIT_PREDECESSOR_SHA=9377a424367281f4a0ff9311c6b1efcb6be727b95ad0319d7b4daf4a4e91f038
readonly UNIT_PREDECESSOR_BYTES=889

readonly UNIT_CONTENT='[Unit]
Description=Wishicraft Minecraft server
Requires=wishicraft-data-volume.service
Requires=wishicraft-rcon-firewall.service
After=wishicraft-data-volume.service wishicraft-rcon-firewall.service

[Service]
Type=simple
User=minecraft
Group=minecraft
EnvironmentFile=/etc/wishicraft/minecraft.env
WorkingDirectory=/srv/minecraft/games/game-vanilla-main/server
ExecStartPre=+/usr/local/lib/wishicraft/data_volume_mount.sh --verify
ExecStartPre=+/usr/local/lib/wishicraft/minecraft_game_setup.sh --verify
ExecStart=/usr/bin/java -Xms1G -Xmx3G -jar /srv/minecraft/packages/vanilla/26.2/server.jar nogui
TimeoutStopSec=30
KillSignal=SIGTERM
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/srv/minecraft/games/game-vanilla-main/server /srv/minecraft/games/game-vanilla-main/runtime

[Install]
WantedBy=multi-user.target'
readonly DROPIN_CONTENT='[Unit]
Requires=wishicraft-rcon-firewall.service
After=wishicraft-rcon-firewall.service'
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
PROFILE_UUID=e912ab95758e4b7fb32e292eda293104
RCON_PARAMETER_NAME=/wishicraft/dev/secret/rcon-password
RCON_PORT=25575
SERVER_PROPERTIES=/srv/minecraft/games/game-vanilla-main/server/server.properties'
readonly EULA_CONTENT=eula=true
readonly WHITELIST_CONTENT='[{"uuid":"e912ab95758e4b7fb32e292eda293104","name":"NEWISHIN_"}]'

regular_meta() { [[ -f "$1" && ! -L "$1" && "$(stat -c '%U:%G:%a' "$1")" == "$2" ]]; }
exact_content() { [[ "$(cat "$1")" == "$2" ]]; }
classify_exact_file() {
  local path="$1" meta="$2" content="$3"
  [[ -e "$path" || -L "$path" ]] || { printf absent; return; }
  regular_meta "$path" "$meta" && exact_content "$path" "$content" && { printf canonical; return; }
  printf conflict
}
classify_dir() {
  local path="$1" meta="$2"
  [[ -e "$path" || -L "$path" ]] || { printf absent; return; }
  [[ -d "$path" && ! -L "$path" && "$(stat -c '%U:%G:%a' "$path")" == "$meta" ]] && { printf canonical; return; }
  printf conflict
}
classify_hash_file() {
  local path="$1" meta="$2" bytes="$3" sha="$4"
  [[ -e "$path" || -L "$path" ]] || { printf absent; return; }
  regular_meta "$path" "$meta" && [[ "$(stat -c %s "$path")" == "$bytes" ]] &&
    [[ "$(sha256sum "$path"|awk '{print $1}')" == "$sha" ]] && { printf canonical; return; }
  printf conflict
}
unit_state() {
  local state
  state="$(classify_exact_file "$UNIT" root:root:644 "$UNIT_CONTENT")"
  [[ "$state" != conflict ]] && { printf '%s' "$state"; return; }
  [[ "$(classify_hash_file "$UNIT" root:root:644 "$UNIT_PREDECESSOR_BYTES" "$UNIT_PREDECESSOR_SHA")" == canonical ]] &&
    { printf approved_predecessor; return; }
  printf conflict
}
game_setup_state() {
  local state
  state="$(classify_hash_file "$GAME_SETUP" root:root:755 "$GAME_SETUP_BYTES" "$GAME_SETUP_SHA")"
  [[ "$state" != conflict ]] && { printf '%s' "$state"; return; }
  [[ "$(classify_hash_file "$GAME_SETUP" root:root:755 "$GAME_SETUP_PREDECESSOR_BYTES" "$GAME_SETUP_PREDECESSOR_SHA")" == canonical ]] &&
    { printf approved_predecessor; return; }
  printf conflict
}
atomic_file() {
  local path="$1" owner="$2" group="$3" mode="$4" content="$5" tmp
  tmp="$(mktemp "${path}.XXXXXX")" || fail TEMP_CREATE 61
  trap 'rm -f "${tmp:-}"' RETURN
  printf '%s\n' "$content" >"$tmp" || fail TEMP_WRITE 62
  chown "$owner:$group" "$tmp" && chmod "$mode" "$tmp" || fail TEMP_META 63
  [[ "$(stat -c '%U:%G:%a' "$tmp")" == "$owner:$group:${mode#0}" ]] || fail TEMP_VERIFY 64
  mv "$tmp" "$path" || fail ATOMIC_PLACE 65
  tmp=
  trap - RETURN
}
assert_no_processes() {
  ! systemctl is-active --quiet minecraft.service || fail MINECRAFT_ACTIVE 20
  ! pgrep -u minecraft -f 'java.*server\.jar' >/dev/null 2>&1 || fail JAVA_PROCESS_PRESENT 21
  ! ss -H -ltn 2>/dev/null | awk '$4 ~ /:(25565|25575)$/ {found=1} END {exit !found}' || fail LISTENER_PRESENT 22
}
verify_mount() {
  local source serial
  findmnt -rn --target "$MOUNT_PATH" >/dev/null || fail MOUNT_ABSENT 23
  [[ "$(findmnt -rn -o FSTYPE --target "$MOUNT_PATH")" == xfs ]] || fail MOUNT_TYPE 24
  source="$(readlink -f "$(findmnt -rn -o SOURCE --target "$MOUNT_PATH")")" || fail MOUNT_QUERY 25
  serial="$(lsblk -dn -o SERIAL "$source" | tr -d '-')"
  [[ "${serial,,}" == "${DATA_VOLUME_ID//-/}" ]] || fail MOUNT_VOLUME 26
  [[ "$(awk '$1 !~ /^#/ && $2=="/srv/minecraft" && $1 ~ /^UUID=/ && $3=="xfs" && $4=="defaults,nofail" {n++} END {print n+0}' /etc/fstab)" == 1 ]] || fail FSTAB 27
}
verify_java() {
  rpm -q java-25-amazon-corretto-headless >/dev/null || fail JAVA_PACKAGE 28
  [[ "$(command -v java)" == /usr/bin/java ]] || fail JAVA_PATH 29
  local v; v="$(java -version 2>&1)" || fail JAVA_QUERY 30
  grep -Eq 'version "25([. ]|$)' <<<"$v" && grep -qi Corretto <<<"$v" || fail JAVA_VERSION 31
}
verify_firewall() {
  regular_meta "$FIREWALL_SCRIPT" root:root:755 || fail FIREWALL_SCRIPT_META 32
  [[ "$(sha256sum "$FIREWALL_SCRIPT" | awk '{print $1}')" == "$FIREWALL_SHA" ]] || fail FIREWALL_SCRIPT_HASH 33
  regular_meta "$FIREWALL_RULES" root:root:600 || fail FIREWALL_RULES_META 34
  [[ "$(sha256sum "$FIREWALL_RULES" | awk '{print $1}')" == "$FIREWALL_RULES_SHA" ]] || fail FIREWALL_RULES_HASH 35
  [[ "$(systemctl show wishicraft-rcon-firewall.service -p ActiveState --value)" == active ]] || fail FIREWALL_UNIT 36
  [[ "$(env RCON_PORT="$RCON_PORT" "$FIREWALL_SCRIPT" --classify-table)" == canonical ]] || fail FIREWALL_TABLE 37
}
verify_bootstrap_dependencies() {
  regular_meta "$MOUNT_GUARD" root:root:755 || fail MOUNT_GUARD_META 13
  [[ "$(sha256sum "$MOUNT_GUARD"|awk '{print $1}')" == "$MOUNT_GUARD_SHA" ]] || fail MOUNT_GUARD_HASH 14
  [[ "$(game_setup_state)" != conflict && "$(game_setup_state)" != absent ]] || fail GAME_SETUP_HASH 16
}
quiesce_known_failed_service() {
  local load active sub
  load="$(systemctl show minecraft.service -p LoadState --value 2>/dev/null || true)"
  [[ "$load" == loaded ]] || return 0
  active="$(systemctl show minecraft.service -p ActiveState --value 2>/dev/null || true)"
  sub="$(systemctl show minecraft.service -p SubState --value 2>/dev/null || true)"
  case "$active:$sub" in
    inactive:dead|failed:failed) return 0 ;;
    activating:auto-restart)
      systemctl stop minecraft.service || fail QUIESCE_STOP 84
      [[ "$(systemctl show minecraft.service -p ActiveState --value)" == inactive ]] || fail QUIESCE_STATE 85
      assert_no_processes
      pass C00_QUIESCE
      ;;
    *) fail SERVICE_STATE_CONFLICT 86 ;;
  esac
}
upgrade_game_setup() {
  local tmp
  tmp="$(mktemp "${GAME_SETUP}.XXXXXX")" || fail GAME_SETUP_TEMP 87
  trap 'rm -f "${tmp:-}"' RETURN
  python3 - "$GAME_SETUP" "$tmp" <<'PY' || fail GAME_SETUP_BUILD 88
import pathlib,sys
source=pathlib.Path(sys.argv[1]).read_bytes()
old=b'  "$MOUNT_GUARD"\n  [[ -r "$ARTIFACT_PATH" ]]'
new=b'  "$MOUNT_GUARD" --verify\n  [[ -r "$ARTIFACT_PATH" ]]'
if source.count(old) != 1:
    raise SystemExit(1)
pathlib.Path(sys.argv[2]).write_bytes(source.replace(old,new,1))
PY
  chown root:root "$tmp" && chmod 0755 "$tmp" || fail GAME_SETUP_META 89
  [[ "$(stat -c %s "$tmp")" == "$GAME_SETUP_BYTES" && "$(sha256sum "$tmp"|awk '{print $1}')" == "$GAME_SETUP_SHA" ]] || fail GAME_SETUP_VERIFY 90
  [[ "$(game_setup_state)" == approved_predecessor ]] || fail GAME_SETUP_RACE 91
  mv "$tmp" "$GAME_SETUP" || fail GAME_SETUP_PLACE 92
  tmp=; trap - RETURN
}
non_target_fingerprint() {
  nft -j list ruleset | python3 -c 'import hashlib,json,sys
d=json.load(sys.stdin); kept=[]
for item in d.get("nftables",[]):
    if "metainfo" in item: continue
    obj=next(iter(item.values())) if isinstance(item,dict) and item else {}
    if isinstance(obj,dict) and obj.get("family")=="inet" and (obj.get("name")=="wishicraft_rcon" or obj.get("table")=="wishicraft_rcon"): continue
    if isinstance(obj,dict): obj={k:v for k,v in obj.items() if k not in {"handle"}}
    kept.append(item if not isinstance(item,dict) or not item else {next(iter(item)):obj})
print(hashlib.sha256(json.dumps(kept,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
}
verify_jar() {
  regular_meta "$JAR" root:root:644 || return 1
  [[ "$(stat -c %s "$JAR")" == "$JAR_BYTES" ]] &&
    [[ "$(sha1sum "$JAR" | awk '{print $1}')" == "$JAR_SHA1" ]] &&
    [[ "$(sha256sum "$JAR" | awk '{print $1}')" == "$JAR_SHA256" ]]
}
properties_state() {
  local path="$SERVER_DIR/server.properties"
  [[ -e "$path" || -L "$path" ]] || { printf absent; return; }
  regular_meta "$path" root:minecraft:640 || { printf conflict; return; }
  python3 - "$path" <<'PY' || { printf conflict; return; }
import re,sys
pairs={}; allowed={"server-port":"25565","online-mode":"true","white-list":"true","enforce-whitelist":"true","enable-rcon":"true","rcon.port":"25575","broadcast-rcon-to-ops":"false","management-server-enabled":"false"}
for raw in open(sys.argv[1],encoding="utf-8"):
    line=raw.rstrip("\n")
    if not line or line.startswith("#"): continue
    if "=" not in line: raise SystemExit(1)
    k,v=line.split("=",1)
    if k in pairs: raise SystemExit(1)
    pairs[k]=v
if set(pairs)!=set(allowed)|{"rcon.password"}: raise SystemExit(1)
if any(pairs[k]!=v for k,v in allowed.items()): raise SystemExit(1)
if not re.fullmatch(r"[A-Za-z0-9!#$%&()*+,./:;?@\[\]^_{}~-]{16,}",pairs["rcon.password"]): raise SystemExit(1)
PY
  printf canonical
}
account_state() {
  local group_line user_line uid gid user_gid shell
  group_line="$(getent group minecraft || true)"; user_line="$(getent passwd minecraft || true)"
  if [[ -z "$group_line" && -z "$user_line" ]]; then printf absent; return; fi
  [[ -n "$group_line" && -n "$user_line" ]] || { printf conflict; return; }
  gid="$(cut -d: -f3 <<<"$group_line")"; uid="$(cut -d: -f3 <<<"$user_line")"
  user_gid="$(cut -d: -f4 <<<"$user_line")"; shell="$(cut -d: -f7 <<<"$user_line")"
  [[ "$uid" =~ ^[0-9]+$ && "$gid" =~ ^[0-9]+$ && "$uid" -lt 1000 && "$gid" -lt 1000 && "$user_gid" == "$gid" && "$shell" == /sbin/nologin ]] && { printf canonical; return; }
  printf conflict
}
enable_state() {
  if [[ ! -e "$ENABLE_LINK" && ! -L "$ENABLE_LINK" ]]; then printf absent; return; fi
  [[ -L "$ENABLE_LINK" ]] || { printf conflict; return; }
  [[ -e "$ENABLE_LINK" && "$(readlink -f "$ENABLE_LINK")" == "$UNIT" ]] && { printf canonical; return; }
  printf conflict
}
env_state() {
  [[ -e "$ENV_FILE" || -L "$ENV_FILE" ]] || { printf absent; return; }
  regular_meta "$ENV_FILE" root:root:644 || { printf conflict; return; }
  exact_content "$ENV_FILE" "$ENV_CONTENT" && { printf canonical; return; }
  [[ "$(stat -c %s "$ENV_FILE")" == 799 && "$(sha256sum "$ENV_FILE"|awk '{print $1}')" == 973b24da0b4669b07b396ab4f9d5222aa6525427cb4890b55f4f9e110e42d2ec ]] && { printf approved_predecessor; return; }
  printf conflict
}
completed_state() {
  [[ "$(systemctl show minecraft.service -p ActiveState --value 2>/dev/null)" == active ]] || return 1
  verify_mount && verify_java && verify_firewall && verify_bootstrap_dependencies && verify_jar || return 1
  [[ "$(game_setup_state)" == canonical ]] || return 1
  [[ "$(account_state)" == canonical && "$(properties_state)" == canonical ]] || return 1
  [[ "$(classify_exact_file "$ENV_FILE" root:root:644 "$ENV_CONTENT")" == canonical ]] || return 1
  [[ "$(classify_exact_file "$UNIT" root:root:644 "$UNIT_CONTENT")" == canonical ]] || return 1
  [[ "$(classify_exact_file "$RCON_DROPIN" root:root:644 "$DROPIN_CONTENT")" == canonical ]] || return 1
  [[ "$(enable_state)" == canonical ]] || return 1
  [[ "$(classify_exact_file "$SERVER_DIR/eula.txt" minecraft:minecraft:640 "$EULA_CONTENT")" == canonical ]] || return 1
  [[ "$(classify_exact_file "$SERVER_DIR/whitelist.json" minecraft:minecraft:640 "$WHITELIST_CONTENT")" == canonical ]] || return 1
  [[ -d "$SERVER_DIR/world" && -f "$SERVER_DIR/logs/latest.log" ]] || return 1
  grep -Fq 'Done (' "$SERVER_DIR/logs/latest.log" || return 1
  [[ "$(ss -H -ltn | awk '$4 ~ /:25565$/ {n++} END {print n+0}')" == 1 ]] || return 1
  [[ "$(ss -H -ltn | awk '$4 ~ /:25575$/ {n++} END {print n+0}')" == 1 ]] || return 1
  [[ "$(ss -H -ltn | awk '$4 ~ /:25585$/ {n++} END {print n+0}')" == 0 ]] || return 1
}

checkpoint P00_START
[[ "$(id -u)" == 0 ]] || fail NOT_ROOT 10
command -v python3 >/dev/null || fail PYTHON_MISSING 11
if systemctl is-active --quiet minecraft.service; then
  completed_state || fail ACTIVE_STATE_CONFLICT 12
  pass P99_CANONICAL_NOOP
  checkpoint OK:minecraft_initial_game_completed
  exit 0
fi
assert_no_processes; pass P01_STOPPED
verify_mount; pass P02_MOUNT
verify_java; pass P03_JAVA
verify_firewall; pass P04_FIREWALL
NON_TARGET_BEFORE="$(non_target_fingerprint)" || fail NON_TARGET_QUERY 38
readonly NON_TARGET_BEFORE
verify_bootstrap_dependencies; pass P04_BOOTSTRAP_DEPENDENCIES

declare -A states
states[account]="$(account_state)"
states[mount]="$(classify_dir "$MOUNT_PATH" root:root:755)"
states[packages]="$(classify_dir "$MOUNT_PATH/packages" root:root:755)"
states[vanilla]="$(classify_dir "$MOUNT_PATH/packages/vanilla" root:root:755)"
states[version]="$(classify_dir "$MOUNT_PATH/packages/vanilla/26.2" root:root:755)"
states[games]="$(classify_dir "$MOUNT_PATH/games" root:root:755)"
states[game]="$(classify_dir "$GAME_DIR" root:root:755)"
states[server]="$(classify_dir "$SERVER_DIR" minecraft:minecraft:750)"
states[runtime]="$(classify_dir "$RUNTIME_DIR" minecraft:minecraft:750)"
states[eula]="$(classify_exact_file "$SERVER_DIR/eula.txt" minecraft:minecraft:640 "$EULA_CONTENT")"
states[whitelist]="$(classify_exact_file "$SERVER_DIR/whitelist.json" minecraft:minecraft:640 "$WHITELIST_CONTENT")"
states[properties]="$(properties_state)"
states[env]="$(env_state)"
states[unit]="$(unit_state)"
states[dropin]="$(classify_exact_file "$RCON_DROPIN" root:root:644 "$DROPIN_CONTENT")"
states[enable]="$(enable_state)"
states[game_setup]="$(game_setup_state)"
for key in "${!states[@]}"; do checkpoint "STATE:$key=${states[$key]}"; [[ "${states[$key]}" != conflict ]] || fail "${key^^}_CONFLICT" 40; done
if [[ -e "$JAR" || -L "$JAR" ]]; then verify_jar || fail JAR_CONFLICT 41; states[jar]=canonical; else states[jar]=absent; fi
compgen -G "$MOUNT_PATH/packages/vanilla/26.2/.server.jar.*" >/dev/null && fail JAR_TEMP_CONFLICT 42
compgen -G "$SERVER_DIR/*.tmp.*" >/dev/null && fail CONFIG_TEMP_CONFLICT 43
for path in "$SERVER_DIR/world" "$SERVER_DIR/world_nether" "$SERVER_DIR/world_the_end" "$SERVER_DIR/logs"; do [[ ! -e "$path" && ! -L "$path" ]] || fail PREEXISTING_RUNTIME_STATE 44; done
pass P05_ARTIFACT_CLASSIFICATION

# Race check before the first mutation.
assert_no_processes; verify_mount; verify_firewall
[[ "$(properties_state)" == "${states[properties]}" ]] || fail PROPERTIES_RACE 45
[[ "$(env_state)" == "${states[env]}" ]] || fail ENV_RACE 46
[[ "$(unit_state)" == "${states[unit]}" ]] || fail UNIT_RACE 80
[[ "$(game_setup_state)" == "${states[game_setup]}" ]] || fail GAME_SETUP_RACE 91
[[ "$(classify_exact_file "$RCON_DROPIN" root:root:644 "$DROPIN_CONTENT")" == "${states[dropin]}" ]] || fail DROPIN_RACE 81
[[ "$(enable_state)" == "${states[enable]}" ]] || fail ENABLE_RACE 82
if [[ "${states[jar]}" == canonical ]]; then verify_jar || fail JAR_RACE 55; else [[ ! -e "$JAR" && ! -L "$JAR" ]] || fail JAR_RACE 55; fi
for path in "$SERVER_DIR/world" "$SERVER_DIR/world_nether" "$SERVER_DIR/world_the_end" "$SERVER_DIR/logs"; do [[ ! -e "$path" && ! -L "$path" ]] || fail RUNTIME_RACE 83; done
pass P06_RACE
checkpoint C00_CHANGE_BEGIN
quiesce_known_failed_service

if [[ "${states[game_setup]}" == approved_predecessor ]]; then upgrade_game_setup; fi
[[ "$(game_setup_state)" == canonical ]] || fail GAME_SETUP_POST 93

if [[ "${states[account]}" == absent ]]; then
  groupadd --system minecraft || fail GROUP_CREATE 47
  useradd --system --gid minecraft --no-create-home --shell /sbin/nologin minecraft || fail USER_CREATE 48
fi
[[ "$(account_state)" == canonical ]] || fail ACCOUNT_POST 49

for spec in \
  "$MOUNT_PATH/packages:root:root:0755" "$MOUNT_PATH/packages/vanilla:root:root:0755" \
  "$MOUNT_PATH/packages/vanilla/26.2:root:root:0755" "$MOUNT_PATH/games:root:root:0755" \
  "$GAME_DIR:root:root:0755" "$SERVER_DIR:minecraft:minecraft:0750" "$RUNTIME_DIR:minecraft:minecraft:0750"; do
  IFS=: read -r path owner group mode <<<"$spec"
  [[ -e "$path" ]] || install -d -o "$owner" -g "$group" -m "$mode" "$path" || fail DIRECTORY_CREATE 50
done
pass C01_DIRECTORIES

if [[ "${states[jar]}" == absent ]]; then
  tmp="$(mktemp "$MOUNT_PATH/packages/vanilla/26.2/.server.jar.XXXXXX")" || fail JAR_TEMP 51
  trap 'rm -f "${tmp:-}"' EXIT
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 300 --retry 2 --output "$tmp" "$JAR_URL" || fail JAR_DOWNLOAD 52
  [[ "$(stat -c %s "$tmp")" == "$JAR_BYTES" && "$(sha1sum "$tmp"|awk '{print $1}')" == "$JAR_SHA1" && "$(sha256sum "$tmp"|awk '{print $1}')" == "$JAR_SHA256" ]] || fail JAR_VERIFY 53
  chown root:root "$tmp" && chmod 0644 "$tmp" || fail JAR_META 54
  [[ ! -e "$JAR" && ! -L "$JAR" ]] || fail JAR_RACE 55
  mv "$tmp" "$JAR" || fail JAR_PLACE 56; tmp=; trap - EXIT
fi
verify_jar || fail JAR_POST 57; pass C02_JAR

[[ "${states[eula]}" == canonical ]] || atomic_file "$SERVER_DIR/eula.txt" minecraft minecraft 0640 "$EULA_CONTENT"
[[ "${states[whitelist]}" == canonical ]] || atomic_file "$SERVER_DIR/whitelist.json" minecraft minecraft 0640 "$WHITELIST_CONTENT"
if [[ "${states[properties]}" == absent ]]; then
  command -v aws >/dev/null || fail AWS_CLI 58
  secret="$(timeout 30 aws ssm get-parameter --name "$RCON_PARAMETER" --with-decryption --output json | python3 -c 'import json,re,sys; p=json.load(sys.stdin)["Parameter"]; v=p["Value"]; assert p["Type"]=="SecureString" and re.fullmatch(r"[A-Za-z0-9!#$%&()*+,./:;?@\[\]^_{}~-]{16,}",v); sys.stdout.write(v)')" || fail SECRET_RETRIEVAL 59
  atomic_file "$SERVER_DIR/server.properties" root minecraft 0640 "server-port=25565
online-mode=true
white-list=true
enforce-whitelist=true
enable-rcon=true
rcon.port=25575
rcon.password=$secret
broadcast-rcon-to-ops=false
management-server-enabled=false"
  unset secret
fi
[[ "$(properties_state)" == canonical ]] || fail PROPERTIES_POST 60
[[ "${states[env]}" == canonical ]] || atomic_file "$ENV_FILE" root root 0644 "$ENV_CONTENT"
if [[ "${states[unit]}" != canonical ]]; then
  [[ "$(unit_state)" == "${states[unit]}" ]] || fail UNIT_RACE 80
  atomic_file "$UNIT" root root 0644 "$UNIT_CONTENT"
fi
pass C03_CONFIGURATION

assert_no_processes; verify_mount; verify_java; verify_firewall; verify_jar
[[ "$(properties_state)" == canonical ]] || fail FINAL_RACE 66
systemctl daemon-reload || fail DAEMON_RELOAD 67
systemctl enable minecraft.service || fail ENABLE 68
[[ "$(enable_state)" == canonical ]] || fail ENABLE_LINK 79
systemctl start minecraft.service || fail START 69
pass C04_START

ready=false
for _ in $(seq 1 120); do
  [[ "$(systemctl show minecraft.service -p ActiveState --value)" == active ]] || fail SERVICE_EXITED 70
  if [[ -f "$SERVER_DIR/logs/latest.log" ]] && grep -Fq 'Done (' "$SERVER_DIR/logs/latest.log"; then ready=true; break; fi
  sleep 2
done
[[ "$ready" == true ]] || fail READY_TIMEOUT 71
[[ "$(ss -H -ltn | awk '$4 ~ /:25565$/ {n++} END {print n+0}')" == 1 ]] || fail MINECRAFT_LISTENER 72
[[ "$(ss -H -ltn | awk '$4 ~ /:25575$/ {n++} END {print n+0}')" == 1 ]] || fail RCON_LISTENER 73
[[ "$(ss -H -ltn | awk '$4 ~ /:25585$/ {n++} END {print n+0}')" == 0 ]] || fail MANAGEMENT_LISTENER 75
verify_mount; verify_firewall
[[ "$(non_target_fingerprint)" == "$NON_TARGET_BEFORE" ]] || fail NON_TARGET_CHANGED 78
[[ "$(systemctl show minecraft.service -p ActiveState --value)" == active ]] || fail POST_SERVICE 76
[[ -d "$SERVER_DIR/world" && "$(findmnt -rn -o TARGET --target "$SERVER_DIR/world")" == "$MOUNT_PATH" ]] || fail WORLD_DATA_PATH 77
pass F00_POSTFLIGHT
checkpoint OK:minecraft_initial_game_completed
