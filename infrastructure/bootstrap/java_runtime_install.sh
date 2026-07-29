#!/usr/bin/env bash
set -euo pipefail

: "${JAVA_RUNTIME:?JAVA_RUNTIME is required}"

fail() {
  printf '%s\n' "wishicraft Java runtime: $*" >&2
  exit 1
}

case "$JAVA_RUNTIME" in
  corretto-25-headless)
    readonly JAVA_PACKAGE="java-25-amazon-corretto-headless"
    ;;
  *)
    fail "unsupported Java runtime: $JAVA_RUNTIME"
    ;;
esac

dnf install -y "$JAVA_PACKAGE"
rpm -q "$JAVA_PACKAGE" >/dev/null

java_version="$(java -version 2>&1)" || fail "java command failed"
grep -Eq 'version "25([. ]|$)' <<<"$java_version" || fail "Java major version is not 25"
grep -qi 'Corretto' <<<"$java_version" || fail "Java runtime is not Corretto"
