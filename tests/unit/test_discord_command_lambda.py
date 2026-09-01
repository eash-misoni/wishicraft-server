from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import cast

import pytest
from nacl.signing import SigningKey

from wishicraft import discord_command_lambda

APPLICATION_ID = "1531887197433757768"
GUILD_ID = "1251169327554625757"
OPERATION_CHANNEL_ID = "1531883129525244015"
PLAYER_ROLE_ID = "1531883392205983765"
ADMIN_ROLE_ID = "1531883595113697410"
TIMESTAMP = "1788060000"


class Admission:
    def __init__(self, result: str | Exception = "op-status-001") -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def admit(
        self, *, operation_type: str, interaction_id: str, guild_id: str, channel_id: str
    ) -> str:
        self.calls.append((operation_type, interaction_id))
        assert guild_id == GUILD_ID
        assert channel_id == OPERATION_CHANNEL_ID
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> SigningKey:
    key = SigningKey.generate()
    environment = {
        "DISCORD_APPLICATION_ID": APPLICATION_ID,
        "DISCORD_GUILD_ID": GUILD_ID,
        "DISCORD_OPERATION_CHANNEL_ID": OPERATION_CHANNEL_ID,
        "DISCORD_PLAYER_ROLE_ID": PLAYER_ROLE_ID,
        "DISCORD_ADMIN_ROLE_ID": ADMIN_ROLE_ID,
        "DISCORD_PUBLIC_KEY": key.verify_key.encode().hex(),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(discord_command_lambda, "_operation_admission", Admission())
    return key


def payload(
    *,
    interaction_type: int = 2,
    subcommand: str = "status",
    include_empty_subcommand_options: bool = False,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "1532000000000000001",
        "application_id": APPLICATION_ID,
        "type": interaction_type,
        "token": "non-production-test-token",
        "version": 1,
    }
    if interaction_type == 2:
        option: dict[str, object] = {"name": subcommand, "type": 1}
        if include_empty_subcommand_options:
            option["options"] = []
        value.update(
            {
                "guild_id": GUILD_ID,
                "channel_id": OPERATION_CHANNEL_ID,
                "member": {"roles": [PLAYER_ROLE_ID]},
                "data": {
                    "id": "1532000000000000002",
                    "name": "mc",
                    "type": 1,
                    "options": [option],
                },
            }
        )
    return value


def event(
    value: object,
    key: SigningKey,
    *,
    raw: bytes | None = None,
    encoded: bool = False,
) -> dict[str, object]:
    body = raw if raw is not None else json.dumps(value, separators=(",", ":")).encode()
    signature = key.sign(TIMESTAMP.encode() + body).signature.hex()
    return {
        "headers": {
            "x-signature-ed25519": signature,
            "x-signature-timestamp": TIMESTAMP,
        },
        "body": base64.b64encode(body).decode() if encoded else body.decode(),
        "isBase64Encoded": encoded,
    }


def response_body(response: dict[str, object]) -> dict[str, object]:
    body = response["body"]
    assert isinstance(body, str)
    result = json.loads(body)
    assert isinstance(result, dict)
    return result


def test_ping_returns_pong(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(interaction_type=1), signing_key), None)
    assert response["statusCode"] == 200
    assert response_body(response) == {"type": 1}


def test_valid_status_is_admitted_once_then_deferred(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(), signing_key), None)
    assert response["statusCode"] == 200
    assert response_body(response) == {
        "type": 5,
        "data": {"flags": 64},
    }
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == [("STATUS", "1532000000000000001")]


def test_start_uses_shared_admission_and_immediate_ephemeral_ack(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(subcommand="start"), signing_key), None)
    assert response["statusCode"] == 200
    assert response_body(response)["type"] == 4
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == [("START", "1532000000000000001")]


def test_stop_uses_shared_admission_and_immediate_ephemeral_ack(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(subcommand="stop"), signing_key), None)
    assert response["statusCode"] == 200
    assert response_body(response)["type"] == 4
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == [("STOP", "1532000000000000001")]


@pytest.mark.parametrize("subcommand", ["status", "start", "stop"])
def test_production_empty_subcommand_options_reach_shared_admission_once(
    signing_key: SigningKey, subcommand: str
) -> None:
    response = discord_command_lambda.handler(
        event(
            payload(subcommand=subcommand, include_empty_subcommand_options=True),
            signing_key,
        ),
        None,
    )

    assert response["statusCode"] == 200
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == [(subcommand.upper(), "1532000000000000001")]


@pytest.mark.parametrize("nested_options", [[{}], None, {}, "unexpected"])
def test_malformed_subcommand_options_do_not_reach_admission(
    signing_key: SigningKey, nested_options: object
) -> None:
    value = payload(include_empty_subcommand_options=True)
    value["data"]["options"][0]["options"] = nested_options  # type: ignore[index]

    response = discord_command_lambda.handler(event(value, signing_key), None)

    assert response["statusCode"] == 400
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == []


def test_base64_command_uses_same_boundary(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(), signing_key, encoded=True), None)
    assert response["statusCode"] == 200


def test_invalid_signature_precedes_malformed_json(signing_key: SigningKey) -> None:
    signed = event({}, signing_key, raw=b"not-json")
    headers = signed["headers"]
    assert isinstance(headers, dict)
    headers["x-signature-ed25519"] = "0" * 128

    response = discord_command_lambda.handler(signed, None)

    assert response["statusCode"] == 401
    assert response_body(response) == {"error": "invalid request"}
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == []


def test_signed_malformed_json_is_safe_400(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event({}, signing_key, raw=b"not-json"), None)
    assert response["statusCode"] == 400
    assert response_body(response) == {"error": "invalid interaction"}


def test_unauthorized_request_has_no_role_or_internal_detail(signing_key: SigningKey) -> None:
    value = payload()
    value["member"] = {"roles": []}
    response = discord_command_lambda.handler(event(value, signing_key), None)
    rendered = json.dumps(response_body(response))
    assert response["statusCode"] == 200
    assert "not available" in rendered
    assert PLAYER_ROLE_ID not in rendered
    assert ADMIN_ROLE_ID not in rendered
    assert "arn:" not in rendered
    admission = discord_command_lambda._operation_admission
    assert isinstance(admission, Admission)
    assert admission.calls == []


def test_invalid_public_key_configuration_is_safe_500(
    signing_key: SigningKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", "invalid")
    response = discord_command_lambda.handler(event(payload(), signing_key), None)
    assert response["statusCode"] == 500
    assert response_body(response) == {"error": "service unavailable"}


def test_status_admission_failure_is_safe_and_retryable(signing_key: SigningKey) -> None:
    discord_command_lambda._operation_admission = Admission(RuntimeError("internal detail"))
    response = discord_command_lambda.handler(event(payload(), signing_key), None)
    assert response["statusCode"] == 200
    rendered = json.dumps(response_body(response))
    assert "Please retry" in rendered
    assert "internal detail" not in rendered


def test_lambda_admission_uses_stable_discord_key_and_accepts_duplicate_result() -> None:
    class Api:
        calls: list[dict[str, object]] = []

        def invoke(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(
                    b'{"schema_version":1,"operation_id":"op-existing",'
                    b'"created":false,"lease_id":null}'
                ),
            }

    api = Api()
    admission = discord_command_lambda.LambdaOperationAdmission(api, function_name="admission")
    assert (
        admission.admit(
            operation_type="STATUS",
            interaction_id="1532000000000000001",
            guild_id=GUILD_ID,
            channel_id=OPERATION_CHANNEL_ID,
        )
        == "op-existing"
    )
    raw_payload = api.calls[0]["Payload"]
    assert isinstance(raw_payload, bytes)
    request = json.loads(raw_payload)
    assert request == {
        "schema_version": 1,
        "operation": "admit",
        "operation_type": "STATUS",
        "idempotency_key": "discord:1532000000000000001",
        "requested_by": "DISCORD",
        "discord": {
            "guild_id": GUILD_ID,
            "channel_id": OPERATION_CHANNEL_ID,
            "interaction_id": "1532000000000000001",
        },
    }


def test_start_duplicate_uses_same_shared_admission_identity() -> None:
    class Api:
        calls: list[dict[str, object]] = []

        def invoke(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(
                    b'{"schema_version":1,"operation_id":"op-start-existing",'
                    b'"created":false,"lease_id":"lease-existing"}'
                ),
            }

    api = Api()
    admission = discord_command_lambda.LambdaOperationAdmission(api, function_name="admission")
    assert (
        admission.admit(
            operation_type="START",
            interaction_id="1532000000000000001",
            guild_id=GUILD_ID,
            channel_id=OPERATION_CHANNEL_ID,
        )
        == "op-start-existing"
    )
    request = json.loads(cast(bytes, api.calls[0]["Payload"]))
    assert request["operation_type"] == "START"
    assert request["idempotency_key"] == "discord:1532000000000000001"


def test_stop_duplicate_uses_same_shared_admission_identity() -> None:
    class Api:
        calls: list[dict[str, object]] = []

        def invoke(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(
                    b'{"schema_version":1,"operation_id":"op-stop-existing",'
                    b'"created":false,"lease_id":"lease-existing"}'
                ),
            }

    api = Api()
    admission = discord_command_lambda.LambdaOperationAdmission(api, function_name="admission")
    assert (
        admission.admit(
            operation_type="STOP",
            interaction_id="1532000000000000001",
            guild_id=GUILD_ID,
            channel_id=OPERATION_CHANNEL_ID,
        )
        == "op-stop-existing"
    )
    request = json.loads(cast(bytes, api.calls[0]["Payload"]))
    assert request["operation_type"] == "STOP"
    assert request["idempotency_key"] == "discord:1532000000000000001"


def test_stop_admission_failure_is_safe_and_retryable(signing_key: SigningKey) -> None:
    discord_command_lambda._operation_admission = Admission(RuntimeError("internal detail"))
    response = discord_command_lambda.handler(event(payload(subcommand="stop"), signing_key), None)
    assert response["statusCode"] == 200
    rendered = json.dumps(response_body(response))
    assert "Please retry" in rendered
    assert "internal detail" not in rendered


def test_phase7f_handler_only_connects_commands_to_shared_admission_lambda() -> None:
    assert discord_command_lambda.__file__ is not None
    source = Path(discord_command_lambda.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "Reconcile",
        "StartExecution",
        "dynamodb",
        "ec2",
        "ssm",
        "route53",
    ):
        assert forbidden not in source
    assert 'operation_type="STATUS"' in source
    assert 'operation_type="START"' in source
    assert 'operation_type="STOP"' in source
    assert "StartExecution" not in source
