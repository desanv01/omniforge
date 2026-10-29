"""Constructor/connection fakes only; no real SQLAlchemy connection or socket."""
import traceback
import os
import unittest
from unittest.mock import patch

from infra.core.worker_db import APPLICATION, JOURNAL_DENIALS, WorkerDatabaseError, build_worker_engine, validate_worker_startup
from infra.core.worker_settings import DATABASE, MIGRATION, ROLE
from tests.contracts.worker import test_worker_settings as settings_fixture


def identity():
    return dict(database_name=DATABASE, current_name=ROLE, session_name=ROLE, schema_name="public",
        database_owner="synthetic-owner", rolsuper=False, rolcreatedb=False, rolcreaterole=False,
        rolreplication=False, rolbypassrls=False, rolinherit=False, has_memberships=False)


def privileges():
    return dict(schema_create=False, principal_read=False, case_read=False, idempotency_read=False,
        profile_read=False, enrollment_read=False, grant_lock_update=True, association_lock_update=True,
        artifact_lock_update=True, temporary_allowed=True, **{key:False for key in JOURNAL_DENIALS})


class FakeResult:
    def __init__(self, value): self.value = value
    def mappings(self): return self
    def one(self): return self.value
    def scalar_one(self): return self.value


class FakeEngine:
    def __init__(self):
        self.rows = [identity(), MIGRATION, privileges()]
        self.sql = []; self.connects = self.closed = self.disposed = 0
        self.failure = None
    def connect(self): self.connects += 1; return self
    def __enter__(self): return self
    def __exit__(self, *args): self.closed += 1
    def execute(self, sql):
        self.sql.append(str(sql))
        if self.failure: raise self.failure
        return FakeResult(self.rows[len(self.sql)-1])
    def dispose(self): self.disposed += 1


class WorkerDatabaseProof(unittest.TestCase):
    def settings(self): return settings_fixture.WorkerSettingsProof().parse(settings_fixture.body())

    def test_01_lazy_bounded_constructor_propagates_exact_closed_parameters(self):
        settings = self.settings(); engine = FakeEngine(); observed = []
        def construct(*args, **kwargs): observed.append((args, kwargs)); return engine
        with patch("infra.core.worker_db.create_engine", side_effect=AssertionError("No actual constructor")), \
             patch("socket.create_connection", side_effect=AssertionError("No socket")):
            self.assertIs(build_worker_engine(settings, constructor=construct), engine)
        self.assertEqual(engine.connects, 0)
        args, kwargs = observed[0]; self.assertEqual(args, (settings.database_url,))
        self.assertTrue(callable(kwargs.pop("creator")))
        self.assertEqual(kwargs, dict(pool_size=2, max_overflow=0, pool_timeout=1, pool_pre_ping=False,
            hide_parameters=True, connect_args={"connect_timeout":3,"application_name":APPLICATION,
                "options":"-c statement_timeout=5000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=5000"}))

    def test_02_explicit_startup_checks_identity_migration_and_privileges(self):
        engine = FakeEngine()
        result = validate_worker_startup(engine, self.settings())
        self.assertEqual(result.migration,"0009_provider_diagnostics")
        self.assertEqual((result.role, result.database, result.migration), (ROLE, DATABASE, MIGRATION))
        self.assertTrue(result.temporary_allowed)
        self.assertIn("actual mutation", result.authority)
        self.assertEqual((engine.connects, engine.closed, engine.disposed), (1,1,0))
        self.assertEqual(len(engine.sql), 3)
        self.assertFalse(any(word in " ".join(engine.sql).upper() for word in ("CREATE ROLE", "GRANT ", "ALTER ", "PASSWORD", "DELETE ")))
        self.assertNotIn("token_hash", " ".join(engine.sql))

    def test_03_wrong_identity_or_owner_privileges_dispose_and_deny(self):
        changes = {"database_name":"legacy", "current_name":"postgres", "session_name":"postgres",
            "schema_name":"elsewhere", "database_owner":ROLE, "rolsuper":True, "rolcreatedb":True,
            "rolcreaterole":True, "rolreplication":True, "rolbypassrls":True, "rolinherit":True,
            "has_memberships":True}
        for key, value in changes.items():
            with self.subTest(key=key):
                engine = FakeEngine(); engine.rows[0][key] = value
                with self.assertRaises(WorkerDatabaseError): validate_worker_startup(engine, self.settings())
                self.assertEqual(engine.disposed,1); self.assertEqual(engine.closed,1)
                self.assertEqual(len(engine.sql),1)

    def test_04_schema_version_exact_and_no_bootstrap_fallback(self):
        for version in ("0008_run_cancellation", "0007_run_delivery", "0010_future", "head", None):
            engine = FakeEngine(); engine.rows[1] = version
            with self.assertRaises(WorkerDatabaseError): validate_worker_startup(engine, self.settings())
            self.assertEqual(len(engine.sql),2); self.assertEqual(engine.disposed,1)

    def test_05_restricted_reads_or_missing_lock_update_fail_closed(self):
        for key in privileges():
            if key == "temporary_allowed": continue
            engine = FakeEngine(); engine.rows[2][key] = not engine.rows[2][key]
            with self.subTest(key=key), self.assertRaises(WorkerDatabaseError): validate_worker_startup(engine, self.settings())
            self.assertEqual(engine.disposed,1)
        engine = FakeEngine(); engine.rows[2]["grant_lock_update"] = 1
        with self.assertRaises(WorkerDatabaseError): validate_worker_startup(engine, self.settings())

    def test_05b_every_journal_denial_is_strict_and_required(self):
        self.assertEqual(len(JOURNAL_DENIALS),16)
        for key in JOURNAL_DENIALS:
            for value in (True,None,0,1,"false","missing"):
                engine=FakeEngine()
                if value=="missing":del engine.rows[2][key]
                else:engine.rows[2][key]=value
                with self.subTest(key=key,value=value),self.assertRaises(WorkerDatabaseError):
                    validate_worker_startup(engine,self.settings())
                self.assertEqual(engine.disposed,1)

    def test_06_effective_temp_reported_not_silently_revoked(self):
        engine = FakeEngine(); engine.rows[2]["temporary_allowed"] = False
        self.assertFalse(validate_worker_startup(engine,self.settings()).temporary_allowed)
        self.assertEqual(engine.disposed,0)

    def test_07_connect_query_constructor_and_disposal_failures_sanitized(self):
        engine = FakeEngine(); engine.failure = RuntimeError("SENSITIVE_DATABASE_FAILURE")
        try: validate_worker_startup(engine, self.settings())
        except WorkerDatabaseError as error:
            self.assertNotIn("SENSITIVE_DATABASE_FAILURE", "".join(traceback.format_exception(error)))
        else: self.fail("Database error must deny")
        self.assertEqual(engine.disposed,1)
        def fail(*args, **kwargs): raise RuntimeError("SENSITIVE_CONSTRUCTOR")
        with self.assertRaises(WorkerDatabaseError) as caught: build_worker_engine(self.settings(),constructor=fail)
        self.assertNotIn("SENSITIVE_CONSTRUCTOR", str(caught.exception))
        class FailConnect(FakeEngine):
            def connect(self): raise RuntimeError("SENSITIVE_CONNECT")
            def dispose(self): raise RuntimeError("SENSITIVE_DISPOSE")
        with self.assertRaises(WorkerDatabaseError): validate_worker_startup(FailConnect(),self.settings())

    def test_08_invalid_or_mutated_settings_rejected_before_constructor(self):
        calls = []
        with self.assertRaises(WorkerDatabaseError): build_worker_engine(None,constructor=lambda *a,**k:calls.append(a))
        settings = self.settings(); object.__setattr__(settings,"database_url","SENSITIVE_FORGED")
        with self.assertRaises(WorkerDatabaseError): build_worker_engine(settings,constructor=lambda *a,**k:calls.append(a))
        self.assertEqual(calls,[])

    def creator(self):
        saved = {}; calls = []
        def constructor(*args, **kwargs): saved.update(kwargs); return FakeEngine()
        def connect(**kwargs): calls.append(kwargs); return object()
        engine = build_worker_engine(self.settings(), constructor=constructor, connector=connect)
        self.assertEqual(engine.connects, 0)
        return saved["creator"], calls

    def test_09_physical_boundary_rejects_ambient_pg_names_before_driver(self):
        creator, calls = self.creator()
        for key in ("PGHOSTADDR", "PGSERVICE", "PGSSLMODE", "PGOPTIONS", "PGPASSFILE"):
            with self.subTest(key=key), patch("infra.core.worker_db.os.environ", {key:"SENSITIVE_PG_MARKER"}):
                with self.assertRaises(WorkerDatabaseError) as caught: creator()
                self.assertNotIn("SENSITIVE_PG_MARKER", str(caught.exception))
        self.assertEqual(calls, [])

    def test_10_clean_explicit_physical_parameters_no_fallback_files(self):
        creator, calls = self.creator()
        with patch("infra.core.worker_db.os.environ", {}): self.assertIsNotNone(creator())
        self.assertEqual(len(calls),1)
        params = calls[0]
        self.assertEqual((params["host"],params["port"],params["user"],params["dbname"]),
                         ("of-core-db",5432,ROLE,DATABASE))
        self.assertEqual((params["sslmode"],params["gssencmode"],params["channel_binding"]),("disable",)*3)
        self.assertEqual(params["passfile"],os.devnull)
        self.assertNotIn("service",params); self.assertNotIn("hostaddr",params)

    def test_11_environment_change_after_lazy_build_blocks_reconnect(self):
        with patch("infra.core.worker_db.os.environ", {}): creator,calls = self.creator(); creator()
        with patch("infra.core.worker_db.os.environ", {"PGHOSTADDR":"SENSITIVE_LATE_DESTINATION"}):
            with self.assertRaises(WorkerDatabaseError): creator()
        self.assertEqual(len(calls),1)
        with patch("infra.core.worker_db.os.environ", {}): creator()
        self.assertEqual(len(calls),2)

    def test_12_environment_policy_does_not_read_values_or_mutate_mapping(self):
        creator,calls = self.creator()
        class NamesOnly(dict):
            def __getitem__(self,key): raise AssertionError("No environment value reads")
            def get(self,*args): raise AssertionError("No environment value reads")
        ambient = NamesOnly(PGSERVICE="SENSITIVE_UNREAD")
        with patch("infra.core.worker_db.os.environ", ambient):
            with self.assertRaises(WorkerDatabaseError): creator()
        self.assertEqual(list(ambient),["PGSERVICE"])
        self.assertEqual(calls,[])


if __name__ == "__main__": unittest.main()
