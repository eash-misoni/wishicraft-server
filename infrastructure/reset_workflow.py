"""Reset composes the existing STOP/START graph. No EC2 lifecycle or intermediate release."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from infrastructure.switch_workflow import definition as switch_definition


def definition(
    *, start: dict[str, Any], stop: dict[str, Any], stop_task_arn: str
) -> dict[str, Any]:
    graph = switch_definition(start=start, stop=stop, stop_task_arn=stop_task_arn)
    states = graph["States"]
    states["PrepareSwitch"]["Parameters"]["Payload"]["action"] = "prepare_reset"
    states["VerifySourceStopped"]["Next"] = "ResetPrepareSend"
    template = deepcopy(states["PrepareSwitch"])
    completion = next(
        name
        for name, value in states.items()
        if value.get("Parameters", {}).get("Payload", {}).get("action") == "complete"
    )

    def task(action: str, following: str) -> dict[str, Any]:
        result = deepcopy(template)
        result["Parameters"]["Payload"]["action"] = action
        result["Next"] = following
        return dict(result)

    for name, action, following in [
        ("ResetPrepare", "prepare", "ResetCommit"),
        ("ResetCleanup", "cleanup", completion),
    ]:
        send = task("run_reset_" + action, name + "Wait")
        send["ResultPath"] = "$.reset_command"
        # Send/reply uncertainty retains ownership. Never release a possibly executing host job.
        # Uncaught Task failure preserves the failing Task for a same-execution redrive.
        # A Fail-state catch would redrive the Fail state itself, not this resumable Task.
        send.pop("Catch", None)
        states[name + "Send"] = send
        states[name + "Wait"] = {"Type": "Wait", "Seconds": 15, "Next": name + "Renew"}
        states[name + "Renew"] = task("renew", name + "Check")
        check = task("check_reset_" + action, name + "Done")
        check["Parameters"]["Payload"]["command_id.$"] = "$.reset_command.Payload.command_id"
        check["ResultPath"] = "$.reset_check"
        check.pop("Catch", None)
        states[name + "Check"] = check
        states[name + "Done"] = {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reset_check.Payload.complete",
                    "BooleanEquals": True,
                    "Next": following,
                }
            ],
            "Default": name + "Wait",
        }
    states["ResetCommit"] = task("commit_reset", "StartReconcileBeforeStart")
    states["ResetCommit"].pop("Catch", None)

    def redirect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"Next", "Default"} and item == completion:
                    value[key] = "ResetCleanupSend"
                else:
                    redirect(item)
        elif isinstance(value, list):
            for item in value:
                redirect(item)

    for name, state in states.items():
        if name != "ResetCleanupDone":
            redirect(state)
    return graph
