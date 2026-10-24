"""Trusted internal delivery transactions. No client, polling loop or OS proof.

Only the bounded harmless Run kind is supported. A verifier injected by the
runtime is a trust boundary; callers cannot turn a broker status into quiescence.
The synthetic receipt used by integration fixtures proves no actual process kill.
"""
from dataclasses import dataclass, asdict
from uuid import UUID, uuid4

from sqlalchemy import text

from services.api.db import digest
from services.api.errors import Problem
from services.api.runs import repository as repo
from services.worker.hatchet_contracts import Binding, DispatchSpec, Observation, STATUSES, verify_observed_payload


def conflict(code="delivery_conflict"):
    raise Problem(409, code, "conflict", "Scheduler delivery requires reconciliation")


@dataclass(frozen=True)
class DeliveryContext:
    binding: Binding
    case_id: UUID
    principal_id: UUID

    def __post_init__(self):
        if type(self.binding) is not Binding or any(type(v) is not UUID for v in (self.case_id, self.principal_id)):
            raise ValueError("Explicit trusted delivery context required")


@dataclass(frozen=True)
class DeliveryReceipt:
    execution_id: UUID
    token: repo.AttemptToken | None


@dataclass(frozen=True)
class QuiescenceAttestation:
    receipt_id: UUID
    run_id: UUID
    attempt_id: UUID
    fence: int
    worker_instance_id: UUID
    root_ids: tuple[UUID, ...]
    process_identity: str
    source: str = "trusted_synthetic_fixture"
    effects: str = "readonly_safe"
    quiescent: bool = True


def authorize(conn, row, context):
    if (type(context) is not DeliveryContext or row["case_id"] != context.case_id
        or row["requested_by"] != context.principal_id):
        conflict("delivery_context_conflict")
    repo.work_authority(conn, row)


def outbox(conn, run_id):
    return dict(conn.execute(text("SELECT * FROM run_outbox WHERE run_id=:r AND command='start' FOR UPDATE"),
                             {"r": run_id}).mappings().one())


def specification(row, intent, generation):
    return DispatchSpec(row["id"], intent["dispatch_key"], digest(row["input_refs"]), generation, intent["created_at"])


def submission_hash(binding, spec):
    values = asdict(binding)
    values.update({key: str(values[key]) for key in ("tenant_id", "workflow_id", "workflow_version_id")})
    return digest({"binding": values, "payload": spec.payload()})


def submission(conn, row, intent, context, spec):
    if type(spec) is not DispatchSpec or spec != specification(row, intent, spec.generation):
        conflict("delivery_spec_conflict")
    saved = conn.execute(text("SELECT * FROM run_scheduler_submissions WHERE outbox_id=:o AND generation=:g"),
                         {"o": intent["id"], "g": spec.generation}).mappings().one_or_none()
    if saved is None or intent["scheduler_kind"] != "hatchet-v1":
        conflict("delivery_unconfigured")
    if (any(saved[key] != value for key, value in asdict(context.binding).items())
        or saved["run_id"] != row["id"] or saved["input_hash"] != spec.input_hash
        or saved["dispatch_identity"] != spec.dispatch_identity
        or saved["submission_hash"] != submission_hash(context.binding, spec)):
        conflict("delivery_binding_conflict")
    return dict(saved)


def insert_submission(conn, row, intent, context, spec, revision, recovery=None):
    values = {"id": uuid4(), "r": row["id"], "o": intent["id"], "g": spec.generation,
              **asdict(context.binding), "input": spec.input_hash,
              "hash": submission_hash(context.binding, spec), "identity": spec.dispatch_identity,
              "revision": revision, "attempt": None, "fence": None, "receipt": None,
              "roots": None, "proof": None}
    if recovery:
        values.update(attempt=recovery.attempt_id, fence=recovery.fence, receipt=recovery.receipt_id,
                      roots=list(recovery.root_ids), proof=digest({key: str(value) if type(value) is UUID
                          else [str(v) for v in value] if type(value) is tuple else value
                          for key, value in asdict(recovery).items()}))
    conn.execute(text("""INSERT INTO run_scheduler_submissions(id,run_id,outbox_id,generation,
        tenant_id,workflow_id,workflow_version_id,workflow_name,namespace,input_hash,submission_hash,
        dispatch_identity,entry_revision,recovery_attempt_id,recovery_fence,recovery_receipt_id,
        recovery_at,recovery_roots,recovery_proof_hash)
        VALUES(:id,:r,:o,:g,:tenant_id,:workflow_id,:workflow_version_id,:workflow_name,:namespace,
        :input,:hash,:identity,:revision,:attempt,:fence,:receipt,
        CASE WHEN :g=1 THEN clock_timestamp() ELSE NULL END,CAST(:roots AS uuid[]),:proof)"""), values)


def configure_delivery(conn, context, run_id, expected_revision):
    row = repo.locked_run(conn, run_id)
    repo._revision(row, expected_revision)
    authorize(conn, row, context)
    repo._wall_budget(conn, row)
    intent = outbox(conn, run_id)
    if (row["status"] != "queued" or row["attempt_id"] is not None or intent["state"] != "pending"
        or intent["dispatch_count"] or intent["reconcile_count"] or intent["claim_token"] is not None
        or intent["scheduler_kind"] != "fake-v1"):
        conflict("delivery_not_fresh")
    spec = specification(row, intent, 0)
    conn.execute(text("UPDATE run_outbox SET scheduler_kind='hatchet-v1' WHERE id=:o"), {"o": intent["id"]})
    insert_submission(conn, row, intent, context, spec, expected_revision)
    return spec


def validate_observation(observed):
    if (type(observed) is not Observation or type(observed.root_id) is not UUID
        or type(observed.task_ids) is not tuple or not 1 <= len(observed.task_ids) <= 50
        or any(type(v) is not UUID for v in observed.task_ids)
        or len(set(observed.task_ids)) != len(observed.task_ids)
        or type(observed.native_status) is not str or observed.native_status not in STATUSES
        or observed.domain_completion_proved is not False or observed.cleanup_proved is not False):
        conflict("invalid_scheduler_observation")


def lock_observations(conn, observations):
    keys = set()
    for observed in observations:
        validate_observation(observed)
        keys.add("root:" + str(observed.root_id))
        keys.update("task:" + str(v) for v in observed.task_ids)
    for key in sorted(keys):
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key})


def map_observation(conn, row, intent, saved, observed):
    """Caller holds Run then outbox. Shared advisory keys serialize task owners.

    Keep the union of observed tasks, so a later reduced observation never erases
    ownership history. These locks also serialize roots competing across Runs.
    """
    lock_observations(conn, (observed,))
    existing = conn.execute(text("""SELECT * FROM run_scheduler_executions
        WHERE scheduler_kind='hatchet-v1' AND external_id=:root"""),
        {"root": str(observed.root_id)}).mappings().one_or_none()
    if existing and (existing["run_id"] != row["id"] or existing["outbox_id"] != intent["id"]
                     or existing["submission_id"] != saved["id"]):
        conflict("scheduler_mapping_conflict")
    overlap = conn.execute(text("""SELECT id FROM run_scheduler_executions
        WHERE scheduler_kind='hatchet-v1' AND task_ids && CAST(:tasks AS uuid[])
        AND external_id<>:root LIMIT 1"""),
        {"tasks": list(observed.task_ids), "root": str(observed.root_id)}).first()
    if overlap:
        conflict("scheduler_task_conflict")
    tasks = sorted(set(observed.task_ids) | set(existing["task_ids"] if existing else ()), key=str)
    if len(tasks) > 50:
        conflict("scheduler_task_limit")
    if not existing:
        count = conn.execute(text("SELECT count(*) FROM run_scheduler_executions WHERE submission_id=:s"),
                             {"s": saved["id"]}).scalar_one()
        if count >= 2:
            conflict("scheduler_root_limit")
    native = existing["native_status"] if existing and existing["native_status"] in ("COMPLETED", "FAILED", "CANCELLED") else observed.native_status
    execution_id = existing["id"] if existing else uuid4()
    conn.execute(text("""INSERT INTO run_scheduler_executions(id,run_id,outbox_id,scheduler_kind,
        external_id,observed_state,submission_id,native_status,task_ids,observed_at)
        VALUES(:id,:r,:o,'hatchet-v1',:root,:state,:s,:native,CAST(:tasks AS uuid[]),clock_timestamp())
        ON CONFLICT(scheduler_kind,external_id) DO UPDATE SET observed_state=EXCLUDED.observed_state,
        native_status=EXCLUDED.native_status,task_ids=EXCLUDED.task_ids,observed_at=EXCLUDED.observed_at"""),
        {"id": execution_id, "r": row["id"], "o": intent["id"], "root": str(observed.root_id),
         "state": "accepted" if native in ("QUEUED", "RUNNING") else "completed", "s": saved["id"],
         "native": native, "tasks": tasks})
    return execution_id


def verified_candidates(conn, intent, candidates=()):
    values = set(intent["candidate_ids"]) | set(candidates)
    mapped = conn.execute(text("""SELECT external_id FROM run_scheduler_executions
        WHERE run_id=:r AND outbox_id=:o AND scheduler_kind='hatchet-v1'"""),
        {"r": intent["run_id"], "o": intent["id"]}).scalars().all()
    values.difference_update(UUID(v) for v in mapped)
    if len(values) > 8:
        conflict("scheduler_candidate_limit")
    return sorted(values, key=str)


def register_delivery(conn, context, spec, observed, raw_payload, worker_id, worker_instance_id,
                      expected_revision, lease_seconds=5):
    if (type(worker_id) is not str or not 1 <= len(worker_id.encode("utf-8")) <= 100
        or type(worker_instance_id) is not UUID):
        conflict("invalid_worker")
    if type(spec) is not DispatchSpec:
        conflict("delivery_spec_conflict")
    row = repo.locked_run(conn, spec.run_id)
    authorize(conn, row, context)
    intent = outbox(conn, spec.run_id)
    saved = submission(conn, row, intent, context, spec)
    if type(expected_revision) is not int or expected_revision != saved["entry_revision"]:
        conflict("stale_revision")
    try:
        verify_observed_payload(raw_payload, spec)
    except ValueError:
        conflict("delivery_payload_conflict")
    execution_id = map_observation(conn, row, intent, saved, observed)
    # Historical delivery can add verified history, never settle a newer intent.
    if spec.generation != intent["dispatch_generation"]:
        return DeliveryReceipt(execution_id, None)
    if intent["state"] == "suppressed":
        conflict("delivery_suppressed")
    candidates = verified_candidates(conn, intent)
    conn.execute(text("""UPDATE run_outbox SET state='acknowledged',candidate_ids=CAST(:ids AS uuid[]),
        claim_token=CASE WHEN state='acknowledged' THEN claim_token ELSE NULL END,
        claim_until=CASE WHEN state='acknowledged' THEN claim_until ELSE NULL END,
        last_error_code=:error WHERE id=:o"""),
        {"o": intent["id"], "ids": candidates, "error": "delivery_unknown" if intent["last_error_code"] == "delivery_unknown"
         else "unresolved_candidates" if candidates else None})
    count = conn.execute(text("SELECT count(*) FROM run_attempts WHERE run_id=:r"), {"r": spec.run_id}).scalar_one()
    native_active = conn.execute(text("SELECT native_status IN ('QUEUED','RUNNING') FROM run_scheduler_executions WHERE id=:e"),
                                 {"e": execution_id}).scalar_one()
    token = None
    if (row["status"] in ("queued", "interrupted") and row["revision"] == expected_revision
        and count == spec.generation and native_active):
        token = repo.claim_attempt(conn, spec.run_id, str(observed.root_id), worker_id, expected_revision,
                                   lease_seconds, scheduler_kind="hatchet-v1", worker_instance_id=worker_instance_id)
    return DeliveryReceipt(execution_id, token)


def rearm_delivery(conn, context, spec, evidence, expected_revision, *, verify_quiescence):
    """Explicit generation 0->1 only. Receipt authenticity is a runtime boundary.

    verify_quiescence must be a trusted pure verifier, with no IO under locks.
    No public route accepts this callback or the resulting internal attestation.
    """
    if not callable(verify_quiescence):
        conflict("quiescence_unproved")
    try:
        proof = verify_quiescence(evidence)
    except Exception:
        conflict("quiescence_unproved")
    if (type(proof) is not QuiescenceAttestation
        or any(type(v) is not UUID for v in (proof.receipt_id, proof.run_id, proof.attempt_id, proof.worker_instance_id))
        or type(proof.fence) is not int or proof.fence < 1
        or type(proof.root_ids) is not tuple or not 1 <= len(proof.root_ids) <= 2
        or any(type(v) is not UUID for v in proof.root_ids) or len(set(proof.root_ids)) != len(proof.root_ids)
        or type(proof.process_identity) is not str or not 1 <= len(proof.process_identity) <= 200
        or proof.source != "trusted_synthetic_fixture" or proof.effects != "readonly_safe" or proof.quiescent is not True):
        conflict("quiescence_unproved")
    if type(spec) is not DispatchSpec:
        conflict("delivery_spec_conflict")
    row = repo.locked_run(conn, spec.run_id)
    repo._revision(row, expected_revision)
    authorize(conn, row, context)
    repo._wall_budget(conn, row)
    intent = outbox(conn, spec.run_id)
    saved = submission(conn, row, intent, context, spec)
    if (spec.generation != 0 or intent["dispatch_generation"] != 0 or row["status"] != "interrupted"
        or row["terminal_reason"] != "lease_expired" or intent["candidate_ids"]
        or intent["state"] != "acknowledged" or intent["last_error_code"] is not None
        or intent["dispatch_count"] >= 2 or intent["reconcile_count"] >= 2
        or intent["claim_token"] is not None):
        conflict("recovery_unresolved")
    prior = conn.execute(text("""SELECT a.*,a.lease_expires_at<=clock_timestamp() AS expired,
        e.submission_id FROM run_attempts a JOIN run_scheduler_executions e ON e.id=a.execution_id
        WHERE a.id=:a AND a.run_id=:r FOR UPDATE OF a"""),
        {"a": row["attempt_id"], "r": row["id"]}).mappings().one_or_none()
    roots = conn.execute(text("SELECT external_id FROM run_scheduler_executions WHERE submission_id=:s"),
                         {"s": saved["id"]}).scalars().all()
    if (prior is None or not prior["expired"] or prior["state"] != "expired"
        or prior["submission_id"] != saved["id"] or row["fence"] != prior["fence"] + 1
        or proof.run_id != row["id"] or proof.attempt_id != prior["id"] or proof.fence != prior["fence"]
        or proof.worker_instance_id != prior["worker_instance_id"] or set(proof.root_ids) != {UUID(v) for v in roots}):
        conflict("quiescence_conflict")
    count = conn.execute(text("SELECT count(*) FROM run_attempts WHERE run_id=:r"), {"r": row["id"]}).scalar_one()
    if count != 1:
        conflict("attempt_limit")
    next_spec = specification(row, intent, 1)
    insert_submission(conn, row, intent, context, next_spec, expected_revision + 1, proof)
    # Receipt uniqueness/FKs can wait; validate the original wall clock again
    # after those blocking checks. A failure rolls back the inserted submission.
    repo._wall_budget(conn, row)
    conn.execute(text("""UPDATE run_outbox SET dispatch_generation=1,state='pending',
        claim_token=NULL,claim_until=NULL,last_error_code=NULL WHERE id=:o"""), {"o": intent["id"]})
    conn.execute(text("UPDATE runs SET revision=revision+1 WHERE id=:r"), {"r": row["id"]})
    repo._event(conn, row, "delivery_rearmed", prior["id"])
    return next_spec
