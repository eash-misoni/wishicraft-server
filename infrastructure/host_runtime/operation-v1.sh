#!/usr/bin/env bash
set -euo pipefail

readonly HOST_RUNTIME_UNIT=wishicraft-host-runtime.service

if [[ "$#" -ne 1 || "$1" != "START" ]]; then
  printf '%s\n' '{"schema_version":1,"status":"rejected","error_code":"INVALID_OPERATION"}'
  exit 64
fi

systemctl start "$HOST_RUNTIME_UNIT"
systemctl is-active --quiet "$HOST_RUNTIME_UNIT"
printf '%s\n' '{"schema_version":1,"operation":"START","status":"accepted"}'
