"""Offline real-port contracts; no SDK import, identity discovery or client setup."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
import re
from typing import Literal, Protocol
from uuid import UUID

NativeStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
STATUSES = frozenset(("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"))


def uuid_value(value):
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise ValueError("Invalid execution identity")
    result = UUID(value)
    if str(result) != value:
        raise ValueError("Invalid execution identity")
    return result


def seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 10:
        raise ValueError("Invalid bounded deadline")
    return float(value)


@dataclass(frozen=True)
class Binding:
    tenant_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_name: str
    namespace: str

    def __post_init__(self):
        if any(type(value) is not UUID for value in (self.tenant_id, self.workflow_id, self.workflow_version_id)):
            raise ValueError("Explicit workflow identities required")
        if (type(self.workflow_name) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", self.workflow_name)
            or type(self.namespace) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.namespace)):
            raise ValueError("Invalid workflow binding")


@dataclass(frozen=True)
class DispatchSpec:
    run_id: UUID
    dispatch_key: str
    input_hash: str
    generation: int
    created_at: datetime

    def __post_init__(self):
        if type(self.run_id) is not UUID:
            raise ValueError("Explicit Run identity required")
        if type(self.dispatch_key) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", self.dispatch_key):
            raise ValueError("Invalid dispatch key")
        if type(self.input_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.input_hash):
            raise ValueError("Invalid input hash")
        if type(self.generation) is not int or self.generation not in (0, 1):
            raise ValueError("Invalid bounded generation")
        if (type(self.created_at) is not datetime or self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None):
            raise ValueError("Aware dispatch timestamp required")

    @property
    def dispatch_identity(self):
        return hashlib.sha256(f"{self.dispatch_key}:g{self.generation}".encode()).hexdigest()

    def metadata(self, binding):
        return {"of_run_id": str(self.run_id), "of_dispatch_key": self.dispatch_key,
                "of_input_hash": self.input_hash, "of_generation": str(self.generation),
                "of_namespace": binding.namespace, "of_workflow_version": str(binding.workflow_version_id)}

    def payload(self):
        return {"run_id": str(self.run_id), "dispatch_key": self.dispatch_key,
                "input_hash": self.input_hash, "generation": self.generation,
                "dispatch_identity": self.dispatch_identity}


@dataclass(frozen=True)
class Policy:
    total_seconds: float = 5.0
    page_size: int = 25
    max_pages: int = 2
    max_executions: int = 2
    sdk_attempts: int = 1

    def __post_init__(self):
        seconds(self.total_seconds)
        for value, bound in ((self.page_size, 50), (self.max_pages, 2), (self.max_executions, 2)):
            if type(value) is not int or not 1 <= value <= bound:
                raise ValueError("Invalid bounded pagination")
        if type(self.sdk_attempts) is not int or self.sdk_attempts != 1:
            raise ValueError("SDK retry multiplication is forbidden")


@dataclass(frozen=True)
class Observation:
    root_id: UUID
    task_ids: tuple[UUID, ...]
    native_status: NativeStatus
    # Broker status is deliberately not an application lifecycle/cleanup verdict.
    domain_completion_proved: Literal[False] = False
    cleanup_proved: Literal[False] = False


@dataclass(frozen=True)
class Result:
    state: Literal["acknowledged", "found", "cancel_requested", "unknown"]
    executions: tuple[Observation, ...] = ()
    candidate_ids: tuple[UUID, ...] = ()
    reason: Literal["verified", "unresolved", "invalid_observation", "deadline", "transport", "lookup_bound"] = "unresolved"
    lookup_complete: bool = False


class Collision(Exception):
    def __init__(self, existing_id):
        super().__init__("Scheduler identity requires verification")
        self.existing_id = uuid_value(existing_id)


class TransportFailure(Exception):
    def __init__(self):
        super().__init__("Scheduler transport unavailable")


class AsyncClient(Protocol):
    async def trigger(self, binding: Binding, spec: DispatchSpec, timeout: float) -> UUID: ...
    async def list_runs(self, binding: Binding, params: list, timeout: float) -> dict: ...
    async def get_run(self, root_id: UUID, timeout: float) -> dict: ...
    async def cancel(self, binding: Binding, root_id: UUID, timeout: float) -> None: ...


def verify_observed_payload(value, spec: DispatchSpec):
    """Require exact JSON shape/types before value equality (bool is not int)."""
    if type(value) is not dict:
        raise ValueError("Invalid observed payload")
    if set(value) == {"input", "overrides"}:
        if value["overrides"] is not None or type(value["input"]) is not dict:
            raise ValueError("Invalid observed payload wrapper")
        value = value["input"]
    expected = spec.payload()
    if (set(value) != set(expected)
        or any(type(value[key]) is not type(expected[key]) for key in expected)
        or value != expected):
        raise ValueError("Observed payload does not match dispatch")
