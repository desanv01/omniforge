"""WinCred generic credentials for the current token, same user/local computer.

No enumeration, environment/file fallback, key migration, UI prompt or network I/O.
"""

import ctypes as c
import sys
from ctypes import wintypes as w

from .store import CredentialRef, SecretStoreError, SecretValue


class _Credential(c.Structure):
    _fields_ = [
        ("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR),
        ("Comment", w.LPWSTR), ("LastWritten", w.FILETIME),
        ("CredentialBlobSize", w.DWORD), ("CredentialBlob", c.POINTER(w.BYTE)),
        ("Persist", w.DWORD), ("AttributeCount", w.DWORD),
        ("Attributes", c.c_void_p), ("TargetAlias", w.LPWSTR), ("UserName", w.LPWSTR),
    ]


def _failure() -> SecretStoreError:
    code = c.get_last_error()
    return SecretStoreError({1168: "missing", 1312: "unavailable", 5: "denied"}.get(code, "storage"))


class WindowsSecretStore:
    """Desktop adapter only. Caller must enforce setup/execution authorization.

    References are identifiers, not grants. put replaces the exact reference.
    delete is idempotent (False means absent); get absence requires re-entry.
    """

    def __init__(self, *, mode: str = "desktop"):
        if sys.platform != "win32" or mode != "desktop":
            raise SecretStoreError("unsupported")
        try:
            # LOAD_LIBRARY_SEARCH_SYSTEM32: never load an application-local DLL.
            self._api = c.WinDLL("Advapi32.dll", use_last_error=True, winmode=0x800)
            pointer = c.POINTER(_Credential)
            self._api.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(pointer)]
            self._api.CredReadW.restype = w.BOOL
            self._api.CredWriteW.argtypes = [pointer, w.DWORD]
            self._api.CredWriteW.restype = w.BOOL
            self._api.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
            self._api.CredDeleteW.restype = w.BOOL
            self._api.CredFree.argtypes = [c.c_void_p]
            self._api.CredFree.restype = None
        except Exception:
            raise SecretStoreError("unavailable") from None

    @staticmethod
    def _target(ref: CredentialRef) -> str:
        if type(ref) is not CredentialRef:
            raise SecretStoreError("invalid_reference")
        # Revalidate even if frozen dataclass was bypassed by a caller.
        return CredentialRef(ref.value).target

    def get(self, ref: CredentialRef) -> SecretValue:
        target = self._target(ref)
        pointer = c.POINTER(_Credential)()
        try:
            if not self._api.CredReadW(target, 1, 0, c.byref(pointer)):
                raise _failure()
            try:
                item = pointer.contents
                if item.Type != 1 or not 1 <= item.CredentialBlobSize <= 2560 or not item.CredentialBlob:
                    raise SecretStoreError("storage")
                return SecretValue(c.string_at(item.CredentialBlob, item.CredentialBlobSize))
            finally:
                # Clear only the secret blob in the allocated return block, then free.
                item = pointer.contents
                if item.CredentialBlob and 0 < item.CredentialBlobSize <= 2560:
                    c.memset(item.CredentialBlob, 0, item.CredentialBlobSize)
                self._api.CredFree(pointer)
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError("storage") from None

    def put(self, ref: CredentialRef, value: SecretValue) -> None:
        target = self._target(ref)
        if type(value) is not SecretValue:
            raise SecretStoreError("invalid_value")
        blob = (w.BYTE * len(value._buffer)).from_buffer_copy(value._buffer)
        if not 1 <= len(blob) <= 2560:
            raise SecretStoreError("invalid_value")
        try:
            item = _Credential()
            item.Type, item.TargetName = 1, target
            item.CredentialBlobSize, item.CredentialBlob = len(blob), blob
            item.Persist, item.UserName = 2, "OmniForge"
            if not self._api.CredWriteW(c.byref(item), 0):
                raise _failure()
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError("storage") from None
        finally:
            c.memset(blob, 0, len(blob))

    def delete(self, ref: CredentialRef) -> bool:
        target = self._target(ref)
        try:
            if self._api.CredDeleteW(target, 1, 0):
                return True
            error = _failure()
            if error.code == "missing":
                return False
            raise error
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError("storage") from None
