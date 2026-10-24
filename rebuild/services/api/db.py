"""Bounded PostgreSQL engine and transaction primitives."""
import hashlib
import json

from sqlalchemy import create_engine, text

MIGRATION = "0002_capture"


def engine_for(settings):
    return create_engine(settings.database_url, pool_size=5, max_overflow=3,
                         pool_pre_ping=True, hide_parameters=True,
                         connect_args={"connect_timeout": 3,
                                       "options": "-c statement_timeout=5000 -c lock_timeout=5000"})


def lock(conn, namespace):
    value = int.from_bytes(hashlib.sha256(namespace.encode()).digest()[:8], "big", signed=True)
    conn.execute(text("SELECT pg_advisory_xact_lock(:value)"), {"value": value})


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def migration_at(conn):
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
