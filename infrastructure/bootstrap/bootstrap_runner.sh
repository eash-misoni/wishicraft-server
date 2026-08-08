#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${BUNDLE_SHA256:?}"
: "${BUNDLE_BASE64:?}"
 : "${BUNDLE_MEMBERS:?}"
readonly destination="${BUNDLE_DEST:-/usr/local/lib/wishicraft}"
readonly temp_root="${BUNDLE_TEMP_ROOT:-/root}"
if [[ "${RUNNER_TEST_MODE:-0}" != 1 ]]; then
  [[ "$(id -u)" == 0 ]] || { echo "bootstrap runner must run as root" >&2; exit 1; }
fi
readonly tmp_dir="$(mktemp -d "$temp_root/wishicraft-bootstrap.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
printf '%s' "$BUNDLE_BASE64" | base64 -d > "$tmp_dir/bundle.tar.gz"
printf '%s  %s\n' "$BUNDLE_SHA256" "$tmp_dir/bundle.tar.gz" | sha256sum -c -
printf '%s' "$BUNDLE_MEMBERS" > "$tmp_dir/allowed-members"
python3 - "$tmp_dir/bundle.tar.gz" "$tmp_dir/allowed-members" "$destination" "${RUNNER_TEST_MODE:-0}" <<'PY'
import os
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive_path = Path(sys.argv[1])
allowed = tuple(Path(sys.argv[2]).read_text(encoding="utf-8").splitlines())
destination = Path(sys.argv[3])
test_mode = sys.argv[4] == "1"

if not allowed or len(allowed) != len(set(allowed)):
    raise SystemExit("invalid bootstrap allowlist")
if destination.is_symlink() or not destination.is_dir():
    raise SystemExit("invalid bootstrap destination")

try:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names: list[str] = []
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit("unsafe archive member path")
            if not member.isreg():
                raise SystemExit("bootstrap member is not a regular file")
            names.append(member.name)
        if len(names) != len(set(names)):
            raise SystemExit("duplicate bootstrap archive member")
        if set(names) != set(allowed) or len(names) != len(allowed):
            raise SystemExit("bootstrap archive members do not match allowlist")

        staging = archive_path.parent / "extracted"
        staging.mkdir(mode=0o700)
        for member in members:
            target = staging / member.name
            if target.parent != staging:
                raise SystemExit("nested bootstrap member path")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit("could not read bootstrap member")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755)
            if not test_mode:
                os.chown(target, 0, 0)
            details = target.lstat()
            if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise SystemExit("invalid extracted bootstrap member")
            if stat.S_IMODE(details.st_mode) != 0o755:
                raise SystemExit("invalid extracted bootstrap member mode")

        for name in allowed:
            source = staging / name
            target = destination / name
            if target.is_symlink():
                raise SystemExit("bootstrap destination member is a symlink")
            shutil.copyfile(source, target)
            target.chmod(0o755)
            if not test_mode:
                os.chown(target, 0, 0)
except (OSError, tarfile.TarError) as error:
    raise SystemExit("invalid bootstrap archive") from error
PY
