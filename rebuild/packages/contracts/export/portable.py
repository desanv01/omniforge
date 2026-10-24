"""Bounded directory-bundle validation/round trip. Never extracts archives or deletes."""
import csv
import hashlib
import io
import json
import html
import re
from pathlib import Path
import stat

from pydantic import ValidationError

from packages.contracts.export.models import Manifest


class BundleError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(manifest):
    return (json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def report(manifest):
    lines = ["# Portable evidence report", "", f"Bundle: {manifest.bundle_id}",
             f"Case: {manifest.case_id}", "", "## Original evidence", ""]
    artifacts = {item.id: item for item in manifest.artifacts}
    for association in manifest.associations:
        artifact = artifacts[association.artifact_id]
        lines.append(f"- Origin `{association.id}` / source `{association.source_id}`: "
                     f"[original bytes]({artifact.path}), SHA256 `{artifact.sha256}`, {artifact.bytes} bytes.")
        original = association.captured_at_original or "unknown"
        lines.append(f"  Capture provenance: {association.captured_at_provenance}; original `{original}`.")
    lines += ["", "## Evidence locations", ""]
    for location in manifest.locations:
        lines.append(f"- `{location.id}`: origin `{location.association_id}`, {location.kind} "
                     f"{location.start}..{location.end}, SHA256 `{location.sha256}`.")
    lines += ["", "## Observations and interpretations", ""]
    for observation in manifest.observations:
        lines.append(f"- Observation `{observation.id}`: {observation.outcome}; coverage {observation.coverage}; "
                     f"count {observation.collection_count}; locations " + ", ".join(f"`{ref}`" for ref in observation.location_ids))
    for claim in manifest.claims:
        # Avoid active user-supplied Markdown/HTML; report text as a JSON string.
        escaped = html.escape(json.dumps(claim.text, ensure_ascii=True))
        escaped = re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", escaped)
        lines.append(f"- Claim `{claim.id}`: {escaped}; {claim.verification}; locations " + ", ".join(f"`{ref}`" for ref in claim.location_ids))
    lines += ["", "## Derivations and preserved legacy envelopes", ""]
    for item in manifest.derivations:
        lines.append(f"- Derivation `{item.id}`: inputs " + ", ".join(f"`{ref}`" for ref in item.input_artifact_ids)
                     + f" -> `{item.output_artifact_id}`; coverage {item.coverage}.")
    for item in manifest.legacy_envelopes:
        lines.append(f"- Legacy envelope `{item.id}`; payload `{item.payload_artifact_id or 'none'}`; "
                     f"state {json.dumps(item.original_state)}.")
    return ("\n".join(lines) + "\n").encode()


def no_links(path, kind=None):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise BundleError("symlink_or_reparse_point")
    if kind == "file" and not stat.S_ISREG(info.st_mode):
        raise BundleError("non_regular_file")
    if kind == "directory" and not stat.S_ISDIR(info.st_mode):
        raise BundleError("non_directory")


def safe_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or "\\" in relative or ":" in relative or any(part in {"..", "."} for part in relative.split("/")):
        raise BundleError("unsafe_path")
    no_links(root)
    current = root
    for part in relative.split("/"):
        current = current / part
        no_links(current)
    if not current.resolve().is_relative_to(root.resolve()):
        raise BundleError("unsafe_path")
    return current


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BundleError("duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(BundleError("invalid_json_number")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise BundleError("malformed_json") from None


def model(data):
    try:
        return Manifest.model_validate(data)
    except (ValidationError, ValueError, TypeError):
        raise BundleError("invalid_manifest") from None


def blob_bytes(root, artifact):
    path = safe_path(root, artifact.path)
    no_links(path, "file")
    try:
        if path.stat().st_size != artifact.bytes:
            raise BundleError("size_mismatch")
        with path.open("rb") as handle:
            data = handle.read(artifact.bytes + 1)
    except OSError:
        raise BundleError("missing_blob") from None
    if len(data) != artifact.bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise BundleError("hash_mismatch")
    return data


def resolve(root, manifest, location_id):
    locations = {item.id: item for item in manifest.locations}
    if location_id not in locations:
        raise BundleError("unknown_location")
    location = locations[location_id]
    association = next(item for item in manifest.associations if item.id == location.association_id)
    artifact = next(item for item in manifest.artifacts if item.id == association.artifact_id)
    data = blob_bytes(root, artifact)
    return select_location(data, location)


def select_location(data, location):
    if location.kind == "bytes":
        return data[location.start:location.end]
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeError:
        raise BundleError("invalid_utf8_location") from None
    # Only LF and CRLF count as line endings; no Unicode/display normalization.
    parts = data.split(b"\n")
    lines = [part + b"\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    if location.end > len(lines):
        raise BundleError("line_out_of_bounds")
    return b"".join(lines[location.start-1:location.end])


def read_bundle(root):
    root = Path(root).absolute()
    try:
        no_links(root, "directory")
        manifest_path = safe_path(root, "manifest.json")
        no_links(manifest_path, "file")
        if manifest_path.stat().st_size > 1024 * 1024:
            raise BundleError("manifest_limit")
        with manifest_path.open("rb") as handle:
            raw = handle.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise BundleError("manifest_limit")
        manifest = model(strict_json(raw))
        allowed = {"manifest.json", "report.md", "blobs", *(item.path for item in manifest.artifacts)}
        for index, entry in enumerate(root.iterdir()):
            if index >= 3:
                raise BundleError("unexpected_entry")
            no_links(entry)
            relative = entry.relative_to(root).as_posix()
            if relative not in allowed or (entry.is_dir() and relative != "blobs"):
                raise BundleError("unexpected_entry")
        blob_dir = safe_path(root, "blobs")
        no_links(blob_dir, "directory")
        if blob_dir.exists():
            # Bounded enumeration; don't follow directories/reparse points.
            for index, entry in enumerate(blob_dir.iterdir()):
                if index >= 64:
                    raise BundleError("bundle_limit")
                no_links(entry)
                if entry.is_dir() or entry.relative_to(root).as_posix() not in allowed:
                    raise BundleError("unexpected_entry")
        for artifact in manifest.artifacts:
            blob_bytes(root, artifact)
        for location in manifest.locations:
            resolve(root, manifest, location.id)
        report_path = safe_path(root, "report.md")
        no_links(report_path, "file")
        if report_path.stat().st_size > 1024*1024:
            raise BundleError("report_mismatch")
        with report_path.open("rb") as handle:
            rendered = handle.read(1024*1024+1)
        if rendered != report(manifest):
            raise BundleError("report_mismatch")
        return manifest
    except OSError:
        raise BundleError("bundle_io") from None


def write_exact(path, data):
    no_links(path, "file")
    if path.exists():
        with path.open("rb") as handle:
            old = handle.read(len(data) + 1)
        if old != data:
            raise BundleError("existing_content_conflict")
        return
    with path.open("xb") as output:
        output.write(data)


def write_bundle(root, manifest, blobs):
    manifest = model(manifest.model_dump(mode="json") if isinstance(manifest, Manifest) else manifest)
    root = Path(root).absolute()
    expected = {item.sha256 for item in manifest.artifacts}
    if set(blobs) != expected:
        raise BundleError("blob_set_mismatch")
    for artifact in manifest.artifacts:
        data = blobs[artifact.sha256]
        if len(data) != artifact.bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise BundleError("blob_validation_failed")
    by_id = {item.id: item for item in manifest.artifacts}
    associations = {item.id: item for item in manifest.associations}
    for location in manifest.locations:
        artifact = by_id[associations[location.association_id].artifact_id]
        select_location(blobs[artifact.sha256], location)
    no_links(root, "directory")
    root.mkdir(parents=True, exist_ok=True)
    blob_dir = safe_path(root, "blobs")
    no_links(blob_dir, "directory")
    blob_dir.mkdir(exist_ok=True)
    for artifact in manifest.artifacts:
        write_exact(safe_path(root, artifact.path), blobs[artifact.sha256])
    write_exact(safe_path(root, "report.md"), report(manifest))
    # Manifest is completion marker. Partial output remains visible/recoverable.
    write_exact(safe_path(root, "manifest.json"), canonical(manifest))
    return read_bundle(root)


def parse_structured(data, media_type):
    """Bounded syntax validation, not evidence collection or authenticity proof."""
    if len(data) > 25 * 1024 * 1024:
        raise BundleError("parse_limit")
    if media_type == "application/json":
        return strict_json(data)
    try:
        value = data.decode("utf-8", errors="strict")
        if media_type == "text/plain":
            return value
        if media_type == "text/csv":
            rows = []
            for index, row in enumerate(csv.reader(io.StringIO(value, newline=""), strict=True)):
                if index >= 10000 or len(row) > 256 or any(len(field) > 65536 for field in row):
                    raise BundleError("parse_limit")
                rows.append(row)
            if rows and (not rows[0] or len(set(rows[0])) != len(rows[0]) or any(len(row) != len(rows[0]) for row in rows[1:])):
                raise BundleError("malformed_csv")
            return rows
    except (UnicodeError, csv.Error):
        raise BundleError("malformed_text_or_csv") from None
    raise BundleError("unsupported_parser")
