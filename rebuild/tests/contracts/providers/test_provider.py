from dataclasses import replace
import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from adapters.models.contracts import Budget, Location, Measurement, Profile, ReadOnlyContext
from adapters.models.deepseek import DeepSeekHTTPS, ProviderFailure
from adapters.models.mock import ScriptedMock, final_round, tool_round
from adapters.secrets.store import CredentialRef, SecretStoreError, SecretValue
from services.api.providers.answer import answer


class SyntheticStore:
    def __init__(self, error=None):
        self.error, self.reads, self.values = error, 0, []

    def get(self, ref):
        self.reads += 1
        if self.error:
            raise SecretStoreError(self.error)
        value = SecretValue(b"synthetic-unused-key")
        self.values.append(value)
        return value


class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.data = b"abc\x00\xff\r\n"
        self.loc = Location(id=uuid4(), association_id=uuid4(), artifact_id=uuid4(),
            sha256=hashlib.sha256(self.data).hexdigest(), start_byte=1, end_byte=5)
        self.profile = Profile(uuid4(), 1, "https://api.deepseek.com/chat/completions", "configured-model", CredentialRef.new(testing=True))
        self.reads = []
        def read(*args):
            self.reads.append(args)
            return self.data[1:5]
        self.ctx = ReadOnlyContext(uuid4(), "policy-fixture-v1", "Synthetic scope only", (self.loc,), read,
            lambda p: p == self.profile, lambda: False)
        self.budget = Budget(calls=3, input_tokens=100000, output_tokens=1536, wall_seconds=5, tool_bytes=32)

    def run_answer(self, rounds=None, *, ctx=None, profile=None, budget=None, store=None, **kwargs):
        self.store = store or SyntheticStore()
        self.transport = ScriptedMock(rounds if rounds is not None else [tool_round(self.loc), final_round(self.loc)])
        return answer(ctx or self.ctx, profile or self.profile, budget or self.budget,
                      store=self.store, transport=self.transport, **kwargs)

    def test_exact_range_and_known_usage(self):
        result = self.run_answer()
        self.assertIsNone(result.error)
        self.assertEqual(self.reads, [(self.loc.association_id, self.loc.sha256, 1, 5)])
        self.assertEqual((result.usage.calls, result.usage.tool_bytes), (2, 4))
        self.assertEqual(result.usage.input_tokens.value, 70)
        self.assertEqual(result.usage.output_tokens.value, 45)
        self.assertEqual(result.usage.cost.state, "unknown")
        self.assertIsNone(result.usage.cost.value)
        for value in self.store.values:
            with self.assertRaises(SecretStoreError):
                value.reveal()

    def test_citation_must_have_been_read(self):
        self.assertEqual(self.run_answer([final_round(self.loc)]).error, "forbidden")
        for field, replacement in (("location_id", str(uuid4())), ("expected_sha256", "0" * 64)):
            with self.subTest(field=field):
                final = final_round(self.loc)
                body = json.loads(final["choices"][0]["message"]["content"])
                body["observations"][0]["citations"][0][field] = replacement
                final["choices"][0]["message"]["content"] = json.dumps(body)
                self.assertEqual(self.run_answer([tool_round(self.loc), final]).error, "forbidden")

    def test_reference_hash_range_rejected_before_reader(self):
        for field, value in (("location_id", str(uuid4())), ("expected_sha256", "0" * 64),
                             ("start_byte", 0), ("end_byte", 6), ("start_byte", True)):
            with self.subTest(field=field, value=value):
                tool = tool_round(self.loc)
                fn = tool["choices"][0]["message"]["tool_calls"][0]["function"]
                args = json.loads(fn["arguments"])
                args[field] = value
                fn["arguments"] = json.dumps(args)
                self.reads.clear()
                self.assertEqual(self.run_answer([tool]).error, "forbidden")
                self.assertEqual(self.reads, [])

    def test_bound_profile_and_endpoint_fail_before_secret(self):
        for profile in (replace(self.profile, endpoint="https://evil.invalid/chat/completions"),
                        replace(self.profile, revision=2), replace(self.profile, credential_ref=CredentialRef.new(testing=True))):
            self.assertEqual(self.run_answer(profile=profile).error, "forbidden")
            self.assertEqual(self.store.reads, 0)

    def test_missing_and_denied_do_not_dispatch(self):
        for code in ("missing", "denied", "unavailable", "unsupported", "storage"):
            result = self.run_answer(store=SyntheticStore(code))
            self.assertEqual(result.error, "credential_" + code)
            self.assertEqual(result.usage.calls, 0)

    def test_cumulative_reservations_and_no_retry(self):
        for budget in (self.budget.model_copy(update={"calls": 1}),
                       self.budget.model_copy(update={"output_tokens": 512}),
                       self.budget.model_copy(update={"tool_bytes": 3})):
            self.assertEqual(self.run_answer(budget=budget).error, "budget")
            self.assertEqual(self.transport.calls, 1)
        result = self.run_answer(budget=self.budget.model_copy(update={"input_tokens": 1}))
        self.assertEqual(result.error, "budget")
        self.assertEqual(self.store.reads, 0)
        # Second range would exceed cumulative bytes despite each being valid alone.
        result = self.run_answer([tool_round(self.loc), tool_round(self.loc)], budget=self.budget.model_copy(update={"tool_bytes": 7}))
        self.assertEqual((result.error, result.usage.calls, result.usage.tool_bytes), ("budget", 2, 4))

    def test_reported_usage_reconciled_before_next_admission(self):
        first = tool_round(self.loc)
        first["usage"]["prompt_tokens"] = self.budget.input_tokens - 1
        result = self.run_answer([first, final_round(self.loc)])
        self.assertEqual((result.error, result.usage.calls, self.store.reads), ("budget", 1, 1))
        self.assertEqual(result.usage.input_tokens.value, 99999)
        self.assertEqual(result.usage.charged_input, 99999)
        self.assertLess(result.usage.reserved_input, result.usage.charged_input)

        # First response reports more than its512 reservation, below the total.
        # The second call gets only the actual remaining436; it cannot buy a third
        # call by reporting less than this reservation on its own response.
        first = tool_round(self.loc)
        first["usage"]["completion_tokens"] = 1100
        result = self.run_answer([first, tool_round(self.loc), final_round(self.loc)])
        self.assertEqual((result.error, result.usage.calls, self.store.reads), ("budget", 2, 2))
        self.assertEqual(result.usage.output_tokens.value, 1120)
        self.assertEqual(result.usage.charged_output, self.budget.output_tokens)
        self.assertEqual(result.usage.reserved_output, 512 + 436)

        # A missing first usage never refunds its reservation when later usage is
        # known; known subtotals remain available without turning the total known.
        first = tool_round(self.loc)
        del first["usage"]
        result = self.run_answer([first, tool_round(self.loc), final_round(self.loc)],
                                budget=self.budget.model_copy(update={"output_tokens": 1024}))
        self.assertEqual((result.error, result.usage.calls, self.store.reads), ("budget", 2, 2))
        self.assertEqual(result.usage.output_tokens.state, "unknown")
        self.assertEqual(result.usage.known_output_subtotal, 20)
        self.assertEqual(result.usage.charged_output, 1024)

    def test_provider_errors_keep_unknown_usage_no_retry(self):
        for code in ("provider_auth", "provider_rate_limit", "provider_timeout", "invalid_schema"):
            result = self.run_answer([ProviderFailure(code)])
            self.assertEqual(result.error, code)
            self.assertEqual(result.usage.calls, 1)
            self.assertEqual(result.usage.input_tokens.state, "unknown")

    def test_missing_usage_never_becomes_zero(self):
        first = tool_round(self.loc)
        del first["usage"]
        result = self.run_answer([first, final_round(self.loc)])
        self.assertIsNone(result.error)
        self.assertEqual(result.usage.input_tokens.state, "unknown")
        self.assertIsNone(result.usage.input_tokens.value)
        self.assertEqual(result.usage.known_input_subtotal, 40)
        self.assertGreater(result.usage.reserved_input, 0)
        self.assertEqual(Measurement(value=12, state="estimated", provenance="wire reservation").state, "estimated")

    def test_tool_failure_sanitized_and_usage_preserved(self):
        def fail(*args):
            raise RuntimeError("sensitive-private-content")
        result = self.run_answer(ctx=replace(self.ctx, read_range=fail))
        self.assertEqual(result.error, "tool_failure")
        self.assertEqual(result.usage.input_tokens.value, 30)
        self.assertNotIn("sensitive-private", repr(result))
        self.assertEqual(self.run_answer(ctx=replace(self.ctx, read_range=lambda *args: b"wrong-size")).error, "tool_failure")

    def test_cancellation_before_dispatch_and_after_response(self):
        result = self.run_answer(ctx=replace(self.ctx, canceled=lambda: True))
        self.assertEqual((result.error, result.usage.calls, self.store.reads), ("canceled", 0, 0))
        checks = iter([False, False, True])
        result = self.run_answer(ctx=replace(self.ctx, canceled=lambda: next(checks)))
        self.assertEqual((result.error, result.usage.calls, len(self.reads)), ("canceled", 1, 0))
        self.assertEqual(result.usage.input_tokens.value, 30)

    def test_deadline_and_invalid_schema(self):
        ticks = iter([0, 6])
        self.assertEqual(self.run_answer(clock=lambda: next(ticks)).error, "provider_timeout")
        for response in ({}, {"choices": []}, {"choices": [{"finish_reason": "length", "message": {}}]}):
            self.assertEqual(self.run_answer([response]).error, "invalid_schema")

    def test_only_evidence_tool_and_authority_revocation(self):
        tool = tool_round(self.loc)
        tool["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "exec"
        self.assertEqual(self.run_answer([tool]).error, "unsupported")
        calls = iter([True, True, True, False])
        result = self.run_answer(ctx=replace(self.ctx, authorize_profile=lambda p: next(calls)))
        self.assertEqual((result.error, result.usage.calls), ("forbidden", 1))

    def test_reported_budget_overrun_and_schema_claim_rejection(self):
        response = tool_round(self.loc)
        response["usage"]["completion_tokens"] = 9999
        result = self.run_answer([response])
        self.assertEqual(result.error, "budget")
        self.assertEqual(result.usage.output_tokens.value, 9999)
        self.assertEqual(self.reads, [])
        final = final_round(self.loc)
        body = json.loads(final["choices"][0]["message"]["content"])
        body["claims"] = [{"text": "test", "supporting": [], "contradicting": [],
                           "verification": "verified", "uncertainty": "unknown"}]
        final["choices"][0]["message"]["content"] = json.dumps(body)
        self.assertEqual(self.run_answer([tool_round(self.loc), final]).error, "invalid_schema")

    def test_https_statuses_body_limits_and_no_redirect_retry(self):
        # No network or OS credential operation: mock the stdlib connection itself.
        for status, code in ((401, "provider_auth"), (402, "provider_balance"),
                             (429, "provider_rate_limit"), (302, "provider_unavailable"),
                             (503, "provider_unavailable"), (422, "invalid_schema")):
            with self.subTest(status=status), patch("adapters.models.deepseek.http.client.HTTPSConnection") as factory:
                connection = factory.return_value
                connection.getresponse.return_value.status = status
                with self.assertRaises(ProviderFailure) as caught:
                    DeepSeekHTTPS().complete(self.profile, SecretValue(b"synthetic"), {}, 1)
                self.assertEqual(caught.exception.code, code)
                connection.request.assert_called_once()
                connection.close.assert_called_once()
        for raw in (b"invalid json", b"x" * 1048577):
            with patch("adapters.models.deepseek.http.client.HTTPSConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status, response.read.return_value = 200, raw
                with self.assertRaises(ProviderFailure) as caught:
                    DeepSeekHTTPS().complete(self.profile, SecretValue(b"synthetic"), {}, 1)
                self.assertEqual(caught.exception.code, "invalid_schema")

    def test_injected_raw_exception_cannot_escape(self):
        result = self.run_answer([RuntimeError("secret-private")])
        self.assertEqual(result.error, "provider_unavailable")
        self.assertNotIn("secret-private", repr(result))
        self.assertEqual(result.usage.input_tokens.state, "unknown")


if __name__ == "__main__":
    unittest.main()
