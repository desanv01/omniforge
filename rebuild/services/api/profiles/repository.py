"""Serialized revisions with current grants before journal replay."""
from uuid import uuid4

from sqlalchemy import text

from services.api.db import lock
from services.api.errors import Problem
from services.api.profiles.contracts import CAP_FIELDS, ProviderProfileView


def grant(conn, principal_id, case_id, write=False):
    # Lock the actual grant through mutation/replay, so revocation cannot overtake it.
    row = conn.execute(text("SELECT g.can_write FROM case_grants g JOIN principals p ON p.id=g.principal_id "
                            "WHERE g.principal_id=:p AND g.case_id=:c FOR SHARE OF g,p"),
                       {"p": principal_id, "c": case_id}).scalar_one_or_none()
    if row is None or (write and not row):
        raise Problem(403, "profile_forbidden", "forbidden", "Profile access denied")


def current(conn, case_id, profile_id, locked=False):
    if locked:
        lock(conn, "profile:" + str(profile_id))
    row = conn.execute(text("SELECT * FROM provider_profile_versions WHERE profile_id=:p AND case_id=:c "
                            "ORDER BY revision DESC LIMIT 1"), {"p": profile_id, "c": case_id}).mappings().one_or_none()
    if row is None:
        raise Problem(404, "profile_not_found", "not_found", "Profile not found")
    return with_binding_state(conn, row)


def with_binding_state(conn, row):
    result = dict(row)
    if row["credential_ref"] is not None:
        result["binding_status"] = "attached"
    else:
        state = conn.execute(text("SELECT state FROM provider_enrollments WHERE profile_id=:p "
                                  "ORDER BY created_at DESC,operation_id DESC LIMIT 1"),
                             {"p": row["profile_id"]}).scalar_one_or_none()
        result["binding_status"] = state or "unconfigured"
    return result


def dto(row):
    return ProviderProfileView(id=row["profile_id"], case_id=row["case_id"], revision=row["revision"],
                              label=row["label"], endpoint=row["endpoint"], model=row["model"],
                              caps={name: row[name] for name in CAP_FIELDS}, created_at=row["created_at"],
                              enabled=row["enabled"], credential_configured=row["credential_ref"] is not None,
                              binding_status=row.get("binding_status", "attached" if row["credential_ref"] else "unconfigured"))


def append(conn, principal_id, case_id, values, profile_id=None, revision=1, *, binding=None):
    profile_id = profile_id or uuid4()
    lock(conn, "profile:" + str(profile_id))
    bound = {name: None for name in ("credential_ref", "binding_operation_id", "binding_principal_id", "binding_expected_revision")}
    if revision > 1:
        prior = current(conn, case_id, profile_id)
        bound.update({name: prior[name] for name in bound})
    if binding is not None:
        bound.update(credential_ref=binding.credential_ref.value, binding_operation_id=binding.operation_id,
                     binding_principal_id=binding.principal_id, binding_expected_revision=binding.expected_revision)
    params = {"profile": profile_id, "case": case_id, "principal": principal_id, "revision": revision,
              "label": values["label"], "endpoint": values["endpoint"], "model": values["model"], **values["caps"],
              **bound, "enabled": values.get("enabled", False)}
    row = conn.execute(text("INSERT INTO provider_profile_versions(profile_id,case_id,created_by,revision,label,endpoint,model,"
                            "calls,input_tokens,output_tokens,wall_seconds,tool_bytes,enabled,credential_ref,"
                            "binding_operation_id,binding_principal_id,binding_expected_revision) "
                            "VALUES(:profile,:case,:principal,:revision,:label,:endpoint,:model,"
                            ":calls,:input_tokens,:output_tokens,:wall_seconds,:tool_bytes,:enabled,:credential_ref,"
                            ":binding_operation_id,:binding_principal_id,:binding_expected_revision) RETURNING *"), params).mappings().one()
    return dto(with_binding_state(conn, row))
