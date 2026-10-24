"""B1 actual-core proof; executed only by the exclusive backend runtime owner.

Requires explicit new-core config. No Hatchet, execution claims, provider or SSE.
All seeded rows are synthetic and retained; no legacy queries or cleanup.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from services.api.app import create_app
from services.api.contracts import ErrorEnvelope
from services.api.runs import repository
from services.api.settings import Settings


class RunJournalProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings.from_env()
        if cls.settings is None:
            raise RuntimeError("Explicit isolated core configuration required")
        cls.app = create_app(cls.settings)
        cls.client = TestClient(cls.app, raise_server_exceptions=False)
        token = (Path(os.environ["OMNIFORGE_CONFIG"]).parent / "auth-token").read_text().strip()
        cls.auth = {"Authorization": "Bearer " + token}
        cls.principal_b = uuid4()
        token_b = secrets.token_urlsafe(48)
        cls.auth_b = {"Authorization": "Bearer " + token_b}
        with cls.app.state.engine.begin() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one() == "omniforge_rebuild"
            conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:id,'run-journal-proof',:hash)"),
                         {"id": cls.principal_b, "hash": hashlib.sha256(token_b.encode()).hexdigest()})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.app.state.engine.dispose()

    def error(self, result, status):
        self.assertEqual(result.status_code, status)
        ErrorEnvelope.model_validate(result.json())
        self.assertNotIn("PRIVATE_RUN_FIXTURE", result.text)

    def case(self, auth=None):
        result = self.client.post("/api/v1/cases", json={"title": "Run journal " + str(uuid4())},
            headers={**(auth or self.auth), "Idempotency-Key": str(uuid4())})
        self.assertEqual(result.status_code, 201)
        return result.json()["id"]

    def create(self, case, key=None, body=None, auth=None):
        return self.client.post(f"/api/v1/cases/{case}/runs", json=body or {},
            headers={**(auth or self.auth), "Idempotency-Key": key or str(uuid4())})

    def counts(self, run_id):
        with self.app.state.engine.connect() as conn:
            return tuple(conn.execute(text(f"SELECT count(*) FROM {table} WHERE {column}=:id"),
                         {"id": run_id}).scalar_one() for table, column in
                         (("runs", "id"), ("run_events", "run_id"), ("run_outbox", "run_id")))

    def test_01_atomic_admission_replay_and_restart(self):
        case, key = self.case(), str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.create(case, key), range(2)))
        self.assertEqual([r.status_code for r in results], [202, 202])
        self.assertEqual(results[0].json(), results[1].json())
        run = results[0].json()
        self.assertEqual((run["status"], run["revision"], run["attempt_id"], run["output_refs"]), ("queued", 1, None, []))
        self.assertEqual(self.counts(run["id"]), (1, 1, 1))
        with self.app.state.engine.connect() as conn:
            intent = conn.execute(text("SELECT state,dispatch_key FROM run_outbox WHERE run_id=:r"), {"r": run["id"]}).one()
            self.assertEqual(intent.state, "pending")
            self.assertEqual(intent.dispatch_key, "run:" + run["id"] + ":start:v1")
        self.error(self.create(case, key, {"budget": {"wall_seconds": 11}}), 409)
        fresh = create_app(self.settings)
        with TestClient(fresh, raise_server_exceptions=False) as client:
            self.assertEqual(client.get(f"/api/v1/runs/{run['id']}", headers=self.auth).json(), run)
        self.assertEqual(self.client.get("/api/v1/capabilities", headers=self.auth).json()["features"]["scheduler"]["status"], "unverified")

    def test_02_transaction_rollback_preserves_no_partial_admission(self):
        case, key, staged = self.case(), str(uuid4()), []
        original = repository.insert_queued
        def fail_after_writes(*args, **kwargs):
            value = original(*args, **kwargs)
            staged.append(str(value.id))
            raise RuntimeError("PRIVATE_RUN_FIXTURE")
        with patch.object(repository, "insert_queued", fail_after_writes):
            self.error(self.create(case, key), 500)
        self.assertEqual(len(staged), 1)
        self.assertEqual(self.counts(staged[0]), (0, 0, 0))
        with self.app.state.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM idempotency WHERE operation=:op AND key=:key"),
                {"op": "create_run:" + case, "key": key}).scalar_one(), 0)
        self.assertEqual(self.create(case, key).status_code, 202)

    def test_03_input_snapshot_and_authority_boundaries(self):
        case, foreign = self.case(), self.case(self.auth_b)
        data = b"synthetic immutable input\n"
        upload = self.client.post(f"/api/v1/cases/{case}/artifacts", params={"expected_revision": 1},
            headers={**self.auth, "Idempotency-Key": str(uuid4())}, files={"file": ("input.txt", data, "text/plain")})
        self.assertEqual(upload.status_code, 201)
        item = upload.json()
        ref = {"association_id": item["id"], "revision": item["revision"], "sha256": item["sha256"]}
        accepted = self.create(case, body={"input_refs": [ref]})
        self.assertEqual(accepted.status_code, 202)
        snapshot = accepted.json()["input_refs"][0]
        self.assertEqual(snapshot["artifact_id"], item["artifact_id"])
        self.assertEqual(snapshot["coverage"], "unknown")
        self.error(self.create(foreign, body={"input_refs": [ref]}, auth=self.auth_b), 404)
        self.error(self.create(case, body={"input_refs": [{**ref, "sha256": "0"*64}]}), 409)
        self.error(self.create(case, body={"input_refs": [{**ref, "revision": ref["revision"] + 1}]}), 409)
        self.error(self.create(case, body={"input_refs": [ref, ref]}), 422)
        self.error(self.create(case, body={"input_refs": [ref]*33}), 422)
        self.error(self.create(case, body={"kind": "host-command", "PRIVATE_RUN_FIXTURE": "ignored"}), 422)
        self.error(self.create(case, body={"policy_version": "arbitrary-policy"}), 422)
        self.error(self.create(case, body={"budget": {"calls": 1}}), 422)
        self.error(self.create(case, body={"provider_profile_ref": "not-admitted"}), 422)
        for invalid in (True, 1.0, "1"):
            self.error(self.create(case, body={"input_refs": [{**ref, "revision": invalid}]}), 422)
            self.error(self.create(case, body={"budget": {"wall_seconds": invalid}}), 422)
        for invalid in (False, 0.0, "0"):
            self.error(self.create(case, body={"budget": {"calls": invalid}}), 422)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE artifact_associations SET publication_status='pending' WHERE id=:id"), {"id": item["id"]})
        try:
            self.error(self.create(case, body={"input_refs": [ref]}), 409)
        finally:
            with self.app.state.engine.begin() as conn:
                conn.execute(text("UPDATE artifact_associations SET publication_status='committed' WHERE id=:id"), {"id": item["id"]})
        run_id = accepted.json()["id"]
        for suffix in ("", "/events"):
            self.error(self.client.get(f"/api/v1/runs/{run_id}" + suffix, headers=self.auth_b), 404)
        self.error(self.client.post(f"/api/v1/runs/{run_id}/cancel", json={"expected_revision": 1},
            headers={**self.auth_b, "Idempotency-Key": str(uuid4())}), 404)
        self.error(self.client.get(f"/api/v1/runs/{uuid4()}", headers=self.auth), 404)
        self.error(self.client.get(f"/api/v1/runs/{run_id}", headers={"X-Principal-ID": str(self.principal_b)}), 401)

    def test_04_queued_cancel_is_atomic_and_idempotent(self):
        run = self.create(self.case()).json()
        path, key = f"/api/v1/runs/{run['id']}/cancel", str(uuid4())
        for invalid in (True, 1.0, "1"):
            self.error(self.client.post(path, json={"expected_revision": invalid},
                headers={**self.auth, "Idempotency-Key": str(uuid4())}), 422)
        def cancel(_):
            return self.client.post(path, json={"expected_revision": 1}, headers={**self.auth, "Idempotency-Key": key})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(cancel, range(2)))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual(results[0].json(), results[1].json())
        result = results[0].json()
        self.assertEqual((result["status"], result["revision"]), ("canceled", 3))
        self.assertEqual(result["terminal_reason"], "canceled_before_dispatch")
        self.assertIsNotNone(result["finished_at"])
        self.assertIsNone(result["outcome"])
        self.assertEqual(self.counts(run["id"]), (1, 3, 1))
        with self.app.state.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT state FROM run_outbox WHERE run_id=:id"), {"id": run["id"]}).scalar_one(), "suppressed")
        self.error(self.client.post(path, json={"expected_revision": 1}, headers={**self.auth, "Idempotency-Key": str(uuid4())}), 409)
        self.error(self.client.post(path, json={"expected_revision": 3}, headers={**self.auth, "Idempotency-Key": key}), 409)
        terminal = self.client.post(path, json={"expected_revision": 3}, headers={**self.auth, "Idempotency-Key": str(uuid4())})
        self.assertEqual(terminal.json(), result)
        self.assertEqual(self.counts(run["id"]), (1, 3, 1))

    def test_05_grant_checked_before_replay_and_principal_scoped(self):
        case, key = self.case(), str(uuid4())
        first = self.create(case, key).json()
        with self.app.state.engine.begin() as conn:
            conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,true)"),
                {"p": self.principal_b, "c": case})
        second = self.create(case, key, auth=self.auth_b)
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(second.json()["id"], first["id"])
        cancel_key = str(uuid4())
        path = f"/api/v1/runs/{second.json()['id']}/cancel"
        headers = {**self.auth_b, "Idempotency-Key": cancel_key}
        self.assertEqual(self.client.post(path, json={"expected_revision": 1}, headers=headers).status_code, 200)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("DELETE FROM case_grants WHERE principal_id=:p AND case_id=:c"),
                {"p": self.principal_b, "c": case})
        self.error(self.create(case, key, auth=self.auth_b), 403)
        self.error(self.client.post(path, json={"expected_revision": 1}, headers=headers), 404)
        self.error(self.client.get(path[:-7], headers=self.auth_b), 404)
        self.error(self.client.get(path[:-7] + "/events", headers=self.auth_b), 404)

    def test_06_replay_cursor_bounds_and_json_only(self):
        run = self.create(self.case()).json()
        self.client.post(f"/api/v1/runs/{run['id']}/cancel", json={"expected_revision": 1},
            headers={**self.auth, "Idempotency-Key": str(uuid4())})
        path = f"/api/v1/runs/{run['id']}/events"
        page = self.client.get(path, params={"after": 0, "limit": 1}, headers=self.auth).json()
        self.assertEqual([e["sequence"] for e in page["items"]], [1])
        self.assertTrue(page["has_more"])
        rest = self.client.get(path, params={"after": page["next_after"]}, headers=self.auth).json()
        self.assertEqual([e["sequence"] for e in rest["items"]], [2, 3])
        self.assertFalse(rest["has_more"])
        self.assertEqual([e["type"] for e in rest["items"]], ["cancel_requested", "canceled"])
        self.assertEqual(self.client.get(path, params={"after": 3}, headers=self.auth).json()["items"], [])
        self.assertEqual(self.client.get(path, headers={**self.auth, "Last-Event-ID": "1"}).json(), rest)
        self.error(self.client.get(path, params={"after": 1}, headers={**self.auth, "Last-Event-ID": "2"}), 409)
        self.error(self.client.get(path, params={"after": 4}, headers=self.auth), 409)
        for params in ({"after": -1}, {"after": "x"}, {"after": "1.0"}, {"after": "1e0"}, {"limit": 101}):
            self.error(self.client.get(path, params=params, headers=self.auth), 422)
        self.error(self.client.get(path, headers={**self.auth, "Last-Event-ID": "+1"}), 422)
        self.error(self.client.get(path, headers={**self.auth, "Accept": "text/event-stream"}), 501)
        fresh = create_app(self.settings)
        with TestClient(fresh, raise_server_exceptions=False) as client:
            self.assertEqual(client.get(path, headers=self.auth).json()["items"][-1]["sequence"], 3)

    def test_07_cancel_waits_for_run_lock_then_suppresses_intent(self):
        # Exercise the shared row-lock seam only, not a fabricated B2 claim.
        run = self.create(self.case()).json()
        entered = threading.Event()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            with self.app.state.engine.begin() as conn:
                conn.execute(text("SELECT id FROM runs WHERE id=:r FOR UPDATE"), {"r": run["id"]})
                holder = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
                def cancel():
                    entered.set()
                    return self.client.post(f"/api/v1/runs/{run['id']}/cancel", json={"expected_revision": 1},
                        headers={**self.auth, "Idempotency-Key": str(uuid4())})
                pending = pool.submit(cancel)
                self.assertTrue(entered.wait(1))
                # Observe a real PostgreSQL waiter blocked by this exact holder,
                # not merely a thread scheduled before the HTTP request starts.
                observed = False
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with self.app.state.engine.connect() as observer:
                        observed = observer.execute(text("""SELECT EXISTS(SELECT 1
                            FROM pg_stat_activity WHERE datname=current_database()
                            AND wait_event_type='Lock' AND :holder=ANY(pg_blocking_pids(pid))
                            AND query LIKE '%FOR UPDATE OF r%')"""), {"holder": holder}).scalar_one()
                    if observed:
                        break
                    time.sleep(0.025)
                self.assertTrue(observed, "Expected a bounded PostgreSQL Run-row lock waiter")
                self.assertFalse(pending.done())
            result = pending.result(timeout=8)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["status"], "canceled")
            with self.app.state.engine.connect() as conn:
                self.assertEqual(conn.execute(text("SELECT state FROM run_outbox WHERE run_id=:r"),
                    {"r": run["id"]}).scalar_one(), "suppressed")
        finally:
            pool.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
