"""Trusted local enrollment callbacks; no input/store/network defaults."""
import hashlib

from sqlalchemy import text

from adapters.secrets.enrollment import EnrollmentBinding, EnrollmentReceipt, Reservation
from services.api.db import lock
from services.api.errors import Problem
from services.api.profiles import repository


def authenticate(conn, bearer_token, principal_id):
    if not isinstance(bearer_token, str) or not 1 <= len(bearer_token) <= 256:
        raise Problem(401, "local_auth_required", "unauthenticated", "Explicit local authentication required")
    found = conn.execute(text("SELECT id FROM principals WHERE token_hash=:h FOR SHARE"),
                         {"h": hashlib.sha256(bearer_token.encode()).hexdigest()}).scalar_one_or_none()
    if found != principal_id:
        raise Problem(401, "local_auth_required", "unauthenticated", "Explicit local authentication required")


def authority(conn, bearer_token, request):
    authenticate(conn, bearer_token, request.principal_id)
    repository.grant(conn, request.principal_id, request.case_id, write=True)
    return repository.current(conn, request.case_id, request.profile_id, locked=True)


def request_tuple(value):
    return (value.operation_id, value.principal_id, value.case_id, value.profile_id, value.expected_revision)


def row_binding(row):
    from adapters.secrets.store import CredentialRef
    return EnrollmentBinding(operation_id=row["operation_id"], principal_id=row["principal_id"],
        case_id=row["case_id"], profile_id=row["profile_id"], expected_revision=row["expected_revision"],
        credential_ref=CredentialRef(row["credential_ref"]))


def receipt(row):
    return EnrollmentReceipt(operation_id=row["operation_id"], principal_id=row["principal_id"],
        case_id=row["case_id"], profile_id=row["profile_id"], expected_revision=row["expected_revision"],
        attached_revision=row["attached_revision"])


def operation(conn, operation_id):
    lock(conn, "enrollment:" + str(operation_id))
    return conn.execute(text("SELECT * FROM provider_enrollments WHERE operation_id=:o FOR UPDATE"),
                        {"o": operation_id}).mappings().one_or_none()


def reserve(engine, bearer_token, candidate):
    with engine.begin() as conn:
        current = authority(conn, bearer_token, candidate)
        old = operation(conn, candidate.operation_id)
        if old:
            if request_tuple(row_binding(old)) != request_tuple(candidate):
                raise Problem(409, "enrollment_conflict", "conflict", "Enrollment operation conflicts")
            # Current auth/grant/profile check above precedes canonical replay.
            # The freshly generated unused candidate ref is not an existing target.
            if old["state"] == "attached":
                return Reservation(disposition="settled", receipt=receipt(old))
            return Reservation(disposition="blocked")
        if current["revision"] != candidate.expected_revision:
            raise Problem(409, "stale_revision", "conflict", "Profile revision is stale")
        conn.execute(text("INSERT INTO provider_enrollments(operation_id,principal_id,case_id,profile_id,credential_ref,expected_revision) "
                          "VALUES(:o,:p,:c,:f,:r,:v)"), {"o": candidate.operation_id, "p": candidate.principal_id,
            "c": candidate.case_id, "f": candidate.profile_id, "r": candidate.credential_ref.value, "v": candidate.expected_revision})
        return Reservation(disposition="ready", binding=candidate)


def pending(conn, bearer_token, binding):
    current = authority(conn, bearer_token, binding)
    row = operation(conn, binding.operation_id)
    if row is None or row_binding(row) != binding or row["state"] != "pending":
        raise Problem(409, "enrollment_conflict", "conflict", "Enrollment binding conflicts")
    if current["revision"] != binding.expected_revision:
        raise Problem(409, "stale_revision", "conflict", "Profile revision is stale")
    return current


def authorize_put(engine, bearer_token, binding):
    with engine.begin() as conn:
        pending(conn, bearer_token, binding)
    return binding


def attach(engine, bearer_token, binding):
    with engine.begin() as conn:
        current = pending(conn, bearer_token, binding)
        values = repository.dto(current).model_dump(mode="json")
        values["enabled"] = False  # Attachment cannot implicitly activate paid use.
        repository.append(conn, binding.principal_id, binding.case_id, values,
                          binding.profile_id, binding.expected_revision+1, binding=binding)
        row = conn.execute(text("UPDATE provider_enrollments SET state='attached',attached_revision=:v,settled_at=clock_timestamp() "
                                "WHERE operation_id=:o RETURNING *"),
                           {"v": binding.expected_revision+1, "o": binding.operation_id}).mappings().one()
        result = receipt(row)
    return result


def unresolved(engine, binding):
    # Only the complete privately captured operation can settle its own uncertainty.
    # Does not need a now-revoked grant and never reads/deletes/rewrites a credential.
    try:
        with engine.begin() as conn:
            row = operation(conn, binding.operation_id)
            if row is not None and row_binding(row) == binding and row["state"] == "pending":
                conn.execute(text("UPDATE provider_enrollments SET state='unresolved',failure_code='enrollment_incomplete',"
                                  "settled_at=clock_timestamp() WHERE operation_id=:o"), {"o": binding.operation_id})
    except Exception:
        pass  # Last durable pending intent is retained, never called attached.


def attached_binding(conn, row):
    if row["credential_ref"] is None:
        raise Problem(403, "profile_unconfigured", "forbidden", "Profile has no attached credential binding")
    enrollment = conn.execute(text("SELECT * FROM provider_enrollments WHERE operation_id=:o"),
                              {"o": row["binding_operation_id"]}).mappings().one_or_none()
    if (enrollment is None or enrollment["state"] != "attached" or
        (enrollment["principal_id"], enrollment["case_id"], enrollment["profile_id"], enrollment["credential_ref"], enrollment["expected_revision"])
        != (row["binding_principal_id"], row["case_id"], row["profile_id"], row["credential_ref"], row["binding_expected_revision"]) or
        enrollment["attached_revision"] != enrollment["expected_revision"]+1 or enrollment["attached_revision"] > row["revision"]):
        raise Problem(403, "profile_binding_denied", "forbidden", "Profile binding denied")
    return row_binding(enrollment)
