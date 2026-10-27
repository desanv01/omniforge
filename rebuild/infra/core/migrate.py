"""Staged forward-only targets; no argument pins 0008, never implicit head."""
import argparse
from pathlib import Path

STABLE = "0008_run_cancellation"
JOURNAL = "0009_provider_diagnostics"
TARGETS = (STABLE, JOURNAL)
HISTORY = ("0001_core", "0002_capture", "0003_runs", "0004_run_execution",
           "0005_provider_profiles", "0006_profile_bindings", "0007_run_delivery", STABLE, JOURNAL)


def current_revision():
    from sqlalchemy import inspect, text
    from services.api.db import engine_for
    from services.api.settings import Settings
    settings = Settings.from_env()
    if settings is None:
        raise RuntimeError("Explicit migration configuration required")
    engine = engine_for(settings)
    try:
        with engine.connect() as conn:
            if not inspect(conn).has_table("alembic_version"):
                return None
            versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if len(versions) > 1:
                raise RuntimeError("Ambiguous migration state")
            return versions[0] if versions else None
    finally:
        engine.dispose()


def upgrade(target=STABLE, *, read_current=None, apply=None):
    if type(target) is not str or target not in TARGETS:
        raise ValueError("Unsupported staged migration target")
    # Validate before configuration/connection/migration I/O. A future unrecognized
    # revision is not silently downgraded or called a successful no-op.
    current = (read_current or current_revision)()
    if current is not None and (current not in HISTORY or HISTORY.index(current) > HISTORY.index(target)):
        raise RuntimeError("Database is ahead of staged target or unknown")
    if apply is None:
        from alembic import command
        from alembic.config import Config
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
        command.upgrade(config, target)
    else:
        apply(target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, default=STABLE)
    args = parser.parse_args(argv)
    upgrade(args.target)
    print("Staged migration upgrade completed")


if __name__ == "__main__":
    main()
