"""Authored synthetic corpus; fixed identities make portable replay deterministic."""
import hashlib
from pathlib import Path
from uuid import UUID

from packages.contracts.evidence.capture import parse_capture
from packages.contracts.export.models import Manifest


def uid(value):
    return UUID(int=value)


def fixture():
    root = Path(__file__).parent
    data = [(root / name).read_bytes() for name in ("sample.txt", "events.json", "events.csv")]
    # A byte-exact mixed-newline derivation and complete empty collection.
    data += [b"First\r\nSecond \xce\xb2\nThird\r\n", b""]
    artifacts = [{"id": uid(i+10), "sha256": hashlib.sha256(value).hexdigest(),
                  "bytes": len(value), "path": "blobs/"+hashlib.sha256(value).hexdigest()}
                 for i, value in enumerate(data)]
    provenance = {"source_system": "synthetic", "source_entity": "fixture",
                  "source_id": "original-a", "migration_version": "portable-v1"}
    associations = [{"id": uid(i+20), "case_id": uid(2), "artifact_id": artifact["id"],
                     "source_id": uid(i+30), "original_name": "synthetic-"+str(i)+".bin",
                     "media_type": ("text/plain", "application/json", "text/csv", "text/plain", "text/plain")[i],
                     "imported_at": "2026-10-23T15:00:00Z",
                     "provenance": {**provenance, "source_id": "original-"+str(i)},
                     **parse_capture("2026-10-23T12:34:56.123456+08:00" if i == 0 else None)}
                    for i, artifact in enumerate(artifacts)]
    # Same immutable bytes, separate source association, never merged origins.
    associations.append({**associations[0], "id": uid(25), "source_id": uid(35),
                         "provenance": {**provenance, "source_id": "independent-origin"}})
    value = {"bundle_id": uid(1), "case_id": uid(2), "artifacts": artifacts,
        "associations": associations,
        "locations": [
            {"id": uid(40), "association_id": uid(20), "sha256": artifacts[0]["sha256"], "kind": "bytes", "start": 6, "end": 12},
            {"id": uid(41), "association_id": uid(23), "sha256": artifacts[3]["sha256"], "kind": "lines", "start": 2, "end": 3, "encoding": "utf-8"}],
        "observations": [
            {"id": uid(50), "source_id": uid(34), "coverage": "complete", "collection_count": 0, "outcome": "not_observed", "location_ids": []},
            {"id": uid(51), "source_id": uid(34), "coverage": "partial", "collection_count": 0, "outcome": "insufficient_data", "location_ids": []}],
        "claims": [{"id": uid(60), "text": "Synthetic line is present; source authenticity remains unverified.",
                    "verification": "supported", "location_ids": [uid(40), uid(41)]}],
        "derivations": [{"id": uid(70), "input_artifact_ids": [uid(10)], "output_artifact_id": uid(13),
                         "tool": "synthetic-fixture", "tool_version": "1", "options_sha256": hashlib.sha256(b"{}").hexdigest(),
                         "coverage": "partial", "warnings": ["Synthetic transformation, no semantic equivalence asserted"]}],
        "legacy_envelopes": [{"id": uid(80), "provenance": provenance, "original_state": "insufficient_data",
                              "unsupported_reason": "Synthetic preservation envelope only"}]}
    return Manifest.model_validate(value), {item["sha256"]: raw for item, raw in zip(artifacts, data)}


if __name__ == "__main__":
    from packages.contracts.export.portable import canonical
    manifest, _ = fixture()
    (Path(__file__).parent / "manifest.json").write_bytes(canonical(manifest))
