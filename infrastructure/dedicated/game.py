"""Pure, per-Game safety contract. No runtime callers or AWS side effects."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class Backend(StrEnum):
    LEGACY = "legacy"
    DEDICATED = "dedicated"


class HostState(StrEnum):
    ABSENT = "absent"
    STOPPED = "stopped"
    RUNNING = "running"
    UNKNOWN = "unknown"


class OperationKind(StrEnum):
    START = "start"
    STOP = "stop"
    RETIRE = "retire"


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class Writer:
    backend: Backend
    revision: int


@dataclass(frozen=True)
class Binding:
    game_id: str
    generation: int
    incarnation: int
    writer: Writer


@dataclass(frozen=True)
class Operation:
    binding: Binding
    kind: OperationKind
    request_id: str
    revision: int


@dataclass(frozen=True)
class RestoreManifest:
    game_id: str
    generation: int
    save_revision: int
    snapshot_id: str


@dataclass(frozen=True)
class RetirementProof:
    binding: Binding
    snapshot_id: str
    snapshot_complete: bool
    manifest: RestoreManifest


@dataclass(frozen=True)
class DedicatedGame:
    binding: Binding
    state: HostState = HostState.UNKNOWN
    save_revision: int | None = None
    held: bool = False
    active: Operation | None = None
    receipts: tuple[Operation, ...] = ()
    running_operation: Operation | None = None
    heartbeat_sequence: int = -1

    def begin(
        self,
        *,
        writer: Writer,
        kind: OperationKind,
        request_id: str,
        retirement: RetirementProof | None = None,
    ) -> tuple[DedicatedGame, Operation]:
        """Admit only this Game; repeat the same request without a new operation."""
        if writer != self.binding.writer or writer.backend is not Backend.DEDICATED:
            raise ContractError("stale or non-dedicated writer")
        if not request_id.strip():
            raise ContractError("request identity is required")
        for operation in self.receipts:
            if operation.binding.writer == writer and operation.request_id == request_id:
                if operation.kind != kind:
                    raise ContractError("request identity already used for another operation")
                return self, operation
        if self.active is not None:
            raise ContractError("another operation is active for this Game")
        if kind is OperationKind.START and self.state not in {HostState.STOPPED, HostState.ABSENT}:
            raise ContractError("START requires a known stopped or absent host")
        if kind is OperationKind.STOP and self.state is not HostState.RUNNING:
            raise ContractError("STOP requires a known running host")
        if kind is OperationKind.RETIRE:
            self._require_retirement_proof(retirement)
        operation = Operation(self.binding, kind, request_id, len(self.receipts) + 1)
        return (
            replace(
                self,
                active=operation,
                receipts=(*self.receipts, operation),
                running_operation=None,
                heartbeat_sequence=-1,
            ),
            operation,
        )

    def _require_retirement_proof(self, proof: RetirementProof | None) -> None:
        if (
            self.state is not HostState.STOPPED
            or self.save_revision is None
            or self.held
            or proof is None
            or proof.binding != self.binding
            or not proof.snapshot_id.strip()
            or not proof.snapshot_complete
            or proof.manifest
            != RestoreManifest(
                self.binding.game_id,
                self.binding.generation,
                self.save_revision,
                proof.snapshot_id,
            )
        ):
            raise ContractError("retirement requires a saved stopped Game and matching backup")

    def record_uncertain(self, operation: Operation) -> DedicatedGame:
        self._require_active(operation)
        # Preserve active ownership while the result is uncertain; never admit on a guess.
        return replace(self, state=HostState.UNKNOWN, save_revision=None)

    def finish(self, operation: Operation, *, confirmed_saved: bool = False) -> DedicatedGame:
        """Apply a positively verified result. Ambiguous outcomes use record_uncertain."""
        self._require_active(operation)
        match operation.kind:
            case OperationKind.START:
                return replace(
                    self,
                    state=HostState.RUNNING,
                    save_revision=None,
                    active=None,
                    running_operation=operation,
                )
            case OperationKind.STOP:
                if not confirmed_saved:
                    raise ContractError("STOP completion requires confirmed save")
                return replace(
                    self, state=HostState.STOPPED, save_revision=operation.revision, active=None
                )
            case OperationKind.RETIRE:
                if self.held:
                    raise ContractError("a held Game cannot finish retirement")
                return replace(
                    self,
                    state=HostState.ABSENT,
                    save_revision=None,
                    active=None,
                    binding=replace(self.binding, incarnation=self.binding.incarnation + 1),
                )

    def _require_active(self, operation: Operation) -> None:
        if operation.binding != self.binding or operation != self.active:
            raise ContractError("operation is not current for this Game")

    def heartbeat(self, running_operation: Operation, *, sequence: int) -> DedicatedGame:
        """Accept only a monotonic heartbeat for the current successful start."""
        if (
            self.state is not HostState.RUNNING
            or running_operation.binding != self.binding
            or running_operation != self.running_operation
            or sequence <= self.heartbeat_sequence
        ):
            raise ContractError("heartbeat is not current for this Game")
        return replace(self, heartbeat_sequence=sequence)

    def reassign(self, *, expected: Writer, backend: Backend) -> DedicatedGame:
        """A caller must fence and observe the old writer before this storage CAS."""
        if (
            expected != self.binding.writer
            or backend == expected.backend
            or self.active is not None
            or self.state not in {HostState.STOPPED, HostState.ABSENT}
            or (self.state is HostState.STOPPED and self.save_revision is None)
        ):
            raise ContractError("backend reassignment requires a saved quiescent Game")
        return replace(
            self,
            binding=replace(self.binding, writer=Writer(backend, expected.revision + 1)),
            running_operation=None,
            heartbeat_sequence=-1,
        )
