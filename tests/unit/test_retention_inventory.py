from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tools.retention_inventory import (
    ALLOWED,
    Reader,
    bounded_capture,
    decode,
    main,
    report,
    save,
    stability_view,
)
from tools.retention_projection import policy_projection, project_snapshots, provenance_pairs
from tools.retention_references import journal_references, manifest_references
from wishicraft.backup_provenance import BackupProvenanceRecord
from wishicraft.daily_backup import initial
from wishicraft.maintenance_repository import encode
from wishicraft.restore_source import request_operation
from wishicraft.retention import RetentionContext

NOW = datetime(2026, 9, 27, tzinfo=UTC)
VOLUME = "vol-0123456789abcdef0"
ACCOUNT = "385526546525"
CONTEXT = RetentionContext(
    "wishicraft", "dev", "game-vanilla-main", VOLUME, ACCOUNT, shared_volume=True
)
SID = "snap-0123456789abcdef0"
OP = "op-01234567-89ab-cdef-0123-456789abcdef"
CANARY = "DO_NOT_PERSIST_mock_secret_or_environment_hash"


class Pages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def describe_snapshots(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_pages_empty_middle_and_final_audit() -> None:
    api = Pages(
        [
            {"Snapshots": [{"SnapshotId": SID}], "NextToken": "one"},
            {"Snapshots": [], "NextToken": "two"},
            {"Snapshots": []},
        ]
    )
    reader = Reader({"ec2": api})
    assert (
        len(
            reader.pages(
                "ec2",
                "describe_snapshots",
                {"OwnerIds": [ACCOUNT]},
                items="Snapshots",
                identity="SnapshotId",
            )
        )
        == 1
    )
    assert len(api.calls) == 3
    assert reader.audit[0]["final_page"] and reader.audit[0]["pages"] == 3
    assert not reader.audit[0]["issues"]
    assert "NextToken" not in json.dumps(reader.audit)


@pytest.mark.parametrize(
    "last,issue",
    [
        ({"Snapshots": [], "NextToken": "one"}, "invalid-or-cyclic-token"),
        ({"Snapshots": [{"SnapshotId": SID}]}, "missing-or-duplicate-identity"),
        (ValueError(CANARY), "read-failed"),
        ({"Snapshots": CANARY}, "invalid-page"),
    ],
)
def test_pages_fail_closed_without_exception_values(last: Any, issue: str) -> None:
    reader = Reader(
        {"ec2": Pages([{"Snapshots": [{"SnapshotId": SID}], "NextToken": "one"}, last])}
    )
    reader.pages("ec2", "describe_snapshots", {}, items="Snapshots", identity="SnapshotId")
    assert issue in reader.audit[0]["issues"]
    assert CANARY not in json.dumps(reader.audit)


def journal(phase: str = "PLANNED") -> dict[str, Any]:
    oid = request_operation("wishicraft-main", "dev", "restore-test-123")
    return dict(
        record_type="RESTORE",
        system_id="restore#" + oid,
        revision=1,
        phase=phase,
        plan=dict(
            schema_version=1,
            kind="RESTORE",
            operation_id=oid,
            request_id="restore-test-123",
            system_id="wishicraft-main",
            stage="dev",
            project="wishicraft",
            source_volume_id=VOLUME,
            game_id="game-vanilla-main",
            source_snapshot_id=SID,
            runtime_env=CANARY,
        ),
        pre_restore_backup=dict(snapshot_id=SID),
        token=CANARY,
    )


@pytest.mark.parametrize("phase", ["PLANNED", "PREPARED", "COMMITTED", "ROLLED_BACK"])
def test_all_journal_phases_keep_both_references(phase: str) -> None:
    holds, projection, issues = journal_references(
        [journal(phase)],
        system="wishicraft-main",
        stage="dev",
        project="wishicraft",
        volume=VOLUME,
        games={"game-vanilla-main"},
    )
    assert len(holds[SID]) == 2 and not issues
    assert CANARY not in json.dumps(projection)


@pytest.mark.parametrize(
    "change", [dict(system_id="wrong"), dict(plan={}), dict(record_type="OTHER")]
)
def test_invalid_journal_never_silently_releases(change: dict[str, Any]) -> None:
    row = {**journal(), **change}
    holds, _, issues = journal_references(
        [row],
        system="wishicraft-main",
        stage="dev",
        project="wishicraft",
        volume=VOLUME,
        games={"game-vanilla-main"},
    )
    assert issues and SID in holds


def manifest() -> dict[str, Any]:
    return dict(
        schema_version=1,
        review_status="PROPOSED",
        account_id=ACCOUNT,
        region="ap-northeast-1",
        entries=[],
    )


def test_manifest_review_cannot_be_self_asserted() -> None:
    with pytest.raises(ValueError):
        manifest_references(
            {**manifest(), "review_status": "APPROVED"},
            account=ACCOUNT,
            region="ap-northeast-1",
            snapshot_ids={SID},
        )
    entry = dict(snapshot_id=SID, kind="explicit-retention")
    holds, issues = manifest_references(
        {**manifest(), "entries": [entry]},
        account=ACCOUNT,
        region="ap-northeast-1",
        snapshot_ids=set(),
    )
    assert SID in holds and "manifest-snapshot-missing:" + SID in issues
    assert "invalid-hold-evidence:" + SID in issues


def data() -> dict[str, Any]:
    return {
        k: []
        for k in (
            "state",
            "games",
            "backups",
            "operations",
            "snapshots",
            "locks",
            "rules",
            "recycle_bin",
        )
    }


def wire(row: dict[str, Any]) -> dict[str, Any]:
    return encode(row)


def test_private_wire_nested_json_and_failure_never_reach_saved_output(tmp_path: Path) -> None:
    payload = data()
    payload["state"] = [
        wire(
            dict(
                system_id="wishicraft-main",
                backup_protection=initial(VOLUME, NOW),
                Environment={"Variables": {"KEY": CANARY}},
                AfterContext=json.dumps({"Environment": {"Variables": {"KEY": CANARY}}}),
            )
        ),
        wire(journal()),
    ]
    payload["games"] = [
        wire(
            dict(
                game_id="game-vanilla-main",
                playerdata=CANARY,
                recovery_json=json.dumps({"runtime_env": CANARY}),
            )
        )
    ]
    payload["backups"] = [wire(dict(recovery_json=CANARY, token=CANARY))]
    result = report(
        payload,
        context=CONTEXT,
        region="ap-northeast-1",
        system="wishicraft-main",
        manifest=manifest(),
        now=NOW,
        audit=[],
        comparisons=[{"equal": True}],
    )
    path = tmp_path / "report.json"
    save(path, result)
    assert CANARY not in path.read_text()
    assert result["status"] == "NO_DELETE" and result["planned_delete_ids"] == []
    assert result["deletion_authorized"] is False and result["delete_action_count"] == 0
    assert result["completeness"]["deletion_safety_complete"] is False
    stream = io.StringIO()

    def failing(_: Any) -> Any:
        raise RuntimeError(CANARY)

    with redirect_stdout(stream), redirect_stderr(stream):
        assert (
            main(
                [
                    "--stage",
                    "dev",
                    "--profile",
                    "mock",
                    "--manifest",
                    "mock",
                    "--output",
                    str(tmp_path / "never.json"),
                ],
                execute=failing,
            )
            == 1
        )
    assert CANARY not in stream.getvalue() and not (tmp_path / "never.json").exists()


def test_reference_changes_detected_but_observer_clock_ignored() -> None:
    a = data()
    a["state"] = [
        wire(
            dict(
                system_id="wishicraft-main",
                observed_at="old",
                backup_protection=initial(VOLUME, NOW),
            )
        ),
        wire(journal()),
    ]
    b = deepcopy(a)
    b["state"][0]["observed_at"] = {"S": "new"}
    assert stability_view(a) == stability_view(b)
    b["state"][1]["revision"] = {"N": "2"}
    assert stability_view(a) != stability_view(b)
    b = deepcopy(a)
    b["snapshots"].append({"SnapshotId": SID, "State": "pending"})
    assert stability_view(a) != stability_view(b)


def test_projection_boundary_and_holds_do_not_use_seven_slots() -> None:
    rows = [
        dict(
            snapshot_id=str(i),
            normal_eligible=True,
            acquired_at_utc=(NOW - timedelta(days=i)).isoformat(),
            reasons=[],
        )
        for i in range(20)
    ]
    rows[0]["normal_eligible"] = False
    p = policy_projection(rows, NOW)
    assert p["normal_count"] == 19
    assert rows[7]["newest_seven"] and rows[14]["within_14_days"]
    assert p["new_14d_or_seven_outside_ids"] == ["15", "16", "17", "18", "19"]
    assert len(p["old_newest_seven_outside_ids"]) == 12
    for row in rows:
        row["acquired_at_utc"] = (NOW - timedelta(days=20)).isoformat()
    p = policy_projection(rows, NOW)
    assert p["boundary_tie"] and not p["new_14d_or_seven_outside_ids"]


def test_no_mutation_exposed_and_wire_values_not_echoed() -> None:
    assert all(
        not method.startswith(
            ("delete", "put", "update", "create", "invoke", "start", "stop", "execute")
        )
        for methods in ALLOWED.values()
        for method in methods
    )
    with pytest.raises(ValueError, match="allowlist"):
        Reader({}).pages("ec2", "delete_snapshot", {})
    with pytest.raises(ValueError, match="unsupported wire"):
        decode({"UNKNOWN": CANARY})


def proof() -> BackupProvenanceRecord:
    tags = dict(
        Project="wishicraft",
        Stage="dev",
        WishicraftCategory="backup",
        WishicraftGameId="game-vanilla-main",
        WishicraftOperationId=OP,
        WishicraftSourceVolumeId=VOLUME,
        WishicraftSchemaVersion="1",
        WishicraftProtected="false",
        WishicraftCreatedAt=NOW.isoformat(),
    )
    return BackupProvenanceRecord(
        SID,
        OP,
        "game-vanilla-main",
        VOLUME,
        "dev",
        "wishicraft",
        "backup",
        False,
        NOW,
        NOW,
        NOW,
        NOW,
        ACCOUNT,
        tags,
    )


def test_pair_validation_ttl_independence_legacy_orphans_duplicates() -> None:
    p = proof()
    records = [p.snapshot_item(), p.operation_item()]
    parsed, _, issues = provenance_pairs([wire(r) for r in records], records, CONTEXT)
    assert SID in parsed and not issues  # No Operations read or TTL assumption.
    for bad in [
        records[:1],
        records[1:],
        records + records[:1],
        [records[0], {**records[1], "snapshot_id": "snap-fffffffffffffffff"}],
    ]:
        _, _, issues = provenance_pairs([wire(r) for r in bad], bad, CONTEXT)
        assert issues
    raw = dict(
        SnapshotId=SID,
        VolumeId=VOLUME,
        OwnerId=ACCOUNT,
        State="completed",
        StartTime=NOW,
        Encrypted=True,
        Description="Wishicraft backup " + OP,
        Tags=[dict(Key=k, Value=v) for k, v in p.metadata.items()],
    )
    rows = project_snapshots(
        [raw], parsed, context=CONTEXT, region="ap-northeast-1", now=NOW, holds={}, locks={}
    )
    assert not rows[0]["normal_eligible"] and rows[0]["classification"] == "EXCLUDED"
    assert not rows[0]["holds"]  # Provenance self-reference is not a permanent hold.
    raw["StartTime"] = NOW + timedelta(seconds=1)
    rows = project_snapshots(
        [raw],
        parsed,
        context=CONTEXT,
        region="ap-northeast-1",
        now=NOW,
        holds={SID: ["journal:source"]},
        locks={},
    )
    assert rows[0]["holds"] and rows[0]["integrity_issues"]
    assert rows[0]["classification"] == "ANOMALY"


def test_bounded_capture_does_not_claim_stability(monkeypatch: pytest.MonkeyPatch) -> None:
    n = 0

    def collect(*_: Any) -> dict[str, Any]:
        nonlocal n
        n += 1
        d = data()
        d["snapshots"] = [{"SnapshotId": SID, "State": str(n)}]
        return d

    monkeypatch.setattr("tools.retention_inventory.collect_round", collect)
    _, comparisons = bounded_capture(Reader({}), {}, ACCOUNT)
    assert n == 4 and not any(c["equal"] for c in comparisons)


@pytest.mark.parametrize(
    "field,value",
    [
        ("OwnerId", "111111111111"),
        ("VolumeId", "vol-fffffffffffffffff"),
        ("StartTime", datetime(2026, 9, 27)),
    ],
)
def test_scope_and_naive_time_never_enter_normal(field: str, value: Any) -> None:
    p = proof()
    raw = dict(
        SnapshotId=SID,
        VolumeId=VOLUME,
        OwnerId=ACCOUNT,
        State="completed",
        StartTime=NOW,
        Encrypted=True,
        Description="Wishicraft backup " + OP,
        Tags=[dict(Key=k, Value=v) for k, v in p.metadata.items()],
    )
    raw[field] = value
    rows = project_snapshots(
        [raw], {}, context=CONTEXT, region="ap-northeast-1", now=NOW, holds={}, locks={}
    )
    assert not rows[0]["normal_eligible"]
    assert rows[0]["classification"] in {"EXCLUDED", "ANOMALY"}


def test_safe_stage_mismatch_and_unprotected_restore_reference() -> None:
    p = proof()
    raw = dict(
        SnapshotId=SID,
        VolumeId=VOLUME,
        OwnerId=ACCOUNT,
        State="completed",
        StartTime=NOW,
        Encrypted=True,
        Description=CANARY,
        Tags=[dict(Key=k, Value=("other" if k == "Stage" else v)) for k, v in p.metadata.items()],
    )
    rows = project_snapshots(
        [raw],
        {},
        context=CONTEXT,
        region="ap-northeast-1",
        now=NOW,
        holds={SID: ["journal:source"]},
        locks={},
    )
    assert rows[0]["holds"] and not rows[0]["normal_eligible"]
    assert CANARY not in json.dumps(rows)


def test_failed_api_is_unknown_not_confirmed_empty() -> None:
    audit = [
        dict(
            api="ec2.describe_locked_snapshots", final_page=False, issues=["UnauthorizedOperation"]
        )
    ]
    result = report(
        data(),
        context=CONTEXT,
        region="ap-northeast-1",
        system="wishicraft-main",
        manifest=manifest(),
        now=NOW,
        audit=audit,
        comparisons=[{"equal": True}],
    )
    assert not result["completeness"]["api_pages"]
    assert "incomplete-or-invalid-read:ec2.describe_locked_snapshots" in result["missing_checks"]
    assert result["planned_delete_ids"] == []


def test_repository_manifest_paths_and_identities_are_real() -> None:
    root = Path(__file__).resolve().parents[2]
    m = json.loads((root / "docs/evidence/retention_holds_dev.proposed.json").read_text())
    for entry in m["entries"]:
        assert (root / entry["evidence"]["path"]).is_file()
    holds, issues = manifest_references(
        m,
        account=ACCOUNT,
        region="ap-northeast-1",
        snapshot_ids={e["snapshot_id"] for e in m["entries"]},
    )
    assert len(holds) == 6 and issues == ["historical-hold-manifest-unreviewed"]


def test_rule_metadata_request_id_does_not_fake_reference_change() -> None:
    a = data()
    a["rules"] = [dict(Identifier="rule123", ResponseMetadata={"RequestId": "one"})]
    b = deepcopy(a)
    b["rules"][0]["ResponseMetadata"]["RequestId"] = "two"
    assert stability_view(a) == stability_view(b)
    b["rules"][0]["Status"] = "pending"
    assert stability_view(a) != stability_view(b)


def test_games_registry_policy_and_import_are_not_malformed_games() -> None:
    from tools.retention_references import game_references

    gid = "game-" + "a" * 64
    rows: list[dict[str, Any]] = [
        dict(game_id="registry-game-creation-v1", registered_ids=[gid]),
        dict(game_id="policy-whitelist-common-v1", policy_json='{"revision":2,"members":{}}'),
        dict(
            game_id=gid,
            world=dict(generation=1, generation_counter=2),
            creation={"import": {"archive": CANARY}},
        ),
    ]
    projection, issues = game_references(rows)
    assert not issues and projection[-1]["counter"] == 2
    assert projection[-1]["import_record_present"]
    assert CANARY not in json.dumps(projection)
    rows[0]["registered_ids"] = ["bad"]
    assert game_references(rows)[1] == ["invalid-game-registry"]


def test_old_terminal_start_is_not_unresolved_backup_but_backup_timeout_is() -> None:
    from tools.retention_inventory import needs_operation_review
    from tools.retention_references import OPERATION, identifier

    assert identifier("op-phase4-integration-stale-20260829", OPERATION)
    assert not needs_operation_review(dict(operation_type="START", status="TIMED_OUT"))
    assert needs_operation_review(dict(operation_type="BACKUP", status="TIMED_OUT"))
    assert needs_operation_review(dict(operation_type="BACKUP", status="FAILED"))


def test_valid_shared_recovery_checks_original_then_removes_payload_and_hashes(
    tmp_path: Path,
) -> None:
    import hashlib
    from dataclasses import replace

    from wishicraft.backup_recovery import shared_tags

    p = proof()
    env_hash = hashlib.sha256(CANARY.encode()).hexdigest()
    recovery = json.dumps(
        dict(
            schema_version=1,
            source_volume_id=VOLUME,
            games={
                "game-vanilla-main": dict(
                    game_id="game-vanilla-main",
                    data_source="/srv/minecraft/games/game-vanilla-main/server",
                )
            },
            runtime=dict(
                runtime_env=CANARY,
                compose_yaml=CANARY,
                manifest_json=json.dumps(
                    dict(
                        games=["game-vanilla-main"],
                        compose_sha256=env_hash,
                        runtime_env_sha256=env_hash,
                    )
                ),
            ),
        )
    )
    p = replace(
        p,
        schema_version=2,
        recovery_json=recovery,
        metadata=shared_tags({**p.metadata, "WishicraftSchemaVersion": "2"}, recovery),
    )
    pair = [p.snapshot_item(), p.operation_item()]
    parsed, projection, issues = provenance_pairs([wire(r) for r in pair], pair, CONTEXT)
    assert not issues and SID in parsed
    path = tmp_path / "projection.json"
    save(path, {"provenance": projection})
    assert CANARY not in path.read_text() and env_hash not in path.read_text()
    bad = deepcopy(pair)
    bad[0]["recovery_json"] = recovery.replace(CANARY, "different")
    assert provenance_pairs([wire(r) for r in bad], bad, CONTEXT)[2]


def test_invalid_protection_with_pending_operation_is_reported_not_aborted() -> None:
    payload = data()
    payload["state"] = [
        wire(dict(system_id="wishicraft-main", backup_protection={"schema_version": 99}))
    ]
    payload["operations"] = [
        wire(
            dict(
                operation_id=OP,
                operation_type="BACKUP",
                status="PENDING",
                requested_at=NOW.isoformat(),
            )
        )
    ]
    r = report(
        payload,
        context=CONTEXT,
        region="ap-northeast-1",
        system="wishicraft-main",
        manifest=manifest(),
        now=NOW,
        audit=[],
        comparisons=[{"equal": True}],
    )
    assert "invalid-protection-authority" in r["missing_checks"]
    assert r["unresolved_operations"][0]["operation_id"] == OP
    assert r["status"] == "NO_DELETE"


def test_malformed_journal_phase_preserves_references() -> None:
    r = journal()
    r["phase"] = {"unexpected": CANARY}
    holds, projection, issues = journal_references(
        [r],
        system="wishicraft-main",
        stage="dev",
        project="wishicraft",
        volume=VOLUME,
        games={"game-vanilla-main"},
    )
    assert issues and holds[SID] and projection[0]["phase"] == "UNKNOWN"
    assert CANARY not in json.dumps(projection)


def test_protected_tag_does_not_skip_snapshot_metadata_integrity() -> None:
    p = proof()
    pair = [p.snapshot_item(), p.operation_item()]
    parsed, _, _ = provenance_pairs([wire(r) for r in pair], pair, CONTEXT)
    raw = dict(
        SnapshotId=SID,
        VolumeId=VOLUME,
        OwnerId=ACCOUNT,
        State="completed",
        StartTime=NOW,
        Encrypted=True,
        Description="Wishicraft backup " + OP,
        Tags=[
            dict(Key=k, Value=v) for k, v in {**p.metadata, "WishicraftProtected": "true"}.items()
        ],
    )
    rows = project_snapshots(
        [raw], parsed, context=CONTEXT, region="ap-northeast-1", now=NOW, holds={}, locks={}
    )
    assert rows[0]["holds"] == ["explicit-protected-tag"]
    assert "actual-snapshot-provenance-mismatch" in rows[0]["integrity_issues"]
