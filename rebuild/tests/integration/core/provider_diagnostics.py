"""DEFERRED real-PG fixture source. No env/config/migration/engine construction.

Backend must explicitly inject the released isolated engine at 0009. Synthetic
metadata/capabilities and clock descriptors are test boundaries, NOT native proof.
No credential store/provider or subprocess is used. Do not run in source-only gate.
"""
from concurrent.futures import ThreadPoolExecutor
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

    def tearDown(self):
        with self.engine.connect() as conn:
            current=snapshot(conn)
            self.assertTrue(all(not (old-current[name]) for name,old in self.baseline.items()))

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
        with self.assertRaises(Problem):
            with self.engine.begin() as conn:d.commit_candidate(conn,cmd,"d"*64,desc,bearer_token=self.token,trust=self.trust)

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
