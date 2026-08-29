#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly RUNTIME_DIR=/run/wishicraft
readonly SECRET_PATH="$RUNTIME_DIR/rcon-password"
readonly CLI_ENV_PATH="$RUNTIME_DIR/rcon-cli.env"
readonly CLI_YAML_PATH="$RUNTIME_DIR/rcon-cli.yaml"
readonly ENV_PATH=/etc/wishicraft/rcon.env

fail() {
  printf '%s\n' '{"schema_version":1,"status":"failed","error_code":"RCON_SECRET_FAILED"}'
  exit 70
}

[[ "$#" -eq 1 && ( "$1" == "prepare" || "$1" == "remove" ) ]] || fail

if [[ "$1" == "remove" ]]; then
  rm -f -- "$SECRET_PATH" "$CLI_ENV_PATH" "$CLI_YAML_PATH"
  exit 0
fi

[[ -f "$ENV_PATH" && ! -L "$ENV_PATH" ]] || fail
parameter_name="$(sed -n 's/^RCON_PARAMETER_NAME=//p' "$ENV_PATH")"
[[ "$parameter_name" =~ ^/wishicraft/(dev|prod)/secret/rcon-password$ ]] || fail
install -d -o root -g root -m 0700 "$RUNTIME_DIR"
install -o root -g root -m 0600 /dev/null "$CLI_ENV_PATH"
install -o root -g root -m 0600 /dev/null "$CLI_YAML_PATH"
temporary="$(mktemp "$RUNTIME_DIR/.rcon-password.XXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
chmod 0400 "$temporary"
aws ssm get-parameter \
  --name "$parameter_name" \
  --with-decryption \
  --query Parameter.Value \
  --output text >"$temporary" || fail
[[ -s "$temporary" && "$(wc -l <"$temporary")" -le 1 ]] || fail
chown root:root "$temporary"
mv -f -- "$temporary" "$SECRET_PATH"
trap - EXIT
[[ -f "$SECRET_PATH" && ! -L "$SECRET_PATH" ]] || fail
[[ "$(stat -c '%U:%G:%a' "$SECRET_PATH")" == "root:root:400" ]] || fail
[[ "$(stat -c '%U:%G:%a' "$CLI_ENV_PATH")" == "root:root:600" ]] || fail
[[ "$(stat -c '%U:%G:%a' "$CLI_YAML_PATH")" == "root:root:600" ]] || fail
printf '%s\n' '{"schema_version":1,"operation":"RCON_SECRET_PREPARE","status":"succeeded"}'
