"""Closed-purpose metadata authority. Enrollment and positive execution are deferred.

No store, prompt, provider or network dependency is constructed here. The absence
of an attached binding is an explicit denial, never a synthetic execution grant.
"""
from enum import Enum

from adapters.models.contracts import Budget
from services.api.errors import Problem
from services.api.profiles import repository
from services.api.profiles.contracts import CAP_FIELDS, ProviderProfileView


class Purpose(str, Enum):
    CONFIGURE = "configure"
    ENROLL = "enroll"
    EXECUTE_DIAGNOSTIC = "execute_diagnostic"


def narrow_budget(caps: Budget, requested: Budget) -> Budget:
    if any(getattr(requested, field) > getattr(caps, field) for field in CAP_FIELDS):
        raise Problem(422, "profile_budget_exceeded", "validation", "Requested budget exceeds profile caps")
    return requested


def load_profile(engine, principal_id, case_id, profile_id, expected_revision, purpose):
    try:
        purpose = Purpose(purpose)
    except (ValueError, TypeError):
        raise Problem(403, "profile_purpose_denied", "forbidden", "Profile purpose denied") from None
    with engine.begin() as conn:
        repository.grant(conn, principal_id, case_id, write=True)
        row = repository.current(conn, case_id, profile_id, locked=True)
        if row["revision"] != expected_revision:
            raise Problem(409, "stale_revision", "conflict", "Profile revision is stale")
        snapshot = repository.dto(row)
        if purpose != Purpose.CONFIGURE:
            # No enrollment table/bridge yet; disabled/unconfigured always deny.
            raise Problem(403, "profile_unconfigured", "forbidden", "Profile is disabled and unconfigured")
        return snapshot


def bind_authorize_profile(engine, principal_id, case_id, pinned_snapshot: ProviderProfileView, purpose):
    # Serialize to detach from mutable caller models. Full view includes case,
    # revision, endpoint/model/caps, enabled and recorded binding status.
    pinned = pinned_snapshot.model_dump(mode="json")
    def authorize(candidate):
        try:
            current = load_profile(engine, principal_id, case_id, pinned_snapshot.id,
                                   pinned["revision"], purpose)
            # This metadata callback cannot authorize adapter Profile execution;
            # such a Profile has no case/caps/attached binding proof.
            return (type(candidate) is ProviderProfileView and
                    current.model_dump(mode="json") == pinned == candidate.model_dump(mode="json"))
        except Exception:
            return False
    return authorize
