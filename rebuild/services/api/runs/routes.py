"""B1 router binding to the existing trusted core authority and transaction seam."""
from dataclasses import dataclass
import re
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from services.api.db import digest
from services.api.errors import Problem
from services.api.runs import repository
from services.api.runs.contracts import Run, RunCancel, RunCreate, RunEventPage


@dataclass(frozen=True)
class RunBindings:
    engine: Callable
    principal: Callable
    require_grant: Callable
    idem: Callable
    save_idem: Callable
    event_principal: Callable | None = None
    stream_events: Callable | None = None


def accepts_sse(accept):
    """Specific q=0 excludes a range; generic wildcards retain JSON defaults."""
    if type(accept) is not str:
        return False
    ranges = {}
    for part in accept.lower().split(","):
        pieces = [p.strip() for p in part.split(";")]
        media, quality = pieces[0], 1.0
        weights = []
        for parameter in pieces[1:]:
            name, separator, value = parameter.partition("=")
            if name.strip() == "q":
                weights.append(value.strip() if separator else "")
        if weights:
            value = weights[0]
            quality = float(value) if len(weights) == 1 and re.fullmatch(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)", value) else 0.0
        ranges[media] = max(ranges.get(media, 0.0), quality)
    if "text/event-stream" not in ranges and "text/*" not in ranges:
        return False
    sse = ranges.get("text/event-stream", ranges.get("text/*", 0.0))
    json_quality = ranges.get("application/json", ranges.get("application/*", ranges.get("*/*", 0.0)))
    return sse > 0 and sse >= json_quality


def cursor(after, last):
    def parse(value):
        if value is None:
            return None
        # No signs, whitespace, scientific notation or decimal-point coercion.
        if not value or len(value) > 19 or not value.isascii() or not value.isdecimal():
            raise Problem(422, "invalid_event_cursor", "validation", "Invalid event cursor")
        result = int(value)
        if result > 9223372036854775807:
            raise Problem(422, "invalid_event_cursor", "validation", "Invalid event cursor")
        return result
    parsed_after, parsed_last = parse(after), parse(last)
    if parsed_after is not None and parsed_last is not None and parsed_after != parsed_last:
        raise Problem(409, "event_cursor_conflict", "conflict", "Event cursors disagree")
    return parsed_last if parsed_last is not None else (parsed_after if parsed_after is not None else 0)


def build_router(bindings: RunBindings):
    router = APIRouter()

    @router.post("/api/v1/cases/{case_id}/runs", response_model=Run, status_code=202,
                 operation_id="create_run")
    def create_run(case_id: UUID, body: RunCreate, principal_id=Depends(bindings.principal),
                   key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        operation = "create_run:" + str(case_id)
        fingerprint = digest(body.model_dump(mode="json"))
        with bindings.engine().begin() as conn:
            repository.grant(conn, bindings, principal_id, case_id)
            replay = bindings.idem(conn, principal_id, operation, key, fingerprint)
            if replay is not None:
                return replay
            result = repository.insert_queued(conn, principal_id, case_id, body).model_dump(mode="json")
            bindings.save_idem(conn, principal_id, operation, key, fingerprint, result, 202)
        return JSONResponse(result, status_code=202)

    @router.get("/api/v1/runs/{run_id}", response_model=Run, operation_id="get_run")
    def get_run(run_id: UUID, principal_id=Depends(bindings.principal)):
        with bindings.engine().connect() as conn:
            return repository.dto(repository.authorized_run(conn, principal_id, run_id))

    @router.post("/api/v1/runs/{run_id}/cancel", response_model=Run, operation_id="cancel_run")
    def cancel_run(run_id: UUID, body: RunCancel, principal_id=Depends(bindings.principal),
                   key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        operation = "cancel_run:" + str(run_id)
        fingerprint = digest(body.model_dump(mode="json"))
        with bindings.engine().begin() as conn:
            row = repository.authorized_run(conn, principal_id, run_id, write=True, locked=True)
            # Fresh current authority precedes even stored-response replay.
            bindings.require_grant(conn, principal_id, row["case_id"], write=True)
            replay = bindings.idem(conn, principal_id, operation, key, fingerprint)
            if replay is not None:
                return replay
            if row["revision"] != body.expected_revision:
                raise Problem(409, "stale_revision", "conflict", "Run revision is stale")
            result = repository.request_cancellation(conn, row, principal_id).model_dump(mode="json")
            bindings.save_idem(conn, principal_id, operation, key, fingerprint, result, 200)
        return result

    @router.get("/api/v1/runs/{run_id}/events", response_model=RunEventPage, operation_id="list_run_events",
                responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}})
    async def get_events(request: Request, run_id: UUID, identity=Depends(bindings.event_principal or bindings.principal),
                   after: str | None = Query(default=None, max_length=19),
                   limit: int = Query(default=100, ge=1, le=100),
                   last: str | None = Header(default=None, alias="Last-Event-ID", max_length=19),
                   accept: str | None = Header(default=None, alias="Accept", max_length=256)):
        after_value = cursor(after, last)
        if accepts_sse(accept):
            if bindings.event_principal is None or bindings.stream_events is None:
                raise Problem(503, "stream_unavailable", "storage", "Run streaming unavailable", True)
            return await bindings.stream_events(request, identity, run_id, after_value, limit)
        principal_id = identity if type(identity) is UUID else identity.principal_id
        def read_json():
            with bindings.engine().connect() as conn:
                row = repository.authorized_run(conn, principal_id, run_id)
                return repository.replay(conn, row, after_value, limit)
        return await run_in_threadpool(read_json)

    return router
