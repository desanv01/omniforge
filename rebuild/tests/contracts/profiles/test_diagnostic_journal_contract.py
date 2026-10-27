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


class StagedMigrationTests(unittest.TestCase):
    def test_default_is_stable_and_explicit_journal_is_exact(self):
        from infra.core import migrate
        applied=[]
        self.assertEqual(migrate.upgrade(read_current=lambda:None,apply=applied.append),migrate.STABLE)
        self.assertEqual(migrate.upgrade(migrate.JOURNAL,read_current=lambda:migrate.STABLE,apply=applied.append),migrate.JOURNAL)
        self.assertEqual(applied,[migrate.STABLE,migrate.JOURNAL])

    def test_bad_targets_fail_before_any_io(self):
        from infra.core import migrate
        for target in (None,True,"head","base","0008","0009_provider_diagnostics ","+1"):
            with self.subTest(target=target),patch.object(migrate,"current_revision") as read:
                with self.assertRaises(ValueError):migrate.upgrade(target,apply=lambda value:self.fail("migration attempted"))
                read.assert_not_called()

    def test_ahead_or_unknown_never_applies(self):
        from infra.core import migrate
        for current,target in ((migrate.JOURNAL,migrate.STABLE),("unexpected",migrate.JOURNAL)):
            with self.subTest(current=current),self.assertRaises(RuntimeError):
                migrate.upgrade(target,read_current=lambda:current,apply=lambda value:self.fail("migration attempted"))

    def test_same_target_delegates_exact_noop_without_seed(self):
        from infra.core import migrate
        applied=[]
        migrate.upgrade(migrate.JOURNAL,read_current=lambda:migrate.JOURNAL,apply=applied.append)
        self.assertEqual(applied,[migrate.JOURNAL])

    def test_cli_default_and_explicit_target(self):
        from infra.core import migrate
        with patch.object(migrate,"upgrade") as upgrade,patch("builtins.print"):
            migrate.main([]);upgrade.assert_called_once_with(migrate.STABLE)
            upgrade.reset_mock();migrate.main(["--target",migrate.JOURNAL]);upgrade.assert_called_once_with(migrate.JOURNAL)


class JournalContextTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from tests.integration.core import provider_diagnostics_runner as runner
        self.runner=runner
        # Virtual nonexistent paths; no config, credentials or database are read.
        temporary=(Path.cwd().anchor and Path(Path.cwd().anchor)/"synthetic-journal-runner-temp").resolve()
        workspace=(temporary.parent/"synthetic-journal-workspace").resolve()
        root=temporary/"omniforge-journal-ci-inert"
        self.env=dict(GITHUB_ACTIONS="true",GITHUB_JOB=runner.JOB,GITHUB_RUN_ID="42",GITHUB_RUN_ATTEMPT="1",
            RUNNER_TEMP=str(temporary),GITHUB_WORKSPACE=str(workspace),OMNIFORGE_JOURNAL_CI_ROOT=str(root),
            OMNIFORGE_CONFIG=str(root/"config.json"),OMNIFORGE_JOURNAL_CI_MANIFEST=str(root/"manifest.json"))
        self.manifest=dict(schema_version=1,purpose=runner.PURPOSE,run_id="42",run_attempt="1",job=runner.JOB,
            root=str(root),config=str(root/"config.json"),workspace=str(workspace))
        self.data=dict(database_url="synthetic-url-never-connected",artifact_root=str(root/"artifacts"))
        self.url=dict(drivername="postgresql+psycopg",host="127.0.0.1",port=5432,database=runner.DATABASE,
            username=runner.DATABASE,password="ephemeral-journal-ci-only",query={})
        self.reads=[]

    def validate(self):
        def read(path):
            self.reads.append(path.name)
            return self.manifest if path.name=="manifest.json" else self.data
        return self.runner.validate_context(self.env,reader=read,parse_url=lambda value:SimpleNamespace(**self.url))

    def test_complete_closed_tuple_accepts_without_external_io(self):
        ctx=self.validate()
        self.assertEqual(ctx.config.name,"config.json");self.assertEqual(self.reads,["manifest.json","config.json"])
        self.assertNotIn(self.data["database_url"],repr(ctx))

    def test_missing_or_wrong_job_and_identity_fail_before_config(self):
        for key,value in (("GITHUB_ACTIONS","false"),("GITHUB_JOB","postgres-core"),("GITHUB_RUN_ID","0"),
                          ("GITHUB_RUN_ATTEMPT","01"),("OMNIFORGE_CONFIG","relative.json")):
            original=self.env[key];self.env[key]=value;self.reads.clear()
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.validate()
            self.assertEqual(self.reads,[]);self.env[key]=original

    def test_prefix_or_marker_cannot_select_checkout_or_other_config(self):
        from pathlib import Path
        for key,value in (("GITHUB_WORKSPACE",self.env["RUNNER_TEMP"]),
            ("OMNIFORGE_CONFIG",str(Path(self.env["OMNIFORGE_CONFIG"]).parent/"retained.json")),
            ("OMNIFORGE_JOURNAL_CI_ROOT",str(Path(self.env["RUNNER_TEMP"])/"nested"/"omniforge-journal-ci-x"))):
            original=self.env[key];self.env[key]=value;self.reads.clear()
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.validate()
            self.assertEqual(self.reads,[]);self.env[key]=original

    def test_manifest_requires_exact_provenance_and_closed_fields(self):
        for key,value in (("schema_version",True),("run_id","43"),("purpose","marker"),("job","postgres-core"),("extra",True)):
            original=dict(self.manifest);self.manifest[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.validate()
            self.manifest=original

    def test_config_refuses_extra_fields_and_wrong_artifact_root(self):
        for replacement in ({**self.data,"auth_token":"forbidden"},{**self.data,"artifact_root":self.env["GITHUB_WORKSPACE"]}):
            original=self.data;self.data=replacement
            with self.assertRaises(RuntimeError):self.validate()
            self.data=original

    def test_database_endpoint_user_password_and_options_are_closed(self):
        for key,value in (("database","omniforge_rebuild"),("username","postgres"),("host","localhost"),
            ("port",63140),("password","other"),("drivername","postgresql"),("query",{"options":"other"})):
            original=self.url[key];self.url[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.validate()
            self.url[key]=original

    def test_symlink_path_refused_before_config(self):
        from pathlib import Path
        with patch.object(Path,"is_symlink",return_value=True),self.assertRaises(RuntimeError):self.validate()
        self.assertEqual(self.reads,[])

    def test_main_refusal_never_calls_runtime(self):
        with patch.dict("os.environ",{},clear=True),patch.object(self.runner,"run") as run:
            with self.assertRaises(RuntimeError):self.runner.main()
            run.assert_not_called()

    def test_preservation_detects_loss_and_structure_change(self):
        old={"table":dict(columns=["id"],structure="fixed",hashes={"one":2},count=2)}
        for new,expected in ((dict(columns=["id"],structure="fixed",hashes={"one":2,"new":1}),True),
            (dict(columns=["id"],structure="fixed",hashes={"one":1}),False),
            (dict(columns=["id"],structure="changed",hashes={"one":2}),False)):
            self.assertEqual(self.runner.preserved(old,{"table":new}),expected)


class MigrationEngineSettlementTests(unittest.TestCase):
    def test_disposes_on_success_connect_failure_and_migration_failure(self):
        from pathlib import Path
        import runpy
        from unittest.mock import MagicMock
        from alembic import context
        from services.api import db,settings
        source=Path(__file__).resolve().parents[3]/"migrations"/"env.py"
        for stage in ("success","connect","migrate","migrate_and_dispose"):
            engine=MagicMock();failure=RuntimeError("injected inert failure")
            if stage=="connect":engine.connect.side_effect=failure
            if stage=="migrate_and_dispose":engine.dispose.side_effect=RuntimeError("secondary disposal failure")
            with self.subTest(stage=stage),patch.object(settings.Settings,"from_env",return_value=object()),\
                patch.object(db,"engine_for",return_value=engine),patch.object(context,"configure"),\
                patch.object(context,"begin_transaction",return_value=MagicMock()),\
                patch.object(context,"run_migrations",side_effect=failure if stage.startswith("migrate") else None):
                if stage=="success":runpy.run_path(str(source))
                else:
                    with self.assertRaises(RuntimeError) as caught:runpy.run_path(str(source))
                    self.assertIs(caught.exception,failure)
                engine.dispose.assert_called_once_with()


class RunnerSettlementTests(unittest.TestCase):
    def test_first_unexpected_failure_aborts_later_mutation_but_settles_and_reports(self):
        from unittest.mock import MagicMock
        from tests.integration.core import provider_diagnostics_runner as runner,provider_diagnostics as fixture
        events=[]
        class InertMatrix(unittest.TestCase):
            engine=None
            def setUp(self):self.addCleanup(lambda:events.append("test_cleanup"))
            def test_01_unexpected_barrier_failure(self):
                events.append("first");self.fail("injected missing barrier")
            def test_02_must_not_mutate(self):events.append("SECOND_MUTATION")
        engine=MagicMock();engine.pool.checkedout.return_value=0
        engine.connect.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value=0
        engine.begin.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value=0
        chunks=[];handle=MagicMock();handle.write.side_effect=chunks.append;handle.fileno.return_value=17
        root=MagicMock();receipt=root.__truediv__.return_value;receipt.exists.return_value=False
        receipt.open.return_value.__enter__.return_value=handle
        projections={"original":dict(columns=["id"],structure="fixed",hashes={"synthetic":1},count=1)}
        with patch("sqlalchemy.create_engine",return_value=engine),patch.object(runner,"identities",return_value="inert-cluster"),\
            patch.object(runner,"schema_at",side_effect=[None,runner.JOURNAL]),patch.object(runner.os,"fsync"),\
            patch.object(runner,"projections",side_effect=lambda conn:(events.append("projection_check") or projections)),\
            patch("infra.core.migrate.upgrade"),patch.object(fixture,"ORIGINAL",("original",)),\
            patch.object(fixture,"seed_original_baseline"),patch.object(fixture,"JournalPostgresProof",InertMatrix):
            self.assertEqual(runner.run(runner.Context(root,root,"inert-never-connected")),1)
        self.assertNotIn("SECOND_MUTATION",events);self.assertEqual(events.count("first"),1)
        self.assertIn("test_cleanup",events);self.assertEqual(events[-1],"projection_check")
        engine.dispose.assert_called_once_with();self.assertIsNone(InertMatrix.engine)
        data=json.loads("".join(chunks))
        self.assertEqual(data["tests"],1);self.assertTrue(data["aborted"])
        self.assertEqual(len(data["planned_test_ids"]),2);self.assertEqual(len(data["started_test_ids"]),1)
        self.assertEqual(data["passed_test_ids"],[]);self.assertEqual(len(data["unexecuted_test_ids"]),1)
        self.assertTrue(data["unexecuted_test_ids"][0].endswith("test_02_must_not_mutate"))
        self.assertEqual(data["skipped"],0);self.assertTrue(data["original18_preserved"])
        self.assertEqual(data["checked_out"],0);self.assertTrue(data["pool_disposed"])
        self.assertEqual(data["status"],"failed");self.assertNotIn("injected missing barrier","".join(chunks))

    def test_migration_setup_failure_disposes_pool_and_keeps_sanitized_receipt(self):
        from unittest.mock import MagicMock
        from tests.integration.core import provider_diagnostics_runner as runner
        engine=MagicMock();engine.pool.checkedout.return_value=0
        engine.connect.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value=0
        chunks=[];handle=MagicMock();handle.write.side_effect=chunks.append;handle.fileno.return_value=17
        root=MagicMock();receipt=root.__truediv__.return_value;receipt.exists.return_value=False
        receipt.open.return_value.__enter__.return_value=handle
        context=runner.Context(root,root,"inert-never-connected")
        with patch("sqlalchemy.create_engine",return_value=engine),patch.object(runner,"identities",return_value="inert-cluster"),\
            patch.object(runner,"schema_at",return_value=None),patch.object(runner.os,"fsync") as sync,\
            patch("infra.core.migrate.upgrade",side_effect=RuntimeError("private failure detail")):
            self.assertEqual(runner.run(context),1)
        engine.dispose.assert_called_once_with();sync.assert_called_once_with(17)
        serialized="".join(chunks)
        self.assertNotIn("private failure detail",serialized);self.assertNotIn(context.database_url,serialized)
        data=json.loads(serialized)
        self.assertEqual(data["status"],"failed");self.assertEqual(data["checked_out"],0)
        self.assertTrue(data["pool_disposed"]);self.assertFalse(data["migration_applied"])


if __name__=="__main__":unittest.main()
