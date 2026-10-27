# Receiver REST1 source proof (partial)

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
