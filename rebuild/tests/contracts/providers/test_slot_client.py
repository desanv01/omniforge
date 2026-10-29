"""Focused model-only buffer/ownership tests; no DLL, C build or OS handles."""
import ctypes
from dataclasses import replace
import gc
import struct
import unittest
from unittest.mock import patch
from uuid import uuid4
import weakref

from infra.provider_process import slot_client as sc
from infra.provider_process.contracts import NativeUnavailable, Role, SettlementDeadline


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


class Lease:
    pass


class Model:
    """Keeps bytes/values/addresses only, never client Memory/lease references."""
    def __init__(self):
        self.states = {}
        self.calls = []
        self.before = None
        self.after = None
        self.snapshot_hook = None
        self.init_hook = None
        self.close_fails = False
        self.counter = 100
        self.effects = 0
        self.replays = 0
        self.refuse = None
        self.limit_effects = 0

    def init(self, slot, identity):
        self.calls.append(("init", slot.address))
        self.states[slot.address] = {"view": sc.Snapshot(identity.read()), "records": {},
                                     "cleanup": False, "limit_attempt": False}
        if self.init_hook:
            self.init_hook()
        return 0

    def snapshot(self, slot, identity, out):
        self.calls.append(("snapshot", slot.address))
        state = self.states.get(slot.address)
        if state is None:
            return 2
        if self.snapshot_hook:
            status = self.snapshot_hook(state, out)
            if status is not None:
                return status
        out.write(sc.snapshot_bytes(state["view"]))
        return 0

    def apply(self, slot, identity, request, launch, out):
        self.calls.append(("apply", slot.address, request.read(), None if launch is None else launch.read()))
        if self.before:
            self.before()
        state = self.states[slot.address]
        seq, kind, index, parameter, launch_pointer = struct.unpack("<QIIQQ", request.read())
        key = (request.read(), None if launch is None else launch.read())
        if seq in state["records"]:
            prior, answer = state["records"][seq]
            if key != prior:
                return 2
            self.replays += 1
            out.write(sc.result_bytes(replace(answer, replay=1)))
            if self.after:
                self.after(True)
            return int(answer.code)
        if self.refuse is not None:
            return self.refuse  # deliberately leaves all output untouched
        v = state["view"]
        if seq != v.next_sequence or seq == 0:
            return 4
        action = sc.Action(kind)
        if action is sc.Action.PROCESS:
            assert launch is not None and launch_pointer == launch.address and len(launch.read()) == 4100
        else:
            assert launch is None and launch_pointer == 0
        cleanup = action in (sc.Action.TERMINATE, sc.Action.ATTR_DELETE, sc.Action.CLOSE) or (
            (state["cleanup"] or (v.normal_count >= 64 and not v.process_possible)) and
            action in (sc.Action.WAIT, sc.Action.ACTIVE, sc.Action.EXIT))
        if not cleanup and v.normal_count >= 64:
            return 5
        handles, life = list(v.handles), list(v.life)
        change = {}
        code = sc.Code.OK
        if action is sc.Action.LIMIT_SET:
            # Faithful to accepted C execute(): a repeated once guard RECORDS INVALID
            # without entering limits_set again; admission refusals above record nothing.
            if state["limit_attempt"]:
                code = sc.Code.INVALID
            else:
                state["limit_attempt"] = True
                self.limit_effects += 1
        elif action in (sc.Action.JOB, sc.Action.STANDARD, sc.Action.PROCESS):
            indexes = (0,) if action is sc.Action.JOB else (index+1,) if action is sc.Action.STANDARD else (4, 5)
            for i in indexes:
                self.counter += 1
                handles[i], life[i] = self.counter, 1
            if action is sc.Action.PROCESS:
                change.update(process_possible=1, root_signaled=0, zero_active_observed=0)
        elif action is sc.Action.CLOSE:
            assert life[index] == 1
            life[index] = 3 if self.close_fails else 2
            if self.close_fails:
                code = sc.Code.FAILED
                change["uncertain"] = 1
        elif action is sc.Action.ATTR_INIT:
            change["attr_life"] = 2
        elif action is sc.Action.ATTR_DELETE:
            change["attr_life"] = 5
        elif action is sc.Action.WAIT:
            change["root_signaled"] = 1
        elif action is sc.Action.ACTIVE:
            change["zero_active_observed"] = 1
        elif action is sc.Action.TERMINATE:
            state["cleanup"] = True
        answer = sc.Result(code)
        state["view"] = replace(v, next_sequence=seq+1, record_count=v.record_count+1,
            normal_count=v.normal_count + int(not cleanup), cleanup_count=v.cleanup_count+int(cleanup),
            handles=tuple(handles), life=tuple(life), last=answer, **change)
        state["records"][seq] = (key, answer)
        self.effects += 1
        out.write(sc.result_bytes(answer))
        if self.after:
            self.after(False)
        return int(code)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.root_ids = set(sc._ROOTS)
        self.model = Model()
        self.clock = Clock()
        self.lease = Lease()
        self.backend = sc.Backend(sc.model_descriptor(), self.model.init, self.model.apply, self.model.snapshot)
        self.root = sc.Invocation(uuid4(), uuid4(), 1, clock=self.clock, work_deadline=30,
                                  backend=self.backend, artifact_lease=self.lease)
        self.token = self.root.slot(Role.CHILD, uuid4())

    def tearDown(self):
        # TEST-ONLY removal of fake-only invocations. Production has no force-clear.
        for key in set(sc._ROOTS) - self.root_ids:
            del sc._ROOTS[key]

    def issue(self, action, index=0, parameter=0, launch=None):
        return self.root.issue(self.token, sc.Request(action, index, parameter, launch))

    def state(self):
        return self.model.states[self.root._session(self.token).storage.address]

    def close_job(self):
        self.issue(sc.Action.TERMINATE)
        self.issue(sc.Action.ACTIVE)
        return self.issue(sc.Action.CLOSE)

    def test_aligned_opaque_storage_uuid_convention_and_closed_numeric_handle(self):
        session = self.root._session(self.token)
        self.assertEqual(session.storage.address % 8, 0)
        self.assertEqual(session.storage.size, 131072)
        self.assertEqual(session.identity.read()[:16], self.root.operation_id.bytes)
        self.assertEqual(session.identity.read()[16:32], self.token.generation.bytes)
        self.issue(sc.Action.JOB)
        self.assertFalse(self.root.resources_closed(self.token))
        self.close_job()
        self.assertGreater(session.latest.handles[0], 0)  # lifecycle, never numericzero
        self.assertTrue(self.root.resources_closed(self.token))
        self.assertIsNone(self.root.release())

    def test_invocation_registry_pins_slot_lease_and_backend_without_caller_refs(self):
        session = self.root._session(self.token)
        self.issue(sc.Action.JOB)
        root_id = self.root.invocation_id
        references = tuple(weakref.ref(v) for v in (self.root, session.storage, self.lease, self.backend))
        del session
        self.root = self.token = self.lease = self.backend = None
        gc.collect()
        self.assertTrue(all(r() is not None for r in references))
        retained = sc._ROOTS[root_id]
        token = retained._sessions[Role.CHILD].token
        for action in (sc.Action.TERMINATE, sc.Action.ACTIVE, sc.Action.CLOSE):
            retained.issue(token, sc.Request(action))
        retained.release()
        del retained, token
        gc.collect()
        self.assertTrue(all(r() is None for r in references))

    def test_exact_descriptor_types_offsets_enums_and_unknown_fields(self):
        changes = (("pointer", True), ("wchar", 4), ("calling_convention", "stdcall"),
                   ("slot_alignment", 4), ("schema", 2))
        for key, value in changes:
            descriptor = sc.model_descriptor()
            descriptor[key] = value
            with self.subTest(key=key), self.assertRaises(sc.ClientError):
                sc.Backend(descriptor, self.model.init, self.model.apply, self.model.snapshot)
        for mode in ("offset", "extra", "missing", "enum"):
            descriptor = sc.model_descriptor()
            if mode == "offset": descriptor["shapes"]["request"]["offsets"]["launch"] = 16
            if mode == "extra": descriptor["arbitrary_pointer"] = 123
            if mode == "missing": del descriptor["codes"]
            if mode == "enum": descriptor["actions"]["JOB"] = 99
            with self.subTest(mode=mode), self.assertRaises(sc.ClientError):
                sc.validate_descriptor(descriptor)

    def test_native_default_and_forged_tokens_cannot_select_owner(self):
        with self.assertRaises(NativeUnavailable):
            sc.Invocation(uuid4(), uuid4(), 1, clock=self.clock, work_deadline=30)
        with self.assertRaises(sc.ClientError):
            self.root.resources_closed(replace(self.token))
        with self.assertRaises(sc.ClientError):
            self.root.slot(Role.CHILD, uuid4())

    def test_overlaps_malformed_inputs_and_utf16_are_rejected_before_apply(self):
        memory = sc.Memory(16)
        with self.assertRaises(sc.ClientError): sc.disjoint([memory, memory])
        bad = sc.Request(sc.Action.WAIT, parameter=20)
        with self.assertRaises(sc.ClientError): self.root.issue(self.token, bad)
        launch = sc.Launch(r"C:\approved\python.exe", r"C:\approved\windows_process_dummy.py", r"C:\approved")
        encoded = launch.encode()
        self.assertEqual(len(encoded), 4100)
        self.assertEqual(encoded[:2], b"C\0")
        for value in ("x"*512, "C:\\bad\npath", "C:\\bad\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(sc.ClientError):
                replace(launch, directory=value).encode()
        self.assertEqual(self.model.effects, 0)

    def test_lost_original_return_uses_identical_history_once_and_failure_stays_latched(self):
        def lose(replay):
            if not replay:
                raise KeyboardInterrupt("private")
        self.model.after = lose
        result = self.issue(sc.Action.JOB)
        self.assertTrue(result.recorded)
        self.assertEqual(result.result.replay, 1)
        self.assertEqual((self.model.effects, self.model.replays), (1, 1))
        self.assertEqual(self.root.failure, "action_interrupted")
        self.model.after = None
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.STANDARD)
        self.close_job()
        self.assertTrue(self.root.resources_closed(self.token))
        self.assertEqual(self.root.release(), "action_interrupted")

    def test_unknown_call_not_recorded_is_never_reexecuted_and_sequence_can_cleanup(self):
        self.issue(sc.Action.JOB)
        def before(): raise RuntimeError("not entered")
        self.model.before = before
        outcome = self.issue(sc.Action.STANDARD)
        self.assertFalse(outcome.recorded)
        self.assertEqual(self.model.effects, 1)
        self.assertEqual(self.model.replays, 0)
        prior_sequence = self.root._session(self.token).latest.next_sequence
        self.model.before = None
        self.close_job()
        self.assertTrue(self.root.resources_closed(self.token))
        calls = [args for name, *args in self.model.calls if name == "apply"]
        seqs = [struct.unpack_from("<Q", args[1])[0] for args in calls]
        self.assertEqual(seqs[1], prior_sequence)
        self.assertEqual(seqs[2], prior_sequence)  # new cleanup command, old call definitively unrecorded

    def test_busy_stale_closed_output_not_parsed_and_pending_blocks_new_action(self):
        def busy(state, out):
            # Deliberately poisoned/stale buffer cannot claim current closure.
            out.write(sc.snapshot_bytes(sc.Snapshot(self.root._session(self.token).identity.read())))
            return 3
        self.model.snapshot_hook = busy
        self.assertIsNone(self.issue(sc.Action.JOB))
        self.assertFalse(self.root.resources_closed(self.token))
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.STANDARD)
        self.model.snapshot_hook = None
        self.assertTrue(self.root.reconcile(self.token).recorded)
        self.assertEqual(self.model.effects, 1)

    def test_return_status_not_untouched_zero_output_is_authoritative(self):
        self.model.refuse = 5
        result = self.issue(sc.Action.JOB)
        self.assertFalse(result.recorded)
        self.assertEqual(self.model.effects, 0)
        self.assertIsNotNone(self.root.failure)
        self.assertTrue(self.root.resources_closed(self.token))

    def test_progress_identity_class_and_resource_contradictions_preserve_pending(self):
        for mode in ("identity", "progress", "class", "lifecycle"):
            with self.subTest(mode=mode):
                model, clock = Model(), Clock()
                backend = sc.Backend(sc.model_descriptor(), model.init, model.apply, model.snapshot)
                root = sc.Invocation(uuid4(), uuid4(), 1, clock=clock, work_deadline=30,
                                     backend=backend, artifact_lease=Lease())
                token = root.slot(Role.CHILD, uuid4())
                def corrupt(state, out):
                    value = state["view"]
                    if mode == "identity": value = replace(value, identity=bytes(36))
                    if mode == "progress": value = replace(value, next_sequence=3, record_count=2, normal_count=2)
                    if mode == "class": value = replace(value, normal_count=0, cleanup_count=1)
                    if mode == "lifecycle": value = replace(value, life=(2, 0, 0, 0, 0, 0))
                    out.write(sc.snapshot_bytes(value))
                    return 0
                model.snapshot_hook = corrupt
                self.assertIsNone(root.issue(token, sc.Request(sc.Action.JOB)))
                self.assertIsNotNone(root._session(token).pending)
                self.assertFalse(root.resources_closed(token))
                with self.assertRaises(sc.ClientError): root.release()

    def test_interrupted_projection_keeps_exact_buffers_and_all_partial_resources(self):
        launch = sc.Launch(r"C:\approved\python.exe", r"C:\approved\windows_process_dummy.py", r"C:\approved")
        session = self.root._session(self.token)
        original = session._finish
        def partial(*args):
            original(*args)
            # Simulate interruption after some projection bookkeeping, before caller return.
            session.pending = args[0]
            raise KeyboardInterrupt("projection")
        with patch.object(session, "_finish", side_effect=partial):
            self.assertIsNone(self.issue(sc.Action.PROCESS, parameter=0x08080404, launch=launch))
        pending = session.pending
        refs = [weakref.ref(v) for v in (pending.request_buffer, pending.result_buffer, pending.launch_buffer)]
        del pending
        gc.collect()
        self.assertTrue(all(r() is not None for r in refs))
        self.assertFalse(self.root.resources_closed(self.token))
        self.assertTrue(self.root.reconcile(self.token).recorded)
        self.assertEqual(len(session.completed), 1)
        self.assertEqual(session.latest.life[4:], (1, 1))
        self.assertIsNotNone(self.root.failure)

    def test_init_return_loss_recovers_snapshot_without_reinit(self):
        self.root.stop()
        # Independent invocation with an unknown original init return.
        model = Model()
        def lost(): raise KeyboardInterrupt("init")
        model.init_hook = lost
        root = sc.Invocation(uuid4(), uuid4(), 1, clock=self.clock, work_deadline=30,
            backend=sc.Backend(sc.model_descriptor(), model.init, model.apply, model.snapshot), artifact_lease=Lease())
        token = root.slot(Role.CHILD, uuid4())
        self.assertFalse(root.resources_closed(token))
        root.reconcile(token)
        self.assertTrue(root.resources_closed(token))
        self.assertEqual(len([e for e in model.calls if e[0] == "init"]), 1)
        self.assertEqual(root.failure, "initialization")

    def test_history_failure_is_not_retried_with_new_sequence(self):
        def lose(replay): raise KeyboardInterrupt("each return")
        self.model.after = lose
        self.assertIsNone(self.issue(sc.Action.JOB))
        self.assertEqual((self.model.effects, self.model.replays), (1, 1))
        self.model.after = None
        self.assertIsNone(self.root.reconcile(self.token))
        self.assertEqual((self.model.effects, self.model.replays), (1, 1))
        self.assertFalse(self.root.resources_closed(self.token))

    def test_close_failure_is_unresolved_and_no_new_normal_work(self):
        self.issue(sc.Action.JOB)
        self.model.close_fails = True
        result = self.close_job()
        self.assertEqual(result.result.code, sc.Code.FAILED)
        self.assertFalse(self.root.resources_closed(self.token))
        calls = len(self.model.calls)
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.CLOSE)
        self.assertEqual(len(self.model.calls), calls)
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.STANDARD)
        with self.assertRaises(sc.ClientError): self.root.release()

    def test_deadline_bootstrap_consumption_and_no_grace_refresh(self):
        self.issue(sc.Action.JOB)
        self.clock.now = 30
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.STANDARD)
        self.assertEqual(self.root.cleanup_deadline, 32)
        self.clock.now = 32
        before = len(self.model.calls)
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.TERMINATE)
        self.assertEqual(len(self.model.calls), before)
        self.assertFalse(self.root.resources_closed(self.token))

    def test_busy_reconciliation_is_bounded_by_original_cutoff(self):
        self.model.snapshot_hook = lambda state, out: 3
        self.assertIsNone(self.issue(sc.Action.JOB))
        self.clock.now = 32
        calls = len(self.model.calls)
        self.assertIsNone(self.root.reconcile(self.token))
        self.assertEqual(len(self.model.calls), calls)
        self.assertIsNotNone(self.root._session(self.token).pending)

    def test_normal_credit_exhaustion_preserves_cleanup_phase_counts(self):
        self.issue(sc.Action.JOB)
        for _ in range(63): self.issue(sc.Action.LIMIT_GET)
        result = self.issue(sc.Action.STANDARD)
        self.assertFalse(result.recorded)
        self.assertEqual(self.root._session(self.token).latest.normal_count, 64)
        self.close_job()
        self.assertTrue(self.root.resources_closed(self.token))
        self.assertEqual(self.root._session(self.token).latest.cleanup_count, 3)

    def test_settlement_delayed_original_command_is_rejected(self):
        authority = self.root.slot(Role.AUTHORITY, uuid4())
        self.root.stop()
        # Both initialized, known empty slots can be physically closed, not success history.
        self.assertTrue(self.root.resources_closed(authority))
        issued = SettlementDeadline(30, 2, 2)
        self.clock.now = 0.1
        with self.assertRaises(sc.ClientError):
            self.root.slot(Role.SETTLEMENT, uuid4(), settlement_deadline=issued)
        self.assertNotIn(Role.SETTLEMENT, self.root._sessions)

    def test_snapshot_backend_reentrancy_cannot_observe_closed_or_start_another_call(self):
        seen = []
        def reenter(state, out):
            seen.append(self.root.resources_closed(self.token))
            with self.assertRaises(sc.ClientError): self.root.reconcile(self.token)
            with self.assertRaises(sc.ClientError): self.issue(sc.Action.STANDARD)
            return None
        self.model.snapshot_hook = reenter
        self.assertTrue(self.issue(sc.Action.JOB).recorded)
        self.assertEqual(seen, [False])

    def test_successful_history_with_busy_followup_never_runs_history_again(self):
        def lost(replay):
            if not replay: raise KeyboardInterrupt("lost")
        busy_once = []
        def snapshot(state, out):
            if self.model.replays and not busy_once:
                busy_once.append(True)
                return 3
            return None
        self.model.after, self.model.snapshot_hook = lost, snapshot
        self.assertIsNone(self.issue(sc.Action.JOB))
        self.assertEqual((self.model.effects, self.model.replays), (1, 1))
        self.assertTrue(self.root.reconcile(self.token).recorded)
        self.assertEqual((self.model.effects, self.model.replays), (1, 1))
        self.assertIsNotNone(self.root.failure)

    def test_settlement_local_interruption_never_revives_normal_work(self):
        self.root.slot(Role.AUTHORITY, uuid4())
        self.root.stop()
        token = self.root.slot(Role.SETTLEMENT, uuid4(), settlement_deadline=SettlementDeadline(30, 2, 2))
        def lost(replay):
            if not replay: raise KeyboardInterrupt("settlement")
        self.model.after = lost
        self.assertTrue(self.root.issue(token, sc.Request(sc.Action.JOB)).recorded)
        self.model.after = None
        with self.assertRaises(sc.ClientError): self.root.issue(token, sc.Request(sc.Action.STANDARD))
        for action in (sc.Action.TERMINATE, sc.Action.ACTIVE, sc.Action.CLOSE):
            self.root.issue(token, sc.Request(action))
        self.assertTrue(self.root.resources_closed(token))
        self.assertEqual(self.root.failure, "stopped")

    def test_no_library_or_callback_prototype_construction(self):
        with patch.object(ctypes, "CDLL", side_effect=AssertionError("load")), \
             patch.object(ctypes, "WinDLL", side_effect=AssertionError("load"), create=True), \
             patch.object(ctypes, "CFUNCTYPE", side_effect=AssertionError("prototype")), \
             patch.object(ctypes, "WINFUNCTYPE", side_effect=AssertionError("prototype"), create=True):
            self.issue(sc.Action.JOB)
            self.close_job()
            self.assertTrue(self.root.resources_closed(self.token))

    def test_recorded_invalid_outcome_resolves_failure_and_keeps_cleanup_reachable(self):
        self.issue(sc.Action.JOB)
        self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        before = self.root._session(self.token).latest
        result = self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        session = self.root._session(self.token)
        self.assertTrue(result.recorded)
        self.assertEqual(result.result.code, sc.Code.INVALID)
        self.assertEqual(result.result.replay, 0)
        self.assertIsNone(session.pending)
        self.assertEqual(session.latest.record_count, before.record_count + 1)
        self.assertEqual(session.latest.normal_count, before.normal_count + 1)
        self.assertEqual(self.model.limit_effects, 1)
        self.assertIsNotNone(self.root.failure)
        with self.assertRaises(sc.ClientError): self.issue(sc.Action.STANDARD)
        self.close_job()
        self.assertTrue(self.root.resources_closed(self.token))
        self.assertEqual(self.model.limit_effects, 1)
        self.assertIsNotNone(self.root.release())

    def test_recorded_invalid_outcome_lost_return_replays_history_without_effect(self):
        self.issue(sc.Action.JOB)
        self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        def lose(replay):
            if not replay: raise KeyboardInterrupt("original invalid return lost")
        self.model.after = lose
        result = self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        self.assertTrue(result.recorded)
        self.assertEqual(result.result.code, sc.Code.INVALID)
        self.assertEqual(result.result.replay, 1)
        self.assertEqual((self.model.limit_effects, self.model.replays), (1, 1))
        self.assertIsNone(self.root._session(self.token).pending)
        self.assertEqual(self.root.failure, "action_interrupted")
        self.model.after = None
        self.close_job()
        self.assertTrue(self.root.resources_closed(self.token))
        self.assertEqual((self.model.limit_effects, self.model.replays), (1, 1))

    def test_unrecorded_invalid_outcome_does_not_advance_or_reexecute(self):
        self.issue(sc.Action.JOB)
        before = self.root._session(self.token).latest
        self.model.refuse = int(sc.Code.INVALID)
        result = self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        self.assertFalse(result.recorded)
        self.assertIsNone(result.result)
        self.assertIsNone(self.root._session(self.token).pending)
        self.assertEqual(self.root._session(self.token).latest, before)
        self.assertEqual((self.model.limit_effects, self.model.replays), (0, 0))
        self.model.refuse = None
        self.close_job()
        self.assertTrue(self.root.resources_closed(self.token))
        self.assertEqual(self.model.limit_effects, 0)

    def test_recorded_invalid_outcome_requires_exact_result_and_snapshot_match(self):
        self.issue(sc.Action.JOB)
        self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        def corrupt(replay):
            if not replay:
                pending = self.root._session(self.token).pending
                pending.result_buffer.write(sc.result_bytes(sc.Result(sc.Code.OK)))
        self.model.after = corrupt
        self.assertIsNone(self.issue(sc.Action.LIMIT_SET, parameter=0x2000))
        self.assertIsNotNone(self.root._session(self.token).pending)
        self.assertFalse(self.root.resources_closed(self.token))
        self.assertEqual(self.model.limit_effects, 1)

    def test_recorded_invalid_outcome_does_not_admit_impossible_recorded_busy(self):
        self.issue(sc.Action.JOB)
        self.issue(sc.Action.LIMIT_SET, parameter=0x2000)
        original = self.model.apply
        def impossible(*args):
            original(*args)
            return int(sc.Code.BUSY)
        self.backend = sc.Backend(sc.model_descriptor(), self.model.init, impossible, self.model.snapshot)
        self.root.backend = self.backend
        self.assertIsNone(self.issue(sc.Action.LIMIT_SET, parameter=0x2000))
        self.assertIsNotNone(self.root._session(self.token).pending)
        self.assertFalse(self.root.resources_closed(self.token))
        self.assertEqual(self.model.limit_effects, 1)


if __name__ == "__main__":
    unittest.main()
