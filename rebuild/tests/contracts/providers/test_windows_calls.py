"""Raw Python functions mutate wrapper-owned pointers; no native functions."""
import ctypes as c
import gc
import unittest
import weakref
from unittest.mock import patch
from uuid import uuid4

from infra.provider_process.contracts import (Attributes, HandleSlot, LaunchSpec,
    Manifest, NativeFailure, NativeUnavailable, Role, SettlementDeadline, Target, WorkDeadline)
from infra.provider_process.windows_job import JobOwner, native_api, windows_abi_declarations
from infra.provider_process.windows_calls import (InjectedCalls, INVALID_HANDLE, JOB_LIST,
    HANDLE_LIST, SECURITY_ATTRIBUTES, DWORD, BOOL, HANDLE, SIZE_T, load_native_calls, target_abi_check)


def pointed(ptr, kind):
    return c.cast(ptr, c.POINTER(kind)).contents


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


class Raw:
    def __init__(self):
        self.error = 0
        self.events = []
        self.overrides = {}
        self.counter = 100
        self.handles = {}
        self.flags = 0x2000
        self.active = 0
        self.wait = 0
        self.resume = 1
        self.member = 1
        self.closed = []
        self.attributes = []
        abi = windows_abi_declarations()
        self.basic, self.extended, self.accounting, self.startup, self.pi = abi["structures"]
        self.symbols = {name: self.function(name) for name in
            (*abi["signatures"], "CreateFileW", "GetHandleInformation")}

    def function(self, name):
        def invoke(*args):
            self.events.append((name, args))
            if name in self.overrides:
                return self.overrides[name](*args)
            return getattr(self, name)(*args)
        return invoke

    def allocate(self, inherit):
        self.counter += 1
        self.handles[self.counter] = inherit
        return self.counter

    def set_error(self, value):
        self.error = value

    def get_error(self):
        self.events.append(("error_snapshot", (self.error,)))
        return self.error

    def CreateJobObjectW(self, security, name):
        assert security is None and name is None
        return self.allocate(0)

    def GetHandleInformation(self, handle, flags):
        pointed(flags, DWORD).value = self.handles[handle]
        self.error = 999  # success stale error must not become a failure
        return 9  # raw nonzero normalizes to exact bool

    def CreateFileW(self, name, access, share, security, disposition, flags, template):
        assert name == "NUL" and access in (0x80000000, 0x40000000)
        assert share == 3 and disposition == 3 and flags == 0x80 and template is None
        sa = pointed(security, SECURITY_ATTRIBUTES)
        assert sa.nLength == c.sizeof(sa) and sa.bInheritHandle == 1 and not sa.lpSecurityDescriptor
        return self.allocate(1)

    def SetInformationJobObject(self, job, kind, data, size):
        assert kind == 9 and size == c.sizeof(self.extended)
        self.flags = pointed(data, self.extended).BasicLimitInformation.LimitFlags
        return 1

    def QueryInformationJobObject(self, job, kind, data, size, used):
        if kind == 9:
            pointed(data, self.extended).BasicLimitInformation.LimitFlags = self.flags
        elif kind == 1:
            pointed(data, self.accounting).ActiveProcesses = self.active
        else:
            raise AssertionError("unexpected information class")
        pointed(used, DWORD).value = size
        return 1

    def InitializeProcThreadAttributeList(self, data, count, flags, size):
        assert count == 2 and flags == 0
        pointed(size, SIZE_T).value = 128
        if data is None:
            self.error = 122
            return 0
        return 1

    def UpdateProcThreadAttribute(self, data, flags, key, values, size, previous, returned):
        assert flags == 0 and previous is None and returned is None
        count = 1 if key == JOB_LIST else 3
        assert key in (JOB_LIST, HANDLE_LIST) and size == count * c.sizeof(HANDLE)
        values = tuple(c.cast(values, c.POINTER(HANDLE))[i] for i in range(count))
        self.attributes.append((key, values))
        return 1

    def DeleteProcThreadAttributeList(self, data):
        assert data is not None

    def CreateProcessW(self, app, command, process_sa, thread_sa, inherit, flags, env, directory, startup, output):
        assert app.endswith("python.exe") and command.value.startswith('"C:\\approved path\\python.exe"')
        assert process_sa is None and thread_sa is None and inherit == 1 and flags == 0x08080404
        assert directory == "C:\\approved path"
        si = pointed(startup, self.startup)
        assert si.StartupInfo.cb == c.sizeof(si) and si.StartupInfo.dwFlags == 0x100
        standards = (si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError)
        assert standards == self.attributes[-1][1] and all(self.handles[v] == 1 for v in standards)
        assert self.attributes[-2][1][0] not in standards
        assert env[len(env) - 1] == env[len(env) - 2] == "\x00"
        pi = pointed(output, self.pi)
        pi.hProcess, pi.hThread = self.allocate(0), self.allocate(0)
        return 1

    def IsProcessInJob(self, process, job, member):
        pointed(member, BOOL).value = self.member
        return 1

    def ResumeThread(self, thread):
        return self.resume

    def TerminateJobObject(self, job, code):
        assert code == 0xD1A6
        return 1

    def WaitForSingleObject(self, process, milliseconds):
        assert milliseconds == 0
        return self.wait

    def GetExitCodeProcess(self, process, code):
        pointed(code, DWORD).value = 23
        return 1

    def CloseHandle(self, handle):
        assert handle not in self.closed
        self.closed.append(handle)
        return 1

    def named(self, name):
        return [args for key, args in self.events if key == name]


class CallsTests(unittest.TestCase):
    def setUp(self):
        self.raw = Raw()
        # Explicit model-only host check seam; does not certify host native ABI.
        self.calls = InjectedCalls(symbols=self.raw.symbols, get_last_error=self.raw.get_error,
            set_last_error=self.raw.set_error, abi_check=lambda: None)
        self.clock = Clock()
        self.manifest = Manifest(r"C:\approved path\python.exe", r"C:\approved path\windows_process_dummy.py",
                                 r"C:\approved path")
        self.owner = JobOwner(uuid4(), clock=self.clock, work_deadline=30,
                              manifest=self.manifest, api=self.calls)

    def launch(self, role=Role.CHILD):
        return self.owner.launch_suspended(LaunchSpec(role, Target.WAIT, WorkDeadline(30)))

    def attributes(self):
        attr = Attributes(allocation=bytearray(128))
        self.calls.initialize_attributes(attr, 2)
        attr.values.update(JOB_LIST=(1,), HANDLE_LIST=(2, 3, 4))
        return attr

    def test_actual_wrapper_composes_with_policy_and_closes_exact_tree(self):
        token = self.launch()
        self.assertEqual(self.owner.status(token).state, "suspended")
        self.assertEqual(self.raw.named("ResumeThread"), [])
        self.assertEqual(self.owner.resume(token).state, "running")
        result = self.owner.dispose(token, cutoff=30)
        self.assertEqual(result.closed.kind, "process_tree")
        self.assertEqual(result.closed.exit_code, 23)
        self.assertEqual(len(self.raw.closed), 6)
        self.assertEqual(len(self.raw.named("TerminateJobObject")), 1)
        self.assertEqual(self.raw.named("error_snapshot"), [(122,)])

    def test_handle_failure_sentinels_and_immediate_error_snapshot(self):
        self.raw.overrides["CreateJobObjectW"] = lambda *args: None
        token = self.launch()
        self.assertIsNotNone(self.owner.dispose(token, cutoff=2).closed)
        self.assertEqual(self.raw.named("GetHandleInformation"), [])
        self.assertEqual(len(self.raw.named("error_snapshot")), 1)
        self.setUp()
        original = self.raw.CreateFileW
        def second_failure(*args):
            if len(self.raw.named("CreateFileW")) == 2:
                self.raw.error = 5
                return INVALID_HANDLE
            return original(*args)
        self.raw.overrides["CreateFileW"] = second_failure
        token = self.launch()
        self.assertEqual(self.calls.last_failure, 5)
        self.assertIsNotNone(self.owner.dispose(token, cutoff=2).closed)
        self.assertEqual(len(self.raw.closed), 2)  # job and first standard only

    def test_standard_handle_partial_failure_each_output_is_retained(self):
        for fail_at in (1, 2, 3):
            with self.subTest(fail_at=fail_at):
                self.setUp()
                original = self.raw.GetHandleInformation
                def fail(handle, ptr):
                    if len(self.raw.named("CreateFileW")) == fail_at:
                        self.raw.error = 6
                        return 0
                    return original(handle, ptr)
                self.raw.overrides["GetHandleInformation"] = fail
                token = self.launch()
                self.assertIsNotNone(self.owner.dispose(token, cutoff=2).closed)
                self.assertEqual(len(self.raw.closed), 1 + fail_at)

    def test_job_inheritance_verification_failure_keeps_job_output(self):
        def fail(handle, ptr):
            self.raw.error = 5
            return 0
        self.raw.overrides["GetHandleInformation"] = fail
        token = self.launch()
        self.assertEqual(len(self.raw.named("CreateFileW")), 0)
        self.assertIsNotNone(self.owner.dispose(token, cutoff=2).closed)
        self.assertEqual(len(self.raw.closed), 1)

    def test_process_partial_outputs_publish_before_failure_or_interrupt(self):
        for mode in ("false_one", "raise_two", "success_missing", "after_return_query"):
            with self.subTest(mode=mode):
                self.setUp()
                def create(*args):
                    pi = pointed(args[-1], self.raw.pi)
                    pi.hProcess = self.raw.allocate(0)
                    if mode in ("raise_two", "after_return_query"):
                        pi.hThread = self.raw.allocate(0)
                    if mode == "raise_two":
                        raise KeyboardInterrupt("private")
                    if mode == "false_one":
                        self.raw.error = 8
                        return 0
                    return 1
                self.raw.overrides["CreateProcessW"] = create
                if mode == "after_return_query":
                    original = self.raw.GetHandleInformation
                    def query(handle, ptr):
                        if len(self.raw.named("CreateProcessW")):
                            raise RuntimeError("private")
                        return original(handle, ptr)
                    self.raw.overrides["GetHandleInformation"] = query
                token = self.launch()
                st = self.calls._storage[id(self.owner._record(token))]
                self.assertIsNotNone(st.owner.process.value)
                self.assertTrue(st.owner.process_created)
                self.assertEqual(self.raw.named("ResumeThread"), [])
                result = self.owner.dispose(token, cutoff=2)
                self.assertIn(st.owner.process.value, self.raw.closed)
                if mode != "false_one":
                    self.assertIsNone(result.closed)

    def test_process_both_outputs_retained_when_error_accessor_raises(self):
        def create(*args):
            pi = pointed(args[-1], self.raw.pi)
            pi.hProcess, pi.hThread = self.raw.allocate(0), self.raw.allocate(0)
            return 0
        self.raw.overrides["CreateProcessW"] = create
        original = self.calls.get_error
        def error():
            if self.raw.named("CreateProcessW"):
                raise RuntimeError("private accessor failure")
            return original()
        self.calls.get_error = error
        token = self.launch()
        result = self.owner.dispose(token, cutoff=2)
        self.assertIsNone(result.closed)
        self.assertEqual(len(self.raw.closed), 6)

    def test_attribute_arrays_remain_pinned_until_delete_completes(self):
        attr = self.attributes()
        self.calls.update_attribute(attr, "JOB_LIST")
        self.calls.update_attribute(attr, "HANDLE_LIST")
        st = self.calls._storage[id(attr)]
        self.assertIs(st.owner, attr)
        self.assertIn("JOB_LIST", st.buffers)
        def delete(ptr):
            self.assertIn("HANDLE_LIST", st.buffers)
            self.assertIn("view", st.buffers)
        self.raw.overrides["DeleteProcThreadAttributeList"] = delete
        self.assertIs(self.calls.destroy_attributes(attr), True)
        self.assertEqual(st.buffers, {})

    def test_duplicate_attribute_attempt_retains_original_without_recorder_references(self):
        for name in ("JOB_LIST", "HANDLE_LIST"):
            for first in ("success", "false", "raise"):
                for second in ("false", "raise"):
                    with self.subTest(name=name, first=first, second=second):
                        self.setUp()
                        attr = self.attributes()
                        attempts = []  # strings only; no byref/array retention
                        def initial(*args):
                            attempts.append("first")
                            if first == "raise":
                                raise RuntimeError("ambiguous update")
                            return 0 if first == "false" else 1
                        self.raw.overrides["UpdateProcThreadAttribute"] = initial
                        if first == "success":
                            self.calls.update_attribute(attr, name)
                        else:
                            with self.assertRaises(NativeFailure if first == "false" else RuntimeError):
                                self.calls.update_attribute(attr, name)
                        storage = self.calls._storage[id(attr)]
                        original = weakref.ref(storage.buffers[name])
                        self.raw.events.clear()  # removes every recorded byref argument
                        gc.collect()
                        self.assertIsNotNone(original())
                        attr.values[name] = (9,) if name == "JOB_LIST" else (9, 10, 11)
                        def duplicate(*args):
                            attempts.append("second")
                            if second == "raise":
                                raise RuntimeError("must not enter")
                            return 0
                        self.raw.overrides["UpdateProcThreadAttribute"] = duplicate
                        with self.assertRaises(NativeFailure):
                            self.calls.update_attribute(attr, name)
                        self.assertEqual(attempts, ["first"])
                        self.assertEqual(self.raw.events, [])
                        self.assertIs(storage.buffers[name], original())
                        def destroy(*args):
                            self.assertIsNotNone(original())
                            self.assertIs(storage.buffers[name], original())
                        self.raw.overrides["DeleteProcThreadAttributeList"] = destroy
                        self.calls.destroy_attributes(attr)
                        self.raw.events.clear()
                        gc.collect()
                        self.assertIsNone(original())  # destruction is the release point

    def test_ambiguous_initialize_and_delete_keep_storage_without_retry(self):
        attr = Attributes(allocation=bytearray(128))
        def interrupted(*args):
            raise KeyboardInterrupt("private")
        self.raw.overrides["InitializeProcThreadAttributeList"] = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.calls.initialize_attributes(attr, 2)
        self.assertTrue(attr.initialized)
        with self.assertRaises(NativeUnavailable):
            self.calls.destroy_attributes(attr)
        self.assertIn("view", self.calls._storage[id(attr)].buffers)
        self.assertEqual(self.raw.named("DeleteProcThreadAttributeList"), [])
        self.setUp()
        attr = self.attributes()
        self.raw.overrides["DeleteProcThreadAttributeList"] = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.calls.destroy_attributes(attr)
        with self.assertRaises(NativeUnavailable):
            self.calls.destroy_attributes(attr)
        self.assertEqual(len(self.raw.named("DeleteProcThreadAttributeList")), 1)
        self.assertIn("view", self.calls._storage[id(attr)].buffers)

    def test_probe_and_update_failure_use_real_pointer_sizes_and_error(self):
        self.assertEqual(self.calls.attribute_size(2), (False, 122, 128))
        attr = self.attributes()
        def failure(*args):
            self.raw.error = 87
            return 0
        self.raw.overrides["UpdateProcThreadAttribute"] = failure
        with self.assertRaises(NativeFailure):
            self.calls.update_attribute(attr, "JOB_LIST")
        self.assertEqual(self.calls.last_failure, 87)
        self.assertIn("JOB_LIST", self.calls._storage[id(attr)].buffers)

    def test_declared_signatures_missing_symbols_and_query_size_failure(self):
        signature = self.calls.signatures["CreateFileW"]
        self.assertIs(signature[0], HANDLE)
        self.assertEqual(len(signature[1]), 7)
        self.assertIsNone(self.calls.signatures["DeleteProcThreadAttributeList"][0])
        table = dict(self.raw.symbols)
        table.pop("CloseHandle")
        with self.assertRaises(ValueError):
            InjectedCalls(symbols=table, get_last_error=self.raw.get_error,
                          set_last_error=self.raw.set_error, abi_check=lambda: None)
        def bad_size(job, kind, data, size, used):
            pointed(used, DWORD).value = size - 1
            return 1
        self.raw.overrides["QueryInformationJobObject"] = bad_size
        with self.assertRaises(ValueError):
            self.calls.get_limits(1)

    def test_failed_initialization_is_distinct_from_ambiguous_initialization(self):
        def failed(data, count, flags, size):
            self.raw.error = 87
            return 0
        self.raw.overrides["InitializeProcThreadAttributeList"] = failed
        attr = Attributes(allocation=bytearray(128))
        with self.assertRaises(NativeFailure):
            self.calls.initialize_attributes(attr, 2)
        self.assertFalse(attr.initialized)
        self.assertEqual(self.calls._storage[id(attr)].state, "failed_initialization")
        self.assertEqual(self.calls.last_failure, 87)

    def test_handle_return_conversion_failure_is_unknown_and_raw_result_retained(self):
        raw_value = object()
        self.raw.overrides["CreateJobObjectW"] = lambda *args: raw_value
        slot = HandleSlot()
        with self.assertRaises(ValueError):
            self.calls.create_job(slot)
        storage = self.calls._storage[id(slot)]
        self.assertIs(storage.buffers["raw_handle"], raw_value)
        self.assertEqual(storage.state, "unknown")
        self.assertIsNone(slot.value)

    def test_mutated_handle_array_refuses_process_before_raw_creation(self):
        original = self.calls.create_process
        def changed(output, *args):
            storage = self.calls._storage[id(output.attributes)]
            storage.buffers["HANDLE_LIST"][0] = output.job.value
            return original(output, *args)
        self.calls.create_process = changed
        token = self.launch()
        self.assertEqual(self.raw.named("CreateProcessW"), [])
        self.assertIsNotNone(self.owner.dispose(token, cutoff=2).closed)

    def test_sentinel_normalization_and_no_wait_extension(self):
        self.raw.member = 0
        self.assertIs(self.calls.is_process_in_job(1, 2), False)
        for value in (0, 1, 2):
            self.raw.resume = value
            self.assertEqual(self.calls.resume_thread(1), value)
        self.raw.resume = 0xffffffff
        with self.assertRaises(NativeFailure):
            self.calls.resume_thread(1)
        for code, expected in ((0, "signaled"), (258, "timeout")):
            self.raw.wait = code
            self.assertEqual(self.calls.wait_process(1, 0), expected)
        for code in (0xffffffff, 128, 11):
            self.raw.wait = code
            with self.assertRaises(NativeFailure):
                self.calls.wait_process(1, 0)
        with self.assertRaises(NativeFailure):
            self.calls.wait_process(1, 1)

    def test_root_and_accounting_observation_and_close_failure_composition(self):
        token = self.launch()
        self.raw.active = 1
        self.assertIsNone(self.owner.dispose(token, cutoff=30).closed)
        self.assertEqual(len(self.raw.closed), 3)
        self.raw.active = 0
        original = self.raw.CloseHandle
        def failure(handle):
            if handle == self.owner._record(token).thread.value:
                return 0
            return original(handle)
        self.raw.overrides["CloseHandle"] = failure
        self.assertIsNone(self.owner.poll(token).closed)
        attempts = len(self.raw.named("CloseHandle"))
        self.assertIsNone(self.owner.poll(token).closed)
        self.assertEqual(len(self.raw.named("CloseHandle")), attempts)

    def test_quoting_environment_and_forbidden_controls(self):
        self.manifest = Manifest(r"C:\approved path\python.exe",
            r'C:\approved path\with"quote\windows_process_dummy.py', r"C:\approved path",
            (("SystemRoot", r"C:\Windows"),))
        self.owner.manifest = self.manifest
        token = self.launch()
        self.assertEqual(self.owner.status(token).state, "suspended")
        args = self.raw.named("CreateProcessW")[0]
        self.assertIn('with\\"quote', args[1].value)
        self.assertEqual("".join(args[6]), "SystemRoot=C:\\Windows\x00\x00")
        self.setUp()
        self.owner.manifest = Manifest(r"C:\approved path\python.exe",
            "C:\\bad\nname\\windows_process_dummy.py", r"C:\approved path")
        token = self.launch()
        self.assertEqual(self.raw.named("CreateProcessW"), [])
        self.assertEqual(self.owner.status(token).failure, "startup_failed")

    def test_delayed_settlement_original_cutoff_rejects_without_refresh(self):
        self.owner.stop()
        self.owner.close_uncreated(Role.CHILD)
        self.owner.close_uncreated(Role.AUTHORITY)
        issued = 2
        self.clock.now = 0.1
        with self.assertRaises(ValueError):
            self.owner.launch_suspended(LaunchSpec(Role.SETTLEMENT, Target.SETTLEMENT,
                SettlementDeadline(30, 2, issued)))
        self.assertEqual(self.raw.events, [])

    def test_no_dll_or_native_factory_and_unsupported_abi_before_acquisition(self):
        for function in (native_api, load_native_calls):
            with self.assertRaises(NativeUnavailable):
                function(manifest=self.manifest, operation_release=object())
        def unsupported():
            raise NativeUnavailable("unsupported")
        with self.assertRaises(NativeUnavailable):
            InjectedCalls(symbols=self.raw.symbols, get_last_error=self.raw.get_error,
                set_last_error=self.raw.set_error, abi_check=unsupported)
        self.assertEqual(self.raw.events, [])
        with patch.object(c, "CDLL", side_effect=AssertionError("load")), \
             patch.object(c, "WinDLL", side_effect=AssertionError("load"), create=True), \
             patch.object(c, "CFUNCTYPE", side_effect=AssertionError("prototype")), \
             patch.object(c, "WINFUNCTYPE", side_effect=AssertionError("prototype"), create=True):
            self.setUp()
            self.assertEqual(self.owner.status(self.launch()).state, "suspended")


if __name__ == "__main__":
    unittest.main()
