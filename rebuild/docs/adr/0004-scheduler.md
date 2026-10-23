# ADR 0004 — Durable execution behind scheduler boundary

Status: candidate, not accepted scheduler technology; OF-013 owns proof.

Hatchet is the first candidate. Domain Run/Event/Attempt records remain owned by
the application, with transactional dispatch outbox, monotonically fenced leases,
durable output refs and explicit reconciliation to scheduler execution records.
Stream closure never indicates completion. Unknown external effects remain
uncertain; interrupted safe reads may retry under a new attempt.

No Hatchet SDK, service or recovery implementation exists in OF-010. OF-013 must
select compatible exact versions/images, isolate service/DB names and ports,
interrupt a deterministic job, restart/reconcile without duplicate output, reject
a stale attempt, and show canceled/failed histories. If that deployment/recovery
test fails after one distinguishing diagnostic/correction, compare one alternative
(Temporal candidate) on the same fixture before deeper workflow implementation.
Choosing this ADR alone cannot pass the scheduler gate. A host in-memory task
queue cannot serve as a durability fallback.
