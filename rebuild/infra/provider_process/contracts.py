"""Closed, dummy-only contracts for the injected process adapter.

No path discovery, configuration loading, credentials or runtime construction.
"""
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from pathlib import PureWindowsPath
from typing import Protocol
from uuid import UUID


class Role(str, Enum):
    CHILD = "child"
    AUTHORITY = "authority"
    SETTLEMENT = "settlement"


class Target(str, Enum):
    WAIT = "dummy_wait"
    TREE = "dummy_tree"
    SETTLEMENT = "dummy_settlement"


def time_value(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("invalid absolute time")


@dataclass(frozen=True)
class Manifest:
    """Trusted caller selection only; possession is NOT native-operation authority."""
    interpreter: str
    fixture_script: str
    directory: str
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        for value in (self.interpreter, self.fixture_script, self.directory):
            if type(value) is not str or not value or "\x00" in value or not PureWindowsPath(value).is_absolute():
                raise ValueError("explicit absolute Windows path required")
        if PureWindowsPath(self.interpreter).name.lower() != "python.exe":
            raise ValueError("unsupported interpreter")
        if PureWindowsPath(self.fixture_script).name != "windows_process_dummy.py":
            raise ValueError("unsupported dummy target")
        if type(self.environment) is not tuple or len(self.environment) > 1:
            raise ValueError("invalid environment")
        for item in self.environment:
            if (type(item) is not tuple or len(item) != 2 or item[0] != "SystemRoot"
                    or type(item[1]) is not str or not item[1] or "\x00" in item[1]):
                raise ValueError("invalid environment")


@dataclass(frozen=True)
class WorkDeadline:
    at: float

    def __post_init__(self):
        time_value(self.at)


@dataclass(frozen=True)
class SettlementDeadline:
    work_deadline: float
    original_cleanup_deadline: float
    cutoff: float

    def __post_init__(self):
        for value in (self.work_deadline, self.original_cleanup_deadline, self.cutoff):
            time_value(value)


@dataclass(frozen=True)
class LaunchSpec:
    role: Role
    target: Target
    deadline: WorkDeadline | SettlementDeadline

    def __post_init__(self):
        if type(self.role) is not Role or type(self.target) is not Target:
            raise ValueError("closed role and target required")
        if self.role is Role.SETTLEMENT:
            if self.target is not Target.SETTLEMENT or type(self.deadline) is not SettlementDeadline:
                raise ValueError("settlement-only specification required")
        elif type(self.deadline) is not WorkDeadline or self.target is Target.SETTLEMENT:
            raise ValueError("work specification required")


@dataclass(frozen=True)
class Token:
    operation: UUID
    role: Role
    generation: UUID


@dataclass
class HandleSlot:
    """Output sink registered BEFORE the injected acquisition is called."""
    value: int | None = None
    inheritable: bool = False
    close_attempted: bool = False
    closed: bool = False


@dataclass
class Attributes:
    allocation: bytearray | None = None
    initialized: bool = False
    destroy_attempted: bool = False
    destroyed: bool = False
    values: dict = field(default_factory=dict)


@dataclass
class Ledger:
    token: Token
    spec: LaunchSpec | None
    job: HandleSlot = field(default_factory=HandleSlot)
    process: HandleSlot = field(default_factory=HandleSlot)
    thread: HandleSlot = field(default_factory=HandleSlot)
    # Three model-only approved null-device standard handles, not pipe endpoints.
    standards: list[HandleSlot] = field(default_factory=lambda: [HandleSlot() for _ in range(3)])
    attributes: Attributes = field(default_factory=Attributes)
    process_created: bool = False
    resume_attempted: bool = False
    possibly_run: bool = False
    terminate_attempted: bool = False
    pending_io: bool = False
    uncertainty: bool = False
    failure: str | None = None
    state: str = "starting"
    exit_code: int | None = None
    tree_empty_observed: bool = False
    observation_broken: bool = False
    close_attempts: set[int] = field(default_factory=set)
    evidence: object = None


@dataclass(frozen=True)
class ClosedEvidence:
    token: Token
    kind: str  # process_tree or never_created; neither asserts successful work
    observed_at: float
    exit_code: int | None


@dataclass(frozen=True)
class Status:
    token: Token
    state: str
    failure: str | None
    possibly_run: bool
    closed: ClosedEvidence | None


class NativeFailure(Exception):
    """Known failed call with all acquired output already recorded in its sink."""


class NativeUnavailable(RuntimeError):
    pass


class Win32Calls(Protocol):
    """Injected table only. Acquisitions write sinks before returning OR raising.

    True is success except the documented expected failed attribute size probe.
    Partial output/initialization is recorded in sinks even on interruption.
    No implementation is allowed to hide a native handle in a local return value.
    """
    def create_job(self, output: HandleSlot) -> bool: ...
    def set_limits(self, job: int, flags: int) -> bool: ...
    def get_limits(self, job: int) -> int: ...
    def prepare_standard_handles(self, outputs: list[HandleSlot]) -> bool: ...
    def attribute_size(self, count: int) -> tuple[bool, int, int]: ...
    def initialize_attributes(self, output: Attributes, count: int) -> bool: ...
    def update_attribute(self, output: Attributes, name: str) -> bool: ...
    def create_process(self, output: Ledger, manifest: Manifest, flags: int,
                       inherit_handles: bool, use_standard_handles: bool) -> bool: ...
    def is_process_in_job(self, process: int, job: int) -> bool: ...
    def resume_thread(self, thread: int) -> int: ...
    def terminate_job(self, job: int) -> bool: ...
    def wait_process(self, process: int, milliseconds: int) -> str: ...
    def active_processes(self, job: int) -> int: ...
    def process_exit_code(self, process: int) -> int: ...
    def destroy_attributes(self, output: Attributes) -> bool: ...
    def close_handle(self, handle: int) -> bool: ...
