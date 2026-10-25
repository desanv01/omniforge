"""Offline terminal entrypoint tests; all sensitive I/O uses explicit fakes."""

from dataclasses import replace
import getpass
import importlib
import io
import json
from pathlib import Path
import secrets
import unittest
import warnings
from unittest.mock import Mock, patch
from uuid import uuid4

from adapters.secrets.enrollment import EnrollmentReceipt, Reservation
from adapters.secrets.store import SecretStoreError
from infra.core import enroll_profile_cli as cli


class Terminal(io.StringIO):
    def isatty(self):
        return True


class FakeEngine:
    def __init__(self):
        self.disposed = 0

    def dispose(self):
        self.disposed += 1


class FakeStore:
    def __init__(self):
        self.puts = []

    def put(self, ref, value):
        self.puts.append((ref, value))

    def get(self, *args):
        raise AssertionError("Credential reads are forbidden")

    def delete(self, *args):
        raise AssertionError("Credential deletion is forbidden")


class ProfileCliTests(unittest.TestCase):
    def setUp(self):
        self.ids = [str(uuid4()) for _ in range(4)]
        self.config = str(Path.cwd() / "synthetic-not-read-config.json")
        self.argv = ["--config", self.config, "--principal-id", self.ids[0],
                     "--case-id", self.ids[1], "--profile-id", self.ids[2],
                     "--operation-id", self.ids[3], "--expected-revision", "2"]
        self.token = secrets.token_hex(32)
        self.key = secrets.token_hex(32)
        self.output, self.errors = io.StringIO(), Terminal()
        self.engine, self.store = FakeEngine(), FakeStore()
        self.events, self.values = [], []
        self.engine_factory = Mock(return_value=self.engine)
        self.store_factory = Mock(return_value=self.store)
        self.prompt = Mock(side_effect=[self.token, self.key])
        self.bridge = Mock(side_effect=self.fake_bridge)
        # No test may accidentally select a real factory/input/config read.
        self.guards = [patch.object(cli, name, side_effect=AssertionError("Default I/O forbidden"))
                       for name in ("_engine", "_store", "_bridge")]
        self.guards += [patch("getpass.getpass", side_effect=AssertionError("Real input forbidden"))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)

    def receipt(self, request):
        return EnrollmentReceipt(request.operation_id, request.principal_id, request.case_id,
                                 request.profile_id, request.expected_revision,
                                 request.expected_revision + 1)

    def fake_bridge(self, engine, *, bearer_token, request, store, hidden_input):
        self.assertTrue(bearer_token == self.token)
        self.assertIs(engine, self.engine)
        self.assertIs(store, self.store)
        value = hidden_input()
        self.values.append(value)
        self.assertTrue(secrets.compare_digest(value.reveal(), self.key.encode()))
        return self.receipt(request)

    def invoke(self, **overrides):
        options = dict(argv=self.argv, stdin=Terminal(), stdout=self.output,
                       stderr=self.errors, prompt=self.prompt,
                       engine_factory=self.engine_factory, store_factory=self.store_factory,
                       bridge=self.bridge)
        options.update(overrides)
        return cli.run(**options)

    def assert_redacted(self):
        combined = self.output.getvalue() + self.errors.getvalue()
        for private in (self.token, self.key, self.config):
            self.assertTrue(private not in combined)
        self.assertTrue("Traceback" not in combined)
        self.assertTrue("wincred:" not in combined)

    def assert_cleared(self):
        for value in self.values:
            with self.assertRaises(SecretStoreError):
                value.reveal()

    def test_success_hidden_handoff_receipt_only_and_close(self):
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.prompt.call_count, 2)
        self.engine_factory.assert_called_once_with(Path(self.config))
        self.assertEqual(self.engine.disposed, 1)
        result = json.loads(self.output.getvalue())
        self.assertEqual(set(result), {"schema_version", "operation_id", "case_id", "profile_id",
                                      "expected_revision", "attached_revision", "status"})
        self.assertEqual((result["status"], result["attached_revision"]), ("attached", 3))
        self.assert_cleared()
        self.assert_redacted()

    def test_parser_rejects_missing_duplicate_unknown_sensitive_or_bad_values(self):
        variants = [[], self.argv + ["--credential-ref", self.key],
                    self.argv + ["--bearer-token", self.token],
                    self.argv[:2] + self.argv[:2] + self.argv[4:]]
        for index, value in ((0, "--conf"), (1, "relative.json"), (3, "bad-uuid"),
                             (3, self.ids[0].upper()), (11, "0"), (11, "-1"),
                             (11, "2147483648"), (11, "1.0"), (11, "0" * 100)):
            changed = list(self.argv)
            changed[index] = value
            variants.append(changed)
        for arguments in variants:
            with self.subTest(argument_count=len(arguments)):
                self.assertEqual(self.invoke(argv=arguments), 2)
        self.prompt.assert_not_called()
        self.engine_factory.assert_not_called()
        self.bridge.assert_not_called()
        self.assert_redacted()

    def test_non_tty_input_or_prompt_stream_before_sensitive_calls(self):
        for options in ({"stdin": io.StringIO()}, {"stderr": io.StringIO()}):
            self.assertEqual(self.invoke(**options), 2)
        self.prompt.assert_not_called()
        self.engine_factory.assert_not_called()

    def test_broken_output_preflight_before_auth_or_configuration(self):
        class Broken(io.StringIO):
            def flush(self):
                raise OSError("synthetic private output")
        self.assertEqual(self.invoke(stdout=Broken()), 1)
        self.prompt.assert_not_called()
        self.engine_factory.assert_not_called()

    def test_noecho_warning_before_auth_fallback(self):
        echo = []
        def fallback(*args, **kwargs):
            warnings.warn("synthetic private warning", getpass.GetPassWarning)
            echo.append(True)
            return self.token
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", getpass.GetPassWarning)
            self.assertEqual(self.invoke(prompt=fallback), 1)
        self.assertEqual(echo, [])
        self.engine_factory.assert_not_called()
        self.assert_redacted()

    def test_invalid_auth_never_constructs_resources_or_bridge(self):
        for token in ("", " ", "Bearer " + self.token, "x" * 257, "\u20ac", None):
            self.assertEqual(self.invoke(prompt=Mock(return_value=token)), 1)
        self.engine_factory.assert_not_called()
        self.store_factory.assert_not_called()
        self.bridge.assert_not_called()
        self.assert_redacted()

    def test_auth_interruption_or_eof_before_resources(self):
        for error in (KeyboardInterrupt(), EOFError(self.token)):
            self.assertEqual(self.invoke(prompt=Mock(side_effect=error)), 1)
        self.engine_factory.assert_not_called()
        self.store_factory.assert_not_called()
        self.bridge.assert_not_called()
        self.assert_redacted()

    def test_auth_and_utf8_credential_upper_bounds(self):
        self.token, self.key = "x" * 256, "\U0001f600" * 640
        self.assertEqual(self.invoke(prompt=Mock(side_effect=[self.token, self.key])), 0)
        self.assert_cleared()
        self.assert_redacted()

    def test_cleanup_interrupt_and_diagnostic_interrupt_do_not_escape(self):
        self.engine.dispose = Mock(side_effect=KeyboardInterrupt())
        self.assertEqual(self.invoke(store_factory=Mock(side_effect=RuntimeError(self.token))), 1)
        self.engine.dispose.assert_called_once_with()
        self.assertIn("Local resource closure failed", self.errors.getvalue())
        class InterruptedErrorStream(Terminal):
            def write(self, text):
                raise KeyboardInterrupt()
        self.assertEqual(self.invoke(argv=[], stderr=InterruptedErrorStream()), 2)

    def test_invalid_provider_values_close_without_success_or_put(self):
        for key in ("", " \t", "x" * 2561, "\U0001f600" * 641, "\ud800", None):
            self.assertEqual(self.invoke(prompt=Mock(side_effect=[self.token, key])), 1)
        self.assertEqual(self.engine.disposed, 6)
        self.assertEqual(self.store.puts, [])
        self.assertEqual(self.output.getvalue(), "")
        self.assert_redacted()

    def test_provider_warning_refuses_fallback_and_closes(self):
        attempts = []
        def prompt(*args, **kwargs):
            if not attempts:
                attempts.append("auth")
                return self.token
            warnings.warn("private warning", getpass.GetPassWarning)
            attempts.append("echo")
            return self.key
        self.assertEqual(self.invoke(prompt=prompt), 1)
        self.assertEqual(attempts, ["auth"])
        self.assertEqual(self.engine.disposed, 1)
        self.assertEqual(self.output.getvalue(), "")

    def test_factory_errors_sanitized_and_store_failure_closes_engine(self):
        failure = RuntimeError(self.key + self.token + self.config)
        self.assertEqual(self.invoke(engine_factory=Mock(side_effect=failure)), 1)
        self.store_factory.assert_not_called()
        self.assertEqual(self.invoke(prompt=Mock(return_value=self.token),
                                     store_factory=Mock(side_effect=failure)), 1)
        self.assertEqual(self.engine.disposed, 1)
        self.assert_redacted()

    def test_bridge_failure_or_interrupt_after_input_clears_and_never_retries(self):
        for error in (RuntimeError(self.key), KeyboardInterrupt()):
            def failed(engine, **kwargs):
                value = kwargs["hidden_input"]()
                self.values.append(value)
                raise error
            bridge = Mock(side_effect=failed)
            self.assertEqual(self.invoke(prompt=Mock(side_effect=[self.token, self.key]), bridge=bridge), 1)
            self.assertEqual(bridge.call_count, 1)
            self.assert_cleared()
        self.assertEqual(self.engine.disposed, 2)
        self.assertIn("outcome is uncertain", self.errors.getvalue())
        self.assert_redacted()

    def test_output_loss_after_operation_is_uncertain_no_retry_and_closes(self):
        class Broken(io.StringIO):
            def write(self, value):
                if value:
                    raise OSError("synthetic private output")
                return super().write(value)
        self.assertEqual(self.invoke(stdout=Broken()), 1)
        self.assertEqual(self.bridge.call_count, 1)
        self.assertEqual(self.engine.disposed, 1)
        self.assert_cleared()
        self.assertIn("outcome is uncertain", self.errors.getvalue())

    def test_invalid_receipt_is_not_success(self):
        def wrong(engine, **kwargs):
            return replace(self.receipt(kwargs["request"]), profile_id=uuid4())
        self.assertEqual(self.invoke(bridge=wrong), 1)
        self.assertEqual(self.prompt.call_count, 1)
        self.assertEqual(self.output.getvalue(), "")
        self.assertEqual(self.engine.disposed, 1)

    def test_repeated_provider_prompt_refused(self):
        def twice(engine, **kwargs):
            self.values.append(kwargs["hidden_input"]())
            kwargs["hidden_input"]()
        self.assertEqual(self.invoke(bridge=twice), 1)
        self.assertEqual(self.prompt.call_count, 2)
        self.assert_cleared()

    def test_dispose_failure_not_success_and_not_retried(self):
        self.engine.dispose = Mock(side_effect=RuntimeError(self.config))
        self.assertEqual(self.invoke(), 1)
        self.engine.dispose.assert_called_once_with()
        self.assertEqual(self.output.getvalue(), "")
        self.assert_cleared()
        self.assert_redacted()

    def test_import_does_not_load_config_construct_store_or_read_input(self):
        with patch("pathlib.Path.read_text", side_effect=AssertionError("Config read forbidden")):
            importlib.reload(cli)
        self.prompt.assert_not_called()
        self.engine_factory.assert_not_called()
        self.store_factory.assert_not_called()

    def test_real_accepted_bridge_with_fake_binding_callbacks_and_store(self):
        from infra.core.enroll_profile import enroll_profile
        def reserve(engine, token, candidate):
            self.events.append("reserve")
            self.assertTrue(token == self.token)
            return Reservation("ready", binding=candidate)
        def authorize(engine, token, binding):
            self.events.append("authorize")
            return binding
        def attach(engine, token, binding):
            self.events.append("attach")
            return self.receipt(binding)
        def prompt(label, **kwargs):
            self.events.append("auth_input" if "bearer" in label else "provider_input")
            return self.token if "bearer" in label else self.key
        with patch("infra.core.enroll_profile.bindings.reserve", side_effect=reserve), \
             patch("infra.core.enroll_profile.bindings.authorize_put", side_effect=authorize), \
             patch("infra.core.enroll_profile.bindings.attach", side_effect=attach):
            self.assertEqual(self.invoke(bridge=enroll_profile, prompt=prompt), 0)
        self.assertEqual(self.events, ["auth_input", "reserve", "provider_input", "authorize", "attach"])
        self.assertEqual(len(self.store.puts), 1)
        with self.assertRaises(SecretStoreError):
            self.store.puts[0][1].reveal()
        self.assert_redacted()

    def test_real_bridge_settled_replay_has_only_auth_prompt(self):
        from infra.core.enroll_profile import enroll_profile
        def settled(engine, token, candidate):
            return Reservation("settled", receipt=self.receipt(candidate))
        with patch("infra.core.enroll_profile.bindings.reserve", side_effect=settled), \
             patch("infra.core.enroll_profile.bindings.authorize_put") as authorize, \
             patch("infra.core.enroll_profile.bindings.attach") as attach:
            self.assertEqual(self.invoke(bridge=enroll_profile), 0)
            authorize.assert_not_called()
            attach.assert_not_called()
        self.assertEqual(self.prompt.call_count, 1)
        self.assertEqual(self.store.puts, [])

    def test_real_bridge_pending_does_not_prompt_provider_or_retry(self):
        from infra.core.enroll_profile import enroll_profile
        with patch("infra.core.enroll_profile.bindings.reserve", return_value=Reservation("blocked")), \
             patch("infra.core.enroll_profile.bindings.unresolved") as unresolved:
            self.assertEqual(self.invoke(bridge=enroll_profile), 1)
            unresolved.assert_not_called()
        self.assertEqual(self.prompt.call_count, 1)
        self.assertEqual(self.store.puts, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
