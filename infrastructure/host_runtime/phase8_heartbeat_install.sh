#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_ROOT=/var/tmp/wishicraft-phase8-heartbeat-v2
readonly PACKAGE_ROOT=/usr/local/libexec/wishicraft
readonly ENV_PATH=/etc/wishicraft/heartbeat.env
readonly SERVICE_PATH=/etc/systemd/system/wishicraft-heartbeat.service
readonly TIMER_PATH=/etc/systemd/system/wishicraft-heartbeat.timer

fail() { printf 'FAIL:%s\n' "$1" >&2; exit "${2:-70}"; }
sha256() { sha256sum "$1" | cut -d ' ' -f 1; }

install_fixed() {
  local source="$1" target="$2" digest="$3" mode="$4"
  local temporary
  [[ -f "$source" && ! -L "$source" && "$(sha256 "$source")" == "$digest" ]] || \
    fail SOURCE_MISMATCH
  if [[ -e "$target" || -L "$target" ]]; then
    [[ -f "$target" && ! -L "$target" && "$(sha256 "$target")" == "$digest" ]] || \
      fail UNAPPROVED_EXISTING_TARGET
    [[ "$(stat -c '%U:%G:%a' "$target")" == "root:root:$mode" ]] || fail TARGET_IDENTITY
    return
  fi
  temporary="$(mktemp "$(dirname "$target")/.heartbeat.XXXXXX")"
  trap 'rm -f -- "${temporary:-}"' RETURN
  install -o root -g root -m "$mode" "$source" "$temporary"
  [[ "$(sha256 "$temporary")" == "$digest" ]] || fail TEMPORARY_MISMATCH
  mv -f -- "$temporary" "$target"
  trap - RETURN
}

main() {
  [[ "$#" -eq 0 && "$(id -u)" -eq 0 ]] || fail INVOCATION 64
  command -v aws >/dev/null || fail AWS_CLI_MISSING
  command -v python3 >/dev/null || fail PYTHON_MISSING
  install -d -o root -g root -m 755 "$PACKAGE_ROOT"
  install_fixed "$SOURCE_ROOT/__init__.py" "$PACKAGE_ROOT/__init__.py" \
    35d5944f8d5ea699f6074219075ad1fe0e3abce2e9271a282f8600e966be90b0 644
  install_fixed "$SOURCE_ROOT/runtime_heartbeat.py" "$PACKAGE_ROOT/runtime_heartbeat.py" \
    d92dd704ccc56f821ba5116298a8861bab70ad26d29101cbc23ef423ffd1b0d9 644
  install_fixed "$SOURCE_ROOT/runtime_heartbeat_producer.py" \
    "$PACKAGE_ROOT/runtime_heartbeat_producer.py" \
    a7e2b141d2f5b4c79fb5f847f633557c4935dc0374da044a16b6dcc3134e9999 644
  install_fixed "$SOURCE_ROOT/host_runtime_probe.py" "$PACKAGE_ROOT/host-runtime-probe.py" \
    0efcf7e493d85495e36c2234c8ebee3b7a35fdba0f855e527ec1a3d51e1bebb2 755
  install_fixed "$SOURCE_ROOT/heartbeat.env" "$ENV_PATH" \
    251792467184d0b01bb3bf76f953cd99744947dc4046027a853f268586a7f7c2 600
  install_fixed "$SOURCE_ROOT/wishicraft-heartbeat.service" "$SERVICE_PATH" \
    cda0c2e22e6079ba2859a45abc5779f3037f684cc02c4e8dbabe81e7a79b0be0 644
  install_fixed "$SOURCE_ROOT/wishicraft-heartbeat.timer" "$TIMER_PATH" \
    a186a1893904c797b297aa924f6f83d06b0a7d264aac992e5c08f7abe1bf2b54 644
  systemctl daemon-reload
  systemctl enable --now wishicraft-heartbeat.timer
  printf 'PASS:PHASE8_HEARTBEAT_INSTALL\n'
}

main "$@"
