#!/usr/bin/env bash
set -euo pipefail

readonly IMAGE='ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77'
readonly EXPECTED_DIGEST='sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77'

fail() {
  printf '%s\n' "Phase 2b-1 integration failure: $*" >&2
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
    printf '::error::Phase 2b-1 integration failure: %s\n' "$*" >&2
  fi
  exit 1
}
fail_with_container_log() {
  tail -n 80 "$failure_log" >&2
  fail "$1"
}
require_meta() {
  local path=$1 expected=$2
  local actual
  actual=$(stat -c '%u:%g:%a:%F' "$path")
  [[ "$actual" == "$expected" ]] || fail "$path metadata is $actual, expected $expected"
}

command -v docker >/dev/null || fail 'Docker is required'
command -v getfacl >/dev/null || fail 'getfacl is required on the CI runner'
docker buildx version >/dev/null || fail 'Docker Buildx is required for manifest verification'

test_root=$(mktemp -d "${RUNNER_TEMP:-/tmp}/wishicraft-itzg.XXXXXX")
data_dir="$test_root/data"
failure_log="$test_root/incompatible.log"
container_prefix="wishicraft-itzg-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}"

cleanup() {
  docker rm -f "${container_prefix}-incompatible" "${container_prefix}-migrated" \
    "${container_prefix}-restart" >/dev/null 2>&1 || true
  sudo rm -rf -- "$test_root"
}
trap cleanup EXIT

remote_inspect=$(docker buildx imagetools inspect "$IMAGE") || \
  fail 'fixed image manifest inspection failed'
awk -v digest="$EXPECTED_DIGEST" '$1 == "Digest:" && $2 == digest {found=1} END {exit !found}' \
  <<<"$remote_inspect" || \
  fail 'remote manifest did not report the fixed top-level digest'

pull_output=$(docker pull --platform linux/amd64 "$IMAGE" 2>&1) || {
  printf '%s\n' "$pull_output" >&2
  fail 'fixed image pull failed'
}
printf '%s\n' "$pull_output"
inspect_arch=$(docker image inspect --format '{{.Architecture}}' "$IMAGE")
[[ "$inspect_arch" == amd64 ]] || fail "image architecture is $inspect_arch, expected amd64"

mkdir -p "$data_dir/preexisting/nested"
printf '%s\n' 'difficulty=easy' 'enable-rcon=true' > "$data_dir/server.properties"
printf '%s\n' 'eula=true' > "$data_dir/eula.txt"
printf '%s\n' 'ordinary fixture' > "$data_dir/preexisting/ordinary.txt"
printf '%s\n' 'ownership sentinel' > "$data_dir/preexisting/nested/sentinel.txt"
sudo chown 993:993 "$data_dir" "$data_dir/eula.txt" \
  "$data_dir/preexisting" "$data_dir/preexisting/ordinary.txt"
sudo chown 4242:4343 "$data_dir/preexisting/nested" \
  "$data_dir/preexisting/nested/sentinel.txt"
sudo chown 0:993 "$data_dir/server.properties"
chmod 0750 "$data_dir"
chmod 0644 "$data_dir/eula.txt"
chmod 0755 "$data_dir/preexisting"
chmod 0644 "$data_dir/preexisting/ordinary.txt"
chmod 0710 "$data_dir/preexisting/nested"
chmod 0600 "$data_dir/preexisting/nested/sentinel.txt"
chmod 0640 "$data_dir/server.properties"

preexisting_before=$(find "$data_dir/preexisting" -xdev -printf '%P|%U:%G|%m|%y\n' | sort)
server_inode_before=$(stat -c %i "$data_dir/server.properties")

common_args=(
  --platform linux/amd64
  --mount "type=bind,src=$data_dir,dst=/data"
  --env EULA=TRUE
  --env UID=993
  --env GID=993
  --env SKIP_CHOWN_DATA=true
  --env VERSION=26.2
  --env TYPE=VANILLA
  --env ENABLE_RCON=false
  --env DIFFICULTY=hard
  --env INIT_MEMORY=1G
  --env MAX_MEMORY=2G
  --env SETUP_ONLY=true
)

set +e
docker run --name "${container_prefix}-incompatible" "${common_args[@]}" "$IMAGE" \
  >"$failure_log" 2>&1
incompatible_rc=$?
set -e
[[ "$incompatible_rc" -ne 0 ]] || fail 'root:993/0640 unexpectedly allowed property update'
grep -F 'Failed to update server.properties' "$failure_log" >/dev/null || \
  fail_with_container_log 'failure was not identified at server.properties update'
grep -E 'AccessDeniedException|Permission denied' "$failure_log" >/dev/null || \
  fail_with_container_log 'failure did not contain a permission error'
require_meta "$data_dir/server.properties" '0:993:640:regular file'

# The real migration changes exactly one inode's ownership and preserves its mode/content.
server_hash_before=$(sha256sum "$data_dir/server.properties" | awk '{print $1}')
sudo chown 993:993 "$data_dir/server.properties"
require_meta "$data_dir/server.properties" '993:993:640:regular file'
[[ "$(sha256sum "$data_dir/server.properties" | awk '{print $1}')" == "$server_hash_before" ]] || \
  fail 'ownership migration changed server.properties content'

docker run --name "${container_prefix}-migrated" "${common_args[@]}" "$IMAGE"
require_meta "$data_dir/server.properties" '993:993:640:regular file'
[[ ! -L "$data_dir/server.properties" ]] || fail 'server.properties became a symlink'
[[ "$(stat -c %i "$data_dir/server.properties")" == "$server_inode_before" ]] || \
  fail 'server.properties inode was replaced'
[[ "$(getfacl -cp "$data_dir/server.properties" | awk '/^$/ {next} /^(user::|group::|other::)/ {next} {n++} END{print n+0}')" == 0 ]] || \
  fail 'server.properties gained an extended ACL'
grep -Fx 'difficulty=hard' "$data_dir/server.properties" >/dev/null || \
  fail 'server.properties was not realized'
grep -Fx 'enable-rcon=false' "$data_dir/server.properties" >/dev/null || \
  fail 'RCON was not disabled'
[[ ! -e "$data_dir/.rcon-cli.env" && ! -e "$data_dir/.rcon-cli.yaml" ]] || \
  fail 'RCON secret artifacts exist while RCON is disabled'

preexisting_after=$(find "$data_dir/preexisting" -xdev -printf '%P|%U:%G|%m|%y\n' | sort)
[[ "$preexisting_after" == "$preexisting_before" ]] || \
  fail 'SKIP_CHOWN_DATA did not preserve pre-existing fixture metadata'
require_meta "$data_dir/preexisting/nested/sentinel.txt" '4242:4343:600:regular file'

realized_hash=$(sha256sum "$data_dir/server.properties" | awk '{print $1}')
realized_meta=$(stat -c '%u:%g:%a:%F:%i' "$data_dir/server.properties")
docker run --name "${container_prefix}-restart" "${common_args[@]}" "$IMAGE"
[[ "$(sha256sum "$data_dir/server.properties" | awk '{print $1}')" == "$realized_hash" ]] || \
  fail 'identical restart changed realized server.properties'
[[ "$(stat -c '%u:%g:%a:%F:%i' "$data_dir/server.properties")" == "$realized_meta" ]] || \
  fail 'identical restart changed server.properties metadata or inode'
[[ "$(find "$data_dir/preexisting" -xdev -printf '%P|%U:%G|%m|%y\n' | sort)" == "$preexisting_before" ]] || \
  fail 'identical restart changed pre-existing fixture metadata'
[[ ! -e "$data_dir/.rcon-cli.env" && ! -e "$data_dir/.rcon-cli.yaml" ]] || \
  fail 'identical restart created RCON secret artifacts'

printf '%s\n' \
  'PASS:image-digest-and-architecture' \
  'PASS:root-owned-properties-fails-with-permission-error' \
  'PASS:migrated-properties-realized-with-stable-metadata' \
  'PASS:skip-chown-data-preserves-sentinels' \
  'PASS:restart-is-idempotent' \
  'PASS:rcon-disabled-leaves-no-secret-artifacts'
