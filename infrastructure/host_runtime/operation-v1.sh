#!/usr/bin/env bash
set -euo pipefail

readonly HOST_RUNTIME_UNIT=wishicraft-host-runtime.service

if [[ "$#" -ne 1 || ( "$1" != "START" && "$1" != "STOP" ) ]]; then
  printf '%s\n' '{"schema_version":1,"status":"rejected","error_code":"INVALID_OPERATION"}'
  exit 64
fi

if [[ "$1" == "START" ]]; then
  if systemctl is-active --quiet "$HOST_RUNTIME_UNIT"; then
    printf '%s\n' '{"schema_version":1,"operation":"START","status":"accepted"}'
    exit 0
  fi
  /usr/local/libexec/wishicraft/rcon-secret-v1 prepare
  if ! systemctl start "$HOST_RUNTIME_UNIT"; then
    /usr/local/libexec/wishicraft/rcon-secret-v1 remove
    exit 1
  fi
  systemctl is-active --quiet "$HOST_RUNTIME_UNIT"
  printf '%s\n' '{"schema_version":1,"operation":"START","status":"accepted"}'
else
  /usr/local/libexec/wishicraft/stop-v1
  /usr/local/libexec/wishicraft/rcon-secret-v1 remove
  printf '%s\n' '{"schema_version":1,"operation":"STOP","status":"succeeded"}'
fi
