from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from adapters.models.contracts import Budget
from services.api.contracts import ContractModel, Capability

ENDPOINT = "https://api.deepseek.com/chat/completions"
CAP_FIELDS = tuple(Budget.model_fields)


def default_caps():
    return Budget(calls=2, input_tokens=32768, output_tokens=1024, tool_bytes=32, wall_seconds=30)


def printable(value):
    if value is not None and (not value.isascii() or not value.isprintable() or value != value.strip()):
        raise ValueError("Expected bounded printable text")
    return value


class ProviderProfileCreate(ContractModel):
    label: str = Field(min_length=1, max_length=120)
    endpoint: Literal["https://api.deepseek.com/chat/completions"] = ENDPOINT
    model: str = Field(min_length=1, max_length=120)
    caps: Budget = Field(default_factory=default_caps)
    _printable = field_validator("label", "model")(printable)


class ProviderProfileUpdate(ContractModel):
    expected_revision: int = Field(ge=1, le=2147483646, strict=True)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: Literal["https://api.deepseek.com/chat/completions"] | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)
    caps: Budget | None = None
    enabled: bool | None = Field(default=None, strict=True)
    _printable = field_validator("label", "model")(printable)

    @model_validator(mode="after")
    def changes(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, key) is None for key in fields):
            raise ValueError("Expected nonnull metadata change")
        return self


class ProviderProfileView(ContractModel):
    schema_version: Literal[1] = 1
    id: UUID
    case_id: UUID
    revision: int
    label: str
    endpoint: Literal["https://api.deepseek.com/chat/completions"]
    model: str
    caps: Budget
    enabled: bool = False
    credential_configured: bool = False
    binding_status: Literal["unconfigured", "pending", "attached", "unresolved"] = "unconfigured"
    created_at: datetime


class ProviderProfilePage(ContractModel):
    items: list[ProviderProfileView]
    next_cursor: str | None


class ProviderProfileDiagnostics(ContractModel):
    schema_version: Literal[1] = 1
    profile_id: UUID
    revision: int
    enabled: bool = False
    credential_configured: bool = False
    binding_status: Literal["unconfigured", "pending", "attached", "unresolved"] = "unconfigured"
    features: dict[str, Capability]
    provenance: Literal["passive persisted metadata only; no credential-store or transport operations"] = "passive persisted metadata only; no credential-store or transport operations"
