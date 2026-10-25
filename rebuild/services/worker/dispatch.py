"""Explicit allowlisted B2 outbox driver with a fake scheduler port.

No CLI/background scanner or network adapter. Network-like port calls occur only
after reservation commit. Uncertain acknowledgements must reconcile first.
"""
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text

from services.api.db import digest
from services.api.errors import Problem
from services.api.runs import repository
from services.worker.scheduler_port import AcknowledgementLost, DispatchCommand, Execution, Reconciliation


@dataclass(frozen=True)
class Reservation:
    run_id: UUID
    outbox_id: UUID
    token: UUID
    operation: str
    command: DispatchCommand


class Dispatcher:
    def __init__(self, engine, port, allowed_run_ids):
        ids = frozenset(allowed_run_ids)
        if not ids or len(ids) > 32 or any(type(value) is not UUID for value in ids):
            raise ValueError("Explicit bounded UUID allowlist required")
        self.engine, self.port, self.allowed_run_ids = engine, port, ids

    def reserve(self, run_id):
        if run_id not in self.allowed_run_ids:
            raise ValueError("Run is outside explicit dispatch allowlist")
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM runs WHERE id=:id FOR UPDATE SKIP LOCKED"),
                               {"id": run_id}).mappings().one_or_none()
            if row is None or row["status"] != "queued":
                return None
            row = dict(row)
            repository.work_authority(conn, row)
            intent = conn.execute(text("""SELECT *,claim_until>clock_timestamp() AS claim_live
                FROM run_outbox WHERE run_id=:r AND command='start' FOR UPDATE SKIP LOCKED"""),
                {"r": run_id}).mappings().one_or_none()
            if intent is None or intent["scheduler_kind"] != "fake-v1" or intent["state"] in ("suppressed", "acknowledged"):
                return None
            if intent["state"] == "claimed" and intent["claim_live"]:
                return None
            operation = "submit" if intent["state"] == "pending" else "reconcile"
            counter = "dispatch_count" if operation == "submit" else "reconcile_count"
            if intent[counter] >= 2:
                conn.execute(text("""UPDATE run_outbox SET state='reconcile_required',
                    claim_token=NULL,claim_until=NULL,last_error_code=:code WHERE id=:id"""),
                    {"id": intent["id"], "code": "dispatch_limit" if operation == "submit" else "reconcile_limit"})
                return None
            token = uuid4()
            conn.execute(text(f"""UPDATE run_outbox SET state='claimed',claim_token=:token,
                claim_until=clock_timestamp()+interval '1 second',{counter}={counter}+1
                WHERE id=:id"""), {"token": token, "id": intent["id"]})
            return Reservation(run_id, intent["id"], token, operation,
                DispatchCommand(intent["dispatch_key"], run_id, digest(row["input_refs"])))

    def _finish(self, reserved, executions=(), *, next_state="reconcile_required", error=None):
        # All mutators lock Run then outbox, matching queued cancellation.
        with self.engine.begin() as conn:
            row = repository.locked_run(conn, reserved.run_id)
            intent = conn.execute(text("SELECT * FROM run_outbox WHERE id=:id FOR UPDATE"),
                                  {"id": reserved.outbox_id}).mappings().one()
            if intent["claim_token"] != reserved.token or intent["state"] != "claimed":
                return "stale_ack"
            if row["status"] != "queued" and row["cancellation_id"] is None:
                return "stale_run"
            if row["cancellation_id"] is None:
                repository.work_authority(conn, row)
            else:
                from services.worker import cancellation
                cancellation.current(conn, row)
            for execution in executions:
                if (not isinstance(execution, Execution) or not 1 <= len(execution.external_id) <= 100
                    or execution.state not in ("accepted", "completed")):
                    raise Problem(409, "invalid_scheduler_observation", "conflict", "Scheduler observation invalid")
                existing = conn.execute(text("""SELECT run_id,outbox_id FROM run_scheduler_executions
                    WHERE scheduler_kind='fake-v1' AND external_id=:id"""),
                    {"id": execution.external_id}).one_or_none()
                if existing is not None and (existing.run_id != reserved.run_id or existing.outbox_id != reserved.outbox_id):
                    raise Problem(409, "scheduler_mapping_conflict", "conflict", "Scheduler execution maps to another run")
                mapped = conn.execute(text("""INSERT INTO run_scheduler_executions
                    (id,run_id,outbox_id,scheduler_kind,external_id,observed_state)
                    VALUES(:id,:r,:o,'fake-v1',:external,:state)
                    ON CONFLICT(scheduler_kind,external_id) DO UPDATE
                    SET observed_state=EXCLUDED.observed_state
                    WHERE run_scheduler_executions.run_id=EXCLUDED.run_id
                    AND run_scheduler_executions.outbox_id=EXCLUDED.outbox_id
                    RETURNING run_id"""),
                    {"id": uuid4(), "r": reserved.run_id, "o": reserved.outbox_id,
                     "external": execution.external_id, "state": execution.state}).scalar_one_or_none()
                if mapped != reserved.run_id:
                    raise Problem(409, "scheduler_mapping_conflict", "conflict", "Scheduler execution maps to another run")
            if row["cancellation_id"] is not None and next_state == "pending":
                next_state = "reconcile_required"
            conn.execute(text("""UPDATE run_outbox SET state=:state,claim_token=NULL,
                claim_until=NULL,last_error_code=:error WHERE id=:id"""),
                {"state": next_state, "error": error, "id": reserved.outbox_id})
            if row["cancellation_id"] is not None:
                cancellation.sync_targets(conn, row)
            return next_state

    def tick(self, run_id):
        reserved = self.reserve(run_id)
        if reserved is None:
            return "not_eligible"
        try:
            if reserved.operation == "submit":
                execution = self.port.submit(reserved.command)
                return self._finish(reserved, (execution,), next_state="acknowledged")
            observed = self.port.lookup(reserved.command)
            if not isinstance(observed, Reconciliation) or len(observed.executions) > 2:
                raise ValueError("Invalid bounded reconciliation")
            if observed.state == "found" and observed.executions:
                return self._finish(reserved, observed.executions, next_state="acknowledged")
            if observed.state == "absent" and not observed.executions:
                # Explicit harmless redelivery only. reserve enforces at most two
                # total submit reservations and two reconciliation reads.
                return self._finish(reserved, next_state="pending", error="reconciled_absent")
            return self._finish(reserved, error="reconciliation_unknown")
        except AcknowledgementLost:
            return self._finish(reserved, error="acknowledgement_lost")
        except Exception:
            # Do not expose scheduler/transport exception text. Leave unresolved
            # intent durable, without a blind submit retry or invented Run success.
            return self._finish(reserved, error="scheduler_operation_failed")
