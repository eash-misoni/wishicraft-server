"""Proposed two-Game contract boundaries, not production completion evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from infrastructure.stacks.control_plane_stack import _start_definition, _stop_definition
from infrastructure.switch_workflow import definition
from wishicraft.artifacts.targeted_runtime import authorize
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.runtime_contract import RuntimeTargetRepository

GAMES = ("game-vanilla-main", "game-vanilla-secondary")
A = dict(
    instance_id="i-0123456789abcdef0",
    game_id=GAMES[0],
    data_source=f"/srv/minecraft/games/{GAMES[0]}/server",
    config_digest="a" * 64,
    run_id="op-first",
)
B = {
    **A,
    "game_id": GAMES[1],
    "data_source": f"/srv/minecraft/games/{GAMES[1]}/server",
    "run_id": "op-switch",
}


def test_graph_reuses_normal_tasks_without_ec2_or_intermediate_completion() -> None:
    graph = definition(
        start=_start_definition(
            reconcile_arn="reconcile", start_task_arn="start", lease_renew_seconds=120
        ),
        stop=_stop_definition(
            reconcile_arn="reconcile", stop_task_arn="stop", lease_renew_seconds=120
        ),
        stop_task_arn="stop",
    )
    tasks = [
        v["Parameters"]["Payload"].get("action")
        for v in graph["States"].values()
        if v.get("Type") == "Task"
    ]
    assert "start_ec2" not in tasks and "stop_ec2" not in tasks
    assert tasks.count("complete") == 1
    assert all(
        x in tasks
        for x in ("prepare_switch", "run_host_stop", "verify_switch_stopped", "run_host_start")
    )


def test_rendered_game_and_run_are_required_and_no_automatic_bind_creation() -> None:
    config = load_configuration(Path(__file__).resolve().parents[2], "dev")
    rendered = render_boot_time_artifacts(
        config.project,
        config.stage,
        observed_uid=993,
        observed_gid=993,
        enable_rcon=True,
        rcon_parameter_name="/wishicraft/dev/secret/rcon-password",
        targeted=True,
        games=GAMES,
    )
    assert "${GAME_DIRECTORY:?targeted Game required}" in rendered.compose_yaml
    assert "${WISHICRAFT_RUN_ID:?targeted START required}" in rendered.compose_yaml
    assert "create_host_path: false" in rendered.compose_yaml
    assert json.loads(rendered.manifest_json)["games"] == list(GAMES)
    assert RuntimeCatalog.parse(json.dumps(GAMES)).data_source(GAMES[0]) == A["data_source"]
    with pytest.raises(ValueError):
        RuntimeCatalog.parse(json.dumps(GAMES)).data_source("game-unknown")


@pytest.mark.parametrize("action,target", [("STOP", A), ("START", B)])
def test_one_switch_operation_authorizes_exact_source_or_destination(
    action: str, target: dict[str, str]
) -> None:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    op = dict(
        operation_id="op-switch",
        lease_id="lease-switch",
        operation_type="SWITCH",
        status="RUNNING",
        timeout_at="2026-09-11T01:00:00Z",
        target_game_id=GAMES[1],
        runtime_target=B,
        switch_source=A,
    )
    lease = dict(
        owner_operation_id="op-switch",
        lease_id="lease-switch",
        resource_id="wishicraft-main",
        lease_expires_at=int(now.timestamp()) + 900,
    )
    config = dict(
        instance_id=A["instance_id"],
        config_digest=A["config_digest"],
        system_id="wishicraft-main",
        games=list(GAMES),
    )
    request = dict(
        schema_version=2, operation_id="op-switch", lease_id="lease-switch", action=action
    )
    assert authorize(request, op, lease, config, now) == target
    op["status"] = "FAILED"
    with pytest.raises(ValueError, match="STALE_OPERATION"):
        authorize(request, op, lease, config, now)


def test_atomic_pair_response_loss_read_back_does_not_choose_new_source() -> None:
    class Dynamo:
        item: dict[str, Any] = {}

        def update_item(self, **kwargs: Any) -> None:
            values = kwargs["ExpressionAttributeValues"]
            self.item = {"runtime_target": values[":target"], "switch_source": values[":source"]}
            raise TimeoutError("committed response lost")

        def get_item(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["ConsistentRead"]
            return {"Item": self.item}

    repository = RuntimeTargetRepository(Dynamo(), "operations")
    repository.freeze_switch(operation_id="op-switch", lease_id="lease-switch", source=A, target=B)
    assert repository.read("op-switch") == B
    repository.field = "switch_source"
    assert repository.read("op-switch") == A
