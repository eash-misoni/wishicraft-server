#!/usr/bin/env bash
set -euo pipefail

: "${DATA_VOLUME_ID:?DATA_VOLUME_ID is required}"
: "${MOUNT_PATH:?MOUNT_PATH is required}"
: "${FILESYSTEM_TYPE:?FILESYSTEM_TYPE is required}"

readonly FSTAB_PATH="${WISHICRAFT_FSTAB_PATH:-/etc/fstab}"
readonly MARKER_PATH="${WISHICRAFT_MOUNT_MARKER_PATH:-/run/wishicraft/data-volume-mounted}"
readonly MAX_ATTEMPTS="${WISHICRAFT_DEVICE_WAIT_ATTEMPTS:-60}"
readonly WAIT_SECONDS="${WISHICRAFT_DEVICE_WAIT_SECONDS:-2}"

fail() {
  rm -f "$MARKER_PATH"
  printf '%s\n' "wishicraft data volume: $*" >&2
  exit 1
}

normalize_volume_id() {
  tr -d '-' <<<"$1" | tr '[:upper:]' '[:lower:]'
}

find_expected_device() {
  local expected_serial device serial
  expected_serial="$(normalize_volume_id "$DATA_VOLUME_ID")"

  while read -r device serial; do
    if [[ "$(normalize_volume_id "$serial")" == "$expected_serial" ]]; then
      printf '%s\n' "$device"
      return 0
    fi
  done < <(lsblk --nodeps --noheadings --output PATH,SERIAL)
  return 1
}

wait_for_expected_device() {
  local attempt device
  for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    if device="$(find_expected_device)"; then
      printf '%s\n' "$device"
      return 0
    fi
    if ((attempt < MAX_ATTEMPTS)); then
      sleep "$WAIT_SECONDS"
    fi
  done
  fail "timed out waiting for EBS volume $DATA_VOLUME_ID"
}

ensure_expected_filesystem() {
  local device filesystem_type signatures
  device="$1"
  filesystem_type="$(blkid --output value --match-token TYPE "$device" 2>/dev/null || true)"
  signatures="$(wipefs --noheadings --output TYPE "$device")"

  if [[ -z "$filesystem_type" && -z "$signatures" ]]; then
    mkfs.xfs "$device"
    return 0
  fi
  if [[ "$filesystem_type" == "$FILESYSTEM_TYPE" && "$signatures" == "$FILESYSTEM_TYPE" ]]; then
    return 0
  fi
  fail "refusing to modify volume $DATA_VOLUME_ID with existing signatures"
}

ensure_fstab_entry() {
  local uuid expected_entry existing_entries temporary_fstab
  uuid="$1"
  expected_entry="UUID=$uuid $MOUNT_PATH $FILESYSTEM_TYPE defaults,nofail 0 2 # wishicraft-data-volume"
  existing_entries="$(awk -v mount_path="$MOUNT_PATH" '
    $1 !~ /^#/ && NF >= 2 && $2 == mount_path { print }
  ' "$FSTAB_PATH")"

  if [[ -n "$existing_entries" && "$existing_entries" != "$expected_entry" ]]; then
    fail "fstab already has a conflicting entry for $MOUNT_PATH"
  fi
  if [[ "$existing_entries" == "$expected_entry" ]]; then
    return 0
  fi

  temporary_fstab="$(mktemp "${FSTAB_PATH}.XXXXXX")"
  cat "$FSTAB_PATH" > "$temporary_fstab"
  printf '%s\n' "$expected_entry" >> "$temporary_fstab"
  mv "$temporary_fstab" "$FSTAB_PATH"
}

verify_mount() {
  local device uuid source mounted_uuid mounted_type
  device="$1"
  uuid="$2"
  source="$(findmnt --noheadings --output SOURCE --target "$MOUNT_PATH")"
  mounted_uuid="$(findmnt --noheadings --output UUID --target "$MOUNT_PATH")"
  mounted_type="$(findmnt --noheadings --output FSTYPE --target "$MOUNT_PATH")"

  [[ "$(readlink -f "$source")" == "$(readlink -f "$device")" ]] || fail "mount source differs from expected volume"
  [[ "$mounted_uuid" == "$uuid" ]] || fail "mount UUID differs from expected volume"
  [[ "$mounted_type" == "$FILESYSTEM_TYPE" ]] || fail "mount filesystem type differs from expected volume"
}

prepare_mount_path() {
  if findmnt --noheadings --target "$MOUNT_PATH" >/dev/null 2>&1; then
    return 0
  fi
  mkdir -p "$MOUNT_PATH"
  [[ -z "$(find "$MOUNT_PATH" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "unmounted mount path is not empty"
}

main() {
  local device uuid
  [[ "$FILESYSTEM_TYPE" == "xfs" ]] || fail "unsupported filesystem type: $FILESYSTEM_TYPE"
  [[ "$MAX_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || fail "invalid device wait attempts"
  [[ "$WAIT_SECONDS" =~ ^[0-9]+$ ]] || fail "invalid device wait seconds"

  device="$(wait_for_expected_device)"
  ensure_expected_filesystem "$device"
  uuid="$(blkid --output value --match-token UUID "$device")"
  [[ -n "$uuid" ]] || fail "expected filesystem UUID is missing"

  if findmnt --noheadings --target "$MOUNT_PATH" >/dev/null 2>&1; then
    verify_mount "$device" "$uuid"
    ensure_fstab_entry "$uuid"
    install -d -m 0755 "$(dirname "$MARKER_PATH")"
    : > "$MARKER_PATH"
    return 0
  fi

  prepare_mount_path
  ensure_fstab_entry "$uuid"
  mount "$MOUNT_PATH"
  verify_mount "$device" "$uuid"
  install -d -m 0755 "$(dirname "$MARKER_PATH")"
  : > "$MARKER_PATH"
}

verify_only() {
  local device uuid filesystem_type
  [[ "$FILESYSTEM_TYPE" == "xfs" ]] || fail "unsupported filesystem type: $FILESYSTEM_TYPE"
  device="$(wait_for_expected_device)"
  filesystem_type="$(blkid --output value --match-token TYPE "$device" 2>/dev/null || true)"
  [[ "$filesystem_type" == "$FILESYSTEM_TYPE" ]] || fail "expected filesystem type is missing"
  uuid="$(blkid --output value --match-token UUID "$device")"
  [[ -n "$uuid" ]] || fail "expected filesystem UUID is missing"
  findmnt --noheadings --target "$MOUNT_PATH" >/dev/null 2>&1 || fail "mount path is not mounted"
  verify_mount "$device" "$uuid"
}

if [[ "${1:-}" == "--verify" ]]; then
  verify_only
elif [[ $# -eq 0 ]]; then
  main
else
  fail "unsupported argument: $1"
fi
