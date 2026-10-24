"""Bound enrollment sequencing with injected I/O only; no CLI or OS effects.

Callbacks are trusted in-process application boundaries, never HTTP-supplied
authority. Backend owns durable reservations, current grants and post-put attach.
"""

from dataclasses import dataclass, field
from typing import Callable, Literal
from uuid import UUID

from .store import CredentialRef, SecretStore, SecretValue


class EnrollmentError(Exception):
    _MESSAGES = {
        "denied": "Credential enrollment denied before storage.",
        "recovery_required": "Credential enrollment requires explicit recovery.",
        "uncertain": "Credential write outcome is uncertain; do not retry automatically.",
    }

    def __init__(self, code: str):
        self.code = code if type(code) is str and code in self._MESSAGES else "denied"
        super().__init__(self._MESSAGES[self.code])


def _request_key(item) -> tuple:
    values = (item.operation_id, item.principal_id, item.case_id, item.profile_id)
    if any(type(value) is not UUID for value in values):
        raise EnrollmentError("denied")
    if type(item.expected_revision) is not int or item.expected_revision <= 0:
        raise EnrollmentError("denied")
    return (*values, item.expected_revision)


def _ref_key(ref: CredentialRef) -> str:
    if type(ref) is not CredentialRef:
        raise EnrollmentError("denied")
    # Revalidate even if frozen dataclass protections were bypassed elsewhere.
    value = CredentialRef(ref.value).value
    if not value.startswith("wincred:omniforge:v1:"):
        raise EnrollmentError("denied")
    return value


def _binding_key(binding) -> tuple:
    if type(binding) is not EnrollmentBinding:
        raise EnrollmentError("denied")
    return (*_request_key(binding), _ref_key(binding.credential_ref))


@dataclass(frozen=True)
class EnrollmentRequest:
    operation_id: UUID
    principal_id: UUID
    case_id: UUID
    profile_id: UUID
    expected_revision: int

    def __post_init__(self):
        _request_key(self)


@dataclass(frozen=True)
class EnrollmentBinding(EnrollmentRequest):
    credential_ref: CredentialRef = field(repr=False)

    def __post_init__(self):
        _request_key(self)
        _ref_key(self.credential_ref)


@dataclass(frozen=True)
class EnrollmentReceipt(EnrollmentRequest):
    attached_revision: int
    status: Literal["attached"] = "attached"

    def __post_init__(self):
        _request_key(self)
        if (type(self.attached_revision) is not int or self.attached_revision <= 0
                or self.status != "attached"):
            raise EnrollmentError("denied")


@dataclass(frozen=True)
class Reservation:
    disposition: Literal["ready", "settled", "blocked"]
    binding: EnrollmentBinding | None = None
    receipt: EnrollmentReceipt | None = None


def enroll_new(*, request: EnrollmentRequest,
               reserve: Callable[[EnrollmentBinding], Reservation],
               hidden_input: Callable[[], SecretValue],
               authorize_put: Callable[[EnrollmentBinding], EnrollmentBinding],
               store: SecretStore) -> EnrollmentBinding | EnrollmentReceipt:
    """Reserve, input, freshly authorize, then single put; always clear input.

    reserve must commit/close its transaction before returning. authorize_put
    must freshly check the complete pending tuple and current authority, then
    close its transaction before returning that exact binding. No transaction
    may span input or store I/O. Successful return is NOT attachment/activation.
    """
    value = None
    write_started = False
    try:
        if type(request) is not EnrollmentRequest:
            raise EnrollmentError("denied")
        request_key = _request_key(request)
        ref = CredentialRef.new()
        ref_key = _ref_key(ref)
        candidate = EnrollmentBinding(*request_key, credential_ref=ref)
        expected = (*request_key, ref_key)
        reservation = reserve(candidate)
        if type(reservation) is not Reservation or _request_key(request) != request_key:
            raise EnrollmentError("denied")
        if reservation.disposition == "settled":
            receipt = reservation.receipt
            if (reservation.binding is not None or type(receipt) is not EnrollmentReceipt
                    or _request_key(receipt) != request_key
                    or type(receipt.attached_revision) is not int
                    or receipt.attached_revision <= 0 or receipt.status != "attached"):
                raise EnrollmentError("denied")
            return receipt
        if reservation.disposition == "blocked":
            if reservation.binding is not None or reservation.receipt is not None:
                raise EnrollmentError("denied")
            raise EnrollmentError("recovery_required")
        if (reservation.disposition != "ready" or reservation.receipt is not None
                or _binding_key(reservation.binding) != expected
                or _binding_key(candidate) != expected):
            raise EnrollmentError("denied")
        binding = reservation.binding
        value = hidden_input()
        if type(value) is not SecretValue or not 1 <= len(value._buffer) <= 2560:
            raise EnrollmentError("denied")
        if (_request_key(request) != request_key or _binding_key(binding) != expected
                or _ref_key(ref) != ref_key):
            raise EnrollmentError("denied")
        authorized = authorize_put(binding)
        # Compare primitive immutable snapshots, not just mutable object equality.
        if (_binding_key(authorized) != expected or _binding_key(binding) != expected
                or _request_key(request) != request_key or _ref_key(ref) != ref_key):
            raise EnrollmentError("denied")
        write_started = True
        store.put(ref, value)
        return binding
    except (Exception, KeyboardInterrupt) as error:
        code = "uncertain" if write_started else "denied"
        if not write_started and isinstance(error, EnrollmentError) and error.code == "recovery_required":
            code = "recovery_required"
        raise EnrollmentError(code) from None
    finally:
        if type(value) is SecretValue:
            value.clear()
