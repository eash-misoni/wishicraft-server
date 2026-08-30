from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_doc(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_phase7_decisions_preserve_control_plane_boundaries() -> None:
    decisions = read_doc("09_decisions_and_backlog.md")

    for decision_id in range(79, 85):
        assert f"### D-{decision_id:03d}" in decisions

    assert "player roleまたはadmin role" in decisions
    assert "State MachineをAdmission抜きで起動しない" in decisions
    assert "Lockを取得せず、`SystemState.current_operation_id`も設定しない" in decisions
    assert "Discord message create/updateはOperation/Observed Stateの" in decisions
    assert "Bot Tokenを読まない" in decisions
    assert "CDK deployの暗黙side effectにせず" in decisions


def test_phase7_delivery_plan_is_sliced_before_implementation() -> None:
    plan = read_doc("06_delivery_plan.md")

    for phase in "ABCDEFG":
        assert f"### Phase 7{phase}" in plan

    assert "Phase 7A Contract / Decision freeze" in plan
    assert "source、infrastructure、AWS、Discord external configurationは変更しない" in plan
    assert "Phase 7B — Discord ingress / signature / authorization" in plan
    assert "Phase 7G — real Discord + AWS E2E / release gate" in plan


def test_phase7_secret_and_registration_ownership_are_consistent() -> None:
    security = read_doc("07_operations_security_and_cost.md")
    configuration = read_doc("12_initial_configuration.md")

    assert "Bot Tokenの`ssm:GetParameter`はMessage componentだけ" in security
    assert "Command Lambdaへ配布し、Bot Tokenは配布しない" in security
    assert "値を表示せず確認" in configuration
    assert "command registrationをCDK deployの暗黙side effectにしない" in configuration
