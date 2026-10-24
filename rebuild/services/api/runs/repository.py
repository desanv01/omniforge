"""Explicit B1 domain transactions; every function uses the caller's connection.

No commit, scheduler submission, attempt claim or tool execution occurs here.
"""
import json
from uuid import uuid4

from sqlalchemy import text
from starlette.exceptions import HTTPException

from services.api.errors import Problem
from services.api.runs.contracts import InputSnapshot, Run, RunEvent, UnusedUsage


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
