"""Human-terminal-only initial SecureString registration; no secret output or overwrite."""

from __future__ import annotations

import getpass
import secrets
import sys
import warnings
from pathlib import Path
from typing import Any

from wishicraft.config import load_configuration


class RegistrationStopped(RuntimeError):
    pass


def missing(api: Any, name: str) -> bool:
    result = api.describe_parameters(
        ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}]
    )
    entries = result.get("Parameters", [])
    if result.get("NextToken") or len(entries) > 1:
        raise RegistrationStopped("Unexpected parameter metadata; stop.")
    if not entries:
        return True
    entry = entries[0]
    if entry.get("Name") != name or entry.get("Type") != "SecureString":
        raise RegistrationStopped("Existing parameter metadata mismatch; stop.")
    return False


def create(api: Any, name: str, value: str) -> None:
    try:
        result = api.put_parameter(
            Name=name, Value=value, Type="SecureString", Tier="Standard", Overwrite=False
        )
    except Exception:
        raise RegistrationStopped(
            "Registration failed or result unknown; stop without retry."
        ) from None
    if result.get("Version") != 1:
        raise RegistrationStopped("Unexpected version; stop.")
    print(f"CREATED SecureString Version 1: {name}", flush=True)


def register(api: Any, oauth_name: str, signing_name: str) -> None:
    oauth_missing, signing_missing = missing(api, oauth_name), missing(api, signing_name)
    if oauth_missing:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise RegistrationStopped("Use an interactive human terminal; no piped secret input.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Discord OAuth client secret (hidden): ")
        if not value or value != value.strip() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise RegistrationStopped("Invalid secret input; nothing written.")
        create(api, oauth_name, value)
        del value
    else:
        print(f"EXISTS: {oauth_name}; preserved, value not read.")
    if signing_missing:
        create(api, signing_name, secrets.token_urlsafe(48))
    else:
        print(f"EXISTS: {signing_name}; preserved, value not read.")


def main() -> None:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    root = Path(__file__).resolve().parents[1]
    configuration = load_configuration(root, "dev")
    region = configuration.stage.aws_region
    session = boto3.Session(profile_name="wishicraft-dev", region_name=region)
    options = Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 1})
    try:
        caller = session.client("sts", config=options).get_caller_identity()
        if (
            caller.get("Account") != configuration.stage.aws_account_id
            or region != "ap-northeast-1"
        ):
            raise RegistrationStopped("Canonical caller/account/region mismatch; stop.")
        print(
            "Canonical caller/account/region verified. No existing parameter will be overwritten."
        )
        print(
            "Expected Discord Application: "
            + configuration.stage.discord_public_id("application_id")
        )
        names: Any = configuration.secrets.values["future_secure_parameters"]
        register(
            session.client("ssm", config=options),
            names["discord_oauth_client_secret"]["dev_parameter_name"],
            names["web_session_signing_key"]["dev_parameter_name"],
        )
    except (Exception, KeyboardInterrupt):
        print(
            "STOPPED. No secret printed. "
            "Do not retry a result-unknown write; ask for metadata review.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
