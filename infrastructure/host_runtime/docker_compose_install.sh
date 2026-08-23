#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${AL2023_RELEASE:?AL2023_RELEASE is required}"
: "${EXPECTED_DOCKER_NEVRA:?EXPECTED_DOCKER_NEVRA is required}"
: "${COMPOSE_VERSION:?COMPOSE_VERSION is required}"
: "${COMPOSE_URL:?COMPOSE_URL is required}"
: "${COMPOSE_SHA256:?COMPOSE_SHA256 is required}"

readonly PLUGIN_PATH="${COMPOSE_PLUGIN_PATH:-/usr/local/lib/docker/cli-plugins/docker-compose}"
readonly RECORD_PATH="${HOST_RUNTIME_PACKAGE_RECORD:-/var/lib/wishicraft/host-runtime/packages.json}"

fail() { printf '%s\n' "wishicraft Host Runtime installer: $*" >&2; exit 1; }
sha256_of() { sha256sum "$1" | awk '{print $1}'; }

[[ "$(id -u)" == 0 ]] || fail "must run as root"
[[ "$AL2023_RELEASE" =~ ^2023\.[0-9]+\.[0-9]{8}$ ]] || fail "invalid AL2023 release"
[[ "$COMPOSE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "invalid Compose version"
[[ "$COMPOSE_URL" == "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-x86_64" ]] || fail "unexpected Compose URL"
[[ "$COMPOSE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "invalid Compose SHA-256"
[[ "$EXPECTED_DOCKER_NEVRA" =~ ^docker-[0-9].*\.x86_64$ ]] || fail "invalid Docker NEVRA"

installed_release="$(rpm -q system-release --qf '%{VERSION}')"
[[ "$installed_release" == "$AL2023_RELEASE" ]] || fail "AL2023 release mismatch"

available_docker_nevra="$(
  dnf --releasever="$AL2023_RELEASE" repoquery --arch=x86_64 \
    --qf '%{name}-%{version}-%{release}.%{arch}' docker | sort -V | tail -n 1
)"
[[ "$available_docker_nevra" == "$EXPECTED_DOCKER_NEVRA" ]] || \
  fail "Docker repository NEVRA mismatch: $available_docker_nevra"

dnf --releasever="$AL2023_RELEASE" install -y docker
docker_nevra="$(rpm -q docker --qf '%{NEVRA}')" || fail "Docker package is not installed"
[[ "$docker_nevra" == "$EXPECTED_DOCKER_NEVRA" ]] || fail "installed Docker NEVRA mismatch"

if [[ -e "$PLUGIN_PATH" ]]; then
  [[ -f "$PLUGIN_PATH" && ! -L "$PLUGIN_PATH" ]] || fail "Compose plugin path is not a regular file"
  [[ "$(sha256_of "$PLUGIN_PATH")" == "$COMPOSE_SHA256" ]] || fail "existing Compose plugin differs"
else
  install -d -m 0755 "$(dirname "$PLUGIN_PATH")"
  temporary="$(mktemp "$(dirname "$PLUGIN_PATH")/.docker-compose.XXXXXX")"
  trap 'rm -f "$temporary"' EXIT
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 20 --max-time 300 --retry 2 --output "$temporary" "$COMPOSE_URL"
  [[ "$(sha256_of "$temporary")" == "$COMPOSE_SHA256" ]] || fail "downloaded Compose checksum mismatch"
  chmod 0755 "$temporary"
  chown root:root "$temporary"
  mv "$temporary" "$PLUGIN_PATH"
  trap - EXIT
fi

compose_actual="$(docker compose version --short)" || fail "Compose plugin verification failed"
[[ "${compose_actual#v}" == "$COMPOSE_VERSION" ]] || fail "Compose version mismatch"

install -d -o root -g root -m 0755 "$(dirname "$RECORD_PATH")"
temporary_record="$(mktemp "$(dirname "$RECORD_PATH")/.packages.XXXXXX")"
printf '{"schema_version":1,"al2023_release":"%s","docker_nevra":"%s","compose_version":"%s","compose_sha256":"%s"}\n' \
  "$AL2023_RELEASE" "$docker_nevra" "$COMPOSE_VERSION" "$COMPOSE_SHA256" >"$temporary_record"
chmod 0644 "$temporary_record"
chown root:root "$temporary_record"
mv "$temporary_record" "$RECORD_PATH"
