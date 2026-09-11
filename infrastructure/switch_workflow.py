"""Compose the existing graceful STOP/START graphs, without EC2 lifecycle tasks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def definition(
    *, start: dict[str, Any], stop: dict[str, Any], stop_task_arn: str
) -> dict[str, Any]:
    def renamed(value: Any, prefix: str) -> Any:
        if isinstance(value, dict):
            return {
                k: prefix + v if k in {"Next", "Default", "StartAt"} else renamed(v, prefix)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [renamed(x, prefix) for x in value]
        return value

    states = {"Start" + k: renamed(v, "Start") for k, v in deepcopy(start["States"]).items()}
    states.update({"Stop" + k: renamed(v, "Stop") for k, v in deepcopy(stop["States"]).items()})
    prepare = deepcopy(states["StopSetDesiredStopped"])
    prepare["Parameters"]["Payload"]["action"] = "prepare_switch"
    prepare["ResultPath"] = "$.switch_prepared"
    prepare["Next"] = "StopSetDesiredStopped"
    states["PrepareSwitch"] = prepare
    states["StopReconcileBeforeStop"]["Next"] = "PrepareSwitch"
    states["StopSetDesiredStopped"]["Next"] = "StopAlreadyRuntimeStopped"
    states["StopAlreadyRuntimeStopped"]["Choices"][0]["Next"] = "VerifySourceStopped"
    states["StopRuntimeStopped"]["Choices"][0]["Next"] = "VerifySourceStopped"
    verify = deepcopy(prepare)
    verify["Parameters"]["Payload"]["action"] = "verify_switch_stopped"
    verify["Parameters"]["FunctionName"] = stop_task_arn
    verify["Next"] = "StartReconcileBeforeStart"
    states["VerifySourceStopped"] = verify
    states["StartAlreadyReady"]["Default"] = "StartRunStartScript"

    # Reachability pruning also excludes source completion/lock release and EC2 waits.
    def successors(value: Any) -> list[str]:
        if isinstance(value, dict):
            result: list[str] = []
            for key, item in value.items():
                result.extend([item] if key in {"Next", "Default"} else successors(item))
            return result
        if isinstance(value, list):
            return [n for item in value for n in successors(item)]
        return []

    reached: set[str] = set()
    pending = ["StopInitializeWorkflow"]
    while pending:
        name = pending.pop()
        if name not in reached:
            reached.add(name)
            pending.extend(successors(states[name]))
    result = {name: states[name] for name in sorted(reached)}
    if any(
        name in result for name in ("StartStartEc2IfNeeded", "StopStopEc2", "StopCompleteOperation")
    ):
        raise ValueError("SWITCH graph includes EC2 lifecycle or intermediate completion")
    return {"StartAt": "StopInitializeWorkflow", "TimeoutSeconds": 3000, "States": result}
