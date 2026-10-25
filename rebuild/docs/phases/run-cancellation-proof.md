# OF-013-B3B2 — active cancellation and cleanup-only authority

25 October2026. Implemented and tested against the confirmed cancellation
interface; frozen for independent review. No native scheduler or whole-phase
acceptance is implied.

The slice separates cancellation request, native stop acknowledgement and proven
application cleanup. First active request revokes work/publication with a new fence
and durable cancellation identity. Existing queued undispatched cancellation stays
immediate. Separate per-execution commands preserve the start-outbox invariant.
Native cancel/status observations alone never settle the Run as canceled.

Cleanup-only credentials bind current cancellation and owned execution/original
attempt/worker/task snapshot. They survive revoked work authority only to report
cleanup and cannot publish or resume work. The database stores a secret hash, not
the credential. Receipts are immutable and require exact current binding. Unknown
candidates, missing/failed finally acknowledgements or expanded known task sets
remain unresolved; no automatic credential replacement or uncertain retry exists.

All previous histories, partial outputs and known/unknown usage remain retained.
Validation will use fresh synthetic Runs, injected scheduler/cancellation doubles
and the existing isolated PostgreSQL resource, with no actual worker, native
scheduler, provider, OS credential or image operation. SSE and native B3C remain
separate gates. Backend runs the combined proof only after Scheduler source freeze.

## Observed validation

The sole combined retained-PostgreSQL run passed **54 tests**, zero failures/errors,
runner42.219s (unittest42.221s). Twenty new CoreCancellationProof tests ran with34
unchanged affected regressions: B1journal7, B2execution11, B3B1delivery15 and the core
health/error/OpenAPI check. No method was excluded and no runtime correction/repeat
was needed. Unrelated accepted provider/profile/binding behavior evidence was
reused; this run did not execute those suites. Four core fixture migration literals
were updated with Main's approval, preserving every other old assertion.

New fixtures prove queued fast path, immediate work/renew/output/claim fencing,
cleanup after work-grant/lease revocation, strict foreign/old/forged credential and
receipt rejection, exact request/receipt idempotency, failed/unknown/missing finally
remaining unresolved, native ACK not cleanup, no SQL transaction across await,
bounded unknown cancel, claimed/unknown late delivery with cleanup-only authority,
all-root/candidate settlement, task expansion reopening, success/cancel and claim/
receive lock races, exact partial-output/unknown-usage retention, a different current
writer canceling revoked original work, fake-kind late ACK compatibility, private
credentials and unsupported SSE, injected cooperative finally/noack cases, deadline/
dispatcher coroutine cancellation durability and the in-flight early-delivery race.

The last race required a pre-freeze source refinement: verified early registration
retains an outstanding submit claim until its reply is processed. Test20 proves
that a cleanup receipt cannot terminalize canceled while that earlier reply is
still in flight. The agreed eight-file source was frozen/hashed before generation
and runtime; no moving dependency or initial-version runtime was consumed.

Migration0008_run_cancellation actually added three tables and nullable/defaulted
Run cancellation fields while preserving every original column/row across all
fifteen prior tables. Original column projections and retained-row fingerprints
matched immediately after migration and after tests. Migrations0001–0007, accepted
B3A adapter and root lock remain byte unchanged. All212 prior profile versions and
64 enrollment rows, including pending/unresolved states, are unchanged. These are
retained test-DB checks, not a physical backup or legacy recovery proof.

Additive fixtures retain26 cancellation requests (11settled/11pending/4unresolved),
28targets and17immutable receipts (14succeeded/2failed/1unknown). Fifteen Runs remain
cancel_requested with honest pending/failed/unknown cleanup. Other running/queued/
interrupted/uncertain metadata and two candidate-bearing intents remain preserved;
none is a live process or automatic recovery claim. No destructive cleanup occurred.

The exact owned database was stopped/preserved with exit0; no API/worker listener
was started. All stop/lookup/finally operations used injected scheduler doubles;
no native Hatchet client/session/channel, external credential, provider, image build
or worker runtime was used. Synthetic finally/quiescence evidence does not prove
actual OS cleanup/termination, and retained partial-output fixtures do not introduce
a new production partial-publication API.

Actual pinned OpenAPI/client generation and strict TypeScript compilation passed;
the actual API schema matched the generated document. Exact source hashes and
private command/migration/test/history/settlement receipts are in the coordination
handoff outside public source. Independent review and Main's delivery/CI remain
required. SSE B3B3, native B3C and worker image execution remain subsequent gates.
