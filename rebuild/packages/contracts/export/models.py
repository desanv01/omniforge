"""Versioned portable manifest. Validation does not grant execution authority."""
import re
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from packages.contracts.evidence.models import (Artifact, Association, Claim, Derivation,
    LegacyEnvelope, Location, Observation, StrictModel)

PRIVATE_PATH = re.compile(r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|\\\\|(?<![a-z0-9:/])/(?!/))")
SECRET_KEY = re.compile(r"(?i)(?:password|api[_-]?key|authorization|bearer\s+|secret[_:=]|access[_-]?token)")


def safe_metadata(value):
    if isinstance(value, str) and (PRIVATE_PATH.search(value) or SECRET_KEY.search(value)):
        raise ValueError("Private path or credential-shaped metadata is not portable")
    if isinstance(value, dict):
        for key, item in value.items():
            safe_metadata(key)
            safe_metadata(item)
    elif isinstance(value, list):
        for item in value:
            safe_metadata(item)


class Manifest(StrictModel):
    schema_version: Literal[1] = 1
    bundle_id: UUID
    case_id: UUID
    artifacts: list[Artifact] = Field(max_length=64)
    associations: list[Association] = Field(max_length=128)
    locations: list[Location] = Field(max_length=256)
    observations: list[Observation] = Field(max_length=128)
    claims: list[Claim] = Field(max_length=128)
    derivations: list[Derivation] = Field(default_factory=list, max_length=64)
    legacy_envelopes: list[LegacyEnvelope] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def references(self):
        def unique(items):
            result = {item.id: item for item in items}
            if len(result) != len(items):
                raise ValueError("Duplicate entity identity")
            return result
        artifacts, associations, locations = unique(self.artifacts), unique(self.associations), unique(self.locations)
        for group in (self.observations, self.claims, self.derivations, self.legacy_envelopes):
            unique(group)
        if len({item.sha256 for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("Identical bytes must share one artifact identity")
        if sum(item.bytes for item in self.artifacts) > 64 * 1024 * 1024:
            raise ValueError("Bundle exceeds aggregate byte limit")
        for item in self.associations:
            if item.case_id != self.case_id or item.artifact_id not in artifacts:
                raise ValueError("Association outside bundle case/artifact set")
            if any(c in item.original_name for c in ("/", "\\", ":")):
                raise ValueError("Original name must be metadata basename")
        for item in self.locations:
            if item.association_id not in associations:
                raise ValueError("Unknown citation origin")
            artifact = artifacts[associations[item.association_id].artifact_id]
            if item.sha256 != artifact.sha256 or (item.kind == "bytes" and item.end > artifact.bytes):
                raise ValueError("Citation hash or byte bound mismatch")
        source_ids = {item.source_id for item in self.associations}
        for item in self.observations:
            if item.source_id not in source_ids:
                raise ValueError("Observation source missing")
            for ref in item.location_ids:
                if ref not in locations or associations[locations[ref].association_id].source_id != item.source_id:
                    raise ValueError("Observation citation belongs to another source")
        for item in [*self.observations, *self.claims]:
            if any(ref not in locations for ref in item.location_ids):
                raise ValueError("Unknown evidence location")
        for item in self.derivations:
            if item.output_artifact_id not in artifacts or any(ref not in artifacts for ref in item.input_artifact_ids):
                raise ValueError("Derivation artifact missing")
        for item in self.legacy_envelopes:
            if item.payload_artifact_id is not None and item.payload_artifact_id not in artifacts:
                raise ValueError("Legacy payload artifact missing")
        safe_metadata(self.model_dump(mode="json"))
        return self
