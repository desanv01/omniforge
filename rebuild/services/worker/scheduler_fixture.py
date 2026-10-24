"""Harmless scheduler feasibility worker; NOT application Run persistence.

SQLite is only a synthetic publication witness. Real Run/Event/Attempt/outbox and
authorization transactions remain an accepted-core integration dependency.
"""
import asyncio
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import sqlite3

from hatchet_sdk import Context, Hatchet
from hatchet_sdk.config import ClientConfig, ClientTLSConfig, TenacityConfig
from pydantic import BaseModel


def client():
    root = Path(os.environ["OF_SCHEDULER_PRIVATE_ROOT"])
    return Hatchet(config=ClientConfig(
        token=(root / "worker-token").read_text().strip(),
        host_port=os.environ.get("OF_SCHEDULER_GRPC", "127.0.0.1:63152"),
        server_url=os.environ.get("OF_SCHEDULER_HTTP", "http://127.0.0.1:63151"),
        tls_config=ClientTLSConfig(strategy="none"),
        tenacity=TenacityConfig(max_attempts=1),
    ))


def database():
    conn = sqlite3.connect(Path(os.environ["OF_SCHEDULER_PRIVATE_ROOT"]) / "fixture.sqlite", timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def initialize():
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, mode TEXT NOT NULL,
          epoch INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued');
        CREATE TABLE IF NOT EXISTS publications(run_id TEXT PRIMARY KEY, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL, type TEXT NOT NULL, epoch INTEGER NOT NULL);
        """)


def claim(run_id):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row["status"] in ("cancel_requested", "canceled", "succeeded", "failed"):
            raise ValueError("Run does not admit an attempt")
        epoch = row["epoch"] + 1
        db.execute("UPDATE runs SET epoch=?,status='running' WHERE id=?", (epoch, run_id))
        db.execute("INSERT INTO events(run_id,type,epoch) VALUES(?,'claimed',?)", (run_id, epoch))
        return epoch


def publish(run_id, epoch):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row["epoch"] != epoch or row["status"] != "running":
            raise ValueError("Stale or canceled attempt")
        # The fixture's sole output is fixed synthetic bytes; no filesystem/tool/provider effects.
        digest = hashlib.sha256(b"OF-013-A synthetic output\n").hexdigest()
        db.execute("INSERT INTO publications VALUES(?,?) ON CONFLICT(run_id) DO NOTHING", (run_id, digest))
        db.execute("INSERT INTO events(run_id,type,epoch) VALUES(?,'publication_reconciled',?)", (run_id, epoch))


class Input(BaseModel):
    run_id: str
    mode: str


def workflow(hatchet):
    @hatchet.task(name="OmniForgeOF013A", input_validator=Input,
                  retries=1, execution_timeout=timedelta(seconds=120),
                  schedule_timeout=timedelta(seconds=180))
    async def fixture(input: Input, ctx: Context) -> dict[str, str]:
        epoch = claim(input.run_id)
        if input.mode == "fail":
            raise ValueError("Deterministic synthetic failure")
        if input.mode == "cancel":
            while True:
                await asyncio.sleep(0.2)
        publish(input.run_id, epoch)
        if epoch == 1:
            # Deliberate crash window: publication committed, scheduler completion not acknowledged.
            while True:
                await asyncio.sleep(0.2)
        return {"run_id": input.run_id, "publication": "reconciled"}
    return fixture


if __name__ == "__main__":
    initialize()
    hatchet = client()
    hatchet.worker("omniforge-rebuild-scheduler-of013a-worker", slots=2,
                   workflows=[workflow(hatchet)]).start()
