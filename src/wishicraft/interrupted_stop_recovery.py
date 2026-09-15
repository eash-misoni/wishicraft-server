"""Operator-only closure of one interrupted run; never a Game START or admission API.

The operator transports this module with a reviewed, root-owned plan. Production
uses the hash-verified installed operation-v2, not a replacement host runtime.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

GAMES = Path("/srv/minecraft/games")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def recover(
    host: Any,
    plan: dict[str, Any],
    *,
    operator_gate: Callable[[], None],
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Hold the normal flock and require fresh operator/host gates before effects.

    operator_gate verifies closed ingress, STOPPED Desired, no Current/workflow,
    active SSM other than this invocation, queues and DNS. It must fail on unknown
    observations. The host additionally checks the live lease and terminal old
    Operation independently. Neither gate grants a new run or a lease override.
    """
    target = plan["target"]
    if (
        plan["schema_version"] != 1
        or set(plan)
        != {
            "schema_version",
            "target",
            "container_id",
            "original_started_at",
            "game_sha256",
            "prepared_owner_sha256",
            "package_digest",
            "world_directory_inode",
        }
        or set(target) != {"instance_id", "game_id", "run_id", "data_source", "config_digest"}
        or re.fullmatch(r"[0-9a-f]{64}", plan["container_id"]) is None
        or re.fullmatch(r"game-[0-9a-f]{64}", target["game_id"]) is None
        or target["data_source"] != str(GAMES / target["game_id"] / "server")
    ):
        raise ValueError("RECOVERY_PLAN_INVALID")
    with (host.ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt_path = host.ROOT / "receipt.json"
        journal_path = host.ROOT / "interrupted-stop.json"
        record = host.initial_module().worlds.record
        config = record(host.CONFIG)
        manifest_bytes = (host.ARTIFACTS / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        if (
            host.actual_instance() != target["instance_id"]
            or config["instance_id"] != target["instance_id"]
            or config["config_digest"] != target["config_digest"]
            or hashlib.sha256(manifest_bytes).hexdigest() != target["config_digest"]
        ):
            raise ValueError("RECOVERY_RUNTIME_MISMATCH")
        for name, field in (
            ("compose.yaml", "compose_sha256"),
            ("runtime.env", "runtime_env_sha256"),
        ):
            if hashlib.sha256((host.ARTIFACTS / name).read_bytes()).hexdigest() != manifest[field]:
                raise ValueError("RECOVERY_ARTIFACT_MISMATCH")

        def gate() -> None:
            operator_gate()
            if host.item(config, "locks_table", "lock_name", config["lock_name"]):
                raise ValueError("RECOVERY_LOCK_PRESENT")
            operation = host.item(config, "operations_table", "operation_id", target["run_id"])
            if (
                operation.get("status") != "FAILED"
                or operation.get("operation_type") != "START"
                or operation.get("runtime_target") != target
            ):
                raise ValueError("RECOVERY_OLD_OPERATION_MISMATCH")
            game = host.item(config, "games_table", "game_id", target["game_id"])
            if (
                digest(game) != plan["game_sha256"]
                or game["lifecycle_state"] != "ACTIVE"
                or game["materialization_state"] != "UNMATERIALIZED"
                or game["world"]["generation"] != 1
            ):
                raise ValueError("RECOVERY_GAME_MISMATCH")
            package = host.package_module().registered(game, manifest, target["config_digest"])
            if host.package_module().digest(package) != plan["package_digest"]:
                raise ValueError("RECOVERY_PACKAGE_MISMATCH")

        gate()
        host.execute(
            [
                "bash",
                "-c",
                'set -aeu; source /etc/wishicraft/host-runtime.env; "$MOUNT_GUARD" --verify',
            ]
        )
        owner_path = Path(target["data_source"]).parent.parent / (
            target["game_id"] + ".initial-owner.json"
        )
        owner = host.initial_module().worlds.record(owner_path)
        if digest({**owner, "phase": "prepared"}) != plan["prepared_owner_sha256"] or owner[
            "phase"
        ] not in {"prepared", "initialized"}:
            raise ValueError("RECOVERY_INITIAL_OWNER_MISMATCH")
        world = Path(target["data_source"]) / "world"
        if (
            world.is_symlink()
            or not world.is_dir()
            or world.stat().st_ino != plan["world_directory_inode"]
            or not (world / "level.dat").is_file()
        ):
            raise ValueError("RECOVERY_WORLD_MISSING")
        receipt = record(receipt_path)
        if receipt.get("target") != target or receipt.get("phase") not in {
            "running",
            "stopping",
            "stopped",
        }:
            raise ValueError("RECOVERY_RECEIPT_MISMATCH")
        journal = (
            record(journal_path) if journal_path.exists() or journal_path.is_symlink() else None
        )
        if journal and journal.get("plan") != plan:
            raise ValueError("RECOVERY_JOURNAL_MISMATCH")
        if journal and journal.get("phase") not in {"reacquiring", "saved", "finalized"}:
            raise ValueError("RECOVERY_JOURNAL_PHASE")

        def container() -> dict[str, Any] | None:
            current = host.inspect()
            all_ids = host.execute(["docker", "ps", "-aq", "--no-trunc"]).split()
            if not current:
                if all_ids:
                    raise ValueError("RECOVERY_OTHER_CONTAINER")
                return None
            value = current[0]
            if all_ids != [plan["container_id"]] or value["Id"] != plan["container_id"]:
                raise ValueError("RECOVERY_CONTAINER_MISMATCH")
            host.validate_container(value, target)
            host.configured_container(value, manifest)
            host.validate_persistence(value, target)
            if value["HostConfig"]["RestartPolicy"]["Name"] != "no":
                raise ValueError("RECOVERY_RESTART_POLICY")
            return dict(value)

        current = container()
        if receipt["phase"] == "stopped":
            if (
                current
                or not journal
                or not journal.get("proof")
                or receipt.get("stop") != {**journal["proof"], "removal_ready": True}
                or not receipt["stop"].get("removal_ready")
            ):
                raise ValueError("RECOVERY_TERMINAL_UNPROVEN")
            host.stopped_environment()
            return
        if not journal:
            if not current:
                raise ValueError("RECOVERY_INITIAL_STATE")
            if current["State"]["StartedAt"] != plan["original_started_at"]:
                raise ValueError("RECOVERY_PROCESS_MISMATCH")
            if receipt["phase"] == "stopping":
                # This branch accepts an existing canonical stopping receipt;
                # a log or an exited container cannot supply this proof.
                journal = {"plan": plan, "phase": "saved", "proof": receipt.get("stop")}
            elif receipt == {"target": target, "phase": "running"}:
                journal = {"plan": plan, "phase": "reacquiring"}
            else:
                raise ValueError("RECOVERY_INITIAL_STATE")
            host.atomic(journal_path, json.dumps(journal))

        if receipt["phase"] == "running" and "proof" not in journal:
            if current is None:
                raise ValueError("RECOVERY_CONTAINER_MISSING")
            state = current["State"]
            if not state["Running"]:
                if (
                    state["Status"] != "exited"
                    or state["ExitCode"] != 0
                    or state["OOMKilled"]
                    or state["Error"]
                ):
                    raise ValueError("RECOVERY_ABNORMAL_EXIT")
                host.stopped_environment()
                gate()
                # Restore only volatile run/secret inputs for the existing container.
                # docker start preserves its ID, labels, mounts and old run identity.
                package = host.package_module().observed(current, manifest, target)
                env = {
                    "WISHICRAFT_RUN_ID": target["run_id"],
                    "WISHICRAFT_GAME_ID": target["game_id"],
                    "GAME_DIRECTORY": target["data_source"],
                    **host.package_module().projection(target["game_id"], package),
                }
                host.RUN_ENV.parent.mkdir(mode=0o700, exist_ok=True)
                host.atomic(host.RUN_ENV, "".join(k + "=" + v + "\n" for k, v in env.items()))
                host.execute(["/usr/local/libexec/wishicraft/rcon-secret-v2", "prepare"])
                host.execute(["docker", "start", plan["container_id"]], timeout=60)
            for _ in range(120):
                current = container()
                if current is None or not current["State"]["Running"]:
                    raise ValueError("RECOVERY_RUNTIME_EXITED")
                if current["State"].get("Health", {}).get("Status") == "healthy":
                    break
                sleep(5)
            else:
                raise ValueError("RECOVERY_HEALTH_TIMEOUT")
            gate()
            players = host.execute(["docker", "exec", plan["container_id"], "rcon-cli", "list"])
            if not host.confirmed_empty_players(players, neoforge=True):
                raise ValueError("RECOVERY_PLAYERS_NOT_EMPTY")
            response = host.execute(
                ["docker", "exec", plan["container_id"], "rcon-cli", "save-all", "flush"],
                timeout=60,
            )
            if response.replace("\x1b[0m", "").strip().splitlines() != [
                "Saving the game (this may take a moment!)",
                "Saved the game",
            ]:
                raise ValueError("RECOVERY_SAVE_RESPONSE_UNKNOWN")
            after = container()
            if (
                after is None
                or after["State"]["StartedAt"] != current["State"]["StartedAt"]
                or not after["State"]["Running"]
            ):
                raise ValueError("RECOVERY_SAVE_PROCESS_CHANGED")
            journal = {
                **journal,
                "phase": "saved",
                "proof": {
                    "container_id": plan["container_id"],
                    "started_at": current["State"]["StartedAt"],
                    "save_confirmed": True,
                    "removal_ready": False,
                },
            }
            host.atomic(journal_path, json.dumps(journal))

        proof = journal.get("proof")
        if (
            not proof
            or set(proof) != {"container_id", "started_at", "save_confirmed", "removal_ready"}
            or proof.get("container_id") != plan["container_id"]
            or proof.get("save_confirmed") is not True
            or type(proof.get("removal_ready")) is not bool
        ):
            raise ValueError("RECOVERY_SAVE_PROOF_MISSING")
        current = container()
        if current and current["State"]["StartedAt"] != proof["started_at"]:
            raise ValueError("RECOVERY_PROOF_PROCESS_MISMATCH")
        if receipt["phase"] == "running":
            receipt = {"target": target, "phase": "stopping", "stop": proof}
            host.atomic(receipt_path, json.dumps(receipt))
        elif {**receipt.get("stop", {}), "removal_ready": False} != {
            **proof,
            "removal_ready": False,
        }:
            raise ValueError("RECOVERY_STOP_PROOF_MISMATCH")
        gate()
        if current and current["State"]["Running"]:
            host.execute(["docker", "stop", "--time", "150", plan["container_id"]], timeout=180)
        host.finish_stop(receipt_path, receipt, target, manifest)
        final = json.loads(receipt_path.read_text())
        host.atomic(
            journal_path, json.dumps({**journal, "phase": "finalized", "proof": final["stop"]})
        )
