"""Injected-only enrollment checks: no terminal, OS store, database or network."""

from dataclasses import FrozenInstanceError, replace
import secrets
import traceback
import unittest
from unittest.mock import patch
from uuid import uuid4

from adapters.secrets.enrollment import (
    EnrollmentBinding, EnrollmentError, EnrollmentReceipt, EnrollmentRequest,
    Reservation, enroll_new,
)
from adapters.secrets.store import CredentialRef, SecretStoreError, SecretValue


class FakeStore:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.failure = None

    def put(self, ref, value):
        self.events.append("put")
        self.calls.append((ref, value))
        if self.failure is not None:
            raise self.failure

    def get(self, *args):
        raise AssertionError("Credential reads are forbidden")

    def delete(self, *args):
        raise AssertionError("Credential deletion is forbidden")


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.request = EnrollmentRequest(uuid4(), uuid4(), uuid4(), uuid4(), 2)
        self.events = []
        self.store = FakeStore(self.events)
        self.value = SecretValue(secrets.token_bytes(32))
        self.binding = None

    def tearDown(self):
        self.value.clear()

    def reserve(self, candidate):
        self.events.append("reserve")
        self.binding = candidate
        return Reservation("ready", binding=candidate)

    def hidden_input(self):
        self.events.append("input")
        return self.value

    def authorize(self, binding):
        self.events.append("authorize")
        return binding

    def invoke(self, **overrides):
        arguments = dict(request=self.request, reserve=self.reserve,
                         hidden_input=self.hidden_input, authorize_put=self.authorize,
                         store=self.store)
        arguments.update(overrides)
        return enroll_new(**arguments)

    def assert_cleared(self):
        with self.assertRaises(SecretStoreError):
            self.value.reveal()

    def assert_denied(self, **arguments):
        with self.assertRaises(EnrollmentError) as outcome:
            self.invoke(**arguments)
        self.assertEqual(outcome.exception.code, "denied")
        self.assertEqual(self.store.calls, [])

    def test_reserve_input_fresh_authority_single_put_and_clear(self):
        result = self.invoke()
        self.assertIs(result, self.binding)
        self.assertEqual(self.events, ["reserve", "input", "authorize", "put"])
        self.assertEqual(len(self.store.calls), 1)
        self.assertEqual(self.store.calls[0][0], result.credential_ref)
        self.assertTrue(result.credential_ref.value.startswith("wincred:omniforge:v1:"))
        self.assertEqual(result.expected_revision, 2)
        self.assertTrue(result.credential_ref.value not in repr(result))
        self.assert_cleared()
        with self.assertRaises(FrozenInstanceError):
            result.profile_id = uuid4()

    def test_settled_replay_returns_only_receipt_without_input_authorize_or_put(self):
        receipt = EnrollmentReceipt(self.request.operation_id, self.request.principal_id,
                                    self.request.case_id, self.request.profile_id, 2, 3)
        def settled(candidate):
            self.events.append("reserve")
            return Reservation("settled", receipt=receipt)
        result = self.invoke(reserve=settled)
        self.assertIs(result, receipt)
        self.assertEqual(self.events, ["reserve"])
        self.assertFalse(hasattr(result, "credential_ref"))
        self.assertEqual(self.store.calls, [])

    def test_pending_or_unresolved_requires_recovery_without_input_or_put(self):
        def blocked(candidate):
            self.events.append("reserve")
            return Reservation("blocked")
        with self.assertRaises(EnrollmentError) as outcome:
            self.invoke(reserve=blocked)
        self.assertEqual(outcome.exception.code, "recovery_required")
        self.assertEqual(self.events, ["reserve"])
        self.assertEqual(self.store.calls, [])

    def test_revoked_during_input_is_rechecked_zero_write_and_clear(self):
        revoked = []
        def input_then_revoke():
            self.events.append("input")
            revoked.append(True)
            return self.value
        def authorize(binding):
            self.events.append("authorize")
            if revoked:
                raise PermissionError("synthetic revoked authority")
            return binding
        self.assert_denied(hidden_input=input_then_revoke, authorize_put=authorize)
        self.assertEqual(self.events, ["reserve", "input", "authorize"])
        self.assert_cleared()

    def test_changed_reservation_tuple_denied_before_input(self):
        changes = {"operation_id": uuid4(), "principal_id": uuid4(), "case_id": uuid4(),
                   "profile_id": uuid4(), "expected_revision": 3,
                   "credential_ref": CredentialRef.new()}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.events.clear()
                def reserve(candidate):
                    self.events.append("reserve")
                    return Reservation("ready", binding=replace(candidate, **{field: value}))
                self.assert_denied(reserve=reserve)
                self.assertEqual(self.events, ["reserve"])

    def test_changed_authorized_tuple_or_untyped_permission_denied_and_clear(self):
        changes = {"operation_id": uuid4(), "principal_id": uuid4(), "case_id": uuid4(),
                   "profile_id": uuid4(), "expected_revision": 3,
                   "credential_ref": CredentialRef.new()}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.value = SecretValue(secrets.token_bytes(32))
                self.assert_denied(authorize_put=lambda binding: replace(binding, **{field: value}))
                self.assert_cleared()
        for result in (None, True, False, self.request):
            self.value = SecretValue(secrets.token_bytes(32))
            self.assert_denied(authorize_put=lambda binding: result)
            self.assert_cleared()

    def test_mutation_bypassing_frozen_binding_during_input_is_detected(self):
        def hidden():
            object.__setattr__(self.binding, "principal_id", uuid4())
            return self.value
        self.assert_denied(hidden_input=hidden)
        self.assert_cleared()

    def test_mutation_during_authorize_is_detected_from_primitive_snapshot(self):
        def authorize(binding):
            object.__setattr__(binding.credential_ref, "value", CredentialRef.new().value)
            return binding
        self.assert_denied(authorize_put=authorize)
        self.assert_cleared()

    def test_request_mutation_during_input_is_denied(self):
        def hidden():
            object.__setattr__(self.request, "case_id", uuid4())
            return self.value
        self.assert_denied(hidden_input=hidden)
        self.assert_cleared()

    def clone_reservation(self, candidate):
        self.events.append("reserve")
        self.original_ref = candidate.credential_ref
        self.binding = replace(candidate, credential_ref=CredentialRef(candidate.credential_ref.value))
        self.assertIsNot(self.binding.credential_ref, self.original_ref)
        return Reservation("ready", binding=self.binding)

    def test_cloned_reservation_original_ref_mutation_during_input_is_denied(self):
        def hidden():
            self.events.append("input")
            object.__setattr__(self.original_ref, "value", CredentialRef.new().value)
            return self.value
        self.assert_denied(reserve=self.clone_reservation, hidden_input=hidden)
        self.assertEqual(self.events, ["reserve", "input"])
        self.assert_cleared()

    def test_cloned_reservation_original_ref_mutation_during_authorize_is_denied(self):
        def authorize(binding):
            self.events.append("authorize")
            object.__setattr__(self.original_ref, "value", CredentialRef.new().value)
            return binding
        self.assert_denied(reserve=self.clone_reservation, authorize_put=authorize)
        self.assertEqual(self.events, ["reserve", "input", "authorize"])
        self.assert_cleared()

    def test_put_exception_is_uncertain_once_cleared_no_raw_error(self):
        marker = self.value.reveal().hex()
        self.store.failure = RuntimeError(marker)
        try:
            self.invoke()
        except EnrollmentError as error:
            self.assertEqual(error.code, "uncertain")
            display = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            self.assertTrue(marker not in display)
            self.assertTrue(error.__suppress_context__)
        else:
            self.fail("Expected uncertainty")
        self.assertEqual(len(self.store.calls), 1)
        self.assert_cleared()

    def test_put_denial_or_interrupt_still_uncertain(self):
        for error in (EnrollmentError("denied"), KeyboardInterrupt()):
            self.value = SecretValue(secrets.token_bytes(32))
            self.store.calls.clear()
            self.store.failure = error
            with self.assertRaises(EnrollmentError) as outcome:
                self.invoke()
            self.assertEqual(outcome.exception.code, "uncertain")
            self.assertEqual(len(self.store.calls), 1)
            self.assert_cleared()

    def test_reserve_failure_never_prompts(self):
        def reserve(candidate):
            self.events.append("reserve")
            raise RuntimeError("synthetic reservation failure")
        self.assert_denied(reserve=reserve)
        self.assertEqual(self.events, ["reserve"])

    def test_input_failure_never_authorizes_or_writes(self):
        for error in (EOFError(), KeyboardInterrupt(), RuntimeError("synthetic input failure")):
            self.events.clear()
            def hidden():
                self.events.append("input")
                raise error
            self.assert_denied(hidden_input=hidden)
            self.assertEqual(self.events, ["reserve", "input"])

    def test_invalid_input_wrapper_denied_before_authorize(self):
        self.value.clear()
        self.assert_denied()
        self.assertEqual(self.events, ["reserve", "input"])
        self.assert_cleared()
        self.assert_denied(hidden_input=lambda: None)

    def test_request_validation_and_test_refs_fail_closed(self):
        self.assert_denied(request={"credential_ref": CredentialRef.new()})
        self.assertEqual(self.events, [])
        for revision in (True, 0, -1, "2"):
            with self.assertRaises(EnrollmentError):
                replace(self.request, expected_revision=revision)
        with self.assertRaises(EnrollmentError):
            replace(self.request, operation_id=str(uuid4()))
        with patch("adapters.secrets.enrollment.CredentialRef.new", return_value=CredentialRef.new(testing=True)):
            self.assert_denied()
        self.assertEqual(self.events, [])

    def test_invalid_reservations_and_wrong_settled_receipt_do_not_prompt(self):
        receipt = EnrollmentReceipt(self.request.operation_id, self.request.principal_id,
                                    self.request.case_id, uuid4(), 2, 3)
        for reservation in (None, Reservation("unknown"), Reservation("ready"),
                            Reservation("settled", receipt=receipt), Reservation("blocked", receipt=receipt)):
            self.assert_denied(reserve=lambda candidate: reservation)
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
