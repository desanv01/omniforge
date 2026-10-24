"""Pure fake scheduler port for B2; no real scheduler SDK or network."""
from dataclasses import dataclass
import threading
from typing import Literal, Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DispatchCommand:
    dispatch_key: str
    run_id: UUID
    input_hash: str


@dataclass(frozen=True)
class Execution:
    external_id: str
    state: Literal["accepted", "completed"] = "accepted"


@dataclass(frozen=True)
class Reconciliation:
    state: Literal["found", "absent", "unknown"]
    executions: tuple[Execution, ...] = ()


class AcknowledgementLost(Exception):
    """Submission may have been accepted; do not assume safe automatic retry."""


class SchedulerPort(Protocol):
    def submit(self, command: DispatchCommand) -> Execution: ...
    def lookup(self, command: DispatchCommand) -> Reconciliation: ...


class FakeSchedulerPort:
    """Simulates duplicate execution and lost acknowledgement, not exactly-once."""
    def __init__(self, *, lose_ack=False, unknown_lookup=False, completed=False):
        self.lose_ack = lose_ack
        self.unknown_lookup = unknown_lookup
        self.completed = completed
        self.submissions = 0
        self.lookups = 0
        self._records = {}
        self._lock = threading.Lock()

    def submit(self, command):
        with self._lock:
            self.submissions += 1
            execution = Execution("fake-" + str(uuid4()), "completed" if self.completed else "accepted")
            self._records.setdefault(command.dispatch_key, []).append(execution)
            if self.lose_ack:
                self.lose_ack = False
                raise AcknowledgementLost()
            return execution

    def lookup(self, command):
        with self._lock:
            self.lookups += 1
            if self.unknown_lookup:
                return Reconciliation("unknown")
            executions = tuple(self._records.get(command.dispatch_key, ()))
            return Reconciliation("found" if executions else "absent", executions)
