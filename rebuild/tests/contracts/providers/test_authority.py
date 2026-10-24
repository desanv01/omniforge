"""Synthetic action-boundary checks; no database, OS store or network."""
from dataclasses import replace
import unittest
from uuid import uuid4

from adapters.models.contracts import Budget, Location, Profile, ReadOnlyContext
from adapters.models.mock import ScriptedMock, final_round, tool_round
from adapters.secrets.store import CredentialRef, SecretStoreError, SecretValue
from services.api.providers.answer import answer


class ReturningStore:
    def __init__(self, on_get=lambda: None):
        self.on_get = on_get
        self.values = []
        self.reads = 0

    def get(self, ref):
        self.reads += 1
        value = SecretValue(b"synthetic-unused-authority-value")
        self.values.append(value)
        self.on_get()
        return value


class AuthorityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(uuid4(), 1, "https://api.deepseek.com/chat/completions",
                               "synthetic-only", CredentialRef.new(testing=True))
        self.current = self.profile
        self.allowed = True
        self.authority_error = None
        self.loc = Location(id=uuid4(), association_id=uuid4(), artifact_id=uuid4(),
                            sha256="a" * 64, start_byte=0, end_byte=4)
        self.context = ReadOnlyContext(uuid4(), "synthetic-authority-v1", "Synthetic fixture",
            (self.loc,), lambda *args: b"test", self.authorize, lambda: False)
        self.budget = Budget(calls=3, input_tokens=100000, output_tokens=1536,
                             wall_seconds=5, tool_bytes=16)

    def authorize(self, candidate):
        if self.authority_error is not None:
            raise self.authority_error
        return self.allowed and candidate == self.current

    def assert_cleared(self, store):
        for value in store.values:
            with self.assertRaises(SecretStoreError):
                value.reveal()

    def execute(self, store, transport, context=None):
        return answer(context or self.context, self.profile, self.budget,
                      store=store, transport=transport)

    def test_deny_revision_or_ref_change_during_get_prevents_dispatch(self):
        def deny():
            self.allowed = False
        def revise():
            self.current = replace(self.profile, revision=2)
        def change_ref():
            self.current = replace(self.profile, credential_ref=CredentialRef.new(testing=True))
        for mutation in (deny, revise, change_ref):
            with self.subTest(mutation=mutation.__name__):
                self.allowed, self.current = True, self.profile
                store = ReturningStore(mutation)
                transport = ScriptedMock([tool_round(self.loc), final_round(self.loc)])
                result = self.execute(store, transport)
                self.assertEqual(result.error, "forbidden")
                self.assertIsNone(result.answer)
                self.assertEqual((store.reads, transport.calls, result.usage.calls), (1, 0, 0))
                self.assertEqual(result.usage.input_tokens.value, 0)
                self.assertEqual(result.usage.output_tokens.value, 0)
                # Reservations made before retrieval are deliberately not refunded.
                self.assertGreater(result.usage.charged_input, 0)
                self.assertEqual(result.usage.charged_output, 512)
                self.assert_cleared(store)

    def test_authority_exception_after_get_is_safe_and_clears_value(self):
        def fail():
            self.authority_error = RuntimeError("private-authorization-detail")
        store = ReturningStore(fail)
        transport = ScriptedMock([tool_round(self.loc)])
        result = self.execute(store, transport)
        self.assertEqual((result.error, transport.calls, result.usage.calls), ("forbidden", 0, 0))
        self.assertIsNone(result.answer)
        self.assertNotIn("private-authorization-detail", repr(result))
        self.assert_cleared(store)

    def test_final_authority_denial_or_exception_keeps_dispatched_usage(self):
        for mode in ("deny", "exception"):
            with self.subTest(mode=mode):
                self.allowed, self.authority_error = True, None
                state = self
                class FinalAuthorityChange(ScriptedMock):
                    def complete(self, *args):
                        response = super().complete(*args)
                        if self.calls == 2:
                            if mode == "deny":
                                state.allowed = False
                            else:
                                state.authority_error = RuntimeError("private-final-authority")
                        return response
                store = ReturningStore()
                transport = FinalAuthorityChange([tool_round(self.loc), final_round(self.loc)])
                result = self.execute(store, transport)
                self.assertEqual(result.error, "forbidden")
                self.assertIsNone(result.answer)
                self.assertEqual((store.reads, transport.calls, result.usage.calls), (2, 2, 2))
                self.assertEqual((result.usage.input_tokens.value, result.usage.output_tokens.value), (70, 45))
                self.assertEqual(result.usage.charged_output, 1024)
                self.assertEqual(result.usage.tool_bytes, 4)
                self.assertNotIn("private-final-authority", repr(result))
                self.assert_cleared(store)

    def test_second_get_revocation_keeps_first_round_usage_and_reservations(self):
        store = ReturningStore()
        def revoke_second():
            if store.reads == 2:
                self.allowed = False
        store.on_get = revoke_second
        transport = ScriptedMock([tool_round(self.loc), final_round(self.loc)])
        result = self.execute(store, transport)
        self.assertEqual((result.error, store.reads, transport.calls, result.usage.calls),
                         ("forbidden", 2, 1, 1))
        self.assertEqual((result.usage.input_tokens.value, result.usage.output_tokens.value), (30, 20))
        self.assertEqual(result.usage.reserved_output, 1024)
        self.assertEqual(result.usage.charged_output, 1024)
        self.assertIsNone(result.answer)
        self.assert_cleared(store)

    def test_final_denial_keeps_unknown_usage_and_known_subtotal(self):
        first = tool_round(self.loc)
        del first["usage"]
        state = self
        class FinalDenial(ScriptedMock):
            def complete(self, *args):
                response = super().complete(*args)
                if self.calls == 2:
                    state.allowed = False
                return response
        store = ReturningStore()
        result = self.execute(store, FinalDenial([first, final_round(self.loc)]))
        self.assertEqual(result.error, "forbidden")
        self.assertIsNone(result.answer)
        self.assertEqual(result.usage.calls, 2)
        self.assertEqual(result.usage.input_tokens.state, "unknown")
        self.assertIsNone(result.usage.input_tokens.value)
        self.assertEqual(result.usage.known_input_subtotal, 40)
        self.assertEqual(result.usage.known_output_subtotal, 25)
        self.assert_cleared(store)

    def test_non_boolean_authority_fails_closed(self):
        store = ReturningStore()
        transport = ScriptedMock([])
        result = self.execute(store, transport,
                              context=replace(self.context, authorize_profile=lambda p: "yes"))
        self.assertEqual((result.error, store.reads, result.usage.calls), ("forbidden", 0, 0))


if __name__ == "__main__":
    unittest.main()
