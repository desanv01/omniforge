"""PREPARED, UNEXECUTED actual-role proof. No import-time I/O or CLI.

Only a separately released Backend window may call execute(). The caller supplies
an exclusively owned owner engine, expected cluster identity and NEW secret from
the approved private channel. Nothing discovers credentials, reads/writes config,
starts resources, uses an SDK, or prints exceptions. This is trusted development
code: granted locking columns permit real mutation, with no per-Run SQL isolation.
Owner orchestration stays in this Backend process; only build_worker_engine()'s
fresh nonowner connections exercise receiver seams. Never mount owner credentials
in a receiver. Host resolution of of-core-db:5432 must be released beforehand.
"""
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import re
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException

from infra.core.worker_db import build_worker_engine, validate_worker_startup
from infra.core.worker_settings import DATABASE, MIGRATION, ROLE, WorkerSettings
from services.api.errors import Problem
from services.api.runs import repository as repo
from services.api.runs.contracts import RunCreate
from services.worker import cancellation, delivery
from services.worker.hatchet_contracts import Binding, Observation


RELEASE = "EXECUTE_REVIEWED_B3C_AUTHORITY_PROOF"
TABLES = tuple("principals cases case_grants artifacts artifact_associations idempotency "
    "provider_profile_versions provider_enrollments runs run_events run_outbox run_attempts "
    "run_outputs run_scheduler_executions run_scheduler_submissions run_cancellations "
    "run_cancel_targets run_cancel_receipts".split())
PURPOSES = ("complete", "cleanup_after_grant_revocation", "revoked_grant_admission",
    "changed_input_admission", "wrong_payload_registration", "stale_renewal", "wrong_context_registration")

# Complete SELECT projections frozen at 0008, not ALL TABLES/future-column grants.
SELECT = {
    "alembic_version": "version_num",
    "case_grants": "principal_id case_id can_write",
    "artifacts": "id sha256 bytes",
    "artifact_associations": "id case_id revision artifact_id source_id publication_status",
    "runs": "id case_id requested_by schema_version revision kind status outcome terminal_reason input_refs policy_version scope_snapshot budget usage provider_profile_ref output_refs attempt_id fence next_event_sequence created_at started_at finished_at cancel_requested_at cancellation_id cancel_generation cleanup_status",
    "run_outbox": "id run_id dispatch_key command state payload created_at claim_token claim_until dispatch_count reconcile_count last_error_code scheduler_kind dispatch_generation candidate_ids",
    "run_attempts": "id run_id fence state worker_id lease_expires_at created_at finished_at execution_id worker_instance_id",
    "run_outputs": "id run_id output_key sha256 content attempt_id fence expected_revision created_at",
    "run_scheduler_executions": "id run_id outbox_id scheduler_kind external_id observed_state created_at submission_id native_status task_ids observed_at",
    "run_scheduler_submissions": "id run_id outbox_id generation tenant_id workflow_id workflow_version_id workflow_name namespace input_hash submission_hash dispatch_identity entry_revision created_at recovery_attempt_id recovery_fence recovery_receipt_id recovery_at recovery_roots recovery_proof_hash",
    "run_cancellations": "id run_id case_id requested_by generation request_revision request_snapshot state created_at",
    "run_cancel_targets": "id run_id cancel_id generation execution_id original_attempt_id original_fence worker_instance_id task_ids cleanup_credential_hash command_key command_state cancel_count lookup_count claim_token claim_until last_error_code created_at",
    "run_cancel_receipts": "id run_id cancel_id target_id execution_id generation credential_hash worker_instance_id result receipt_hash task_ids received_at",
}
INSERT = {
    "run_events": "run_id sequence type attempt_id payload",
    "run_attempts": "id run_id fence state worker_id lease_expires_at execution_id worker_instance_id",
    "run_outputs": "id run_id output_key sha256 content attempt_id fence expected_revision",
    "run_scheduler_executions": "id run_id outbox_id scheduler_kind external_id observed_state submission_id native_status task_ids observed_at",
    "run_cancel_targets": "id run_id cancel_id generation execution_id original_attempt_id original_fence worker_instance_id task_ids command_key",
    "run_cancel_receipts": "id run_id cancel_id target_id execution_id generation credential_hash worker_instance_id result receipt_hash task_ids",
}
UPDATE = {
    "case_grants": "can_write", "artifact_associations": "revision", "artifacts": "bytes",
    "runs": "status attempt_id fence revision started_at finished_at terminal_reason usage next_event_sequence outcome output_refs cleanup_status",
    "run_outbox": "state candidate_ids claim_token claim_until last_error_code",
    "run_attempts": "state lease_expires_at finished_at",
    "run_scheduler_executions": "observed_state native_status task_ids observed_at",
    "run_cancellations": "state",
    "run_cancel_targets": "task_ids worker_instance_id cleanup_credential_hash",
}
MATRIX = {"SELECT": SELECT, "INSERT": INSERT, "UPDATE": UPDATE}


class ProofFailure(Exception):
    """Fixed codes only; never format driver exceptions/parameters into evidence."""


class ProofInterrupted(BaseException):
    """Sanitized control propagation carrying the caller-owned private report."""
    def __init__(self, report):
        self.report = report
        super().__init__("Authority proof interrupted; retain private evidence and inspect disposition")


def require(condition, code):
    if not condition:
        raise ProofFailure(code)


def identifier(value):
    require(type(value) is str and re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value), "invalid_identifier")
    return '"' + value + '"'


def grant_sql():
    """Reviewable non-secret SQL; password DDL is separately composed below."""
    statements = [f'GRANT CONNECT ON DATABASE {identifier(DATABASE)} TO {identifier(ROLE)}',
                  f'GRANT USAGE ON SCHEMA public TO {identifier(ROLE)}']
    for privilege, tables in MATRIX.items():
        for table, columns in tables.items():
            names = ",".join(identifier(column) for column in columns.split())
            statements.append(f'GRANT {privilege} ({names}) ON TABLE public.{identifier(table)} TO {identifier(ROLE)}')
    return tuple(statements)


def schema_projection(conn):
    """Catalog structure, including constraints/indexes/functions/triggers; excludes ACLs."""
    queries = (
        "SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum WHERE n.nspname='public' AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum",
        "SELECT c.relname,k.conname,pg_get_constraintdef(k.oid) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,k.conname",
        "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname",
        "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
        "SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind='f' ORDER BY 1",
    )
    return [hashlib.sha256(repo.encode([list(row) for row in conn.execute(text(query))]).encode()).hexdigest()
            for query in queries]


def snapshot(conn):
    # SQL hashes every original column; no sensitive row data crosses the driver.
    # Multisets preserve duplicate projections; counts alone are insufficient.
    return {table: Counter(conn.execute(text(f"SELECT md5(row_to_json(t)::text) FROM public.{identifier(table)} t")).scalars())
            for table in TABLES}


@contextmanager
def owner_transaction(engine):
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL statement_timeout='5000ms'"))
        conn.execute(text("SET LOCAL lock_timeout='1000ms'"))
        conn.execute(text("SET LOCAL idle_in_transaction_session_timeout='5000ms'"))
        yield conn


def guard_owner(conn, expected_owner, expected_cluster):
    require(expected_owner != ROLE, "owner_is_receiver")
    identifier(expected_owner)
    actual = conn.execute(text("SELECT current_database(),current_user,session_user,current_schema(),pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()")).one()
    require(tuple(actual) == (DATABASE, expected_owner, expected_owner, "public", expected_owner), "wrong_owner_database")
    require(str(conn.execute(text("SELECT system_identifier FROM pg_control_system()")).scalar_one()) == expected_cluster, "wrong_cluster")
    require(conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() == [MIGRATION], "wrong_schema")
    require(conn.execute(text("SELECT count(*) FROM pg_roles WHERE rolname=:r"), {"r": ROLE}).scalar_one() == 0, "role_already_exists")
    resources = conn.execute(text("SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p')")).all()
    require({row[0] for row in resources} == set(TABLES) | {"alembic_version"}
            and all(row[1] == expected_owner for row in resources), "unexpected_resource_or_owner")
    require(conn.execute(text("SELECT count(*) FROM pg_attribute WHERE attrelid='public.runs'::regclass AND attname='authority_proof_forbidden_column' AND NOT attisdropped")).scalar_one() == 0, "unexpected_probe_column")


def provision(conn, secret):
    # Direct DBAPI cursor avoids SQLAlchemy statement logging of password DDL.
    # Backend future release must also approve PostgreSQL server log disposition.
    from psycopg import sql
    with conn.connection.driver_connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4 PASSWORD {}").format(sql.Identifier(ROLE), sql.Literal(secret)))
    for statement in grant_sql():
        conn.execute(text(statement))


@dataclass(frozen=True)
class Fixture:
    run_id: UUID
    context: delivery.DeliveryContext
    spec: object
    association_id: UUID


def seed(conn):
    """Exactly seven new additive Runs, one independent authority/input per Run."""
    fixtures = []
    binding = Binding(uuid4(), uuid4(), uuid4(), "authority-proof", "authority-proof")
    for purpose in PURPOSES:
        principal, case, artifact, association, source = (uuid4() for _ in range(5))
        content_hash = hashlib.sha256(("synthetic-authority:" + str(artifact)).encode()).hexdigest()
        conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:id,'synthetic authority proof',:hash)"),
                     {"id": principal, "hash": hashlib.sha256(str(principal).encode()).hexdigest()})
        conn.execute(text("INSERT INTO cases(id,revision,title,objective,policy_profile_ref) VALUES(:id,1,:title,'synthetic metadata only','local-read-only-v1')"), {"id": case, "title": purpose})
        conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,true)"), {"p": principal, "c": case})
        conn.execute(text("INSERT INTO artifacts(id,sha256,bytes) VALUES(:id,:hash,0)"), {"id": artifact, "hash": content_hash})
        conn.execute(text("INSERT INTO artifact_associations(id,case_id,artifact_id,source_id,original_name,media_type,publication_status,stage_name) VALUES(:id,:c,:a,:s,'synthetic.txt','text/plain','committed',:stage)"),
                     {"id": association, "c": case, "a": artifact, "s": source, "stage": "authority-proof-" + str(association)})
        body = RunCreate.model_validate({"input_refs": [{"association_id": association, "revision": 1, "sha256": content_hash}], "budget": {"wall_seconds": 60}})
        run = repo.insert_queued(conn, principal, case, body)
        context = delivery.DeliveryContext(binding, case, principal)
        spec = delivery.configure_delivery(conn, context, run.id, 1)
        fixtures.append(Fixture(run.id, context, spec, association))
    require(len({f.run_id for f in fixtures}) == 7, "fixture_bound")
    return tuple(fixtures)


def effective_privileges(conn):
    require(conn.execute(text("SELECT has_database_privilege(current_user,current_database(),'CREATE')")).scalar_one() is False, "unexpected_database_create")
    columns = conn.execute(text("SELECT c.relname,a.attname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid WHERE n.nspname='public' AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum")).all()
    checked = 0
    for table, column in columns:
        for privilege, matrix in MATRIX.items():
            actual = conn.execute(text("SELECT has_column_privilege(current_user,:t,:c,:p)"),
                {"t": "public." + table, "c": column, "p": privilege}).scalar_one()
            require(actual == (column in matrix.get(table, "").split()), "effective_column_privilege_mismatch")
            checked += 1
    for table in (*TABLES, "alembic_version"):
        for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            require(conn.execute(text("SELECT has_table_privilege(current_user,:t,:p)"),
                {"t": "public." + table, "p": privilege}).scalar_one() is False, "unexpected_table_privilege")
        require(conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=CAST(:t AS regclass) AND attnum>0 AND NOT attisdropped AND has_column_privilege(current_user,attrelid,attnum,'REFERENCES'))"),
                {"t": "public." + table}).scalar_one() is False, "unexpected_column_references")
    # Catalog metadata only: report inherited/default grants; never revoke PUBLIC.
    functions = [dict(row) for row in conn.execute(text("SELECT n.nspname AS schema,p.oid::regprocedure::text AS function,p.prosecdef AS security_definer,has_function_privilege(current_user,p.oid,'EXECUTE') AS executable,coalesce(p.proacl,acldefault('f',p.proowner))::text AS effective_acl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' ORDER BY 2")).mappings()]
    defaults = [dict(row) for row in conn.execute(text("SELECT pg_get_userbyid(defaclrole) AS owner,defaclnamespace::regnamespace::text AS schema,defaclobjtype AS kind,defaclacl::text AS acl FROM pg_default_acl ORDER BY 1,2,3")).mappings()]
    public = [dict(row) for row in conn.execute(text("SELECT 'database' AS resource,datacl::text AS acl FROM pg_database WHERE datname=current_database() UNION ALL SELECT 'public_schema',nspacl::text FROM pg_namespace WHERE nspname='public'")).mappings()]
    other_functions = [dict(row) for row in conn.execute(text("SELECT n.nspname AS schema,count(*) AS executable_functions,count(*) FILTER(WHERE p.prosecdef) AS executable_security_definers FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname<>'public' AND has_function_privilege(current_user,p.oid,'EXECUTE') GROUP BY n.nspname ORDER BY 1")).mappings()]
    require(not any(f["security_definer"] and f["executable"] for f in functions), "unexpected_public_security_definer")
    return {"column_checks": checked, "public_functions": functions, "other_executable_function_counts": other_functions,
            "default_acls": defaults, "resource_acls": public, "database_create": False}


def denied_sql(engine, statement):
    # Every probe rolls back even if privileges unexpectedly permit it. DML has
    # WHERE false; no old rows are read/changed. Never use TRUNCATE as a probe.
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text(statement))
        except DBAPIError as exc:
            require(getattr(exc.orig, "sqlstate", None) == "42501", "unexpected_denial_sqlstate")
        else:
            raise ProofFailure("expected_sql_denial_missing")
        finally:
            tx.rollback()


def denied_domain(engine, callback, status):
    try:
        with engine.begin() as conn:
            callback(conn)
            raise ProofFailure("expected_domain_denial_missing")
    except (Problem, HTTPException) as exc:
        require(getattr(exc, "status", getattr(exc, "status_code", None)) == status, "wrong_domain_denial")


def receiver_checks(owner, worker, settings, fixtures):
    checks = []
    for index, fixture in enumerate(fixtures):
        settings.require_run(fixture.run_id)
        context, spec = fixture.context, fixture.spec
        observed, instance = Observation(uuid4(), (uuid4(),), "RUNNING"), uuid4()
        if index in (4, 6):
            bad_context = delivery.DeliveryContext(context.binding, uuid4(), context.principal_id) if index == 6 else context
            payload = {**spec.payload(), "input_hash": "0" * 64} if index == 4 else spec.payload()
            denied_domain(worker, lambda c: delivery.register_delivery(c, bad_context, spec, observed,
                payload, "authority-proof", instance, 1, 60), 409)
        with worker.begin() as conn:
            receipt = delivery.register_delivery(conn, context, spec, observed, spec.payload(), "authority-proof", instance, 1, 60)
            require(receipt.token is not None, "registration_did_not_claim")
            # Actual successful metadata input/FOR SHARE queries on all three
            # tables, not privilege assertions or simulated SQL permissions.
            require(len(repo.admit_work(conn, receipt.token, receipt.token.revision)) == 1, "input_lock_missing")
        token = receipt.token
        if index == 1:
            with owner_transaction(owner) as conn:
                cancellation.request_cancellation(conn, repo.locked_run(conn, fixture.run_id), context.principal_id)
                conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"), {"p": context.principal_id, "c": context.case_id})
            denied_domain(worker, lambda c: repo.admit_work(c, token, token.revision), 409)
            with worker.begin() as conn:
                credential = cancellation.issue_cleanup(conn, context, fixture.run_id, receipt.execution_id, token.attempt_id, instance)
                require(credential is not None, "cleanup_credential_missing")
                cancellation.record_cleanup(conn, context, credential, uuid4(), "succeeded")
                require(repo.locked_run(conn, fixture.run_id)["status"] == "canceled", "cleanup_not_settled")
        else:
            if index in (2, 3):
                with owner_transaction(owner) as conn:
                    if index == 2:
                        conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"), {"p": context.principal_id, "c": context.case_id})
                    else:
                        conn.execute(text("UPDATE artifact_associations SET revision=2 WHERE id=:id"), {"id": fixture.association_id})
                denied_domain(worker, lambda c: repo.admit_work(c, token, token.revision), 403 if index == 2 else 409)
                with owner_transaction(owner) as conn:
                    if index == 2:
                        conn.execute(text("UPDATE case_grants SET can_write=true WHERE principal_id=:p AND case_id=:c"), {"p": context.principal_id, "c": context.case_id})
                    else:
                        conn.execute(text("UPDATE artifact_associations SET revision=1 WHERE id=:id"), {"id": fixture.association_id})
            if index == 5:
                denied_domain(worker, lambda c: repo.renew_attempt(c, token, token.revision + 1, 60), 409)
            with worker.begin() as conn:
                renewed = repo.renew_attempt(conn, token, token.revision, 60)
            with worker.begin() as conn:
                result = repo.complete_attempt(conn, renewed, renewed.revision, "result", {"value": "synthetic authority proof"})
                require(result.status == "succeeded", "completion_not_settled")
        checks.append({"run_id": str(fixture.run_id), "purpose": PURPOSES[index], "status": "passed"})
    return checks


def execute(*, owner_engine, expected_owner, expected_cluster, new_secret, release, evidence):
    """Future explicit call; returns private, sanitized evidence, never writes it.

    Caller transfers exclusive ownership of the engine (hide_parameters=True,
    echo=False, bounded connect/statement timeouts). Caller supplies an empty plain
    evidence dict and persists it privately in its own finally, on return OR any
    BaseException; never print tracebacks/locals. ProofInterrupted propagates control
    with this same sanitized dict after independent settlement attempts. No retries.
    Caller separately records actual
    container/volume/topology verification and PostgreSQL password-log controls.
    Confirmed-created role disable is attempted independently; uncertain creation
    is retained for Main inspection, never automatically altered/retried. Fresh
    fixture/history is never deleted. Caller owns secret retirement/receipt storage.
    Hard process termination cannot run Python settlement: the caller's outer
    runtime controller must preserve/inspect unresolved resources in that case.
    """
    require(type(evidence) is dict and not evidence, "empty_caller_evidence_required")
    report = evidence
    report.update({"status": "failed", "native_execution": "unproved_injected_observations_only",
              "role": ROLE, "config": "not_created_by_proof; caller must retire supplied secret",
              "role_disposition": "not_created", "baseline_preserved": None, "schema_preserved": None,
              "runs": [], "failure_stages": [], "control_interrupted": False,
              "receiver_pool_disposition": "not_constructed", "owner_pool_disposition": "not_attempted",
              "provisioning_commit": "not_attempted", "role_disable_commit": "not_attempted"})
    interrupted = False

    def failed(stage, exc):
        nonlocal interrupted
        # No exception value, traceback, DSN, SQL parameters or secret is retained.
        control = not isinstance(exc, Exception)
        interrupted = interrupted or control
        report["control_interrupted"] = interrupted
        report["status"] = "interrupted" if interrupted else "failed"
        report["failure_stages"].append({"stage": stage, "kind": "control_interruption" if control else "operation_failed"})

    created, baseline, schema, worker = False, None, None, None
    try:
        require(release == RELEASE, "execution_not_released")
        require(type(expected_cluster) is str and expected_cluster.isdecimal(), "explicit_cluster_required")
        # Validate secret primitives before any SQL, without generating/logging one.
        provisional = tuple(uuid4() for _ in range(7))
        url = URL.create("postgresql+psycopg", username=ROLE, password=new_secret,
                         host="of-core-db", port=5432, database=DATABASE).render_as_string(hide_password=False)
        WorkerSettings(1, url, provisional)
        require(owner_engine.echo is False and owner_engine.hide_parameters is True, "unsafe_owner_logging")
        with owner_transaction(owner_engine) as conn:
            guard_owner(conn, expected_owner, expected_cluster)
            baseline, schema = snapshot(conn), schema_projection(conn)
            report["baseline18"] = {table: {"count": sum(old.values()), "projection_multiset": dict(old)} for table, old in baseline.items()}
            report["role_disposition"] = "creation_transaction_unconfirmed_requires_inspection_on_failure"
            report["provisioning_commit"] = "unconfirmed_requires_Main_inspection"
            provision(conn, new_secret)
            fixtures = seed(conn)
            # Record identities before commit so an uncertain commit still leaves
            # the exact bounded ledger for inspection; never retry automatically.
            report["runs"] = [{"run_id": str(f.run_id), "purpose": purpose} for f, purpose in zip(fixtures, PURPOSES)]
        created = True
        report["provisioning_commit"] = "confirmed"
        report["role_disposition"] = "created_LOGIN_pending_final_disable"
        settings = WorkerSettings(1, url, tuple(f.run_id for f in fixtures))
        report["receiver_pool_disposition"] = "construction_unconfirmed"
        worker = build_worker_engine(settings)
        report["receiver_pool_disposition"] = "constructed_pending_settlement"
        startup = validate_worker_startup(worker, settings)
        report["startup"] = {"role": startup.role, "database": startup.database,
                             "migration": startup.migration, "temporary_allowed": startup.temporary_allowed,
                             "authority": startup.authority}
        with worker.connect() as conn:
            report["privileges"] = effective_privileges(conn)
        probes = [f"SELECT {column} FROM public.{identifier(table)} WHERE false" for table, column in (
            ("principals", "token_hash"), ("cases", "objective"), ("idempotency", "response"),
            ("provider_profile_versions", "profile_id"), ("provider_enrollments", "operation_id"), ("artifact_associations", "original_name"))]
        probes += ["UPDATE public.runs SET kind=kind WHERE false", "UPDATE public.case_grants SET principal_id=principal_id WHERE false",
                   "DELETE FROM public.runs WHERE false", "INSERT INTO public.runs(id) SELECT NULL::uuid WHERE false",
                   "CREATE TABLE public.authority_proof_forbidden_ddl (id integer)",
                   "ALTER TABLE public.runs ADD COLUMN authority_proof_forbidden_column integer",
                   "SET LOCAL ROLE " + identifier(expected_owner)]
        for probe in probes:
            denied_sql(worker, probe)
        report["sql_denials"] = len(probes)
        report["receiver_checks"] = receiver_checks(owner_engine, worker, settings, fixtures)
        report["status"] = "passed_pending_settlement"
    except BaseException as exc:
        failed("proof_body", exc)
    finally:
        if worker is not None:
            try:
                report["receiver_checked_out"] = worker.pool.checkedout()
                require(report["receiver_checked_out"] == 0, "receiver_connections_unsettled")
            except BaseException as exc:
                failed("receiver_connection_check", exc)
            try:
                report["receiver_pool_disposition"] = "disposal_unconfirmed"
                worker.dispose()
                report["receiver_pool_disposition"] = "disposed_not_a_physical_connection_stop_claim"
            except BaseException as exc:
                failed("receiver_pool_disposal", exc)
        if created:
            try:
                report["role_disposition"] = "disable_transaction_unconfirmed_requires_Main_action"
                report["role_disable_commit"] = "unconfirmed_requires_Main_inspection"
                with owner_transaction(owner_engine) as conn:
                    conn.execute(text("ALTER ROLE " + identifier(ROLE) + " NOLOGIN"))
                    require(conn.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname=:r"), {"r": ROLE}).scalar_one() is False, "role_disable_unverified")
                report["role_disposition"] = "retained_NOLOGIN_with_grants_and_history"
                report["role_disable_commit"] = "confirmed"
            except BaseException as exc:
                failed("role_disable", exc)
        if baseline is not None:
            try:
                with owner_transaction(owner_engine) as conn:
                    current = snapshot(conn)
                    report["baseline_preserved"] = all(not (old - current[table]) for table, old in baseline.items())
                    report["baseline18"] = {table: {"count": sum(old.values()), "projection_multiset": dict(old)} for table, old in baseline.items()}
                    report["schema_preserved"] = schema_projection(conn) == schema
                require(report["baseline_preserved"] and report["schema_preserved"], "preservation_failed")
            except BaseException as exc:
                failed("preservation_verification", exc)
                report["preservation_verification"] = "failed_requires_Main_action"
        try:
            report["owner_checked_out"] = owner_engine.pool.checkedout()
            require(report["owner_checked_out"] == 0, "owner_connections_unsettled")
        except BaseException as exc:
            failed("owner_connection_check", exc)
        try:
            report["owner_pool_disposition"] = "disposal_unconfirmed"
            owner_engine.dispose()
            report["owner_pool_disposition"] = "disposed_not_a_physical_connection_stop_claim"
        except BaseException as exc:
            failed("owner_pool_disposal", exc)
        if report["status"] == "passed_pending_settlement":
            report["status"] = "passed"
    if interrupted:
        raise ProofInterrupted(report) from None
    return report
