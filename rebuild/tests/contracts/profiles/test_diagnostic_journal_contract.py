"""Inert journal contract/order checks. No DB, capability randomness or live I/O."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from adapters.models.contracts import Budget, Profile
from adapters.secrets.enrollment import EnrollmentBinding
from adapters.secrets.store import CredentialRef
from services.api.db import digest
from services.api.errors import Problem
from services.api.profiles import authority as a, diagnostics as d
from services.api.providers.diagnostic_protocol import Reservation, Observation


def invocation():
    principal, case, profile = uuid4(), uuid4(), uuid4()
    binding = EnrollmentBinding(uuid4(), principal, case, profile, 1, CredentialRef("wincred:omniforge:v1:" + str(uuid4())))
    budget = Budget(calls=2, input_tokens=100, output_tokens=100, wall_seconds=30, tool_bytes=32)
    pin = a.BoundProfile(Profile(profile, 2, "https://api.deepseek.com/chat/completions", "inert", binding.credential_ref),
                         budget, budget, case, binding, "a" * 64)
    return d.Invocation(uuid4(), uuid4(), 1, "b" * 64, uuid4(), 1, principal, pin)


class Result:
    def __init__(self, value): self.value = value
    def scalar_one(self): return self.value
    def mappings(self): return self
    def one_or_none(self): return self.value
    def __iter__(self): return iter(self.value)


class Conn:
    """Finite statement recorder/state stub; no SQL implementation or lock claim."""
    def __init__(self):
        self.row, self.rows, self.events = None, [], []
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def execute(self, statement, values=None):
        sql = str(statement); values = values or {}
        self.events.append((sql, values))
        if sql == "SELECT clock_timestamp()": return Result(self.now)
        if sql.startswith("SELECT * FROM provider_diagnostics "): return Result(self.row)
        if sql.startswith("SELECT * FROM provider_diagnostic_rounds "): return Result(sorted(self.rows, key=lambda r:r["round_seq"]))
        if "INSERT INTO provider_diagnostics(" in sql:
            self.row = dict(fingerprint=values["hash"], expires_at=values["expiry"], budget=json.loads(values["budget"]),
                            capability_hash=values["cap"], state="open", candidate_digest=None, settlement_digest=None,
                            settlement_cutoff=None, stop_reason=None)
        elif "INSERT INTO provider_diagnostic_rounds(" in sql:
            self.rows.append(dict(round_seq=values["seq"], reservation_digest=values["digest"], input_estimate=values["input"],
                output_max=values["output"], observation_digest=None, input_tokens=None, output_tokens=None))
        elif sql.startswith("UPDATE provider_diagnostic_rounds"):
            row = next(r for r in self.rows if r["round_seq"]==values["seq"])
            row.update(observation_digest=values["digest"],input_tokens=values["input"],output_tokens=values["output"],
                       charged_input_tokens=values["ci"],charged_output_tokens=values["co"])
        elif sql.startswith("UPDATE provider_diagnostics SET candidate_digest"):
            self.row["candidate_digest"] = values["digest"]
        elif sql.startswith("UPDATE provider_diagnostics SET state="):
            self.row.update(state="stopped",stop_reason=self.row["stop_reason"] or values.get("reason", "budget"))
            if "cutoff" in values:self.row.update(settlement_digest=values["digest"],settlement_cutoff=values["cutoff"])
        return Result(None)


class Contracts(unittest.TestCase):
    def setUp(self):
        self.ctx, self.conn = invocation(), Conn()
        self.bound = self.conn.now + timedelta(seconds=25)
        self.trust = d.Trust(provenance=lambda cmd: cmd is self.command,
            cutoff=lambda conn, cmd, desc: desc.fixed_db_not_after,
            issue_capability=lambda cmd: b"x" * 32)
        self.auth = patch.object(d, "normal_authority", side_effect=lambda conn, cmd, token, **kwargs: conn.events.append(("authority", {})))
        self.auth.start(); self.addCleanup(self.auth.stop)
    def cmd(self, kind, payload):
        proto=d.Command(self.ctx,uuid4(),0,kind,"0"*64)
        self.command=replace(proto,request_digest=d.request_digest(proto,payload))
        purpose="work_admission" if kind=="admit" else "settlement_decision" if kind=="settle" else "work_decision"
        desc=d.CutoffDescriptor(uuid4(),self.ctx.fingerprint,self.command.command_id,purpose,self.bound,0,uuid4(),"valid_conservative")
        return self.command,desc
    def admit(self):
        cmd,desc=self.cmd("admit",{})
        return d.admit(self.conn,cmd,desc,trust=self.trust)
    def reserve(self, seq=1, amount=10):
        r=Reservation(self.ctx.operation_id,seq,"c"*64,amount,10)
        cmd,desc=self.cmd("reserve",{"reservation":r.replay_digest})
        return r,d.reserve_round(self.conn,cmd,r,desc,trust=self.trust)
    def observe(self,r,input_tokens=5):
        o=Observation(r,input_tokens,None,"provider_reported" if input_tokens is not None else "absent","response_received",max(r.input_estimate,input_tokens or 0),r.output_max)
        cmd,desc=self.cmd("observe",{"observation":o.replay_digest})
        return o,d.observe_usage(self.conn,cmd,o,desc,trust=self.trust)
    def mutations(self):return [sql for sql,_ in self.conn.events if sql.startswith(("INSERT","UPDATE"))]
    def test_defaults_and_forged_context_fail_before_mutation(self):
        cmd,desc=self.cmd("admit",{})
        for trust in (d.Trust(),replace(self.trust,cutoff=None),replace(self.trust,issue_capability=None),replace(self.trust,provenance=lambda cmd:False)):
            with self.assertRaises(Problem):d.admit(self.conn,cmd,desc,trust=trust)
        self.assertEqual(self.mutations(),[])
        with self.assertRaises(Problem):d.publish_committed(d.Decision(cmd,"original_prepared",{}),True)
    def test_strict_invocation_cutoff_and_protocol(self):
        with self.assertRaises(Problem):replace(self.ctx,invocation_generation=True)
        with self.assertRaises(Problem):replace(self.ctx,deadline_revision=uuid4())
        with self.assertRaises(Problem):d.instant(datetime(2026,1,1))
        with self.assertRaises(ValueError):Reservation(self.ctx.operation_id,True,"c"*64,1,1)
        cmd,desc=self.cmd("admit",{})
        with self.assertRaises(Problem):d.admit(self.conn,cmd,replace(desc,disposition="unknown"),trust=self.trust)
    def test_capability_issuance_cannot_reset_elapsed_deadline(self):
        cmd,desc=self.cmd("admit",{})
        def delayed_issuer(command):
            self.conn.now=self.bound
            return b"x"*32
        with self.assertRaises(Problem):d.admit(self.conn,cmd,desc,trust=replace(self.trust,issue_capability=delayed_issuer))
        self.assertEqual(self.mutations(),[])
    def test_postcommit_publisher_is_separate_trusted_one_use_boundary(self):
        decision=self.admit();committed=object();seen=set()
        def publisher(candidate, evidence):
            d.check(candidate is decision and evidence is committed and id(candidate) not in seen)
            seen.add(id(candidate))
            return {"disposition":"original_committed","command_id":str(candidate.command.command_id)}
        trusted=replace(self.trust,publish_after_commit=publisher)
        with self.assertRaises(Problem):d.publish_committed(decision,True,trusted)
        self.assertEqual(d.publish_committed(decision,committed,trusted)["disposition"],"original_committed")
        with self.assertRaises(Problem):d.publish_committed(decision,committed,trusted)
    def test_foreign_invocation_and_changed_command_digest_deny(self):
        self.admit();self.ctx=replace(self.ctx,invocation_id=uuid4())
        with self.assertRaises(Problem):self.reserve()
        cmd,desc=self.cmd("reserve",{"reservation":"d"*64})
        r=Reservation(self.ctx.operation_id,1,"c"*64,10,10)
        with self.assertRaises(Problem):d.reserve_round(self.conn,cmd,r,desc,trust=self.trust)
        self.assertEqual(len(self.mutations()),1)
    def test_same_connection_authority_then_operation_then_clock(self):
        decision=self.admit()
        sql=[x[0] for x in self.conn.events]
        self.assertLess(sql.index("authority"),next(i for i,x in enumerate(sql) if "pg_advisory_xact_lock" in x))
        self.assertLess(sql.index("SELECT clock_timestamp()"),sql.index("authority"))
        self.assertLess(next(i for i,x in enumerate(sql) if "FOR UPDATE" in x),max(i for i,x in enumerate(sql) if x=="SELECT clock_timestamp()"))
        self.assertEqual(decision.disposition,"original_prepared")
        self.assertEqual(decision.capability,b"x"*32)
        again=self.admit();self.assertEqual(again.disposition,"canonical_replay");self.assertIsNone(again.capability)
        self.assertNotIn("capability_hash",str(decision.payload))
    def test_expired_lock_clock_and_no_replay_extension(self):
        self.admit();self.conn.now=self.bound
        with self.assertRaises(Problem):self.reserve()
        self.assertEqual(len(self.mutations()),1)
        self.conn.now=self.bound-timedelta(seconds=1);self.bound+=timedelta(seconds=1)
        with self.assertRaises(Problem):self.reserve()
    def test_exact_reserve_usage_replay_and_unknown(self):
        self.admit();r,first=self.reserve();self.reserve()
        self.assertEqual(len(self.conn.rows),1)
        o,_=self.observe(r);_,replay=self.observe(r)
        self.assertEqual(replay.disposition,"canonical_replay")
        used=d.accounting(self.conn.rows)
        self.assertEqual(used["input_tokens"],5);self.assertIsNone(used["output_tokens"])
        self.assertEqual(used["charged_input_tokens"],10)
        changed=replace(o,input_tokens=6)
        cmd,desc=self.cmd("observe",{"observation":changed.replay_digest})
        with self.assertRaises(Problem):d.observe_usage(self.conn,cmd,changed,desc,trust=self.trust)
        bad=replace(r,payload_sha256="d"*64);cmd,desc=self.cmd("reserve",{"reservation":bad.replay_digest})
        with self.assertRaises(Problem):d.reserve_round(self.conn,cmd,bad,desc,trust=self.trust)
    def test_overshoot_retains_charge_and_stops(self):
        self.admit();r,_=self.reserve();self.observe(r,101)
        self.assertEqual(self.conn.row["state"],"stopped")
        self.assertEqual(d.accounting(self.conn.rows)["charged_input_tokens"],101)
        with self.assertRaises(Problem):self.reserve(2)
    def test_nonempty_candidate_final_and_stop_precedence(self):
        self.admit();cmd,desc=self.cmd("candidate",{"candidate_digest":"f"*64})
        with self.assertRaises(Problem):d.commit_candidate(self.conn,cmd,"f"*64,desc,trust=self.trust)
        r,_=self.reserve();self.observe(r)
        cmd,desc=self.cmd("candidate",{"candidate_digest":"f"*64})
        d.commit_candidate(self.conn,cmd,"f"*64,desc,trust=self.trust)
        cmd,desc=self.cmd("final_authority",{"candidate_digest":"f"*64})
        result=d.final_authority(self.conn,cmd,"f"*64,desc,trust=self.trust)
        self.assertEqual(result.payload["authority"],"decision_only_not_delivery")
        cmd,desc=self.cmd("stop",{"reason":"canceled"});d.stop(self.conn,cmd,"canceled",desc,trust=self.trust)
        self.assertEqual(self.conn.row["candidate_digest"],"f"*64)
        cmd,desc=self.cmd("final_authority",{"candidate_digest":"f"*64})
        with self.assertRaises(Problem):d.final_authority(self.conn,cmd,"f"*64,desc,trust=self.trust)
    def test_settlement_after_revoke_no_reverse_auth_one_use(self):
        self.admit();r,_=self.reserve();self.conn.events.clear()
        self.conn.now=self.bound+timedelta(seconds=1);self.bound+=timedelta(seconds=3)
        obs=Observation(r,None,None,"absent","transport_failed",r.input_estimate,r.output_max)
        payload={"observations":[obs.replay_digest],"reason":"interrupted"}
        cmd,desc=self.cmd("settle",payload)
        d.settle_only(self.conn,cmd,b"x"*32,(obs,),"interrupted",desc,trust=self.trust)
        self.assertFalse(any(x[0]=="authority" for x in self.conn.events))
        mutations=len(self.mutations())
        replay=d.settle_only(self.conn,cmd,b"x"*32,(obs,),"interrupted",desc,trust=self.trust)
        self.assertEqual(replay.disposition,"canonical_replay");self.assertEqual(len(self.mutations()),mutations)
        with self.assertRaises(Problem):d.settle_only(self.conn,cmd,b"y"*32,(obs,),"interrupted",desc,trust=self.trust)
        badcmd,baddesc=self.cmd("settle",payload)
        with self.assertRaises(Problem):d.settle_only(self.conn,badcmd,b"x"*32,(obs,),"interrupted",baddesc,trust=self.trust)
    def test_expired_admission_does_not_attempt_authority_or_operation(self):
        self.bound=self.conn.now
        with self.assertRaises(Problem) as caught:self.admit()
        self.assertEqual(caught.exception.code,"diagnostic_expired")
        self.assertFalse(any(sql=="authority" or "pg_advisory_xact_lock" in sql for sql,_ in self.conn.events))
    def test_short_remaining_bounds_before_each_authority_statement(self):
        self.bound=self.conn.now+timedelta(milliseconds=10)
        cmd,desc=self.cmd("admit",{})
        original=self.conn.execute
        def elapsed(statement,values=None):
            result=original(statement,values)
            if str(statement)=="TOKEN LOCK":self.conn.now+=timedelta(milliseconds=6)
            if str(statement)=="GRANT LOCK":self.conn.now+=timedelta(milliseconds=5)
            return result
        self.conn.execute=elapsed
        guard=lambda:d.cutoff(self.conn,cmd,desc,self.trust)
        with patch.object(a.bindings,"authenticate",side_effect=lambda c,*args:c.execute(d.text("TOKEN LOCK"))),patch.object(a.repository,"grant",side_effect=lambda c,*args,**kw:c.execute(d.text("GRANT LOCK"))),patch.object(a.repository,"current",side_effect=lambda c,*args,**kw:c.execute(d.text("PROFILE LOCK"))) as current:
            with self.assertRaises(Problem) as caught:
                a.load_profile_conn(self.conn,self.ctx.principal_id,self.ctx.pin.case_id,self.ctx.pin.profile.id,2,a.Purpose.EXECUTE_DIAGNOSTIC,bearer_token="inert",before_statement=guard)
            self.assertEqual(caught.exception.code,"diagnostic_expired");current.assert_called_once()
            self.assertFalse(any(sql=="PROFILE LOCK" for sql,_ in self.conn.events))
        limits=[int(params['v'][:-2]) for sql,params in self.conn.events if "set_config" in sql]
        self.assertTrue(limits and all(0<value<=10 for value in limits))
    def test_elapsed_operation_stage_blocks_later_row_lock_normal_and_settlement(self):
        for settlement in (False,True):
            with self.subTest(settlement=settlement):
                self.conn=Conn();self.bound=self.conn.now+timedelta(seconds=25)
                if settlement:self.admit()
                self.conn.events.clear();self.bound=self.conn.now+timedelta(milliseconds=10)
                original=self.conn.execute
                def elapsed(statement,values=None):
                    result=original(statement,values)
                    if "pg_advisory_xact_lock" in str(statement):self.conn.now+=timedelta(milliseconds=11)
                    return result
                self.conn.execute=elapsed
                with self.assertRaises(Problem) as caught:
                    if settlement:
                        cmd,desc=self.cmd("settle",{"observations":[],"reason":"interrupted"})
                        d.settle_only(self.conn,cmd,b"x"*32,(),"interrupted",desc,trust=self.trust)
                    else:self.admit()
                self.assertEqual(caught.exception.code,"diagnostic_expired")
                self.assertFalse(any(sql.startswith("SELECT * FROM provider_diagnostics ") for sql,_ in self.conn.events))
                if settlement:self.assertFalse(any(sql=="authority" for sql,_ in self.conn.events))
                limits=[int(params['v'][:-2]) for sql,params in self.conn.events if "set_config" in sql]
                self.assertTrue(limits and all(0<value<=10 for value in limits))


class AuthorityExtraction(unittest.TestCase):
    def test_wrapper_and_conn_preserve_configure_enroll_and_denial(self):
        conn=object();events=[]
        class Tx:
            def __enter__(self):events.append("begin");return conn
            def __exit__(self,*args):events.append("end")
        engine=SimpleNamespace(begin=lambda:Tx())
        ctx=invocation();row={"revision":2,"enabled":False}
        with patch.object(a.repository,"grant",side_effect=lambda c,*x,**k:self.assertIs(c,conn)),patch.object(a.repository,"current",return_value=row),patch.object(a.repository,"dto",return_value="view"),patch.object(a.bindings,"authenticate") as auth:
            self.assertEqual(a.load_profile(engine,ctx.principal_id,ctx.pin.case_id,ctx.pin.profile.id,2,a.Purpose.CONFIGURE),"view")
            self.assertEqual(events,["begin","end"]);auth.assert_not_called()
            events.clear()
            with self.assertRaises(Problem):a.load_profile(engine,ctx.principal_id,ctx.pin.case_id,ctx.pin.profile.id,2,"bad")
            self.assertEqual(events,[])
            with self.assertRaises(Problem):a.load_profile_conn(conn,ctx.principal_id,ctx.pin.case_id,ctx.pin.profile.id,2,a.Purpose.ENROLL,bearer_token="inert")
            auth.assert_called_once_with(conn,"inert",ctx.principal_id)
    def test_execute_order_and_pinned_comparison(self):
        ctx=invocation();conn=object();events=[]
        pin=ctx.pin
        row={"revision":pin.profile.revision,"enabled":True,"profile_id":pin.profile.id,"endpoint":pin.profile.endpoint,"model":pin.profile.model}
        snapshot=SimpleNamespace(caps=pin.caps,model_dump=lambda **k:{"inert":"metadata"})
        with patch.object(a.bindings,"authenticate",side_effect=lambda c,*x:events.append(("token",c))),patch.object(a.repository,"grant",side_effect=lambda c,*x,**k:events.append(("grant",c))),patch.object(a.repository,"current",side_effect=lambda c,*x,**k:(events.append(("profile",c)) or row)),patch.object(a.repository,"dto",return_value=snapshot),patch.object(a.bindings,"attached_binding",return_value=pin.binding):
            result=a.load_profile_conn(conn,ctx.principal_id,pin.case_id,pin.profile.id,2,a.Purpose.EXECUTE_DIAGNOSTIC,bearer_token="inert",requested_budget=pin.budget)
        self.assertEqual([x[0] for x in events],["token","grant","profile"])
        self.assertTrue(all(c is conn for _,c in events));self.assertEqual(result.binding,pin.binding)
    def test_journal_authority_reloads_pin_on_the_supplied_connection(self):
        ctx=invocation();conn=object()
        cmd=d.Command(ctx,uuid4(),0,"reserve","0"*64)
        with patch.object(d,"load_profile_conn",return_value=ctx.pin) as loader:
            d.normal_authority(conn,cmd,"inert")
            self.assertIs(loader.call_args.args[0],conn)
        with patch.object(d,"load_profile_conn",return_value=replace(ctx.pin,metadata_digest="f"*64)):
            with self.assertRaises(Problem):d.normal_authority(conn,cmd,"inert")


if __name__=="__main__":unittest.main()
