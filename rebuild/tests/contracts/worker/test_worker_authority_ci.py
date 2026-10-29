"""Injected files/engines/operations only. No real SQL, credentials or network."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch
from uuid import UUID

from tests.integration.core import worker_authority_ci as h
from tests.integration.core.worker_authority import PURPOSES


def encoded(value):return (json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()


def identity():return dict(database=h.DATABASE,owner=h.OWNER,session=h.OWNER,schema="public",cluster="123456",server_version="170006")


def baseline():return {name:dict(columns=["id"],count=1,projection_multiset={"a"*32:1}) for name in h.TABLES}


def success(before):
    runs=[dict(run_id=str(UUID(int=index+1)),purpose=purpose) for index,purpose in enumerate(PURPOSES)]
    data=dict(status="passed",control_interrupted=False,failure_stages=[],baseline_preserved=True,schema_preserved=True,
        empty_baseline_tables=[],provisioning_commit="confirmed",role_disable_commit="confirmed",
        role_disposition="retained_NOLOGIN_with_grants_and_history",sql_denials=21,active_sql_probe_id=None,runs=runs,
        receiver_checks=[dict(**item,status="passed") for item in runs],
        baseline20={name:{key:row[key] for key in ("count","projection_multiset")} for name,row in before.items()},
        sql_denial_checks=[dict(probe_id=name,status="passed",sqlstate="42501") for name in
            ["legacy_"+str(i) for i in range(13)]+["journal_"+str(i) for i in range(8)]])
    for name in ("owner","receiver"):
        data[name+"_checked_out"]=0;data[name+"_pool_disposition"]="disposed_not_a_physical_connection_stop_claim"
    return data


class ControlStop(BaseException):pass


class FakeRuntime:
    def __init__(self,fault=None):
        self.fault=fault;self.calls=[];self.owner=MagicMock();self.owner.pool.checkedout.return_value=0
        self.before=baseline();self.after=deepcopy(self.before);self.observation=identity()
        self.inspection=dict(role_exists=True,role_login=False,sessions=[])
    def call(self,name):
        self.calls.append(name)
        if self.fault==name:raise RuntimeError("SENSITIVE_RUNTIME_DETAIL")
    def engine(self):self.call("engine");return self.owner
    def identity(self,engine):self.call("identity");return self.observation
    def fresh(self,engine):self.call("fresh")
    def migrate(self,engine,source):self.call("migrate")
    def seed(self,engine):self.call("seed")
    def capture(self,engine):self.call("capture");return self.after,["shape"]
    def execute(self,engine,cluster,evidence):
        self.call("execute");evidence.update(success(self.before))
        if self.fault=="unknown_commit":evidence.update(status="failed",provisioning_commit="unconfirmed_requires_Main_inspection")
        if self.fault=="control":
            evidence.update(status="interrupted",control_interrupted=True,receiver_checks=evidence["receiver_checks"][:1])
            raise ControlStop("SENSITIVE_CONTROL_DETAIL")
    def inspect(self,engine):self.call("inspect");return self.inspection


class MemoryFiles:
    """Real Journal control flow with fully injected durable-file boundaries."""
    def __init__(self,fault=None,index=1):self.fault=fault;self.index=index;self.files={};self.writes=0;self.syncs=0
    def factory(self,path):
        def opener(selected):
            if self.fault=="open" or selected.name in self.files:raise OSError("SENSITIVE_FILE")
            self.files[selected.name]="";outer=self
            class Handle:
                def write(self,payload):
                    outer.writes+=1
                    if outer.fault=="write" and outer.writes==outer.index:raise OSError("SENSITIVE_FILE")
                    if outer.fault=="short" and outer.writes==outer.index:
                        outer.files[selected.name]+=payload[:5];return 5
                    outer.files[selected.name]+=payload;return len(payload)
                def flush(self):
                    if outer.fault=="flush" and outer.writes==outer.index:raise OSError("SENSITIVE_FILE")
                def fileno(self):return 19
                def close(self):
                    if outer.fault=="close":raise OSError("SENSITIVE_FILE")
            return Handle()
        def sync(descriptor):
            self.syncs+=1
            if self.fault in ("sync","control_sync") and self.syncs==self.index:
                raise ControlStop("SENSITIVE_FILE") if self.fault=="control_sync" else OSError("SENSITIVE_FILE")
        return h.Journal(path,opener=opener,sync=sync)
    def read(self,path,limit):
        raw=self.files[path.name].encode();h.require(len(raw)<=limit);return raw
    def record(self,name):return json.loads(self.files[name])


class ContextContract(unittest.TestCase):
    def setUp(self):
        anchor=Path(Path.cwd().anchor)
        self.workspace=(anchor/"inert-worker-ci-checkout").resolve();self.source=self.workspace/"rebuild"
        temporary=(anchor/"inert-worker-ci-temp").resolve();self.root=temporary/"omniforge-worker-authority9-unit"
        self.env=dict(GITHUB_ACTIONS="true",GITHUB_JOB=h.JOB,GITHUB_EVENT_NAME="pull_request",GITHUB_RUN_ID="2",GITHUB_RUN_ATTEMPT="1",
            GITHUB_SHA="a"*40,RUNNER_TEMP=str(temporary),GITHUB_WORKSPACE=str(self.workspace),OMNIFORGE_WORKER_CI_ROOT=str(self.root),
            OMNIFORGE_WORKER_CI_CONTEXT=str(self.root/"context.json"),OMNIFORGE_WORKER_CI_MANIFEST=str(self.root/"manifest.json"))
        self.sources={"worker.py":"f"*64}
        self.context=dict(schema_version=1,purpose=h.PURPOSE,job=h.JOB,event="pull_request",run_id="2",run_attempt="1",sha="a"*40,
            root=str(self.root),workspace=str(self.workspace),sources=self.sources)
        self.files={"context.json":encoded(self.context)};self.reads=[]
    def read(self,path,limit):self.reads.append(path.name);return self.files[path.name]
    def validate(self):return h.validate_context(self.env,reader=self.read,hasher=lambda base:self.sources,source=self.source)
    def bind(self):
        context=self.validate()
        self.files["preflight.json"]=encoded(dict(schema_version=1,mode="preflight",status="passed",context_sha256=context.context_sha256,
            identity=identity(),failures=[],pool=dict(checked_out=0,disposed=True)))
        self.files["manifest.json"]=encoded(dict(schema_version=1,context_sha256=context.context_sha256,
            preflight_sha256=h.digest(self.files["preflight.json"]),cluster="123456"))
        return context
    def test_exact_context_and_bound_identity(self):
        context=self.bind();bound=h.bind_context(context,reader=self.read)
        self.assertEqual(bound.cluster,"123456");self.assertEqual(bound.source,self.source)
    def test_wrong_job_event_sha_run_paths_or_ambient_config_fail_before_read(self):
        for name,value in (("GITHUB_JOB","postgres-core"),("GITHUB_EVENT_NAME","workflow_dispatch"),("GITHUB_SHA","HEAD"),
            ("GITHUB_RUN_ID","0"),("OMNIFORGE_WORKER_CI_CONTEXT","relative.json"),("PGSERVICE","SENSITIVE"),("OMNIFORGE_CONFIG","")):
            with self.subTest(name=name):
                original=dict(self.env);self.env[name]=value;self.reads.clear()
                with self.assertRaises(RuntimeError):self.validate()
                self.assertEqual(self.reads,[]);self.env=original
    def test_closed_context_and_changed_source_fail(self):
        for key,value in (("schema_version",True),("sha","b"*40),("extra",True),("sources",{"other.py":"e"*64})):
            with self.subTest(key=key):
                self.files["context.json"]=encoded({**self.context,key:value})
                with self.assertRaises(RuntimeError):self.validate()
        self.files["context.json"]=b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(RuntimeError):self.validate()
    def test_bind_rejects_failed_changed_or_malformed_first_observation(self):
        for key,value in (("status","failed"),("context_sha256","b"*64),("pool",dict(checked_out=False,disposed=True)),
            ("pool",dict(checked_out=0,disposed=1)),("schema_version",True)):
            context=self.bind();data=json.loads(self.files["preflight.json"]);data[key]=value
            self.files["preflight.json"]=encoded(data)
            with self.subTest(key=key),self.assertRaises(RuntimeError):h.bind_context(context,reader=self.read)
        context=self.bind();self.files["manifest.json"]=encoded(dict(schema_version=1,context_sha256=context.context_sha256,preflight_sha256="0"*64,cluster="654321"))
        with self.assertRaises(RuntimeError):h.bind_context(context,reader=self.read)
    def test_symlink_refusal_and_missing_cli_context_cannot_construct_engine(self):
        with patch.object(Path,"is_symlink",return_value=True),self.assertRaises(RuntimeError):self.validate()
        with patch.object(h,"preflight") as preflight,self.assertRaises(RuntimeError):h.main(["preflight"],env={})
        preflight.assert_not_called()
    def test_source_manifest_hashes_empty_package_files_without_relaxing_receipts(self):
        base=MagicMock();base.resolve.return_value=base;base.is_symlink.return_value=False
        source=MagicMock();source.exists.return_value=True;source.is_symlink.return_value=False
        source.resolve.return_value=source;source.is_file.return_value=True;source.suffix=".py"
        source.relative_to.return_value.as_posix.return_value="infra/__init__.py"
        # Focused empty-source read boundary; the actual enumerator uses the
        # permissive option only for .py, never receipt/config/lock reads.
        path=MagicMock();path.is_absolute.return_value=True;path.resolve.return_value=path;path.is_symlink.return_value=False
        status=SimpleNamespace(st_mode=0o100600,st_size=0,st_dev=1,st_ino=2,st_mtime_ns=3)
        path.stat.return_value=status;path.open.return_value.__enter__.return_value.read.return_value=b""
        self.assertEqual(h.read_bytes(path,allow_empty=True),b"")
        with self.assertRaises(RuntimeError):h.read_bytes(path)
        actual=h.source_manifest(Path(__file__).resolve().parents[3])
        self.assertIn("pyproject.toml",actual);self.assertIn("uv.lock",actual)
        self.assertIn("tests/integration/core/worker_authority_ci.py",actual)


class ModeContract(unittest.TestCase):
    def setUp(self):self.context=h.Context(Path.cwd()/"inert-only-not-created",Path.cwd(),"f"*64,"123456")
    def run_good(self):
        runtime=FakeRuntime();files=MemoryFiles()
        self.assertEqual(h.run(self.context,runtime=runtime,journal_factory=files.factory),0)
        return runtime,files
    def test_preflight_is_identity_only_and_one_shot(self):
        runtime=FakeRuntime();files=MemoryFiles()
        self.assertEqual(h.preflight(self.context,runtime=runtime,journal_factory=files.factory),0)
        self.assertEqual(runtime.calls,["engine","identity","fresh"])
        self.assertEqual(files.record("preflight.json")["pool"],dict(checked_out=0,disposed=True))
        self.assertEqual(h.preflight(self.context,runtime=runtime,journal_factory=files.factory),74)
        self.assertEqual(runtime.calls,["engine","identity","fresh"])
    def test_first_observation_failures_never_become_usable(self):
        for fault in ("engine","identity","fresh"):
            runtime=FakeRuntime(fault);files=MemoryFiles()
            self.assertEqual(h.preflight(self.context,runtime=runtime,journal_factory=files.factory),1)
            self.assertEqual(files.record("preflight.json")["status"],"failed")
            self.assertNotIn("migrate",runtime.calls)
    def test_full_run_exact_lifecycle_then_independent_observe_only_settlement(self):
        runtime,files=self.run_good()
        self.assertEqual(runtime.calls,["engine","identity","fresh","migrate","seed","capture","execute"])
        self.assertEqual([r["event"] for r in h.parse_proof(files.read(self.context.root/"proof.jsonl",h.JOURNAL_LIMIT),self.context)],
            ["initialized","before_execute","final"])
        second=FakeRuntime()
        self.assertEqual(h.settlement(self.context,0,runtime=second,reader=files.read,journal_factory=files.factory),0)
        self.assertEqual(second.calls,["engine","identity","inspect","capture"])
        report=files.record("settlement.json")
        self.assertEqual(report["service_disposition"],"CI_managed_not_independently_observed")
        self.assertEqual(report["actual_proof_exit"],0);self.assertTrue(report["preservation"])
    def test_second_identity_mismatch_stops_before_migration_or_provisioning(self):
        runtime=FakeRuntime();runtime.observation["cluster"]="654321";files=MemoryFiles()
        self.assertEqual(h.run(self.context,runtime=runtime,journal_factory=files.factory),1)
        self.assertEqual(runtime.calls,["engine","identity"]);runtime.owner.dispose.assert_called_once_with()
    def test_stage_failures_stop_later_work_and_preserve_partial_evidence(self):
        for fault in ("engine","fresh","migrate","seed","capture","execute","unknown_commit","control"):
            with self.subTest(fault=fault):
                runtime=FakeRuntime(fault);files=MemoryFiles()
                code=h.run(self.context,runtime=runtime,journal_factory=files.factory)
                self.assertEqual(code,130 if fault=="control" else 1)
                records=[json.loads(line) for line in files.files["proof.jsonl"].splitlines()]
                self.assertEqual(records[-1]["data"]["status"],"failed")
                self.assertLessEqual(runtime.calls.count("execute"),1)
                self.assertNotIn("SENSITIVE",files.files["proof.jsonl"])
                if fault=="unknown_commit":self.assertEqual(records[-1]["data"]["proof"]["provisioning_commit"],"unconfirmed_requires_Main_inspection")
                if fault=="control":self.assertEqual(len(records[-1]["data"]["proof"]["receiver_checks"]),1)
    def test_empty_twenty_baseline_blocks_execute(self):
        runtime=FakeRuntime();runtime.after["provider_diagnostics"]["count"]=0;files=MemoryFiles()
        self.assertEqual(h.run(self.context,runtime=runtime,journal_factory=files.factory),1)
        self.assertNotIn("execute",runtime.calls)
    def test_durability_failure_is_sticky_and_blocks_early_provision(self):
        for fault,index in (("open",1),("write",1),("flush",1),("sync",1),("control_sync",1),("short",1),
            ("write",2),("flush",2),("sync",2),("sync",3),("close",1)):
            with self.subTest(fault=fault,index=index):
                runtime=FakeRuntime();files=MemoryFiles(fault,index)
                self.assertEqual(h.run(self.context,runtime=runtime,journal_factory=files.factory),74)
                if fault=="open" or index<=2 and fault!="close":self.assertNotIn("execute",runtime.calls)
                if fault=="sync" and index==1:self.assertGreaterEqual(files.syncs,2)  # later fsync success cannot clear74.
    def test_actual_exit_wins_over_written_candidate_zero(self):
        runtime=FakeRuntime();files=MemoryFiles("close")
        self.assertEqual(h.run(self.context,runtime=runtime,journal_factory=files.factory),74)
        self.assertEqual(json.loads(files.files["proof.jsonl"].splitlines()[-1])["data"]["candidate_exit"],0)
        files.fault=None
        self.assertEqual(h.settlement(self.context,74,runtime=FakeRuntime(),reader=files.read,journal_factory=files.factory),1)
    def test_partial_or_invalid_journal_still_inspects_but_never_passes(self):
        for payload in (b"",b"{bad",b'{}\n{}\n{}\n',b'{"event":"x","event":"y"}'):
            runtime=FakeRuntime();files=MemoryFiles();files.files["proof.jsonl"]=payload.decode()
            self.assertEqual(h.settlement(self.context,0,runtime=runtime,reader=files.read,journal_factory=files.factory),1)
            self.assertIn("inspect",runtime.calls);self.assertNotIn("execute",runtime.calls)
    def test_missing_exit_login_sessions_lost_history_and_wrong_cluster_are_nonpassing(self):
        for variant in ("missing_exit","login","receiver_session","owner_same_application","preservation","cluster"):
            _,files=self.run_good();runtime=FakeRuntime();exit_code=0
            if variant=="missing_exit":exit_code=None
            if variant=="login":runtime.inspection["role_login"]=True
            if variant in ("receiver_session","owner_same_application"):
                runtime.inspection["sessions"]=[dict(pid=123,started="synthetic",role="owner" if variant=="owner_same_application" else "receiver",application="expected")]
            if variant=="preservation":runtime.after["provider_diagnostics"]["projection_multiset"]={}
            if variant=="cluster":runtime.observation["cluster"]="654321"
            with self.subTest(variant=variant):
                self.assertEqual(h.settlement(self.context,exit_code,runtime=runtime,reader=files.read,journal_factory=files.factory),1)
                if variant=="cluster":self.assertNotIn("inspect",runtime.calls)
    def test_predicates_refuse_missing_checks_and_unknown_commits(self):
        before=baseline();valid=success(before)
        for key,value in (("status","passed_pending_settlement"),("control_interrupted",True),("sql_denials",20),
            ("role_disable_commit","unconfirmed"),("receiver_checked_out",False),("receiver_checks",[]),
            ("baseline_preserved",False),("active_sql_probe_id","journal_0")):
            with self.subTest(key=key),self.assertRaises(RuntimeError):h.proof_success({**valid,key:value},before)


class RuntimeSeams(unittest.TestCase):
    def test_real_seed_path_uses_accepted_baseline_and_synthetic_journal_only(self):
        from datetime import datetime,timezone
        from tests.contracts.profiles.test_diagnostic_journal_contract import invocation
        from tests.integration.core import provider_diagnostics as fixture
        from services.api.profiles import diagnostics as d
        engine=MagicMock();conn=engine.begin.return_value.__enter__.return_value
        conn.execute.return_value.scalar_one.return_value=datetime(2026,1,1,tzinfo=timezone.utc)
        ctx=invocation();events=[]
        def decision(kind):
            def call(supplied,command,*args,**kwargs):
                self.assertIs(supplied,conn);self.assertEqual(command.kind,kind)
                self.assertTrue(kwargs["trust"].provenance(command))
                self.assertIsNone(kwargs["trust"].publish_after_commit)
                events.append(kind)
            return call
        with patch.object(fixture,"seed_original_baseline",side_effect=lambda c:events.append("original18")),\
            patch.object(fixture,"seed",return_value=(ctx,"inert-never-stored")),\
            patch.object(d,"admit",side_effect=decision("admit")),patch.object(d,"reserve_round",side_effect=decision("reserve")),\
            patch.object(d,"observe_usage",side_effect=decision("observe")),patch.object(d,"commit_candidate",side_effect=decision("candidate")),\
            patch.object(d,"stop",side_effect=decision("stop")):
            h.Runtime().seed(engine)
        self.assertEqual(events,["original18","admit","reserve","observe","candidate","stop"])

    def test_capture_includes_every_table_ordered_columns_and_multiplicity(self):
        from collections import Counter
        from tests.integration.core import worker_authority as proof
        engine=MagicMock();conn=engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.scalars.return_value.all.return_value=["id","original_second"]
        rows={table:Counter({"a"*32:2}) for table in proof.TABLES}
        with patch.object(proof,"snapshot",return_value=rows),patch.object(proof,"schema_projection",return_value=["shape"]):
            observed,schema=h.Runtime().capture(engine)
        self.assertEqual(set(observed),set(h.TABLES));self.assertEqual(schema,["shape"])
        for row in observed.values():
            self.assertEqual(row["columns"],["id","original_second"]);self.assertEqual(row["count"],2)
            self.assertEqual(row["projection_multiset"],{"a"*32:2})
        self.assertEqual(conn.execute.call_count,20)

    def test_fixed_owner_connection_does_not_use_worker_or_retained_configuration(self):
        with patch("sqlalchemy.create_engine") as create:
            h.Runtime().engine();args,kwargs=create.call_args
        url=args[0];self.assertEqual((url.host,url.port,url.database,url.username),(h.HOST,5432,h.DATABASE,h.OWNER))
        self.assertEqual(url.password,h.OWNER_PASSWORD);self.assertFalse(kwargs["echo"]);self.assertTrue(kwargs["hide_parameters"])
        self.assertEqual(kwargs["connect_args"]["passfile"],h.os.devnull)
        self.assertIn("lock_timeout=1000",kwargs["connect_args"]["options"])
    def test_migration_is_literal_nine_on_supplied_connection_without_env_hooks(self):
        engine=MagicMock();conn=engine.begin.return_value.__enter__.return_value
        script=MagicMock();script.get_heads.return_value=[h.MIGRATION]
        environment=MagicMock();environment.__enter__.return_value=environment
        def construct(config,selected,**options):
            self.assertIs(selected,script);self.assertEqual(options["destination_rev"],"0009_provider_diagnostics")
            self.assertFalse(options["as_sql"]);options["fn"]("0008_run_cancellation",object());return environment
        with patch("alembic.script.ScriptDirectory.from_config",return_value=script),\
            patch("alembic.runtime.environment.EnvironmentContext",side_effect=construct):h.Runtime().migrate(engine,Path.cwd())
        script._upgrade_revs.assert_called_once_with("0009_provider_diagnostics","0008_run_cancellation")
        script.run_env.assert_not_called();environment.configure.assert_called_once_with(connection=conn,transactional_ddl=True)
        environment.run_migrations.assert_called_once_with()
    def test_session_inspection_excludes_only_own_pid_and_keeps_other_owner(self):
        from datetime import datetime,timezone
        engine=MagicMock();conn=engine.connect.return_value.__enter__.return_value
        conn.execute.side_effect=[SimpleNamespace(scalar_one_or_none=lambda:False),
            SimpleNamespace(all=lambda:[(42,datetime(2026,1,1,tzinfo=timezone.utc),h.OWNER,h.APPLICATION)])]
        result=h.Runtime().inspect(engine)
        self.assertEqual(result["sessions"][0]["role"],"owner")
        sql=str(conn.execute.call_args_list[1].args[0])
        self.assertIn("pid<>pg_backend_pid()",sql);self.assertNotIn("application_name<>",sql)
        self.assertFalse(any(word in sql.upper() for word in ("TERMINATE","ALTER ","DROP ")))


if __name__=="__main__":unittest.main()
