"""Conn-bound diagnostic journal; no default trusted adapter or live entrypoint.

Caller owns transaction/commit. Decisions are PREPARED, never committed receipts.
Only a separately trusted post-commit publisher may emit original acknowledgments.
Normal lock order: principal/grant/profile -> diagnostic operation -> rounds.
Settlement: operation -> rounds ONLY, never current authority in reverse order.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import hmac
import json
from typing import Callable
from uuid import UUID

from sqlalchemy import text

from services.api.db import digest, lock
from services.api.errors import Problem
from services.api.profiles.authority import BoundProfile, Purpose, load_profile_conn
from services.api.providers.diagnostic_protocol import Reservation, Observation


def deny(code="diagnostic_conflict", status=409):
    raise Problem(status, code, "forbidden" if status == 403 else "conflict", "Diagnostic journal unavailable")


def check(value):
    if not value:
        deny()


def uuid(value):
    check(type(value) is UUID)


def integer(value, low=0, high=1_000_000):
    check(type(value) is int and low <= value <= high)


def sha(value):
    check(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value))


def instant(value):
    check(type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None)


@dataclass(frozen=True)
class Invocation:
    operation_id: UUID
    invocation_id: UUID
    invocation_generation: int
    bootstrap_fingerprint: str
    deadline_identity: UUID
    deadline_revision: int
    principal_id: UUID
    pin: BoundProfile = field(repr=False)

    def __post_init__(self):
        for value in (self.operation_id, self.invocation_id, self.deadline_identity, self.principal_id): uuid(value)
        integer(self.invocation_generation, 1); integer(self.deadline_revision, 1)
        sha(self.bootstrap_fingerprint)
        check(type(self.pin) is BoundProfile)
        uuid(self.pin.case_id); uuid(self.pin.profile.id)
        integer(self.pin.profile.revision, 1); sha(self.pin.metadata_digest)
        # Revalidate detached immutable budget primitives; model_copy can bypass DTO validation.
        from adapters.models.contracts import Budget
        Budget.model_validate(self.pin.budget.model_dump())
        Budget.model_validate(self.pin.caps.model_dump())
        check(all(getattr(self.pin.budget, name) <= getattr(self.pin.caps, name)
                  for name in ("calls", "input_tokens", "output_tokens", "wall_seconds", "tool_bytes")))
        check(self.pin.budget.calls <= 2 and self.pin.budget.input_tokens <= 32768
              and self.pin.budget.output_tokens <= 1024 and self.pin.budget.wall_seconds <= 30
              and self.pin.budget.tool_bytes <= 32)

    def identity(self):
        return {"operation_id": str(self.operation_id), "invocation_id": str(self.invocation_id),
            "invocation_generation": self.invocation_generation, "bootstrap_fingerprint": self.bootstrap_fingerprint,
            "deadline_identity": str(self.deadline_identity), "deadline_revision": self.deadline_revision}

    @property
    def fingerprint(self):
        binding = self.pin.binding
        return digest({**self.identity(), "principal": str(self.principal_id), "case": str(self.pin.case_id),
            "profile": str(self.pin.profile.id), "revision": self.pin.profile.revision,
            "metadata": self.pin.metadata_digest, "budget": self.pin.budget.model_dump(),
            "binding": [str(binding.operation_id), str(binding.principal_id), str(binding.case_id),
                str(binding.profile_id), binding.expected_revision, binding.credential_ref.value]})


KINDS = frozenset(("admit", "reserve", "observe", "candidate", "stop", "final_authority", "readback", "settle"))


@dataclass(frozen=True)
class Command:
    invocation: Invocation
    command_id: UUID
    controller_command_index: int
    kind: str
    request_digest: str

    def __post_init__(self):
        check(type(self.invocation) is Invocation)
        self.invocation.__post_init__()
        uuid(self.command_id); integer(self.controller_command_index)
        check(type(self.kind) is str and self.kind in KINDS); sha(self.request_digest)


@dataclass(frozen=True)
class CutoffDescriptor:
    descriptor_id: UUID
    invocation_fingerprint: str
    command_id: UUID
    purpose: str
    fixed_db_not_after: datetime
    uncertainty_bound_ns: int
    mapping_evidence_id: UUID
    disposition: str = "unknown"

    def __post_init__(self):
        uuid(self.descriptor_id); uuid(self.command_id); uuid(self.mapping_evidence_id)
        sha(self.invocation_fingerprint); instant(self.fixed_db_not_after)
        integer(self.uncertainty_bound_ns, 0, 1_000_000_000)
        check(type(self.purpose) is str and self.purpose in ("work_admission", "work_decision", "settlement_decision"))
        check(type(self.disposition) is str and self.disposition in ("unknown", "valid_conservative"))


@dataclass(frozen=True)
class Trust:
    # Validators must check EXACT registered context/command/descriptor object
    # identity/provenance; serialized resemblance does not establish trust.
    provenance: Callable | None = field(default=None, repr=False)
    cutoff: Callable | None = field(default=None, repr=False)
    issue_capability: Callable | None = field(default=None, repr=False)
    publish_after_commit: Callable | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Decision:
    command: Command
    disposition: str  # original_prepared or canonical_replay; not a committed ACK.
    payload: dict
    capability: bytes | None = field(default=None, repr=False)


def publish_committed(decision, commit_evidence, trust=Trust()):
    """Missing real channel/commit provenance denies; never infer from UUID/bool.

    Trusted injected publisher validates exact transaction commit evidence and
    pending original request, emits schema1 original_committed/canonical_replay,
    and captures capability once privately. This module cannot prove IPC capture.
    """
    check(type(decision) is Decision and type(trust) is Trust)
    if not callable(trust.publish_after_commit):
        deny("diagnostic_provenance_unavailable", 403)
    return trust.publish_after_commit(decision, commit_evidence)


def prepared(command, payload, replay=False, capability=None):
    return Decision(command, "canonical_replay" if replay else "original_prepared",
        {"schema_version": 1, **command.invocation.identity(), "command_id": str(command.command_id),
         "command_kind": command.kind, "request_digest": command.request_digest, **payload}, capability)


def request_digest(command, payload):
    return digest({**command.invocation.identity(), "kind": command.kind, "payload": payload})


def validate_request(command, kind, payload, trust, descriptor=None):
    check(type(command) is Command and type(trust) is Trust)
    command.__post_init__()
    check(command.kind == kind and command.request_digest == request_digest(command, payload))
    if not callable(trust.provenance) or trust.provenance(command) is not True:
        deny("diagnostic_provenance_unavailable", 403)
    if kind != "readback":
        if not callable(trust.cutoff) or type(descriptor) is not CutoffDescriptor:
            deny("diagnostic_cutoff_unavailable", 403)
        descriptor.__post_init__()
        check(descriptor.invocation_fingerprint == command.invocation.fingerprint and descriptor.command_id == command.command_id)
        check(descriptor.disposition == "valid_conservative")


def bounded(conn):
    # Historical readback only; execution-capable paths use absolute cutoffs
    # BEFORE acquisitions, not this independent fixed policy.
    conn.execute(text("SET LOCAL statement_timeout='1000ms'"))
    conn.execute(text("SET LOCAL lock_timeout='1000ms'"))
    conn.execute(text("SET LOCAL idle_in_transaction_session_timeout='1000ms'"))


def normal_authority(conn, command, token, *, before_statement=None):
    ctx = command.invocation
    current = load_profile_conn(conn, ctx.principal_id, ctx.pin.case_id, ctx.pin.profile.id,
        ctx.pin.profile.revision, Purpose.EXECUTE_DIAGNOSTIC, bearer_token=token, requested_budget=ctx.pin.budget,
        before_statement=before_statement)
    check(current == ctx.pin)


def operation(conn, command, *, before_statement=None):
    ctx = command.invocation
    if before_statement is not None: before_statement()
    lock(conn, "diagnostic:" + str(ctx.operation_id))
    if before_statement is not None: before_statement()
    row = conn.execute(text("SELECT * FROM provider_diagnostics WHERE operation_id=:o FOR UPDATE"), {"o": ctx.operation_id}).mappings().one_or_none()
    if row is not None:
        check(row["fingerprint"] == ctx.fingerprint)
    return row


def cutoff(conn, command, descriptor, trust, row=None):
    purpose = "work_admission" if command.kind == "admit" else "settlement_decision" if command.kind == "settle" else "work_decision"
    check(descriptor.purpose == purpose)
    bound = trust.cutoff(conn, command, descriptor)  # Injected original bound; no default producer.
    instant(bound)
    check(bound == descriptor.fixed_db_not_after)
    if row is not None:
        check(bound <= (row["expires_at"] + timedelta(seconds=4) if command.kind == "settle" else row["expires_at"]))
        if command.kind == "settle" and row["settlement_cutoff"] is not None:
            check(bound == row["settlement_cutoff"])
    now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    instant(now)
    if now >= bound: deny("diagnostic_expired")
    if row is None and command.kind == "admit":
        check(bound <= now + timedelta(seconds=command.invocation.pin.budget.wall_seconds))
    # Fresh post-lock remaining duration can only shrink timeouts, never reset expiry.
    milliseconds = min(1000, int((bound - now).total_seconds() * 1000))
    if milliseconds < 1: deny("diagnostic_expired")
    conn.execute(text("SELECT set_config('statement_timeout',:v,true),set_config('lock_timeout',:v,true),set_config('idle_in_transaction_session_timeout',:v,true)"), {"v": str(milliseconds) + "ms"})
    return bound


def rounds(conn, command):
    return list(conn.execute(text("SELECT * FROM provider_diagnostic_rounds WHERE operation_id=:o ORDER BY round_seq FOR UPDATE"), {"o": command.invocation.operation_id}).mappings())


def checked_rounds(conn, command, descriptor, trust, row):
    cutoff(conn, command, descriptor, trust, row)
    result = rounds(conn, command)
    cutoff(conn, command, descriptor, trust, row)
    return result


def accounting(rows):
    result = {"possible_dispatch_upper_bound": len(rows), "accepted_request_lower_bound": 0, "cost": None}
    for name, reserved in (("input_tokens", "input_estimate"), ("output_tokens", "output_max")):
        values = [row[name] if row["observation_digest"] is not None else None for row in rows]
        result[name] = sum(values) if all(v is not None for v in values) else None
        result["known_" + name + "_subtotal"] = sum(v for v in values if v is not None)
        result["charged_" + name] = sum(row["charged_" + name] if row["observation_digest"] is not None else row[reserved] for row in rows)
    return result


def summary(row, rows):
    return {"state": row["state"], "candidate_digest": row["candidate_digest"], **accounting(rows)}


def enter(conn, command, kind, payload, descriptor, trust, token=None):
    validate_request(command, kind, payload, trust, descriptor)
    guard = lambda: cutoff(conn, command, descriptor, trust)
    guard()
    if kind != "settle":
        normal_authority(conn, command, token, before_statement=guard)
    row = operation(conn, command, before_statement=guard)
    check(row is not None)
    cutoff(conn, command, descriptor, trust, row)
    return row


def admit(conn, command, descriptor, *, bearer_token=None, trust=Trust()):
    validate_request(command, "admit", {}, trust, descriptor)
    if not callable(trust.issue_capability):
        deny("diagnostic_capability_unavailable", 403)
    guard = lambda: cutoff(conn, command, descriptor, trust)
    guard()
    normal_authority(conn, command, bearer_token, before_statement=guard)
    row = operation(conn, command, before_statement=guard)
    bound = cutoff(conn, command, descriptor, trust, row)
    if row is not None:
        return prepared(command, summary(row, checked_rounds(conn, command, descriptor, trust, row)), True)
    cap = trust.issue_capability(command)
    check(type(cap) is bytes and len(cap) == 32)
    ctx = command.invocation
    cutoff(conn, command, descriptor, trust)
    conn.execute(text("""INSERT INTO provider_diagnostics(operation_id,invocation_id,invocation_generation,
        bootstrap_fingerprint,deadline_identity,deadline_revision,principal_id,case_id,profile_id,profile_revision,
        fingerprint,budget,expires_at,capability_hash)
        VALUES(:o,:i,:g,:b,:d,:v,:p,:c,:f,:r,:hash,CAST(:budget AS jsonb),:expiry,:cap)"""),
        {"o": ctx.operation_id, "i": ctx.invocation_id, "g": ctx.invocation_generation, "b": ctx.bootstrap_fingerprint,
         "d": ctx.deadline_identity, "v": ctx.deadline_revision, "p": ctx.principal_id, "c": ctx.pin.case_id,
         "f": ctx.pin.profile.id, "r": ctx.pin.profile.revision, "hash": ctx.fingerprint,
         "budget": json.dumps(ctx.pin.budget.model_dump()), "expiry": bound,
         "cap": hashlib.sha256(cap).hexdigest()})
    # PREPARED only: publisher after confirmed commit must capture raw cap once.
    return prepared(command, {"state": "open", "expires_at": bound.isoformat()}, capability=cap)


def reserve_round(conn, command, reservation, descriptor, *, bearer_token=None, trust=Trust()):
    check(type(reservation) is Reservation); reservation.__post_init__()
    check(reservation.operation_id == command.invocation.operation_id)
    row = enter(conn, command, "reserve", {"reservation": reservation.replay_digest}, descriptor, trust, bearer_token)
    rows = checked_rounds(conn, command, descriptor, trust, row)
    old = next((r for r in rows if r["round_seq"] == reservation.round_seq), None)
    if old:
        check(old["reservation_digest"] == reservation.replay_digest)
        return prepared(command, summary(row, rows), True)
    check(row["state"] == "open" and row["candidate_digest"] is None)
    check(reservation.round_seq == len(rows) + 1 and all(r["observation_digest"] is not None for r in rows))
    used = accounting(rows); budget = row["budget"]
    check(len(rows) < budget["calls"] and used["charged_input_tokens"] + reservation.input_estimate <= budget["input_tokens"]
          and used["charged_output_tokens"] + reservation.output_max <= budget["output_tokens"])
    cutoff(conn, command, descriptor, trust, row)
    conn.execute(text("""INSERT INTO provider_diagnostic_rounds(operation_id,round_seq,payload_sha256,input_estimate,output_max,reservation_digest)
        VALUES(:o,:seq,:payload,:input,:output,:digest)"""), {"o": reservation.operation_id, "seq": reservation.round_seq,
        "payload": reservation.payload_sha256, "input": reservation.input_estimate, "output": reservation.output_max, "digest": reservation.replay_digest})
    return prepared(command, {"round_seq": reservation.round_seq, "reservation_digest": reservation.replay_digest,
                              "possible_dispatch_upper_bound": len(rows) + 1})


def apply_observation(conn, command, observation, rows):
    check(type(observation) is Observation); observation.__post_init__()
    reservation = observation.reservation
    check(reservation.operation_id == command.invocation.operation_id)
    old = next((r for r in rows if r["round_seq"] == reservation.round_seq), None)
    check(old is not None and old["reservation_digest"] == reservation.replay_digest)
    if old["observation_digest"] is not None:
        check(old["observation_digest"] == observation.replay_digest)
        return True
    conn.execute(text("""UPDATE provider_diagnostic_rounds SET input_tokens=:input,output_tokens=:output,
        provenance=:provenance,safe_outcome=:outcome,charged_input_tokens=:ci,charged_output_tokens=:co,
        observation_digest=:digest,observed_at=clock_timestamp() WHERE operation_id=:o AND round_seq=:seq"""),
        {"o": reservation.operation_id, "seq": reservation.round_seq, "input": observation.input_tokens,
         "output": observation.output_tokens, "provenance": observation.provenance, "outcome": observation.safe_outcome,
         "ci": observation.charged_input, "co": observation.charged_output, "digest": observation.replay_digest})
    return False


def observe_usage(conn, command, observation, descriptor, *, bearer_token=None, trust=Trust()):
    check(type(observation) is Observation); observation.__post_init__()
    row = enter(conn, command, "observe", {"observation": observation.replay_digest}, descriptor, trust, bearer_token)
    rows = checked_rounds(conn, command, descriptor, trust, row)
    existing = next((r for r in rows if r["round_seq"] == observation.reservation.round_seq), None)
    check(row["state"] == "open" or (existing is not None and existing["observation_digest"] == observation.replay_digest))
    cutoff(conn, command, descriptor, trust, row)
    replay = apply_observation(conn, command, observation, rows)
    rows = checked_rounds(conn, command, descriptor, trust, row); used = accounting(rows)
    if not replay and (used["charged_input_tokens"] > row["budget"]["input_tokens"] or used["charged_output_tokens"] > row["budget"]["output_tokens"]):
        conn.execute(text("UPDATE provider_diagnostics SET state='stopped',stop_reason='budget' WHERE operation_id=:o"), {"o": command.invocation.operation_id})
        row = {**row, "state": "stopped"}
    return prepared(command, {**summary(row, rows), "observation_digest": observation.replay_digest}, replay)


def commit_candidate(conn, command, candidate_digest, descriptor, *, bearer_token=None, trust=Trust()):
    sha(candidate_digest)
    row = enter(conn, command, "candidate", {"candidate_digest": candidate_digest}, descriptor, trust, bearer_token)
    rows = checked_rounds(conn, command, descriptor, trust, row)
    check(rows and all(r["observation_digest"] is not None for r in rows))
    if row["candidate_digest"] is not None:
        check(row["candidate_digest"] == candidate_digest)
        return prepared(command, summary(row, rows), True)
    check(row["state"] == "open")
    used = accounting(rows)
    check(used["charged_input_tokens"] <= row["budget"]["input_tokens"] and used["charged_output_tokens"] <= row["budget"]["output_tokens"])
    cutoff(conn, command, descriptor, trust, row)
    conn.execute(text("UPDATE provider_diagnostics SET candidate_digest=:digest,candidate_at=clock_timestamp() WHERE operation_id=:o"), {"o": command.invocation.operation_id, "digest": candidate_digest})
    return prepared(command, {**summary(row, rows), "candidate_digest": candidate_digest})


def stop(conn, command, reason, descriptor, *, bearer_token=None, trust=Trust()):
    check(reason in ("canceled", "deadline", "durability", "authority", "interrupted", "budget", "protocol"))
    row = enter(conn, command, "stop", {"reason": reason}, descriptor, trust, bearer_token)
    replay = row["state"] == "stopped"
    if replay:
        check(row["stop_reason"] == reason)
    else:
        cutoff(conn, command, descriptor, trust, row)
        conn.execute(text("UPDATE provider_diagnostics SET state='stopped',stop_reason=:reason WHERE operation_id=:o"), {"o": command.invocation.operation_id, "reason": reason})
    return prepared(command, {**summary({**row, "state": "stopped"}, checked_rounds(conn, command, descriptor, trust, row)), "stop_reason": reason}, replay)


def final_authority(conn, command, candidate_digest, descriptor, *, bearer_token=None, trust=Trust()):
    sha(candidate_digest)
    row = enter(conn, command, "final_authority", {"candidate_digest": candidate_digest}, descriptor, trust, bearer_token)
    rows = checked_rounds(conn, command, descriptor, trust, row)
    check(row["state"] == "open" and row["candidate_digest"] == candidate_digest and rows
          and all(r["observation_digest"] is not None for r in rows))
    cutoff(conn, command, descriptor, trust, row)
    return prepared(command, {"candidate_digest": candidate_digest, "authority": "decision_only_not_delivery"})


def readback(conn, command, *, bearer_token=None, trust=Trust()):
    validate_request(command, "readback", {}, trust)
    bounded(conn)
    # Historical readback authenticates current token/writer, not enabled profile.
    from services.api.profiles import bindings, repository
    ctx = command.invocation
    bindings.authenticate(conn, bearer_token, ctx.principal_id)
    repository.grant(conn, ctx.principal_id, ctx.pin.case_id, write=True)
    row = operation(conn, command); check(row is not None)
    return prepared(command, {**summary(row, rounds(conn, command)), "execution_permission": False}, True)


def settle_only(conn, command, capability, observations, reason, descriptor, *, trust=Trust()):
    check(type(capability) is bytes and len(capability) == 32 and type(observations) is tuple and len(observations) <= 2)
    check(reason in ("canceled", "deadline", "durability", "interrupted", "authority", "budget", "protocol"))
    for item in observations:
        check(type(item) is Observation); item.__post_init__()
    check(len({item.reservation.round_seq for item in observations}) == len(observations))
    payload = {"observations": [item.replay_digest for item in observations], "reason": reason}
    row = enter(conn, command, "settle", payload, descriptor, trust)
    check(hmac.compare_digest(row["capability_hash"], hashlib.sha256(capability).hexdigest()))
    batch = digest({**payload, "command_id": str(command.command_id)})
    rows = checked_rounds(conn, command, descriptor, trust, row)
    if row["settlement_digest"] is not None:
        check(row["settlement_digest"] == batch)
        return prepared(command, summary(row, rows), True)
    # Validate every item before any mutation; a failing caller must roll back.
    for item in observations:
        old = next((r for r in rows if r["round_seq"] == item.reservation.round_seq), None)
        check(old is not None and old["reservation_digest"] == item.reservation.replay_digest
              and old["observation_digest"] in (None, item.replay_digest))
    cutoff(conn, command, descriptor, trust, row)
    for item in observations:
        cutoff(conn, command, descriptor, trust, row)
        apply_observation(conn, command, item, rows)
    cutoff(conn, command, descriptor, trust, row)
    conn.execute(text("""UPDATE provider_diagnostics SET state='stopped',stop_reason=COALESCE(stop_reason,:reason),
        settlement_digest=:digest,settlement_cutoff=:cutoff,settled_at=clock_timestamp() WHERE operation_id=:o"""),
        {"o": command.invocation.operation_id, "reason": reason, "digest": batch, "cutoff": descriptor.fixed_db_not_after})
    return prepared(command, summary({**row, "state": "stopped"}, checked_rounds(conn, command, descriptor, trust, row)))
