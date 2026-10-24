"""Focused integration proof. Requires only the explicitly configured new DB."""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from services.api.app import create_app
from services.api.contracts import ErrorEnvelope
from services.api import evidence
from services.api.settings import Settings


class CoreProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings.from_env()
        if cls.settings is None:
            raise RuntimeError("Explicit new rebuild config is required")
        cls.app = create_app(cls.settings)
        cls.client = TestClient(cls.app, raise_server_exceptions=False)
        token = (Path(os.environ["OMNIFORGE_CONFIG"]).parent / "auth-token").read_text().strip()
        cls.auth = {"Authorization": "Bearer " + token}
        cls.token_b = secrets.token_urlsafe(48)
        cls.auth_b = {"Authorization": "Bearer " + cls.token_b}
        cls.user_b = uuid4()
        with cls.app.state.engine.begin() as conn:
            assert conn.execute(text("SELECT current_database()" )).scalar_one() == "omniforge_rebuild"
            cls.server_version = conn.execute(text("SHOW server_version")).scalar_one()
            conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:id,'synthetic-proof',:hash)"),
                         {"id": cls.user_b, "hash": hashlib.sha256(cls.token_b.encode()).hexdigest()})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.app.state.engine.dispose()

    def error(self, result, status):
        self.assertEqual(result.status_code, status, result.text[:300])
        body = ErrorEnvelope.model_validate(result.json())
        self.assertEqual(str(body.request_id), result.headers["X-Request-ID"])
        return body

    def new_case(self, auth=None):
        result = self.client.post("/api/v1/cases", json={"title": "Synthetic core fixture " + str(uuid4())},
                                  headers={**(auth or self.auth), "Idempotency-Key": str(uuid4())})
        self.assertEqual(result.status_code, 201, result.text[:300])
        return result.json()

    def upload(self, case, data=b"line one\r\nline two\n", auth=None, key=None, name="fixture.txt", revision=1):
        return self.client.post(f"/api/v1/cases/{case['id']}/artifacts", params={"expected_revision": revision},
                                headers={**(auth or self.auth), "Idempotency-Key": key or str(uuid4())},
                                files={"file": (name, data, "text/plain")})

    def test_01_health_errors_contract(self):
        health = self.client.get("/api/v1/system/health").json()
        self.assertEqual(health["migration_version"], "0005_provider_profiles")
        self.assertTrue(health["database"]["ready"] and health["artifacts"]["ready"])
        self.assertFalse(health["ready"])
        self.assertEqual(health["provider"]["status"], "unverified")
        self.assertEqual(health["scheduler"]["status"], "unverified")
        wrong = self.client.post("/api/v1/system/health")
        self.assertEqual(self.error(wrong, 405).category, "method_not_allowed")
        self.assertIn("GET", wrong.headers["Allow"])
        absent = self.client.get("/api/v1/cases", headers={"X-Principal-ID": str(self.user_b)})
        self.assertEqual(self.error(absent, 401).category, "unauthenticated")
        self.assertEqual(absent.headers["WWW-Authenticate"], "Bearer")
        self.error(self.client.get("/api/v1/cases", headers={"Authorization": "Bearer invalid"}), 401)
        invalid = self.client.post("/api/v1/cases", json={"title": "", "secret": "SENSITIVE_FIXTURE"}, headers={**self.auth, "Idempotency-Key": str(uuid4())})
        self.error(invalid, 422)
        self.assertNotIn("SENSITIVE_FIXTURE", invalid.text)
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(schema, json.loads((Path(__file__).resolve().parents[3] / "packages/contracts/openapi.json").read_text()))
        errors = schema["paths"]["/api/v1/cases"]["post"]["responses"]
        for status in ("401", "403", "409", "422", "500", "503"):
            self.assertEqual(errors[status]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/ErrorEnvelope")
        self.assertIn("Allow", errors["405"]["headers"])
        caps = self.client.get("/api/v1/capabilities", headers=self.auth).json()["features"]
        self.assertEqual(caps["provider"]["status"], "unverified")
        self.assertEqual(caps["executor"]["status"], "unsupported")

    def test_02_persistence_idempotency_concurrency(self):
        key = str(uuid4())
        def create(_):
            return self.client.post("/api/v1/cases", json={"title": "Concurrent fixture"}, headers={**self.auth, "Idempotency-Key": key})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertEqual([item.status_code for item in results], [201, 201])
        self.assertEqual(results[0].json(), results[1].json())
        case = results[0].json()
        conflict = self.client.post("/api/v1/cases", json={"title": "Changed"}, headers={**self.auth, "Idempotency-Key": key})
        self.error(conflict, 409)
        # Fresh application/engine proves persisted read, not process-memory state.
        fresh = create_app(self.settings)
        with TestClient(fresh) as other:
            self.assertEqual(other.get(f"/api/v1/cases/{case['id']}", headers=self.auth).json(), case)
        with self.app.state.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM cases WHERE id=:id"), {"id": case["id"]}).scalar_one(), 1)
        self.error(self.client.get(f"/api/v1/cases/{case['id']}", headers=self.auth_b), 403)
        self.new_case()
        page = self.client.get("/api/v1/cases", headers=self.auth, params={"limit": 1}).json()
        self.assertEqual(len(page["items"]), 1)
        self.assertIsNotNone(page["next_cursor"])
        following = self.client.get("/api/v1/cases", headers=self.auth, params={"cursor": page["next_cursor"], "limit": 1}).json()
        self.assertNotEqual(page["items"][0]["id"], following["items"][0]["id"])

    def test_03_hash_ranges_duplicate_origin_grants(self):
        case_a, case_b = self.new_case(), self.new_case(self.auth_b)
        data = b"same exact bytes\r\nincluding \x00 and \xff\n"
        key = str(uuid4())
        first = self.upload(case_a, data=data, key=key)
        self.assertEqual(first.status_code, 201, first.text[:300])
        a = first.json()
        self.assertEqual(self.upload(case_a, data=data, key=key).json(), a)
        self.error(self.upload(case_a, data=b"changed", key=key), 409)
        second = self.upload(case_b, data=data, auth=self.auth_b, name="different-origin.bin")
        self.assertEqual(second.status_code, 201, second.text[:300])
        b = second.json()
        self.assertEqual(a["artifact_id"], b["artifact_id"])
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(a["source_id"], b["source_id"])
        self.assertEqual(a["sha256"], hashlib.sha256(data).hexdigest())
        self.assertIsNone(a["captured_at"])
        path = f"/api/v1/artifacts/{a['id']}"
        ranged = self.client.get(path + "/ranges", params={"start_byte": 5, "end_byte": 20}, headers=self.auth)
        self.assertEqual(ranged.status_code, 200)
        self.assertEqual(ranged.content, data[5:20])
        self.assertEqual(ranged.headers["X-Artifact-SHA256"], a["sha256"])
        self.error(self.client.get(path+"/ranges", params={"start_byte": 0, "end_byte": len(data)+1}, headers=self.auth), 422)
        self.error(self.client.get(f"/api/v1/artifacts/{b['id']}", headers=self.auth), 404)
        self.error(self.client.get(f"/api/v1/artifacts/{b['id']}/ranges", params={"start_byte": 0, "end_byte": 1}, headers=self.auth), 404)
        self.error(self.client.get(f"/api/v1/artifacts/{a['artifact_id']}", headers=self.auth), 404)
        visible = self.client.get(path, headers=self.auth).json()
        self.assertNotIn(b["source_id"], json.dumps(visible))
        self.assertNotIn("different-origin", json.dumps(visible))
        self.error(self.upload(case_a, data=b"stale", revision=1), 409)

    def test_04_publication_recovery(self):
        for after_rename in (False, True):
            case = self.new_case()
            key = str(uuid4())
            real_publish = evidence.publish
            def interrupted(*args):
                if after_rename:
                    real_publish(*args)
                raise OSError("PRIVATE_FAULT_FIXTURE")
            with patch.object(evidence, "publish", interrupted):
                result = self.upload(case, data=secrets.token_bytes(32), key=key)
            self.assertEqual(result.status_code, 202, result.text[:300])
            item = result.json()
            self.assertEqual(item["publication_status"], "pending")
            self.assertNotIn("PRIVATE_FAULT", result.text)
            pending_range = self.client.get(f"/api/v1/artifacts/{item['id']}/ranges", params={"start_byte": 0, "end_byte": 1}, headers=self.auth)
            self.error(pending_range, 503)
            repaired = evidence.reconcile(self.app.state.engine, self.settings.artifact_root, limit=20)
            self.assertIn(item["id"], repaired["repaired"])
            current = self.client.get(f"/api/v1/artifacts/{item['id']}", headers=self.auth).json()
            self.assertEqual(current["publication_status"], "committed")
            with self.app.state.engine.connect() as conn:
                self.assertEqual(conn.execute(text("SELECT status FROM idempotency WHERE key=:key"), {"key": key}).scalar_one(), 201)
                stage = conn.execute(text("SELECT stage_name FROM artifact_associations WHERE id=:id"), {"id": item["id"]}).scalar_one()
            self.assertTrue((self.settings.artifact_root / "staging" / stage).is_file())

    def test_05_limit_truncation_and_revision_race(self):
        case = self.new_case()
        boundary = "boundedfixture"
        def chunks():
            yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="limit.bin"\r\n\r\n'.encode()
            for _ in range(self.settings.upload_limit // 65536):
                yield b"x" * 65536
            yield b"x"
            yield f'\r\n--{boundary}--\r\n'.encode()
        result = self.client.post(f"/api/v1/cases/{case['id']}/artifacts", params={"expected_revision": 1},
            headers={**self.auth, "Idempotency-Key": str(uuid4()), "Content-Type": f"multipart/form-data; boundary={boundary}"}, content=chunks())
        self.error(result, 413)
        truncated = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="bad.txt"\r\n\r\ndata'.encode()
        self.error(self.client.post(f"/api/v1/cases/{case['id']}/artifacts", params={"expected_revision": 1}, headers={**self.auth, "Idempotency-Key": str(uuid4()), "Content-Type": f"multipart/form-data; boundary={boundary}"}, content=truncated), 422)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.upload(case, data=secrets.token_bytes(8)), range(2)))
        self.assertEqual(sorted(item.status_code for item in results), [201, 409])

    def test_06_internal_error_sanitized(self):
        from services.api import app as api_module
        with patch.object(api_module, "migration_at", side_effect=RuntimeError("PRIVATE_INTERNAL_FIXTURE")):
            result = self.client.get("/api/v1/system/health")
        self.assertEqual(self.error(result, 500).category, "internal")
        self.assertNotIn("PRIVATE_INTERNAL", result.text)

    def test_07_reload_artifact_page_and_normalized_root(self):
        normalized = Settings(self.settings.database_url, self.settings.artifact_root / ".." / "artifacts")
        self.assertEqual(normalized.artifact_root, self.settings.artifact_root.resolve())
        case = self.new_case()
        first = self.upload(case, data=b"reload fixture a")
        second = self.upload(case, data=b"reload fixture b", revision=2)
        self.assertEqual([first.status_code, second.status_code], [201, 201])
        fresh = create_app(self.settings)
        with TestClient(fresh) as other:
            route = f"/api/v1/cases/{case['id']}/artifacts"
            page = other.get(route, params={"limit": 1}, headers=self.auth).json()
            self.assertEqual(len(page["items"]), 1)
            self.assertIsNotNone(page["next_cursor"])
            next_page = other.get(route, params={"limit": 1, "cursor": page["next_cursor"]}, headers=self.auth).json()
            self.assertEqual({page["items"][0]["id"], next_page["items"][0]["id"]}, {first.json()["id"], second.json()["id"]})
            self.assertIsNone(next_page["next_cursor"])
            self.error(other.get(route, headers=self.auth_b), 403)

    def test_08_non_utc_capture_and_authority_seam(self):
        from services.api.evidence_access import bind_read_range
        from services.api.errors import Problem
        from uuid import UUID
        case = self.new_case()
        original = "2026-10-23T12:34:56.123456+05:30"
        result = self.client.post(f"/api/v1/cases/{case['id']}/artifacts",
            params={"expected_revision": 1, "captured_at": original},
            headers={**self.auth, "Idempotency-Key": str(uuid4())},
            files={"file": ("capture.txt", b"exact provenance fixture\n", "text/plain")})
        self.assertEqual(result.status_code, 201, result.text[:300])
        item = result.json()
        self.assertEqual(item["captured_at"], "2026-10-23T07:04:56.123456Z")
        self.assertEqual(item["captured_at_original"], original)
        self.assertEqual(item["captured_at_offset"], "+05:30")
        self.assertEqual(item["captured_at_provenance"], "supplied")
        reread = self.client.get(f"/api/v1/artifacts/{item['id']}", headers=self.auth).json()
        self.assertEqual(reread, item)
        with self.app.state.engine.connect() as conn:
            principal = conn.execute(text("SELECT id FROM principals WHERE token_hash=:hash"),
                {"hash": hashlib.sha256(self.auth["Authorization"].split(" ", 1)[1].encode()).hexdigest()}).scalar_one()
        read = bind_read_range(self.app.state.engine, self.settings.artifact_root, principal, UUID(case["id"]))
        self.assertEqual(read(UUID(item["id"]), item["sha256"], 0, 5), b"exact")
        http_range = self.client.get(f"/api/v1/artifacts/{item['id']}/ranges", params={"start_byte": 0, "end_byte": 5}, headers=self.auth)
        self.assertEqual(http_range.content, b"exact")
        with self.assertRaises(Problem) as mismatch:
            read(UUID(item["id"]), "0"*64, 0, 5)
        self.assertEqual(mismatch.exception.status, 409)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"), {"p": principal, "c": case["id"]})
        # Read permission remains, but upload write grant must fail.
        self.assertEqual(read(UUID(item["id"]), item["sha256"], 0, 5), b"exact")
        self.error(self.upload(case, revision=2), 403)
        # Revocation only affects this synthetic fixture grant.
        with self.app.state.engine.begin() as conn:
            conn.execute(text("DELETE FROM case_grants WHERE principal_id=:p AND case_id=:c"), {"p": principal, "c": case["id"]})
        with self.assertRaises(Problem) as denied:
            read(UUID(item["id"]), item["sha256"], 0, 5)
        self.assertEqual(denied.exception.status, 404)


if __name__ == "__main__":
    import faulthandler
    faulthandler.dump_traceback_later(60, exit=True)
    unittest.main(verbosity=2)
