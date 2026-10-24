# OF-013-B3B1 — asynchronous delivery handshake

24 October2026. Implemented and tested against the isolated PostgreSQL core;
frozen for independent C review. No native scheduler runtime or whole-phase
acceptance is implied.

This finite slice connects the accepted asynchronous scheduler-port contract to
the PostgreSQL Run/outbox/attempt journal using injected asynchronous doubles.
Only fresh explicitly allowlisted synthetic Runs participate. No pending-intent
scanner, native scheduler launch, session/channel factory, credential discovery,
provider call, enrollment, installation or dependency change belongs to this gate.

Required correlation includes trusted tenant, workflow/version/name, namespace,
Run ID, stable logical dispatch key, input hash and bounded physical generation.
Verified root/task identities establish same-Run mappings; candidate execution IDs
remain unverified and cannot admit work. A broker completion observation cannot
publish domain success. Real eventual-index lookup never proves authoritative
absence and cannot silently cause another submission.

Early worker delivery must be verified and durably registered before an attempt
is admitted, even when submit acknowledgement has not arrived. A late verified
acknowledgement may update its own bookkeeping after the Run becomes running or
terminal, without rewriting domain state. A previous-generation acknowledgement
must never clear a newer reservation. Existing fake-v1 behavior and rows remain
preserved.

One recovery generation may be considered only with explicit trusted prior-attempt
expiry/quiescence evidence, current authority/input scope, known harmless effects,
coverage of all known executions, no unresolved candidate identities and remaining
original reservation counters/wall budget. Unknown effects remain unresolved;
counters and immutable payload snapshots cannot be reset to evade the limits.
Injected synthetic receipts do not establish actual process quiescence.

Active cancellation, cleanup/finally acknowledgement, SSE, actual scheduler engine
semantics, combined worker runtime and supervised hard interruption remain later
gates. No global scheduler/provider readiness or whole-phase completion follows
from this fake-only PostgreSQL handshake proof.

## Observed proof and preservation

The sole combined run passed **64 tests**, zero failures/errors, runner42.656s
(unittest42.659s). Fifteen new core_delivery tests ran with the retained49
regressions: B1 journal7, B2 execution11, core8, deterministic provider1, profile10
and binding12. The accepted asynchronous Hatchet adapter was exercised with an
injected client only; no SDK client/channel/session or vendor service was created.
Provider/binding regressions used their existing synthetic input/stores/transport.

New fixtures cover registration before submit reply at running and terminal state;
early ACK followed by unknown reply with extra durable candidates; bounded lookup
without absence/resubmission; one token for duplicate worker deliveries; atomic
root/task collisions including concurrent cross-Run claims; strict case/binding/
input/generation; expired-lease safe rearm with counters preserved; historical ACK
without clearing a newer reservation; rejection of missing/bool/live/wrong proof,
unknown candidates and exhausted counters; current authority/scope/original wall
budget; fake-driver segregation; native terminal noncompletion; late unknown and
duplicate registration preserving another acknowledged lookup claim; newly
discovered historical roots blocking recovery work/output; async deadline and
cancellation retaining unresolved intent. Process quiescence is supplied only by
an injected trusted synthetic verifier, never inferred from broker completion.

Before runtime, hash verification caught the Scheduler owner's first freeze
changing during a source-inspection correction. The revised freeze preserves an
acknowledged lookup claim/unknown marker on duplicate registration and adds test12
assertions. Only the verified revised six-file source entered the database proof.
No initial-version PostgreSQL run or runtime failure/retry was performed.

Migration0007_run_delivery actually preserved every original column and row across
all fourteen prior application tables, checked immediately after migration and
again after tests using original column projections and retained-row fingerprints.
Migrations0001–0006, accepted B3A source and the root dependency lock remain byte
unchanged. All original Run/profile/enrollment records remain, including the
pre-existing pending/unresolved operations. These are retained test-DB row checks,
not a new physical backup/legacy restore proof.

Additive fixtures leave22 immutable submission rows (20generation0/2generation1),
one candidate-bearing intent and running/queued/interrupted/uncertain Run metadata.
No process or automatic recovery is implied by those records. The exact owned
database is stopped/preserved with exit0; no API/worker listener was started and
no old intent was drained. No destructive fixture cleanup was performed.

Actual pinned OpenAPI/client generation and strict TypeScript compilation passed;
the actual API schema matches the generated contract in the core regression.
The public JSON replay enum now admits delivery_rearmed; there is no SSE or new
public delivery/claim endpoint. No dependency/environment change was required.
Exact source hashes, receipts and private resource evidence remain in the
coordination handoff outside public source. C review and Main's CI/delivery remain
required before acceptance of this finite slice.
