"""Explicit domain transactions; caller owns the connection/commit.

Only the harmless synthetic kind is admitted. No scheduler/network/tool execution.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from uuid import UUID, uuid4

from sqlalchemy import text
from starlette.exceptions import HTTPException

from services.api.errors import Problem
from services.api.runs.contracts import InputRef, InputSnapshot, Run, RunEvent, UnusedUsage


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def grant(conn, bindings, principal_id, case_id):
    bindings.require_grant(conn, principal_id, case_id, write=True)
    # Serialize against grant revocation through transaction commit. Authority is
    # still the existing application callback, never client-supplied scope.
    allowed = conn.execute(text("""SELECT can_write FROM case_grants
        WHERE principal_id=:p AND case_id=:c FOR SHARE"""),
        {"p": principal_id, "c": case_id}).scalar_one_or_none()
    if allowed is not True:
        raise HTTPException(403)


def authorized_run(conn, principal_id, run_id, write=False, locked=False):
    # Unknown and unauthorized run IDs have the same public result.
    sql = """SELECT r.* FROM runs r JOIN case_grants g ON g.case_id=r.case_id
        WHERE r.id=:r AND g.principal_id=:p"""
    if write:
        sql += " AND g.can_write=true"
    if locked:
        sql += " FOR UPDATE OF r FOR SHARE OF g"
    row = conn.execute(text(sql), {"r": run_id, "p": principal_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404)
    return dict(row)


def dto(row):
    fields = Run.model_fields
    return Run.model_validate({key: value for key, value in row.items() if key in fields})


def snapshot_inputs(conn, case_id, refs):
    snapshots = []
    for ref in refs:
        item = conn.execute(text("""SELECT a.id AS association_id,a.revision,
            a.artifact_id,a.source_id,a.publication_status,b.sha256,b.bytes
            FROM artifact_associations a JOIN artifacts b ON b.id=a.artifact_id
            WHERE a.id=:id AND a.case_id=:case FOR SHARE OF a,b"""),
            {"id": ref.association_id, "case": case_id}).mappings().one_or_none()
        if item is None:
            raise Problem(404, "run_input_unavailable", "not_found", "Run input unavailable")
        if item["revision"] != ref.revision or item["sha256"] != ref.sha256:
            raise Problem(409, "run_input_conflict", "conflict", "Run input version or hash changed")
        if item["publication_status"] != "committed":
            raise Problem(409, "run_input_pending", "conflict", "Run input is not committed")
        snapshots.append(InputSnapshot.model_validate({key: item[key] for key in
            ("association_id", "revision", "artifact_id", "source_id", "sha256", "bytes")}).model_dump(mode="json"))
    return snapshots


def insert_queued(conn, principal_id, case_id, body):
    inputs = snapshot_inputs(conn, case_id, body.input_refs)
    run_id = uuid4()
    scope = {"principal_id": str(principal_id), "case_id": str(case_id),
             "operation": "synthetic-read-only-v1", "association_ids": [r["association_id"] for r in inputs]}
    row = conn.execute(text("""INSERT INTO runs(id,case_id,requested_by,kind,
        schema_version,revision,status,input_refs,scope_snapshot,policy_version,
        budget,usage,output_refs,fence,next_event_sequence)
        VALUES(:id,:case,:principal,:kind,1,1,'queued',CAST(:inputs AS jsonb),
        CAST(:scope AS jsonb),:policy,CAST(:budget AS jsonb),CAST(:usage AS jsonb),'[]'::jsonb,0,2)
        RETURNING *"""), {"id": run_id, "case": case_id, "principal": principal_id,
        "kind": body.kind, "inputs": encode(inputs), "scope": encode(scope),
        "policy": body.policy_version, "budget": encode(body.budget.model_dump()),
        "usage": encode(UnusedUsage().model_dump())}).mappings().one()
    conn.execute(text("""INSERT INTO run_events(run_id,sequence,type,payload)
        VALUES(:id,1,'queued','{"status":"queued"}'::jsonb)"""), {"id": run_id})
    conn.execute(text("""INSERT INTO run_outbox(id,run_id,dispatch_key,command,state,payload)
        VALUES(:id,:run,:key,'start','pending',CAST(:payload AS jsonb))"""),
        {"id": uuid4(), "run": run_id, "key": "run:" + str(run_id) + ":start:v1",
         "payload": encode({"run_id": str(run_id), "kind": body.kind, "schema_version": 1})})
    return dto(row)


def cancel_queued(conn, row):
    if row["status"] == "canceled":
        return dto(row)
    if row["status"] != "queued" or row["attempt_id"] is not None:
        raise Problem(409, "run_state_conflict", "conflict", "Run cannot be canceled by this operation")
    # No dispatcher exists in B1; guard nevertheless prevents an inconsistent
    # outbox claim from being falsely represented as settled queued cancellation.
    outbox = conn.execute(text("""SELECT state FROM run_outbox WHERE run_id=:id
        AND command='start' FOR UPDATE"""), {"id": row["id"]}).scalars().all()
    if outbox != ["pending"]:
        raise Problem(409, "run_dispatch_conflict", "conflict", "Run dispatch requires reconciliation")
    sequence = row["next_event_sequence"]
    conn.execute(text("""INSERT INTO run_events(run_id,sequence,type,payload)
        VALUES(:id,:s,'cancel_requested','{"status":"cancel_requested"}'::jsonb),
              (:id,:n,'canceled','{"status":"canceled","reason":"canceled_before_dispatch"}'::jsonb)"""),
        {"id": row["id"], "s": sequence, "n": sequence + 1})
    conn.execute(text("UPDATE run_outbox SET state='suppressed' WHERE run_id=:id AND command='start'"), {"id": row["id"]})
    current = conn.execute(text("""UPDATE runs SET status='canceled',revision=revision+2,
        cancel_requested_at=now(),finished_at=now(),terminal_reason='canceled_before_dispatch',
        next_event_sequence=next_event_sequence+2 WHERE id=:id RETURNING *"""), {"id": row["id"]}).mappings().one()
    return dto(current)


def replay(conn, row, after, limit):
    if after >= row["next_event_sequence"]:
        raise Problem(409, "event_cursor_ahead", "conflict", "Event cursor is ahead of persisted history")
    rows = conn.execute(text("""SELECT * FROM run_events WHERE run_id=:id
        AND sequence>:after ORDER BY sequence LIMIT :limit"""),
        {"id": row["id"], "after": after, "limit": limit+1}).mappings().all()
    items = [RunEvent.model_validate(dict(event)) for event in rows[:limit]]
    return {"schema_version": 1, "run_id": row["id"], "items": items,
            "next_after": items[-1].sequence if items else after, "has_more": len(rows) > limit}


@dataclass(frozen=True)
class AttemptToken:
    run_id: UUID
    attempt_id: UUID
    fence: int
    revision: int
    lease_expires_at: datetime


def locked_run(conn, run_id):
    row = conn.execute(text("SELECT * FROM runs WHERE id=:id FOR UPDATE"), {"id": run_id}).mappings().one_or_none()
    if row is None:
        raise Problem(404, "run_unavailable", "not_found", "Run unavailable")
    return dict(row)


def work_authority(conn, row):
    """Stored requesting principal plus current grant; scope is only a ceiling."""
    allowed = conn.execute(text("""SELECT can_write FROM case_grants
        WHERE principal_id=:p AND case_id=:c FOR SHARE"""),
        {"p": row["requested_by"], "c": row["case_id"]}).scalar_one_or_none()
    if allowed is not True:
        raise Problem(403, "run_authority_revoked", "forbidden", "Run authority unavailable")
    scope = row["scope_snapshot"]
    ids = [item["association_id"] for item in row["input_refs"]]
    if (row["kind"] != "synthetic-read-only-v1" or row["policy_version"] != "local-read-only-v1"
        or scope != {"principal_id": str(row["requested_by"]), "case_id": str(row["case_id"]),
                     "operation": row["kind"], "association_ids": ids}):
        raise Problem(403, "run_scope_changed", "forbidden", "Run scope unavailable")
    refs = [InputRef.model_validate({key: item[key] for key in ("association_id", "revision", "sha256")})
            for item in row["input_refs"]]
    if snapshot_inputs(conn, row["case_id"], refs) != row["input_refs"]:
        raise Problem(409, "run_input_conflict", "conflict", "Run inputs changed")


def _revision(row, expected):
    if type(expected) is not int or expected < 1 or row["revision"] != expected:
        raise Problem(409, "stale_revision", "conflict", "Run revision is stale")


def _lease_seconds(row, seconds):
    if type(seconds) is not int or not 1 <= seconds <= min(60, row["budget"]["wall_seconds"]):
        raise Problem(422, "invalid_lease", "validation", "Invalid bounded lease")


def _wall_budget(conn, row):
    if row["started_at"] is not None:
        live = conn.execute(text("SELECT clock_timestamp()<CAST(:started AS timestamptz)+:seconds*interval '1 second'"),
            {"started": row["started_at"], "seconds": row["budget"]["wall_seconds"]}).scalar_one()
        if not live:
            raise Problem(409, "run_budget_expired", "conflict", "Synthetic execution wall budget expired")


def _event(conn, row, kind, attempt_id=None):
    conn.execute(text("""INSERT INTO run_events(run_id,sequence,type,attempt_id,payload)
        VALUES(:r,:s,:kind,:attempt,CAST(:payload AS jsonb))"""),
        {"r": row["id"], "s": row["next_event_sequence"], "kind": kind,
         "attempt": attempt_id, "payload": encode({"status": kind})})
    conn.execute(text("UPDATE runs SET next_event_sequence=next_event_sequence+1 WHERE id=:r"), {"r": row["id"]})


def _token(conn, run_id):
    row = conn.execute(text("""SELECT r.id,r.attempt_id,r.fence,r.revision,a.lease_expires_at
        FROM runs r JOIN run_attempts a ON a.id=r.attempt_id WHERE r.id=:r"""), {"r": run_id}).one()
    return AttemptToken(row.id, row.attempt_id, row.fence, row.revision, row.lease_expires_at)


def claim_attempt(conn, run_id, external_id, worker_id, expected_revision, lease_seconds=5):
    row = locked_run(conn, run_id)
    _revision(row, expected_revision)
    work_authority(conn, row)
    _lease_seconds(row, lease_seconds)
    _wall_budget(conn, row)
    if not isinstance(worker_id, str) or not 1 <= len(worker_id) <= 100:
        raise Problem(422, "invalid_worker", "validation", "Invalid worker identity")
    if row["status"] not in ("queued", "interrupted"):
        raise Problem(409, "run_attempt_conflict", "conflict", "Run does not admit an attempt")
    mapped = conn.execute(text("""SELECT e.id FROM run_scheduler_executions e
        JOIN run_outbox o ON o.id=e.outbox_id WHERE e.run_id=:r AND e.external_id=:external
        AND e.scheduler_kind='fake-v1' AND o.state='acknowledged'"""),
        {"r": run_id, "external": external_id}).scalar_one_or_none()
    if mapped is None:
        raise Problem(409, "execution_unmapped", "conflict", "Execution is not reconciled")
    count = conn.execute(text("SELECT count(*) FROM run_attempts WHERE run_id=:r"), {"r": run_id}).scalar_one()
    if count >= 2:
        raise Problem(409, "attempt_limit", "conflict", "Synthetic recovery attempt limit reached")
    attempt, fence = uuid4(), row["fence"] + 1
    conn.execute(text("""INSERT INTO run_attempts(id,run_id,fence,state,worker_id,lease_expires_at)
        VALUES(:id,:r,:f,'running',:worker,LEAST(clock_timestamp()+:seconds*interval '1 second',
        COALESCE(CAST(:started AS timestamptz),clock_timestamp())+:wall*interval '1 second'))"""),
        {"id": attempt, "r": run_id, "f": fence, "worker": worker_id, "seconds": lease_seconds,
         "started": row["started_at"], "wall": row["budget"]["wall_seconds"]})
    usage = UnusedUsage(provenance="Synthetic execution; no provider or tools").model_dump()
    conn.execute(text("""UPDATE runs SET status='running',attempt_id=:a,fence=:f,
        revision=revision+1,started_at=COALESCE(started_at,clock_timestamp()),
        finished_at=NULL,terminal_reason=NULL,usage=CAST(:usage AS jsonb) WHERE id=:r"""),
        {"a": attempt, "f": fence, "usage": encode(usage), "r": run_id})
    _event(conn, row, "running", attempt)
    return _token(conn, run_id)


def _active(conn, token, expected_revision):
    row = locked_run(conn, token.run_id)
    _revision(row, expected_revision)
    if (row["status"] != "running" or row["attempt_id"] != token.attempt_id
        or row["fence"] != token.fence):
        raise Problem(409, "stale_attempt", "conflict", "Attempt is not current")
    live = conn.execute(text("""SELECT id FROM run_attempts WHERE id=:a AND run_id=:r
        AND fence=:f AND state='running' AND lease_expires_at>clock_timestamp() FOR UPDATE"""),
        {"a": token.attempt_id, "r": token.run_id, "f": token.fence}).scalar_one_or_none()
    if live is None:
        raise Problem(409, "lease_expired", "conflict", "Attempt lease is not live")
    work_authority(conn, row)
    _wall_budget(conn, row)
    # Authority/input SHARE locks above may have waited across lease expiry.
    # Keep Run -> attempt lock order, but validate DB time again after every
    # potentially blocking authority check before admitting work or renewal.
    live_after_authority = conn.execute(text("""SELECT id FROM run_attempts
        WHERE id=:a AND run_id=:r AND fence=:f AND state='running'
        AND lease_expires_at>clock_timestamp()"""),
        {"a": token.attempt_id, "r": token.run_id, "f": token.fence}).scalar_one_or_none()
    if live_after_authority is None:
        raise Problem(409, "lease_expired", "conflict", "Attempt lease is not live")
    return row


def admit_work(conn, token, expected_revision):
    """A harmless admission check only; no tool/provider/command is executed."""
    row = _active(conn, token, expected_revision)
    return tuple(InputSnapshot.model_validate(item) for item in row["input_refs"])


def renew_attempt(conn, token, expected_revision, lease_seconds=5):
    row = _active(conn, token, expected_revision)
    _lease_seconds(row, lease_seconds)
    conn.execute(text("""UPDATE run_attempts SET lease_expires_at=
        LEAST(clock_timestamp()+:seconds*interval '1 second',
        CAST(:started AS timestamptz)+:wall*interval '1 second') WHERE id=:a"""),
        {"a": token.attempt_id, "seconds": lease_seconds,
         "started": row["started_at"], "wall": row["budget"]["wall_seconds"]})
    conn.execute(text("UPDATE runs SET revision=revision+1 WHERE id=:r"), {"r": row["id"]})
    _event(conn, row, "lease_renewed", token.attempt_id)
    return _token(conn, token.run_id)


def expire_attempt(conn, run_id, expected_revision):
    row = locked_run(conn, run_id)
    _revision(row, expected_revision)
    if row["status"] != "running":
        raise Problem(409, "run_attempt_conflict", "conflict", "Run has no running attempt")
    expired = conn.execute(text("""UPDATE run_attempts SET state='expired',finished_at=clock_timestamp()
        WHERE id=:a AND fence=:f AND state='running' AND lease_expires_at<=clock_timestamp()
        RETURNING id"""), {"a": row["attempt_id"], "f": row["fence"]}).scalar_one_or_none()
    if expired is None:
        raise Problem(409, "lease_live", "conflict", "Attempt lease has not expired")
    # Only the fixed harmless kind can recover. Unknown effects use mark_failed(...,
    # uncertain=True) and are terminal, never automatically promoted to safe retry.
    conn.execute(text("""UPDATE runs SET status='interrupted',terminal_reason='lease_expired',
        revision=revision+1,fence=fence+1,finished_at=clock_timestamp() WHERE id=:r"""), {"r": run_id})
    _event(conn, row, "interrupted", row["attempt_id"])
    return dto(locked_run(conn, run_id))


def mark_failed(conn, token, expected_revision, *, uncertain=False):
    row = _active(conn, token, expected_revision)
    status, reason = ("uncertain", "uncertain_effect") if uncertain else ("failed", "synthetic_failure")
    conn.execute(text("UPDATE run_attempts SET state=:s,finished_at=clock_timestamp() WHERE id=:a"),
        {"s": status, "a": token.attempt_id})
    conn.execute(text("""UPDATE runs SET status=:s,terminal_reason=:reason,revision=revision+1,
        finished_at=clock_timestamp() WHERE id=:r"""), {"s": status, "reason": reason, "r": token.run_id})
    _event(conn, row, status, token.attempt_id)
    return dto(locked_run(conn, token.run_id))


def complete_attempt(conn, token, expected_revision, output_key, content):
    if (not isinstance(output_key, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", output_key)
        or type(content) is not dict or set(content) != {"value"}
        or type(content["value"]) is not str or len(content["value"]) > 1024):
        raise Problem(422, "invalid_synthetic_output", "validation", "Invalid bounded synthetic output")
    canonical = encode(content)
    if len(canonical.encode("utf-8")) > 8192:
        raise Problem(422, "invalid_synthetic_output", "validation", "Synthetic output exceeds byte limit")
    sha = hashlib.sha256(canonical.encode()).hexdigest()
    row = locked_run(conn, token.run_id)
    work_authority(conn, row)
    existing = conn.execute(text("SELECT * FROM run_outputs WHERE run_id=:r AND output_key=:k"),
        {"r": token.run_id, "k": output_key}).mappings().one_or_none()
    if row["status"] == "succeeded" and existing:
        # Lost completion acknowledgement: exact original command replays committed
        # canonical result, without treating a stale revision as a fresh mutation.
        if (row["attempt_id"] != token.attempt_id or row["fence"] != token.fence
            or existing["attempt_id"] != token.attempt_id or existing["fence"] != token.fence
            or existing["sha256"] != sha or existing["content"] != content
            or type(expected_revision) is not int or existing["expected_revision"] != expected_revision):
            raise Problem(409, "output_conflict", "conflict", "Output publication conflicts with committed result")
        return dto(row)
    row = _active(conn, token, expected_revision)
    if existing:
        raise Problem(409, "output_conflict", "conflict", "Output publication requires reconciliation")
    output_id = uuid4()
    conn.execute(text("""INSERT INTO run_outputs(id,run_id,output_key,sha256,content,attempt_id,fence,expected_revision)
        VALUES(:id,:r,:k,:sha,CAST(:content AS jsonb),:a,:f,:revision)"""),
        {"id": output_id, "r": token.run_id, "k": output_key, "sha": sha, "content": canonical,
         "a": token.attempt_id, "f": token.fence, "revision": expected_revision})
    refs = [{"id": str(output_id), "kind": "run_output", "sha256": sha}]
    conn.execute(text("""UPDATE runs SET status='succeeded',outcome='synthetic_complete',
        terminal_reason=NULL,output_refs=CAST(:refs AS jsonb),revision=revision+1,
        finished_at=clock_timestamp() WHERE id=:r"""), {"refs": encode(refs), "r": token.run_id})
    conn.execute(text("UPDATE run_attempts SET state='completed',finished_at=clock_timestamp() WHERE id=:a"), {"a": token.attempt_id})
    _event(conn, row, "succeeded", token.attempt_id)
    return dto(locked_run(conn, token.run_id))
