#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${EXPECTED_AMI_ID:?EXPECTED_AMI_ID is required}"
: "${EXPECTED_RELEASE:?EXPECTED_RELEASE is required}"
: "${EXPECTED_KERNEL_PREFIX:?EXPECTED_KERNEL_PREFIX is required}"
: "${EXPECTED_DOCKER_NEVRA:?EXPECTED_DOCKER_NEVRA is required}"
: "${COMPOSE_VERSION:?COMPOSE_VERSION is required}"
: "${COMPOSE_URL:?COMPOSE_URL is required}"
: "${COMPOSE_SHA256:?COMPOSE_SHA256 is required}"
: "${IMAGE:?IMAGE is required}"
: "${EXPECTED_IMAGE_DIGEST:?EXPECTED_IMAGE_DIGEST is required}"
: "${INSTALLER:?INSTALLER is required}"
: "${HOST_RUNTIME_UNIT:?HOST_RUNTIME_UNIT is required}"

readonly VALIDATION_PREFIX=/var/tmp/wishicraft-phase2-validation-
readonly CONTAINER_NAME=wishicraft-phase2-synthetic
validation_root="${VALIDATION_PREFIX}$(date -u +%Y%m%dT%H%M%SZ)-$$"
data_dir="$validation_root/data"
compose_file="$validation_root/compose.yaml"

fail() { printf 'FAIL:%s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS:%s\n' "$*"; }
meta() { stat -c '%u:%g:%a:%F' "$1"; }

[[ "$(id -u)" == 0 ]] || fail must-run-as-root
[[ "$validation_root" == "$VALIDATION_PREFIX"* ]] || fail unsafe-validation-root
ami_id="$(curl -fsS --connect-timeout 5 -X PUT \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
  http://169.254.169.254/latest/api/token)"
instance_ami="$(curl -fsS --connect-timeout 5 \
  -H "X-aws-ec2-metadata-token: $ami_id" \
  http://169.254.169.254/latest/meta-data/ami-id)"
[[ "$instance_ami" == "$EXPECTED_AMI_ID" ]] || fail ami-id-mismatch
[[ "$(rpm -q system-release --qf '%{VERSION}')" == "$EXPECTED_RELEASE" ]] || \
  fail al2023-release-mismatch
[[ "$(uname -r)" == "$EXPECTED_KERNEL_PREFIX"* ]] || fail kernel-mismatch
[[ "$(uname -m)" == x86_64 ]] || fail architecture-mismatch
pass platform

if getent passwd 993 >/dev/null; then fail uid-993-already-used; fi
if getent group 993 >/dev/null; then fail gid-993-already-used; fi
if getent passwd minecraft >/dev/null; then fail minecraft-user-already-exists; fi
if getent group minecraft >/dev/null; then fail minecraft-group-already-exists; fi
pass uid-gid-993-unused

groupadd --gid 993 minecraft
useradd --uid 993 --gid 993 --no-create-home --home-dir /nonexistent \
  --shell /sbin/nologin minecraft
[[ "$(id -u minecraft)" == 993 && "$(id -g minecraft)" == 993 ]] || fail identity-mismatch
[[ "$(getent passwd minecraft | cut -d: -f6-7)" == '/nonexistent:/sbin/nologin' ]] || \
  fail identity-runtime-settings
pass identity-created-993-993

AL2023_RELEASE="$EXPECTED_RELEASE" EXPECTED_DOCKER_NEVRA="$EXPECTED_DOCKER_NEVRA" \
  COMPOSE_VERSION="$COMPOSE_VERSION" COMPOSE_URL="$COMPOSE_URL" \
  COMPOSE_SHA256="$COMPOSE_SHA256" "$INSTALLER"
systemctl enable --now docker
[[ "$(rpm -q docker --qf '%{NEVRA}')" == "$EXPECTED_DOCKER_NEVRA" ]] || \
  fail docker-nevra-mismatch
docker version --format 'OBS:DockerClient={{.Client.Version}} DockerServer={{.Server.Version}}'
docker info --format 'OBS:Driver={{.Driver}} CgroupVersion={{.CgroupVersion}} Architecture={{.Architecture}}'
[[ "$(systemctl is-active docker)" == active ]] || fail docker-inactive
[[ "$(docker compose version --short)" == "$COMPOSE_VERSION" ]] || fail compose-version
[[ "$(sha256sum /usr/local/lib/docker/cli-plugins/docker-compose | awk '{print $1}')" == \
  "$COMPOSE_SHA256" ]] || fail compose-checksum
pass docker-compose

pull_output="$(docker pull --platform linux/amd64 "$IMAGE" 2>&1)" || {
  printf '%s\n' "$pull_output" >&2
  fail image-pull
}
image_arch="$(docker image inspect --format '{{.Architecture}}' "$IMAGE")"
[[ "$image_arch" == amd64 ]] || fail image-architecture
repo_digests="$(docker image inspect --format '{{join .RepoDigests " "}}' "$IMAGE")"
[[ "$repo_digests" == *"@$EXPECTED_IMAGE_DIGEST"* ]] || fail image-repodigest
java_version="$(docker run --rm --entrypoint java "$IMAGE" -version 2>&1 | head -n 1)"
[[ "$java_version" == *'25.'* ]] || fail image-java-version
printf 'OBS:RepoDigests=%s\nOBS:Java=%s\n' "$repo_digests" "$java_version"
pass image-digest-architecture-java25

install -d -o 993 -g 993 -m 0750 "$data_dir" "$data_dir/preexisting"
printf '%s\n' 'difficulty=easy' 'enable-rcon=true' >"$data_dir/server.properties"
printf '%s\n' 'eula=true' >"$data_dir/eula.txt"
printf '%s\n' sentinel >"$data_dir/preexisting/sentinel.txt"
chown 993:993 "$data_dir/server.properties" "$data_dir/eula.txt"
chown 4242:4343 "$data_dir/preexisting" "$data_dir/preexisting/sentinel.txt"
chmod 0640 "$data_dir/server.properties"
chmod 0600 "$data_dir/preexisting/sentinel.txt"
sentinel_before="$(stat -c '%u:%g:%a:%i' "$data_dir/preexisting/sentinel.txt")"
properties_inode="$(stat -c %i "$data_dir/server.properties")"

common_args=(
  --platform linux/amd64 --mount "type=bind,src=$data_dir,dst=/data"
  --env EULA=TRUE --env UID=993 --env GID=993 --env SKIP_CHOWN_DATA=true
  --env VERSION=26.2 --env TYPE=VANILLA --env ENABLE_RCON=false
  --env DIFFICULTY=hard --env INIT_MEMORY=1G --env MAX_MEMORY=2G
)
docker run --rm "${common_args[@]}" --env SETUP_ONLY=true "$IMAGE"
[[ "$(meta "$data_dir/server.properties")" == '993:993:640:regular file' ]] || \
  fail properties-metadata
[[ "$(stat -c %i "$data_dir/server.properties")" == "$properties_inode" ]] || \
  fail properties-inode-changed
grep -Fx difficulty=hard "$data_dir/server.properties" >/dev/null || fail properties-not-realized
grep -Fx enable-rcon=false "$data_dir/server.properties" >/dev/null || fail rcon-not-disabled
[[ "$(stat -c '%u:%g:%a:%i' "$data_dir/preexisting/sentinel.txt")" == "$sentinel_before" ]] || \
  fail sentinel-changed
[[ ! -e "$data_dir/.rcon-cli.env" && ! -e "$data_dir/.rcon-cli.yaml" ]] || \
  fail rcon-secret-artifact
pass synthetic-setup

cat >"$compose_file" <<EOF
services:
  minecraft:
    container_name: $CONTAINER_NAME
    image: $IMAGE
    pull_policy: never
    restart: "no"
    mem_limit: 2816MiB
    stop_grace_period: 150s
    environment:
      EULA: "TRUE"
      UID: "993"
      GID: "993"
      SKIP_CHOWN_DATA: "true"
      VERSION: "26.2"
      TYPE: "VANILLA"
      ENABLE_RCON: "false"
      INIT_MEMORY: "1G"
      MAX_MEMORY: "2G"
    volumes:
      - type: bind
        source: $data_dir
        target: /data
EOF
docker compose -p wishicraft-phase2-validation -f "$compose_file" up -d
for _ in $(seq 1 120); do
  state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  logs="$(docker logs --tail 80 "$CONTAINER_NAME" 2>&1 || true)"
  if [[ "$state" == *healthy* && "$logs" == *'Done ('* ]]; then break; fi
  if [[ "$state" == exited* || "$state" == dead* ]]; then
    printf '%s\n' "$logs" >&2
    fail minecraft-exited-before-ready
  fi
  sleep 5
done
state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CONTAINER_NAME")"
logs="$(docker logs --tail 120 "$CONTAINER_NAME" 2>&1)"
[[ "$state" == *healthy* && "$logs" == *'Done ('* ]] || fail minecraft-not-ready
[[ "$logs" == *'26.2'* ]] || fail minecraft-version-not-observed
inspect_state="$(docker inspect --format \
  'OBS:Running={{.State.Running}} OOMKilled={{.State.OOMKilled}} RestartCount={{.RestartCount}} RestartPolicy={{.HostConfig.RestartPolicy.Name}} Memory={{.HostConfig.Memory}}' \
  "$CONTAINER_NAME")"
printf '%s\n' "$inspect_state"
[[ "$inspect_state" == *'Running=true OOMKilled=false RestartCount=0 RestartPolicy=no Memory=2952790016'* ]] || \
  fail container-runtime-contract
docker stats --no-stream --format 'OBS:ContainerMemory={{.MemUsage}} ContainerMemPercent={{.MemPerc}}' \
  "$CONTAINER_NAME"
free -b | awk 'NR==2 {printf "OBS:HostMemTotal=%s HostMemUsed=%s HostMemAvailable=%s\n",$2,$3,$7}'
pid="$(docker inspect --format '{{.State.Pid}}' "$CONTAINER_NAME")"
cgroup_path="$(awk -F: '$1 == "0" {print $3}' "/proc/$pid/cgroup")"
if [[ -r "/sys/fs/cgroup${cgroup_path}/memory.current" ]]; then
  printf 'OBS:CgroupMemoryCurrent=%s CgroupMemoryPeak=%s\n' \
    "$(<"/sys/fs/cgroup${cgroup_path}/memory.current")" \
    "$(<"/sys/fs/cgroup${cgroup_path}/memory.peak")"
fi
pass synthetic-minecraft-ready

grep -Fx 'Restart=no' "$HOST_RUNTIME_UNIT" >/dev/null || fail systemd-restart-policy
! grep -Eq '^WantedBy=|^RequiredBy=' "$HOST_RUNTIME_UNIT" || fail systemd-enable-hook
systemd-analyze verify "$HOST_RUNTIME_UNIT"
pass lifecycle-static-contract

stop_start="$(date +%s)"
docker compose -p wishicraft-phase2-validation -f "$compose_file" stop --timeout 150
stop_elapsed="$(( $(date +%s) - stop_start ))"
stop_state="$(docker inspect --format \
  'OBS:StopStatus={{.State.Status}} ExitCode={{.State.ExitCode}} OOMKilled={{.State.OOMKilled}} FinishedAt={{.State.FinishedAt}}' \
  "$CONTAINER_NAME")"
printf '%s\nOBS:StopElapsedSeconds=%s\n' "$stop_state" "$stop_elapsed"
[[ "$stop_state" == *'StopStatus=exited ExitCode=0 OOMKilled=false'* ]] || fail graceful-stop
! ss -H -ltnp | grep -E ':(25565|25575|25585)[[:space:]]' || fail listener-remains
systemctl restart docker
[[ "$(docker inspect --format '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}' "$CONTAINER_NAME")" == \
  'exited no' ]] || fail daemon-restart-revived-container
pass lifecycle-daemon-restart-no-autostart

docker compose -p wishicraft-phase2-validation -f "$compose_file" rm -f
[[ ! -e "$data_dir/.rcon-cli.env" && ! -e "$data_dir/.rcon-cli.yaml" ]] || \
  fail cleanup-secret-artifact
rm -rf -- "$validation_root"
pass synthetic-cleanup
pass target-host-validation-complete
