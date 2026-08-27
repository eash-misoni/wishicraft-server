"""Strict parsing and normalization for Host Runtime probe schema v1."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

INSTANCE_ID_PATTERN = re.compile(r"^i-[0-9a-f]{17}$")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
EXPECTED_MINECRAFT_VERSION = "26.2"


class ProbeContractError(ValueError):
    """The transport succeeded but the probe document is not trustworthy."""


class MountState(StrEnum):
    EXPECTED = "expected"
    NOT_MOUNTED = "not-mounted"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class DockerState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    NOT_FOUND = "not-found"
    UNKNOWN = "unknown"


class UnitState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    ACTIVATING = "activating"
    DEACTIVATING = "deactivating"
    NOT_FOUND = "not-found"
    UNKNOWN = "unknown"


class ContainerState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not-found"
    UNKNOWN = "unknown"


class ProtocolState(StrEnum):
    READY = "ready"
    NOT_READY = "not-ready"
    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


class ProtocolResult(StrEnum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MountObservation:
    state: MountState
    mount_path: str
    filesystem_type: str | None
    filesystem_uuid: str | None
    expected_filesystem_type: str
    expected_filesystem_uuid: str
    root_uid: int | None
    root_gid: int | None
    root_mode: str | None


@dataclass(frozen=True)
class ContainerObservation:
    state: ContainerState
    container_id: str | None
    name: str | None
    image_reference: str | None
    image_digest: str | None
    restart_policy: str | None
    health: str
    oom_killed: bool | None
    restart_count: int | None
    published_ports: dict[str, object]


@dataclass(frozen=True)
class ProtocolObservation:
    attempted: bool
    result: ProtocolResult
    compatible_response: bool
    host: str
    port: int
    reported_version: str | None
    protocol_version: int | None
    version_match: bool | None
    observed_at: datetime | None


@dataclass(frozen=True)
class HostRuntimeProbe:
    observed_at: datetime
    instance_id: str
    runtime_id: str
    compose_project: str
    compose_service: str
    mount: MountObservation
    docker_state: DockerState
    host_runtime_unit: str
    host_runtime_state: UnitState
    container: ContainerObservation
    minecraft_runtime_state: str
    protocol_state: ProtocolState
    protocol: ProtocolObservation
    ready: bool
    errors: tuple[str, ...]


def parse_host_runtime_probe(stdout: str, *, expected_instance_id: str) -> HostRuntimeProbe:
    """Parse exactly schema v1 and reject unsafe or impossible combinations."""
    if INSTANCE_ID_PATTERN.fullmatch(expected_instance_id) is None:
        raise ProbeContractError("invalid expected instance ID")
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ProbeContractError("invalid probe JSON") from exc
    document = _mapping(raw, "document")
    if _integer(document, "schema_version") != 1:
        raise ProbeContractError("unsupported probe schema version")
    if _string(document, "probe_version") != "1.1.0":
        raise ProbeContractError("unsupported probe version")
    observed_at = _timestamp(document, "observed_at")

    identity = _mapping(document.get("identity"), "identity")
    instance_id = _string(identity, "instance_id")
    if instance_id != expected_instance_id:
        raise ProbeContractError("probe instance identity mismatch")
    runtime_id = _string(identity, "runtime_id")
    compose_project = _string(identity, "compose_project")
    compose_service = _string(identity, "compose_service")
    if (runtime_id, compose_project, compose_service) != (
        "wishicraft-host-runtime",
        "wishicraft-host-runtime",
        "minecraft",
    ):
        raise ProbeContractError("probe runtime identity mismatch")

    mount = _parse_mount(_mapping(document.get("mount"), "mount"))
    docker = _mapping(document.get("docker"), "docker")
    docker_state = _enum(DockerState, docker, "state")
    host_runtime = _mapping(document.get("host_runtime"), "host_runtime")
    host_runtime_unit = _string(host_runtime, "unit")
    if host_runtime_unit != "wishicraft-host-runtime.service":
        raise ProbeContractError("unexpected Host Runtime unit")
    host_runtime_state = _enum(UnitState, host_runtime, "state")
    container = _parse_container(_mapping(document.get("container"), "container"))
    minecraft = _mapping(document.get("minecraft"), "minecraft")
    minecraft_runtime_state = _string(minecraft, "runtime_state")
    protocol_state = _enum(ProtocolState, minecraft, "protocol_state")
    protocol = _parse_protocol(_mapping(minecraft.get("protocol"), "minecraft.protocol"))
    ready = _boolean(minecraft, "ready")
    errors = _errors(document.get("errors"))

    if docker_state is not DockerState.ACTIVE and container.state is not ContainerState.UNKNOWN:
        raise ProbeContractError("container state requires an active Docker daemon")
    if container.state in {ContainerState.STOPPED, ContainerState.NOT_FOUND}:
        if (
            minecraft_runtime_state != "not-running"
            or protocol_state is not ProtocolState.NOT_APPLICABLE
            or protocol.attempted
            or protocol.result is not ProtocolResult.NOT_APPLICABLE
            or ready
        ):
            raise ProbeContractError("stopped container has impossible Minecraft state")
    elif container.state is ContainerState.RUNNING:
        if minecraft_runtime_state != "running" or not protocol.attempted:
            raise ProbeContractError("running container requires protocol observation")
        if protocol.result is ProtocolResult.SUCCESS:
            expected_state = (
                ProtocolState.READY if protocol.version_match else ProtocolState.NOT_READY
            )
            if protocol_state is not expected_state or ready is not protocol.version_match:
                raise ProbeContractError("protocol success has inconsistent READY state")
        elif protocol.result is ProtocolResult.FAILED:
            if protocol_state is not ProtocolState.NOT_READY or ready:
                raise ProbeContractError("protocol failure has inconsistent state")
        elif protocol_state is not ProtocolState.UNKNOWN or ready:
            raise ProbeContractError("unavailable protocol must remain unknown")
    elif (
        minecraft_runtime_state != "unknown"
        or protocol_state is not ProtocolState.UNKNOWN
        or protocol.attempted
        or protocol.result is not ProtocolResult.UNKNOWN
        or ready
    ):
        raise ProbeContractError("unprobed Minecraft state must remain unknown")
    if ready and (
        mount.state is not MountState.EXPECTED
        or docker_state is not DockerState.ACTIVE
        or host_runtime_state is not UnitState.ACTIVE
        or container.state is not ContainerState.RUNNING
        or protocol_state is not ProtocolState.READY
        or errors
    ):
        raise ProbeContractError("READY requires every observed runtime layer")
    if errors and not _has_unknown_observation(
        mount, docker_state, host_runtime_state, container.state
    ):
        raise ProbeContractError("probe errors require an unknown observation")

    return HostRuntimeProbe(
        observed_at=observed_at,
        instance_id=instance_id,
        runtime_id=runtime_id,
        compose_project=compose_project,
        compose_service=compose_service,
        mount=mount,
        docker_state=docker_state,
        host_runtime_unit=host_runtime_unit,
        host_runtime_state=host_runtime_state,
        container=container,
        minecraft_runtime_state=minecraft_runtime_state,
        protocol_state=protocol_state,
        protocol=protocol,
        ready=ready,
        errors=errors,
    )


def _parse_mount(value: dict[str, object]) -> MountObservation:
    state = _enum(MountState, value, "state")
    mount_path = _string(value, "mount_path")
    expected_type = _string(value, "expected_filesystem_type")
    expected_uuid = _string(value, "expected_filesystem_uuid")
    filesystem_type = _optional_string(value, "filesystem_type")
    filesystem_uuid = _optional_string(value, "filesystem_uuid")
    root_uid = _optional_integer(value, "root_uid")
    root_gid = _optional_integer(value, "root_gid")
    root_mode = _optional_string(value, "root_mode")
    if mount_path != "/srv/minecraft" or expected_type != "xfs":
        raise ProbeContractError("unexpected mount identity")
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", expected_uuid) is None:
        raise ProbeContractError("invalid expected filesystem UUID")
    if state is MountState.EXPECTED and (
        filesystem_type != expected_type
        or filesystem_uuid != expected_uuid
        or root_uid is None
        or root_gid is None
        or root_mode is None
    ):
        raise ProbeContractError("expected mount does not match its contract")
    if state is MountState.NOT_MOUNTED and any(
        item is not None
        for item in (filesystem_type, filesystem_uuid, root_uid, root_gid, root_mode)
    ):
        raise ProbeContractError("unmounted filesystem contains observed metadata")
    return MountObservation(
        state=state,
        mount_path=mount_path,
        filesystem_type=filesystem_type,
        filesystem_uuid=filesystem_uuid,
        expected_filesystem_type=expected_type,
        expected_filesystem_uuid=expected_uuid,
        root_uid=root_uid,
        root_gid=root_gid,
        root_mode=root_mode,
    )


def _parse_container(value: dict[str, object]) -> ContainerObservation:
    state = _enum(ContainerState, value, "state")
    container_id = _optional_string(value, "container_id")
    name = _optional_string(value, "name")
    image_reference = _optional_string(value, "image_reference")
    image_digest = _optional_string(value, "image_digest")
    restart_policy = _optional_string(value, "restart_policy")
    health = _string(value, "health")
    oom_killed = _optional_boolean(value, "oom_killed")
    restart_count = _optional_integer(value, "restart_count")
    published_ports = _mapping(value.get("published_ports"), "container.published_ports")
    if image_digest is not None and SHA256_PATTERN.fullmatch(image_digest) is None:
        raise ProbeContractError("invalid container image digest")
    if state is ContainerState.NOT_FOUND and any(
        item is not None
        for item in (
            container_id,
            name,
            image_reference,
            image_digest,
            restart_policy,
            oom_killed,
            restart_count,
        )
    ):
        raise ProbeContractError("missing container contains runtime metadata")
    if state in {ContainerState.RUNNING, ContainerState.STOPPED} and any(
        item is None
        for item in (
            container_id,
            name,
            image_reference,
            restart_policy,
            oom_killed,
            restart_count,
        )
    ):
        raise ProbeContractError("existing container lacks runtime metadata")
    return ContainerObservation(
        state=state,
        container_id=container_id,
        name=name,
        image_reference=image_reference,
        image_digest=image_digest,
        restart_policy=restart_policy,
        health=health,
        oom_killed=oom_killed,
        restart_count=restart_count,
        published_ports=published_ports,
    )


def _parse_protocol(value: dict[str, object]) -> ProtocolObservation:
    attempted = _boolean(value, "attempted")
    result = _enum(ProtocolResult, value, "result")
    compatible_response = _boolean(value, "compatible_response")
    host = _string(value, "host")
    port = _integer(value, "port")
    reported_version = _optional_string(value, "reported_version")
    protocol_version = _optional_integer(value, "protocol_version")
    version_match = _optional_boolean(value, "version_match")
    observed_at = _optional_timestamp(value, "observed_at")
    if host != "localhost" or port != 25565:
        raise ProbeContractError("protocol observation must remain container-local")
    if attempted is not (observed_at is not None):
        raise ProbeContractError("protocol attempt requires its own observed_at")
    response_fields = (reported_version, protocol_version, version_match)
    if result is ProtocolResult.SUCCESS:
        if not compatible_response or any(item is None for item in response_fields):
            raise ProbeContractError("protocol success lacks compatible response metadata")
        assert reported_version is not None
        if version_match is not _version_matches_expected(reported_version):
            raise ProbeContractError("protocol version comparison is inconsistent")
    elif compatible_response or any(item is not None for item in response_fields):
        raise ProbeContractError("unsuccessful protocol observation contains response metadata")
    if result is ProtocolResult.NOT_APPLICABLE and attempted:
        raise ProbeContractError("not-applicable protocol cannot be attempted")
    if (
        result in {ProtocolResult.SUCCESS, ProtocolResult.FAILED, ProtocolResult.UNAVAILABLE}
        and not attempted
    ):
        raise ProbeContractError("protocol result requires an attempt")
    return ProtocolObservation(
        attempted=attempted,
        result=result,
        compatible_response=compatible_response,
        host=host,
        port=port,
        reported_version=reported_version,
        protocol_version=protocol_version,
        version_match=version_match,
        observed_at=observed_at,
    )


def _version_matches_expected(reported_version: str) -> bool:
    pattern = rf"(?:^|[^0-9.]){re.escape(EXPECTED_MINECRAFT_VERSION)}(?:$|[^0-9.])"
    return re.search(pattern, reported_version) is not None


def _has_unknown_observation(
    mount: MountObservation,
    docker: DockerState,
    runtime: UnitState,
    container: ContainerState,
) -> bool:
    return (
        mount.state is MountState.UNKNOWN
        or docker is DockerState.UNKNOWN
        or runtime is UnitState.UNKNOWN
        or container is ContainerState.UNKNOWN
    )


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProbeContractError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _string(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise ProbeContractError(f"{key} must be a non-empty string")
    return value


def _optional_string(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProbeContractError(f"{key} must be null or a non-empty string")
    return value


def _integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProbeContractError(f"{key} must be an integer")
    return value


def _optional_integer(values: dict[str, object], key: str) -> int | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProbeContractError(f"{key} must be null or a non-negative integer")
    return value


def _boolean(values: dict[str, object], key: str) -> bool:
    value = values.get(key)
    if not isinstance(value, bool):
        raise ProbeContractError(f"{key} must be a boolean")
    return value


def _optional_boolean(values: dict[str, object], key: str) -> bool | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ProbeContractError(f"{key} must be null or a boolean")
    return value


def _timestamp(values: dict[str, object], key: str) -> datetime:
    value = _string(values, key)
    if not value.endswith("Z"):
        raise ProbeContractError("observed_at must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ProbeContractError("observed_at must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ProbeContractError("observed_at must be UTC")
    return parsed


def _optional_timestamp(values: dict[str, object], key: str) -> datetime | None:
    if values.get(key) is None:
        return None
    return _timestamp(values, key)


def _enum[T: StrEnum](enum_type: type[T], values: dict[str, object], key: str) -> T:
    value = _string(values, key)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ProbeContractError(f"unsupported {key}") from exc


def _errors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and ERROR_CODE_PATTERN.fullmatch(item) for item in value
    ):
        raise ProbeContractError("errors must contain stable error codes")
    if len(value) != len(set(value)):
        raise ProbeContractError("errors must be unique")
    return tuple(value)
