#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly RUNTIME_DIR=/run/wishicraft
readonly SECRET_PATH="$RUNTIME_DIR/rcon-password"
readonly CLI_ENV_PATH="$RUNTIME_DIR/rcon-cli.env"
readonly CLI_YAML_PATH="$RUNTIME_DIR/rcon-cli.yaml"
readonly ENV_PATH=/etc/wishicraft/rcon.env
readonly RUNTIME_ENV_PATH=/etc/wishicraft/host-runtime/runtime.env
readonly HOST_ENV_PATH=/etc/wishicraft/host-runtime.env

fail() {
  printf '%s\n' '{"schema_version":1,"status":"failed","error_code":"RCON_SECRET_FAILED"}'
  exit 70
}

[[ "$#" -eq 1 && ( "$1" == "prepare" || "$1" == "remove" ) ]] || fail
[[ -f "$ENV_PATH" && ! -L "$ENV_PATH" ]] || fail
[[ -f "$RUNTIME_ENV_PATH" && ! -L "$RUNTIME_ENV_PATH" ]] || fail
[[ -f "$HOST_ENV_PATH" && ! -L "$HOST_ENV_PATH" ]] || fail
parameter_name="$(sed -n 's/^RCON_PARAMETER_NAME=//p' "$ENV_PATH")"
[[ "$parameter_name" =~ ^/wishicraft/(dev|prod)/secret/rcon-password$ ]] || fail
runtime_uid="$(sed -n 's/^UID=//p' "$RUNTIME_ENV_PATH")"
runtime_gid="$(sed -n 's/^GID=//p' "$RUNTIME_ENV_PATH")"
[[ "$runtime_uid" =~ ^[1-9][0-9]*$ && "$runtime_gid" =~ ^[1-9][0-9]*$ ]] || fail
game_directory="$(sed -n 's/^GAME_DIRECTORY=//p' "$HOST_ENV_PATH")"
[[ "$game_directory" =~ ^/srv/minecraft/games/[a-z0-9-]+/server$ ]] || fail

remove_data_placeholders() {
  local name path
  for name in .rcon-cli.env .rcon-cli.yaml; do
    path="$game_directory/$name"
    if [[ -e "$path" || -L "$path" ]]; then
      [[ -f "$path" && ! -L "$path" && ! -s "$path" ]] || fail
      rm -f -- "$path"
    fi
  done
}

if [[ "$1" == "remove" ]]; then
  rm -f -- "$SECRET_PATH" "$CLI_ENV_PATH" "$CLI_YAML_PATH"
  remove_data_placeholders
  exit 0
fi

remove_data_placeholders
install -d -o root -g root -m 0700 "$RUNTIME_DIR"
install -o "$runtime_uid" -g "$runtime_gid" -m 0600 /dev/null "$CLI_ENV_PATH"
install -o "$runtime_uid" -g "$runtime_gid" -m 0600 /dev/null "$CLI_YAML_PATH"
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
[[ "$(stat -c '%u:%g:%a' "$CLI_ENV_PATH")" == "$runtime_uid:$runtime_gid:600" ]] || fail
[[ "$(stat -c '%u:%g:%a' "$CLI_YAML_PATH")" == "$runtime_uid:$runtime_gid:600" ]] || fail
printf '%s\n' '{"schema_version":1,"operation":"RCON_SECRET_PREPARE","status":"succeeded"}'
