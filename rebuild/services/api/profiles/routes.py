from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from services.api.contracts import Capability
from services.api.db import digest
from services.api.errors import Problem
from services.api.profiles import repository
from services.api.profiles.contracts import (ProviderProfileCreate, ProviderProfileUpdate,
    ProviderProfileView, ProviderProfilePage, ProviderProfileDiagnostics)


@dataclass(frozen=True)
class ProfileBindings:
    engine: Callable
    principal: Callable
    idem: Callable
    save_idem: Callable


def build_router(b: ProfileBindings):
    router = APIRouter(prefix="/api/v1/cases/{case_id}/provider-profiles")

    @router.post("", response_model=ProviderProfileView, status_code=201, operation_id="create_provider_profile")
    def create(case_id: UUID, body: ProviderProfileCreate, principal_id=Depends(b.principal),
               key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        operation = "create_provider_profile:" + str(case_id)
        fingerprint = digest(body.model_dump(mode="json"))
        with b.engine().begin() as conn:
            repository.grant(conn, principal_id, case_id, write=True)
            replay = b.idem(conn, principal_id, operation, key, fingerprint)
            if replay is not None:
                return replay
            result = repository.append(conn, principal_id, case_id, body.model_dump(mode="json")).model_dump(mode="json")
            b.save_idem(conn, principal_id, operation, key, fingerprint, result, 201)
        return JSONResponse(result, status_code=201)

    @router.get("", response_model=ProviderProfilePage, operation_id="list_provider_profiles")
    def listing(case_id: UUID, principal_id=Depends(b.principal),
                cursor: UUID | None = None, limit: int = Query(default=25, ge=1, le=100)):
        with b.engine().begin() as conn:
            repository.grant(conn, principal_id, case_id)
            rows = conn.execute(text("SELECT DISTINCT ON (profile_id) * FROM provider_profile_versions "
                                     "WHERE case_id=:c AND profile_id>:after ORDER BY profile_id,revision DESC LIMIT :limit"),
                                {"c": case_id, "after": cursor or UUID(int=0), "limit": limit+1}).mappings().all()
            return ProviderProfilePage(items=[repository.dto(row) for row in rows[:limit]],
                                       next_cursor=str(rows[limit-1]["profile_id"]) if len(rows)>limit else None)

    @router.get("/{profile_id}", response_model=ProviderProfileView, operation_id="get_provider_profile")
    def get(case_id: UUID, profile_id: UUID, principal_id=Depends(b.principal)):
        with b.engine().begin() as conn:
            repository.grant(conn, principal_id, case_id)
            return repository.dto(repository.current(conn, case_id, profile_id))

    @router.patch("/{profile_id}", response_model=ProviderProfileView, operation_id="update_provider_profile")
    def update(case_id: UUID, profile_id: UUID, body: ProviderProfileUpdate, principal_id=Depends(b.principal),
               key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        operation = "update_provider_profile:" + str(case_id) + ":" + str(profile_id)
        fingerprint = digest(body.model_dump(mode="json", exclude_unset=True))
        with b.engine().begin() as conn:
            repository.grant(conn, principal_id, case_id, write=True)
            row = repository.current(conn, case_id, profile_id, locked=True)
            replay = b.idem(conn, principal_id, operation, key, fingerprint)
            if replay is not None:
                return replay
            if row["revision"] != body.expected_revision:
                raise Problem(409, "stale_revision", "conflict", "Profile revision is stale")
            if body.enabled is True:
                raise Problem(409, "profile_unconfigured", "conflict", "Profile has no attached credential binding")
            values = repository.dto(row).model_dump(mode="json")
            values.update(body.model_dump(mode="json", exclude_unset=True))
            result = repository.append(conn, principal_id, case_id, values, profile_id, row["revision"]+1).model_dump(mode="json")
            b.save_idem(conn, principal_id, operation, key, fingerprint, result, 200)
        return result

    @router.get("/{profile_id}/diagnostics", response_model=ProviderProfileDiagnostics,
                operation_id="get_provider_profile_diagnostics")
    def diagnostics(case_id: UUID, profile_id: UUID, principal_id=Depends(b.principal)):
        with b.engine().begin() as conn:
            repository.grant(conn, principal_id, case_id)
            row = repository.current(conn, case_id, profile_id)
            return ProviderProfileDiagnostics(profile_id=profile_id, revision=row["revision"], features={
                "enrollment": Capability(status="unsupported", reason="Profile enrollment bridge deferred"),
                **{name: Capability(status="unverified", reason="No credential-store or provider operation performed")
                   for name in ("store_availability", "credential_validity", "tools", "schema", "streaming", "hosted_search")}})

    return router
