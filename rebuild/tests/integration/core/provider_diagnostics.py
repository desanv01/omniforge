"""DEFERRED real-PG fixture source. No env/config/migration/engine construction.

Backend must explicitly inject the released isolated engine at 0009. Synthetic
metadata/capabilities and clock descriptors are test boundaries, NOT native proof.
No credential store/provider or subprocess is used. Do not run in source-only gate.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import hashlib
import threading
import queue
import time
import unittest
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adapters.models.contracts import Budget
from adapters.secrets.enrollment import EnrollmentBinding
from adapters.secrets.store import CredentialRef
from services.api.errors import Problem
from services.api.profiles import authority, repository, diagnostics as d
from services.api.providers.diagnostic_protocol import Reservation, Observation


ORIGINAL = tuple("principals cases case_grants artifacts artifact_associations idempotency provider_profile_versions "
                 "provider_enrollments runs run_events run_outbox run_attempts run_outputs run_scheduler_executions "
                 "run_scheduler_submissions run_cancellations run_cancel_targets run_cancel_receipts".split())


def snapshot(conn):
    from collections import Counter
    return {name: Counter(conn.execute(text(f"SELECT md5(row_to_json(t)::text) FROM {name} t")).scalars()) for name in ORIGINAL}


def seed(conn):
    """One new synthetic principal/case/bound profile; no actual credential exists."""
    principal, case, profile, enrollment = (uuid4() for _ in range(4))
    token = "synthetic-diagnostic-fixture:" + str(principal)
    conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:p,'synthetic diagnostic',:h)"),
                 {"p": principal, "h": hashlib.sha256(token.encode()).hexdigest()})
    conn.execute(text("INSERT INTO cases(id,revision,title,objective,policy_profile_ref) VALUES(:c,1,'diagnostic fixture','synthetic only','local')"), {"c": case})
    conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,true)"), {"p": principal,"c": case})
    caps = dict(calls=2,input_tokens=100,output_tokens=100,wall_seconds=30,tool_bytes=32)
    values = dict(label="synthetic diagnostic",endpoint="https://api.deepseek.com/chat/completions",model="deepseek-chat",caps=caps,enabled=False)
    repository.append(conn,principal,case,values,profile,1)
    ref=CredentialRef("wincred:omniforge:v1:"+str(uuid4()))  # Reference only, no store/value.
    binding=EnrollmentBinding(enrollment,principal,case,profile,1,ref)
    conn.execute(text("INSERT INTO provider_enrollments(operation_id,principal_id,case_id,profile_id,credential_ref,expected_revision) VALUES(:o,:p,:c,:f,:r,1)"),
                 {"o":enrollment,"p":principal,"c":case,"f":profile,"r":ref.value})
    repository.append(conn,principal,case,values,profile,2,binding=binding)
    conn.execute(text("UPDATE provider_enrollments SET state='attached',attached_revision=2,settled_at=clock_timestamp() WHERE operation_id=:o"),{"o":enrollment})
    repository.append(conn,principal,case,{**values,"enabled":True},profile,3)
    pin=authority.load_profile_conn(conn,principal,case,profile,3,authority.Purpose.EXECUTE_DIAGNOSTIC,bearer_token=token,requested_budget=Budget(**caps))
    return d.Invocation(uuid4(),uuid4(),1,"a"*64,uuid4(),1,principal,pin),token


def seed_original_baseline(conn):
    """Representative synthetic data in ALL eighteen original 0008 tables."""
    from services.api.runs import repository as runs
    from services.api.runs.contracts import RunCreate
    from services.worker import delivery, cancellation
    from services.worker.hatchet_contracts import Binding, Observation as NativeObservation
    ctx,token=seed(conn)
    artifact,association=uuid4(),uuid4()
    conn.execute(text("INSERT INTO artifacts(id,sha256,bytes) VALUES(:a,:h,0)"),{"a":artifact,"h":hashlib.sha256(artifact.bytes).hexdigest()})
    conn.execute(text("""INSERT INTO artifact_associations(id,case_id,artifact_id,source_id,original_name,media_type,publication_status,stage_name)
        VALUES(:a,:c,:blob,:s,'synthetic.txt','text/plain','committed','synthetic-journal-baseline')"""),
        {"a":association,"c":ctx.pin.case_id,"blob":artifact,"s":uuid4()})
    conn.execute(text("""INSERT INTO idempotency(principal_id,operation,key,body_hash,response,status)
        VALUES(:p,'synthetic-baseline',:k,:h,'{}'::jsonb,200)"""),{"p":ctx.principal_id,"k":str(uuid4()),"h":"a"*64})
    binding=Binding(uuid4(),uuid4(),uuid4(),"journal-baseline","journal-baseline")
    context=delivery.DeliveryContext(binding,ctx.pin.case_id,ctx.principal_id)
    for cancel in (False,True):
        run=runs.insert_queued(conn,ctx.principal_id,ctx.pin.case_id,RunCreate.model_validate({"budget":{"wall_seconds":60}}))
        spec=delivery.configure_delivery(conn,context,run.id,1)
        instance=uuid4()
        receipt=delivery.register_delivery(conn,context,spec,NativeObservation(uuid4(),(uuid4(),),"RUNNING"),spec.payload(),"synthetic-baseline",instance,1,60)
        if cancel:
            cancellation.request_cancellation(conn,runs.locked_run(conn,run.id),ctx.principal_id)
            credential=cancellation.issue_cleanup(conn,context,run.id,receipt.execution_id,receipt.token.attempt_id,instance)
            cancellation.record_cleanup(conn,context,credential,uuid4(),"unknown")  # Retain actual uncertainty.
        else:
            runs.complete_attempt(conn,receipt.token,receipt.token.revision,"baseline",{"value":"synthetic"})
    # One pending original intent is retained, never drained by journal tests.
    runs.insert_queued(conn,ctx.principal_id,ctx.pin.case_id,RunCreate())


def wait_for_owned_lock(conn, contender_pid, holder_pid, *, profile_id=None):
    """Bounded observation of EXACT backend blocked by EXACT holder; no query text.

    Profile waits additionally require the precise Python advisory key. Grant
    fixture holder holds only its named new grant row, so that holder edge fixes
    the intended authority conflict. Poll cadence alone is never evidence.
    """
    deadline=time.monotonic()+0.4
    if profile_id is None:
        sql="""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted
            AND locktype='transactionid' AND :holder=ANY(pg_blocking_pids(pid)))"""
        params={"pid":contender_pid,"holder":holder_pid}
    else:
        key=int.from_bytes(hashlib.sha256(("profile:"+str(profile_id)).encode()).digest()[:8],"big")
        sql="""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted
            AND locktype='advisory' AND classid::bigint=:hi AND objid::bigint=:lo
            AND objsubid=1 AND :holder=ANY(pg_blocking_pids(pid)))"""
        params={"pid":contender_pid,"holder":holder_pid,"hi":key>>32,"lo":key&0xffffffff}
    for _ in range(80):
        if conn.execute(text(sql),params).scalar_one() is True:return True
        if time.monotonic()>=deadline:return False
        threading.Event().wait(0.005)  # Poll pacing, not an inferred lock barrier.
    return False


class JournalPostgresProof(unittest.TestCase):
    engine = None  # Set explicitly by Backend's later released harness. No defaults.

    def setUp(self):
        if self.engine is None: raise RuntimeError("Explicit Backend runtime release/engine required")
        self.baseline=None
        self.addCleanup(self.preserve_and_check_pool)
        with self.engine.begin() as conn:
            if conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "0009_provider_diagnostics":
                raise RuntimeError("Expected separately applied isolated schema")
            self.baseline=snapshot(conn)
            self.ctx,self.token=seed(conn)
            self.bound=conn.execute(text("SELECT clock_timestamp()+interval '25 seconds'")).scalar_one()
        self.command=None
        self.trust=d.Trust(provenance=lambda command:command is self.command,
            cutoff=lambda conn,command,descriptor:descriptor.fixed_db_not_after,
            issue_capability=lambda command:hashlib.sha256(command.invocation.operation_id.bytes).digest())  # INERT only; no real producer.

    def preserve_and_check_pool(self):
        try:
            if self.baseline is not None:
                with self.engine.connect() as conn:
                    current=snapshot(conn)
                    self.assertTrue(all(not (old-current[name]) for name,old in self.baseline.items()))
        finally:
            self.assertEqual(self.engine.pool.checkedout(),0)

    def expect_problem(self, code, callback):
        with self.assertRaises(Problem) as caught:
            with self.engine.begin() as conn:callback(conn)
        self.assertEqual(caught.exception.code,code)

    def expect_sqlstate(self, code, sql, params):
        with self.assertRaises(DBAPIError) as caught:
            with self.engine.begin() as conn:conn.execute(text(sql),params)
        self.assertEqual(getattr(caught.exception.orig,"sqlstate",None),code)

    def reserved(self):
        admission=self.admitted()
        r=Reservation(self.ctx.operation_id,1,"b"*64,10,10)
        cmd,desc=self.command_for("reserve",{"reservation":r.replay_digest})
        with self.engine.begin() as conn:d.reserve_round(conn,cmd,r,desc,bearer_token=self.token,trust=self.trust)
        return admission,r

    def observed(self):
        admission,r=self.reserved()
        o=Observation(r,5,None,"provider_reported","response_received",10,10)
        cmd,desc=self.command_for("observe",{"observation":o.replay_digest})
        with self.engine.begin() as conn:d.observe_usage(conn,cmd,o,desc,bearer_token=self.token,trust=self.trust)
        return admission,r,o

    def current_time(self):
        with self.engine.connect() as conn:return conn.execute(text("SELECT clock_timestamp()")).scalar_one()

    def wait_db_until(self, moment, conn=None):
        end=time.monotonic()+5
        while time.monotonic()<end:
            if conn is None:now=self.current_time()
            else:now=conn.execute(text("SELECT clock_timestamp()")).scalar_one()
            if now>=moment:return
            threading.Event().wait(0.005)
        self.fail("Bounded DB-time barrier not reached")

    def command_for(self,kind,payload):
        from dataclasses import replace
        command=d.Command(self.ctx,uuid4(),0,kind,"0"*64)
        self.command=replace(command,request_digest=d.request_digest(command,payload))
        purpose="work_admission" if kind=="admit" else "settlement_decision" if kind=="settle" else "work_decision"
        return self.command,d.CutoffDescriptor(uuid4(),self.ctx.fingerprint,self.command.command_id,purpose,self.bound,0,uuid4(),"valid_conservative")

    def admitted(self):
        command,desc=self.command_for("admit",{})
        with self.engine.begin() as conn:
            return d.admit(conn,command,desc,bearer_token=self.token,trust=self.trust)

    def test_01_real_sql_reserve_usage_candidate_and_exact_replay(self):
        admitted=self.admitted();self.assertEqual(admitted.disposition,"original_prepared")
        r=Reservation(self.ctx.operation_id,1,"b"*64,10,10)
        cmd,desc=self.command_for("reserve",{"reservation":r.replay_digest})
        for index in range(2):
            with self.engine.begin() as conn:
                result=d.reserve_round(conn,cmd,r,desc,bearer_token=self.token,trust=self.trust)
                self.assertEqual(result.disposition,"original_prepared" if index==0 else "canonical_replay")
        o=Observation(r,None,None,"absent","transport_failed",10,10)
        cmd,desc=self.command_for("observe",{"observation":o.replay_digest})
        with self.engine.begin() as conn:d.observe_usage(conn,cmd,o,desc,bearer_token=self.token,trust=self.trust)
        cmd,desc=self.command_for("candidate",{"candidate_digest":"c"*64})
        with self.engine.begin() as conn:d.commit_candidate(conn,cmd,"c"*64,desc,bearer_token=self.token,trust=self.trust)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM provider_diagnostic_rounds WHERE operation_id=:o"),{"o":self.ctx.operation_id}).scalar_one(),1)

    def test_02_revocation_blocks_waiting_transaction_without_old_row_mutation(self):
        # Lock barrier: request cannot authenticate/grant until our NEW grant is
        # committed revoked. No arbitrary sleeps or whole-table pending scan.
        contender=queue.Queue(maxsize=1)
        cmd,desc=self.command_for("admit",{})
        def attempt():
            try:
                with self.engine.begin() as conn:
                    contender.put(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
                    d.admit(conn,cmd,desc,bearer_token=self.token,trust=self.trust)
            except Problem as error:return error.status,error.code
            return 0,"unexpected"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),{"p":self.ctx.principal_id,"c":self.ctx.pin.case_id})
                holder=conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
                future=executor.submit(attempt)
                pid=contender.get(timeout=1)
                self.assertTrue(wait_for_owned_lock(conn,pid,holder),"Exact contender grant wait was not observed")
            self.assertEqual(future.result(timeout=5),(403,"profile_forbidden"))

    def test_03_remaining_timeout_during_observed_profile_lock_wait(self):
        cmd,desc=self.command_for("admit",{})
        from dataclasses import replace
        with self.engine.connect() as conn:
            expiry=conn.execute(text("SELECT clock_timestamp()+interval '800 milliseconds'")).scalar_one()
        desc=replace(desc,fixed_db_not_after=expiry)
        contender=queue.Queue(maxsize=1)
        def attempt():
            try:
                with self.engine.begin() as conn:
                    contender.put(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
                    d.admit(conn,cmd,desc,bearer_token=self.token,trust=self.trust)
            except DBAPIError as error:
                return getattr(error.orig,"sqlstate",None)
            return "unexpected"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.engine.begin() as conn:
                repository.current(conn,self.ctx.pin.case_id,self.ctx.pin.profile.id,locked=True)
                holder=conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
                future=executor.submit(attempt)
                pid=contender.get(timeout=1)
                self.assertTrue(wait_for_owned_lock(conn,pid,holder,profile_id=self.ctx.pin.profile.id),"Exact advisory lock wait was not observed")
                # DB clock predicate, not guessed sleep duration, determines barrier.
                conn.execute(text("SELECT pg_sleep(GREATEST(0,EXTRACT(EPOCH FROM CAST(:expiry AS timestamptz)-clock_timestamp()))+0.05)"),{"expiry":expiry})
            # Either explicit lock or statement timeout may win at the SAME
            # remaining bound; arbitrary Problem/authority denial is not success.
            self.assertIn(future.result(timeout=5),("55P03","57014"))

    def test_04_zero_round_candidate_denied(self):
        self.admitted();cmd,desc=self.command_for("candidate",{"candidate_digest":"d"*64})
        self.expect_problem("diagnostic_conflict",lambda conn:d.commit_candidate(conn,cmd,"d"*64,desc,bearer_token=self.token,trust=self.trust))

    def test_05_same_operation_concurrent_admission_has_one_capability(self):
        cmd,desc=self.command_for("admit",{})
        barrier=threading.Barrier(2)
        def attempt():
            barrier.wait(timeout=2)
            with self.engine.begin() as conn:return d.admit(conn,cmd,desc,bearer_token=self.token,trust=self.trust)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(attempt) for _ in range(2)]
            results=[future.result(timeout=5) for future in futures]
        self.assertEqual(sum(item.capability is not None for item in results),1)
        self.assertEqual({item.disposition for item in results},{"original_prepared","canonical_replay"})

    def test_06_constraints_and_immutable_identity_and_rounds(self):
        self.admitted();params={"o":self.ctx.operation_id}
        self.expect_sqlstate("23514","UPDATE provider_diagnostics SET expires_at=expires_at+interval '1 second' WHERE operation_id=:o",params)
        self.expect_sqlstate("23514","DELETE FROM provider_diagnostics WHERE operation_id=:o",params)
        self.expect_sqlstate("23514","UPDATE provider_diagnostics SET candidate_digest=repeat('a',64),candidate_at=clock_timestamp() WHERE operation_id=:o",params)
        sql="""INSERT INTO provider_diagnostic_rounds(operation_id,round_seq,payload_sha256,input_estimate,output_max,reservation_digest)
            VALUES(:o,:seq,repeat('b',64),1,1,repeat('c',64))"""
        self.expect_sqlstate("23514",sql,{**params,"seq":3})
        with self.engine.begin() as conn:conn.execute(text(sql),{**params,"seq":1})
        self.expect_sqlstate("23505",sql,{**params,"seq":1})
        self.expect_sqlstate("23503",sql,{"o":uuid4(),"seq":1})
        self.expect_sqlstate("23514","UPDATE provider_diagnostic_rounds SET input_estimate=2 WHERE operation_id=:o",params)

    def authority_race(self, mutation, expected, *, profile=False):
        cmd,desc=self.command_for("admit",{});pid_queue=queue.Queue(maxsize=1)
        def attempt():
            try:
                with self.engine.begin() as conn:
                    pid_queue.put(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
                    d.admit(conn,cmd,desc,bearer_token=self.token,trust=self.trust)
            except Problem as error:return error.status,error.code
            return 0,"unexpected"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.engine.begin() as conn:
                mutation(conn)
                holder=conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
                future=executor.submit(attempt);pid=pid_queue.get(timeout=1)
                self.assertTrue(wait_for_owned_lock(conn,pid,holder,profile_id=self.ctx.pin.profile.id if profile else None))
            self.assertEqual(future.result(timeout=5),expected)

    def test_07_token_rotation_serializes_with_reauthentication(self):
        self.authority_race(lambda c:c.execute(text("UPDATE principals SET token_hash=:h WHERE id=:p"),
            {"h":hashlib.sha256((self.token+"-rotated").encode()).hexdigest(),"p":self.ctx.principal_id}),(401,"local_auth_required"))

    def test_08_profile_disable_revision_serializes(self):
        def disable(conn):
            row=repository.current(conn,self.ctx.pin.case_id,self.ctx.pin.profile.id,locked=True)
            values=repository.dto(row).model_dump(mode="json");values["enabled"]=False
            repository.append(conn,self.ctx.principal_id,self.ctx.pin.case_id,values,self.ctx.pin.profile.id,row["revision"]+1)
        self.authority_race(disable,(409,"stale_revision"),profile=True)

    def test_09_concurrent_exact_reserve_and_observation(self):
        self.admitted();r=Reservation(self.ctx.operation_id,1,"b"*64,10,10)
        for kind,value in (("reserve",r),("observe",Observation(r,5,None,"provider_reported","response_received",10,10))):
            cmd,desc=self.command_for(kind,{"reservation" if kind=="reserve" else "observation":value.replay_digest})
            barrier=threading.Barrier(2)
            def attempt():
                barrier.wait(timeout=2)
                with self.engine.begin() as conn:
                    fn=d.reserve_round if kind=="reserve" else d.observe_usage
                    return fn(conn,cmd,value,desc,bearer_token=self.token,trust=self.trust)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures=[executor.submit(attempt) for _ in range(2)]
                results=[future.result(timeout=5) for future in futures]
            self.assertEqual({result.disposition for result in results},{"original_prepared","canonical_replay"})
        with self.engine.connect() as conn:
            rows=d.rounds(conn,cmd)
            self.assertEqual(len(rows),1);self.assertEqual(d.accounting(rows)["charged_input_tokens"],10)

    def test_10_changed_replays_conflict_without_overwrite(self):
        _,r,o=self.observed()
        for kind,value in (("reserve",replace(r,payload_sha256="f"*64)),("observe",replace(o,input_tokens=6))):
            cmd,desc=self.command_for(kind,{"reservation" if kind=="reserve" else "observation":value.replay_digest})
            fn=d.reserve_round if kind=="reserve" else d.observe_usage
            self.expect_problem("diagnostic_conflict",lambda c:fn(c,cmd,value,desc,bearer_token=self.token,trust=self.trust))

    def test_11_partial_unknown_usage_and_truthful_overshoot(self):
        _,_,_=self.observed()
        r=Reservation(self.ctx.operation_id,2,"d"*64,10,10)
        cmd,desc=self.command_for("reserve",{"reservation":r.replay_digest})
        with self.engine.begin() as c:d.reserve_round(c,cmd,r,desc,bearer_token=self.token,trust=self.trust)
        o=Observation(r,101,None,"provider_reported","invalid_response",101,10)
        cmd,desc=self.command_for("observe",{"observation":o.replay_digest})
        with self.engine.begin() as c:result=d.observe_usage(c,cmd,o,desc,bearer_token=self.token,trust=self.trust)
        self.assertEqual(result.payload["state"],"stopped");self.assertEqual(result.payload["charged_input_tokens"],111)
        self.assertIsNone(result.payload["output_tokens"]);self.assertEqual(result.payload["known_input_tokens_subtotal"],106)

    def test_12_stop_candidate_normal_entry_profile_wait_both_orders(self):
        original=self.ctx
        for stop_first in (True,False):
            self.ctx=replace(original,operation_id=uuid4(),invocation_id=uuid4(),deadline_identity=uuid4())
            self.observed()
            candidate,cd=self.command_for("candidate",{"candidate_digest":"c"*64})
            stop,sd=self.command_for("stop",{"reason":"canceled"})
            trust=replace(self.trust,provenance=lambda cmd:cmd is candidate or cmd is stop)
            first,fd=(stop,sd) if stop_first else (candidate,cd)
            second,ssd=(candidate,cd) if stop_first else (stop,sd)
            contender=queue.Queue(maxsize=1)
            def invoke(conn,cmd,desc):
                if cmd is candidate:return d.commit_candidate(conn,cmd,"c"*64,desc,bearer_token=self.token,trust=trust)
                return d.stop(conn,cmd,"canceled",desc,bearer_token=self.token,trust=trust)
            def attempt():
                try:
                    with self.engine.begin() as conn:
                        contender.put(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
                        # Normal entry preserves current authority/profile before
                        # operation acquisition and applies its trusted cutoff.
                        return invoke(conn,second,ssd).disposition
                except Problem as error:return error.code
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.engine.begin() as conn:
                    self.assertEqual(invoke(conn,first,fd).disposition,"original_prepared")
                    holder=conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
                    future=executor.submit(attempt);pid=contender.get(timeout=1)
                    self.assertTrue(wait_for_owned_lock(conn,pid,holder,profile_id=self.ctx.pin.profile.id),"Exact candidate/stop profile wait absent")
                self.assertEqual(future.result(timeout=5),"diagnostic_conflict" if stop_first else "original_prepared")
            cmd,_=self.command_for("readback",{})
            with self.engine.begin() as c:history=d.readback(c,cmd,bearer_token=self.token,trust=self.trust)
            self.assertFalse(history.payload["execution_permission"])
            self.assertEqual(history.payload["candidate_digest"],None if stop_first else "c"*64)

    def test_13_final_authority_current_grant_after_candidate(self):
        self.observed();cmd,desc=self.command_for("candidate",{"candidate_digest":"c"*64})
        with self.engine.begin() as c:d.commit_candidate(c,cmd,"c"*64,desc,bearer_token=self.token,trust=self.trust)
        with self.engine.begin() as c:c.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),{"p":self.ctx.principal_id,"c":self.ctx.pin.case_id})
        cmd,desc=self.command_for("final_authority",{"candidate_digest":"c"*64})
        self.expect_problem("profile_forbidden",lambda c:d.final_authority(c,cmd,"c"*64,desc,bearer_token=self.token,trust=self.trust))

    def test_14_settlement_after_expiry_revoke_replay_and_misuse(self):
        self.bound=self.current_time()+timedelta(milliseconds=800)
        admission,r=self.reserved();work_expiry=self.bound
        with self.engine.begin() as c:c.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"),{"p":self.ctx.principal_id,"c":self.ctx.pin.case_id})
        self.wait_db_until(work_expiry);self.bound=work_expiry+timedelta(seconds=3)
        o=Observation(r,None,None,"absent","transport_failed",10,10)
        cmd,desc=self.command_for("settle",{"observations":[o.replay_digest],"reason":"interrupted"})
        self.expect_problem("diagnostic_conflict",lambda c:d.settle_only(c,cmd,b"z"*32,(o,),"interrupted",desc,trust=self.trust))
        self.expect_problem("diagnostic_conflict",lambda c:d.settle_only(c,cmd,admission.capability,(o,),"interrupted",replace(desc,purpose="work_decision"),trust=self.trust))
        self.expect_problem("diagnostic_conflict",lambda c:d.settle_only(c,cmd,admission.capability,(o,),"interrupted",replace(desc,invocation_fingerprint="f"*64),trust=self.trust))
        self.expect_problem("diagnostic_conflict",lambda c:d.settle_only(c,cmd,admission.capability,(o,),"interrupted",replace(desc,fixed_db_not_after=work_expiry+timedelta(seconds=5)),trust=self.trust))
        for index in range(2):
            with self.engine.begin() as c:result=d.settle_only(c,cmd,admission.capability,(o,),"interrupted",desc,trust=self.trust)
            self.assertEqual(result.disposition,"original_prepared" if index==0 else "canonical_replay")
        changed,newdesc=self.command_for("settle",{"observations":[],"reason":"interrupted"})
        self.expect_problem("diagnostic_conflict",lambda c:d.settle_only(c,changed,admission.capability,(),"interrupted",newdesc,trust=self.trust))
        self.wait_db_until(self.bound)
        self.command=cmd
        self.expect_problem("diagnostic_expired",lambda c:d.settle_only(c,cmd,admission.capability,(o,),"interrupted",desc,trust=self.trust))

    def test_15_fresh_clock_after_observed_lock_released_before_cutoff(self):
        self.bound=self.current_time()+timedelta(seconds=1)
        cmd,desc=self.command_for("admit",{});pid_queue=queue.Queue(maxsize=1);observed=threading.Event();delayed=set()
        key=int.from_bytes(hashlib.sha256(("profile:"+str(self.ctx.pin.profile.id)).encode()).digest()[:8],"big")
        def delayed_descriptor(conn,command,descriptor):
            if observed.is_set() and not delayed:
                held=conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND granted AND locktype='advisory' AND classid::bigint=:hi AND objid::bigint=:lo AND objsubid=1)"),{"hi":key>>32,"lo":key&0xffffffff}).scalar_one()
                if held:
                    delayed.add(True)
                    conn.execute(text("SELECT pg_sleep(GREATEST(0,EXTRACT(EPOCH FROM CAST(:bound AS timestamptz)-clock_timestamp()))+0.03)"),{"bound":self.bound})
            return descriptor.fixed_db_not_after
        self.trust=replace(self.trust,cutoff=delayed_descriptor)
        def attempt():
            try:
                with self.engine.begin() as conn:
                    pid_queue.put(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
                    d.admit(conn,cmd,desc,bearer_token=self.token,trust=self.trust)
            except Problem as error:return error.code
            return "unexpected"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.engine.begin() as conn:
                repository.current(conn,self.ctx.pin.case_id,self.ctx.pin.profile.id,locked=True)
                holder=conn.execute(text("SELECT pg_backend_pid()")).scalar_one();future=executor.submit(attempt)
                pid=pid_queue.get(timeout=1)
                self.assertTrue(wait_for_owned_lock(conn,pid,holder,profile_id=self.ctx.pin.profile.id));observed.set()
                self.wait_db_until(self.bound-timedelta(milliseconds=300),conn)
            self.assertEqual(future.result(timeout=5),"diagnostic_expired")
        self.assertTrue(delayed)

    def test_16_conflicting_concurrent_admit_reserve_observe(self):
        """Start barrier is coordination only; durable winner/conflict is evidence."""
        def race(kind,values,invoke):
            commands=[]
            for value in values:
                saved=self.ctx
                if kind=="admit":self.ctx=value
                payload={} if kind=="admit" else {"reservation" if kind=="reserve" else "observation":value.replay_digest}
                cmd,desc=self.command_for(kind,payload);commands.append((cmd,desc,value));self.ctx=saved
            trust=replace(self.trust,provenance=lambda cmd:any(cmd is item[0] for item in commands))
            barrier=threading.Barrier(2)
            def attempt(item):
                cmd,desc,value=item;barrier.wait(timeout=2)
                try:
                    with self.engine.begin() as conn:result=invoke(conn,cmd,desc,value,trust)
                    return result.disposition,item
                except Problem as error:return error.code,item
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures=[executor.submit(attempt,item) for item in commands]
                outcomes=[future.result(timeout=5) for future in futures]
            self.assertEqual(sorted(value for value,_ in outcomes),["diagnostic_conflict","original_prepared"])
            return next(item for outcome,item in outcomes if outcome=="original_prepared")
        winner,_,_=race("admit",(self.ctx,replace(self.ctx,invocation_id=uuid4())),
            lambda c,cmd,desc,value,trust:d.admit(c,cmd,desc,bearer_token=self.token,trust=trust))
        self.ctx=winner.invocation
        first=Reservation(self.ctx.operation_id,1,"b"*64,10,10)
        _,_,reserved=race("reserve",(first,replace(first,payload_sha256="c"*64)),
            lambda c,cmd,desc,value,trust:d.reserve_round(c,cmd,value,desc,bearer_token=self.token,trust=trust))
        first=Observation(reserved,5,None,"provider_reported","response_received",10,10)
        cmd,_,observation=race("observe",(first,replace(first,input_tokens=6)),
            lambda c,cmd,desc,value,trust:d.observe_usage(c,cmd,value,desc,bearer_token=self.token,trust=trust))
        with self.engine.connect() as conn:
            rows=d.rounds(conn,cmd)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]["observation_digest"],observation.replay_digest)
            self.assertEqual(d.accounting(rows)["charged_input_tokens"],10)
        self.expect_sqlstate("23514","UPDATE provider_diagnostic_rounds SET input_tokens=7 WHERE operation_id=:o",{"o":self.ctx.operation_id})

    def test_17_rollback_is_not_ack_and_readback_requires_committed_history(self):
        cmd,desc=self.command_for("admit",{})
        with self.engine.connect() as conn:
            transaction=conn.begin()
            try:
                prepared=d.admit(conn,cmd,desc,bearer_token=self.token,trust=self.trust)
                self.assertEqual(prepared.disposition,"original_prepared")
            finally:transaction.rollback()
        cmd,_=self.command_for("readback",{})
        self.expect_problem("diagnostic_conflict",lambda c:d.readback(c,cmd,bearer_token=self.token,trust=self.trust))
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM provider_diagnostics WHERE operation_id=:o"),{"o":self.ctx.operation_id}).scalar_one(),0)

    def test_18_candidate_commit_after_local_stop_and_expiry_is_history_only(self):
        self.bound=self.current_time()+timedelta(milliseconds=800)
        admission,_,_=self.observed();work_expiry=self.bound
        candidate,desc=self.command_for("candidate",{"candidate_digest":"c"*64})
        local_stop=threading.Event()
        with self.engine.connect() as conn:
            transaction=conn.begin()
            try:
                prepared=d.commit_candidate(conn,candidate,"c"*64,desc,bearer_token=self.token,trust=self.trust)
                # Model parent local stop BEFORE commit; retain no delivery ACK.
                local_stop.set()
                self.wait_db_until(work_expiry+timedelta(milliseconds=30),conn)
                self.assertGreaterEqual(conn.execute(text("SELECT clock_timestamp()")).scalar_one(),work_expiry)
                transaction.commit()  # Controlled late durable history, not a timely ACK.
            finally:
                if transaction.is_active:transaction.rollback()
        self.assertTrue(local_stop.is_set());self.assertEqual(prepared.disposition,"original_prepared")
        with self.assertRaises(Problem) as caught:d.publish_committed(prepared,object(),trust=self.trust)
        self.assertEqual((caught.exception.status,caught.exception.code),(403,"diagnostic_provenance_unavailable"))
        # Even exact candidate replay/final-authority cannot renew the old bound.
        self.expect_problem("diagnostic_expired",lambda c:d.commit_candidate(c,candidate,"c"*64,desc,bearer_token=self.token,trust=self.trust))
        cmd,fd=self.command_for("final_authority",{"candidate_digest":"c"*64})
        self.expect_problem("diagnostic_expired",lambda c:d.final_authority(c,cmd,"c"*64,fd,bearer_token=self.token,trust=self.trust))
        # Synthetic capability allows only bounded settlement, retaining candidate.
        self.bound=work_expiry+timedelta(seconds=3)
        cmd,sd=self.command_for("settle",{"observations":[],"reason":"canceled"})
        with self.engine.begin() as conn:d.settle_only(conn,cmd,admission.capability,(),"canceled",sd,trust=self.trust)
        cmd,_=self.command_for("readback",{})
        with self.engine.begin() as conn:history=d.readback(conn,cmd,bearer_token=self.token,trust=self.trust)
        self.assertEqual(history.payload["state"],"stopped");self.assertEqual(history.payload["candidate_digest"],"c"*64)
        self.assertFalse(history.payload["execution_permission"])
