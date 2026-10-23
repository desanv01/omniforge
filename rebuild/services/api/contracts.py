from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DependencyHealth(ContractModel):
    status: Literal["not_connected", "ready", "unavailable", "unverified"]
    ready: bool = False


class Health(ContractModel):
    schema_version: Literal[1] = 1
    service: Literal["omniforge-api"] = "omniforge-api"
    status: Literal["alive"] = "alive"
    ready: Literal[False] = False
    database: DependencyHealth
    artifacts: DependencyHealth
    provider: DependencyHealth
    scheduler: DependencyHealth
    migration_version: str | None = None


class ErrorEnvelope(ContractModel):
    schema_version: Literal[1] = 1
    code: str
    category: Literal["validation", "conflict", "not_found", "unauthenticated", "forbidden",
                      "unsupported", "storage", "internal", "method_not_allowed"]
    message: str
    retryable: bool
    request_id: UUID
    evidence_refs: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)


class CaseCreate(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(default="", max_length=4000)
    policy_profile_ref: str = Field(default="local-read-only-v1", max_length=100)


class Case(ContractModel):
    schema_version: Literal[1] = 1
    id: UUID
    revision: int
    title: str
    objective: str
    policy_profile_ref: str
    status: Literal["open"] = "open"
    created_at: datetime
    updated_at: datetime


class CasePage(ContractModel):
    items: list[Case]
    next_cursor: str | None


class ArtifactAssociation(ContractModel):
    schema_version: Literal[1] = 1
    id: UUID
    case_id: UUID
    artifact_id: UUID
    source_id: UUID
    sha256: str
    bytes: int
    media_type: str
    original_name: str
    captured_at: datetime | None
    imported_at: datetime
    publication_status: Literal["pending", "committed", "failed"]
    warnings: list[str] = Field(default_factory=list)
    revision: int


class Capability(ContractModel):
    status: Literal["available", "unverified", "unsupported"]
    reason: str


class ArtifactPage(ContractModel):
    items: list[ArtifactAssociation]
    next_cursor: str | None


class Capabilities(ContractModel):
    schema_version: Literal[1] = 1
    features: dict[str, Capability]


ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope, "description": description,
             "headers": {"X-Request-ID": {"schema": {"type": "string", "format": "uuid"}},
                         **({"Allow": {"schema": {"type": "string"}}} if status == 405 else {}),
                         **({"WWW-Authenticate": {"schema": {"type": "string"}}} if status == 401 else {})}}
    for status, description in {
        401: "Bearer authentication required", 403: "Case grant required", 404: "Resource not found",
        405: "Method not allowed", 409: "Idempotency or revision conflict", 413: "Upload limit exceeded",
        415: "Unsupported media type", 422: "Sanitized request validation error",
        500: "Sanitized internal error", 503: "Dependency or publication unavailable",
    }.items()
}
