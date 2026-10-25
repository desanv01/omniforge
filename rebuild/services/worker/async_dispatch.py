"""Finite explicit async adapter bridge; no factory, live client or global drain.

Short synchronous SQL transactions finish before each await. This internal
driver is deliberately not an async HTTP handler or a throughput claim.
"""
import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text

from services.api.runs import repository as repo
from services.worker import delivery
from services.worker.hatchet_contracts import DispatchSpec, Policy, Result


@dataclass(frozen=True)
class Reservation:
    run_id: UUID
    outbox_id: UUID
    submission_id: UUID
    token: UUID
    operation: str
    spec: DispatchSpec


class AsyncDispatcher:
    def __init__(self, engine, port, contexts):
        if (type(contexts) is not dict or not 1 <= len(contexts) <= 32
            or any(type(k) is not UUID or type(v) is not delivery.DeliveryContext for k, v in contexts.items())
            or type(getattr(port, "policy", None)) is not Policy
            or any(port.binding != v.binding for v in contexts.values())):
            raise ValueError("Explicit bounded new-Run contexts and matching port required")
        self.engine, self.port, self.contexts = engine, port, dict(contexts)

    def context(self, run_id):
        if type(run_id) is not UUID or run_id not in self.contexts:
            raise ValueError("Run is outside explicit dispatch allowlist")
        return self.contexts[run_id]

    def configure(self, run_id, expected_revision):
        context = self.context(run_id)
        with self.engine.begin() as conn:
            return delivery.configure_delivery(conn, context, run_id, expected_revision)

    def reserve(self, run_id):
        context = self.context(run_id)
        with self.engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM runs WHERE id=:r FOR UPDATE SKIP LOCKED"),
                               {"r": run_id}).mappings().one_or_none()
            if row is None:
                return None
            row = dict(row)
            delivery.authorize(conn, row, context)
            intent = delivery.outbox(conn, run_id)
            if intent["scheduler_kind"] != "hatchet-v1" or intent["state"] == "suppressed":
                return None
            if intent["claim_token"] is not None:
                live = conn.execute(text("SELECT :until>clock_timestamp()"), {"until": intent["claim_until"]}).scalar_one()
                if live:
                    return None
            if (intent["state"] == "acknowledged" and not intent["candidate_ids"]
                and intent["last_error_code"] != "delivery_unknown"):
                return None
            spec = delivery.specification(row, intent, intent["dispatch_generation"])
            saved = delivery.submission(conn, row, intent, context, spec)
            operation = "submit" if intent["state"] == "pending" else "lookup"
            if operation == "submit":
                if (row["cancellation_id"] is not None or row["status"] not in ("queued", "interrupted") or row["revision"] != saved["entry_revision"]
                    or (spec.generation == 0 and row["status"] != "queued")):
                    return None
                repo._wall_budget(conn, row)
            counter = "dispatch_count" if operation == "submit" else "reconcile_count"
            if intent[counter] >= 2:
                conn.execute(text("""UPDATE run_outbox SET claim_token=NULL,claim_until=NULL,
                    last_error_code=:error WHERE id=:o"""),
                    {"o": intent["id"], "error": "dispatch_limit" if operation == "submit" else "reconcile_limit"})
                return None
            token = uuid4()
            conn.execute(text(f"""UPDATE run_outbox SET state=:state,claim_token=:token,
                claim_until=clock_timestamp()+interval '15 seconds',{counter}={counter}+1 WHERE id=:o"""),
                {"o": intent["id"], "token": token,
                 "state": "acknowledged" if intent["state"] == "acknowledged" else "claimed"})
            return Reservation(run_id, intent["id"], saved["id"], token, operation, spec)

    @staticmethod
    def validate_result(result, operation):
        if (type(result) is not Result or type(result.executions) is not tuple or len(result.executions) > 2
            or type(result.candidate_ids) is not tuple or len(result.candidate_ids) > 2
            or any(type(v) is not UUID for v in result.candidate_ids)
            or len(set(result.candidate_ids)) != len(result.candidate_ids)
            or type(result.lookup_complete) is not bool
            or result.reason not in ("verified", "unresolved", "invalid_observation", "deadline", "transport", "lookup_bound")
            or result.state not in ("acknowledged", "found", "unknown")
            or (result.state == "acknowledged" and operation != "submit")
            or (result.state == "found" and (operation != "lookup" or result.lookup_complete is not True))
            or (result.state == "unknown" and result.executions)
            or (result.state != "unknown" and (not result.executions or result.reason != "verified"))):
            raise ValueError("Invalid bounded adapter result")
        for observed in result.executions:
            delivery.validate_observation(observed)
        if len({v.root_id for v in result.executions}) != len(result.executions):
            raise ValueError("Duplicate root observations")

    def finish(self, reserved, result):
        context = self.context(reserved.run_id)
        self.validate_result(result, reserved.operation)
        with self.engine.begin() as conn:
            row = repo.locked_run(conn, reserved.run_id)
            delivery.authorize(conn, row, context)
            intent = delivery.outbox(conn, reserved.run_id)
            saved = delivery.submission(conn, row, intent, context, reserved.spec)
            if intent["id"] != reserved.outbox_id or saved["id"] != reserved.submission_id:
                delivery.conflict()
            delivery.lock_observations(conn, result.executions)
            for observed in result.executions:
                delivery.map_observation(conn, row, intent, saved, observed)
            candidates = delivery.verified_candidates(conn, intent, result.candidate_ids)
            if reserved.spec.generation != intent["dispatch_generation"]:
                # Generation-zero callbacks may only append verified history and
                # preserve newly discovered unresolved IDs. No new token touched.
                conn.execute(text("UPDATE run_outbox SET candidate_ids=CAST(:ids AS uuid[]) WHERE id=:o"),
                             {"o": intent["id"], "ids": candidates})
                if row["cancellation_id"] is not None:
                    from services.worker import cancellation
                    cancellation.sync_targets(conn, row)
                    cancellation.settle_cancellation(conn, context, row["id"])
                return "historical_ack" if result.executions else "historical_unknown"
            known = conn.execute(text("SELECT EXISTS(SELECT 1 FROM run_scheduler_executions WHERE submission_id=:s)"),
                                 {"s": saved["id"]}).scalar_one()
            acknowledged = known or intent["state"] == "acknowledged"
            unresolved = bool(candidates) or result.state == "unknown"
            state = "acknowledged" if acknowledged else "reconcile_required"
            # Registration preserves the in-flight reservation until its actual
            # reply. A later reservation still owns its own separate claim.
            owns = intent["claim_token"] == reserved.token
            may_settle = owns or intent["claim_token"] is None
            if may_settle:
                conn.execute(text("""UPDATE run_outbox SET state=:state,candidate_ids=CAST(:ids AS uuid[]),
                    claim_token=NULL,claim_until=NULL,last_error_code=:error WHERE id=:o"""),
                    {"o": intent["id"], "state": state, "ids": candidates,
                     "error": "delivery_unknown" if unresolved else None})
            else:
                conn.execute(text("UPDATE run_outbox SET candidate_ids=CAST(:ids AS uuid[]) WHERE id=:o"),
                             {"o": intent["id"], "ids": candidates})
            if row["cancellation_id"] is not None:
                from services.worker import cancellation
                cancellation.sync_targets(conn, row)
                cancellation.settle_cancellation(conn, context, row["id"])
            return "acknowledged_unresolved" if acknowledged and unresolved else state

    async def tick(self, run_id):
        reserved = self.reserve(run_id)
        if reserved is None:
            return "not_eligible"
        try:
            async with asyncio.timeout(self.port.policy.total_seconds):
                result = await (self.port.submit(reserved.spec) if reserved.operation == "submit"
                                else self.port.lookup(reserved.spec))
            self.validate_result(result, reserved.operation)
        except asyncio.CancelledError:
            self.finish(reserved, Result("unknown", reason="transport"))
            raise
        except Exception:
            result = Result("unknown", reason="transport")
        return self.finish(reserved, result)
