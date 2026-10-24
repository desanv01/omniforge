"""Portable evidence v1: identity, origins, exact locations and coverage."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from packages.contracts.evidence.capture import CaptureTime


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value and type(value["schema_version"]) is not int:
            raise ValueError("Schema version must be an integer")
        return value


class Provenance(StrictModel):
    source_system: str = Field(max_length=100)
    source_entity: str = Field(max_length=100)
    source_id: str = Field(max_length=200)
    source_commit: str | None = Field(default=None, max_length=100)
    source_schema_version: str | None = Field(default=None, max_length=100)
    source_revision: str | None = Field(default=None, max_length=100)
    migration_version: str = Field(max_length=100)


class Artifact(StrictModel):
    id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(strict=True, ge=0, le=25 * 1024 * 1024)
    path: str

    @model_validator(mode="after")
    def content_address(self):
        if self.path != "blobs/" + self.sha256:
            raise ValueError("Artifact path must be canonical relative content address")
        return self


class Association(CaptureTime):
    id: UUID
    case_id: UUID
    artifact_id: UUID
    source_id: UUID
    original_name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(max_length=128)
    imported_at: AwareDatetime
    provenance: Provenance


class Location(StrictModel):
    id: UUID
    association_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["bytes", "lines"]
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=1)
    encoding: Literal["utf-8"] | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.kind == "bytes" and (self.start >= self.end or self.encoding is not None):
            raise ValueError("Bytes use half-open bounds without text encoding")
        if self.kind == "lines" and (self.start < 1 or self.start > self.end or self.encoding != "utf-8"):
            raise ValueError("Lines use one-based inclusive bounds and explicit UTF8")
        return self


class Observation(StrictModel):
    id: UUID
    source_id: UUID
    coverage: Literal["complete", "partial", "unknown"]
    collection_count: int = Field(strict=True, ge=0)
    outcome: Literal["observed", "not_observed", "insufficient_data"]
    location_ids: list[UUID] = Field(max_length=256)

    @model_validator(mode="after")
    def negative_coverage(self):
        if self.outcome == "not_observed" and self.coverage != "complete":
            raise ValueError("Incomplete collection cannot establish a negative")
        return self


class Claim(StrictModel):
    id: UUID
    text: str = Field(max_length=4000)
    verification: Literal["unverified", "supported", "contradicted"]
    location_ids: list[UUID] = Field(max_length=256)

    @model_validator(mode="after")
    def cited(self):
        if self.verification != "unverified" and not self.location_ids:
            raise ValueError("Verified interpretations require evidence locations")
        return self


class Derivation(StrictModel):
    id: UUID
    input_artifact_ids: list[UUID] = Field(min_length=1, max_length=64)
    output_artifact_id: UUID
    tool: str = Field(max_length=100)
    tool_version: str = Field(max_length=100)
    options_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage: Literal["complete", "partial", "unknown"]
    warnings: list[str] = Field(max_length=20)


class LegacyEnvelope(StrictModel):
    id: UUID
    provenance: Provenance
    unsupported_reason: str = Field(max_length=500)
    original_state: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    # Raw legacy payload/credentials are intentionally outside this prototype.
    payload_artifact_id: UUID | None = None
