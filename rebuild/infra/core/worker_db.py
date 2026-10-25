"""Bounded nonowner construction and explicit startup checks, no discovery."""
from dataclasses import dataclass
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from infra.core.worker_settings import DATABASE, MIGRATION, ROLE, WorkerSettings

APPLICATION = "omniforge-b3c-receiver-v1"


class WorkerDatabaseError(Exception):
    def __init__(self):
        super().__init__("Worker database initialization unavailable")


IDENTITY_SQL = """SELECT current_database() AS database_name,current_user AS current_name,
session_user AS session_name,current_schema() AS schema_name,
pg_get_userbyid(d.datdba) AS database_owner,
r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,r.rolinherit,
EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) AS has_memberships
FROM pg_roles r JOIN pg_database d ON d.datname=current_database() WHERE r.rolname=current_user"""

PRIVILEGE_SQL = """SELECT
has_schema_privilege(current_user,'public','CREATE') AS schema_create,
has_any_column_privilege(current_user,'public.principals','SELECT') AS principal_read,
has_any_column_privilege(current_user,'public.cases','SELECT') AS case_read,
has_any_column_privilege(current_user,'public.idempotency','SELECT') AS idempotency_read,
has_any_column_privilege(current_user,'public.provider_profile_versions','SELECT') AS profile_read,
has_any_column_privilege(current_user,'public.provider_enrollments','SELECT') AS enrollment_read,
has_column_privilege(current_user,'public.case_grants','can_write','UPDATE') AS grant_lock_update,
has_column_privilege(current_user,'public.artifact_associations','revision','UPDATE') AS association_lock_update,
has_column_privilege(current_user,'public.artifacts','bytes','UPDATE') AS artifact_lock_update,
has_database_privilege(current_user,current_database(),'TEMP') AS temporary_allowed"""


@dataclass(frozen=True)
class WorkerStartup:
    role: str
    database: str
    migration: str
    temporary_allowed: bool
    authority: str = "trusted development; locking columns permit actual mutation; no per-Run SQL isolation"


def _dispose(engine):
    try:
        engine.dispose()
    except Exception:
        pass


def build_worker_engine(settings, *, constructor=None, connector=None):
    """Lazy pool construction only. No migration, probe or fallback is performed."""
    engine = None
    try:
        if type(settings) is not WorkerSettings:
            raise ValueError()
        # Frozen dataclasses can be bypassed by caller code: revalidate primitives.
        WorkerSettings(settings.schema_version, settings.database_url, settings.allowed_run_ids)
        url = make_url(settings.database_url)
        parameters = dict(host=url.host, port=url.port, dbname=url.database, user=url.username,
            password=url.password, connect_timeout=3, application_name=APPLICATION,
            options="-c statement_timeout=5000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=5000",
            sslmode="disable", gssencmode="disable", channel_binding="disable", passfile=os.devnull)
        def physical_connect():
            try:
                # Inspect names only, never environment values. This executes on
                # EVERY physical checkout/reconnect, not just lazy construction.
                if any(name.upper().startswith("PG") for name in os.environ):
                    raise WorkerDatabaseError()
                driver = connector
                if driver is None:
                    from psycopg import connect
                    driver = connect
                return driver(**parameters)
            except Exception:
                raise WorkerDatabaseError() from None
        factory = constructor if constructor is not None else create_engine
        engine = factory(settings.database_url, pool_size=2, max_overflow=0, pool_timeout=1,
            pool_pre_ping=False, hide_parameters=True, creator=physical_connect,
            connect_args={"connect_timeout": 3, "application_name": APPLICATION,
                          "options": "-c statement_timeout=5000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=5000"})
        return engine
    except Exception:
        if engine is not None:
            _dispose(engine)
        raise WorkerDatabaseError() from None


def validate_worker_startup(engine, settings):
    """Invoke explicitly against the future new role; offline tests use fakes only.

    This identity/denial check does not replace actual complete GRANT matrix and
    PUBLIC/default privilege verification in the separately authorized role proof.
    """
    try:
        if type(settings) is not WorkerSettings:
            raise ValueError()
        WorkerSettings(settings.schema_version, settings.database_url, settings.allowed_run_ids)
        with engine.connect() as conn:
            identity = conn.execute(text(IDENTITY_SQL)).mappings().one()
            if (identity["database_name"] != DATABASE or identity["current_name"] != ROLE or
                identity["session_name"] != ROLE or identity["database_owner"] == ROLE or
                identity["schema_name"] != "public" or any(identity[key] is not False for key in
                  ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls", "rolinherit", "has_memberships"))):
                raise ValueError()
            version = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            if version != MIGRATION:
                raise ValueError()
            privileges = conn.execute(text(PRIVILEGE_SQL)).mappings().one()
            if any(privileges[key] is not False for key in ("schema_create", "principal_read", "case_read",
                     "idempotency_read", "profile_read", "enrollment_read")):
                raise ValueError()
            if any(privileges[key] is not True for key in ("grant_lock_update", "association_lock_update", "artifact_lock_update")):
                raise ValueError()
            if type(privileges["temporary_allowed"]) is not bool:
                raise ValueError()
        return WorkerStartup(ROLE, DATABASE, MIGRATION, privileges["temporary_allowed"])
    except Exception:
        _dispose(engine)
        raise WorkerDatabaseError() from None
