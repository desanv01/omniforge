"""Selected Win32 marshaling over explicit Python/raw-symbol injection only.

No DLL loader or native function construction. Arbitrary asynchronous acquisition
publication is NOT solved here; native execution remains separately blocked.
"""
import ctypes as c
from dataclasses import dataclass, field
from subprocess import list2cmdline

from .contracts import Manifest, NativeFailure, NativeUnavailable, Target
from .windows_job import CREATE_FLAGS, KILL_ON_CLOSE, windows_abi_declarations

DWORD, BOOL, HANDLE, SIZE_T = c.c_uint32, c.c_int32, c.c_void_p, c.c_size_t
INVALID_HANDLE = (1 << (c.sizeof(HANDLE) * 8)) - 1
JOB_LIST, HANDLE_LIST = 0x2000D, 0x20002


class SECURITY_ATTRIBUTES(c.Structure):
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", c.c_void_p), ("bInheritHandle", BOOL)]


def load_native_calls(*args, **kwargs):
    raise NativeUnavailable("native loading is not released")


def target_abi_check():
    """Necessary host-shape gate, not a verified Windows SDK ABI probe."""
    if c.sizeof(HANDLE) != 8 or c.sizeof(c.c_wchar) != 2 or c.sizeof(DWORD) != 4:
        raise NativeUnavailable("unsupported target ABI")


@dataclass
class Storage:
    owner: object
    buffers: dict = field(default_factory=dict)
    state: str = "registered"


class InjectedCalls:
    """All raw symbols/error accessors are caller-injected; no discovery fallback.

    abi_check is an explicit fake seam for non-Windows model tests. A permissive
    injected check is never native ABI evidence or native-operation authority.
    """
    def __init__(self, *, symbols, get_last_error, set_last_error, abi_check=target_abi_check):
        abi_check()  # before any possible acquisition
        abi = windows_abi_declarations()
        self.basic, self.extended, self.accounting, self.startup, self.process_info = abi["structures"]
        self.signatures = dict(abi["signatures"])
        self.signatures.update({
            "CreateFileW": (HANDLE, (c.c_wchar_p, DWORD, DWORD, c.POINTER(SECURITY_ATTRIBUTES), DWORD, DWORD, HANDLE)),
            "GetHandleInformation": (BOOL, (HANDLE, c.POINTER(DWORD))),
        })
        if type(symbols) is not dict or set(symbols) != set(self.signatures) or any(not callable(v) for v in symbols.values()):
            raise ValueError("closed raw symbol table required")
        if not callable(get_last_error) or not callable(set_last_error):
            raise ValueError("explicit error accessors required")
        self.symbols = dict(symbols)
        self.get_error, self.set_error = get_last_error, set_last_error
        self._storage = {}
        self.last_failure = None

    def _retain(self, owner):
        existing = self._storage.get(id(owner))
        if existing is not None:
            if existing.owner is not owner:
                raise ValueError("storage identity mismatch")
            return existing
        result = Storage(owner)
        self._storage[id(owner)] = result
        return result

    def _raw(self, name, *args):
        # No generic errcheck: acquisition outputs must be published first.
        self.set_error(0)
        result = self.symbols[name](*args)
        return result

    def _error(self):
        value = self.get_error()  # immediately after failed raw result
        self.last_failure = value if type(value) is int and 0 <= value <= 0xffffffff else None
        return self.last_failure

    @staticmethod
    def _handle(value):
        if value is None:
            return None
        if isinstance(value, c.c_void_p):
            return value.value
        if type(value) is not int:
            raise ValueError("invalid raw handle result")
        return value

    def _inheritance(self, handle):
        flags = DWORD()
        result = self._raw("GetHandleInformation", handle, c.byref(flags))
        if not result:
            self._error()
            raise NativeFailure()
        if flags.value & ~1:  # protect-from-close/unknown flags unsupported
            raise NativeFailure()
        return bool(flags.value & 1)

    def create_job(self, output):
        st = self._retain(output)
        st.state = "acquiring"
        try:
            raw = self._raw("CreateJobObjectW", None, None)
            st.buffers["raw_handle"] = raw
            if raw is None or raw == 0:
                self._error()
            output.value = self._handle(raw)
            st.state = "published"
            if not output.value:
                raise NativeFailure()
            output.inheritable = self._inheritance(output.value)
            if output.inheritable:
                raise NativeFailure()
            return True
        except BaseException:
            if st.state == "acquiring":
                st.state = "unknown"
            raise

    def set_limits(self, job, flags):
        if flags != KILL_ON_CLOSE:
            raise NativeFailure()
        value = self.extended()
        value.BasicLimitInformation.LimitFlags = flags
        if not self._raw("SetInformationJobObject", job, 9, c.byref(value), c.sizeof(value)):
            self._error()
            raise NativeFailure()
        return True

    def _query(self, job, kind, value):
        used = DWORD()
        if not self._raw("QueryInformationJobObject", job, kind, c.byref(value), c.sizeof(value), c.byref(used)):
            self._error()
            raise NativeFailure()
        if used.value != c.sizeof(value):
            raise ValueError("contradictory query size")
        return value

    def get_limits(self, job):
        return self._query(job, 9, self.extended()).BasicLimitInformation.LimitFlags

    def active_processes(self, job):
        return self._query(job, 1, self.accounting()).ActiveProcesses

    def prepare_standard_handles(self, outputs):
        if len(outputs) != 3:
            raise NativeFailure()
        for index, output in enumerate(outputs):
            st = self._retain(output)
            sa = SECURITY_ATTRIBUTES(c.sizeof(SECURITY_ATTRIBUTES), None, 1)
            st.buffers["security"] = sa
            st.state = "acquiring"
            try:
                raw = self._raw("CreateFileW", "NUL", 0x80000000 if index == 0 else 0x40000000,
                                3, c.byref(sa), 3, 0x80, None)
                st.buffers["raw_handle"] = raw
                normalized = self._handle(raw)
                if normalized == INVALID_HANDLE:
                    self._error()
                output.value = None if normalized == INVALID_HANDLE else normalized
                st.state = "published"
                if not output.value:
                    raise NativeFailure()
                output.inheritable = self._inheritance(output.value)
                if not output.inheritable:
                    raise NativeFailure()
            except BaseException:
                if st.state == "acquiring":
                    st.state = "unknown"
                raise
        return True

    def attribute_size(self, count):
        if count != 2:
            raise NativeFailure()
        size = SIZE_T()
        result = self._raw("InitializeProcThreadAttributeList", None, count, 0, c.byref(size))
        error = self._error() if not result else 0
        return bool(result), error, size.value

    def initialize_attributes(self, output, count):
        st = self._retain(output)
        if count != 2 or type(output.allocation) is not bytearray or not output.allocation:
            raise NativeFailure()
        view = (c.c_ubyte * len(output.allocation)).from_buffer(output.allocation)
        if c.addressof(view) % c.alignment(c.c_void_p):
            raise NativeUnavailable("unaligned attribute allocation")
        size = SIZE_T(len(output.allocation))
        st.buffers.update(view=view, size=size)
        st.state = "initializing"
        try:
            result = self._raw("InitializeProcThreadAttributeList", c.byref(view), count, 0, c.byref(size))
            if not result:
                self._error()
                st.state = "failed_initialization"
                raise NativeFailure()
            output.initialized = True
            st.state = "initialized"
            return True
        except BaseException:
            if st.state == "initializing":
                # Pin storage, prevent policy treating uncertain initialization as absent.
                output.initialized = True
                st.state = "unknown_initialization"
            raise

    def update_attribute(self, output, name):
        st = self._retain(output)
        if st.state != "initialized" or name not in ("JOB_LIST", "HANDLE_LIST"):
            raise NativeFailure()
        # A failed/raised update may still reference its original value array.
        # Never replace a per-key attempt before completed list destruction.
        if name in st.buffers:
            raise NativeFailure()
        values = output.values[name]
        if (type(values) is not tuple or len(values) != (1 if name == "JOB_LIST" else 3)
                or any(type(v) is not int or not 0 < v < (1 << 63) for v in values)):
            raise NativeFailure()
        array = (HANDLE * len(values))(*values)
        st.buffers[name] = array
        if not self._raw("UpdateProcThreadAttribute", c.byref(st.buffers["view"]), 0,
                         JOB_LIST if name == "JOB_LIST" else HANDLE_LIST,
                         c.byref(array), c.sizeof(array), None, None):
            self._error()
            raise NativeFailure()
        return True

    def destroy_attributes(self, output):
        st = self._retain(output)
        if st.state != "initialized":
            raise NativeUnavailable("attribute initialization or disposal uncertain")
        st.state = "destroying"
        try:
            self._raw("DeleteProcThreadAttributeList", c.byref(st.buffers["view"]))
        except BaseException:
            st.state = "unknown_destruction"
            raise
        st.state = "destroyed"
        st.buffers.clear()  # only after completed destruction
        return True

    def create_process(self, output, manifest, flags, inherit_handles, use_standard_handles):
        if (type(manifest) is not Manifest or flags != CREATE_FLAGS or inherit_handles is not True
                or use_standard_handles is not True or output.spec.target not in tuple(Target)):
            raise NativeFailure()
        attr = self._retain(output.attributes)
        if attr.state != "initialized" or not all(n in attr.buffers for n in ("JOB_LIST", "HANDLE_LIST")):
            raise NativeFailure()
        expected_standards = tuple(s.value for s in output.standards)
        if (tuple(attr.buffers["JOB_LIST"]) != (output.job.value,)
                or tuple(attr.buffers["HANDLE_LIST"]) != expected_standards
                or len(set(expected_standards + (output.job.value,))) != 4):
            raise NativeFailure()
        argv = [manifest.interpreter, "-I", "-S", "-B", manifest.fixture_script, output.spec.target.value]
        for value in argv + [manifest.directory] + [v for pair in manifest.environment for v in pair]:
            if any(ord(ch) < 32 for ch in value):
                raise NativeFailure()
        # Revalidate environment shape, including duplicate/non-path values before call.
        if len(manifest.environment) > 1 or any(k != "SystemRoot" for k, _ in manifest.environment):
            raise NativeFailure()
        st = self._retain(output)
        pi, si = self.process_info(), self.startup()
        si.StartupInfo.cb = c.sizeof(si)
        si.StartupInfo.dwFlags = 0x100
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = tuple(s.value for s in output.standards)
        si.lpAttributeList = c.addressof(attr.buffers["view"])
        command = c.create_unicode_buffer(list2cmdline(argv))
        env_text = "\x00".join(k + "=" + v for k, v in manifest.environment) + "\x00\x00"
        environment = c.create_unicode_buffer(env_text, len(env_text))
        st.buffers.update(process_info=pi, startup=si, command=command, environment=environment)
        st.state = "creating"
        result = None
        try:
            try:
                result = self._raw("CreateProcessW", manifest.interpreter, command, None, None, 1,
                    flags, environment, manifest.directory, c.byref(si), c.byref(pi))
                if not result:
                    self._error()
            finally:
                # Both outputs independently published before validation/follow-up.
                output.process.value = pi.hProcess
                output.thread.value = pi.hThread
                if result or pi.hProcess or pi.hThread:
                    output.process_created = True
            st.state = "published"
            if not result:
                raise NativeFailure()
            if not pi.hProcess or not pi.hThread:
                raise ValueError("contradictory process output")
            output.process.inheritable = self._inheritance(pi.hProcess)
            output.thread.inheritable = self._inheritance(pi.hThread)
            if output.process.inheritable or output.thread.inheritable:
                raise NativeFailure()
            return True
        except BaseException:
            if st.state == "creating":
                st.state = "unknown_creation"
            raise

    def is_process_in_job(self, process, job):
        member = BOOL()
        if not self._raw("IsProcessInJob", process, job, c.byref(member)):
            self._error()
            raise NativeFailure()
        return bool(member.value)

    def resume_thread(self, thread):
        result = self._raw("ResumeThread", thread)
        if type(result) is not int or result == 0xffffffff:
            self._error()
            raise NativeFailure()
        return result

    def terminate_job(self, job):
        if not self._raw("TerminateJobObject", job, 0xD1A6):
            self._error()
            raise NativeFailure()
        return True

    def wait_process(self, process, milliseconds):
        if type(milliseconds) is not int or milliseconds != 0:
            raise NativeFailure()
        result = self._raw("WaitForSingleObject", process, 0)
        if result == 0:
            return "signaled"
        if result == 258:
            return "timeout"
        if result == 0xffffffff:
            self._error()
        raise NativeFailure()

    def process_exit_code(self, process):
        code = DWORD()
        if not self._raw("GetExitCodeProcess", process, c.byref(code)):
            self._error()
            raise NativeFailure()
        return code.value

    def close_handle(self, handle):
        if not self._raw("CloseHandle", handle):
            self._error()
            raise NativeFailure()
        return True
