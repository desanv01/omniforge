"""Offline portable evidence fixtures. Retains synthetic outputs in private root."""
import copy
import json
import os
from pathlib import Path
import subprocess
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from packages.contracts.evidence.capture import CaptureTime, parse_capture
from packages.contracts.export.models import Manifest
from packages.contracts.export.portable import (BundleError, canonical, model, parse_structured,
                                               read_bundle, report, resolve, write_bundle)
from tests.fixtures.evidence.build_fixture import fixture, uid


class PortableProof(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ["OMNIFORGE_EVIDENCE_PROOF_ROOT"]) / (self._testMethodName + "-" + str(uuid4()))
        self.root.mkdir(parents=True)
        self.manifest, self.blobs = fixture()

    def rejected(self, operation, code=None):
        with self.assertRaises(BundleError) as raised:
            operation()
        if code:
            self.assertEqual(raised.exception.code, code)

    def test_01_round_trip_ids_origins_capture(self):
        first, second = self.root / "first", self.root / "second"
        saved = write_bundle(first, self.manifest, self.blobs)
        imported = read_bundle(first)
        exported = write_bundle(second, imported, self.blobs)
        self.assertEqual(canonical(saved), canonical(exported))
        self.assertEqual(canonical(write_bundle(first, imported, self.blobs)), canonical(saved))
        a, b = imported.associations[0], imported.associations[-1]
        self.assertEqual(a.artifact_id, b.artifact_id)
        self.assertNotEqual(a.source_id, b.source_id)
        self.assertEqual(a.captured_at_original, "2026-10-23T12:34:56.123456+08:00")
        self.assertEqual(a.captured_at_offset, "+08:00")
        self.assertEqual(a.captured_at.isoformat(), "2026-10-23T04:34:56.123456+00:00")
        self.assertEqual(a.imported_at.isoformat(), "2026-10-23T15:00:00+00:00")
        source = Path(__file__).resolve().parents[2] / "fixtures/evidence/manifest.json"
        self.assertEqual(source.read_bytes(), canonical(saved))

    def test_02_exact_bytes_lines_and_unknown_citation(self):
        root = self.root / "bundle"
        write_bundle(root, self.manifest, self.blobs)
        self.assertEqual(resolve(root, self.manifest, uid(40)), "βeta\n".encode())
        self.assertEqual(resolve(root, self.manifest, uid(41)), b"Second \xce\xb2\nThird\r\n")
        self.rejected(lambda: resolve(root, self.manifest, uid(999)), "unknown_location")
        broken = self.manifest.model_dump(mode="json")
        broken["locations"][1]["end"] = 999
        self.rejected(lambda: write_bundle(self.root / "invalid-lines", model(broken), self.blobs), "line_out_of_bounds")
        self.assertFalse((self.root / "invalid-lines").exists())

    def test_03_syntax_corpus_rejects_without_clean_negative(self):
        source = Path(__file__).resolve().parents[2] / "fixtures/evidence"
        self.assertIn("βeta", parse_structured((source / "sample.txt").read_bytes(), "text/plain"))
        self.assertEqual(len(parse_structured((source / "events.json").read_bytes(), "application/json")["events"]), 2)
        self.assertEqual(len(parse_structured((source / "events.csv").read_bytes(), "text/csv")), 3)
        for name, mime in (("malformed.json", "application/json"), ("truncated.json", "application/json"),
                           ("malformed.csv", "text/csv"), ("truncated.csv", "text/csv")):
            self.rejected(lambda name=name, mime=mime: parse_structured((source / name).read_bytes(), mime))
        self.rejected(lambda: parse_structured(b'{"id":1,"id":2}', "application/json"), "duplicate_json_key")
        self.rejected(lambda: parse_structured(b'{"value":NaN}', "application/json"), "invalid_json_number")
        complete, incomplete = self.manifest.observations
        self.assertEqual((complete.collection_count, incomplete.collection_count), (0, 0))
        self.assertEqual((complete.outcome, incomplete.outcome), ("not_observed", "insufficient_data"))
        invalid = self.manifest.model_dump(mode="json")
        invalid["observations"][1]["outcome"] = "not_observed"
        self.rejected(lambda: model(invalid), "invalid_manifest")

    def test_04_path_traversal_absolute_and_link_rejection(self):
        for path in ("../escape", "/absolute", "Z:/private/example", "blobs/../escape", "blobs\\escape"):
            invalid = self.manifest.model_dump(mode="json")
            invalid["artifacts"][0]["path"] = path
            self.rejected(lambda: model(invalid), "invalid_manifest")
        outside, root = self.root / "outside", self.root / "linked-bundle"
        outside.mkdir()
        root.mkdir()
        link = root / "blobs"
        if os.name == "nt":
            command = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(command.returncode, 0, "Synthetic junction setup failed: " + command.stderr.decode(errors="replace"))
        else:
            link.symlink_to(outside, target_is_directory=True)
        self.rejected(lambda: write_bundle(root, self.manifest, self.blobs), "symlink_or_reparse_point")
        self.assertEqual(list(outside.iterdir()), [])

    def test_05_hash_size_and_unknown_file_rejection(self):
        for mismatch in ("hash", "size"):
            root = self.root / mismatch
            write_bundle(root, self.manifest, self.blobs)
            artifact = self.manifest.artifacts[0]
            # Mutate only this generated synthetic attack copy, never source originals.
            data = self.blobs[artifact.sha256]
            (root / artifact.path).write_bytes((b"X" + data[1:]) if mismatch == "hash" else data+b"extra")
            self.rejected(lambda: read_bundle(root), "hash_mismatch" if mismatch == "hash" else "size_mismatch")
        root = self.root / "extra-file"
        write_bundle(root, self.manifest, self.blobs)
        (root / "unexpected.txt").write_text("synthetic unexpected content")
        self.rejected(lambda: read_bundle(root), "unexpected_entry")

    def test_06_capture_unknown_and_inconsistent_provenance(self):
        old = CaptureTime(captured_at="2026-10-23T00:00:00Z")
        self.assertEqual(old.captured_at_provenance, "unknown")
        self.assertIsNone(old.captured_at_original)
        for value in ("2026-10-23T12:00:00", "2026-10-23T12:00:00+08:99", "invalid"):
            with self.assertRaises(ValueError):
                parse_capture(value)
        changed = parse_capture("2026-10-23T12:00:00-05:30")
        changed["captured_at_offset"] = "+00:00"
        with self.assertRaises(ValidationError):
            CaptureTime.model_validate(changed)

    def test_07_private_metadata_and_manifest_truncation(self):
        for text in ("Z:/private/example", "/root/private/example", "/opt/private/example", "Authorization: Bearer synthetic"):
            invalid = self.manifest.model_dump(mode="json")
            invalid["claims"][0]["text"] = text
            self.rejected(lambda: model(invalid), "invalid_manifest")
        invalid = self.manifest.model_dump(mode="json")
        invalid["api_key"] = "synthetic-only"
        self.rejected(lambda: model(invalid), "invalid_manifest")
        root = self.root / "truncated-manifest"
        root.mkdir()
        (root / "manifest.json").write_bytes(b'{"schema_version":1,')
        self.rejected(lambda: read_bundle(root), "malformed_json")
        altered = self.manifest.model_dump(mode="json")
        altered["claims"][0]["text"] = "[example](https://example.invalid) <script>synthetic"
        rendered = report(model(altered)).decode()
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[example](https://example.invalid)", rendered)

    def test_08_schema_snapshot_and_identity_conflict(self):
        source = Path(__file__).resolve().parents[3]
        schema = json.loads((source / "packages/contracts/export/manifest.schema.json").read_text())
        expected = Manifest.model_json_schema()
        schema.pop("$id")
        schema.pop("$schema")
        self.assertEqual(schema, expected)
        invalid = self.manifest.model_dump(mode="json")
        invalid["associations"].append(copy.deepcopy(invalid["associations"][0]))
        self.rejected(lambda: model(invalid), "invalid_manifest")
        root = self.root / "identity"
        write_bundle(root, self.manifest, self.blobs)
        altered = self.manifest.model_dump(mode="json")
        altered["bundle_id"] = str(uuid4())
        self.rejected(lambda: write_bundle(root, model(altered), self.blobs), "existing_content_conflict")
        self.assertEqual(read_bundle(root).bundle_id, self.manifest.bundle_id)

    def test_09_nonregular_nodes_never_opened(self):
        from packages.contracts.export.portable import no_links, write_exact
        target = self.root / "synthetic-fifo"
        if hasattr(os, "mkfifo"):
            os.mkfifo(target)
            self.rejected(lambda: write_exact(target, b"fixture"), "non_regular_file")
        else:
            metadata = SimpleNamespace(st_mode=stat.S_IFIFO, st_file_attributes=0)
            with patch.object(Path, "lstat", return_value=metadata), patch.object(Path, "open", side_effect=AssertionError("Must reject before opening")):
                self.rejected(lambda: no_links(target, "file"), "non_regular_file")
        root = self.root / "directory-as-manifest"
        root.mkdir()
        (root / "manifest.json").mkdir()
        self.rejected(lambda: read_bundle(root), "non_regular_file")

    def test_10_source_attribution_and_strict_integer_selectors(self):
        invalid = self.manifest.model_dump(mode="json")
        invalid["observations"].append({"id": str(uid(90)), "source_id": str(uid(35)),
            "coverage": "complete", "collection_count": 1, "outcome": "observed", "location_ids": [str(uid(40))]})
        self.rejected(lambda: model(invalid), "invalid_manifest")
        invalid["locations"].append({**invalid["locations"][0], "id": str(uid(42)), "association_id": str(uid(25))})
        invalid["observations"][-1]["location_ids"] = [str(uid(42))]
        self.assertEqual(len(model(invalid).observations), 3)
        for group, key in (("artifacts", "bytes"), ("locations", "start"), ("observations", "collection_count")):
            for value in (True, "1", 1.0):
                changed = self.manifest.model_dump(mode="json")
                changed[group][0][key] = value
                self.rejected(lambda: model(changed), "invalid_manifest")
        changed = self.manifest.model_dump(mode="json")
        changed["schema_version"] = True
        self.rejected(lambda: model(changed), "invalid_manifest")


if __name__ == "__main__":
    unittest.main(verbosity=2)
