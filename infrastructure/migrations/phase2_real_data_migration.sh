#!/usr/bin/env bash
# Fail-closed Phase 2b real-data host migration. Never formats or repairs a filesystem.
set -euo pipefail
set +x
umask 077

readonly EXPECTED_TARGET_INSTANCE=i-04fc0629dc4ea466e
readonly EXPECTED_SOURCE_INSTANCE=i-021eaa7f33ddaf0a6
readonly EXPECTED_VOLUME=vol-03ac9f534326c345c
readonly EXPECTED_UUID=420cea6d-0520-4436-bb5a-db1191f1e63b
readonly EXPECTED_AZ=ap-northeast-1a
readonly EXPECTED_SIZE_BYTES=32212254720
readonly MOUNT_PATH=/srv/minecraft
readonly SERVER_DIR=/srv/minecraft/games/game-vanilla-main/server
readonly PROPERTIES="$SERVER_DIR/server.properties"
readonly STATE_DIR=/var/lib/wishicraft/phase2-migration
readonly FSTAB=/etc/fstab
readonly FSTAB_ENTRY="UUID=$EXPECTED_UUID $MOUNT_PATH xfs defaults,nofail 0 2 # wishicraft-phase2-data-volume"

fail() { printf 'FAIL:%s\n' "$1" >&2; exit "${2:-1}"; }
pass() { printf 'PASS:%s\n' "$1"; }
normalize_volume() { tr -d '-' <<<"$1" | tr '[:upper:]' '[:lower:]'; }

instance_id() {
  local token
  token="$(curl -fsS --connect-timeout 5 -X PUT \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
    http://169.254.169.254/latest/api/token)" || fail IMDS_TOKEN
  curl -fsS --connect-timeout 5 -H "X-aws-ec2-metadata-token: $token" \
    http://169.254.169.254/latest/meta-data/instance-id
}

expected_device() {
  local path serial found=
  while read -r path serial; do
    if [[ "$(normalize_volume "$serial")" == "$(normalize_volume "$EXPECTED_VOLUME")" ]]; then
      [[ -z "$found" ]] || fail DUPLICATE_VOLUME_DEVICE
      found="$path"
    fi
  done < <(lsblk -dn -o PATH,SERIAL)
  [[ -n "$found" ]] || fail DATA_DEVICE_ABSENT
  printf '%s\n' "$found"
}

raw_preflight() {
  local device type uuid signatures children size
  [[ "$(id -u)" == 0 ]] || fail NOT_ROOT
  [[ "$(instance_id)" == "$EXPECTED_TARGET_INSTANCE" ]] || fail TARGET_INSTANCE
  device="$(expected_device)"
  children="$(lsblk -nr -o TYPE "$device" | tail -n +2)"
  [[ -z "$children" ]] || fail UNEXPECTED_PARTITION
  size="$(blockdev --getsize64 "$device")"
  [[ "$size" == "$EXPECTED_SIZE_BYTES" ]] || fail DEVICE_SIZE
  type="$(blkid -s TYPE -o value "$device" 2>/dev/null || true)"
  uuid="$(blkid -s UUID -o value "$device" 2>/dev/null || true)"
  signatures="$(wipefs -n --noheadings --output TYPE "$device" | awk '{$1=$1} NF' | sort -u)"
  [[ "$type" == xfs ]] || fail FILESYSTEM_TYPE
  [[ "$uuid" == "$EXPECTED_UUID" ]] || fail FILESYSTEM_UUID
  [[ "$signatures" == xfs ]] || fail FILESYSTEM_SIGNATURES
  printf 'OBS:source_instance=%s target_instance=%s az=%s volume=%s device=%s size=%s type=%s uuid=%s\n' \
    "$EXPECTED_SOURCE_INSTANCE" "$EXPECTED_TARGET_INSTANCE" "$EXPECTED_AZ" "$EXPECTED_VOLUME" \
    "$device" "$size" "$type" "$uuid"
  pass RAW_DEVICE_PREFLIGHT
}

verify_mount() {
  local device source options
  raw_preflight
  device="$(expected_device)"
  findmnt -rn --target "$MOUNT_PATH" >/dev/null || fail MOUNT_ABSENT
  source="$(readlink -f "$(findmnt -rn -o SOURCE --target "$MOUNT_PATH")")"
  [[ "$source" == "$(readlink -f "$device")" ]] || fail MOUNT_SOURCE
  [[ "$(findmnt -rn -o UUID --target "$MOUNT_PATH")" == "$EXPECTED_UUID" ]] || fail MOUNT_UUID
  [[ "$(findmnt -rn -o FSTYPE --target "$MOUNT_PATH")" == xfs ]] || fail MOUNT_TYPE
  options="$(findmnt -rn -o OPTIONS --target "$MOUNT_PATH")"
  [[ ",$options," == *,rw,* ]] || fail MOUNT_NOT_RW
  pass MOUNT_GUARD
}

mount_existing() {
  local entries temporary
  raw_preflight
  if findmnt -rn --target "$MOUNT_PATH" >/dev/null 2>&1; then
    verify_mount
    return
  fi
  install -d -o root -g root -m 0755 "$MOUNT_PATH"
  [[ -z "$(find "$MOUNT_PATH" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail MOUNT_PATH_NOT_EMPTY
  entries="$(awk -v path="$MOUNT_PATH" '$1 !~ /^#/ && NF >= 2 && $2 == path {print}' "$FSTAB")"
  [[ -z "$entries" || "$entries" == "$FSTAB_ENTRY" ]] || fail FSTAB_CONFLICT
  if [[ -z "$entries" ]]; then
    temporary="$(mktemp "${FSTAB}.phase2.XXXXXX")"
    cp --preserve=mode,ownership,timestamps "$FSTAB" "$temporary"
    printf '%s\n' "$FSTAB_ENTRY" >>"$temporary"
    [[ "$(awk -v path="$MOUNT_PATH" '$1 !~ /^#/ && $2 == path {n++} END {print n+0}' "$temporary")" == 1 ]] || fail FSTAB_BUILD
    mv "$temporary" "$FSTAB"
  fi
  mount "$MOUNT_PATH"
  verify_mount
}

no_extended_acl() {
  getfacl -cp -- "$1" | awk '/^$/ {next} /^(user::|group::|other::)/ {next} {exit 1}'
}

filesystem_preflight() {
  local path uid gid unknown=0 count=0
  verify_mount
  command -v getfacl >/dev/null || fail GETFACL_MISSING
  [[ -d "$SERVER_DIR" && ! -L "$SERVER_DIR" ]] || fail SERVER_DIRECTORY
  [[ "$(stat -c '%u:%g:%a:%F' "$SERVER_DIR")" == '993:993:750:directory' ]] || fail SERVER_DIRECTORY_META
  while IFS= read -r -d '' path; do
    ((count += 1))
    [[ ! -L "$path" ]] || fail SYMLINK
    [[ -d "$path" || -f "$path" ]] || fail SPECIAL_FILE
    no_extended_acl "$path" || fail EXTENDED_ACL
    uid="$(stat -c %u -- "$path")"; gid="$(stat -c %g -- "$path")"
    if [[ "$path" == "$PROPERTIES" ]]; then
      [[ "$uid:$gid" == 0:993 || "$uid:$gid" == 993:993 ]] || fail PROPERTIES_OWNER
    elif [[ "$uid:$gid" != 993:993 ]]; then
      ((unknown += 1))
    fi
  done < <(find "$SERVER_DIR" -xdev -print0)
  [[ "$unknown" == 0 ]] || fail UNKNOWN_OWNER
  printf 'OBS:filesystem_entries=%s unknown_owners=%s\n' "$count" "$unknown"
  pass FILESYSTEM_PREFLIGHT
}

properties_migrate() {
  local before after
  filesystem_preflight
  [[ -f "$PROPERTIES" && ! -L "$PROPERTIES" ]] || fail PROPERTIES_TYPE
  no_extended_acl "$PROPERTIES" || fail PROPERTIES_ACL
  before="$(stat -c '%s:%i:%u:%g:%a:%F' "$PROPERTIES"):$(sha256sum "$PROPERTIES" | cut -d ' ' -f1)"
  [[ "$before" == *':0:993:640:regular file:'* ]] || fail PROPERTIES_PRECONDITION
  install -d -o root -g root -m 0700 "$STATE_DIR"
  printf '%s\n' "$before" >"$STATE_DIR/server-properties.before"
  chown 993:993 "$PROPERTIES"
  after="$(stat -c '%s:%i:%u:%g:%a:%F' "$PROPERTIES"):$(sha256sum "$PROPERTIES" | cut -d ' ' -f1)"
  [[ "${after/:993:993:/:0:993:}" == "$before" ]] || fail PROPERTIES_POSTCONDITION
  pass PROPERTIES_OWNERSHIP_MIGRATED
}

properties_verify_realized() {
  verify_mount
  [[ -f "$PROPERTIES" && ! -L "$PROPERTIES" ]] || fail PROPERTIES_TYPE
  [[ "$(stat -c '%u:%g:%a:%F' "$PROPERTIES")" == '993:993:640:regular file' ]] || fail PROPERTIES_META
  no_extended_acl "$PROPERTIES" || fail PROPERTIES_ACL
  [[ "$(grep -Ec '^enable-rcon=false$' "$PROPERTIES")" == 1 ]] || fail RCON_NOT_DISABLED
  printf 'OBS:properties_size=%s inode=%s sha256=%s\n' \
    "$(stat -c %s "$PROPERTIES")" "$(stat -c %i "$PROPERTIES")" \
    "$(sha256sum "$PROPERTIES" | cut -d ' ' -f1)"
  pass PROPERTIES_REALIZED
}

world_record() {
  local world="$SERVER_DIR/world" regions
  filesystem_preflight
  [[ -d "$world" && ! -L "$world" && -f "$world/level.dat" ]] || fail WORLD_STRUCTURE
  regions="$(find "$world" -xdev -type f -name '*.mca' | wc -l | tr -d ' ')"
  [[ "$regions" -gt 0 ]] || fail WORLD_REGION_EMPTY
  install -d -o root -g root -m 0700 "$STATE_DIR"
  printf '%s:%s\n' "$(stat -c %i "$world")" "$regions" >"$STATE_DIR/world.before"
  printf 'OBS:world_inode=%s region_files=%s\n' "$(stat -c %i "$world")" "$regions"
  pass EXISTING_WORLD_RECORDED
}

world_verify() {
  local world="$SERVER_DIR/world" expected regions
  verify_mount
  [[ -f "$STATE_DIR/world.before" ]] || fail WORLD_EVIDENCE_MISSING
  expected="$(cut -d: -f1 "$STATE_DIR/world.before")"
  [[ -d "$world" && "$(stat -c %i "$world")" == "$expected" && -f "$world/level.dat" ]] || fail WORLD_IDENTITY
  regions="$(find "$world" -xdev -type f -name '*.mca' | wc -l | tr -d ' ')"
  [[ "$regions" -gt 0 ]] || fail WORLD_REGION_EMPTY
  printf 'OBS:world_inode=%s region_files=%s\n' "$expected" "$regions"
  pass EXISTING_WORLD_PERSISTED
}

case "${1:-}" in
  --raw-preflight) raw_preflight ;;
  --mount-existing) mount_existing ;;
  --mount-verify|--verify) verify_mount ;;
  --filesystem-preflight) filesystem_preflight ;;
  --properties-migrate) properties_migrate ;;
  --properties-verify-realized) properties_verify_realized ;;
  --world-record) world_record ;;
  --world-verify) world_verify ;;
  *) fail UNSUPPORTED_MODE 64 ;;
esac
