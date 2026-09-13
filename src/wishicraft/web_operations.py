"""Authenticated Web adapter to the existing Admission; no lifecycle side effects here."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any

from wishicraft.authorization import operation_authorized
from wishicraft.operation import OperationType, WebOperationContext
from wishicraft.progress_display import MILESTONE_STEPS
from wishicraft.web_auth import AuthRejected, Policy
from wishicraft.web_status import decode, display_name, mapping, stamp

OPERATIONS = ("START", "STOP", "SWITCH", "BACKUP", "RESET")
CREATION_OPERATIONS = (*OPERATIONS, "CREATE")


class WebRejected(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def principal(record: dict[str, Any], policy: Policy) -> dict[str, Any]:
    value = record.get("principal")
    if not isinstance(value, dict) or value.get("guild_id") != policy.guild_id:
        raise AuthRejected("login required")
    policy.authorize(
        {"id": value.get("user_id")},
        {"user": {"id": value.get("user_id")}, "roles": value.get("roles")},
    )
    if not isinstance(value.get("display_name"), str) or not 1 <= len(value["display_name"]) <= 100:
        raise AuthRejected("login required")
    return value


def allowed(kind: str, actor: dict[str, Any], policy: Policy) -> bool:
    return operation_authorized(
        kind,
        actor.get("roles"),
        player_role_id=policy.player_role_id,
        admin_role_id=policy.admin_role_id,
    )


def request_key(user_id: str, request_id: str) -> str:
    if not isinstance(request_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", request_id
    ):
        raise WebRejected("invalid_input")
    return "web:" + hashlib.sha256((user_id + "|" + request_id).encode()).hexdigest()


def game_key(game_id: str) -> str:
    return hashlib.sha256(("web-game-v1|" + game_id).encode()).hexdigest()[:24]


def parse_request(value: object) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("type") == "CREATE":
        from wishicraft.game_creation import validate

        if (
            set(value) != {"request_id", "type", "creation", "confirm"}
            or value["confirm"] is not True
        ):
            raise WebRejected("invalid_input")
        request_key("0", value["request_id"])
        try:
            validate(value["creation"])
        except ValueError as error:
            raise WebRejected("invalid_input") from error
        return dict(value)
    if not isinstance(value, dict) or set(value) != {
        "request_id",
        "type",
        "game",
        "confirm",
        "seed",
    }:
        raise WebRejected("invalid_input")
    request_key("0", value["request_id"])
    kind = value["type"]
    if not isinstance(kind, str) or kind not in OPERATIONS or type(value["confirm"]) is not bool:
        raise WebRejected("invalid_input")
    if kind in {"START", "SWITCH", "RESET"}:
        if not isinstance(value["game"], str) or not re.fullmatch(r"[0-9a-f]{24}", value["game"]):
            raise WebRejected("invalid_input")
    elif value["game"] is not None:
        raise WebRejected("invalid_input")
    if kind in {"SWITCH", "RESET"} and value["confirm"] is not True:
        raise WebRejected("confirmation_required")
    if kind == "RESET":
        if value["seed"] not in ("fixed", "new"):
            raise WebRejected("invalid_input")
    elif value["seed"] is not None:
        raise WebRejected("invalid_input")
    return dict(value)


def request_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Operations:
    def __init__(
        self,
        api: Any,
        invoke: Any,
        tables: dict[str, str],
        system_id: str,
        policy: Policy,
        catalog: tuple[str, ...],
        reset: dict[str, Any],
        admission: str,
    ) -> None:
        self.api, self.lambda_api, self.tables = api, invoke, tables
        self.system_id, self.policy, self.catalog, self.reset, self.admission = (
            system_id,
            policy,
            catalog,
            reset,
            admission,
        )

    def get(self, source: str, key: str, value: str) -> dict[str, Any]:
        raw = self.api.get_item(
            TableName=self.tables[source], Key={key: {"S": value}}, ConsistentRead=True
        ).get("Item", {})
        return {k: decode(v) for k, v in raw.items()}

    def game_ids(self) -> tuple[str, ...]:

        if os.environ.get("GAME_CREATION") != "1":
            return self.catalog
        from wishicraft.game_creation import registry_ids

        return registry_ids(self.api, self.tables["games"], self.catalog)

    def reset_policy(self, game: str, item: dict[str, Any]) -> dict[str, Any] | None:
        if "creation" in item:
            return mapping(item["creation"]).get("reset_policy")
        return self.reset.get(game)

    def capabilities(self, actor: dict[str, Any]) -> dict[str, Any]:
        games = []
        state = self.get("system", "system_id", self.system_id)
        observed = mapping(state.get("observation"))
        for game in self.game_ids():
            item = self.get("games", "game_id", game)
            if item.get("lifecycle_state") != "ACTIVE":
                continue
            world = mapping(item.get("world"))
            reset = self.reset_policy(game, item)
            materialized = item.get("materialization_state") == "MATERIALIZED"
            # Legacy generation is not a Reset count. No world path/Operation identity leaks.
            games.append(
                {
                    "key": game_key(game),
                    "selected": (state.get("desired_game_id") or state.get("game_id")) == game,
                    "observed_running": observed.get("observed_active_game_id") == game
                    and observed.get("runtime_ready") is True,
                    "observed_at": stamp(state.get("observed_at")),
                    "name": display_name(item.get("display_name")) or "Registered Game",
                    "reset": reset is not None,
                    "materialized": materialized,
                    "seed": str(world["seed"]) if world.get("seed") is not None else None,
                    "seed_modes": ["fixed", "new"] if reset else [],
                    "retain_previous": (reset or {}).get("retain_previous"),
                    "world": "never_started"
                    if not materialized
                    else "managed"
                    if world.get("current_id")
                    else "original",
                    "world_updated_at": stamp(item.get("updated_at")),
                }
            )
        return {
            "games": games,
            "allowed": [
                kind
                for kind in (
                    CREATION_OPERATIONS
                    if os.environ.get("GAME_CREATION") == "1"
                    and os.environ.get("CREATE_DISABLED") != "1"
                    else OPERATIONS
                )
                if allowed(kind, actor, self.policy)
            ],
        }

    def project(self, item: dict[str, Any]) -> dict[str, Any] | None:
        if not item:
            return None
        status = item.get("status")
        if status not in {
            "PENDING",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "TIMED_OUT",
            "CANCELLED",
        } or item.get("operation_type") not in {kind.value for kind in OperationType}:
            raise ValueError("invalid operation projection")
        game = self.get("games", "game_id", item["target_game_id"])
        actor = mapping(item.get("requested_by"))
        error = mapping(item.get("error")).get("code")
        return {
            "type": item["operation_type"],
            "status": status,
            "terminal": status not in {"PENDING", "RUNNING"},
            "game": display_name(game.get("display_name")),
            "actor": display_name(actor.get("display_name")) or "Operator",
            "source": "Web"
            if actor.get("source") == "WEB"
            else "Discord"
            if actor.get("source") == "DISCORD"
            else "Operator",
            "requested_at": stamp(item.get("requested_at")),
            "updated_at": stamp(item.get("updated_at")),
            "completed_at": stamp(item.get("completed_at")),
            "progress": "Gameを登録しました。まだ起動していません。"
            if item["operation_type"] == "CREATE"
            else MILESTONE_STEPS.get(str(item.get("current_step")), "受付済み・進捗待ち"),
            "milestones": [
                {"label": label, "at": stamp(item.get(f"progress_{step.lower()}_at"))}
                for step, label in MILESTONE_STEPS.items()
                if stamp(item.get(f"progress_{step.lower()}_at"))
            ],
            "error": "workflow_start_failed"
            if error == "WORKFLOW_START_FAILED"
            else "precondition_failed"
            if error
            in {
                "START_PRECONDITION_FAILED",
                "STOP_PRECONDITION_FAILED",
                "BACKUP_PRECONDITION_FAILED",
            }
            else "operation_failed"
            if status in {"FAILED", "TIMED_OUT", "CANCELLED"}
            else None,
            "cleanup_pending": mapping(item.get("result")).get("cleanup_pending") is True,
        }

    def lookup(self, actor: dict[str, Any], request_id: str) -> dict[str, Any]:
        record = self.get(
            "idempotency", "idempotency_key", request_key(actor["user_id"], request_id)
        )
        if not record:
            return {}
        item = self.get("operation", "operation_id", record["operation_id"])
        owner = mapping(item.get("requested_by"))
        if owner.get("source") != "WEB" or owner.get("discord_user_id") != actor["user_id"]:
            raise ValueError("request owner mismatch")
        return item

    def read(self, actor: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        if request_id is not None:
            item = self.lookup(actor, request_id)
        else:
            state = self.get("system", "system_id", self.system_id)
            operation_id = state.get("current_operation_id") or state.get("last_operation_id")
            item = self.get("operation", "operation_id", operation_id) if operation_id else {}
        return {"operation": self.project(item), "outcome": "recorded" if item else "not_recorded"}

    def submit(
        self, actor: dict[str, Any], value: object, session_id: str, now: datetime
    ) -> tuple[int, dict[str, Any]]:
        del now
        request = parse_request(value)
        if not allowed(request["type"], actor, self.policy):
            raise WebRejected("forbidden", 403)
        existing = self.lookup(actor, request["request_id"])
        digest = request_digest(request)
        if existing:
            if existing.get("web_request_digest") != digest:
                raise WebRejected("request_conflict", 409)
            return 200, {"outcome": "recorded", "operation": self.project(existing)}
        game = next((g for g in self.game_ids() if game_key(g) == request.get("game")), None)
        if request.get("game") is not None and game is None:
            raise WebRejected("invalid_input")
        if request["type"] == "RESET":
            item = self.get("games", "game_id", str(game))
            if (
                not self.reset_policy(str(game), item)
                or item.get("materialization_state") != "MATERIALIZED"
            ):
                raise WebRejected("unsupported_capability", 422)
        payload = {
            "schema_version": 1,
            "operation": "admit",
            "operation_type": request["type"],
            "requested_by": "WEB",
            "idempotency_key": request_key(actor["user_id"], request["request_id"]),
            "web": {
                **actor,
                "request_digest": digest,
                "session_fingerprint": hashlib.sha256(session_id.encode()).hexdigest(),
            },
            **({"target_game_id": game} if game else {}),
            **({"creation": request["creation"]} if request["type"] == "CREATE" else {}),
            **({"confirmed": True} if request["type"] in {"SWITCH", "RESET"} else {}),
            **({"seed_mode": request["seed"]} if request["type"] == "RESET" else {}),
        }
        try:
            raw = self.lambda_api.invoke(
                FunctionName=self.admission,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload).encode(),
            )
            if raw.get("StatusCode") != 200 or raw.get("FunctionError"):
                raise ValueError("admission outcome unknown")
            result = json.loads(raw["Payload"].read())
            if result.get("error") in {"conflict", "invalid_input", "forbidden"}:
                return {"conflict": 409, "invalid_input": 400, "forbidden": 403}[result["error"]], {
                    "error": result["error"],
                    "outcome": "rejected",
                }
            if (
                not isinstance(result.get("operation_id"), str)
                or type(result.get("created")) is not bool
            ):
                raise ValueError("admission outcome unknown")
        except Exception:
            # Transport failure is not permission to create a replacement request.
            return 503, {"error": "result_unknown", "outcome": "unknown"}
        return 202, {"outcome": "accepted"}


def admission_actor(value: object, kind: str, policy: Policy) -> WebOperationContext:
    if not isinstance(value, dict) or set(value) != {
        "user_id",
        "display_name",
        "roles",
        "guild_id",
        "request_digest",
        "session_fingerprint",
    }:
        raise WebRejected("invalid_input")
    actor = principal({"principal": value}, policy)
    if not allowed(kind, actor, policy):
        raise WebRejected("forbidden", 403)
    return WebOperationContext(
        actor["user_id"],
        actor["display_name"],
        value["request_digest"],
        value["session_fingerprint"],
    )
