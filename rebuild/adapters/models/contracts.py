from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adapters.secrets.store import CredentialRef, SecretValue


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Location(DTO):
    id: UUID
    association_id: UUID
    artifact_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_byte: int = Field(ge=0)
    end_byte: int = Field(gt=0)

    @model_validator(mode="after")
    def bounds(self):
        if not 0 < self.end_byte - self.start_byte <= 1048576:
            raise ValueError("invalid range")
        return self


class Citation(DTO):
    location_id: UUID
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Observation(DTO):
    text: str = Field(min_length=1, max_length=8192)
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=32)
    coverage: Literal["partial", "unknown"] = "partial"


class Claim(DTO):
    text: str = Field(min_length=1, max_length=8192)
    supporting: tuple[Citation, ...] = Field(min_length=1, max_length=32)
    contradicting: tuple[Citation, ...] = Field(max_length=32)
    verification: Literal["unverified"] = "unverified"
    uncertainty: str = Field(min_length=1, max_length=1024)


class Answer(DTO):
    observations: tuple[Observation, ...] = Field(max_length=32)
    claims: tuple[Claim, ...] = Field(max_length=32)
    outcome: Literal["answered", "insufficient_data"]
    reason: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def supported(self):
        if self.outcome == "answered" and not (self.observations or self.claims):
            raise ValueError("answered requires evidence")
        return self


class Measurement(DTO):
    value: int | None = Field(default=None, ge=0)
    state: Literal["known", "estimated", "unknown"] = "unknown"
    provenance: str

    @model_validator(mode="after")
    def consistent(self):
        if (self.value is None) != (self.state == "unknown"):
            raise ValueError("unknown requires null")
        return self


@dataclass(frozen=True)
class Usage:
    calls: int
    input_tokens: Measurement
    output_tokens: Measurement
    cost: Measurement = field(default_factory=lambda: Measurement(provenance="no pricing proof"))
    tool_bytes: int = 0
    reserved_input: int = 0
    reserved_output: int = 0
    known_input_subtotal: int = 0
    known_output_subtotal: int = 0
    charged_input: int = 0
    charged_output: int = 0


class Budget(DTO):
    calls: int = Field(ge=1, le=16)
    input_tokens: int = Field(ge=1, le=1000000)
    output_tokens: int = Field(ge=1, le=100000)
    wall_seconds: int = Field(ge=1, le=300)
    tool_bytes: int = Field(ge=0, le=1048576)


@dataclass(frozen=True)
class Profile:
    id: UUID
    revision: int
    endpoint: str
    model: str
    credential_ref: CredentialRef
    # No flags claim live tool/schema/stream/search support.


@dataclass(frozen=True)
class ReadOnlyContext:
    case_id: UUID
    policy_version: str
    objective: str
    locations: tuple[Location, ...]
    # Application binds these to authenticated principal, case and current grants.
    read_range: Callable[[UUID, str, int, int], bytes] = field(repr=False)
    authorize_profile: Callable[[Profile], bool] = field(repr=False)
    canceled: Callable[[], bool] = field(repr=False)


@dataclass(frozen=True)
class ProviderResult:
    answer: Answer | None
    usage: Usage
    error: str | None = None


class Transport(Protocol):
    def complete(self, profile: Profile, secret: SecretValue, payload: dict, timeout: float) -> dict: ...
