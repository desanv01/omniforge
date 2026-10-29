"""Injected, model-ABI ownership channel. No DLL, native factory or JobOwner bridge.

The module root pins unresolved invocations independently of disposable caller views.
All memory handed to an injected backend is private to a pre-registered owner.
"""
import ctypes
from dataclasses import dataclass, field
from enum import IntEnum
from math import isfinite
import struct
from uuid import UUID, uuid4

from .contracts import NativeUnavailable, Role, SettlementDeadline


class Code(IntEnum):
    OK = 0
    FAILED = 1
    INVALID = 2
    BUSY = 3
    STALE = 4
    FULL = 5
    UNKNOWN = 6


class Action(IntEnum):
    JOB = 1
    LIMIT_SET = 2
    LIMIT_GET = 3
    STANDARD = 4
    ATTR_INIT = 5
    ATTR_UPDATE = 6
    PROCESS = 7
    MEMBER = 8
    RESUME = 9
    TERMINATE = 10
    WAIT = 11
    ACTIVE = 12
    EXIT = 13
    ATTR_DELETE = 14
    CLOSE = 15


_ROOTS = {}  # invocation lifetime root; never removed by token GC/finalizers
_ROLE = {Role.CHILD: 1, Role.AUTHORITY: 2, Role.SETTLEMENT: 3}
_REJECTED = {Code.INVALID, Code.BUSY, Code.STALE, Code.FULL}
# INVALID can also be a completed execute() guard failure in a newly stored record.
_UNRECORDED_ONLY = {Code.BUSY, Code.STALE, Code.FULL}
_CLEANUP = {Action.TERMINATE, Action.WAIT, Action.ACTIVE, Action.EXIT, Action.ATTR_DELETE, Action.CLOSE}
_RESULT = struct.Struct("<IIQQI4x")


class ClientError(RuntimeError):
    """Fixed safe code only; no backend/configuration exception text."""


def integer(value, maximum=(1 << 64) - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ClientError("invalid_integer")


def instant(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ClientError("invalid_clock")


def model_descriptor():
    """Fixed little-endian Windows-x64 thin shapes; NOT native ABI certification."""
    return {
        "schema": 1, "evidence": "model_only", "byteorder": "little",
        "calling_convention": "msvc_x64_c", "pointer": 8, "wchar": 2, "dword": 4,
        "slot_capacity": 131072, "slot_alignment": 8, "arena_capacity": 65536,
        "records": 96, "normal": 64, "cleanup": 32,
        "final_observations": {"wait": 8, "active": 8, "exit": 1},
        "codes": {v.name: int(v) for v in Code}, "actions": {v.name: int(v) for v in Action},
        "roles": {v.value: n for v, n in _ROLE.items()},
        "life": {"absent": 0, "open": 1, "closed": 2, "close_failed": 3},
        "attributes": {"absent": 0, "initializing": 1, "ready": 2,
                       "init_failed": 3, "destroying": 4, "destroyed": 5},
        "shapes": {
            "id": {"size": 36, "alignment": 4, "offsets": {"operation": 0, "generation": 16, "role": 32}},
            "launch": {"size": 4100, "alignment": 4, "offsets": {
                "interpreter": 0, "script": 1024, "directory": 2048, "system_root": 3072, "target": 4096}},
            "request": {"size": 32, "alignment": 8, "offsets": {
                "sequence": 0, "action": 8, "index": 12, "parameter": 16, "launch": 24}},
            "result": {"size": 32, "alignment": 8, "offsets": {"code": 0, "error": 4, "raw": 8, "value": 16, "replay": 24}},
            "snapshot": {"size": 184, "alignment": 8, "offsets": {
                "id": 0, "next_sequence": 40, "record_count": 48, "normal_count": 52,
                "cleanup_count": 56, "uncertain": 60, "handles": 64, "life": 112,
                "attr_life": 136, "process_possible": 140, "root_signaled": 144,
                "zero_active_observed": 148, "last": 152}},
        },
    }


def validate_descriptor(value):
    def exact(actual, expected):
        if type(actual) is not type(expected):
            raise ClientError("abi_mismatch")
        if type(expected) is dict:
            if set(actual) != set(expected):
                raise ClientError("abi_mismatch")
            for key in expected:
                exact(actual[key], expected[key])
        elif actual != expected:
            raise ClientError("abi_mismatch")
    exact(value, model_descriptor())


class Memory:
    """Owned aligned exporter; address is not an ownership token."""
    def __init__(self, size):
        integer(size, 131072)
        if not size:
            raise ClientError("empty_memory")
        self.size = size
        self._exporter = (ctypes.c_uint64 * ((size + 7) // 8))()
        self.address = ctypes.addressof(self._exporter)
        if self.address % 8:
            raise ClientError("alignment")

    def write(self, data):
        if type(data) is not bytes or len(data) != self.size:
            raise ClientError("buffer_size")
        # Python buffer slice, not a foreign function call.
        memoryview(self._exporter).cast("B")[:self.size] = data

    def read(self):
        return bytes(memoryview(self._exporter).cast("B")[:self.size])


def disjoint(memories):
    spans = []
    for mem in memories:
        if type(mem) is not Memory:
            raise ClientError("invalid_buffer")
        integer(mem.address)
        end = mem.address + mem.size
        if not mem.address or end >= (1 << 64):
            raise ClientError("buffer_range")
        if any(mem.address < b and a < end for a, b in spans):
            raise ClientError("buffer_overlap")
        spans.append((mem.address, end))


@dataclass(frozen=True)
class Backend:
    descriptor: dict
    init: object
    apply: object
    snapshot: object

    def __post_init__(self):
        validate_descriptor(self.descriptor)
        if not all(callable(v) for v in (self.init, self.apply, self.snapshot)):
            raise ClientError("backend_contract")


@dataclass(frozen=True)
class Launch:
    interpreter: str
    script: str
    directory: str
    system_root: str = ""
    target: int = 1

    def encode(self):
        from pathlib import PureWindowsPath
        integer(self.target, 3)
        if not self.target:
            raise ClientError("launch_target")
        parts = []
        for name in ("interpreter", "script", "directory", "system_root"):
            text = getattr(self, name)
            if type(text) is not str or any(ord(ch) < 32 for ch in text):
                raise ClientError("launch_text")
            if (name != "system_root" or text) and not PureWindowsPath(text).is_absolute():
                raise ClientError("launch_path")
            try:
                encoded = text.encode("utf-16-le")
            except UnicodeError:
                raise ClientError("launch_text") from None
            if len(encoded) > 1022:
                raise ClientError("launch_length")
            parts.append(encoded + bytes(1024 - len(encoded)))
        if PureWindowsPath(self.interpreter).name != "python.exe" or PureWindowsPath(self.script).name != "windows_process_dummy.py":
            raise ClientError("launch_target")
        return b"".join(parts) + struct.pack("<I", self.target)


@dataclass(frozen=True)
class Request:
    action: Action
    index: int = 0
    parameter: int = 0
    launch: Launch | None = None

    def validate(self):
        if type(self.action) is not Action:
            raise ClientError("request_action")
        integer(self.index, 5)
        integer(self.parameter)
        if self.action is Action.PROCESS:
            if self.index or self.parameter != 0x08080404 or type(self.launch) is not Launch:
                raise ClientError("process_request")
            return self.launch.encode()
        if self.launch is not None:
            raise ClientError("unexpected_launch")
        if self.action is Action.LIMIT_SET:
            if self.index or self.parameter != 0x2000:
                raise ClientError("limit_request")
        elif self.parameter:
            raise ClientError("request_parameter")
        if self.action is Action.STANDARD and self.index > 2:
            raise ClientError("request_index")
        if self.action is Action.ATTR_UPDATE and self.index > 1:
            raise ClientError("request_index")
        if self.action not in (Action.STANDARD, Action.ATTR_UPDATE, Action.CLOSE) and self.index:
            raise ClientError("request_index")
        return None


@dataclass(frozen=True)
class Result:
    code: Code
    error: int = 0
    raw: int = 0
    value: int = 0
    replay: int = 0


def result_bytes(value):
    if type(value) is not Result or type(value.code) is not Code:
        raise ClientError("result_type")
    for item, limit in ((value.error, 0xffffffff), (value.raw, (1 << 64)-1),
                        (value.value, (1 << 64)-1), (value.replay, 1)):
        integer(item, limit)
    return _RESULT.pack(value.code, value.error, value.raw, value.value, value.replay)


def decode_result(data):
    try:
        code, error, raw, value, replay = _RESULT.unpack(data)
        answer = Result(Code(code), error, raw, value, replay)
        result_bytes(answer)
        return answer
    except (ValueError, struct.error):
        raise ClientError("result_encoding") from None


@dataclass(frozen=True)
class Snapshot:
    identity: bytes
    next_sequence: int = 1
    record_count: int = 0
    normal_count: int = 0
    cleanup_count: int = 0
    uncertain: int = 0
    handles: tuple = (0, 0, 0, 0, 0, 0)
    life: tuple = (0, 0, 0, 0, 0, 0)
    attr_life: int = 0
    process_possible: int = 0
    root_signaled: int = 0
    zero_active_observed: int = 0
    last: Result = Result(Code.OK)


def snapshot_bytes(value):
    """Bounded model codec, also used by inert backends; never reads opaque slot."""
    if type(value) is not Snapshot or type(value.identity) is not bytes or len(value.identity) != 36:
        raise ClientError("snapshot_type")
    for item, maximum in ((value.next_sequence, 97), (value.record_count, 96),
                          (value.normal_count, 64), (value.cleanup_count, 25),
                          (value.uncertain, 1), (value.attr_life, 5), (value.process_possible, 1),
                          (value.root_signaled, 1), (value.zero_active_observed, 1)):
        integer(item, maximum)
    if (value.next_sequence != value.record_count + 1 or
            value.record_count != value.normal_count + value.cleanup_count):
        raise ClientError("snapshot_counts")
    if type(value.handles) is not tuple or type(value.life) is not tuple or len(value.handles) != 6 or len(value.life) != 6:
        raise ClientError("snapshot_resources")
    for handle, life in zip(value.handles, value.life):
        integer(handle, (1 << 63)-1)
        integer(life, 3)
        if (life == 0) != (handle == 0):
            raise ClientError("snapshot_lifecycle")
    if value.last.replay or value.last.code not in (Code.OK, Code.FAILED, Code.INVALID, Code.UNKNOWN):
        raise ClientError("snapshot_last")
    data = bytearray(184)
    data[:36] = value.identity
    struct.pack_into("<QIIII", data, 40, value.next_sequence, value.record_count,
                     value.normal_count, value.cleanup_count, value.uncertain)
    struct.pack_into("<6Q", data, 64, *value.handles)
    struct.pack_into("<6I4I", data, 112, *value.life, value.attr_life, value.process_possible,
                     value.root_signaled, value.zero_active_observed)
    data[152:] = result_bytes(value.last)
    return bytes(data)


def decode_snapshot(data):
    if type(data) is not bytes or len(data) != 184:
        raise ClientError("snapshot_encoding")
    counts = struct.unpack_from("<QIIII", data, 40)
    life_attrs = struct.unpack_from("<6I4I", data, 112)
    answer = Snapshot(data[:36], *counts, struct.unpack_from("<6Q", data, 64),
                      life_attrs[:6], *life_attrs[6:], decode_result(data[152:]))
    snapshot_bytes(answer)
    return answer


@dataclass(frozen=True)
class Token:
    operation: UUID
    role: Role
    generation: UUID


@dataclass
class Pending:
    command_id: UUID
    request: Request
    sequence: int
    before: Snapshot
    request_buffer: Memory
    result_buffer: Memory
    launch_buffer: Memory | None
    snapshot_buffers: list = field(default_factory=list)
    status: Code | None = None
    returned: bool = False
    in_flight: bool = False
    history_attempted: bool = False
    history_returned: bool = False
    history_status: Code | None = None
    history_buffer: Memory | None = None
    history_view: Snapshot | None = None


@dataclass(frozen=True)
class Outcome:
    command_id: UUID
    recorded: bool
    result: Result | None


class Invocation:
    def __init__(self, invocation_id, operation_id, invocation_generation, *, clock, work_deadline,
                 backend=None, artifact_lease=None):
        if backend is None:
            raise NativeUnavailable("slot backend unavailable")
        if type(backend) is not Backend:
            raise ClientError("backend_contract")
        validate_descriptor(backend.descriptor)
        if type(invocation_id) is not UUID or type(operation_id) is not UUID:
            raise ClientError("invocation_identity")
        integer(invocation_generation)
        if not invocation_generation or invocation_id in _ROOTS or artifact_lease is None:
            raise ClientError("invocation_registration")
        instant(work_deadline)
        self.invocation_id, self.operation_id = invocation_id, operation_id
        self.invocation_generation, self.clock = invocation_generation, clock
        self.work_deadline, self.backend, self.lease = work_deadline, backend, artifact_lease
        self.failure, self.stop_at, self.cleanup_deadline = None, None, None
        self._last_time = 0
        self._sessions = {}
        self._released = False
        self._now()
        _ROOTS[invocation_id] = self  # independent root before any init/backend call

    def _now(self):
        try:
            now = self.clock()
            instant(now)
            if now < self._last_time:
                raise ClientError("clock_regression")
            self._last_time = now
            return now
        except BaseException:
            self._fail("clock")
            raise ClientError("clock") from None

    def _fail(self, reason):
        if self.failure is None:
            self.failure = reason
        if self.stop_at is None:
            self.stop_at = min(self._last_time, self.work_deadline)
            self.cleanup_deadline = self.stop_at + 2

    def stop(self):
        self._now()
        self._fail("stopped")

    def slot(self, role, generation, *, settlement_deadline=None):
        if self._released or type(role) is not Role or type(generation) is not UUID or role in self._sessions:
            raise ClientError("role_registration")
        now = self._now()
        if role is Role.SETTLEMENT:
            d = settlement_deadline
            if (type(d) is not SettlementDeadline or self.stop_at is None or now >= self.cleanup_deadline
                    or d.work_deadline != self.work_deadline or d.original_cleanup_deadline != self.cleanup_deadline
                    or d.cutoff != min(self.cleanup_deadline + 2, now + 2)
                    or any(r not in self._sessions or not self._sessions[r].closed() for r in (Role.CHILD, Role.AUTHORITY))):
                raise ClientError("settlement_admission")
            cutoff = d.cutoff
        else:
            if settlement_deadline is not None or self.failure is not None or now >= self.work_deadline:
                self._fail("deadline")
                raise ClientError("work_admission")
            cutoff = None
        token = Token(self.operation_id, role, generation)
        session = _Session(self, token, cutoff)
        self._sessions[role] = session  # pins all buffers/token before init
        session.initialize()
        return token

    def _session(self, token):
        if self._released or type(token) is not Token:
            raise ClientError("unowned_token")
        session = self._sessions.get(token.role)
        if session is None or session.token is not token:
            raise ClientError("unowned_token")
        return session

    def _buffers(self):
        found = {}
        for s in self._sessions.values():
            memories = [s.storage, s.identity, *s.init_snapshots]
            records = [*s.history, *[v[1] for v in s.completed.values()]]
            if s.pending is not None:
                records.append(s.pending)
            for p in records:
                memories += [p.request_buffer, p.result_buffer, *p.snapshot_buffers]
                memories += [v for v in (p.launch_buffer, p.history_buffer) if v is not None]
            for mem in memories:
                found[id(mem)] = mem
        return list(found.values())

    def issue(self, token, request):
        return self._session(token).issue(request)

    def reconcile(self, token):
        return self._session(token).reconcile()

    def resources_closed(self, token):
        return self._session(token).closed()

    def release(self):
        if self._released or not self._sessions or any(not s.closed() for s in self._sessions.values()):
            raise ClientError("unresolved_ownership")
        result = self.failure  # never relabel an interrupted invocation successful
        del _ROOTS[self.invocation_id]
        self._released = True
        return result


class _Session:
    def __init__(self, root, token, settlement_cutoff):
        self.root, self.token, self.settlement_cutoff = root, token, settlement_cutoff
        self.storage, self.identity = Memory(131072), Memory(36)
        self.identity.write(token.operation.bytes + token.generation.bytes + struct.pack("<I", _ROLE[token.role]))
        disjoint([self.storage, self.identity])
        self.pending, self.latest = None, None
        self.initialized, self.init_pending = False, True
        self.completed = {}
        self.history = []  # retains original pinned records through terminal release
        self.init_snapshots = []
        self.cleanup_started = False
        self.active = False
        self.failed = False

    @staticmethod
    def _status(value):
        if type(value) is not int:
            raise ClientError("return_status")
        try:
            return Code(value)
        except ValueError:
            raise ClientError("return_status") from None

    def _snapshot(self, owner):
        if self.active:
            raise ClientError("pending_action")
        self._observe_allowed()
        out = Memory(184)
        out.write(b"\xA5" * 184)
        disjoint([*self.root._buffers(), out])
        owner.append(out)  # pins BEFORE call, including BUSY/throw
        self.active = True
        try:
            code = self._status(self.root.backend.snapshot(self.storage, self.identity, out))
        finally:
            self.active = False
        self._observe_allowed()
        if code is Code.BUSY:
            return None  # output may contain stale/untouched bytes: NEVER inspect it
        if code is not Code.OK:
            raise ClientError("snapshot_status")
        view = decode_snapshot(out.read())
        if view.identity != self.identity.read():
            raise ClientError("snapshot_identity")
        return view

    def initialize(self):
        try:
            self.active = True
            try:
                code = self._status(self.root.backend.init(self.storage, self.identity))
            finally:
                self.active = False
            if code is not Code.OK:
                raise ClientError("init_status")
            self._recover_init()
        except BaseException:
            self.failed = True
            self.root._fail("initialization")

    def _recover_init(self):
        view = self._snapshot(self.init_snapshots)
        if view is None:
            return None
        if view != Snapshot(self.identity.read()):
            raise ClientError("init_progress")
        self.latest, self.initialized, self.init_pending = view, True, False
        return view

    def _admit(self, action):
        now = self.root._now()
        if self.token.role is Role.SETTLEMENT:
            cutoff = self.settlement_cutoff
            if self.failed and action not in _CLEANUP:
                raise ClientError("settlement_stopped")
            if now >= cutoff or (action not in _CLEANUP and now >= cutoff - 0.5):
                self.root._fail("settlement_deadline")
                raise ClientError("deadline")
        elif self.root.failure is not None:
            if action not in _CLEANUP or now >= self.root.cleanup_deadline:
                raise ClientError("stopped")
        elif now >= self.root.work_deadline:
            self.root._fail("deadline")
            raise ClientError("deadline")

    def _observe_allowed(self):
        now = self.root._now()
        if self.token.role is Role.SETTLEMENT:
            cutoff = self.settlement_cutoff
        else:
            if self.root.failure is None and now >= self.root.work_deadline:
                self.root._fail("deadline")
            cutoff = self.root.work_deadline if self.root.failure is None else self.root.cleanup_deadline
        if now >= cutoff:
            self.root._fail("observation_deadline")
            raise ClientError("deadline")

    def issue(self, request):
        if type(request) is not Request:
            raise ClientError("request_type")
        launch_data = request.validate()
        if self.active or self.pending is not None or self.init_pending or not self.initialized:
            raise ClientError("pending_action")
        if request.action is Action.CLOSE and self.latest.life[request.index] != 1:
            raise ClientError("close_state")
        if request.action in (Action.RESUME, Action.TERMINATE, Action.ATTR_DELETE):
            if any(value[1].request.action is request.action and value[0].recorded for value in self.completed.values()):
                raise ClientError("once_action")
        self._admit(request.action)
        launch = None if launch_data is None else Memory(4100)
        if launch is not None:
            launch.write(launch_data)
        req, result = Memory(32), Memory(32)
        result.write(b"\xA5" * 32)
        req.write(struct.pack("<QIIQQ", self.latest.next_sequence, request.action, request.index,
                              request.parameter, 0 if launch is None else launch.address))
        disjoint([*self.root._buffers(), req, result] + ([] if launch is None else [launch]))
        p = Pending(uuid4(), request, self.latest.next_sequence, self.latest, req, result, launch)
        self.pending = p  # strong ownership before backend entry
        self.active, p.in_flight = True, True
        try:
            self._admit(request.action)
            p.status = self._status(self.root.backend.apply(self.storage, self.identity, req, launch, result))
            p.returned = True
        except BaseException:
            self.failed = True
            self.root._fail("action_interrupted")
        finally:
            self.active, p.in_flight = False, False
        return self.reconcile()

    def _transition(self, p, view):
        before = p.before
        delta = view.record_count - before.record_count
        if delta not in (0, 1) or view.next_sequence != p.sequence + delta:
            raise ClientError("unexpected_progress")
        if delta == 0:
            if view != before:
                raise ClientError("unrecorded_mutation")
            if p.returned and p.status not in _REJECTED:
                raise ClientError("missing_record")
            return False
        if p.returned and p.status in _UNRECORDED_ONLY:
            raise ClientError("foreign_record")
        dedicated = p.request.action in (Action.TERMINATE, Action.ATTR_DELETE, Action.CLOSE)
        final_query = (self.cleanup_started or (before.normal_count >= 64 and not before.process_possible)) and p.request.action in (Action.WAIT, Action.ACTIVE, Action.EXIT)
        cleanup = dedicated or final_query
        if (view.normal_count != before.normal_count + int(not cleanup)
                or view.cleanup_count != before.cleanup_count + int(cleanup)):
            raise ClientError("class_budget")
        acquisition = ({0} if p.request.action is Action.JOB else
                       {p.request.index + 1} if p.request.action is Action.STANDARD else
                       {4, 5} if p.request.action is Action.PROCESS else set())
        for index, (old_life, new_life, old_handle, new_handle) in enumerate(zip(before.life, view.life, before.handles, view.handles)):
            if old_life and (old_handle != new_handle or (old_life in (2, 3) and new_life != old_life)):
                raise ClientError("resource_history")
            if old_life == 0 and new_life != 0 and (index not in acquisition or new_life != 1):
                raise ClientError("resource_acquisition")
            if old_life == 1 and new_life != 1 and (p.request.action is not Action.CLOSE or p.request.index != index or new_life not in (2, 3)):
                raise ClientError("resource_close")
        if view.attr_life != before.attr_life:
            if not ((p.request.action is Action.ATTR_INIT and before.attr_life == 0 and view.attr_life in (1, 2, 3))
                    or (p.request.action is Action.ATTR_DELETE and before.attr_life == 2 and view.attr_life in (4, 5))):
                raise ClientError("attribute_history")
        for name, allowed in (("process_possible", {Action.PROCESS}),
                              ("root_signaled", {Action.WAIT, Action.PROCESS}),
                              ("zero_active_observed", {Action.ACTIVE, Action.PROCESS})):
            if getattr(view, name) != getattr(before, name) and p.request.action not in allowed:
                raise ClientError("observation_history")
        if before.uncertain and not view.uncertain:
            raise ClientError("uncertainty_reset")
        return True

    def _finish(self, p, view, outcome):
        existing = self.completed.get(p.command_id)
        if existing is not None and existing[0] != outcome:
            raise ClientError("completion_conflict")
        if existing is None:
            self.completed[p.command_id] = (outcome, p, view)
            self.history.append(p)
        self.latest = view
        if outcome.recorded and p.request.action is Action.TERMINATE:
            self.cleanup_started = True
        if not outcome.recorded or outcome.result.code is not Code.OK or view.uncertain:
            self.failed = True
            self.root._fail("action_failed")
        self.pending = None
        return outcome

    def reconcile(self):
        if self.active:
            raise ClientError("pending_action")
        try:
            if self.init_pending:
                return self._recover_init()
            p = self.pending
            if p is None:
                return self.latest
            if p.in_flight:
                return None
            view = self._snapshot(p.snapshot_buffers)
            if view is None:
                return None
            recorded = self._transition(p, view)
            if not recorded:
                return self._finish(p, view, Outcome(p.command_id, False, None))
            if p.returned:
                answer = decode_result(p.result_buffer.read())
                if answer.replay or answer.code is not p.status or answer != view.last:
                    raise ClientError("original_result")
            else:
                if p.history_attempted and not p.history_returned:
                    raise ClientError("history_unavailable")
                if not p.history_attempted:
                    self._observe_allowed()
                    p.history_buffer = Memory(32)
                    p.history_buffer.write(b"\xA5" * 32)
                    disjoint(self.root._buffers())
                    p.history_attempted = True
                    p.history_view = view
                    self.active = True
                    try:
                        p.history_status = self._status(self.root.backend.apply(self.storage, self.identity,
                            p.request_buffer, p.launch_buffer, p.history_buffer))
                        p.history_returned = True
                    finally:
                        self.active = False
                if p.history_view != view:
                    raise ClientError("history_progress")
                answer = decode_result(p.history_buffer.read())
                if not answer.replay or answer.code is not p.history_status or Result(answer.code, answer.error, answer.raw, answer.value) != view.last:
                    raise ClientError("history_result")
                after = self._snapshot(p.snapshot_buffers)
                if after is None:
                    return None
                if after != view:
                    raise ClientError("history_progress")
            return self._finish(p, view, Outcome(p.command_id, True, answer))
        except BaseException:
            self.failed = True
            self.root._fail("reconciliation")
            return None

    def closed(self):
        view = self.latest
        if (not self.initialized or self.init_pending or self.pending is not None or self.active
                or view is None or view.uncertain or view.attr_life not in (0, 3, 5)
                or any(life not in (0, 2) for life in view.life)):
            return False
        if view.process_possible and (not view.root_signaled or not view.zero_active_observed):
            return False
        return True  # resource disposition only: never actual return/authority success
