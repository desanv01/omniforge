"""Bounded real Hatchet interruption fixture. No accepted-core integration claim."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from infra.scheduler.runtime import LITE, NETWORK, PREFIX, owned, docker
from services.worker.scheduler_fixture import client, database, initialize, publish, workflow, Input
from hatchet_sdk.clients.rest.exceptions import NotFoundException


ROOT = Path(os.environ["OF_SCHEDULER_PRIVATE_ROOT"]).resolve()


def wait(check, seconds, label):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = check()
        except NotFoundException:
            # Hatchet status reads may lag accepted dispatch; never repeat the dispatch.
            value = False
        if value:
            return value
        time.sleep(0.5)
    raise RuntimeError("Deadline: " + label)


def row(run):
    with database() as db:
        return dict(db.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone())


def add(mode):
    run = str(uuid.uuid4())
    with database() as db:
        db.execute("INSERT INTO runs(id,mode) VALUES(?,?)", (run, mode))
    return run


def terminal(run, state):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if state == "succeeded":
            assert db.execute("SELECT 1 FROM publications WHERE run_id=?", (run,)).fetchone()
        db.execute("UPDATE runs SET status=? WHERE id=?", (state, run))
        db.execute("INSERT INTO events(run_id,type,epoch) SELECT id,?,epoch FROM runs WHERE id=?", (state, run))


def main():
    initialize()
    h = client()
    task = workflow(h)
    # Register the definition without starting a polling worker, proving queued persistence.
    h._client.admin.put_workflow(task.to_proto())
    log = (ROOT / "worker.log").open("ab")
    processes = []
    result = {"scope": "standalone scheduler plus synthetic publication witness; core integration pending"}
    def start():
        name = PREFIX + "-worker-" + str(len(processes) + 1)
        if name in docker("ps", "-a", "--format", "{{.Names}}").splitlines():
            raise RuntimeError("Worker name already exists")
        docker("run", "-d", "--name", name, "--label", "omniforge.owner=OF-013-A",
               "--network", NETWORK, "--restart", "no", "--memory", "512m", "--cpus", "1",
               "--mount", f"type=bind,src={ROOT},dst=/proof",
               "--mount", f"type=bind,src={Path('services/worker').resolve()},dst=/app/services/worker,readonly",
               "--env", "OF_SCHEDULER_PRIVATE_ROOT=/proof",
               "--env", f"OF_SCHEDULER_GRPC={LITE}:7077",
               "--env", f"OF_SCHEDULER_HTTP=http://{LITE}:8888",
               "omniforge-rebuild-scheduler-of013a-worker:locked")
        processes.append(name)
        return name
    try:
        recovery = add("recover")
        ref = task.run(Input(run_id=recovery, mode="recover"), wait_for_result=False)
        scheduler_id = str(ref.workflow_run_id)
        result["recovery_id"] = scheduler_id
        assert row(recovery)["epoch"] == 0
        result["queued_before_worker"] = True
        first = start()
        wait(lambda: row(recovery)["epoch"] == 1, 50, "first claim")
        wait(lambda: publication_count(recovery) == 1, 15, "first publication")
        owned(first)
        docker("kill", first)
        result["worker_killed_after_publication_before_ack"] = True
        owned(LITE)
        subprocess.run(["docker", "restart", "--timeout", "5", LITE], check=True, capture_output=True)
        result["engine_restarted"] = True
        # Allow one bounded service-readiness window; task retry policy stays fixed.
        time.sleep(4)
        start()
        wait(lambda: row(recovery)["epoch"] >= 2, 150, "reassigned attempt")
        wait(lambda: str(h.runs.get_status(scheduler_id).value) == "COMPLETED", 35, "scheduler recovery terminal")
        terminal(recovery, "succeeded")
        assert publication_count(recovery) == 1
        try:
            publish(recovery, 1)
        except ValueError:
            result["stale_attempt_rejected"] = True
        else:
            raise AssertionError("Stale publication admitted")
        result["publication_count"] = 1
        result["recovery_attempts"] = row(recovery)["epoch"]
        cancel = add("cancel")
        cref = task.run(Input(run_id=cancel, mode="cancel"), wait_for_result=False)
        wait(lambda: row(cancel)["epoch"] > 0, 30, "cancel claim")
        with database() as db:
            db.execute("UPDATE runs SET status='cancel_requested' WHERE id=?", (cancel,))
        h.runs.cancel(str(cref.workflow_run_id))
        h.runs.cancel(str(cref.workflow_run_id))
        wait(lambda: h.runs.get_status(str(cref.workflow_run_id)).value == "CANCELLED", 35, "cancel terminal")
        try:
            publish(cancel, row(cancel)["epoch"])
        except ValueError:
            result["cancel_blocks_publication"] = True
        else:
            raise AssertionError("Canceled publication admitted")
        terminal(cancel, "canceled")
        result["cancel_status"] = "CANCELLED"
        failure = add("fail")
        fref = task.run(Input(run_id=failure, mode="fail"), wait_for_result=False)
        result["failure_id"] = str(fref.workflow_run_id)
        wait(lambda: h.runs.get_status(str(fref.workflow_run_id)).value == "FAILED", 50, "failure terminal")
        terminal(failure, "failed")
        result["failure_status"] = "FAILED"
        result["failure_attempts"] = row(failure)["epoch"]
        result["passed"] = True
    except Exception as exc:
        result["passed"] = False
        result["failure_type"] = type(exc).__name__
        # Fixed labels only: SDK exceptions can contain credentials or local diagnostics.
        if isinstance(exc, RuntimeError) and str(exc).startswith("Deadline:"):
            result["failure_stage"] = str(exc)
        raise
    finally:
        for name in processes:
            owned(name)
            raw = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
            (ROOT / (name + ".log")).write_text(raw.stdout + raw.stderr)
            docker("stop", "--timeout", "10", name)
        log.close()
        (ROOT / "fixture-result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))


def publication_count(run):
    with database() as db:
        return db.execute("SELECT count(*) FROM publications WHERE run_id=?", (run,)).fetchone()[0]


def cli():
    try:
        main()
    except Exception:
        print("Scheduler fixture failed; inspect the private result receipt.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
