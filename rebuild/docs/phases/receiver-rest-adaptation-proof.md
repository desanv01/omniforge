# Receiver REST source proof (partial)

The four-source artifact in infra/scheduler/receiver-rest-adaptation is separate
from the event-delivery derivative. It enforces selected pause one-shot transport,
explicit retry/proxy/redirect/timeouts, safe uncertain failures, captured local
resource ownership and one idempotent response/pool close sweep. It is source and
fake-graph proof only; no SDK installation, native receiver or parent integration.

The checks execute copied derivative classes, the unchanged selected generated
worker_update body and fake HTTP managers/pools/responses. Coverage includes
payload/auth forwarding, each request serialization branch, invalid/tightened
timeouts, transient/status/read/model errors, safe tracebacks, cleanup failure,
partial wrapping, raw borrowing, cancellation, blocked body/request/close ownership,
interruption, immutable snapshots, foreign PID refusal and applicator hash/path
refusals. The source-symlink refusal case simulates the filesystem symlink predicate;
it is not evidence of native link creation. Tests release and join every fake thread.

An initial Windows sandbox run stalled in asyncio socketpair construction before
test setup. One 15-second diagnostic identified that local IPC path; normal
escalation review allowed the offline Windows loop. The first completed run passed
14 of 15 checks; the tamper fixture had replaced text absent from the patch. The
fixture was corrected to change existing context. A six-check focused correction
run passed, covering that refusal plus request/body ownership, aio cancellation,
empty/None responses and PID guards. Further code inspection moved vendor close
calls outside the snapshot lock. Final focused aggregate: 21 tests passed in
7.764 seconds, exit 0, with no skips or reported warnings. This run includes the
corrected fixture, manifest/LF gates and all new ownership/cleanup cases above.

Socket connect/read/total limits are not hard wall-clock or physical-stop proof.
Cancelled asyncio views retain underlying thread activity; pool clear does not
stop in-flight connections. Premature client close remains permanently incomplete.
C2 must consume process-local owners and safe receipts, implement overall lifecycle
supervision and prove actual resources settled. UnsupportedReceiver remains default.
Native construction/image, roles/DB/network, enrollment and live provider gates
remain unexecuted. Required independent review and Main Git/CI delivery are separate.

REST2 adds prepared construction capture before manager/header initialization,
local exact-owner/PID/once-only admission, and a separate request method without
client auto-close. Both partial ApiClient and partial pool manager remain strongly
reachable before blocking/failing constructor work. Safe immutable snapshots add
construction_active/construction_complete and prepared_admission/prepared_claimed.
Only completed construction bound to the same WorkersClient admits a request.
Premature construction close remains incomplete and does not clear a manager
while it is initializing. Existing pause/aio_pause auto-close behavior is retained,
including safe cleanup of partial initialization on its ordinary path.

REST2 focused result: 14 tests passed in 5.541 seconds, exit 0, no skips/warnings
reported. Ten new cases (22 through 31) and four affected REST1 regressions
(01,09,12,14) ran; no unchanged broad suite was repeated. These new tests cover
partial manager/header failure, failed capture before manager side effects,
blocked preparation with an already captured owner, rejection of partial/
foreign/external/closed/used clients, request without client sweep, cancellation
of observation while its exact request thread remains alive, physical thread join
before one cleanup sweep, blocked cleanup snapshots, safe error propagation and
premature construction close. Every fake gate is released and thread joined.
The test inventory is now 31; a 31-case aggregate is not claimed by this focused run.

Preparation, request and cleanup each require a caller-owned operation registered
before its thread starts. Physically join preparation before dispatch and request
before cleanup; no automatic thread launch, C2 parent integration, hard deadline
or physical cancellation is implemented here. REST1 evidence remains historical
for its accepted source; the separate REST2 delivery requires independent review
and Main intended-head CI before acceptance.
