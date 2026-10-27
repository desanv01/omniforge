"""Injected Windows job ownership policy. No WinDLL, spawn or IPC implementation.

The native factory deliberately refuses all operations in this first slice.
"""
from uuid import uuid4

from .contracts import (Attributes, ClosedEvidence, LaunchSpec, Ledger, Manifest,
                        NativeFailure, NativeUnavailable, Role, SettlementDeadline,
                        Status, Token, Win32Calls, WorkDeadline, time_value)

KILL_ON_CLOSE = 0x2000
CREATE_FLAGS = 0x4 | 0x08000000 | 0x400 | 0x80000  # suspended/no-window/Unicode/extended
ERROR_INSUFFICIENT_BUFFER = 122


def native_api(*, manifest=None, operation_release=None):
    """A manifest never grants execution authority; native runtime is not released."""
    raise NativeUnavailable("native process operations unavailable in injected slice")


def windows_abi_declarations():
    """Lazy source declarations, not bindings or ABI/native acceptance.

    Fixed Win32 DWORD/BOOL widths avoid ctypes.wintypes host-long assumptions.
    This function never loads a DLL. A later separately reviewed native table is
    required to bind functions, supply mutable buffers and implement output sinks.
    """
    import ctypes as c

    DWORD, BOOL, HANDLE = c.c_uint32, c.c_int32, c.c_void_p
    SIZE_T, ULONGLONG = c.c_size_t, c.c_uint64

    class BASIC_LIMIT(c.Structure):
        _fields_ = [("PerProcessUserTimeLimit", c.c_int64), ("PerJobUserTimeLimit", c.c_int64),
                    ("LimitFlags", DWORD), ("MinimumWorkingSetSize", SIZE_T),
                    ("MaximumWorkingSetSize", SIZE_T), ("ActiveProcessLimit", DWORD),
                    ("Affinity", SIZE_T), ("PriorityClass", DWORD), ("SchedulingClass", DWORD)]

    class IO_COUNTERS(c.Structure):
        _fields_ = [(name, ULONGLONG) for name in ("ReadOperationCount", "WriteOperationCount",
                    "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class EXTENDED_LIMIT(c.Structure):
        _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", SIZE_T), ("JobMemoryLimit", SIZE_T),
                    ("PeakProcessMemoryUsed", SIZE_T), ("PeakJobMemoryUsed", SIZE_T)]

    class ACCOUNTING(c.Structure):
        _fields_ = [(name, c.c_int64) for name in ("TotalUserTime", "TotalKernelTime",
                    "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [
                    (name, DWORD) for name in ("TotalPageFaultCount", "TotalProcesses",
                    "ActiveProcesses", "TotalTerminatedProcesses")]

    class STARTUPINFO(c.Structure):
        _fields_ = [("cb", DWORD), ("lpReserved", c.c_wchar_p), ("lpDesktop", c.c_wchar_p),
                    ("lpTitle", c.c_wchar_p)] + [(name, DWORD) for name in (
                    "dwX", "dwY", "dwXSize", "dwYSize", "dwXCountChars", "dwYCountChars",
                    "dwFillAttribute", "dwFlags")] + [("wShowWindow", c.c_uint16),
                    ("cbReserved2", c.c_uint16), ("lpReserved2", c.c_void_p),
                    ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE)]

    class STARTUPINFOEX(c.Structure):
        _fields_ = [("StartupInfo", STARTUPINFO), ("lpAttributeList", c.c_void_p)]

    class PROCESS_INFORMATION(c.Structure):
        _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE), ("dwProcessId", DWORD), ("dwThreadId", DWORD)]

    P = c.c_void_p
    # (restype, argtypes); no function pointer is constructed here.
    signatures = {
        "CreateJobObjectW": (HANDLE, (P, c.c_wchar_p)),
        "SetInformationJobObject": (BOOL, (HANDLE, c.c_int32, P, DWORD)),
        "QueryInformationJobObject": (BOOL, (HANDLE, c.c_int32, P, DWORD, c.POINTER(DWORD))),
        "InitializeProcThreadAttributeList": (BOOL, (P, DWORD, DWORD, c.POINTER(SIZE_T))),
        "UpdateProcThreadAttribute": (BOOL, (P, DWORD, SIZE_T, P, SIZE_T, P, c.POINTER(SIZE_T))),
        "DeleteProcThreadAttributeList": (None, (P,)),
        "CreateProcessW": (BOOL, (c.c_wchar_p, c.POINTER(c.c_wchar), P, P, BOOL, DWORD,
                                   P, c.c_wchar_p, c.POINTER(STARTUPINFOEX), c.POINTER(PROCESS_INFORMATION))),
        "IsProcessInJob": (BOOL, (HANDLE, HANDLE, c.POINTER(BOOL))),
        "ResumeThread": (DWORD, (HANDLE,)),
        "TerminateJobObject": (BOOL, (HANDLE, c.c_uint32)),
        "WaitForSingleObject": (DWORD, (HANDLE, DWORD)),
        "GetExitCodeProcess": (BOOL, (HANDLE, c.POINTER(DWORD))),
        "CloseHandle": (BOOL, (HANDLE,)),
    }
    return {"structures": (BASIC_LIMIT, EXTENDED_LIMIT, ACCOUNTING, STARTUPINFOEX, PROCESS_INFORMATION),
            "signatures": signatures, "handle_type": HANDLE, "dword_type": DWORD}


def valid_handle(slot):
    # No pseudo, NULL, bool or INVALID_HANDLE_VALUE sentinel in the selected table.
    return type(slot.value) is int and 0 < slot.value < (1 << 63)


class JobOwner:
    """Single invocation, one token per role; exact handles never reopened by PID."""

    def __init__(self, operation, *, clock, work_deadline, manifest, api: Win32Calls | None = None):
        from uuid import UUID
        if type(operation) is not UUID or type(manifest) is not Manifest:
            raise ValueError("closed invocation required")
        time_value(work_deadline)
        if api is None:
            raise NativeUnavailable("explicit injected table required")
        self.operation, self.clock, self.work_deadline = operation, clock, work_deadline
        self.manifest, self.api = manifest, api
        self._records, self._roles = {}, {}
        self._last_now, self._clock_broken = 0, False
        self.stop_at = self.cleanup_deadline = None

    def _now(self):
        if self._clock_broken:
            raise NativeFailure()
        try:
            value = self.clock()
            time_value(value)
            if value < self._last_now:
                raise ValueError()
        except BaseException:
            self._clock_broken = True
            raise NativeFailure() from None
        self._last_now = value
        return value

    def _record(self, token):
        # Identity, not equality: a constructed/replayed token cannot select a handle.
        record = self._records.get(id(token))
        if record is None or record.token is not token:
            raise ValueError("unowned token")
        return record

    def _new(self, role, spec):
        if role in self._roles:
            raise ValueError("role already reserved")
        token = Token(self.operation, role, uuid4())
        record = Ledger(token, spec)
        self._records[id(token)], self._roles[role] = record, token
        return record

    @staticmethod
    def _require(value):
        if value is not True:
            raise NativeFailure()

    @staticmethod
    def _contradiction(record):
        record.uncertainty = True
        raise NativeFailure()

    def _startup_allowed(self, record):
        try:
            now = self._now()
        except NativeFailure:
            self.stop()
            raise ValueError("clock unavailable") from None
        if record.token.role is Role.SETTLEMENT:
            return now < record.spec.deadline.cutoff - 0.5
        return self.stop_at is None and now < self.work_deadline

    def _check_start(self, record):
        if not self._startup_allowed(record):
            raise NativeFailure()

    def launch_suspended(self, spec):
        if type(spec) is not LaunchSpec:
            raise ValueError("typed launch required")
        try:
            now = self._now()
        except NativeFailure:
            self.stop()
            raise ValueError("clock unavailable") from None
        if spec.role is Role.SETTLEMENT:
            d = spec.deadline
            if (self.stop_at is None or now >= self.cleanup_deadline
                    or d.work_deadline != self.work_deadline
                    or d.original_cleanup_deadline != self.cleanup_deadline
                    or d.cutoff != min(self.cleanup_deadline + 2, now + 2)
                    or any(role not in self._roles or self.status(self._roles[role]).closed is None
                           for role in (Role.CHILD, Role.AUTHORITY))):
                raise ValueError("settlement admission denied")
        elif self.stop_at is not None or spec.deadline.at != self.work_deadline or now >= self.work_deadline:
            raise ValueError("work admission denied")
        record = self._new(spec.role, spec)  # all output sinks registered before calls
        try:
            self._require(self.api.create_job(record.job))
            if not valid_handle(record.job) or record.job.inheritable:
                self._contradiction(record)
            self._check_start(record)
            self._require(self.api.set_limits(record.job.value, KILL_ON_CLOSE))
            if self.api.get_limits(record.job.value) != KILL_ON_CLOSE:
                raise NativeFailure()
            self._check_start(record)
            self._require(self.api.prepare_standard_handles(record.standards))
            handles = tuple(slot.value for slot in record.standards)
            if (any(not valid_handle(s) or not s.inheritable for s in record.standards)
                    or len(set(handles + (record.job.value,))) != 4):
                self._contradiction(record)
            self._check_start(record)
            probe_ok, error, size = self.api.attribute_size(2)
            if (probe_ok is not False or type(error) is not int or error != ERROR_INSUFFICIENT_BUFFER
                    or type(size) is not int or not 0 < size <= 65536):
                raise NativeFailure()
            attr = record.attributes
            attr.allocation = bytearray(size)
            self._require(self.api.initialize_attributes(attr, 2))
            if not attr.initialized:
                self._contradiction(record)
            attr.values["JOB_LIST"] = (record.job.value,)
            attr.values["HANDLE_LIST"] = handles
            for name in ("JOB_LIST", "HANDLE_LIST"):
                self._check_start(record)
                self._require(self.api.update_attribute(attr, name))
            self._check_start(record)
            self._require(self.api.create_process(record, self.manifest, CREATE_FLAGS, True, True))
            if (not record.process_created or not valid_handle(record.process)
                    or not valid_handle(record.thread) or record.process.inheritable or record.thread.inheritable
                    or len(set(handles + (record.job.value, record.process.value, record.thread.value))) != 6):
                self._contradiction(record)
            self._check_start(record)
            self._require(self.api.is_process_in_job(record.process.value, record.job.value))
            self._destroy_attributes(record)
            if record.uncertainty:
                raise NativeFailure()
            # Temporary parent copies close after CreateProcess/attribute destruction.
            for slot in record.standards:
                self._close_slot(record, slot)
            if record.uncertainty:
                raise NativeFailure()
            self._check_start(record)
            record.state = "suspended"
        except BaseException as exc:
            self._failed(record, exc, "startup_failed")
        return record.token

    def resume(self, token):
        record = self._record(token)
        if record.state != "suspended" or record.resume_attempted:
            return self.status(token)
        try:
            self._check_start(record)
            record.resume_attempted, record.possibly_run = True, True
            count = self.api.resume_thread(record.thread.value)
            if type(count) is not int or count != 1:
                raise NativeFailure()
            self._check_start(record)
            record.state = "running"
        except BaseException as exc:
            self._failed(record, exc, "resume_failed")
        return self.status(token)

    def _failed(self, record, exc, code):
        record.failure = code
        if not isinstance(exc, NativeFailure):
            record.uncertainty = True  # ambiguous interruption/output validation
        if record.token.role is not Role.SETTLEMENT:
            self.stop()
        else:
            self.terminate_once(record.token)

    def stop(self):
        if self.stop_at is None:
            try:
                now = self._now()
            except NativeFailure:
                now = self._last_now
            self.stop_at = min(now, self.work_deadline)
            self.cleanup_deadline = self.stop_at + 2
        for record in tuple(self._records.values()):
            if record.evidence is None:
                if self._clock_broken:
                    record.uncertainty, record.failure = True, "clock_unavailable"
                self.terminate_once(record.token)

    def close_uncreated(self, role):
        if self.stop_at is None or type(role) is not Role or role is Role.SETTLEMENT:
            raise ValueError("stopped original role required")
        record = self._new(role, None)
        record.state = "closed"
        record.evidence = ClosedEvidence(record.token, "never_created", self._now(), None)
        return record.token

    def terminate_once(self, token):
        record = self._record(token)
        if record.evidence is not None or record.terminate_attempted:
            return self.status(token)
        record.terminate_attempted, record.state = True, "closing"
        if valid_handle(record.job):
            try:
                self._require(self.api.terminate_job(record.job.value))
            except BaseException:
                record.uncertainty, record.failure = True, "termination_failed"
        elif record.process_created or record.process.value is not None or record.thread.value is not None:
            record.uncertainty, record.failure = True, "missing_containment"
        return self.status(token)

    def _cutoff(self, record):
        if record.token.role is Role.SETTLEMENT:
            return record.spec.deadline.cutoff
        return self.cleanup_deadline if self.stop_at is not None else self.work_deadline

    def _destroy_attributes(self, record):
        attr = record.attributes
        if attr.initialized and not attr.destroy_attempted:
            attr.destroy_attempted = True
            try:
                self._require(self.api.destroy_attributes(attr))
                attr.destroyed = True
            except BaseException:
                record.uncertainty, record.failure = True, "attribute_disposal_failed"
        if not attr.initialized or attr.destroyed:
            # Pointed arrays remain strongly owned until successful destruction.
            attr.values.clear()
            attr.allocation = None

    def _close_slot(self, record, slot):
        if slot.value is None or slot.close_attempted:
            return
        slot.close_attempted = True
        try:
            if not valid_handle(slot) or slot.value in record.close_attempts:
                raise NativeFailure()
            record.close_attempts.add(slot.value)
            self._require(self.api.close_handle(slot.value))
            slot.closed = True
        except BaseException:
            record.uncertainty, record.failure = True, "handle_disposal_failed"

    def dispose(self, token, *, cutoff):
        record = self._record(token)
        time_value(cutoff)
        if cutoff != self._cutoff(record):
            raise ValueError("exact role cutoff required")
        self.terminate_once(token)
        return self.poll(token)

    def poll(self, token):
        record = self._record(token)
        try:
            return self._poll(token)
        except NativeFailure:
            self.stop()
            record.uncertainty, record.state = True, "unconfirmed"
            return self.status(token)

    def _poll(self, token):
        record = self._record(token)
        if record.evidence is not None:
            return self.status(token)
        try:
            now = self._now()
        except NativeFailure:
            self.stop()
            record.uncertainty, record.state = True, "unconfirmed"
            return self.status(token)
        if record.token.role is not Role.SETTLEMENT and self.stop_at is None and now >= self.work_deadline:
            self.stop()
        if record.token.role is Role.SETTLEMENT and now >= self._cutoff(record) - 0.5:
            self.terminate_once(token)
        if self._now() >= self._cutoff(record):
            record.uncertainty = True
            record.state = "unconfirmed"
            return self.status(token)
        if record.state not in ("closing", "unconfirmed"):
            return self.status(token)
        tree_empty = record.tree_empty_observed
        try:
            if record.observation_broken:
                return self.status(token)
            if tree_empty:
                root_closed, active = True, 0
            else:
                root_closed = not record.process_created and record.process.value is None and record.thread.value is None
            if not tree_empty and record.process_created:
                if not valid_handle(record.process):
                    raise NativeFailure()
                wait = self.api.wait_process(record.process.value, 0)
                if wait not in ("signaled", "timeout"):
                    raise NativeFailure()
                root_closed = wait == "signaled"
            if not tree_empty:
                active = self.api.active_processes(record.job.value) if valid_handle(record.job) else 0
            if type(active) is not int or active < 0:
                raise NativeFailure()
            tree_empty = root_closed and active == 0
            if tree_empty and not record.tree_empty_observed and record.process_created:
                record.exit_code = self.api.process_exit_code(record.process.value)
                if type(record.exit_code) is not int or not 0 <= record.exit_code <= 0xffffffff:
                    raise NativeFailure()
            record.tree_empty_observed = tree_empty
        except BaseException:
            record.uncertainty, record.failure = True, "observation_failed"
            record.observation_broken = True
        if tree_empty and not record.pending_io:
            if self._now() >= self._cutoff(record):
                record.uncertainty = True
            self._destroy_attributes(record)
            for slot in (*record.standards, record.thread, record.process, record.job):
                self._close_slot(record, slot)
            complete = (not record.uncertainty and record.attributes.allocation is None
                        and all(s.value is None or s.closed for s in
                                (*record.standards, record.thread, record.process, record.job)))
            if complete and self._now() < self._cutoff(record):
                record.state = "closed"
                record.evidence = ClosedEvidence(record.token,
                    "process_tree" if record.process_created else "never_created", self._now(), record.exit_code)
        if record.evidence is None and record.uncertainty:
            record.state = "unconfirmed"
        return self.status(token)

    def status(self, token):
        record = self._record(token)
        return Status(record.token, record.state, record.failure, record.possibly_run, record.evidence)
