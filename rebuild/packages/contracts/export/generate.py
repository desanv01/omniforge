"""Regenerate versioned JSON Schema from the executable strict models."""
import json
from pathlib import Path

from packages.contracts.evidence.capture import CaptureTime
from packages.contracts.export.models import Manifest


if __name__ == "__main__":
    for model, path, name in (
        (Manifest, Path(__file__).with_name("manifest.schema.json"), "manifest"),
        (CaptureTime, Path(__file__).parents[1] / "evidence/capture.schema.json", "capture"),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = "urn:omniforge:portable-evidence:" + name + ":1"
        path.write_text(json.dumps(schema, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("Generated portable manifest/capture JSON Schemas")
