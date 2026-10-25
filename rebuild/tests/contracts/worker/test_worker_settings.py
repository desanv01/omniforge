"""Injected byte readers only; no actual config/credential discovery."""
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import traceback
import unittest
from unittest.mock import patch
from uuid import uuid4

from infra.core.worker_settings import WorkerSettings, WorkerSettingsError, load_worker_settings

NATIVE_PATH = "C:/explicit/fixture.json" if os.name == "nt" else "/run/secrets/explicit-fixture.json"


def body():
    return {"schema_version": 1,
        "database_url": "postgresql+psycopg://omniforge_b3c_receiver_v1:synthetic-only@of-core-db:5432/omniforge_rebuild",
        "allowed_run_ids": [str(uuid4()) for _ in range(7)]}


class WorkerSettingsProof(unittest.TestCase):
    def parse(self, value, path=NATIVE_PATH):
        return load_worker_settings(path, read_bytes=lambda _: json.dumps(value).encode())

    def test_01_closed_valid_explicit_reader_and_redacted_frozen_context(self):
        fixture = body(); calls = []
        def read(path):
            calls.append(path); return json.dumps(fixture).encode()
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("No real file")), \
             patch.dict("os.environ", {"OMNIFORGE_CONFIG": "SENSITIVE_AMBIENT", "DATABASE_URL": "SENSITIVE_AMBIENT"}):
            result = load_worker_settings(NATIVE_PATH, read_bytes=read)
        self.assertEqual(calls, [NATIVE_PATH])
        self.assertEqual(len(result.allowed_run_ids), 7)
        self.assertNotIn("synthetic-only", repr(result)); self.assertNotIn("postgresql", repr(result))
        with self.assertRaises(FrozenInstanceError): result.schema_version = 2
        self.assertEqual(result.require_run(result.allowed_run_ids[0]), result.allowed_run_ids[0])
        for unknown in (uuid4(), str(result.allowed_run_ids[0]), None):
            with self.assertRaises(WorkerSettingsError): result.require_run(unknown)

    def test_02_closed_fields_and_exact_schema_types(self):
        fixture = body()
        for value in (None, [], {**fixture, "schema_version": True}, {**fixture, "schema_version": "1"},
                      {**fixture, "schema_version": 2}, {**fixture, "artifact_root": "SENSITIVE_INPUT"},
                      {key: val for key, val in fixture.items() if key != "database_url"}):
            with self.subTest(kind=type(value).__name__), self.assertRaises(WorkerSettingsError): self.parse(value)

    def test_03_only_exact_nonowner_database_origin_no_options(self):
        fixture = body(); url = fixture["database_url"]
        variants = [url.replace("omniforge_b3c_receiver_v1:", "postgres:"),
            url.replace("of-core-db", "127.0.0.1"), url.replace("of-core-db", "host.docker.internal"),
            url.replace("of-core-db", "of-core-db,other"), url.replace(":5432", ""),
            url.replace(":5432", ":5433"), url.replace("postgresql+psycopg", "postgresql"),
            url.replace("/omniforge_rebuild", "/legacy"), url+"?options=-c%20role%3Dpostgres",
            url+"?sslmode=disable", url.replace("synthetic-only", ""),
            url.replace("synthetic-only", "x"*257), url.replace("synthetic-only", "%00secret"), None, 1]
        for value in variants:
            with self.subTest(index=variants.index(value)), self.assertRaises(WorkerSettingsError):
                self.parse({**fixture, "database_url": value})

    def test_04_exact_seven_unique_canonical_uuids(self):
        fixture = body(); ids = fixture["allowed_run_ids"]
        for value in (ids[:6], ids+[str(uuid4())], [ids[0]]*7, "all", [True]*7,
                      ["not-a-uuid"]+ids[1:], [ids[0].upper()]+ids[1:], [ids[0].replace("-", "")]+ids[1:]):
            with self.assertRaises(WorkerSettingsError): self.parse({**fixture, "allowed_run_ids": value})

    def test_05_duplicate_json_size_utf8_and_reader_errors_are_safe(self):
        fixture = body(); raw = json.dumps(fixture)
        invalid = [b"", b"\xff", b"x"*16385, "not-bytes", b"{", (raw[:-1]+',"schema_version":1}').encode()]
        for value in invalid:
            with self.assertRaises(WorkerSettingsError): load_worker_settings(NATIVE_PATH, read_bytes=lambda _: value)
        def bad_read(_): raise OSError("SENSITIVE_READER")
        try:
            load_worker_settings(NATIVE_PATH, read_bytes=bad_read)
        except WorkerSettingsError as error:
            rendered = "".join(traceback.format_exception(error))
            self.assertNotIn("SENSITIVE_READER", rendered); self.assertNotIn("SENSITIVE_PATH", str(error))
        else: self.fail("Read failure must deny")

    def test_06_no_relative_uri_unc_or_ambient_path(self):
        for path in (None, "", "config.json", "~/config", "https://example.invalid/config", "\\\\host\\share\\x", "a\x00b"):
            calls = []
            with self.assertRaises(WorkerSettingsError):
                load_worker_settings(path, read_bytes=lambda p: calls.append(p))
            self.assertEqual(calls, [])
        self.assertEqual(self.parse(body(), path=NATIVE_PATH).schema_version, 1)

    def test_08_host_path_semantics_deny_foreign_unc_device_before_reader(self):
        foreign = "/explicit/config.json" if os.name == "nt" else "C:/explicit/config.json"
        for path in (foreign, "//host/share/config.json", "\\\\?\\C:\\config.json", "\\\\.\\config.json"):
            calls = []
            with self.assertRaises(WorkerSettingsError):
                load_worker_settings(path, read_bytes=lambda value: calls.append(value))
            self.assertEqual(calls, [])
        self.assertTrue(Path(NATIVE_PATH).is_absolute())
        self.assertEqual(self.parse(body()).schema_version, 1)

    def test_07_direct_dto_rejects_bypassing_closed_loader(self):
        fixture = body(); valid = self.parse(fixture)
        for ids in (list(valid.allowed_run_ids), tuple(fixture["allowed_run_ids"]), (uuid4(),)*7):
            with self.assertRaises(WorkerSettingsError): WorkerSettings(1, fixture["database_url"], ids)


if __name__ == "__main__": unittest.main()
