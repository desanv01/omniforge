"""Explicit local Windows prototype setup. Never prints credential values."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import URL

from services.api.db import engine_for
from services.api.settings import Settings

CONTAINER = "omniforge-rebuild-core-of011"
VOLUME = "omniforge-rebuild-core-of011-pgdata"
IMAGE = "sha256:32ebb7185baf2c9d38f91684417d140c0745aeff5082dfbb62edb330c2af6197"


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def prepare(root):
    if os.name != "nt":
        raise RuntimeError("This bootstrap ACL implementation is Windows-only")
    root = root.resolve()
    source = Path(__file__).resolve().parents[2]
    if root.exists() or source == root or source in root.parents:
        raise RuntimeError("Requires a new private directory outside source")
    names = command(["docker", "ps", "-a", "--format", "{{.Names}}" ]).splitlines()
    volumes = command(["docker", "volume", "ls", "--format", "{{.Name}}" ]).splitlines()
    if CONTAINER in names or VOLUME in volumes:
        raise RuntimeError("Resource already exists; inspect ownership before reuse")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    root.mkdir(parents=True)
    account = command(["whoami"])
    command(["icacls", str(root), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F"])
    password = secrets.token_urlsafe(48)
    (root / "postgres-password").write_text(password, encoding="utf-8")
    (root / "auth-token").write_text(secrets.token_urlsafe(48), encoding="utf-8")
    for name in ("artifacts/staging", "artifacts/blobs"):
        (root / name).mkdir(parents=True)
    settings = {"database_url": URL.create("postgresql+psycopg", username="omniforge_rebuild",
                 password=password, host="127.0.0.1", port=port, database="omniforge_rebuild").render_as_string(hide_password=False),
                "artifact_root": str(root / "artifacts")}
    (root / "config.json").write_text(json.dumps(settings), encoding="utf-8")
    command(["docker", "volume", "create", "--label", "omniforge.owner=OF-011", VOLUME])
    container_id = command(["docker", "run", "-d", "--name", CONTAINER,
        "--label", "omniforge.owner=OF-011", "--restart", "no", "--publish", f"127.0.0.1:{port}:5432",
        "--mount", f"type=volume,src={VOLUME},dst=/var/lib/postgresql/data",
        "--mount", f"type=bind,src={root / 'postgres-password'},dst=/run/secrets/postgres-password,readonly",
        "--env", "POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password",
        "--env", "POSTGRES_USER=omniforge_rebuild", "--env", "POSTGRES_DB=omniforge_rebuild",
        "--health-cmd", "pg_isready -U omniforge_rebuild -d omniforge_rebuild",
        "--health-interval", "2s", "--health-timeout", "2s", "--health-retries", "10", IMAGE])
    receipt = {"owner": "OF-011", "container": CONTAINER, "container_id": container_id,
               "volume": VOLUME, "image": IMAGE, "database": "omniforge_rebuild", "loopback_port": port,
               "state": "created", "credentials": "private files; values omitted"}
    (root / "resource-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))


def seed(root):
    data = json.loads((root / "config.json").read_text(encoding="utf-8"))
    settings = Settings(data["database_url"], Path(data["artifact_root"]))
    value = (root / "auth-token").read_text(encoding="utf-8").strip()
    engine = engine_for(settings)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:id,'local-user',:hash) ON CONFLICT(token_hash) DO NOTHING"),
                     {"id": uuid4(), "hash": hashlib.sha256(value.encode()).hexdigest()})
    engine.dispose()
    print("Local principal seeded; token value withheld")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "seed"])
    parser.add_argument("private_root", type=Path)
    args = parser.parse_args()
    try:
        (prepare if args.action == "prepare" else seed)(args.private_root)
    except Exception:
        # Underlying subprocess/config exceptions can include private values.
        raise SystemExit("Bootstrap failed; inspect named private resources without printing secrets") from None
