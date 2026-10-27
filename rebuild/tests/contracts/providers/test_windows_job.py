"""Finite fault-injected ownership scenarios; no DLL/process/endpoint operations."""
import ctypes
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import uuid4

from infra.provider_process.contracts import (
    LaunchSpec, Manifest, NativeFailure, NativeUnavailable, Role,
    SettlementDeadline, Target, WorkDeadline,
)
from infra.provider_process.windows_job import (
    CREATE_FLAGS, KILL_ON_CLOSE, JobOwner, native_api, windows_abi_declarations,
)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class FakeWin32:
    """Writes the pre-registered sinks even when failing after acquisition."""
    def __init__(self):
        self.calls = []
        self.next_handle = 100
        self.fault = None
        self.interrupt = None
        self.advance = {}
        self.clock = None
        self.wait = "signaled"
        self.active = 0
        self.count = 1
        self.probe = (False, 122, 128)
        self.extra_limits = 0
        self.pending = False
        self.duplicate_standard = False
        self.inherit_job = False

    def call(self, name, *args):
        self.calls.append((name, args))
        if name in self.advance:
            self.clock.now = self.advance[name]
        if name == self.interrupt:
            raise KeyboardInterrupt("must never escape into public status")
        if name == self.fault:
            raise NativeFailure("private failure text must not escape")

    def fill(self, output, inherit=False):
        output.value = self.next_handle
        output.inheritable = inherit
        self.next_handle += 1

    def create_job(self, output):
        self.call("before_job")
        self.fill(output, self.inherit_job)
        self.call("job", output.value)
        return True

    def set_limits(self, job, flags):
        self.call("set_limits", job, flags)
        return True

    def get_limits(self, job):
        self.call("get_limits", job)
        return KILL_ON_CLOSE | self.extra_limits

    def prepare_standard_handles(self, outputs):
        for index, slot in enumerate(outputs):
            self.call("before_standard" + str(index))
            self.fill(slot, True)
            self.call("standard" + str(index))
        if self.duplicate_standard:
            outputs[1].value = outputs[0].value
        self.call("standards", tuple(s.value for s in outputs))
        return True

    def attribute_size(self, count):
        self.call("probe", count)
        return self.probe

    def initialize_attributes(self, output, count):
        output.initialized = True
        self.call("initialize", output, count)
        return True

    def update_attribute(self, output, name):
        self.call(name, tuple(output.values[name]))
        return True

    def create_process(self, output, manifest, flags, inherit_handles, use_standard_handles):
        # Assert the native boundary's actual proposed creation contract, not defaults.
        assert flags == 0x08080404
        assert inherit_handles is True and use_standard_handles is True
        assert output.attributes.initialized and output.attributes.allocation is not None
        assert output.attributes.values["JOB_LIST"] == (output.job.value,)
        assert output.job.value not in output.attributes.values["HANDLE_LIST"]
        assert len(output.attributes.values["HANDLE_LIST"]) == 3
        self.call("before_create")
        self.fill(output.process)
        output.process_created = True
        self.call("process_output")
        self.fill(output.thread)
        self.call("thread_output")
        output.pending_io = self.pending  # models ownership only; never actual I/O
        self.call("create", output, manifest)
        return True

    def is_process_in_job(self, process, job):
        self.call("membership", process, job)
        return True

    def resume_thread(self, thread):
        self.call("resume", thread)
        return self.count

    def terminate_job(self, job):
        self.call("terminate", job)
        return True

    def wait_process(self, process, milliseconds):
        assert milliseconds == 0
        self.call("wait", process, milliseconds)
        return self.wait

    def active_processes(self, job):
        self.call("active", job)
        return self.active

    def process_exit_code(self, process):
        self.call("exit", process)
        return 17

    def destroy_attributes(self, output):
        assert output.allocation is not None
        # Value arrays survive through the destruction call, even partial updates.
        if output.values:
            assert "JOB_LIST" in output.values and "HANDLE_LIST" in output.values
        self.call("destroy", output)
        return True

    def close_handle(self, handle):
        self.call("close", handle)
        return True

    def named(self, name):
        return [args for key, args in self.calls if key == name]


class WindowsJobTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.api = FakeWin32()
        self.api.clock = self.clock
        self.manifest = Manifest(r"C:\approved\python.exe",
            r"C:\approved\windows_process_dummy.py", r"C:\approved")
        self.owner = JobOwner(uuid4(), clock=self.clock, work_deadline=30,
                              manifest=self.manifest, api=self.api)

    def launch(self, role=Role.CHILD):
        return self.owner.launch_suspended(LaunchSpec(role, Target.WAIT, WorkDeadline(30)))

    def finish(self, token):
        return self.owner.dispose(token, cutoff=self.owner.cleanup_deadline or 30)

    def test_normal_launch_is_contained_suspended_then_resumed_once(self):
        token = self.launch()
        self.assertEqual(self.owner.status(token).state, "suspended")
        self.assertEqual(self.api.named("resume"), [])
        names = [name for name, _ in self.api.calls]
        self.assertLess(names.index("JOB_LIST"), names.index("create"))
        self.assertLess(names.index("create"), names.index("membership"))
        self.assertLess(names.index("membership"), names.index("destroy"))
        self.owner.resume(token)
        self.owner.resume(token)
        self.assertEqual(len(self.api.named("resume")), 1)
        result = self.finish(token)
        self.assertEqual(result.closed.kind, "process_tree")
        self.assertEqual(result.closed.exit_code, 17)
        self.assertEqual(len(self.api.named("close")), 6)
        self.assertLess([n for n, _ in self.api.calls].index("active"),
                        max(i for i, (n, _) in enumerate(self.api.calls) if n == "close"))

    def test_each_acquisition_failure_keeps_partial_outputs_for_disposal(self):
        for fault in ("job", "set_limits", "get_limits", "standards", "probe",
                      "initialize", "JOB_LIST", "HANDLE_LIST", "create", "membership"):
            with self.subTest(fault=fault):
                self.setUp()
                self.api.fault = fault
                token = self.launch()
                self.assertEqual(self.owner.status(token).failure, "startup_failed")
                self.assertEqual(self.api.named("resume"), [])
                self.api.fault = None
                result = self.finish(token)
                self.assertIsNotNone(result.closed)
                self.assertEqual(len(self.api.named("terminate")), 1)
                closed = [v[0] for v in self.api.named("close")]
                self.assertEqual(len(closed), len(set(closed)))
                if fault in ("create", "membership"):
                    self.assertEqual(result.closed.kind, "process_tree")
                    self.assertEqual(len(closed), 6)
                else:
                    self.assertEqual(result.closed.kind, "never_created")

    def test_failure_before_and_after_individual_handle_outputs(self):
        for fault in ("before_job", "before_standard0", "standard0", "before_standard1",
                      "standard1", "before_standard2", "standard2", "before_create",
                      "process_output", "thread_output"):
            with self.subTest(fault=fault):
                self.setUp()
                self.api.fault = fault
                token = self.launch()
                self.api.fault = None
                self.assertEqual(self.api.named("resume"), [])
                self.assertIsNotNone(self.finish(token).closed)
                # Every individually published sink is either observed/disposed or absent.
                expected = (0 if fault == "before_job" else
                            1 if fault == "before_standard0" else
                            2 if fault in ("standard0", "before_standard1") else
                            3 if fault in ("standard1", "before_standard2") else
                            5 if fault == "process_output" else
                            6 if fault == "thread_output" else 4)
                self.assertEqual(len(self.api.named("close")), expected)

    def test_success_with_missing_handle_retains_uncertainty(self):
        original = self.api.create_process

        def missing_thread(*args):
            original(*args)
            args[0].thread.value = None  # contradictory native-table output
            return True

        self.api.create_process = missing_thread
        token = self.launch()
        self.assertEqual(self.api.named("resume"), [])
        self.assertIsNone(self.finish(token).closed)
        self.assertEqual(self.owner.status(token).state, "unconfirmed")

    def test_clock_failure_still_terminates_without_new_work_or_false_closure(self):
        token = self.launch()
        self.clock.now = float("nan")
        result = self.owner.resume(token)
        self.assertEqual(len(self.api.named("terminate")), 1)
        self.assertEqual(self.api.named("resume"), [])
        self.assertIsNone(result.closed)
        self.assertEqual(self.owner.poll(token).state, "unconfirmed")
        with self.assertRaises(ValueError):
            self.launch(Role.AUTHORITY)

    def test_clock_failure_after_observation_never_returns_closed_evidence(self):
        token = self.launch()
        self.api.advance["active"] = float("nan")
        result = self.finish(token)
        self.assertIsNone(result.closed)
        self.assertEqual(result.state, "unconfirmed")

    def test_control_interruption_preserves_outputs_and_uncertainty(self):
        for stage in ("job", "initialize", "create", "membership", "resume"):
            with self.subTest(stage=stage):
                self.setUp()
                self.api.interrupt = stage
                token = self.launch()
                if stage == "resume":
                    self.owner.resume(token)
                self.api.interrupt = None
                result = self.finish(token)
                self.assertIsNone(result.closed)
                self.assertEqual(result.state, "unconfirmed")
                self.assertNotIn("must never", str(result))
                self.assertGreaterEqual(len(self.api.named("close")), 1)

    def test_probe_expected_failure_and_malformed_results(self):
        for probe in ((True, 0, 128), (False, 5, 128), (False, 122, 0),
                      (False, 122, 65537), (False, 122, True)):
            with self.subTest(probe=probe):
                self.setUp()
                self.api.probe = probe
                token = self.launch()
                self.assertEqual(self.api.named("initialize"), [])
                self.assertIsNotNone(self.finish(token).closed)

    def test_inheritance_or_breakaway_mismatch_prevents_creation(self):
        for setting in ("inherit_job", "extra_limits", "duplicate_standard"):
            with self.subTest(setting=setting):
                self.setUp()
                setattr(self.api, setting, True)
                token = self.launch()
                self.assertEqual(self.api.named("create"), [])
                self.finish(token)
                closed = [v[0] for v in self.api.named("close")]
                self.assertEqual(len(closed), len(set(closed)))

    def test_startup_consumes_work_deadline_without_resume_or_fallback(self):
        self.api.advance["create"] = 30
        token = self.launch()
        self.assertEqual(self.api.named("membership"), [])
        self.assertEqual(self.api.named("resume"), [])
        self.assertEqual(self.owner.cleanup_deadline, 32)
        self.assertEqual(len(self.api.named("create")), 1)
        self.assertIsNotNone(self.finish(token).closed)
        with self.assertRaises(ValueError):
            self.launch(Role.AUTHORITY)

    def test_suspended_cancel_never_resumes_and_stop_is_once_per_job(self):
        token = self.launch()
        self.owner.stop()
        self.owner.stop()
        self.owner.resume(token)
        self.finish(token)
        self.finish(token)
        self.assertEqual(self.api.named("resume"), [])
        self.assertEqual(len(self.api.named("terminate")), 1)

    def test_ambiguous_resume_is_possibly_run_and_never_retried(self):
        for count in (0, 2, 0xffffffff, True):
            with self.subTest(count=count):
                self.setUp()
                token = self.launch()
                self.api.count = count
                result = self.owner.resume(token)
                self.owner.resume(token)
                self.assertTrue(result.possibly_run)
                self.assertEqual(result.failure, "resume_failed")
                self.assertEqual(len(self.api.named("resume")), 1)
                self.assertEqual(len(self.api.named("terminate")), 1)

    def test_root_exit_with_grandchild_is_not_closed(self):
        token = self.launch()
        self.api.active = 1
        self.assertIsNone(self.finish(token).closed)
        self.assertEqual(len(self.api.named("close")), 3)  # startup handles only
        self.api.active = 0
        self.assertIsNotNone(self.owner.poll(token).closed)

    def test_zero_job_but_unsignaled_root_is_not_closed(self):
        token = self.launch()
        self.api.wait = "timeout"
        self.assertIsNone(self.finish(token).closed)
        self.api.wait = "signaled"
        self.assertIsNotNone(self.owner.poll(token).closed)

    def test_failed_observation_stays_uncertain_without_unchanged_retry(self):
        for stage in ("wait", "active", "exit"):
            with self.subTest(stage=stage):
                self.setUp()
                token = self.launch()
                self.api.fault = stage
                self.assertIsNone(self.finish(token).closed)
                attempts = len(self.api.named(stage))
                self.api.fault = None
                self.assertIsNone(self.owner.poll(token).closed)
                self.assertEqual(len(self.api.named(stage)), attempts)

    def test_attribute_disposal_failure_retains_array_storage(self):
        self.api.fault = "destroy"
        token = self.launch()
        attr = self.api.named("initialize")[0][0]
        self.assertIsNotNone(attr.allocation)
        self.assertIn("JOB_LIST", attr.values)
        self.assertEqual(self.api.named("resume"), [])
        self.api.fault = None
        self.assertIsNone(self.finish(token).closed)
        self.assertEqual(len(self.api.named("destroy")), 1)
        self.assertIsNotNone(attr.allocation)

    def test_failed_close_attempts_other_handles_without_retry_or_false_closure(self):
        token = self.launch()
        self.api.fault = "close"
        self.assertIsNone(self.finish(token).closed)
        self.assertEqual(len(self.api.named("close")), 6)
        self.api.fault = None
        self.assertIsNone(self.owner.poll(token).closed)
        self.assertEqual(len(self.api.named("close")), 6)

    def test_termination_failure_remains_uncertain_even_after_observed_exit(self):
        token = self.launch()
        self.api.fault = "terminate"
        self.assertIsNone(self.finish(token).closed)
        self.api.fault = None
        self.assertIsNone(self.finish(token).closed)
        self.assertEqual(len(self.api.named("terminate")), 1)

    def test_pending_io_and_elapsed_cleanup_prevent_closed_evidence(self):
        self.api.pending = True
        token = self.launch()
        self.owner.stop()
        self.assertIsNone(self.finish(token).closed)
        self.clock.now = 2
        self.assertEqual(self.owner.poll(token).state, "unconfirmed")
        self.assertEqual(len(self.api.named("close")), 3)

    def test_stale_tokens_and_duplicate_roles_cannot_select_or_replace_handles(self):
        token = self.launch()
        for foreign in (replace(token), replace(token, generation=uuid4())):
            with self.assertRaises(ValueError):
                self.owner.terminate_once(foreign)
        with self.assertRaises(ValueError):
            self.launch()
        self.finish(token)
        with self.assertRaises(ValueError):
            self.launch()

    def test_separate_jobs_allow_child_close_with_authority_retained(self):
        child, authority = self.launch(), self.launch(Role.AUTHORITY)
        self.assertIsNotNone(self.finish(child).closed)
        self.assertEqual(self.owner.status(authority).state, "suspended")
        self.assertEqual(len(self.api.named("terminate")), 1)
        self.assertNotEqual(self.api.named("membership")[0][1], self.api.named("membership")[1][1])
        self.assertIsNotNone(self.finish(authority).closed)

    def test_settlement_can_start_after_work_expiry_only_with_original_closure(self):
        child = self.launch()
        self.clock.now = 30
        self.owner.stop()
        self.owner.close_uncreated(Role.AUTHORITY)
        d = SettlementDeadline(30, 32, 32)
        spec = LaunchSpec(Role.SETTLEMENT, Target.SETTLEMENT, d)
        with self.assertRaises(ValueError):
            self.owner.launch_suspended(spec)
        self.assertIsNotNone(self.finish(child).closed)
        token = self.owner.launch_suspended(spec)
        self.assertEqual(self.owner.resume(token).state, "running")
        self.clock.now = 31.5
        self.owner.poll(token)
        self.owner.poll(token)
        self.assertEqual(len(self.api.named("terminate")), 2)  # child + settlement
        self.assertIsNotNone(self.owner.status(token).closed)
        with self.assertRaises(ValueError):
            self.launch(Role.AUTHORITY)

    def test_settlement_exact_admission_cutoff_and_half_second_disposal(self):
        self.owner.stop()
        self.owner.close_uncreated(Role.CHILD)
        self.owner.close_uncreated(Role.AUTHORITY)
        self.clock.now = 1.9
        for d in (SettlementDeadline(30, 2, 4), SettlementDeadline(31, 2, 3.9)):
            with self.assertRaises(ValueError):
                self.owner.launch_suspended(LaunchSpec(Role.SETTLEMENT, Target.SETTLEMENT, d))
        token = self.owner.launch_suspended(LaunchSpec(Role.SETTLEMENT, Target.SETTLEMENT,
                                                       SettlementDeadline(30, 2, 3.9)))
        self.api.active = 1
        self.clock.now = 3.4
        self.owner.poll(token)
        self.owner.poll(token)
        self.assertEqual(len(self.api.named("terminate")), 1)
        self.clock.now = 3.9
        self.assertEqual(self.owner.poll(token).state, "unconfirmed")
        with self.assertRaises(ValueError):
            self.owner.dispose(token, cutoff=4)

    def test_uncreated_requires_stop_and_is_not_successful_work(self):
        with self.assertRaises(ValueError):
            self.owner.close_uncreated(Role.CHILD)
        self.owner.stop()
        token = self.owner.close_uncreated(Role.CHILD)
        self.assertEqual(self.owner.status(token).closed.kind, "never_created")
        self.assertEqual(self.api.calls, [])

    def test_manifest_and_deadline_inputs_are_closed_without_loading_paths(self):
        with self.assertRaises(ValueError):
            replace(self.manifest, fixture_script=r"C:\arbitrary.py")
        with self.assertRaises(ValueError):
            replace(self.manifest, environment=(("PROVIDER_KEY", "dummy"),))
        for value in (True, float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                WorkDeadline(value)
        with self.assertRaises(ValueError):
            LaunchSpec(Role.SETTLEMENT, Target.WAIT, WorkDeadline(30))

    def test_native_unavailable_even_with_manifest_and_no_dll_loading_for_declarations(self):
        with self.assertRaises(NativeUnavailable):
            JobOwner(uuid4(), clock=self.clock, work_deadline=30, manifest=self.manifest)
        with self.assertRaises(NativeUnavailable):
            native_api(manifest=self.manifest, operation_release=object())
        with patch.object(ctypes, "CDLL", side_effect=AssertionError("DLL load")), \
                patch.object(ctypes, "WinDLL", side_effect=AssertionError("DLL load"), create=True):
            abi = windows_abi_declarations()
        self.assertIn("CreateProcessW", abi["signatures"])
        self.assertEqual(ctypes.sizeof(abi["dword_type"]), 4)


if __name__ == "__main__":
    unittest.main()
