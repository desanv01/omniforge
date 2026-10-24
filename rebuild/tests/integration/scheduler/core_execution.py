"""B2 actual-core proof with only a fake port and newly admitted synthetic IDs.

Executed by the sole backend runtime owner; no live scheduler/network/tools.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import time
import unittest
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import text

from services.api.errors import Problem
from services.api.runs import repository
from services.worker.dispatch import Dispatcher
from services.worker.scheduler_port import Execution, FakeSchedulerPort, Reconciliation
from tests.integration.scheduler import core_journal


class CoreExecutionProof(unittest.TestCase):
    case = core_journal.RunJournalProof.case
    create = core_journal.RunJournalProof.create
    error = core_journal.RunJournalProof.error

    @classmethod
    def setUpClass(cls):
        core_journal.RunJournalProof.setUpClass.__func__(cls)
        # Freeze existing B1 intents/Run state; every dispatcher below gets only
        # newly created IDs. No broad drain, background operation or cleanup.
        cls.baseline = cls._snapshot_existing()

    @classmethod
    def _snapshot_existing(cls):
        with cls.app.state.engine.connect() as conn:
            runs = {str(row["id"]): dict(row) for row in conn.execute(text("SELECT * FROM runs")).mappings()}
            outbox = {str(row["id"]): dict(row) for row in conn.execute(text("SELECT * FROM run_outbox")).mappings()}
            return runs, outbox

    @classmethod
    def tearDownClass(cls):
        try:
            current = cls._snapshot_existing()
            for old, new in zip(cls.baseline, current):
                if any(new.get(key) != value for key, value in old.items()):
                    raise AssertionError("Preexisting Run/outbox rows changed")
        finally:
            core_journal.RunJournalProof.tearDownClass.__func__(cls)

    def new(self, **port_options):
        result = self.create(self.case())
        self.assertEqual(result.status_code, 202)
        run_id = UUID(result.json()["id"])
        port = FakeSchedulerPort(**port_options)
        return run_id, port, Dispatcher(self.app.state.engine, port, (run_id,))

    def row(self, run_id):
        with self.app.state.engine.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM runs WHERE id=:r"), {"r": run_id}).mappings().one())

    def outbox(self, run_id):
        with self.app.state.engine.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM run_outbox WHERE run_id=:r"), {"r": run_id}).mappings().one())

    def count(self, table, run_id):
        assert table in ("run_attempts", "run_outputs", "run_scheduler_executions")
        with self.app.state.engine.connect() as conn:
            return conn.execute(text(f"SELECT count(*) FROM {table} WHERE run_id=:r"), {"r": run_id}).scalar_one()

    def claim(self, run_id, *, seconds=5, expected=None):
        with self.app.state.engine.begin() as conn:
            external = conn.execute(text("SELECT external_id FROM run_scheduler_executions WHERE run_id=:r LIMIT 1"),
                                    {"r": run_id}).scalar_one()
            return repository.claim_attempt(conn, run_id, external, "synthetic-worker",
                self.row(run_id)["revision"] if expected is None else expected, seconds)

    def prepared(self):
        run_id, port, dispatcher = self.new()
        self.assertEqual(dispatcher.tick(run_id), "acknowledged")
        return run_id, port, dispatcher, self.claim(run_id)

    def conflict(self, callback, status=409):
        with self.assertRaises(Problem) as caught:
            with self.app.state.engine.begin() as conn:
                callback(conn)
        self.assertEqual(caught.exception.status, status)

    def test_01_concurrent_dispatch_and_exclusive_attempt(self):
        run_id, _, _ = self.new()
        engine = self.app.state.engine
        class UnlockedPort(FakeSchedulerPort):
            def submit(inner, command):
                # A port call must not hold the application transaction/Run lock.
                with engine.begin() as conn:
                    conn.execute(text("SET LOCAL lock_timeout='500ms'"))
                    conn.execute(text("SELECT id FROM runs WHERE id=:r FOR UPDATE"), {"r": run_id})
                return super().submit(command)
        port = UnlockedPort(completed=True)
        drivers = [Dispatcher(engine, port, (run_id,)) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda driver: driver.tick(run_id), drivers))
        self.assertEqual(results.count("acknowledged"), 1)
        self.assertEqual(port.submissions, 1)
        self.assertEqual(self.count("run_scheduler_executions", run_id), 1)
        self.assertEqual(self.row(run_id)["status"], "queued")
        self.assertEqual(self.row(run_id)["output_refs"], [])
        def claim(_):
            try:
                return self.claim(run_id, expected=1)
            except Problem:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = list(pool.map(claim, range(2)))
        self.assertEqual(sum(token is not None for token in tokens), 1)
        self.assertEqual(self.count("run_attempts", run_id), 1)
        self.assertEqual(self.row(run_id)["status"], "running")
        self.assertEqual(self.count("run_outputs", run_id), 0)
        if self.baseline[0]:
            with self.assertRaises(ValueError):
                drivers[0].tick(UUID(next(iter(self.baseline[0]))))

    def test_02_acknowledgement_loss_reconciles_without_resubmit(self):
        run_id, port, driver = self.new(lose_ack=True)
        self.assertEqual(driver.tick(run_id), "reconcile_required")
        self.assertEqual(self.count("run_scheduler_executions", run_id), 0)
        self.assertEqual(self.row(run_id)["status"], "queued")
        self.assertEqual(driver.tick(run_id), "acknowledged")
        self.assertEqual((port.submissions, port.lookups), (1, 1))
        self.assertEqual(self.count("run_scheduler_executions", run_id), 1)
        self.assertEqual(self.outbox(run_id)["dispatch_count"], 1)
        self.assertEqual(self.row(run_id)["status"], "queued")

    def test_03_pre_submit_loss_bounded_redelivery_and_unknown(self):
        run_id, port, driver = self.new()
        lost = driver.reserve(run_id)
        self.assertIsNotNone(lost)
        self.assertEqual(port.submissions, 0)
        time.sleep(1.1)
        self.assertEqual(driver.tick(run_id), "pending")
        self.assertEqual(driver.tick(run_id), "acknowledged")
        self.assertEqual((port.submissions, port.lookups), (1, 1))
        self.assertEqual(self.outbox(run_id)["dispatch_count"], 2)
        self.assertEqual(driver._finish(lost, (Execution("fake-late-ack"),), next_state="acknowledged"), "stale_ack")
        self.assertEqual(self.count("run_scheduler_executions", run_id), 1)
        unknown, fake, bounded = self.new(lose_ack=True, unknown_lookup=True)
        self.assertEqual(bounded.tick(unknown), "reconcile_required")
        self.assertEqual(bounded.tick(unknown), "reconcile_required")
        self.assertEqual(bounded.tick(unknown), "reconcile_required")
        for _ in range(3):
            self.assertEqual(bounded.tick(unknown), "not_eligible")
        self.assertEqual((fake.submissions, fake.lookups), (1, 2))
        self.assertEqual(self.outbox(unknown)["last_error_code"], "reconcile_limit")
        self.assertEqual(self.row(unknown)["status"], "queued")

    def test_04_db_time_expiry_renewal_new_fence_and_replay(self):
        run_id, _, _, token = self.prepared()
        with self.app.state.engine.begin() as conn:
            current = repository.renew_attempt(conn, token, token.revision, 1)
        self.assertIsNotNone(current.lease_expires_at.tzinfo)
        self.conflict(lambda c: repository.admit_work(c, token, token.revision))
        self.conflict(lambda c: repository.expire_attempt(c, run_id, current.revision))
        time.sleep(1.1)
        self.conflict(lambda c: repository.complete_attempt(c, current, current.revision, "result", {"value": "ok"}))
        with self.app.state.engine.begin() as conn:
            expired = repository.expire_attempt(conn, run_id, current.revision)
        self.assertEqual(expired.status, "interrupted")
        newer = self.claim(run_id)
        self.assertGreater(newer.fence, current.fence)
        # Use the current revision with the old token: this isolates fencing from
        # stale-revision rejection while the replacement attempt is running.
        self.conflict(lambda c: repository.complete_attempt(c, current, newer.revision, "result", {"value": "ok"}))
        with self.app.state.engine.begin() as conn:
            result = repository.complete_attempt(conn, newer, newer.revision, "result", {"value": "ok"})
        with self.app.state.engine.begin() as conn:
            replay = repository.complete_attempt(conn, newer, newer.revision, "result", {"value": "ok"})
        self.assertEqual(result, replay)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(self.count("run_outputs", run_id), 1)
        self.assertEqual(self.count("run_attempts", run_id), 2)
        self.conflict(lambda c: repository.complete_attempt(c, newer, newer.revision, "result", {"value": "changed"}))
        self.conflict(lambda c: repository.complete_attempt(c, newer, result.revision, "result", {"value": "ok"}))

    def test_05_output_terminal_event_rollback_and_postcommit_ack_loss(self):
        run_id, _, _, token = self.prepared()
        with self.assertRaises(RuntimeError):
            with self.app.state.engine.begin() as conn:
                # Crash window after output/Run writes, before terminal-event commit.
                with patch.object(repository, "_event", side_effect=RuntimeError("SYNTHETIC_PRECOMMIT")):
                    repository.complete_attempt(conn, token, token.revision, "result", {"value": "durable"})
        self.assertEqual(self.row(run_id)["status"], "running")
        self.assertEqual(self.row(run_id)["revision"], token.revision)
        self.assertEqual(self.count("run_outputs", run_id), 0)
        with self.app.state.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM run_events WHERE run_id=:r AND type='succeeded'"), {"r": run_id}).scalar_one(), 0)
        with self.app.state.engine.begin() as conn:
            canonical = repository.complete_attempt(conn, token, token.revision, "result", {"value": "durable"})
        # Completion acknowledgement is deliberately ignored after actual commit.
        with self.app.state.engine.begin() as conn:
            recovered = repository.complete_attempt(conn, token, token.revision, "result", {"value": "durable"})
        self.assertEqual(canonical, recovered)
        fetched = self.client.get(f"/api/v1/runs/{run_id}", headers=self.auth)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["status"], "succeeded")
        self.assertEqual(len(fetched.json()["output_refs"]), 1)
        events = self.client.get(f"/api/v1/runs/{run_id}/events", headers=self.auth).json()["items"]
        self.assertEqual([e["type"] for e in events], ["queued", "running", "succeeded"])
        self.assertEqual([e["sequence"] for e in events], [1, 2, 3])

    def test_06_revoked_scope_and_canceled_work_denied(self):
        run_id, _, _, token = self.prepared()
        row = self.row(run_id)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),
                {"p": row["requested_by"], "c": row["case_id"]})
        self.conflict(lambda c: repository.admit_work(c, token, token.revision), 403)
        self.conflict(lambda c: repository.renew_attempt(c, token, token.revision), 403)
        self.conflict(lambda c: repository.complete_attempt(c, token, token.revision, "result", {"value": "denied"}), 403)
        self.assertEqual(self.count("run_outputs", run_id), 0)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=true WHERE principal_id=:p AND case_id=:c"),
                {"p": row["requested_by"], "c": row["case_id"]})
            changed = {**row["scope_snapshot"], "operation": "ungranted"}
            conn.execute(text("UPDATE runs SET scope_snapshot=CAST(:s AS jsonb) WHERE id=:r"),
                {"s": json.dumps(changed), "r": run_id})
        try:
            self.conflict(lambda c: repository.admit_work(c, token, token.revision), 403)
            self.conflict(lambda c: repository.complete_attempt(c, token, token.revision, "result", {"value": "denied"}), 403)
        finally:
            with self.app.state.engine.begin() as conn:
                conn.execute(text("UPDATE runs SET scope_snapshot=CAST(:s AS jsonb) WHERE id=:r"),
                    {"s": json.dumps(row["scope_snapshot"]), "r": run_id})
        canceled, fake, driver = self.new()
        response = self.client.post(f"/api/v1/runs/{canceled}/cancel", json={"expected_revision": 1},
            headers={**self.auth, "Idempotency-Key": "cancel-" + str(canceled)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(driver.tick(canceled), "not_eligible")
        self.assertEqual(fake.submissions, 0)
        forged = replace(token, run_id=canceled)
        self.conflict(lambda c: repository.complete_attempt(c, forged, 3, "result", {"value": "denied"}))
        self.assertEqual(self.count("run_outputs", canceled), 0)

    def test_07_failed_and_uncertain_effects_never_automatically_retry(self):
        for uncertain, expected in ((False, "failed"), (True, "uncertain")):
            run_id, _, driver, token = self.prepared()
            with self.app.state.engine.begin() as conn:
                result = repository.mark_failed(conn, token, token.revision, uncertain=uncertain)
            self.assertEqual(result.status, expected)
            self.assertEqual(result.output_refs, [])
            self.assertEqual(driver.tick(run_id), "not_eligible")
            self.conflict(lambda c: repository.claim_attempt(c, run_id, "unmapped", "worker", result.revision))

    def test_08_duplicate_publication_is_one_atomic_result(self):
        run_id, _, _, token = self.prepared()
        self.conflict(lambda c: repository.complete_attempt(c, token, token.revision,
            "one", {"value": "\U0001f600" * 1024}), 422)
        def finish(_):
            with self.app.state.engine.begin() as conn:
                return repository.complete_attempt(conn, token, token.revision, "one", {"value": "same"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(finish, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.count("run_outputs", run_id), 1)
        self.assertEqual(self.row(run_id)["revision"], token.revision + 1)
        self.conflict(lambda c: repository.complete_attempt(c, token, token.revision, "other", {"value": "same"}))
        row = self.row(run_id)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),
                {"p": row["requested_by"], "c": row["case_id"]})
        try:
            self.conflict(lambda c: repository.complete_attempt(c, token, token.revision, "one", {"value": "same"}), 403)
        finally:
            with self.app.state.engine.begin() as conn:
                conn.execute(text("UPDATE case_grants SET can_write=true WHERE principal_id=:p AND case_id=:c"),
                    {"p": row["requested_by"], "c": row["case_id"]})

    def test_09_attempt_cap_and_authority_before_dispatch(self):
        run_id, _, driver = self.new()
        self.assertEqual(driver.tick(run_id), "acknowledged")
        for _ in range(2):
            token = self.claim(run_id, seconds=1)
            time.sleep(1.1)
            with self.app.state.engine.begin() as conn:
                repository.expire_attempt(conn, run_id, token.revision)
        self.conflict(lambda c: repository.claim_attempt(c, run_id,
            c.execute(text("SELECT external_id FROM run_scheduler_executions WHERE run_id=:r"),
                      {"r": run_id}).scalar_one(), "third-worker", self.row(run_id)["revision"], 1))
        self.assertEqual(self.count("run_attempts", run_id), 2)
        blocked, fake, driver = self.new()
        row = self.row(blocked)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),
                {"p": row["requested_by"], "c": row["case_id"]})
        with self.assertRaises(Problem) as caught:
            driver.tick(blocked)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(fake.submissions, 0)
        self.assertEqual(self.outbox(blocked)["dispatch_count"], 0)

    def test_10_scheduler_execution_identity_cannot_cross_runs(self):
        first, _, _ = self.new()
        second, _, _ = self.new()
        fixed = Execution("fake-collision-" + str(first))
        class CollidingPort:
            def submit(self, command):
                return fixed
            def lookup(self, command):
                return Reconciliation("found", (fixed,))
        driver = Dispatcher(self.app.state.engine, CollidingPort(), (first, second))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(driver.tick, (first, second)))
        self.assertEqual(results.count("acknowledged"), 1)
        self.assertEqual(results.count("reconcile_required"), 1)
        self.assertEqual(self.count("run_scheduler_executions", first) + self.count("run_scheduler_executions", second), 1)
        self.assertEqual(self.row(first)["status"], "queued")
        self.assertEqual(self.row(second)["status"], "queued")


if __name__ == "__main__":
    unittest.main()
