"""Closed-purpose current persisted metadata and exact attached adapter authority."""
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from adapters.models.contracts import Budget, Profile
from adapters.secrets.enrollment import EnrollmentBinding
from services.api.db import digest
from services.api.errors import Problem
from services.api.profiles import repository, bindings
from services.api.profiles.contracts import CAP_FIELDS, ProviderProfileView


class Purpose(str, Enum):
    CONFIGURE = "configure"
    ENROLL = "enroll"
    EXECUTE_DIAGNOSTIC = "execute_diagnostic"


@dataclass(frozen=True)
class BoundProfile:
    profile: Profile = field(repr=False)
    caps: Budget
    budget: Budget
    case_id: UUID
    binding: EnrollmentBinding = field(repr=False)
    metadata_digest: str


def narrow_budget(caps: Budget, requested: Budget) -> Budget:
    if type(caps) is not Budget or type(requested) is not Budget:
        raise Problem(422, "profile_budget_exceeded", "validation", "Validated budget required")
    # model_copy/update bypasses validation; validate a detached copy.
    caps = Budget.model_validate(caps.model_dump())
    requested = Budget.model_validate(requested.model_dump())
    if any(getattr(requested, name) > getattr(caps, name) for name in CAP_FIELDS):
        raise Problem(422, "profile_budget_exceeded", "validation", "Requested budget exceeds profile caps")
    return requested


def load_profile(engine, principal_id, case_id, profile_id, expected_revision, purpose, *, bearer_token=None, requested_budget=None):
    # Preserve invalid-purpose denial before opening a transaction.
    try:
        purpose = Purpose(purpose)
    except (ValueError, TypeError):
        raise Problem(403, "profile_purpose_denied", "forbidden", "Profile purpose denied") from None
    with engine.begin() as conn:
        return load_profile_conn(conn, principal_id, case_id, profile_id, expected_revision, purpose,
                                 bearer_token=bearer_token, requested_budget=requested_budget)


def load_profile_conn(conn, principal_id, case_id, profile_id, expected_revision, purpose, *, bearer_token=None, requested_budget=None, before_statement=None):
    """Current authority held on supplied connection; never commits or reconnects."""
    try:
        purpose = Purpose(purpose)
    except (ValueError, TypeError):
        raise Problem(403, "profile_purpose_denied", "forbidden", "Profile purpose denied") from None
    if before_statement is not None:
        # Narrow internal seam: each existing nested repository SQL acquisition
        # rearms bounds on the SAME underlying connection, without committing.
        supplied = conn
        class GuardedAuthorityConnection:
            def execute(self, statement, *args, **kwargs):
                before_statement()
                return supplied.execute(statement, *args, **kwargs)
        conn = GuardedAuthorityConnection()
    if purpose != Purpose.CONFIGURE:
        if bearer_token is None:
            raise Problem(403, "profile_purpose_denied", "forbidden", "Explicit local authority required")
        bindings.authenticate(conn, bearer_token, principal_id)
    repository.grant(conn, principal_id, case_id, write=True)
    row = repository.current(conn, case_id, profile_id, locked=True)
    if row["revision"] != expected_revision:
        raise Problem(409, "stale_revision", "conflict", "Profile revision is stale")
    snapshot = repository.dto(row)
    if purpose == Purpose.CONFIGURE:
        return snapshot
    if purpose == Purpose.ENROLL:
        raise Problem(403, "profile_purpose_denied", "forbidden", "Operation-bound enrollment required")
    if not row["enabled"]:
        raise Problem(403, "profile_disabled", "forbidden", "Profile is disabled")
    bound = bindings.attached_binding(conn, row)
    budget = narrow_budget(snapshot.caps, requested_budget or snapshot.caps)
    return BoundProfile(Profile(row["profile_id"], row["revision"], row["endpoint"], row["model"], bound.credential_ref),
                        snapshot.caps, budget, case_id, bound, digest(snapshot.model_dump(mode="json")))


def bind_authorize_profile(engine, principal_id, case_id, pinned_snapshot, purpose, *, bearer_token=None):
    if type(pinned_snapshot) is BoundProfile:
        pin = pinned_snapshot
        profile_values = (pin.profile.id, pin.profile.revision, pin.profile.endpoint, pin.profile.model, pin.profile.credential_ref.value)
        caps = pin.caps.model_dump(); budget = pin.budget.model_dump()
        bound_values = (*bindings.request_tuple(pin.binding), pin.binding.credential_ref.value)
        def authorize(candidate):
            try:
                if Purpose(purpose) != Purpose.EXECUTE_DIAGNOSTIC or case_id != pin.case_id or type(candidate) is not Profile:
                    return False
                current = load_profile(engine, principal_id, case_id, profile_values[0], profile_values[1], purpose,
                                       bearer_token=bearer_token, requested_budget=Budget(**budget))
                values = (candidate.id, candidate.revision, candidate.endpoint, candidate.model, candidate.credential_ref.value)
                return (values == profile_values and current == pin and current.caps.model_dump() == caps and
                        current.budget.model_dump() == budget and
                        (*bindings.request_tuple(current.binding), current.binding.credential_ref.value) == bound_values)
            except Exception:
                return False
        return authorize
    if type(pinned_snapshot) is not ProviderProfileView:
        return lambda candidate: False
    pinned = pinned_snapshot.model_dump(mode="json")
    def authorize(candidate):
        try:
            if Purpose(purpose) != Purpose.CONFIGURE:
                return False
            current = load_profile(engine, principal_id, case_id, UUID(pinned["id"]), pinned["revision"], purpose)
            return (type(candidate) is ProviderProfileView and
                    current.model_dump(mode="json") == pinned == candidate.model_dump(mode="json"))
        except Exception:
            return False
    return authorize
