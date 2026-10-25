"""Internal bounded stop/cleanup transactions, with no client or public authority.

Broker acknowledgement never proves cleanup. Credentials authorize only a finally
receipt after the work lease/fence/grant has been revoked. No IO under SQL locks.
"""
import asyncio
from dataclasses import dataclass, field, asdict
import hashlib
import hmac
from uuid import UUID, uuid4

from sqlalchemy import text

from services.api.db import digest
from services.api.errors import Problem
from services.api.runs import repository as repo
from services.worker import delivery
from services.worker.hatchet_contracts import Policy, Result


def deny(code="cleanup_authority_conflict"):
    raise Problem(409, code, "conflict", "Cancellation requires reconciliation")


def hash_secret(secret):
    return hashlib.sha256(str(secret).encode()).hexdigest()


def context_authority(conn, row, context):
    if (type(context) is not delivery.DeliveryContext or context.case_id != row["case_id"]
        or context.principal_id != row["requested_by"]):
        deny()
    saved = conn.execute(text("SELECT * FROM run_scheduler_submissions WHERE run_id=:r"),
                         {"r": row["id"]}).mappings().all()
    if any(any(s[key] != value for key, value in asdict(context.binding).items()) for s in saved):
        deny()


def current(conn, row):
    if row["cancellation_id"] is None or row["cancel_generation"] != 1:
        deny()
    cancel = conn.execute(text("""SELECT * FROM run_cancellations
        WHERE id=:c AND run_id=:r AND generation=:g FOR UPDATE"""),
        {"c": row["cancellation_id"], "r": row["id"], "g": row["cancel_generation"]}).mappings().one_or_none()
    if cancel is None or cancel["case_id"] != row["case_id"]:
        deny()
    return dict(cancel)


def request_cancellation(conn, supplied, principal):
    row = repo.locked_run(conn, supplied["id"])
    repo._revision(row, supplied["revision"])
    allowed = conn.execute(text("SELECT can_write FROM case_grants WHERE case_id=:c AND principal_id=:p FOR SHARE"),
                           {"c": row["case_id"], "p": principal}).scalar_one_or_none()
    if allowed is not True:
        raise Problem(403, "run_authority_revoked", "forbidden", "Cancellation authority unavailable")
    if row["cancellation_id"] is not None:
        current(conn, row)
        return repo.dto(row)
    if row["status"] == "canceled":
        return repo.dto(row)
    if row["status"] not in ("queued", "claimed", "running", "interrupted"):
        deny("run_state_conflict")
    intent = delivery.outbox(conn, row["id"])
    mappings = conn.execute(text("SELECT * FROM run_scheduler_executions WHERE run_id=:r ORDER BY id"),
                            {"r": row["id"]}).mappings().all()
    if len(mappings) > 4:
        deny("cancel_target_limit")
    if (row["status"] == "queued" and row["attempt_id"] is None and intent["state"] == "pending"
        and not intent["dispatch_count"] and not intent["reconcile_count"] and not intent["candidate_ids"]
        and intent["claim_token"] is None and not mappings):
        return repo.cancel_queued(conn, row)
    scope = row["scope_snapshot"]
    if (row["kind"] != "synthetic-read-only-v1" or row["policy_version"] != "local-read-only-v1"
        or scope != {"principal_id": str(row["requested_by"]), "case_id": str(row["case_id"]),
                     "operation": row["kind"], "association_ids": [v["association_id"] for v in row["input_refs"]]}):
        deny("run_scope_changed")
    cancel_id = uuid4()
    snapshot = {"attempt_id": str(row["attempt_id"]) if row["attempt_id"] else None, "fence": row["fence"],
        "start_intent": {"id": str(intent["id"]), "state": intent["state"], "generation": intent["dispatch_generation"],
                         "dispatch_count": intent["dispatch_count"], "reconcile_count": intent["reconcile_count"]},
        "candidate_ids": [str(v) for v in intent["candidate_ids"]],
        "mapped_roots": [{"execution_id": str(e["id"]), "external_id": e["external_id"]} for e in mappings],
        "usage": row["usage"], "output_refs": row["output_refs"]}
    conn.execute(text("""INSERT INTO run_cancellations(id,run_id,case_id,requested_by,generation,request_revision,request_snapshot)
        VALUES(:id,:r,:case,:p,1,:revision,CAST(:snapshot AS jsonb))"""),
        {"id": cancel_id, "r": row["id"], "case": row["case_id"], "p": principal,
         "revision": row["revision"], "snapshot": repo.encode(snapshot)})
    conn.execute(text("""UPDATE runs SET cancellation_id=:c,cancel_generation=1,cleanup_status='pending',
        status='cancel_requested',cancel_requested_at=clock_timestamp(),finished_at=NULL,terminal_reason=NULL,
        fence=fence+1,revision=revision+1 WHERE id=:r"""), {"c": cancel_id, "r": row["id"]})
    repo._event(conn, row, "cancel_requested", row["attempt_id"])
    sync_targets(conn, repo.locked_run(conn, row["id"]))
    return repo.dto(repo.locked_run(conn, row["id"]))


def sync_targets(conn, row):
    """Caller holds Run. Late evidence can revoke cleanup certainty, never work."""
    if row["cancellation_id"] is None:
        return
    cancel = current(conn, row)
    mappings = conn.execute(text("SELECT * FROM run_scheduler_executions WHERE run_id=:r ORDER BY id"),
                            {"r": row["id"]}).mappings().all()
    if len(mappings) > 4:
        deny("cancel_target_limit")
    targets = {v["execution_id"]: dict(v) for v in conn.execute(text("SELECT * FROM run_cancel_targets WHERE cancel_id=:c ORDER BY id FOR UPDATE"),
                                                           {"c": cancel["id"]}).mappings()}
    changed = expanded = False
    for execution in mappings:
        tasks = execution["task_ids"]
        target = targets.get(execution["id"])
        if target is None:
            attempt = conn.execute(text("SELECT * FROM run_attempts WHERE run_id=:r AND execution_id=:e ORDER BY fence DESC LIMIT 1"),
                                   {"r": row["id"], "e": execution["id"]}).mappings().one_or_none()
            if attempt is None and execution["scheduler_kind"] == "fake-v1" and len(mappings) == 1 and row["attempt_id"]:
                attempt = conn.execute(text("SELECT * FROM run_attempts WHERE id=:a AND run_id=:r AND execution_id IS NULL"),
                                       {"a": row["attempt_id"], "r": row["id"]}).mappings().one_or_none()
            target_id = uuid4()
            conn.execute(text("""INSERT INTO run_cancel_targets(id,run_id,cancel_id,generation,execution_id,
                original_attempt_id,original_fence,worker_instance_id,task_ids,command_key)
                VALUES(:id,:r,:c,1,:e,:a,:f,:instance,CAST(:tasks AS uuid[]),:key)"""),
                {"id": target_id, "r": row["id"], "c": cancel["id"], "e": execution["id"],
                 "a": attempt["id"] if attempt else None, "f": attempt["fence"] if attempt else None,
                 "instance": attempt["worker_instance_id"] if attempt else None, "tasks": tasks,
                 "key": "cancel:" + str(cancel["id"]) + ":" + str(target_id)})
            changed = True
        elif set(target["task_ids"] or ()) != set(tasks or ()):
            if target["cleanup_credential_hash"] is None:
                conn.execute(text("UPDATE run_cancel_targets SET task_ids=CAST(:tasks AS uuid[]) WHERE id=:id"),
                             {"id": target["id"], "tasks": tasks})
                changed = True
            else:
                expanded = True
    if expanded or (changed and row["status"] == "canceled"):
        status = "unknown" if expanded else "pending"
        conn.execute(text("UPDATE run_cancellations SET state='unresolved' WHERE id=:id"), {"id": cancel["id"]})
        if row["status"] == "canceled":
            conn.execute(text("""UPDATE runs SET status='cancel_requested',cleanup_status=:status,finished_at=NULL,
                terminal_reason=NULL,revision=revision+1,fence=fence+1 WHERE id=:r"""), {"status": status, "r": row["id"]})
            repo._event(conn, row, "cleanup_reopened", row["attempt_id"])
        else:
            if row["cleanup_status"] != status:
                conn.execute(text("UPDATE runs SET cleanup_status=:status,revision=revision+1 WHERE id=:r"), {"status": status, "r": row["id"]})
                repo._event(conn, row, "cleanup_unresolved", row["attempt_id"])


@dataclass(frozen=True)
class CleanupCredential:
    run_id: UUID
    cancel_id: UUID
    generation: int
    target_id: UUID
    execution_id: UUID
    attempt_id: UUID | None
    fence: int | None
    worker_instance_id: UUID
    task_ids: tuple[UUID, ...] | None
    secret: UUID = field(repr=False)


def issue_cleanup(conn, context, run_id, execution_id, attempt_id, worker_instance_id):
    row = repo.locked_run(conn, run_id)
    context_authority(conn, row, context)
    cancel = current(conn, row)
    sync_targets(conn, row)
    target = conn.execute(text("SELECT * FROM run_cancel_targets WHERE cancel_id=:c AND execution_id=:e FOR UPDATE"),
                          {"c": cancel["id"], "e": execution_id}).mappings().one_or_none()
    if (type(execution_id) is not UUID or type(worker_instance_id) is not UUID or target is None
        or type(run_id) is not UUID or (attempt_id is not None and type(attempt_id) is not UUID)
        or target["original_attempt_id"] != attempt_id
        or (target["worker_instance_id"] is not None and target["worker_instance_id"] != worker_instance_id)):
        deny()
    if target["cleanup_credential_hash"] is not None:
        return None
    execution = conn.execute(text("SELECT scheduler_kind FROM run_scheduler_executions WHERE id=:e"),
                             {"e": execution_id}).scalar_one()
    if execution == "fake-v1" and row["attempt_id"] is not None and attempt_id is None:
        deny("cleanup_ambiguous_attempt")
    secret = uuid4()
    conn.execute(text("UPDATE run_cancel_targets SET worker_instance_id=:instance,cleanup_credential_hash=:hash WHERE id=:id"),
                 {"instance": worker_instance_id, "hash": hash_secret(secret), "id": target["id"]})
    return CleanupCredential(run_id, cancel["id"], 1, target["id"], execution_id, attempt_id,
        target["original_fence"], worker_instance_id, tuple(target["task_ids"]) if target["task_ids"] is not None else None, secret)


def credential_target(conn, row, credential):
    if (type(credential) is not CleanupCredential or type(credential.generation) is not int or credential.generation != 1
        or any(type(v) is not UUID for v in (credential.run_id, credential.cancel_id, credential.target_id,
                                            credential.execution_id, credential.worker_instance_id, credential.secret))
        or credential.run_id != row["id"] or credential.cancel_id != row["cancellation_id"]
        or (credential.attempt_id is None and credential.fence is not None)
        or (credential.attempt_id is not None and (type(credential.attempt_id) is not UUID
            or type(credential.fence) is not int or credential.fence < 1))
        or (credential.task_ids is not None and (type(credential.task_ids) is not tuple
            or not 1 <= len(credential.task_ids) <= 50 or any(type(v) is not UUID for v in credential.task_ids)))):
        deny()
    current(conn, row)
    target = conn.execute(text("SELECT * FROM run_cancel_targets WHERE id=:id AND cancel_id=:c FOR UPDATE"),
                          {"id": credential.target_id, "c": credential.cancel_id}).mappings().one_or_none()
    if (target is None or target["run_id"] != row["id"] or target["execution_id"] != credential.execution_id
        or target["original_attempt_id"] != credential.attempt_id or target["original_fence"] != credential.fence
        or target["worker_instance_id"] != credential.worker_instance_id
        or target["cleanup_credential_hash"] is None
        or not hmac.compare_digest(target["cleanup_credential_hash"], hash_secret(credential.secret))
        or credential.task_ids != (tuple(target["task_ids"]) if target["task_ids"] is not None else None)):
        deny()
    execution = conn.execute(text("SELECT * FROM run_scheduler_executions WHERE id=:e AND run_id=:r"),
                             {"e": credential.execution_id, "r": row["id"]}).mappings().one()
    if set(execution["task_ids"] or ()) != set(target["task_ids"] or ()):
        deny("cleanup_task_conflict")
    if credential.attempt_id is not None:
        attempt = conn.execute(text("SELECT * FROM run_attempts WHERE id=:a AND run_id=:r AND fence=:f"),
                               {"a": credential.attempt_id, "r": row["id"], "f": credential.fence}).mappings().one_or_none()
        if (attempt is None or (execution["scheduler_kind"] == "hatchet-v1"
            and (attempt["execution_id"] != credential.execution_id or attempt["worker_instance_id"] != credential.worker_instance_id))):
            deny()
    return target


def record_cleanup(conn, context, credential, receipt_id, result):
    if type(credential) is not CleanupCredential:
        deny()
    row = repo.locked_run(conn, credential.run_id)
    context_authority(conn, row, context)
    target = credential_target(conn, row, credential)
    if type(receipt_id) is not UUID or type(result) is not str or result not in ("succeeded", "failed", "unknown"):
        deny("invalid_cleanup_receipt")
    receipt_hash = digest({"receipt_id": str(receipt_id), "target_id": str(target["id"]),
        "credential_hash": target["cleanup_credential_hash"], "result": result,
        "tasks": [str(v) for v in credential.task_ids] if credential.task_ids is not None else None})
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                 {"key": "cleanup-receipt:" + str(receipt_id)})
    old = conn.execute(text("SELECT * FROM run_cancel_receipts WHERE id=:id OR target_id=:target"),
                       {"id": receipt_id, "target": target["id"]}).mappings().all()
    if old:
        if len(old) != 1 or old[0]["id"] != receipt_id or old[0]["target_id"] != target["id"] or old[0]["receipt_hash"] != receipt_hash:
            deny("cleanup_receipt_conflict")
        return dict(old[0])
    result_row = conn.execute(text("""INSERT INTO run_cancel_receipts(id,run_id,cancel_id,target_id,execution_id,
        generation,credential_hash,worker_instance_id,result,receipt_hash,task_ids)
        VALUES(:id,:r,:c,:t,:e,1,:hash,:instance,:result,:receipt,CAST(:tasks AS uuid[])) RETURNING *"""),
        {"id": receipt_id, "r": row["id"], "c": row["cancellation_id"], "t": target["id"],
         "e": target["execution_id"], "hash": target["cleanup_credential_hash"],
         "instance": credential.worker_instance_id, "result": result, "receipt": receipt_hash,
         "tasks": list(credential.task_ids) if credential.task_ids is not None else None}).mappings().one()
    conn.execute(text("UPDATE runs SET revision=revision+1 WHERE id=:r"), {"r": row["id"]})
    repo._event(conn, row, "cleanup_received", credential.attempt_id)
    settle_cancellation(conn, context, row["id"])
    return dict(result_row)


def settle_cancellation(conn, context, run_id):
    row = repo.locked_run(conn, run_id)
    context_authority(conn, row, context)
    cancel = current(conn, row)
    sync_targets(conn, row)
    row = repo.locked_run(conn, run_id)
    intent = delivery.outbox(conn, run_id)
    targets = conn.execute(text("""SELECT t.*,r.result,r.task_ids AS receipt_tasks,e.task_ids AS current_tasks
        FROM run_cancel_targets t JOIN run_scheduler_executions e ON e.id=t.execution_id
        LEFT JOIN run_cancel_receipts r ON r.target_id=t.id WHERE t.cancel_id=:c ORDER BY t.id FOR UPDATE OF t"""),
        {"c": cancel["id"]}).mappings().all()
    unknown = (bool(intent["candidate_ids"]) or intent["claim_token"] is not None
        or intent["state"] not in ("acknowledged", "suppressed")
        or intent["last_error_code"] in ("delivery_unknown", "reconciliation_unknown", "acknowledgement_lost", "scheduler_operation_failed", "reconcile_limit"))
    expanded = any(set(t["task_ids"] or ()) != set(t["current_tasks"] or ()) for t in targets)
    all_success = bool(targets) and all(t["result"] == "succeeded" and
        set(t["receipt_tasks"] or ()) == set(t["current_tasks"] or ()) for t in targets)
    if all_success and not unknown and not expanded:
        if row["status"] != "canceled":
            conn.execute(text("""UPDATE runs SET status='canceled',cleanup_status='succeeded',revision=revision+1,
                terminal_reason='canceled_after_cleanup',finished_at=clock_timestamp() WHERE id=:r"""), {"r": run_id})
            repo._event(conn, row, "canceled", row["attempt_id"])
        conn.execute(text("UPDATE run_cancellations SET state='settled' WHERE id=:c"), {"c": cancel["id"]})
    else:
        status = "unknown" if unknown or expanded or any(t["result"] == "unknown" for t in targets) else (
            "failed" if any(t["result"] == "failed" for t in targets) else "pending")
        if row["status"] == "canceled":
            conn.execute(text("""UPDATE runs SET status='cancel_requested',cleanup_status=:status,
                finished_at=NULL,terminal_reason=NULL,fence=fence+1,revision=revision+1 WHERE id=:r"""),
                {"r": run_id, "status": status})
            repo._event(conn, row, "cleanup_reopened", row["attempt_id"])
        elif row["cleanup_status"] != status:
            conn.execute(text("UPDATE runs SET cleanup_status=:status,revision=revision+1 WHERE id=:r"), {"r": run_id, "status": status})
            repo._event(conn, row, "cleanup_unresolved", row["attempt_id"])
        conn.execute(text("UPDATE run_cancellations SET state=:state WHERE id=:c"),
                     {"c": cancel["id"], "state": "pending" if status == "pending" else "unresolved"})
    return repo.dto(repo.locked_run(conn, run_id))


@dataclass(frozen=True)
class CancelReservation:
    run_id: UUID
    cancel_id: UUID
    target_id: UUID
    token: UUID
    operation: str
    execution_id: UUID
    external_id: str
    scheduler_kind: str
    spec: object


class AsyncCancellationDispatcher:
    def __init__(self, engine, port, contexts):
        if (type(contexts) is not dict or not 1 <= len(contexts) <= 32
            or any(type(k) is not UUID or type(v) is not delivery.DeliveryContext for k,v in contexts.items())
            or type(getattr(port, "policy", None)) is not Policy
            or any(port.binding != v.binding for v in contexts.values())):
            raise ValueError("Explicit bounded cancellation contexts required")
        self.engine, self.port, self.contexts = engine, port, dict(contexts)

    def context(self, run_id):
        if type(run_id) is not UUID or run_id not in self.contexts:
            raise ValueError("Run outside cancellation allowlist")
        return self.contexts[run_id]

    def reserve(self, run_id):
        context = self.context(run_id)
        with self.engine.begin() as conn:
            row = repo.locked_run(conn, run_id)
            context_authority(conn, row, context)
            cancel = current(conn, row)
            sync_targets(conn, row)
            row = repo.locked_run(conn, run_id)
            if row["status"] == "canceled":
                return None
            targets = conn.execute(text("SELECT * FROM run_cancel_targets WHERE cancel_id=:c ORDER BY id FOR UPDATE"),
                                   {"c": cancel["id"]}).mappings().all()
            for target in targets:
                receipt = conn.execute(text("SELECT result FROM run_cancel_receipts WHERE target_id=:t"),
                                       {"t": target["id"]}).scalar_one_or_none()
                if receipt == "succeeded":
                    continue
                if target["command_state"] == "acknowledged":
                    continue
                if target["claim_token"] is not None and conn.execute(text("SELECT :until>clock_timestamp()"), {"until": target["claim_until"]}).scalar_one():
                    continue
                operation = "cancel" if target["command_state"] == "pending" else "lookup"
                counter = "cancel_count" if operation == "cancel" else "lookup_count"
                if target[counter] >= 2:
                    continue
                execution = conn.execute(text("SELECT * FROM run_scheduler_executions WHERE id=:e"), {"e": target["execution_id"]}).mappings().one()
                spec = None
                if execution["scheduler_kind"] == "hatchet-v1":
                    intent = delivery.outbox(conn, run_id)
                    saved = conn.execute(text("SELECT generation FROM run_scheduler_submissions WHERE id=:s"), {"s": execution["submission_id"]}).scalar_one()
                    spec = delivery.specification(row, intent, saved)
                    delivery.submission(conn, row, intent, context, spec)
                token = uuid4()
                conn.execute(text(f"UPDATE run_cancel_targets SET command_state='claimed',claim_token=:token,claim_until=clock_timestamp()+interval '15 seconds',{counter}={counter}+1 WHERE id=:id"),
                             {"token": token, "id": target["id"]})
                return CancelReservation(run_id, cancel["id"], target["id"], token, operation,
                    execution["id"], execution["external_id"], execution["scheduler_kind"], spec)
        return None

    def finish(self, reserved, result):
        context = self.context(reserved.run_id)
        with self.engine.begin() as conn:
            row = repo.locked_run(conn, reserved.run_id)
            context_authority(conn, row, context)
            cancel = current(conn, row)
            target = conn.execute(text("SELECT * FROM run_cancel_targets WHERE id=:id AND cancel_id=:c FOR UPDATE"),
                                  {"id": reserved.target_id, "c": cancel["id"]}).mappings().one()
            if reserved.cancel_id != cancel["id"] or target["claim_token"] != reserved.token or target["execution_id"] != reserved.execution_id:
                return "stale_cancel_ack"
            verified = False
            valid = (type(result) is Result and type(result.executions) is tuple and len(result.executions) <= 2
                and type(result.candidate_ids) is tuple and len(result.candidate_ids) <= 2
                and all(type(v) is UUID for v in result.candidate_ids)
                and type(result.lookup_complete) is bool and type(result.state) is str and type(result.reason) is str)
            if (valid
                and result.state in ("cancel_requested", "found") and result.reason == "verified"
                and (reserved.operation == "cancel" and result.state == "cancel_requested"
                     or reserved.operation == "lookup" and result.state == "found" and result.lookup_complete is True)):
                if reserved.scheduler_kind == "hatchet-v1":
                    intent = delivery.outbox(conn, row["id"])
                    saved = delivery.submission(conn, row, intent, context, reserved.spec)
                    delivery.lock_observations(conn, result.executions)
                    for observed in result.executions:
                        delivery.validate_observation(observed)
                        delivery.map_observation(conn, row, intent, saved, observed)
                    match = [o for o in result.executions if str(o.root_id) == reserved.external_id]
                    verified = len(match) == 1 and (reserved.operation == "cancel" or match[0].native_status in ("COMPLETED", "FAILED", "CANCELLED"))
                else:
                    # A separately injected fake stop boundary is allowed in the
                    # fixture; native real-port identities remain UUID-only.
                    verified = not result.executions
            if valid and reserved.scheduler_kind == "hatchet-v1":
                intent = delivery.outbox(conn, row["id"])
                candidates = delivery.verified_candidates(conn, intent, result.candidate_ids)
                conn.execute(text("UPDATE run_outbox SET candidate_ids=CAST(:ids AS uuid[]) WHERE id=:o"),
                             {"o": intent["id"], "ids": candidates})
            state = "acknowledged" if verified else "reconcile_required"
            conn.execute(text("UPDATE run_cancel_targets SET command_state=:state,claim_token=NULL,claim_until=NULL,last_error_code=:error WHERE id=:id"),
                         {"id": target["id"], "state": state, "error": None if verified else "cancel_unknown"})
            settle_cancellation(conn, context, row["id"])
            return state

    async def tick(self, run_id):
        reserved = self.reserve(run_id)
        if reserved is None:
            return "not_eligible"
        try:
            async with asyncio.timeout(self.port.policy.total_seconds):
                if reserved.scheduler_kind == "fake-v1":
                    result = await self.port.cancel_fake(reserved.external_id, reserved.operation)
                else:
                    result = await (self.port.cancel(reserved.spec, UUID(reserved.external_id)) if reserved.operation == "cancel"
                                    else self.port.lookup(reserved.spec))
        except asyncio.CancelledError:
            self.finish(reserved, Result("unknown"))
            raise
        except Exception:
            result = Result("unknown")
        return self.finish(reserved, result)
