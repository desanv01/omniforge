"""Values must never enter DTOs, logs, exports, or exception messages."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4


class SecretStoreError(Exception):
    """Only fixed codes/messages cross the storage boundary."""

    _MESSAGES = {
        "invalid_reference": "Invalid credential reference.",
        "invalid_value": "Credential value must contain 1 to 2560 bytes.",
        "missing": "Credential unavailable; re-enter it using setup.",
        "unsupported": "Credential storage requires supported Windows desktop mode.",
        "unavailable": "Credential storage unavailable; check the intended logon identity.",
        "denied": "Credential storage access denied.",
        "storage": "Credential storage operation failed.",
    }

    def __init__(self, code: str):
        self.code = code if code in self._MESSAGES else "storage"
        super().__init__(self._MESSAGES[self.code])


@dataclass(frozen=True)
class CredentialRef:
    """Opaque nonsecret reference. Namespace is fixed; arbitrary targets forbidden."""

    value: str

    def __post_init__(self):
        valid = False
        if isinstance(self.value, str):
            parts = self.value.split(":")
            if len(parts) == 4 and parts[:2] == ["wincred", "omniforge"] and parts[2] in ("v1", "test"):
                try:
                    parsed = UUID(parts[3])
                    valid = str(parsed) == parts[3] and parsed.version == 4
                except ValueError:
                    pass
        if not valid:
            raise SecretStoreError("invalid_reference")

    @classmethod
    def new(cls, *, testing: bool = False):
        return cls(f"wincred:omniforge:{'test' if testing else 'v1'}:{uuid4()}")

    @property
    def target(self) -> str:
        return "OmniForge/" + self.value


class SecretValue:
    """Redacted wrapper, explicit bytes access, best-effort owned-buffer clearing.

    Python/callers may retain copies; this is not guaranteed memory erasure.
    """

    __slots__ = ("_buffer",)

    def __init__(self, value: bytes):
        if not isinstance(value, bytes) or not 1 <= len(value) <= 2560:
            raise SecretStoreError("invalid_value")
        self._buffer = bytearray(value)

    def reveal(self) -> bytes:
        if not self._buffer:
            raise SecretStoreError("invalid_value")
        return bytes(self._buffer)

    def clear(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._buffer.clear()

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    __str__ = __repr__

    def __reduce_ex__(self, protocol):
        raise TypeError("SecretValue serialization is disabled.")


class SecretStore(Protocol):
    def get(self, ref: CredentialRef) -> SecretValue: ...
    def put(self, ref: CredentialRef, value: SecretValue) -> None: ...
    def delete(self, ref: CredentialRef) -> bool: ...
