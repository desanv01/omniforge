"""Closed disposable-CI authority proof. Import performs no configuration or I/O.

Trusted fresh job only, never a retained/native receiver or generic SQL executor.
Two SQL identity observations are not control-file/capture attestation. Main owns
actual process wall budget, exit capture, service lifecycle and safe export.
"""
from dataclasses import dataclass, replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID

JOB = "postgres-worker-authority9"
PURPOSE = "omniforge-worker-authority9-ci-v1"
OWNER = "omniforge_worker_schema9_ci_owner"
ROLE = "omniforge_b3c_receiver_v1"
DATABASE = "omniforge_rebuild"
HOST = "of-core-db"
MIGRATION = "0009_provider_diagnostics"
OWNER_PASSWORD = "ephemeral-worker-owner-ci-only"  # PUBLIC synthetic CI data.
RECEIVER_PASSWORD = "ephemeral-worker-receiver-ci-only"
APPLICATION = "omniforge-worker-authority-ci-v1"
SOURCE_DIRS = ("infra/core", "migrations", "services", "adapters", "packages", "tests/integration")
SOURCE_FILES = ("pyproject.toml", "uv.lock", "infra/__init__.py", "tests/__init__.py", "tests/integration/__init__.py")
TABLES = tuple("principals cases case_grants artifacts artifact_associations idempotency provider_profile_versions "
    "provider_enrollments runs run_events run_outbox run_attempts run_outputs run_scheduler_executions "
    "run_scheduler_submissions run_cancellations run_cancel_targets run_cancel_receipts "
    "provider_diagnostics provider_diagnostic_rounds".split())
LIMIT = 131072
JOURNAL_LIMIT = 2097152


def require(value):
    if not value: raise RuntimeError("Disposable worker CI prerequisite unavailable")


def digest(raw):return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result);result[key]=value
    return result


def decode(raw):
    require(type(raw) is bytes)
    return json.loads(raw.decode("utf-8"),object_pairs_hook=unique,
        parse_constant=lambda value:require(False))


def read_bytes(path,limit=LIMIT,*,allow_empty=False):
    require(path.is_absolute() and path==path.resolve() and not path.is_symlink())
    before=path.stat();require(stat.S_ISREG(before.st_mode) and (0 if allow_empty else 1)<=before.st_size<=limit)
    with path.open("rb") as handle:raw=handle.read(limit+1)
    after=path.stat()
    require((0 if allow_empty else 1)<=len(raw)<=limit and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
        (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns))
    return raw


def source_manifest(base):
    """Fixed rebuild-local import tree + dependency locks; no private traversal."""
    require(base==base.resolve() and not base.is_symlink())
    paths=[]
    for name in SOURCE_DIRS:
        directory=base/name
        if not directory.exists():continue
        require(not directory.is_symlink() and directory.resolve()==directory)
        for path in directory.rglob("*"):
            require(not path.is_symlink() and path.resolve()==path)
            if path.is_file() and path.suffix==".py":paths.append(path)
    for name in SOURCE_FILES:
        path=base/name
        if path.exists():paths.append(path)
        elif name in ("pyproject.toml","uv.lock"):require(False)
    return {path.relative_to(base).as_posix():digest(read_bytes(path,4194304,allow_empty=path.suffix==".py")) for path in sorted(set(paths))}


@dataclass(frozen=True)
class Context:
    root: Path
    source: Path
    context_sha256: str
    cluster: str | None = None


def validate_context(env,*,reader=read_bytes,hasher=source_manifest,source=None):
    require(env.get("GITHUB_ACTIONS")=="true" and env.get("GITHUB_JOB")==JOB)
    require(env.get("GITHUB_EVENT_NAME") in ("push","pull_request"))
    require("OMNIFORGE_CONFIG" not in env and not any(name.upper().startswith("PG") for name in env))
    for key in ("GITHUB_RUN_ID","GITHUB_RUN_ATTEMPT"):
        require(type(env.get(key)) is str and re.fullmatch(r"[1-9][0-9]{0,19}",env[key]))
    require(type(env.get("GITHUB_SHA")) is str and re.fullmatch(r"[0-9a-f]{40}",env["GITHUB_SHA"]))
    paths={}
    for name in ("RUNNER_TEMP","GITHUB_WORKSPACE","OMNIFORGE_WORKER_CI_ROOT","OMNIFORGE_WORKER_CI_CONTEXT","OMNIFORGE_WORKER_CI_MANIFEST"):
        value=env.get(name);require(type(value) is str and value and not any(c in value for c in "\x00\r\n"))
        path=Path(value);require(path.is_absolute() and not path.is_symlink() and path==path.resolve());paths[name]=path
    temporary,workspace,root=(paths[name] for name in ("RUNNER_TEMP","GITHUB_WORKSPACE","OMNIFORGE_WORKER_CI_ROOT"))
    require(not temporary.is_relative_to(workspace) and not workspace.is_relative_to(temporary))
    require(root.parent==temporary and root.name.startswith("omniforge-worker-authority9-"))
    require(paths["OMNIFORGE_WORKER_CI_CONTEXT"]==root/"context.json" and paths["OMNIFORGE_WORKER_CI_MANIFEST"]==root/"manifest.json")
    base=source if source is not None else Path(__file__).resolve().parents[3]
    require(base==workspace/"rebuild")
    raw=reader(root/"context.json",LIMIT);data=decode(raw)
    expected=dict(schema_version=1,purpose=PURPOSE,job=JOB,event=env["GITHUB_EVENT_NAME"],
        run_id=env["GITHUB_RUN_ID"],run_attempt=env["GITHUB_RUN_ATTEMPT"],sha=env["GITHUB_SHA"],
        root=str(root),workspace=str(workspace),sources=hasher(base))
    require(type(data) is dict and data==expected and type(data["schema_version"]) is int)
    return Context(root,base,digest(raw))


def identity_valid(value):
    require(type(value) is dict and set(value)=={"database","owner","session","schema","cluster","server_version"})
    require((value["database"],value["owner"],value["session"],value["schema"])==(DATABASE,OWNER,OWNER,"public"))
    require(type(value["cluster"]) is str and re.fullmatch(r"[1-9][0-9]{0,19}",value["cluster"]))
    require(type(value["server_version"]) is str and re.fullmatch(r"[1-9][0-9]{4,7}",value["server_version"]))
    return value


def bind_context(context,*,reader=read_bytes):
    raw=reader(context.root/"preflight.json",LIMIT);first=decode(raw)
    require(type(first) is dict and set(first)=={"schema_version","mode","status","context_sha256","identity","failures","pool"})
    require(type(first["schema_version"]) is int and first["schema_version"]==1 and first["mode"]=="preflight"
        and first["status"]=="passed" and first["context_sha256"]==context.context_sha256 and first["failures"]==[])
    identity=identity_valid(first["identity"])
    require(type(first["pool"]) is dict and first["pool"]=={"checked_out":0,"disposed":True}
        and type(first["pool"]["checked_out"]) is int and first["pool"]["disposed"] is True)
    manifest=decode(reader(context.root/"manifest.json",LIMIT))
    require(type(manifest) is dict and manifest==dict(schema_version=1,context_sha256=context.context_sha256,
        preflight_sha256=digest(raw),cluster=identity["cluster"]) and type(manifest["schema_version"]) is int)
    return replace(context,cluster=identity["cluster"])


class Journal:
    """Sticky durability failure; later successful writes cannot repair an exit74."""
    def __init__(self,path,*,opener=None,sync=None):
        self.handle=None;self.failed=False;self.sequence=0
        self.sync=sync or os.fsync
        try:self.handle=(opener or (lambda p:p.open("x",encoding="utf-8")))(path)
        except BaseException:self.failed=True

    def write(self,value):
        if self.handle is None:self.failed=True;return False
        try:
            payload=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n"
            require(self.handle.write(payload)==len(payload))
            self.handle.flush();self.sync(self.handle.fileno());return True
        except BaseException:self.failed=True;return False

    def event(self,event,context,data):
        self.sequence+=1
        return self.write(dict(sequence=self.sequence,event=event,context_sha256=context.context_sha256,data=data))

    def close(self):
        if self.handle is not None:
            try:self.handle.close()
            except BaseException:self.failed=True


class Runtime:
    """Only fixed reviewed CI operations; imported dependencies stay lazy."""
    def engine(self):
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
        url=URL.create("postgresql+psycopg",username=OWNER,password=OWNER_PASSWORD,host=HOST,port=5432,database=DATABASE)
        return create_engine(url,pool_size=2,max_overflow=0,pool_timeout=1,echo=False,hide_parameters=True,
            connect_args={"connect_timeout":3,"application_name":APPLICATION,
                "sslmode":"disable","gssencmode":"disable","channel_binding":"disable","passfile":os.devnull,
                "options":"-c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000"})

    def identity(self,engine):
        from sqlalchemy import text
        with engine.connect() as conn:
            row=conn.execute(text("SELECT current_database(),current_user,session_user,current_schema(),(SELECT system_identifier::text FROM pg_control_system()),current_setting('server_version_num')")).one()
        return identity_valid(dict(zip(("database","owner","session","schema","cluster","server_version"),row)))

    def fresh(self,engine):
        from sqlalchemy import text
        with engine.connect() as conn:
            require(conn.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")).scalar_one()==0)
            require(conn.execute(text("SELECT count(*) FROM pg_roles WHERE rolname=:role"),{"role":ROLE}).scalar_one()==0)

    def migrate(self,engine,source):
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.environment import EnvironmentContext
        config=Config();config.set_main_option("script_location",str(source/"migrations"))
        script=ScriptDirectory.from_config(config);require(script.get_heads()==[MIGRATION])
        # Same pinned Alembic upgrade-step producer as command.upgrade, explicitly
        # connected here; never run env.py, accept target input, stamp or reset.
        with engine.begin() as conn:
            with EnvironmentContext(config,script,fn=lambda revision,context:script._upgrade_revs(MIGRATION,revision),
                    as_sql=False,destination_rev=MIGRATION) as environment:
                environment.configure(connection=conn,transactional_ddl=True)
                with environment.begin_transaction():environment.run_migrations()

    def seed(self,engine):
        from datetime import timedelta
        from dataclasses import replace as copy
        from uuid import uuid4
        from sqlalchemy import text
        from tests.integration.core.provider_diagnostics import seed_original_baseline,seed
        from services.api.profiles import diagnostics as d
        from services.api.providers.diagnostic_protocol import Reservation,Observation
        with engine.begin() as conn:
            seed_original_baseline(conn);ctx,token=seed(conn)
            bound=conn.execute(text("SELECT clock_timestamp()")).scalar_one()+timedelta(seconds=25)
            current=[None]
            trust=d.Trust(provenance=lambda command:command is current[0],cutoff=lambda c,command,desc:desc.fixed_db_not_after,
                issue_capability=lambda command:hashlib.sha256(ctx.operation_id.bytes).digest())
            def command(kind,payload):
                candidate=d.Command(ctx,uuid4(),0,kind,"0"*64)
                current[0]=copy(candidate,request_digest=d.request_digest(candidate,payload))
                purpose="work_admission" if kind=="admit" else "work_decision"
                return current[0],d.CutoffDescriptor(uuid4(),ctx.fingerprint,current[0].command_id,purpose,bound,0,uuid4(),"valid_conservative")
            cmd,desc=command("admit",{});d.admit(conn,cmd,desc,bearer_token=token,trust=trust)
            reservation=Reservation(ctx.operation_id,1,"a"*64,10,10)
            cmd,desc=command("reserve",{"reservation":reservation.replay_digest})
            d.reserve_round(conn,cmd,reservation,desc,bearer_token=token,trust=trust)
            observation=Observation(reservation,5,None,"provider_reported","response_received",10,10)
            cmd,desc=command("observe",{"observation":observation.replay_digest})
            d.observe_usage(conn,cmd,observation,desc,bearer_token=token,trust=trust)
            cmd,desc=command("candidate",{"candidate_digest":"b"*64})
            d.commit_candidate(conn,cmd,"b"*64,desc,bearer_token=token,trust=trust)
            cmd,desc=command("stop",{"reason":"canceled"});d.stop(conn,cmd,"canceled",desc,bearer_token=token,trust=trust)

    def capture(self,engine):
        from sqlalchemy import text
        from tests.integration.core import worker_authority as proof
        require(proof.TABLES==TABLES)
        with engine.connect() as conn:
            rows=proof.snapshot(conn);schema=proof.schema_projection(conn);output={}
            for table in TABLES:
                columns=conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:table ORDER BY ordinal_position"),{"table":table}).scalars().all()
                require(columns)
                output[table]=dict(columns=list(columns),count=sum(rows[table].values()),projection_multiset=dict(rows[table]))
        return output,schema

    def execute(self,engine,cluster,evidence):
        from tests.integration.core import worker_authority as proof
        return proof.execute(owner_engine=engine,expected_owner=OWNER,expected_cluster=cluster,new_secret=RECEIVER_PASSWORD,
            release=proof.RELEASE,evidence=evidence)

    def inspect(self,engine):
        from sqlalchemy import text
        with engine.connect() as conn:
            login=conn.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname=:role"),{"role":ROLE}).scalar_one_or_none()
            require(login is None or type(login) is bool)
            # Exclude this exact connection PID only; include every other owner
            # session even when application_name matches this controller.
            rows=conn.execute(text("SELECT pid,backend_start,usename,application_name FROM pg_stat_activity WHERE datname=:database AND usename IN (:owner,:receiver) AND pid<>pg_backend_pid() ORDER BY pid"),
                {"database":DATABASE,"owner":OWNER,"receiver":ROLE}).all()
        return dict(role_exists=login is not None,role_login=login,sessions=[dict(pid=row[0],started=row[1].isoformat(),
            role="receiver" if row[2]==ROLE else "owner",application="expected" if row[3] in (APPLICATION,"omniforge-b3c-receiver-v1") else "other") for row in rows])


def pool_settle(engine,failures):
    result={"checked_out":None,"disposed":False}
    if engine is None:return result
    try:result["checked_out"]=engine.pool.checkedout();require(type(result["checked_out"]) is int and result["checked_out"]==0)
    except BaseException:failures.append("pool_check_unconfirmed")
    try:engine.dispose();result["disposed"]=True
    except BaseException:failures.append("pool_disposal_unconfirmed")
    return result


def preserved(before,after):
    require(set(before)==set(TABLES) and set(after)==set(TABLES))
    return all(after[table]["columns"]==old["columns"] and all(after[table]["projection_multiset"].get(value,0)>=count
        for value,count in old["projection_multiset"].items()) for table,old in before.items())


def proof_success(evidence,before):
    require(evidence.get("status")=="passed" and evidence.get("control_interrupted") is False and evidence.get("failure_stages")==[])
    require(evidence.get("baseline_preserved") is True and evidence.get("schema_preserved") is True and evidence.get("empty_baseline_tables")==[])
    require(evidence.get("provisioning_commit")=="confirmed" and evidence.get("role_disable_commit")=="confirmed")
    require(evidence.get("role_disposition")=="retained_NOLOGIN_with_grants_and_history")
    for name in ("owner","receiver"):
        require(type(evidence.get(name+"_checked_out")) is int and evidence[name+"_checked_out"]==0)
        require(evidence.get(name+"_pool_disposition")=="disposed_not_a_physical_connection_stop_claim")
    require(set(evidence.get("baseline20",{}))==set(TABLES))
    for table in TABLES:
        require(evidence["baseline20"][table]=={key:before[table][key] for key in ("count","projection_multiset")})
    checks=evidence.get("sql_denial_checks",[])
    require(evidence.get("sql_denials")==21 and len(checks)==21 and evidence.get("active_sql_probe_id") is None)
    require([item.get("probe_id") for item in checks]==["legacy_"+str(i) for i in range(13)]+["journal_"+str(i) for i in range(8)])
    require(all(item.get("status")=="passed" and item.get("sqlstate")=="42501" for item in checks))
    runs=evidence.get("runs",[]);scenarios=evidence.get("receiver_checks",[])
    require(len(runs)==7 and len(scenarios)==7 and len({item["run_id"] for item in runs})==7)
    require(all(type(item["run_id"]) is str and str(UUID(item["run_id"]))==item["run_id"] for item in runs))
    from tests.integration.core.worker_authority import PURPOSES
    require([item["purpose"] for item in runs]==list(PURPOSES))
    require([(item["run_id"],item["purpose"]) for item in scenarios]==[(item["run_id"],item["purpose"]) for item in runs])
    require(all(item.get("status")=="passed" for item in scenarios))


def preflight(context,*,runtime=None,journal_factory=Journal):
    runtime=runtime or Runtime();journal=journal_factory(context.root/"preflight.json")
    if journal.failed:return 74
    engine=None;report=dict(schema_version=1,mode="preflight",status="failed",context_sha256=context.context_sha256,identity=None,failures=[],pool=None)
    try:
        engine=runtime.engine();report["identity"]=identity_valid(runtime.identity(engine));runtime.fresh(engine)
        report["status"]="passed"
    except BaseException:report["failures"].append("preflight_unavailable")
    finally:
        report["pool"]=pool_settle(engine,report["failures"])
        if report["failures"]:report["status"]="failed"
        journal.write(report);journal.close()
    return 74 if journal.failed else 0 if report["status"]=="passed" else 1


def run(context,*,runtime=None,journal_factory=Journal):
    require(context.cluster is not None)
    runtime=runtime or Runtime();journal=journal_factory(context.root/"proof.jsonl")
    if journal.failed:return 74
    report=dict(status="failed",external_capture="unknown",native_execution="unproved",failures=[],proof={},baseline20=None,schema=None,pool=None)
    engine=None;interrupted=False
    try:
        require(journal.event("initialized",context,{"status":"prepared","external_capture":"unknown"}))
        engine=runtime.engine();require(identity_valid(runtime.identity(engine))["cluster"]==context.cluster);runtime.fresh(engine)
        runtime.migrate(engine,context.source);runtime.seed(engine)
        before,schema=runtime.capture(engine);report.update(baseline20=before,schema=schema)
        require(set(before)==set(TABLES) and all(type(row["count"]) is int and row["count"]>0 for row in before.values()))
        require(journal.event("before_execute",context,{"baseline20":before,"schema":schema,"provisioning":"not_attempted"}))
        runtime.execute(engine,context.cluster,report["proof"])
        proof_success(report["proof"],before);report["status"]="passed"
    except BaseException as error:
        interrupted=not isinstance(error,Exception);report["failures"].append("control_interruption" if interrupted else "proof_unavailable")
    finally:
        report["pool"]=pool_settle(engine,report["failures"])
        if report["failures"]:report["status"]="failed"
        candidate=130 if interrupted else 0 if report["status"]=="passed" else 1
        report["candidate_exit"]=candidate
        journal.event("final",context,report);journal.close()
    return 74 if journal.failed else candidate


def parse_proof(raw,context):
    lines=raw.splitlines();require(len(lines)==3)
    records=[decode(line) for line in lines]
    for index,(record,event) in enumerate(zip(records,("initialized","before_execute","final")),1):
        require(type(record) is dict and set(record)=={"sequence","event","context_sha256","data"})
        require(type(record["sequence"]) is int and record["sequence"]==index and record["event"]==event
            and record["context_sha256"]==context.context_sha256 and type(record["data"]) is dict)
    return records


def settlement(context,proof_exit,*,runtime=None,reader=read_bytes,journal_factory=Journal):
    require(context.cluster is not None and (proof_exit is None or type(proof_exit) is int and 0<=proof_exit<=255))
    runtime=runtime or Runtime();journal=journal_factory(context.root/"settlement.json")
    if journal.failed:return 74
    report=dict(schema_version=1,mode="settlement",status="failed",context_sha256=context.context_sha256,
        actual_proof_exit=proof_exit,failures=[],inspection=None,preservation=None,pool=None,
        service_disposition="CI_managed_not_independently_observed",external_capture="unknown")
    engine=None;records=None
    try:records=parse_proof(reader(context.root/"proof.jsonl",JOURNAL_LIMIT),context)
    except BaseException:report["failures"].append("proof_receipt_unavailable")
    try:
        engine=runtime.engine();require(identity_valid(runtime.identity(engine))["cluster"]==context.cluster)
        try:report["inspection"]=runtime.inspect(engine)
        except BaseException:report["failures"].append("role_session_inspection_unavailable")
        if records is not None:
            try:
                before=records[1]["data"]["baseline20"];schema=records[1]["data"]["schema"]
                after,current_schema=runtime.capture(engine)
                report["preservation"]=preserved(before,after) and schema==current_schema
                require(report["preservation"])
            except BaseException:report["failures"].append("preservation_unconfirmed")
        require(records is not None and proof_exit==0)
        final=records[2]["data"]
        require(final.get("status")=="passed" and type(final.get("candidate_exit")) is int and final["candidate_exit"]==0 and final.get("failures")==[])
        require(type(final["pool"]["checked_out"]) is int and final["pool"]["checked_out"]==0 and final["pool"]["disposed"] is True)
        proof_success(final["proof"],records[1]["data"]["baseline20"])
        require(report["preservation"] is True and report["inspection"]==dict(role_exists=True,role_login=False,sessions=[]))
        require(not report["failures"]);report["status"]="selected_sql_and_sessions_settled_service_unobserved"
    except BaseException:report["failures"].append("settlement_unconfirmed")
    finally:
        report["pool"]=pool_settle(engine,report["failures"])
        if report["failures"]:report["status"]="failed"
        journal.write(report);journal.close()
    return 74 if journal.failed else 0 if report["status"]!="failed" else 1


def main(argv=None,*,env=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("preflight","run","settlement"))
    parser.add_argument("--proof-exit",type=int)
    args=parser.parse_args(argv)
    require(args.mode=="settlement" or args.proof_exit is None)
    context=validate_context(os.environ if env is None else env)
    if args.mode=="preflight":return preflight(context)
    context=bind_context(context)
    return run(context) if args.mode=="run" else settlement(context,args.proof_exit)


if __name__=="__main__":
    try:code=main()
    except BaseException:code=1
    raise SystemExit(code)
