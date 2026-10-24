"""B1 Run journal DTOs. No execution, provider admission or live stream."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from services.api.contracts import ContractModel


class InputRef(ContractModel):
    association_id: UUID
    revision: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)


class InputSnapshot(InputRef):
    artifact_id: UUID
    source_id: UUID
    bytes: int = Field(ge=0, strict=True)
    coverage: Literal["unknown"] = "unknown"


class RunBudget(ContractModel):
    calls: Literal[0] = 0
    input_tokens: Literal[0] = 0
    output_tokens: Literal[0] = 0
    tool_bytes: Literal[0] = 0
    wall_seconds: int = Field(default=10, ge=1, le=60, strict=True)

    @field_validator("calls", "input_tokens", "output_tokens", "tool_bytes", mode="before")
    @classmethod
    def exact_zero(cls, value):
        if type(value) is not int or value != 0:
            raise ValueError("Only integer zero is admitted")
        return value


class RunCreate(ContractModel):
    kind: Literal["synthetic-read-only-v1"] = "synthetic-read-only-v1"
    policy_version: Literal["local-read-only-v1"] = "local-read-only-v1"
    input_refs: list[InputRef] = Field(default_factory=list, max_length=32)
    budget: RunBudget = Field(default_factory=RunBudget)

    @model_validator(mode="after")
    def unique_inputs(self):
        if len({ref.association_id for ref in self.input_refs}) != len(self.input_refs):
            raise ValueError("Duplicate input associations")
        return self


class RunCancel(ContractModel):
    expected_revision: int = Field(ge=1, strict=True)


class UnusedUsage(ContractModel):
    calls: Literal[0] = 0
    input_tokens: Literal[0] = 0
    output_tokens: Literal[0] = 0
    tool_bytes: Literal[0] = 0
    state: Literal["known"] = "known"
    provenance: Literal["No work dispatched"] = "No work dispatched"


class Run(ContractModel):
    id: UUID
    case_id: UUID
    kind: Literal["synthetic-read-only-v1"]
    schema_version: Literal[1] = 1
    revision: int = Field(ge=1)
    status: Literal["queued", "cancel_requested", "canceled"]
    outcome: None = None
    terminal_reason: Literal["canceled_before_dispatch"] | None = None
    attempt_id: None = None
    input_refs: list[InputSnapshot]
    policy_version: Literal["local-read-only-v1"]
    budget: RunBudget
    usage: UnusedUsage
    provider_profile_ref: None = None
    output_refs: list[UUID] = Field(default_factory=list, max_length=0)
    created_at: datetime
    started_at: None = None
    finished_at: datetime | None = None


class RunEvent(ContractModel):
    run_id: UUID
    sequence: int = Field(ge=1)
    type: Literal["queued", "cancel_requested", "canceled"]
    attempt_id: None = None
    occurred_at: datetime
    payload: dict[str, str]
    schema_version: Literal[1] = 1


class RunEventPage(ContractModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    items: list[RunEvent] = Field(max_length=100)
    next_after: int = Field(ge=0)
    has_more: bool
