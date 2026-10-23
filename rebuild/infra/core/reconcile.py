"""Explicit bounded, non-deleting publication recovery."""
import argparse
import json
from services.api.db import engine_for
from services.api.evidence import reconcile
from services.api.settings import Settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    settings = Settings.from_env()
    if settings is None:
        raise SystemExit("OMNIFORGE_CONFIG required")
    engine = engine_for(settings)
    print(json.dumps(reconcile(engine, settings.artifact_root, args.limit)))
    engine.dispose()
