"""OF-012I: accepted deterministic provider through actual PostgreSQL core authority."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import unittest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.models.contracts import Budget, Location, Profile, ReadOnlyContext
from adapters.models.mock import ScriptedMock, tool_round, final_round
from adapters.secrets.store import CredentialRef, SecretValue
from services.api.app import create_app
from services.api.evidence_access import bind_read_range
from services.api.errors import Problem
from services.api.providers.answer import answer
from services.api.settings import Settings


class SyntheticOnlyStore:
    def __init__(self, reference):
        self.reference, self.reads = reference, 0

    def get(self, reference):
        assert reference == self.reference
        self.reads += 1
        return SecretValue(b"synthetic-unused-key")

    def put(self, *args):
        raise AssertionError("No secret writes permitted by synthetic proof")

    def delete(self, *args):
        raise AssertionError("No secret deletes permitted by synthetic proof")


class ProviderCoreProof(unittest.TestCase):
    def test_real_core_mock_tool_roundtrip_and_fresh_authority(self):
        settings = Settings.from_env()
        self.assertIsNotNone(settings)
        app = create_app(settings)
        engine = app.state.engine
        token = Path(os.environ["OMNIFORGE_CONFIG"]).with_name("auth-token").read_text().strip()
        auth = {"Authorization": "Bearer " + token}
        secondary_token = secrets.token_urlsafe(48)
        secondary_auth = {"Authorization": "Bearer " + secondary_token}
        with engine.begin() as conn:
            self.assertEqual(conn.execute(text("SELECT current_database()" )).scalar_one(), "omniforge_rebuild")
            self.assertEqual(conn.execute(text("SELECT version_num FROM alembic_version" )).scalar_one(), "0006_profile_bindings")
            principal = conn.execute(text("SELECT id FROM principals WHERE token_hash=:hash"),
                {"hash": hashlib.sha256(token.encode()).hexdigest()}).scalar_one()
            conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:id,'of012i-synthetic',:hash)"),
                {"id": uuid4(), "hash": hashlib.sha256(secondary_token.encode()).hexdigest()})

        def create(client, headers):
            result = client.post("/api/v1/cases", json={"title": "OF-012I synthetic fixture"},
                                 headers={**headers, "Idempotency-Key": str(uuid4())})
            self.assertEqual(result.status_code, 201)
            return result.json()

        def upload(client, case, headers, data):
            result = client.post(f"/api/v1/cases/{case['id']}/artifacts", params={"expected_revision": 1},
                headers={**headers, "Idempotency-Key": str(uuid4())}, files={"file": ("synthetic-provider.bin", data, "application/octet-stream")})
            self.assertEqual(result.status_code, 201)
            return result.json()

        reference = CredentialRef.new(testing=True)
        profile = Profile(uuid4(), 1, "https://api.deepseek.com/chat/completions", "synthetic-fixture-only", reference)
        # No actual transport/network or OS credential-store object is constructed.
        budget = Budget(calls=2, input_tokens=100000, output_tokens=1024, wall_seconds=10, tool_bytes=1024)
        with TestClient(app) as client:
            primary_case, foreign_case = create(client, auth), create(client, secondary_auth)
            data = b"\x00Alpha\r\n\xce\xb2eta\nrange\xffend-" + secrets.token_bytes(16)
            primary = upload(client, primary_case, auth, data)
            foreign = upload(client, foreign_case, secondary_auth, data)
            self.assertEqual(primary["artifact_id"], foreign["artifact_id"])
            self.assertNotEqual(primary["source_id"], foreign["source_id"])
            reader = bind_read_range(engine, settings.artifact_root, principal, UUID(primary_case["id"]))

            def location(item, sha=None, end=14):
                return Location(id=uuid4(), association_id=UUID(item["id"]), artifact_id=UUID(item["artifact_id"]),
                                sha256=sha or item["sha256"], start_byte=2, end_byte=end)

            def run(loc, read=reader, record=False):
                observed = []
                def recorded_reader(*args):
                    value = read(*args)
                    observed.append(value)
                    if record:
                        self.assertEqual(value, data[loc.start_byte:loc.end_byte])
                    return value
                class RecordingMock(ScriptedMock):
                    def complete(inner, candidate, secret, payload, timeout):
                        if record and inner.calls == 1:
                            message = payload["messages"][-1]
                            self.assertEqual(message["role"], "tool")
                            content = json.loads(message["content"])
                            self.assertEqual(base64.b64decode(content["bytes"]), data[loc.start_byte:loc.end_byte])
                            self.assertEqual(content["sha256"], loc.sha256)
                        return super().complete(candidate, secret, payload, timeout)
                transport = RecordingMock([tool_round(loc), final_round(loc)])
                store = SyntheticOnlyStore(reference)
                context = ReadOnlyContext(case_id=UUID(primary_case["id"]), policy_version="of012i-synthetic-v1",
                    objective="Read a synthetic immutable range; no real-world conclusion.", locations=(loc,),
                    read_range=recorded_reader, authorize_profile=lambda candidate: candidate == profile,
                    canceled=lambda: False)
                result = answer(context, profile, budget, store=store, transport=transport)
                return result, transport, store, observed

            loc = location(primary)
            result, transport, store, observed = run(loc, record=True)
            self.assertIsNone(result.error)
            self.assertEqual(result.answer.outcome, "answered")
            self.assertEqual(result.answer.observations[0].citations[0].location_id, loc.id)
            self.assertEqual(result.answer.observations[0].citations[0].expected_sha256, primary["sha256"])
            self.assertEqual(observed, [data[2:14]])
            self.assertEqual((result.usage.calls, transport.calls, store.reads), (2, 2, 2))
            self.assertEqual((result.usage.input_tokens.value, result.usage.output_tokens.value), (70, 45))
            self.assertEqual(result.usage.tool_bytes, 12)
            self.assertIsNone(result.usage.cost.value)
            self.assertEqual(result.usage.cost.state, "unknown")

            def denied(loc, direct_status):
                with self.assertRaises(Problem) as rejected:
                    reader(loc.association_id, loc.sha256, loc.start_byte, loc.end_byte)
                self.assertEqual(rejected.exception.status, direct_status)
                value, mocked, fake_store, reads = run(loc)
                self.assertEqual(value.error, "tool_failure")
                self.assertIsNone(value.answer)
                self.assertEqual((value.usage.calls, mocked.calls, fake_store.reads), (1, 1, 1))
                self.assertEqual((value.usage.input_tokens.value, value.usage.output_tokens.value), (30, 20))
                self.assertEqual(reads, [])

            denied(location(foreign), 404)
            denied(location(primary, sha="0"*64), 409)
            denied(location(primary, end=len(data)+1), 422)
            # Corrupt only this newly created synthetic blob, outside selected range.
            # Original staging bytes and in-memory fixture are retained; restore exact copy afterward.
            blob = settings.artifact_root / "blobs" / primary["sha256"]
            corrupted = data[:-1] + bytes([data[-1] ^ 1])
            try:
                blob.write_bytes(corrupted)
                denied(location(primary), 503)
            finally:
                blob.write_bytes(data)
            self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), primary["sha256"])
            self.assertEqual(reader(loc.association_id, loc.sha256, 2, 14), data[2:14])
            # Same closure/context identity is bound before revocation; every call rechecks DB.
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM case_grants WHERE principal_id=:p AND case_id=:c"),
                             {"p": principal, "c": primary_case["id"]})
            denied(location(primary), 404)


if __name__ == "__main__":
    import faulthandler
    faulthandler.dump_traceback_later(40, exit=True)
    unittest.main(verbosity=2)
