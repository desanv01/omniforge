"""Synthetic-only contract checks. --live-wincred opts into exact owned targets."""

import ctypes as c
import pickle
import secrets
import sys
import traceback
import unittest
from unittest.mock import Mock, patch
from ctypes import wintypes as w

from adapters.secrets import CredentialRef, SecretStoreError, SecretValue, WindowsSecretStore
from adapters.secrets.windows import _Credential

LIVE = "--live-wincred" in sys.argv
if LIVE:
    sys.argv.remove("--live-wincred")


class ContractTests(unittest.TestCase):
    def test_references_reject_arbitrary_targets(self):
        for text in ("legacy", "wincred:omniforge:v1:../x", "wincred:other:v1:x", "", None):
            with self.assertRaises(SecretStoreError) as result:
                CredentialRef(text)
            self.assertEqual(result.exception.code, "invalid_reference")
        ref = CredentialRef.new()
        self.assertTrue(ref.target.startswith("OmniForge/wincred:omniforge:v1:"))

    def test_values_are_redacted_and_not_serializable(self):
        raw = secrets.token_bytes(32)
        value = SecretValue(raw)
        self.assertTrue(repr(raw) not in repr(value))
        self.assertEqual(str(value), "SecretValue(<redacted>)")
        with self.assertRaises(TypeError):
            pickle.dumps(value)
        value.clear()
        with self.assertRaises(SecretStoreError):
            value.reveal()

    def test_invalid_values_have_safe_errors(self):
        for raw in (b"", secrets.token_bytes(2561), "not-bytes"):
            with self.assertRaises(SecretStoreError) as result:
                SecretValue(raw)
            self.assertEqual(str(result.exception), "Credential value must contain 1 to 2560 bytes.")

    def test_unsupported_mode_never_loads_native_library(self):
        with self.assertRaises(SecretStoreError) as result:
            WindowsSecretStore(mode="headless")
        self.assertEqual(result.exception.code, "unsupported")
        with patch("adapters.secrets.windows.sys.platform", "linux"):
            with self.assertRaises(SecretStoreError):
                WindowsSecretStore()

    def test_native_layout_on_windows(self):
        if sys.platform != "win32":
            self.skipTest("Windows ABI only")
        self.assertEqual(c.sizeof(_Credential), 80 if c.sizeof(c.c_void_p) == 8 else 52)
        self.assertEqual(_Credential.CredentialBlob.offset, 40 if c.sizeof(c.c_void_p) == 8 else 28)

    def test_native_error_allowlist_and_no_raw_message(self):
        if sys.platform != "win32":
            self.skipTest("Windows last-error only")
        store = WindowsSecretStore()
        api = Mock()
        api.CredReadW.return_value = False
        store._api = api
        for number, expected in ((1168, "missing"), (1312, "unavailable"), (5, "denied"), (87, "storage")):
            with patch("adapters.secrets.windows.c.get_last_error", return_value=number):
                with self.assertRaises(SecretStoreError) as result:
                    store.get(CredentialRef.new(testing=True))
                self.assertEqual(result.exception.code, expected)
        api.CredReadW.side_effect = RuntimeError("synthetic upstream body must not escape")
        try:
            store.get(CredentialRef.new(testing=True))
        except SecretStoreError as error:
            output = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            self.assertTrue("synthetic upstream body" not in output)
            self.assertTrue(error.__suppress_context__)
        else:
            self.fail("Expected safe storage error")

    def test_read_frees_and_clears_native_buffer(self):
        if sys.platform != "win32":
            self.skipTest("Windows ABI only")
        store = WindowsSecretStore()
        raw = secrets.token_bytes(32)
        blob = (w.BYTE * len(raw)).from_buffer_copy(raw)
        item = _Credential()
        item.Type, item.CredentialBlobSize, item.CredentialBlob = 1, len(blob), blob
        def read(target, kind, flags, output):
            c.cast(output, c.POINTER(c.POINTER(_Credential)))[0] = c.pointer(item)
            return True
        api = Mock()
        api.CredReadW.side_effect = read
        store._api = api
        value = store.get(CredentialRef.new(testing=True))
        self.assertTrue(secrets.compare_digest(value.reveal(), raw), "Synthetic equality failed")
        self.assertTrue(all(byte == 0 for byte in blob))
        self.assertEqual(api.CredFree.call_count, 1)
        value.clear()

    def test_corrupt_read_still_frees(self):
        if sys.platform != "win32":
            self.skipTest("Windows ABI only")
        store = WindowsSecretStore()
        item = _Credential()
        item.Type, item.CredentialBlobSize = 1, 2561
        def read(target, kind, flags, output):
            c.cast(output, c.POINTER(c.POINTER(_Credential)))[0] = c.pointer(item)
            return True
        api = Mock()
        api.CredReadW.side_effect = read
        store._api = api
        with self.assertRaises(SecretStoreError):
            store.get(CredentialRef.new(testing=True))
        self.assertEqual(api.CredFree.call_count, 1)

    def test_failed_write_clears_native_copy_and_hides_secret(self):
        if sys.platform != "win32":
            self.skipTest("Windows ABI only")
        store = WindowsSecretStore()
        value = SecretValue(secrets.token_bytes(32))
        observed = []
        def write(pointer, flags):
            item = c.cast(pointer, c.POINTER(_Credential)).contents
            observed.append((item.CredentialBlob, item.CredentialBlobSize))
            # Keep the allocation alive so clearing can be checked after return.
            observed.append(pointer._obj)
            raise RuntimeError(value.reveal().hex())
        api = Mock()
        api.CredWriteW.side_effect = write
        store._api = api
        try:
            store.put(CredentialRef.new(testing=True), value)
        except SecretStoreError as error:
            output = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            self.assertTrue(value.reveal().hex() not in output)
            self.assertEqual(error.code, "storage")
        else:
            self.fail("Expected safe storage error")
        pointer, size = observed[0]
        self.assertTrue(all(pointer[index] == 0 for index in range(size)))
        value.clear()

    @unittest.skipUnless(LIVE and sys.platform == "win32", "Requires explicit --live-wincred")
    def test_owned_synthetic_lifecycle_and_reentry(self):
        store = WindowsSecretStore()
        ref = CredentialRef.new(testing=True)
        # UUID generated here; only successful writes establish cleanup ownership.
        print("Synthetic target allocated: " + ref.target, flush=True)
        owned = False
        first = SecretValue(bytes(1) + secrets.token_bytes(31))
        second = SecretValue(secrets.token_bytes(2560))
        try:
            with self.assertRaises(SecretStoreError) as missing:
                store.get(ref)
            self.assertEqual(missing.exception.code, "missing")
            store.put(ref, first)
            owned = True
            for value in (first, second):
                store.put(ref, value)
                returned = store.get(ref)
                self.assertTrue(secrets.compare_digest(returned.reveal(), value.reveal()), "Synthetic equality failed")
                returned.clear()
            self.assertTrue(store.delete(ref))
            owned = False
            with self.assertRaises(SecretStoreError) as lost:
                store.get(ref)
            self.assertEqual(lost.exception.code, "missing")
            self.assertFalse(store.delete(ref))
            # Loss recovery is explicit re-entry of a newly supplied value.
            store.put(ref, first)
            owned = True
            returned = store.get(ref)
            self.assertTrue(secrets.compare_digest(returned.reveal(), first.reveal()), "Re-entry equality failed")
            returned.clear()
        finally:
            first.clear()
            second.clear()
            if owned:
                if not store.delete(ref):
                    raise RuntimeError("Owned synthetic cleanup unexpectedly absent")
                print("Owned synthetic target cleanup: deleted", flush=True)
        with self.assertRaises(SecretStoreError) as final:
            store.get(ref)
        self.assertEqual(final.exception.code, "missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
