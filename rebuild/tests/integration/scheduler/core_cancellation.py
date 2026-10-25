"""Actual-core cancellation fixture, executed only by the Backend runtime owner.

Injected ports/finally receipts are synthetic. No native process/provider cleanup
claim. Every operation is allowlisted to new synthetic Runs; old rows are retained.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
import time
import unittest
from uuid import UUID, uuid4

from sqlalchemy import text

from services.api.errors import Problem
from services.api.runs import repository as repo
from services.worker import cancellation as cancel, delivery
from services.worker.async_dispatch import AsyncDispatcher
from services.worker.dispatch import Dispatcher
from services.worker.hatchet_contracts import Binding, Observation, Policy, Result
from services.worker.scheduler_port import FakeSchedulerPort, Execution
from tests.integration.scheduler import core_delivery, core_journal


class StopPort:
    def __init__(self, binding, observed):
        self.binding, self.policy, self.observed = binding, Policy(), observed
        self.cancels = self.lookups = 0
        self.before = lambda: None
        self.unknown = False

    async def cancel(self, spec, root):
        self.cancels += 1
        self.before()
        return Result("unknown") if self.unknown else Result("cancel_requested", (self.observed,), (), "verified")

    async def lookup(self, spec):
        self.lookups += 1
        self.before()
        return Result("unknown") if self.unknown else Result("found", (self.observed,), (), "verified", True)

    async def cancel_fake(self, external_id, operation):
        self.cancels += 1
        return Result("cancel_requested", reason="verified")


class CoreCancellationProof(unittest.TestCase):
    case = core_journal.RunJournalProof.case
    create = core_journal.RunJournalProof.create
    error = core_journal.RunJournalProof.error
    row = core_delivery.CoreDeliveryProof.row
    count = core_delivery.CoreDeliveryProof.count
    new = core_delivery.CoreDeliveryProof.new
    register = core_delivery.CoreDeliveryProof.register
    prepared = core_delivery.CoreDeliveryProof.prepared
    conflict = core_delivery.CoreDeliveryProof.conflict
    tables = core_delivery.CoreDeliveryProof.tables + ("run_cancellations", "run_cancel_targets", "run_cancel_receipts")

    @classmethod
    def snapshot(cls):
        with cls.app.state.engine.connect() as conn:
            rows = [{r["id"]: dict(r) for r in conn.execute(text(f"SELECT * FROM {table}")).mappings()} for table in cls.tables]
            rows.append({(r["run_id"],r["sequence"]): dict(r) for r in conn.execute(text("SELECT * FROM run_events")).mappings()})
            return rows

    @classmethod
    def setUpClass(cls):
        core_journal.RunJournalProof.setUpClass.__func__(cls)
        cls.binding = Binding(uuid4(),uuid4(),uuid4(),"synthetic-read-only","cancel-proof")
        cls.baseline = cls.snapshot()

    @classmethod
    def tearDownClass(cls):
        try:
            for old,new in zip(cls.baseline,cls.snapshot()):
                if any(new.get(k) != v for k,v in old.items()):
                    raise AssertionError("Preexisting Run/cancellation/event history changed")
        finally:
            core_journal.RunJournalProof.tearDownClass.__func__(cls)

    def request(self, run_id, *, revision=None, key=None, auth=None):
        return self.client.post(f"/api/v1/runs/{run_id}/cancel",
            json={"expected_revision": self.row("runs",run_id)["revision"] if revision is None else revision},
            headers={**(auth or self.auth),"Idempotency-Key": key or str(uuid4())})

    def active(self, seconds=5):
        data = self.prepared(seconds=seconds)
        result = self.request(data[0])
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["status"],"cancel_requested")
        return data

    def execution(self, run_id, root):
        with self.app.state.engine.connect() as conn:
            return conn.execute(text("SELECT id FROM run_scheduler_executions WHERE run_id=:r AND external_id=:root"),
                                {"r":run_id,"root":str(root)}).scalar_one()

    def issue(self, data):
        run_id,context,_,_,_,_,observed,token,proof = data
        with self.app.state.engine.begin() as conn:
            return cancel.issue_cleanup(conn,context,run_id,self.execution(run_id,observed.root_id),token.attempt_id,proof.worker_instance_id)

    def record(self, context, credential, *, result="succeeded", receipt=None):
        with self.app.state.engine.begin() as conn:
            return cancel.record_cleanup(conn,context,credential,receipt or uuid4(),result)

    def settle(self, context, run_id):
        with self.app.state.engine.begin() as conn:
            return cancel.settle_cancellation(conn,context,run_id)

    def test_01_queued_fast_path_is_preserved(self):
        run = self.create(self.case()).json()
        run_id,key = UUID(run["id"]),str(uuid4())
        first = self.request(run_id,revision=1,key=key)
        self.assertEqual(first.status_code,200)
        self.assertEqual((first.json()["status"],first.json()["revision"]),("canceled",3))
        self.assertEqual(first.json(),self.request(run_id,revision=1,key=key).json())
        self.assertIsNone(first.json()["cancellation_id"])
        self.assertEqual(self.count("run_cancellations",run_id),0)
        self.assertEqual(self.row("run_outbox",run_id)["state"],"suppressed")

    def test_02_cancel_immediately_fences_work_renew_publication_and_claim(self):
        data = self.active()
        run_id,context,_,driver,spec,_,observed,token,_ = data
        row = self.row("runs",run_id)
        self.assertGreater(row["fence"],token.fence)
        self.conflict(lambda c:repo.admit_work(c,token,row["revision"]))
        self.conflict(lambda c:repo.renew_attempt(c,token,row["revision"]))
        self.conflict(lambda c:repo.complete_attempt(c,token,row["revision"],"result",{"value":"denied"}))
        self.conflict(lambda c:repo.claim_attempt(c,run_id,str(observed.root_id),"worker",row["revision"],
            scheduler_kind="hatchet-v1",worker_instance_id=uuid4()))
        self.assertEqual(asyncio.run(driver.tick(run_id)),"not_eligible")
        self.assertEqual(self.settle(context,run_id).status,"cancel_requested")
        self.assertEqual(self.count("run_outputs",run_id),0)

    def test_03_finally_can_report_after_work_grant_and_lease_revocation(self):
        data = self.active(seconds=1)
        run_id,context = data[:2]
        time.sleep(1.1)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE case_id=:c AND principal_id=:p"),
                         {"c":context.case_id,"p":context.principal_id})
        credential = self.issue(data)
        self.assertNotIn(str(credential.secret),repr(credential))
        self.record(context,credential)
        self.assertEqual(self.row("runs",run_id)["status"],"canceled")
        self.assertEqual(self.row("runs",run_id)["cleanup_status"],"succeeded")
        self.assertEqual(self.request(run_id).status_code,404)
        self.assertEqual(self.count("run_outputs",run_id),0)

    def test_04_foreign_old_or_forged_cleanup_authority_rejected(self):
        data = self.active()
        credential = self.issue(data)
        for wrong in (replace(credential,generation=0),replace(credential,generation=True),
            replace(credential,cancel_id=uuid4()),replace(credential,execution_id=uuid4()),
            replace(credential,attempt_id=uuid4()),replace(credential,fence=True),
            replace(credential,worker_instance_id=uuid4()),replace(credential,secret=uuid4()),
            replace(credential,task_ids=(uuid4(),))):
            self.conflict(lambda c:cancel.record_cleanup(c,data[1],wrong,uuid4(),"succeeded"))
        wrong_context = replace(data[1],case_id=uuid4())
        self.conflict(lambda c:cancel.record_cleanup(c,wrong_context,credential,uuid4(),"succeeded"))
        self.conflict(lambda c:repo.admit_work(c,credential,self.row("runs",data[0])["revision"]))
        self.assertEqual(self.count("run_cancel_receipts",data[0]),0)

    def test_05_request_and_receipt_exact_duplicates_are_idempotent(self):
        data = self.prepared(seconds=5)
        key = str(uuid4())
        first = self.request(data[0],revision=2,key=key)
        self.assertEqual(first.status_code,200)
        self.assertEqual(self.request(data[0],revision=2,key=key).json(),first.json())
        credential = self.issue(data)
        self.assertIsNone(self.issue(data))
        receipt_id = uuid4()
        one = self.record(data[1],credential,receipt=receipt_id)
        before = self.row("runs",data[0])
        self.assertEqual(self.record(data[1],credential,receipt=receipt_id),one)
        self.assertEqual(self.row("runs",data[0]),before)
        self.assertEqual(self.request(data[0],revision=2,key=key).json(),first.json())
        self.error(self.request(data[0],revision=before["revision"],key=key),409)
        self.conflict(lambda c:cancel.record_cleanup(c,data[1],credential,receipt_id,"failed"))
        self.conflict(lambda c:cancel.record_cleanup(c,data[1],credential,uuid4(),"succeeded"))
        self.assertEqual(self.count("run_cancellations",data[0]),1)
        self.assertEqual(self.count("run_cancel_receipts",data[0]),1)
        other = self.active()
        other_credential = self.issue(other)
        self.conflict(lambda c:cancel.record_cleanup(c,other[1],other_credential,receipt_id,"succeeded"))
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE case_id=:c AND principal_id=:p"),
                         {"c":data[1].case_id,"p":data[1].principal_id})
        self.error(self.request(data[0],revision=2,key=key),404)

    def test_06_failed_unknown_and_missing_finally_never_mean_canceled(self):
        for result in ("failed","unknown",None):
            data = self.active()
            if result:
                self.record(data[1],self.issue(data),result=result)
            else:
                self.settle(data[1],data[0])
            row = self.row("runs",data[0])
            self.assertEqual(row["status"],"cancel_requested")
            self.assertEqual(row["cleanup_status"],result or "pending")
            self.assertIsNone(row["finished_at"])

    def test_07_broker_cancel_ack_only_and_no_transaction_across_await(self):
        data = self.active()
        port = StopPort(data[1].binding,data[6])
        def unlocked():
            with self.app.state.engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout='500ms'"))
                conn.execute(text("SELECT id FROM runs WHERE id=:r FOR UPDATE"),{"r":data[0]})
        port.before = unlocked
        driver = cancel.AsyncCancellationDispatcher(self.app.state.engine,port,{data[0]:data[1]})
        self.assertEqual(asyncio.run(driver.tick(data[0])),"acknowledged")
        self.assertEqual(self.row("run_cancel_targets",data[0])["command_state"],"acknowledged")
        self.assertEqual(self.row("runs",data[0])["status"],"cancel_requested")
        self.assertEqual(self.count("run_cancel_receipts",data[0]),0)
        self.record(data[1],self.issue(data))
        self.assertEqual(self.row("runs",data[0])["status"],"canceled")

    def test_08_unknown_cancel_is_bounded_and_not_cleanup(self):
        data = self.active()
        port = StopPort(data[1].binding,data[6])
        port.unknown = True
        driver = cancel.AsyncCancellationDispatcher(self.app.state.engine,port,{data[0]:data[1]})
        for _ in range(3):
            self.assertEqual(asyncio.run(driver.tick(data[0])),"reconcile_required")
        self.assertEqual(asyncio.run(driver.tick(data[0])),"not_eligible")
        target = self.row("run_cancel_targets",data[0])
        self.assertEqual((target["cancel_count"],target["lookup_count"]),(1,2))
        self.assertEqual((port.cancels,port.lookups),(1,2))
        self.assertEqual(self.row("runs",data[0])["status"],"cancel_requested")

    def test_09_claimed_unknown_late_delivery_gets_cleanup_only(self):
        run_id,context,_,driver,spec = self.new()
        reserved = driver.reserve(run_id)
        self.assertEqual(self.request(run_id).status_code,200)
        observed = Observation(uuid4(),(uuid4(),),"RUNNING")
        received = self.register(context,spec,observed)
        self.assertIsNone(received.token)
        self.assertIsNotNone(received.cleanup)
        self.record(context,received.cleanup)
        self.assertEqual(self.row("runs",run_id)["status"],"cancel_requested")
        self.assertEqual(driver.finish(reserved,Result("acknowledged",(observed,),(),"verified")),"acknowledged")
        self.assertEqual(self.row("runs",run_id)["status"],"canceled")
        self.assertEqual(self.count("run_attempts",run_id),0)

    def test_10_all_mapped_roots_and_candidates_must_settle(self):
        data = self.active()
        run_id,context,_,driver,spec,old,observed,_,_ = data
        other = Observation(uuid4(),(uuid4(),),"RUNNING")
        driver.finish(old,Result("unknown",candidate_ids=(other.root_id,)))
        self.record(context,self.issue(data))
        self.assertEqual(self.row("runs",run_id)["status"],"cancel_requested")
        received = self.register(context,spec,other)
        self.assertIsNotNone(received.cleanup)
        self.record(context,received.cleanup)
        self.assertEqual(self.row("runs",run_id)["status"],"cancel_requested")
        driver.finish(old,Result("acknowledged",(observed,other),(),"verified"))
        self.assertEqual(self.row("runs",run_id)["status"],"canceled")
        self.assertEqual(self.count("run_cancel_receipts",run_id),2)

    def test_11_late_root_and_task_expansion_reopen_without_work(self):
        for expand in (False,True):
            data = self.active()
            self.record(data[1],self.issue(data))
            self.assertEqual(self.row("runs",data[0])["status"],"canceled")
            observed = replace(data[6],task_ids=data[6].task_ids+(uuid4(),)) if expand else Observation(uuid4(),(uuid4(),),"RUNNING")
            data[3].finish(data[5],Result("acknowledged",(observed,),(),"verified"))
            row = self.row("runs",data[0])
            self.assertEqual(row["status"],"cancel_requested")
            self.assertEqual(self.count("run_cancel_receipts",data[0]),1)
            self.assertEqual(self.count("run_attempts",data[0]),1)
            self.assertIsNone(row["finished_at"])

    def test_12_success_and_cancel_lock_order_has_one_winner(self):
        for cancel_wins in (True,False):
            data = self.prepared(seconds=5)
            entered = threading.Event()
            engine = self.app.state.engine
            with ThreadPoolExecutor(max_workers=1) as pool:
                with engine.begin() as conn:
                    row = repo.locked_run(conn,data[0])
                    def loser():
                        entered.set()
                        if cancel_wins:
                            try:
                                with engine.begin() as other:
                                    repo.complete_attempt(other,data[7],2,"result",{"value":"denied"})
                            except Problem:
                                return "denied"
                        else:
                            return self.request(data[0],revision=2).status_code
                    future = pool.submit(loser)
                    self.assertTrue(entered.wait(1))
                    if cancel_wins:
                        repo.request_cancellation(conn,row,row["requested_by"])
                    else:
                        repo.complete_attempt(conn,data[7],2,"result",{"value":"winner"})
                self.assertEqual(future.result(timeout=8),"denied" if cancel_wins else 409)
            self.assertEqual(self.count("run_outputs",data[0]),0 if cancel_wins else 1)
            self.assertEqual(self.row("runs",data[0])["status"],"cancel_requested" if cancel_wins else "succeeded")

    def test_13_cancel_wins_claim_and_native_receive_race(self):
        run_id,context,_,_,spec = self.new()
        observed = Observation(uuid4(),(uuid4(),),"RUNNING")
        # A reserved submit ensures this is active, not the queued fast path.
        driver = AsyncDispatcher(self.app.state.engine,core_delivery.InjectedPort(context.binding),{run_id:context})
        driver.reserve(run_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.app.state.engine.begin() as conn:
                row = repo.locked_run(conn,run_id)
                future = pool.submit(lambda:self.register(context,spec,observed))
                repo.request_cancellation(conn,row,row["requested_by"])
            receipt = future.result(timeout=8)
        self.assertIsNone(receipt.token)
        self.assertIsNotNone(receipt.cleanup)
        self.assertEqual(self.count("run_attempts",run_id),0)

    def test_14_partial_output_and_unknown_usage_are_retained_exactly(self):
        data = self.prepared(seconds=5)
        content = {"value":"partial synthetic fixture"}
        output_id = uuid4()
        from services.api.runs.contracts import UnknownUsage
        from services.api.db import digest
        refs = [{"id":str(output_id),"kind":"run_output","sha256":digest(content)}]
        usage = UnknownUsage().model_dump()
        with self.app.state.engine.begin() as conn:
            conn.execute(text("""INSERT INTO run_outputs(id,run_id,output_key,sha256,content,attempt_id,fence,expected_revision)
                VALUES(:id,:r,'partial',:hash,CAST(:content AS jsonb),:a,:f,2)"""),
                {"id":output_id,"r":data[0],"hash":digest(content),"content":json.dumps(content),"a":data[7].attempt_id,"f":data[7].fence})
            conn.execute(text("UPDATE runs SET output_refs=CAST(:refs AS jsonb),usage=CAST(:usage AS jsonb) WHERE id=:r"),
                         {"r":data[0],"refs":json.dumps(refs),"usage":json.dumps(usage)})
        self.assertEqual(self.request(data[0]).status_code,200)
        self.record(data[1],self.issue(data))
        row = self.row("runs",data[0])
        self.assertEqual(row["output_refs"],refs)
        self.assertEqual(row["usage"],usage)
        snapshot = self.row("run_cancellations",data[0])["request_snapshot"]
        self.assertEqual(snapshot["usage"],usage)
        self.assertEqual(snapshot["output_refs"],refs)
        self.assertEqual(self.client.get(f"/api/v1/runs/{data[0]}",headers=self.auth).json()["usage"]["state"],"unknown")

    def test_15_another_current_writer_can_cancel_revoked_original_work(self):
        data = self.prepared(seconds=5)
        with self.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),{"p":data[1].principal_id,"c":data[1].case_id})
            conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,true)"),{"p":self.principal_b,"c":data[1].case_id})
        self.assertEqual(self.request(data[0],auth=self.auth_b).status_code,200)
        self.record(data[1],self.issue(data))
        self.assertEqual(self.row("runs",data[0])["status"],"canceled")

    def test_16_fake_active_and_claimed_late_ack_are_preserved(self):
        for claimed in (False,True):
            result = self.create(self.case()).json()
            run_id = UUID(result["id"])
            row = self.row("runs",run_id)
            context = delivery.DeliveryContext(self.binding,row["case_id"],row["requested_by"])
            fake = FakeSchedulerPort()
            driver = Dispatcher(self.app.state.engine,fake,(run_id,))
            if claimed:
                reserved = driver.reserve(run_id)
                token = None
            else:
                self.assertEqual(driver.tick(run_id),"acknowledged")
                external = self.row("run_scheduler_executions",run_id)["external_id"]
                with self.app.state.engine.begin() as conn:
                    token = repo.claim_attempt(conn,run_id,external,"synthetic-worker",1)
            self.assertEqual(self.request(run_id).status_code,200)
            if claimed:
                self.assertEqual(driver._finish(reserved,(Execution("fake-late-"+str(uuid4())),),next_state="acknowledged"),"acknowledged")
            execution = self.row("run_scheduler_executions",run_id)
            with self.app.state.engine.begin() as conn:
                credential = cancel.issue_cleanup(conn,context,run_id,execution["id"],token.attempt_id if token else None,uuid4())
            self.record(context,credential)
            self.assertEqual(self.row("runs",run_id)["status"],"canceled")

    def test_17_public_receipts_remain_private_and_sse_unsupported(self):
        data = self.active()
        credential = self.issue(data)
        rendered = self.client.get(f"/api/v1/runs/{data[0]}",headers=self.auth).text
        self.assertNotIn(str(credential.secret),rendered)
        self.assertNotIn("cleanup_credential_hash",rendered)
        stream = self.client.get(f"/api/v1/runs/{data[0]}/events",params={"limit":1},headers={**self.auth,"Accept":"text/event-stream"})
        self.assertEqual(stream.status_code,200)
        self.assertTrue(stream.headers["content-type"].startswith("text/event-stream"))
        self.assertIn("id: 1\n",stream.text)
        self.assertEqual(json.loads(next(line[6:] for line in stream.text.splitlines() if line.startswith("data: ")))["sequence"],1)
        port = StopPort(data[1].binding,data[6])
        driver = cancel.AsyncCancellationDispatcher(self.app.state.engine,port,{data[0]:data[1]})
        if self.baseline[0]:
            with self.assertRaises(ValueError):
                driver.reserve(next(iter(self.baseline[0])))

    def test_18_injected_cooperative_finally_success_failure_or_no_ack(self):
        for result in ("succeeded","failed",None):
            data = self.active()
            credential = self.issue(data)
            async def scenario():
                entered = asyncio.Event()
                async def handler():
                    try:
                        entered.set()
                        await asyncio.Event().wait()
                    finally:
                        if result is not None:
                            self.record(data[1],credential,result=result)
                task = asyncio.create_task(handler())
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            asyncio.run(scenario())
            self.assertEqual(self.row("runs",data[0])["status"],"canceled" if result == "succeeded" else "cancel_requested")
            self.assertEqual(self.count("run_cancel_receipts",data[0]),int(result is not None))

    def test_19_stop_deadline_and_driver_cancellation_preserve_intent(self):
        data = self.active()
        class SlowPort(StopPort):
            async def cancel(inner,spec,root):
                await asyncio.Event().wait()
            async def lookup(inner,spec):
                await asyncio.Event().wait()
        port = SlowPort(data[1].binding,data[6])
        port.policy = Policy(total_seconds=0.05)
        driver = cancel.AsyncCancellationDispatcher(self.app.state.engine,port,{data[0]:data[1]})
        self.assertEqual(asyncio.run(driver.tick(data[0])),"reconcile_required")
        async def cancel_lookup():
            task = asyncio.create_task(driver.tick(data[0]))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(cancel_lookup())
        target = self.row("run_cancel_targets",data[0])
        self.assertEqual(target["command_state"],"reconcile_required")
        self.assertIsNone(target["claim_token"])
        self.assertEqual((target["cancel_count"],target["lookup_count"]),(1,1))
        self.assertEqual(self.row("runs",data[0])["status"],"cancel_requested")

    def test_20_early_delivery_cleanup_waits_for_submit_reply(self):
        run_id,context,_,driver,spec = self.new()
        reserved = driver.reserve(run_id)
        observed = Observation(uuid4(),(uuid4(),),"RUNNING")
        instance = uuid4()
        receipt = self.register(context,spec,observed,instance=instance)
        self.assertIsNotNone(receipt.token)
        self.assertEqual(self.row("run_outbox",run_id)["claim_token"],reserved.token)
        self.assertEqual(self.request(run_id).status_code,200)
        with self.app.state.engine.begin() as conn:
            credential = cancel.issue_cleanup(conn,context,run_id,receipt.execution_id,receipt.token.attempt_id,instance)
        self.record(context,credential)
        self.assertEqual(self.row("runs",run_id)["status"],"cancel_requested")
        driver.finish(reserved,Result("acknowledged",(observed,),(),"verified"))
        self.assertEqual(self.row("runs",run_id)["status"],"canceled")


if __name__ == "__main__":
    unittest.main()
