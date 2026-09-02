from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phase_eight_backup_decision_and_scope_are_canonical() -> None:
    decisions = (ROOT / "docs/09_decisions_and_backlog.md").read_text(encoding="utf-8")
    requirements = (ROOT / "docs/02_requirements.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/06_delivery_plan.md").read_text(encoding="utf-8")
    assert "D-090" in decisions
    assert "root EBSを除外" in decisions
    assert "CreateSnapshot`はclient tokenを持たない" in decisions
    assert "migration/protected" in delivery
    assert "自動削除と`DeleteSnapshot`権限を追加しない" in requirements


def test_restore_schedule_running_and_discord_are_out_of_phase_eight_a() -> None:
    delivery = (ROOT / "docs/06_delivery_plan.md").read_text(encoding="utf-8")
    phase = delivery.split("#### Phase 8A", maxsplit=1)[1]
    assert all(word in phase for word in ("Restore", "schedule", "RUNNING", "Discord"))
    assert "対象外" in phase
