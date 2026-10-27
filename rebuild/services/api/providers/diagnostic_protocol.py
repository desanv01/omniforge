"""Selected in-process diagnostic messages; no serialization or live factories."""
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID


def integer(value, maximum=1_000_000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid diagnostic integer")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Reservation:
    operation_id: UUID
    round_seq: int
    payload_sha256: str
    input_estimate: int
    output_max: int

    def __post_init__(self):
        if type(self.operation_id) is not UUID or type(self.round_seq) is not int or self.round_seq not in (1, 2):
            raise ValueError("invalid diagnostic identity")
        if (type(self.payload_sha256) is not str or len(self.payload_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.payload_sha256)):
            raise ValueError("invalid diagnostic digest")
        integer(self.input_estimate, 32768)
        integer(self.output_max, 512)
        if not self.input_estimate or not self.output_max:
            raise ValueError("empty diagnostic reservation")

    @property
    def replay_digest(self):
        return digest([str(self.operation_id), self.round_seq, self.payload_sha256,
                       self.input_estimate, self.output_max])


@dataclass(frozen=True)
class Observation:
    reservation: Reservation
    input_tokens: int | None
    output_tokens: int | None
    provenance: Literal["provider_reported", "absent"]
    safe_outcome: Literal["response_received", "invalid_response", "transport_failed"]
    charged_input: int
    charged_output: int

    def __post_init__(self):
        if type(self.reservation) is not Reservation:
            raise ValueError("invalid diagnostic reservation")
        for value in (self.input_tokens, self.output_tokens):
            if value is not None:
                integer(value)
        if self.provenance not in ("provider_reported", "absent") or self.safe_outcome not in (
                "response_received", "invalid_response", "transport_failed"):
            raise ValueError("invalid diagnostic outcome")
        if (self.provenance == "absent") != (self.input_tokens is None and self.output_tokens is None):
            raise ValueError("invalid diagnostic provenance")
        for charged, reserved, reported in ((self.charged_input, self.reservation.input_estimate, self.input_tokens),
                                            (self.charged_output, self.reservation.output_max, self.output_tokens)):
            integer(charged)
            if charged != max(reserved, reported or 0):
                raise ValueError("invalid diagnostic charge")

    @property
    def replay_digest(self):
        return digest([self.reservation.replay_digest, self.input_tokens, self.output_tokens,
                       self.provenance, self.safe_outcome, self.charged_input, self.charged_output])
