"""Closed disposable-CI proof harness; never a production journal adapter.

Main-controlled workflow/config provenance is mandatory. No retained-config fallback,
store/provider/native calls or actual clock/channel producer. Runtime release is
separate from source review. Migration lifecycle stays in this one process.
"""
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import unittest

DATABASE = "omniforge_rebuild_journal_ci"
JOB = "postgres-provider-journal"
PURPOSE = "omniforge-provider-journal-ci-v1"
STABLE = "0008_run_cancellation"
JOURNAL = "0009_provider_diagnostics"


def require(value):
    if not value: raise RuntimeError("Synthetic journal proof prerequisite unavailable")


def read_json(path):
    require(not path.is_symlink() and path.stat().st_size <= 16384)
    with path.open(encoding="utf-8") as handle: return json.load(handle)


@dataclass(frozen=True)
class Context:
    root: Path
    config: Path
    database_url: str = field(repr=False)


def validate_context(env, *, reader=read_json, parse_url=None):
    """Only trusted Main CI tuple; a marker/prefix alone never selects a DB."""
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_JOB") == JOB)
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(type(env.get(key)) is str and re.fullmatch(r"[1-9][0-9]{0,19}", env[key]))
    paths = {}
    for name in ("RUNNER_TEMP", "GITHUB_WORKSPACE", "OMNIFORGE_JOURNAL_CI_ROOT", "OMNIFORGE_CONFIG", "OMNIFORGE_JOURNAL_CI_MANIFEST"):
        require(type(env.get(name)) is str and Path(env[name]).is_absolute())
        raw = Path(env[name]); require(not raw.is_symlink())
        paths[name] = raw.resolve()
        require(raw == paths[name])
    root, temp, workspace = (paths[name] for name in ("OMNIFORGE_JOURNAL_CI_ROOT", "RUNNER_TEMP", "GITHUB_WORKSPACE"))
    require(root.parent == temp and root.name.startswith("omniforge-journal-ci-")
            and not temp.is_relative_to(workspace) and not workspace.is_relative_to(temp))
    config, manifest_path = paths["OMNIFORGE_CONFIG"], paths["OMNIFORGE_JOURNAL_CI_MANIFEST"]
    require(config == root / "config.json" and manifest_path == root / "manifest.json")
    expected = dict(schema_version=1, purpose=PURPOSE, run_id=env["GITHUB_RUN_ID"],
        run_attempt=env["GITHUB_RUN_ATTEMPT"], job=JOB, root=str(root), config=str(config), workspace=str(workspace))
    manifest = reader(manifest_path)
    require(type(manifest) is dict and manifest == expected and type(manifest.get("schema_version")) is int)
    data = reader(config)
    require(type(data) is dict and set(data) == {"database_url", "artifact_root"})
    require(type(data["database_url"]) is str and type(data["artifact_root"]) is str
            and Path(data["artifact_root"]).resolve() == root / "artifacts")
    if parse_url is None:
        from sqlalchemy.engine import make_url
        parse_url = make_url
    url = parse_url(data["database_url"])
    require(url.drivername == "postgresql+psycopg" and url.host == "127.0.0.1" and url.port == 5432
            and url.database == DATABASE and url.username == DATABASE
            and url.password == "ephemeral-journal-ci-only" and not url.query)
    return Context(root, config, data["database_url"])


def schema_at(engine):
    from sqlalchemy import inspect, text
    with engine.connect() as conn:
        if not inspect(conn).has_table("alembic_version"): return None
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def identities(conn):
    from sqlalchemy import text
    actual = conn.execute(text("SELECT current_database(),current_user,session_user,(SELECT system_identifier::text FROM pg_control_system())")).one()
    require(tuple(actual[:3]) == (DATABASE, DATABASE, DATABASE))
    return actual[3]


def projections(conn):
    """Original ordered columns/multisets and structural digest; no raw row data."""
    from collections import Counter
    import hashlib
    from sqlalchemy import text
    from tests.integration.core.provider_diagnostics import ORIGINAL
    output = {}
    for table in ORIGINAL:
        columns = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"), {"t": table}).scalars().all()
        require(columns and all(re.fullmatch(r"[a-z_][a-z0-9_]*", column) for column in columns))
        selected = ",".join('"' + column + '"' for column in columns)
        counts = Counter(conn.execute(text(f"SELECT md5(row_to_json(t)::text) FROM (SELECT {selected} FROM {table}) t")).scalars())
        shape = [list(row) for row in conn.execute(text("""SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"""), {"t": table})]
        constraints = [list(row) for row in conn.execute(text("""SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=CAST(:t AS regclass) ORDER BY conname"""), {"t": "public." + table})]
        indexes = [list(row) for row in conn.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename=:t ORDER BY indexname"), {"t": table})]
        output[table] = dict(columns=list(columns), count=sum(counts.values()), hashes=dict(counts),
            structure=hashlib.sha256(json.dumps([shape,constraints,indexes],sort_keys=True).encode()).hexdigest())
    return output


def preserved(old, new):
    return all(new[name]["columns"] == value["columns"] and new[name]["structure"] == value["structure"]
        and all(new[name]["hashes"].get(key,0) >= count for key,count in value["hashes"].items()) for name,value in old.items())


class JournalResult(unittest.TextTestResult):
    """Record honest partial execution; failfast also covers cleanup failures."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.started_ids=[];self.passed_ids=[]

    def startTest(self,test):
        self.started_ids.append(test.id());super().startTest(test)

    def addSuccess(self,test):
        self.passed_ids.append(test.id());super().addSuccess(test)

    def addSkip(self,test,reason):
        super().addSkip(test,reason);self.stop()  # Missing proof never permits later mutations.


def run(context):
    from sqlalchemy import create_engine, text
    from infra.core.migrate import upgrade
    from tests.integration.core import provider_diagnostics as fixture
    report = {"scope": "disposable synthetic PostgreSQL only", "status": "failed", "external_capture": "unknown",
              "migration_applied": False, "native_producers": "unavailable", "baseline_complete": False,
              "empty_baseline_tables": None, "failures": []}
    engine, baseline, stream = None, None, io.StringIO()
    receipt = context.root / "journal-proof.json"
    require(not receipt.exists())
    try:
        engine = create_engine(context.database_url, pool_size=5, max_overflow=0, pool_timeout=1,
            echo=False, hide_parameters=True, connect_args={"connect_timeout":3,
                "options":"-c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000"})
        with engine.connect() as conn:
            report["cluster"] = identities(conn)
            require(conn.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")).scalar_one() == 0)
        require(schema_at(engine) is None)
        upgrade(STABLE, read_current=lambda:schema_at(engine))
        with engine.begin() as conn:
            require(all(conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()==0 for name in fixture.ORIGINAL))
            baseline=projections(conn)  # Even failed seed/transaction gets structural cleanup verification.
            fixture.seed_original_baseline(conn)
            baseline=projections(conn)
        report["empty_baseline_tables"]=[name for name,value in baseline.items() if not value["count"]]
        require(not report["empty_baseline_tables"])
        report["baseline_complete"]=True
        report["baseline18"]=baseline
        upgrade(JOURNAL, read_current=lambda:schema_at(engine))
        report["migration_applied"]=True
        require(schema_at(engine)==JOURNAL)
        with engine.connect() as conn:
            require(identities(conn)==report["cluster"] and preserved(baseline,projections(conn)))
        # Explicit same-target no-op, never reseed/replay setup.
        upgrade(JOURNAL, read_current=lambda:schema_at(engine))
        fixture.JournalPostgresProof.engine=engine
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(fixture.JournalPostgresProof)
        planned=[test.id() for test in suite]
        result=unittest.TextTestRunner(stream=stream,verbosity=0,failfast=True,resultclass=JournalResult).run(suite)
        report.update(tests=result.testsRun,skipped=len(result.skipped),
            planned_test_ids=planned,started_test_ids=result.started_ids,passed_test_ids=result.passed_ids,
            unexecuted_test_ids=[name for name in planned if name not in result.started_ids],aborted=result.shouldStop,
            failures=[{"test":test.id(),"kind":"assertion"} for test,_ in result.failures]
                +[{"test":test.id(),"kind":"test_error"} for test,_ in result.errors])
        require(result.wasSuccessful() and not result.skipped and result.testsRun>=18 and not report["unexecuted_test_ids"])
        report["status"]="synthetic_sql_pass_not_native_or_delivery_proof"
    except BaseException as exc:
        report["failures"].append({"stage":"runner","kind":"control_interruption" if not isinstance(exc,Exception) else "prerequisite_or_sql_failure"})
    finally:
        fixture.JournalPostgresProof.engine=None
        if engine is not None and baseline is not None:
            try:
                with engine.connect() as conn:
                    report["final18"]=projections(conn)
                    report["original18_preserved"]=preserved(baseline,report["final18"])
                    require(report["original18_preserved"])
            except BaseException:report["status"]="failed";report["preservation"]="unconfirmed"
        if engine is not None:
            try:
                report["checked_out"]=engine.pool.checkedout();require(report["checked_out"]==0)
            except BaseException:report["status"]="failed";report["pool_check"]="unconfirmed"
            try:engine.dispose();report["pool_disposed"]=True
            except BaseException:report["status"]="failed";report["pool_disposed"]=False
        try:
            with receipt.open("x",encoding="utf-8") as handle:
                json.dump(report,handle,indent=2);handle.flush();os.fsync(handle.fileno())
        except BaseException:return 74
    return 0 if report["status"]=="synthetic_sql_pass_not_native_or_delivery_proof" else 1


def main():
    return run(validate_context(os.environ))


if __name__=="__main__":
    try:code=main()
    except BaseException:code=1
    raise SystemExit(code)
