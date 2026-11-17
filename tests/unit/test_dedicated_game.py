from dataclasses import replace

import pytest

from wishicraft.dedicated_game import (
    Backend,
    Binding,
    ContractError,
    DedicatedGame,
    HostState,
    OperationKind,
    RestoreManifest,
    RetirementProof,
    Writer,
)

WRITER = Writer(Backend.DEDICATED, 1)


def game(game_id: str = "A") -> DedicatedGame:
    return DedicatedGame(Binding(game_id, 2, 1, WRITER), HostState.STOPPED, save_revision=0)


def test_three_worlds_admit_independently_but_one_world_deduplicates() -> None:
    admissions = [
        game(name).begin(writer=WRITER, kind=OperationKind.START, request_id="same-request-id")
        for name in ("A", "B", "C")
    ]
    assert {op.binding.game_id for _, op in admissions} == {"A", "B", "C"}
    a, op = admissions[0]
    assert a.begin(writer=WRITER, kind=OperationKind.START, request_id=op.request_id) == (a, op)
    with pytest.raises(ContractError, match="another operation"):
        a.begin(writer=WRITER, kind=OperationKind.START, request_id="other")
    with pytest.raises(ContractError, match="not current"):
        a.finish(admissions[1][1])
    a = a.finish(op)
    assert a.begin(writer=WRITER, kind=OperationKind.START, request_id=op.request_id) == (a, op)
    with pytest.raises(ContractError, match="another operation"):
        a.begin(writer=WRITER, kind=OperationKind.STOP, request_id=op.request_id)
    assert admissions[1][0].finish(admissions[1][1]).state is HostState.RUNNING


def test_stale_events_and_delayed_results_are_fenced() -> None:
    g, start = game().begin(writer=WRITER, kind=OperationKind.START, request_id="first")
    for binding in (
        replace(start.binding, generation=1),
        replace(start.binding, incarnation=0),
        replace(start.binding, writer=Writer(Backend.DEDICATED, 0)),
    ):
        with pytest.raises(ContractError):
            g.finish(replace(start, binding=binding))
        with pytest.raises(ContractError):
            g.finish(start).heartbeat(replace(start, binding=binding), sequence=1)
    g = g.finish(start).heartbeat(start, sequence=3)
    with pytest.raises(ContractError):
        g.heartbeat(start, sequence=2)
    g, stop = g.begin(writer=WRITER, kind=OperationKind.STOP, request_id="stop")
    with pytest.raises(ContractError):
        g.heartbeat(start, sequence=4)
    with pytest.raises(ContractError):
        g.finish(start)
    with pytest.raises(ContractError, match="confirmed save"):
        g.finish(stop)
    assert g.finish(stop, confirmed_saved=True).save_revision == stop.revision


def test_unknown_never_counts_as_stopped_or_deleted() -> None:
    g, op = game().begin(writer=WRITER, kind=OperationKind.START, request_id="start")
    g = g.record_uncertain(op)
    assert g.state is HostState.UNKNOWN and g.save_revision is None and g.active == op
    with pytest.raises(ContractError):
        g.begin(writer=WRITER, kind=OperationKind.RETIRE, request_id="retire")
    with pytest.raises(ContractError):
        g.reassign(expected=WRITER, backend=Backend.LEGACY)
    assert g.finish(op).state is HostState.RUNNING


def test_retirement_requires_complete_bound_proof_and_no_hold() -> None:
    g = game()
    proof = RetirementProof(g.binding, "snap-proof", True, RestoreManifest("A", 2, 0, "snap-proof"))
    for state, evidence in (
        (replace(g, save_revision=None), proof),
        (replace(g, held=True), proof),
        (replace(g, state=HostState.UNKNOWN), proof),
        (g, None),
        (g, replace(proof, snapshot_complete=False)),
        (g, replace(proof, snapshot_id="other")),
        (g, replace(proof, binding=replace(g.binding, incarnation=0))),
        (g, replace(proof, manifest=replace(proof.manifest, generation=0))),
        (g, replace(proof, manifest=replace(proof.manifest, game_id="B"))),
    ):
        with pytest.raises(ContractError, match="matching backup"):
            state.begin(
                writer=WRITER, kind=OperationKind.RETIRE, request_id="retire", retirement=evidence
            )
    pending, operation = g.begin(
        writer=WRITER, kind=OperationKind.RETIRE, request_id="retire", retirement=proof
    )
    assert pending.state is HostState.STOPPED
    assert pending.record_uncertain(operation).state is HostState.UNKNOWN
    with pytest.raises(ContractError):
        replace(pending, held=True).finish(operation)
    retired = pending.finish(operation)
    assert retired.state is HostState.ABSENT and retired.binding.incarnation == 2
    with pytest.raises(ContractError):
        retired.finish(operation)


def test_backend_handoff_never_accepts_two_assignment_revisions() -> None:
    legacy = Writer(Backend.LEGACY, 0)
    g = replace(game(), binding=Binding("A", 2, 1, legacy))
    with pytest.raises(ContractError):
        g.begin(writer=legacy, kind=OperationKind.START, request_id="start")
    dedicated = g.reassign(expected=legacy, backend=Backend.DEDICATED)
    assert dedicated.binding.writer == WRITER
    with pytest.raises(ContractError):
        dedicated.reassign(expected=legacy, backend=Backend.DEDICATED)
    pending, start = dedicated.begin(writer=WRITER, kind=OperationKind.START, request_id="start")
    with pytest.raises(ContractError):
        pending.reassign(expected=WRITER, backend=Backend.LEGACY)
    running = pending.finish(start)
    with pytest.raises(ContractError):
        running.reassign(expected=WRITER, backend=Backend.LEGACY)


def test_previous_run_cannot_report_into_a_new_run_on_same_host() -> None:
    g, first = game().begin(writer=WRITER, kind=OperationKind.START, request_id="first")
    g = g.finish(first)
    g, stop = g.begin(writer=WRITER, kind=OperationKind.STOP, request_id="stop")
    g = g.finish(stop, confirmed_saved=True)
    g, second = g.begin(writer=WRITER, kind=OperationKind.START, request_id="second")
    g = g.finish(second)
    assert first.binding == second.binding
    with pytest.raises(ContractError):
        g.heartbeat(first, sequence=100)
    assert g.heartbeat(second, sequence=0).heartbeat_sequence == 0


def test_snapshot_from_before_latest_save_cannot_authorize_retirement() -> None:
    g = game()
    old = RetirementProof(g.binding, "snap-old", True, RestoreManifest("A", 2, 0, "snap-old"))
    g, start = g.begin(writer=WRITER, kind=OperationKind.START, request_id="start")
    g = g.finish(start)
    g, stop = g.begin(writer=WRITER, kind=OperationKind.STOP, request_id="stop")
    g = g.finish(stop, confirmed_saved=True)
    assert g.binding == old.binding
    with pytest.raises(ContractError, match="matching backup"):
        g.begin(writer=WRITER, kind=OperationKind.RETIRE, request_id="retire", retirement=old)
    fresh = RetirementProof(
        g.binding,
        "snap-fresh",
        True,
        RestoreManifest("A", 2, stop.revision, "snap-fresh"),
    )
    pending, op = g.begin(
        writer=WRITER, kind=OperationKind.RETIRE, request_id="retire", retirement=fresh
    )
    assert pending.finish(op).state is HostState.ABSENT
