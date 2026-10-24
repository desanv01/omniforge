"""Local authenticated core. Explicit configuration never discovers legacy resources."""
import base64
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from services.api import evidence
from services.api.contracts import (ArtifactAssociation, ArtifactPage, Capabilities, Capability, Case,
                                   CaseCreate, CasePage, DependencyHealth, ERROR_RESPONSES,
                                   ErrorEnvelope, Health)
from services.api.db import MIGRATION, digest, engine_for, lock, migration_at
from services.api.errors import Problem, response
from services.api.settings import Settings
from packages.contracts.evidence.capture import parse_capture
from services.api.evidence_access import bind_read_range
from services.api.runs.routes import RunBindings, build_router
from services.api.profiles.routes import ProfileBindings, build_router as profile_router

bearer = HTTPBearer(auto_error=False)


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        yield
        if app.state.engine:
            app.state.engine.dispose()

    app = FastAPI(title="OmniForge API", version="0.2.0", responses=ERROR_RESPONSES,
                  servers=[{"url": "/"}], lifespan=lifespan)
    app.state.engine = engine_for(settings) if settings else None
    app.state.settings = settings

    @app.middleware("http")
    async def request_identity(request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        try:
            result = await call_next(request)
        except SQLAlchemyError:
            result = response(request_id, 503, "database_unavailable", "storage", "Database unavailable", True)
        except OSError:
            result = response(request_id, 503, "storage_unavailable", "storage", "Storage unavailable", True)
        except Exception:
            result = response(request_id, 500, "internal_error", "internal", "Request failed")
        result.headers["X-Request-ID"] = request_id
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    @app.exception_handler(Problem)
    async def domain_error(request, exc):
        return response(request.state.request_id, exc.status, exc.code, exc.category, exc.message, exc.retryable)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        mapping = {
            401: ("authentication_required", "unauthenticated", "Bearer authentication required"),
            403: ("grant_required", "forbidden", "Case grant required"),
            404: ("not_found", "not_found", "Resource not found"),
            405: ("method_not_allowed", "method_not_allowed", "Method not allowed"),
        }
        code, category, message = mapping.get(exc.status_code, ("request_rejected", "validation", "Request rejected"))
        headers = {}
        for key, value in (exc.headers or {}).items():
            if key.lower() in {"allow", "www-authenticate", "retry-after"} and len(value) <= 200 and "\r" not in value and "\n" not in value:
                headers[key] = value
        return response(request.state.request_id, exc.status_code, code, category, message, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return response(request.state.request_id, 422, "invalid_request", "validation", "Request validation failed")

    def engine():
        if app.state.engine is None:
            raise Problem(503, "core_unconfigured", "storage", "Core is not configured", True)
        return app.state.engine

    def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != "bearer" or len(credentials.credentials) > 256:
            raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
        token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        with engine().connect() as conn:
            principal_id = conn.execute(text("SELECT id FROM principals WHERE token_hash=:hash"), {"hash": token_hash}).scalar_one_or_none()
        if principal_id is None:
            raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
        return principal_id

    def require_grant(conn, principal_id, case_id, write=False):
        allowed = conn.execute(text("SELECT can_write FROM case_grants WHERE principal_id=:p AND case_id=:c"), {"p": principal_id, "c": case_id}).scalar_one_or_none()
        if allowed is None or (write and not allowed):
            raise HTTPException(403)

    def idem(conn, principal_id, operation, key, body_hash):
        lock(conn, f"idem:{principal_id}:{operation}:{key}")
        old = conn.execute(text("SELECT body_hash,response,status FROM idempotency WHERE principal_id=:p AND operation=:o AND key=:k"), {"p": principal_id, "o": operation, "k": key}).mappings().one_or_none()
        if old and old["body_hash"] != body_hash:
            raise Problem(409, "idempotency_conflict", "conflict", "Idempotency key was used with different input")
        return JSONResponse(old["response"], status_code=old["status"]) if old else None

    def save_idem(conn, principal_id, operation, key, body_hash, body, status):
        conn.execute(text("INSERT INTO idempotency(principal_id,operation,key,body_hash,response,status) VALUES(:p,:o,:k,:h,CAST(:r AS jsonb),:s)"),
                     {"p": principal_id, "o": operation, "k": key, "h": body_hash, "r": json.dumps(body), "s": status})

    @app.get("/api/v1/system/health", response_model=Health, operation_id="get_system_health")
    def health():
        database = DependencyHealth(status="not_connected")
        artifacts = DependencyHealth(status="not_connected")
        version = None
        if settings:
            try:
                with engine().connect() as conn:
                    version = migration_at(conn)
                database = DependencyHealth(status="ready" if version == MIGRATION else "unavailable", ready=version == MIGRATION)
            except SQLAlchemyError:
                database = DependencyHealth(status="unavailable")
            available = all((settings.artifact_root / name).is_dir() and os.access(settings.artifact_root / name, os.R_OK | os.W_OK) for name in ("staging", "blobs"))
            artifacts = DependencyHealth(status="ready" if available else "unavailable", ready=available)
        return Health(database=database, artifacts=artifacts,
                      provider=DependencyHealth(status="unverified"), scheduler=DependencyHealth(status="unverified"),
                      migration_version=version)

    @app.get("/api/v1/capabilities", response_model=Capabilities, operation_id="get_capabilities")
    def capabilities(principal_id=Depends(principal)):
        state = health()
        available = state.database.ready and state.artifacts.ready
        return Capabilities(features={
            "cases": Capability(status="available" if state.database.ready else "unverified", reason="Local authenticated PostgreSQL case API"),
            "artifacts": Capability(status="available" if available else "unverified", reason="Bounded local multipart and byte ranges"),
            "provider": Capability(status="unverified", reason="Provider proof pending"),
            "scheduler": Capability(status="unverified", reason="Scheduler recovery proof pending"),
            "executor": Capability(status="unsupported", reason="No isolated executor configured"),
        })

    @app.post("/api/v1/cases", response_model=Case, status_code=201, operation_id="create_case")
    def create_case(body: CaseCreate, principal_id=Depends(principal),
                    key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        if body.policy_profile_ref != "local-read-only-v1":
            raise Problem(422, "unknown_policy", "validation", "Policy profile is unsupported")
        fingerprint = digest(body.model_dump())
        with engine().begin() as conn:
            replay = idem(conn, principal_id, "create_case", key, fingerprint)
            if replay is not None:
                return replay
            case_id = uuid4()
            row = conn.execute(text("INSERT INTO cases(id,revision,title,objective,policy_profile_ref) VALUES(:id,1,:title,:objective,:policy_profile_ref) RETURNING *"), {"id": case_id, **body.model_dump()}).mappings().one()
            conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,true)"), {"p": principal_id, "c": case_id})
            result = Case.model_validate(dict(row)).model_dump(mode="json")
            save_idem(conn, principal_id, "create_case", key, fingerprint, result, 201)
        return JSONResponse(result, status_code=201)

    @app.get("/api/v1/cases", response_model=CasePage, operation_id="list_cases")
    def list_cases(principal_id=Depends(principal), cursor: str | None = Query(default=None, max_length=100), limit: int = Query(default=25, ge=1, le=100)):
        after = UUID(int=0)
        if cursor:
            try:
                after = UUID(base64.urlsafe_b64decode(cursor).decode("ascii"))
            except (ValueError, UnicodeError):
                raise Problem(422, "invalid_cursor", "validation", "Invalid page cursor") from None
        with engine().connect() as conn:
            rows = conn.execute(text("SELECT c.* FROM cases c JOIN case_grants g ON g.case_id=c.id WHERE g.principal_id=:p AND c.id>:after ORDER BY c.id LIMIT :limit"), {"p": principal_id, "after": after, "limit": limit+1}).mappings().all()
        items = [Case.model_validate(dict(row)) for row in rows[:limit]]
        next_cursor = base64.urlsafe_b64encode(str(items[-1].id).encode()).decode() if len(rows) > limit else None
        return CasePage(items=items, next_cursor=next_cursor)

    @app.get("/api/v1/cases/{case_id}", response_model=Case, operation_id="get_case")
    def get_case(case_id: UUID, principal_id=Depends(principal)):
        with engine().connect() as conn:
            require_grant(conn, principal_id, case_id)
            row = conn.execute(text("SELECT * FROM cases WHERE id=:id"), {"id": case_id}).mappings().one()
        return Case.model_validate(dict(row))

    def permitted_association(conn, principal_id, association_id):
        found = conn.execute(text(evidence.ASSOCIATION_SQL + " JOIN case_grants g ON g.case_id=a.case_id WHERE a.id=:id AND g.principal_id=:p"), {"id": association_id, "p": principal_id}).mappings().one_or_none()
        if found is None:
            raise HTTPException(404)
        return dict(found)

    @app.get("/api/v1/cases/{case_id}/artifacts", response_model=ArtifactPage, operation_id="list_case_artifacts")
    def list_artifacts(case_id: UUID, principal_id=Depends(principal),
                       cursor: str | None = Query(default=None, max_length=100),
                       limit: int = Query(default=25, ge=1, le=100)):
        after = UUID(int=0)
        if cursor:
            try:
                after = UUID(base64.urlsafe_b64decode(cursor).decode("ascii"))
            except (ValueError, UnicodeError):
                raise Problem(422, "invalid_cursor", "validation", "Invalid page cursor") from None
        with engine().connect() as conn:
            require_grant(conn, principal_id, case_id)
            rows = conn.execute(text(evidence.ASSOCIATION_SQL + " WHERE a.case_id=:case AND a.id>:after ORDER BY a.id LIMIT :limit"),
                                {"case": case_id, "after": after, "limit": limit+1}).mappings().all()
        items = [ArtifactAssociation.model_validate(dict(row)) for row in rows[:limit]]
        next_cursor = base64.urlsafe_b64encode(str(items[-1].id).encode()).decode() if len(rows) > limit else None
        return ArtifactPage(items=items, next_cursor=next_cursor)

    upload_schema = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {"type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}}}}}}}

    @app.post("/api/v1/cases/{case_id}/artifacts", response_model=ArtifactAssociation, status_code=201,
              responses={202: {"model": ArtifactAssociation, "description": "Durably staged; publication pending"}},
              openapi_extra=upload_schema, operation_id="upload_artifact")
    async def upload_artifact(case_id: UUID, request: Request, principal_id=Depends(principal),
                              expected_revision: int = Query(ge=1), captured_at: str | None = Query(default=None, max_length=40),
                              key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        with engine().connect() as conn:
            require_grant(conn, principal_id, case_id, write=True)
        try:
            capture = parse_capture(captured_at)
        except (ValueError, TypeError):
            raise Problem(422, "invalid_capture_time", "validation", "captured_at requires a valid RFC3339 timestamp and offset") from None
        item = evidence.Upload(settings.artifact_root, request.headers.get("content-type", ""), settings.upload_limit)
        await item.receive(request)
        fingerprint = digest({"hash": item.hash.hexdigest(), "bytes": item.size, "name": item.original_name,
                              "mime": item.media_type, "captured_at": captured_at,
                              "expected_revision": expected_revision})
        operation = "upload:" + str(case_id)
        association_id = uuid4()
        with engine().begin() as conn:
            require_grant(conn, principal_id, case_id, write=True)
            replay = idem(conn, principal_id, operation, key, fingerprint)
            if replay is not None:
                return replay
            revision = conn.execute(text("SELECT revision FROM cases WHERE id=:id FOR UPDATE"), {"id": case_id}).scalar_one()
            if revision != expected_revision:
                raise Problem(409, "stale_revision", "conflict", "Case revision is stale")
            conn.execute(text("INSERT INTO artifacts(id,sha256,bytes) VALUES(:id,:hash,:bytes) ON CONFLICT(sha256) DO NOTHING"), {"id": uuid4(), "hash": item.hash.hexdigest(), "bytes": item.size})
            artifact_id = conn.execute(text("SELECT id FROM artifacts WHERE sha256=:hash"), {"hash": item.hash.hexdigest()}).scalar_one()
            conn.execute(text("INSERT INTO artifact_associations(id,case_id,artifact_id,source_id,original_name,media_type,captured_at,captured_at_original,captured_at_offset,captured_at_provenance,publication_status,stage_name) VALUES(:id,:case,:artifact,:source,:name,:mime,:captured_at,:captured_at_original,:captured_at_offset,:captured_at_provenance,'pending',:stage)"),
                         {"id": association_id, "case": case_id, "artifact": artifact_id, "source": uuid4(), "name": item.original_name, "mime": item.media_type, **capture, "stage": item.name})
            conn.execute(text("UPDATE cases SET revision=revision+1,updated_at=now() WHERE id=:id"), {"id": case_id})
            result = ArtifactAssociation.model_validate(evidence.association(conn, association_id)).model_dump(mode="json")
            save_idem(conn, principal_id, operation, key, fingerprint, result, 202)
        try:
            with engine().begin() as conn:
                conn.execute(text("SELECT id FROM artifact_associations WHERE id=:id FOR UPDATE"), {"id": association_id})
                published = ArtifactAssociation.model_validate(evidence.publish(conn, settings.artifact_root, association_id)).model_dump(mode="json")
            return JSONResponse(published, status_code=201)
        except (Problem, OSError, SQLAlchemyError):
            return JSONResponse(result, status_code=202)

    @app.get("/api/v1/artifacts/{association_id}", response_model=ArtifactAssociation, operation_id="get_artifact_association")
    def get_artifact(association_id: UUID, principal_id=Depends(principal)):
        with engine().connect() as conn:
            return ArtifactAssociation.model_validate(permitted_association(conn, principal_id, association_id))

    @app.get("/api/v1/artifacts/{association_id}/ranges", response_class=Response, operation_id="read_artifact_range",
             responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
                              "headers": {name: {"schema": {"type": "string"}} for name in ("X-Artifact-SHA256", "X-Start-Byte", "X-End-Byte", "X-Total-Bytes")}}})
    def read_range(association_id: UUID, principal_id=Depends(principal), start_byte: int = Query(ge=0), end_byte: int = Query(gt=0)):
        with engine().connect() as conn:
            item = permitted_association(conn, principal_id, association_id)
        read = bind_read_range(engine(), settings.artifact_root, principal_id, item["case_id"])
        data = read(association_id, item["sha256"], start_byte, end_byte)
        return Response(data, media_type="application/octet-stream", headers={
            "X-Artifact-SHA256": item["sha256"], "X-Start-Byte": str(start_byte),
            "X-End-Byte": str(end_byte), "X-Total-Bytes": str(item["bytes"]),
        })

    app.include_router(build_router(RunBindings(engine, principal, require_grant, idem, save_idem)))
    app.include_router(profile_router(ProfileBindings(engine, principal, idem, save_idem)))
    return app


app = create_app(Settings.from_env())
