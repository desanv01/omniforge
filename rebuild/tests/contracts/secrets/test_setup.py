"""Mock-only enrollment checks: never construct an OS store or read real input."""

import getpass
import io
import unittest
import warnings

from adapters.secrets.setup import run
from adapters.secrets.store import CredentialRef, SecretStoreError


class Terminal(io.StringIO):
    def isatty(self):
        return True


class FakeStore:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def put(self, reference, value):
        self.calls.append((reference, value, value.reveal()))
        if self.fail:
            raise RuntimeError("synthetic-private-store-detail")

    def get(self, reference):
        raise AssertionError("Existing credential reads are forbidden")

    def delete(self, reference):
        raise AssertionError("Credential deletion is forbidden")


class SetupTests(unittest.TestCase):
    def invoke(self, *, argv=(), input_text="synthetic-unused-value", stdin=None,
               stderr=None, stdout=None, prompt=None, store=None):
        self.output = io.StringIO() if stdout is None else stdout
        self.errors = Terminal() if stderr is None else stderr
        self.store = FakeStore() if store is None else store
        self.prompt_calls = self.factory_calls = 0

        def reader(*args, **kwargs):
            self.prompt_calls += 1
            return input_text if prompt is None else prompt(*args, **kwargs)

        def factory():
            self.factory_calls += 1
            return self.store

        return run(argv, stdin=Terminal() if stdin is None else stdin,
                   stdout=self.output, stderr=self.errors, prompt=reader,
                   store_factory=factory)

    def test_success_is_fresh_reference_only_and_clears_owned_value(self):
        references = []
        for _ in range(2):
            self.assertEqual(self.invoke(), 0)
            self.assertEqual((self.prompt_calls, self.factory_calls), (1, 1))
            reference, value, captured = self.store.calls[0]
            self.assertEqual(CredentialRef(self.output.getvalue().strip()), reference)
            self.assertTrue(reference.value.startswith("wincred:omniforge:v1:"))
            self.assertEqual(captured, b"synthetic-unused-value")
            self.assertEqual(self.output.getvalue(), reference.value + "\n")
            self.assertEqual(self.errors.getvalue(), "")
            with self.assertRaises(SecretStoreError):
                value.reveal()
            references.append(reference)
        self.assertNotEqual(*references)

    def test_arguments_and_noninteractive_streams_never_prompt_or_construct_store(self):
        for options in ({"argv": ["private-argument"]}, {"stdin": io.StringIO()},
                        {"stderr": io.StringIO()}):
            with self.subTest(options=tuple(options)):
                self.assertNotEqual(self.invoke(**options), 0)
                self.assertEqual((self.prompt_calls, self.factory_calls), (0, 0))
                self.assertEqual(self.store.calls, [])
                self.assertNotIn("private-argument", self.errors.getvalue())

    def test_getpass_warning_raises_before_echo_fallback(self):
        fallback = []
        def reader(*args, **kwargs):
            warnings.warn("synthetic-private-warning", getpass.GetPassWarning)
            fallback.append(True)
            return "must-not-be-read"
        self.assertEqual(self.invoke(prompt=reader), 1)
        self.assertEqual(fallback, [])
        self.assertEqual(self.factory_calls, 0)
        self.assertNotIn("synthetic-private-warning", self.errors.getvalue())

    def test_invalid_or_overlarge_values_never_reach_store(self):
        for raw in ("", " \t", "x" * 2561, "\U0001f600" * 641, "\ud800", None):
            with self.subTest(kind=type(raw).__name__):
                self.assertEqual(self.invoke(input_text=raw), 1)
                self.assertEqual((self.factory_calls, len(self.store.calls)), (0, 0))
                self.assertEqual(self.output.getvalue(), "")
                self.assertEqual(self.errors.getvalue(), "Credential setup did not complete.\n")

    def test_interruption_and_reader_errors_are_safe_without_writes(self):
        for failure in (EOFError("private-input-detail"), KeyboardInterrupt(),
                        RuntimeError("private-input-detail")):
            def reader(*args, **kwargs):
                raise failure
            with self.subTest(kind=type(failure).__name__):
                self.assertEqual(self.invoke(prompt=reader), 1)
                self.assertEqual(self.factory_calls, 0)
                self.assertEqual(self.errors.getvalue(), "Credential setup did not complete.\n")

    def test_storage_error_clears_value_and_does_not_retry_or_print_reference(self):
        self.assertEqual(self.invoke(store=FakeStore(fail=True)), 1)
        self.assertEqual((self.factory_calls, len(self.store.calls)), (1, 1))
        self.assertEqual(self.output.getvalue(), "")
        self.assertEqual(self.errors.getvalue(),
                         "Credential setup outcome is uncertain; do not retry automatically.\n")
        with self.assertRaises(SecretStoreError):
            self.store.calls[0][1].reveal()

    def test_lost_output_after_put_is_uncertain_and_clears_without_retry(self):
        class BrokenOutput(io.StringIO):
            def write(self, value):
                if value:
                    raise OSError("private-output-detail")
                return super().write(value)
        self.assertEqual(self.invoke(stdout=BrokenOutput()), 1)
        self.assertEqual(len(self.store.calls), 1)
        self.assertIn("outcome is uncertain", self.errors.getvalue())
        self.assertNotIn("private-output-detail", self.errors.getvalue())
        with self.assertRaises(SecretStoreError):
            self.store.calls[0][1].reveal()


if __name__ == "__main__":
    unittest.main()
