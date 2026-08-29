#!/usr/bin/env bash
set -euo pipefail

readonly COMPOSE_PATH=/etc/wishicraft/host-runtime/compose.yaml
readonly UNIT_PATH=/etc/systemd/system/wishicraft-host-runtime.service
readonly COMPOSE_PREDECESSOR_SHA256=08c5cee203eb8350e30778456ccd1e240eeff5e9cc65494b292684092c0108a7
readonly COMPOSE_TARGET_SHA256=c92fbbfb8c955e249b39edbd2b2063e0cfa05214d8242bdeb302dd1d996b0770
readonly UNIT_PREDECESSOR_SHA256=01abb954ad53d08bfedc393da1b7b0b6d0b58c8b9b1ffaccd442b5a922d2728a
readonly UNIT_TARGET_SHA256=6de3ea3ecfa68537f804872b467400e1e0316ed6627d50e5ed96fa80af2c1608
readonly COMPOSE_TARGET_BASE64=bmFtZTogd2lzaGljcmFmdC1ob3N0LXJ1bnRpbWUKc2VydmljZXM6CiAgbWluZWNyYWZ0OgogICAgZW52X2ZpbGU6CiAgICAtIHJ1bnRpbWUuZW52CiAgICBpbWFnZTogZ2hjci5pby9pdHpnL21pbmVjcmFmdC1zZXJ2ZXI6MjAyNi43LjItamF2YTI1QHNoYTI1Njo2ZWMxMTEwZTRkOTIzNmQwMGFlOTQzNmEzZTRhNTkyOTU4M2U1YjE5Y2M5NGI3NTZhN2M2MDNmN2NmNjQ3YTc3CiAgICBsYWJlbHM6CiAgICAgIGNvbS53aXNoaWNyYWZ0LmFjdGl2ZS1nYW1lLWRhdGEtc291cmNlOiAvc3J2L21pbmVjcmFmdC9nYW1lcy9nYW1lLXZhbmlsbGEtbWFpbi9zZXJ2ZXIKICAgICAgY29tLndpc2hpY3JhZnQuYWN0aXZlLWdhbWUtaWQ6IGdhbWUtdmFuaWxsYS1tYWluCiAgICBtZW1fbGltaXQ6IDI4MTZNaUIKICAgIHBvcnRzOgogICAgLSAyNTU2NToyNTU2NS90Y3AKICAgIHB1bGxfcG9saWN5OiBuZXZlcgogICAgcmVzdGFydDogJ25vJwogICAgc3RvcF9ncmFjZV9wZXJpb2Q6IDE1MHMKICAgIHZvbHVtZXM6CiAgICAtIHNvdXJjZTogL3Nydi9taW5lY3JhZnQvZ2FtZXMvZ2FtZS12YW5pbGxhLW1haW4vc2VydmVyCiAgICAgIHRhcmdldDogL2RhdGEKICAgICAgdHlwZTogYmluZAo=
readonly UNIT_TARGET_BASE64=W1VuaXRdCkRlc2NyaXB0aW9uPVdpc2hpY3JhZnQgaXR6ZyBIb3N0IFJ1bnRpbWUKUmVxdWlyZXM9d2lzaGljcmFmdC1kYXRhLXZvbHVtZS5zZXJ2aWNlIGRvY2tlci5zZXJ2aWNlCkFmdGVyPXdpc2hpY3JhZnQtZGF0YS12b2x1bWUuc2VydmljZSBkb2NrZXIuc2VydmljZQpSZXF1aXJlc01vdW50c0Zvcj0vc3J2L21pbmVjcmFmdAoKW1NlcnZpY2VdClR5cGU9b25lc2hvdApSZW1haW5BZnRlckV4aXQ9eWVzCkVudmlyb25tZW50RmlsZT0vZXRjL3dpc2hpY3JhZnQvaG9zdC1ydW50aW1lLmVudgpFeGVjU3RhcnQ9L3Vzci9sb2NhbC9saWIvd2lzaGljcmFmdC1ob3N0LXJ1bnRpbWUvc3RhcnQuc2gKRXhlY1N0b3A9L3Vzci9sb2NhbC9saWIvd2lzaGljcmFmdC1ob3N0LXJ1bnRpbWUvc3RvcC5zaApUaW1lb3V0U3RhcnRTZWM9MzAwClRpbWVvdXRTdG9wU2VjPTE4MApSZXN0YXJ0PW5vCgojIERlbGliZXJhdGVseSBubyBbSW5zdGFsbF0gc2VjdGlvbjogQ29udHJvbCBQbGFuZS9Ib3N0IFJ1bnRpbWUgc3RhcnRzIGl0IGV4cGxpY2l0bHkuCg==

sha256() { sha256sum "$1" | cut -d ' ' -f 1; }

apply_artifact() {
  local path="$1" predecessor="$2" target="$3" payload="$4" mode="$5" owner="$6"
  local current temporary
  [[ -f "$path" && ! -L "$path" ]] || { printf 'FAIL:TYPE:%s\n' "$path" >&2; return 70; }
  [[ "$(stat -c '%U:%G' "$path")" == "$owner" ]] || {
    printf 'FAIL:OWNER:%s\n' "$path" >&2
    return 71
  }
  current="$(sha256 "$path")"
  if [[ "$current" == "$target" ]]; then
    [[ "$(stat -c '%a' "$path")" == "$mode" ]] || return 72
    printf 'PASS:CURRENT:%s\n' "$path"
    return 0
  fi
  [[ "$current" == "$predecessor" ]] || {
    printf 'FAIL:UNAPPROVED_PREDECESSOR:%s:%s\n' "$path" "$current" >&2
    return 73
  }
  temporary="${path}.phase5-upgrade.$$"
  trap 'rm -f "${temporary:-}"' RETURN
  umask 077
  printf '%s' "$payload" | base64 -d >"$temporary"
  [[ "$(sha256 "$temporary")" == "$target" ]] || return 74
  chown "$owner" "$temporary"
  chmod "$mode" "$temporary"
  mv -f "$temporary" "$path"
  trap - RETURN
  [[ "$(sha256 "$path")" == "$target" ]] || return 75
  [[ "$(stat -c '%U:%G:%a' "$path")" == "$owner:$mode" ]] || return 76
  printf 'PASS:UPGRADED:%s\n' "$path"
}

main() {
  [[ "$#" -eq 0 ]] || { printf 'FAIL:ARGUMENTS\n' >&2; return 64; }
  [[ "$(systemctl is-active wishicraft-host-runtime.service 2>/dev/null || true)" != active ]] || {
    printf 'FAIL:HOST_RUNTIME_ACTIVE\n' >&2
    return 65
  }
  [[ "$(docker ps --filter label=com.docker.compose.project=wishicraft --format '{{.ID}}' | wc -l)" -eq 0 ]] || {
    printf 'FAIL:CONTAINER_RUNNING\n' >&2
    return 66
  }
  [[ "$(ss -H -ltn sport = :25565 2>/dev/null | wc -l)" -eq 0 ]] || {
    printf 'FAIL:LISTENER_PRESENT\n' >&2
    return 67
  }
  apply_artifact "$COMPOSE_PATH" "$COMPOSE_PREDECESSOR_SHA256" \
    "$COMPOSE_TARGET_SHA256" "$COMPOSE_TARGET_BASE64" 600 root:root
  apply_artifact "$UNIT_PATH" "$UNIT_PREDECESSOR_SHA256" \
    "$UNIT_TARGET_SHA256" "$UNIT_TARGET_BASE64" 644 root:root
  grep -F 'com.wishicraft.active-game-id: game-vanilla-main' "$COMPOSE_PATH" >/dev/null
  grep -F 'com.wishicraft.active-game-data-source: /srv/minecraft/games/game-vanilla-main/server' \
    "$COMPOSE_PATH" >/dev/null
  ! grep -Eiq 'password|secret|token|rcon' "$COMPOSE_PATH"
  grep -Fx 'RequiresMountsFor=/srv/minecraft' "$UNIT_PATH" >/dev/null
  ! grep -Eq '^WantedBy=|^RequiredBy=' "$UNIT_PATH"
  systemctl daemon-reload
  printf 'PASS:PHASE5_RUNTIME_CONTRACT_UPGRADE\n'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
