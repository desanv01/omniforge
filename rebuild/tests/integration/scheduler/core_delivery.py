"""B3B1 actual-core fixture; sole backend owner executes, never this worker.

All ports/process receipts are synthetic injected trust boundaries. No vendor,
OS termination, provider, credentials, global drain or active cancellation proof.
Rows are additive/retained. Snapshot asserts all preexisting delivery rows survive.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time
import unittest
from uuid import UUID, uuid4

from sqlalchemy import text

from services.api.errors import Problem
from services.api.runs import repository as repo
from services.worker import delivery
from services.worker.async_dispatch import AsyncDispatcher
from services.worker.dispatch import Dispatcher
from services.worker.hatchet_contracts import Binding, Observation, Policy, Result
from services.worker.hatchet_port import HatchetPort
from services.worker.scheduler_port import FakeSchedulerPort
from tests.integration.scheduler import core_journal


class InjectedPort:
    """Result boundary only; carries no network client or runtime identity."""
    def __init__(self, binding):
        self.binding, self.policy = binding, Policy()
        self.submissions = self.lookups = 0
        self.on_submit = self.on_lookup = lambda spec: Result("unknown")

    async def submit(self, spec):
        self.submissions += 1
        return self.on_submit(spec)

    async def lookup(self, spec):
        self.lookups += 1
        return self.on_lookup(spec)


class CoreDeliveryProof(unittest.TestCase):
    case = core_journal.RunJournalProof.case
    create = core_journal.RunJournalProof.create
    error = core_journal.RunJournalProof.error
    tables = ("runs", "run_outbox", "run_attempts", "run_outputs", "run_scheduler_executions", "run_scheduler_submissions")

    @classmethod
    def setUpClass(cls):
        core_journal.RunJournalProof.setUpClass.__func__(cls)
        cls.baseline = cls.snapshot()
        cls.binding = Binding(uuid4(), uuid4(), uuid4(), "synthetic-read-only", "delivery-proof")

    @classmethod
    def snapshot(cls):
        with cls.app.state.engine.connect() as conn:
            return [{row["id"]: dict(row) for row in conn.execute(text(f"SELECT * FROM {table}")).mappings()}
                    for table in cls.tables]

    @classmethod
    def tearDownClass(cls):
        try:
            for old, new in zip(cls.baseline, cls.snapshot()):
                if any(new.get(key) != value for key, value in old.items()):
                    raise AssertionError("Preexisting Run/delivery history changed")
        finally:
            core_journal.RunJournalProof.tearDownClass.__func__(cls)

    def row(self, table, run_id):
        assert table in self.tables
        key = "id" if table == "runs" else "run_id"
        with self.app.state.engine.connect() as conn:
            return dict(conn.execute(text(f"SELECT * FROM {table} WHERE {key}=:r"), {"r": run_id}).mappings().one())

    def count(self, table, run_id):
        assert table in self.tables + ("run_events",)
        with self.app.state.engine.connect() as conn:
            return conn.execute(text(f"SELECT count(*) FROM {table} WHERE run_id=:r"), {"r": run_id}).scalar_one()

    def new(self):
        result = self.create(self.case(), body={"budget": {"wall_seconds": 60}})
        self.assertEqual(result.status_code, 202)
        run_id = UUID(result.json()["id"])
        row = self.row("runs", run_id)
        context = delivery.DeliveryContext(self.binding, row["case_id"], row["requested_by"])
        port = InjectedPort(self.binding)
        driver = AsyncDispatcher(self.app.state.engine, port, {run_id: context})
        spec = driver.configure(run_id, 1)
        return run_id, context, port, driver, spec

    def register(self, context, spec, observed, *, revision=1, instance=None, seconds=5, payload=None):
        with self.app.state.engine.begin() as conn:
            return delivery.register_delivery(conn, context, spec, observed,
                spec.payload() if payload is None else payload, "synthetic-worker", instance or uuid4(), revision, seconds)

    def conflict(self, callback, status=409):
        with self.assertRaises(Problem) as caught:
            with self.app.state.engine.begin() as conn:
                callback(conn)
        self.assertEqual(caught.exception.status, status)

    def prepared(self, seconds=1):
        run_id, context, port, driver, spec = self.new()
        reserved = driver.reserve(run_id)
        observed = Observation(uuid4(), (uuid4(),), "RUNNING")
        instance = uuid4()
        receipt = self.register(context, spec, observed, instance=instance, seconds=seconds)
        self.assertIsNotNone(receipt.token)
        self.assertEqual(driver.finish(reserved, Result("acknowledged", (observed,), (observed.root_id,), "verified")), "acknowledged")
        proof = delivery.QuiescenceAttestation(uuid4(), run_id, receipt.token.attempt_id,
            receipt.token.fence, instance, (observed.root_id,), "synthetic-process-identity")
        return run_id, context, port, driver, spec, reserved, observed, receipt.token, proof

    def expire(self, run_id):
        time.sleep(1.1)
        with self.app.state.engine.begin() as conn:
            return repo.expire_attempt(conn, run_id, self.row("runs", run_id)["revision"])

    def rearm(self, context, spec, proof, revision):
        # Opaque receipt can be resolved only through this injected trusted map.
        issued = {proof.receipt_id: proof}
        with self.app.state.engine.begin() as conn:
            return delivery.rearm_delivery(conn, context, spec, proof.receipt_id, revision,
                                            verify_quiescence=issued.__getitem__)

    def test_01_real_adapter_early_registration_before_running_and_terminal_ack(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                run_id, context, _, _, spec = self.new()
                observed = Observation(uuid4(), (uuid4(),), "RUNNING")
                state = {}
                outer = self
                class Client:
                    async def trigger(inner, binding, command, timeout):
                        # Also proves the submit await holds no SQL Run lock.
                        with outer.app.state.engine.begin() as conn:
                            conn.execute(text("SET LOCAL lock_timeout='500ms'"))
                            conn.execute(text("SELECT id FROM runs WHERE id=:r FOR UPDATE"), {"r": run_id})
                        receipt = outer.register(context, command, observed)
                        state["token"] = receipt.token
                        if complete:
                            with outer.app.state.engine.begin() as conn:
                                repo.complete_attempt(conn, receipt.token, receipt.token.revision, "result", {"value": "synthetic"})
                        state["row"] = outer.row("runs", run_id)
                        state["events"] = outer.count("run_events", run_id)
                        return observed.root_id

                    async def get_run(inner, root, timeout):
                        fields = {"tenantId": str(context.binding.tenant_id), "workflowId": str(context.binding.workflow_id),
                            "workflowVersionId": str(context.binding.workflow_version_id), "status": "COMPLETED" if complete else "RUNNING",
                            "additionalMetadata": spec.metadata(context.binding)}
                        return {"run": {**fields, "metadata": {"id": str(root)}, "input": spec.payload()},
                            "tasks": [{**fields, "type": "TASK", "workflowRunExternalId": str(root),
                                       "taskExternalId": str(observed.task_ids[0])}]}
                port = HatchetPort(Client(), context.binding)
                driver = AsyncDispatcher(self.app.state.engine, port, {run_id: context})
                self.assertEqual(asyncio.run(driver.tick(run_id)), "acknowledged")
                self.assertEqual(self.row("runs", run_id), state["row"])
                self.assertEqual(self.count("run_events", run_id), state["events"])
                self.assertEqual(self.count("run_attempts", run_id), 1)
                self.assertEqual(self.count("run_outputs", run_id), int(complete))
                replay = self.register(context, spec, observed)
                self.assertIsNone(replay.token)
                self.assertEqual(self.row("run_outbox", run_id)["state"], "acknowledged")

    def test_02_early_ack_unknown_preserves_extra_candidates_and_bounded_lookup(self):
        run_id, context, port, driver, spec = self.new()
        first, second = Observation(uuid4(), (uuid4(),), "RUNNING"), Observation(uuid4(), (uuid4(),), "QUEUED")
        def submit(command):
            self.assertIsNotNone(self.register(context, command, first).token)
            return Result("unknown", candidate_ids=(first.root_id, second.root_id))
        port.on_submit = submit
        self.assertEqual(asyncio.run(driver.tick(run_id)), "acknowledged_unresolved")
        intent = self.row("run_outbox", run_id)
        self.assertEqual(intent["state"], "acknowledged")
        self.assertEqual(intent["candidate_ids"], [second.root_id])
        before = self.row("runs", run_id)
        port.on_lookup = lambda _: Result("found", (first, second), (first.root_id, second.root_id), "verified", True)
        self.assertEqual(asyncio.run(driver.tick(run_id)), "acknowledged")
        self.assertEqual(self.row("run_outbox", run_id)["candidate_ids"], [])
        self.assertEqual(self.row("runs", run_id), before)
        self.assertEqual((port.submissions, port.lookups), (1, 1))
        self.assertIsNone(self.register(context, spec, second).token)

    def test_03_unknown_is_never_absent_or_a_submit_retry(self):
        run_id, _, port, driver, _ = self.new()
        self.assertEqual(asyncio.run(driver.tick(run_id)), "reconcile_required")
        for _ in range(2):
            self.assertEqual(asyncio.run(driver.tick(run_id)), "reconcile_required")
        self.assertEqual(asyncio.run(driver.tick(run_id)), "not_eligible")
        self.assertEqual((port.submissions, port.lookups), (1, 2))
        self.assertEqual(self.count("run_attempts", run_id), 0)
        self.assertEqual(self.count("run_scheduler_executions", run_id), 0)

    def test_04_duplicate_workers_get_exactly_one_token_and_scope_is_checked(self):
        run_id, context, _, _, spec = self.new()
        observed = Observation(uuid4(), (uuid4(),), "RUNNING")
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda _: self.register(context, spec, observed), range(2)))
        self.assertEqual(sum(r.token is not None for r in receipts), 1)
        self.assertEqual(self.count("run_attempts", run_id), 1)
        for wrong in (replace(context, case_id=uuid4()), replace(context, principal_id=uuid4()),
                      replace(context, binding=replace(context.binding, tenant_id=uuid4()))):
            self.conflict(lambda conn: delivery.register_delivery(conn, wrong, spec, observed,
                spec.payload(), "worker", uuid4(), 1))
        for wrong in ({**spec.payload(), "generation": False}, {**spec.payload(), "input_hash": "0"*64}):
            self.conflict(lambda conn: delivery.register_delivery(conn, context, spec, observed, wrong, "worker", uuid4(), 1))
        for wrong in (replace(spec, generation=1), replace(spec, input_hash="0"*64)):
            self.conflict(lambda conn: delivery.register_delivery(conn, context, wrong, observed, wrong.payload(), "worker", uuid4(), 1))

    def test_05_cross_run_root_and_concurrent_task_collision_are_atomic(self):
        one, two = self.new(), self.new()
        observed = Observation(uuid4(), (uuid4(),), "RUNNING")
        self.register(one[1], one[4], observed)
        self.conflict(lambda conn: delivery.register_delivery(conn, two[1], two[4], observed,
            two[4].payload(), "worker", uuid4(), 1))
        self.assertEqual(self.count("run_scheduler_executions", two[0]), 0)
        three, four = self.new(), self.new()
        task = uuid4()
        def collide(item):
            try:
                return self.register(item[1], item[4], Observation(uuid4(), (task,), "RUNNING"))
            except Problem as exc:
                return exc
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(collide, (three, four)))
        self.assertEqual(sum(isinstance(v, delivery.DeliveryReceipt) for v in results), 1)
        self.assertEqual(sum(self.count("run_attempts", item[0]) for item in (three, four)), 1)

    def test_06_safe_rearm_keeps_budgets_and_old_ack_cannot_clear_new_claim(self):
        run_id, context, _, driver, spec, old, observed, token, proof = self.prepared()
        self.expire(run_id)
        revision = self.row("runs", run_id)["revision"]
        next_spec = self.rearm(context, spec, proof, revision)
        self.assertEqual(next_spec.generation, 1)
        current = driver.reserve(run_id)
        self.assertEqual(self.row("run_outbox", run_id)["dispatch_count"], 2)
        result = Result("acknowledged", (observed,), (observed.root_id,), "verified")
        self.assertEqual(driver.finish(old, result), "historical_ack")
        self.assertEqual(self.row("run_outbox", run_id)["claim_token"], current.token)
        self.assertIsNone(self.register(context, spec, observed).token)
        self.assertEqual(self.row("run_outbox", run_id)["claim_token"], current.token)
        new_observed = Observation(uuid4(), (uuid4(),), "RUNNING")
        new_token = self.register(context, next_spec, new_observed, revision=revision+1).token
        self.assertIsNotNone(new_token)
        self.assertGreater(new_token.fence, token.fence)
        self.conflict(lambda conn: repo.admit_work(conn, token, new_token.revision))
        with self.app.state.engine.begin() as conn:
            repo.complete_attempt(conn, new_token, new_token.revision, "result", {"value": "recovered synthetic"})
        self.assertEqual(self.count("run_outputs", run_id), 1)
        self.assertEqual(self.count("run_attempts", run_id), 2)
        with self.app.state.engine.connect() as conn:
            saved = conn.execute(text("SELECT * FROM run_scheduler_submissions WHERE run_id=:r AND generation=1"), {"r": run_id}).mappings().one()
            self.assertEqual(saved["recovery_receipt_id"], proof.receipt_id)
            self.assertEqual(len(saved["recovery_proof_hash"]), 64)
        replay = self.client.get(f"/api/v1/runs/{run_id}/events", headers=self.auth)
        self.assertEqual(replay.status_code, 200)
        self.assertIn("delivery_rearmed", [e["type"] for e in replay.json()["items"]])

    def test_07_rearm_denies_live_missing_bool_and_wrong_quiescence(self):
        run_id, context, _, _, spec, _, _, _, proof = self.prepared()
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, proof, 2,
            verify_quiescence=lambda _: proof))
        self.expire(run_id)
        revision = self.row("runs", run_id)["revision"]
        wrong_proofs = (True, None, replace(proof, root_ids=(uuid4(),)), replace(proof, attempt_id=uuid4()),
            replace(proof, worker_instance_id=uuid4()), replace(proof, fence=proof.fence+1),
            replace(proof, quiescent=1), replace(proof, effects="unknown"), replace(proof, process_identity=""))
        for wrong in wrong_proofs:
            self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, None, revision,
                verify_quiescence=lambda _: wrong))
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, None, revision,
            verify_quiescence=None))
        self.assertEqual(self.count("run_scheduler_submissions", run_id), 1)

    def test_08_unresolved_roots_and_exhausted_counters_block_rearm(self):
        run_id, context, _, _, spec, _, _, _, proof = self.prepared()
        self.expire(run_id)
        revision = self.row("runs", run_id)["revision"]
        candidate = uuid4()
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE run_outbox SET candidate_ids=ARRAY[CAST(:id AS uuid)] WHERE run_id=:r"), {"id": candidate, "r": run_id})
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, proof, revision, verify_quiescence=lambda _: proof))
        # Verify the candidate before removal; never discard it or infer absence.
        extra = Observation(candidate, (uuid4(),), "COMPLETED")
        self.assertIsNone(self.register(context, spec, extra).token)
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, proof, revision, verify_quiescence=lambda _: proof))
        both = replace(proof, root_ids=proof.root_ids + (candidate,))
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE run_outbox SET reconcile_count=2 WHERE run_id=:r"), {"r": run_id})
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, both, revision, verify_quiescence=lambda _: both))
        self.assertEqual(self.count("run_scheduler_submissions", run_id), 1)

    def test_09_authority_revocation_stops_dispatch_registration_and_rearm(self):
        run_id, context, _, driver, spec, _, observed, _, proof = self.prepared()
        self.expire(run_id)
        revision = self.row("runs", run_id)["revision"]
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE case_id=:c AND principal_id=:p"),
                         {"c": context.case_id, "p": context.principal_id})
        self.conflict(lambda conn: delivery.register_delivery(conn, context, spec, observed,
            spec.payload(), "worker", uuid4(), 1), 403)
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, proof, revision,
            verify_quiescence=lambda _: proof), 403)
        with self.assertRaises(Problem):
            driver.reserve(run_id)

    def test_10_fake_driver_skips_real_kind_and_allowlist_protects_history(self):
        run_id, _, _, driver, _ = self.new()
        fake = FakeSchedulerPort()
        self.assertEqual(Dispatcher(self.app.state.engine, fake, (run_id,)).tick(run_id), "not_eligible")
        self.assertEqual(fake.submissions, 0)
        self.assertEqual(self.row("run_outbox", run_id)["dispatch_count"], 0)
        if self.baseline[0]:
            with self.assertRaises(ValueError):
                asyncio.run(driver.tick(next(iter(self.baseline[0]))))
        with self.assertRaises(ValueError):
            AsyncDispatcher(self.app.state.engine, InjectedPort(self.binding), {})

    def test_11_native_terminal_is_bookkeeping_without_domain_success(self):
        run_id, context, _, _, spec = self.new()
        observed = Observation(uuid4(), (uuid4(),), "COMPLETED")
        self.assertIsNone(self.register(context, spec, observed).token)
        self.assertEqual(self.row("runs", run_id)["status"], "queued")
        self.assertEqual(self.count("run_attempts", run_id), 0)
        self.assertEqual(self.count("run_outputs", run_id), 0)
        self.assertIsNone(self.register(context, spec, replace(observed, native_status="RUNNING")).token)
        self.conflict(lambda conn: delivery.register_delivery(conn, context, spec,
            replace(observed, domain_completion_proved=True), spec.payload(), "worker", uuid4(), 1))

    def test_12_late_unknown_preserves_candidates_without_clearing_other_reservation(self):
        run_id, context, _, driver, spec, old, observed, _, _ = self.prepared(seconds=5)
        unknown_root = uuid4()
        self.assertEqual(driver.finish(old, Result("unknown", candidate_ids=(unknown_root,))), "acknowledged_unresolved")
        current = driver.reserve(run_id)
        self.assertIsNotNone(current)
        self.assertEqual(driver.finish(old, Result("acknowledged", (observed,), (), "verified")), "acknowledged_unresolved")
        self.assertEqual(self.row("run_outbox", run_id)["claim_token"], current.token)
        self.assertEqual(self.row("run_outbox", run_id)["candidate_ids"], [unknown_root])
        self.assertIsNone(self.register(context, spec, observed).token)
        self.assertEqual(self.row("run_outbox", run_id)["claim_token"], current.token)
        self.assertEqual(self.row("run_outbox", run_id)["last_error_code"], "delivery_unknown")
        self.conflict(lambda conn: repo.admit_work(conn, self._token(run_id), self.row("runs", run_id)["revision"]))

    def _token(self, run_id):
        with self.app.state.engine.connect() as conn:
            return repo._token(conn, run_id)

    def test_13_new_historical_root_invalidates_recovery_work_ceiling(self):
        run_id, context, _, driver, spec, old, _, _, proof = self.prepared()
        self.expire(run_id)
        revision = self.row("runs", run_id)["revision"]
        next_spec = self.rearm(context, spec, proof, revision)
        driver.reserve(run_id)
        token = self.register(context, next_spec, Observation(uuid4(), (uuid4(),), "RUNNING"), revision=revision+1).token
        extra = Observation(uuid4(), (uuid4(),), "COMPLETED")
        self.assertEqual(driver.finish(old, Result("acknowledged", (extra,), (), "verified")), "historical_ack")
        self.conflict(lambda conn: repo.admit_work(conn, token, token.revision))
        self.conflict(lambda conn: repo.complete_attempt(conn, token, token.revision, "result", {"value": "denied"}))
        self.assertEqual(self.count("run_outputs", run_id), 0)

    def test_14_current_scope_and_original_wall_budget_still_gate_rearm(self):
        run_id, context, _, _, spec, _, _, _, proof = self.prepared()
        self.expire(run_id)
        revision = self.row("runs", run_id)["revision"]
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE runs SET started_at=clock_timestamp()-interval '61 seconds' WHERE id=:r"), {"r": run_id})
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, proof, revision,
            verify_quiescence=lambda _: proof))
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE runs SET scope_snapshot='{}'::jsonb WHERE id=:r"), {"r": run_id})
        self.conflict(lambda conn: delivery.rearm_delivery(conn, context, spec, proof, revision,
            verify_quiescence=lambda _: proof), 403)

    def test_15_async_deadline_and_cancellation_leave_unresolved_intent(self):
        run_id, context, _, _, _ = self.new()
        class SlowPort(InjectedPort):
            async def submit(inner, spec):
                await asyncio.Event().wait()
        port = SlowPort(self.binding)
        port.policy = Policy(total_seconds=0.05)
        driver = AsyncDispatcher(self.app.state.engine, port, {run_id: context})
        self.assertEqual(asyncio.run(driver.tick(run_id)), "reconcile_required")
        self.assertEqual(self.row("run_outbox", run_id)["dispatch_count"], 1)
        other, context2, _, _, _ = self.new()
        canceled = AsyncDispatcher(self.app.state.engine, port, {other: context2})
        async def cancel():
            task = asyncio.create_task(canceled.tick(other))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(cancel())
        self.assertEqual(self.row("run_outbox", other)["state"], "reconcile_required")
        self.assertEqual(self.count("run_attempts", other), 0)


if __name__ == "__main__":
    unittest.main()
