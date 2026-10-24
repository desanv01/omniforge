"""Reconcile the original finite proof after a lagging REST read, no redispatch."""
import json
import os
from pathlib import Path

from services.worker.scheduler_fixture import client, database, claim, publish
from tests.integration.scheduler.check import add, terminal, row, publication_count


def main():
    root = Path(os.environ["OF_SCHEDULER_PRIVATE_ROOT"])
    original = json.loads((root / "fixture-result.json").read_text())
    assert original["recovery_attempts"] == 2 and original["publication_count"] == 1
    assert original["cancel_status"] == "CANCELLED"
    assert original["failure_type"] == "NotFoundException"
    h = client()
    summaries = h.runs.list(limit=10).model_dump(mode="json")["rows"]
    expected = {"recover": "COMPLETED", "cancel": "CANCELLED", "fail": "FAILED"}
    receipt = {"redispatched": False, "scheduler_states": {}}
    for mode, state in expected.items():
        with database() as db:
            local = db.execute("SELECT id,epoch FROM runs WHERE mode=?", (mode,)).fetchall()
        assert len(local) == 1
        run, epoch = local[0]
        matches = [s for s in summaries if s["input"]["input"]["run_id"] == run]
        assert len(matches) == 1 and matches[0]["status"] == state
        scheduler_id = matches[0]["workflow_run_external_id"]
        assert h.runs.get_status(scheduler_id).value == state
        receipt["scheduler_states"][mode] = state
        if mode == "fail":
            terminal(run, "failed")
            receipt["failed_attempts"] = epoch
            assert publication_count(run) == 0
        if mode == "recover":
            assert publication_count(run) == 1 and row(run)["status"] == "succeeded"
    # Isolate token rejection from terminal-state rejection in the synthetic witness.
    fence = add("fence-only")
    assert claim(fence) == 1 and claim(fence) == 2
    try:
        publish(fence, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("Stale token admitted while current attempt running")
    assert publication_count(fence) == 0
    publish(fence, 2)
    terminal(fence, "succeeded")
    receipt["synthetic_running_fence_rejected"] = True
    receipt["passed"] = True
    (root / "reconciliation-result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


def cli():
    try:
        main()
    except Exception:
        print("Scheduler reconciliation failed; private evidence retained.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
