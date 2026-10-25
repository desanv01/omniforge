"""Bounded synthetic Run journal/execution DTOs; no provider or live stream."""
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
    provenance: Literal["No work dispatched", "Synthetic execution; no provider or tools"] = "No work dispatched"


class OutputRef(ContractModel):
    id: UUID
    kind: Literal["run_output"] = "run_output"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)


class UnknownUsage(ContractModel):
    calls: None = None
    input_tokens: None = None
    output_tokens: None = None
    tool_bytes: None = None
    state: Literal["unknown"] = "unknown"
    provenance: Literal["Usage not measured"] = "Usage not measured"


class Run(ContractModel):
    id: UUID
    case_id: UUID
    kind: Literal["synthetic-read-only-v1"]
    schema_version: Literal[1] = 1
    revision: int = Field(ge=1)
    status: Literal["queued", "claimed", "running", "succeeded", "failed", "interrupted", "uncertain", "cancel_requested", "canceled"]
    outcome: Literal["synthetic_complete"] | None = None
    terminal_reason: Literal["canceled_before_dispatch", "canceled_after_cleanup", "lease_expired", "synthetic_failure", "uncertain_effect"] | None = None
    attempt_id: UUID | None = None
    input_refs: list[InputSnapshot]
    policy_version: Literal["local-read-only-v1"]
    budget: RunBudget
    usage: UnusedUsage | UnknownUsage
    cancellation_id: UUID | None = None
    cancel_generation: int = Field(default=0, ge=0, le=1, strict=True)
    cleanup_status: Literal["not_requested", "pending", "succeeded", "failed", "unknown"] = "not_requested"
    provider_profile_ref: None = None
    output_refs: list[OutputRef] = Field(default_factory=list, max_length=1)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEvent(ContractModel):
    run_id: UUID
    sequence: int = Field(ge=1)
    type: Literal["queued", "cancel_requested", "canceled", "running", "lease_renewed", "interrupted", "succeeded", "failed", "uncertain", "delivery_rearmed", "cleanup_received", "cleanup_reopened", "cleanup_unresolved"]
    attempt_id: UUID | None = None
    occurred_at: datetime
    payload: dict[str, str]
    schema_version: Literal[1] = 1


class RunEventPage(ContractModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    items: list[RunEvent] = Field(max_length=100)
    next_after: int = Field(ge=0)
    has_more: bool
