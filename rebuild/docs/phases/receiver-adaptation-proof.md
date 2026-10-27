# Receiver derivative Stage B proof (partial)

Five-file deterministic overlay for SDK1.41.1: accepted Stage A config/connection
bytes plus dispatcher, action listener and used admin workflow registration.
No installed SDK, application default, lock or image is changed. UnsupportedReceiver
remains correct. Stage A results below are historical, not a new native proof.

Actual GetVersion/Register/PutWorkflow timeout10s and single attempt; heartbeat/
unsubscribe5s; explicit listener lifetime1..60s before channel/registration, with
one stream/channel and no hidden reconnect, retry-reset or backoff. Valid action
mapping and UNIMPLEMENTED version compatibility remain. Selected failure logs use
fixed codes. Child/parent upstream raw logging is not yet addressed.

Owned read cleanup waits250ms and strongly retains resistant tasks for explicit
bounded join, including repeated cancellation. No channel close is issued here;
Stage A owns that. No native physical cleanup is inferred from fake cancellation.
Existing heartbeat/unregister lifecycle, child STOP_LOOP, action-event retries and
REST shutdown need later reviewed source stages. No whole-worker termination,
single-delivery, native/role/provider/enrollment or Phase1 completion claim.

Validation loads actual disposable derivative modules with a fake module graph;
all RPC/channel/stream seams are fakes. Initial7checks failed in common fake setup
(annotation stub lacked nested types); one setup correction exposed an actual
generator mapping indentation error. That loop was stopped; an author-script
encoding error prevented the first correction, and a bounded retry ended at20s.
After UTF8 correction,7checks passed in2.626s. Added mapping/cancellation/applicator
cases passed11checks in4.335s. V1 affected-module receipt:26checks PASS in13.237s after the final read-task
exception observation guard;13new checks separately PASS in5.502s before that
aggregate. Earlier26checks PASS in15.394s preceded the final guard.
CI invocation: `python -B -m unittest discover -s tests/contracts/scheduler
-p "test_receiver_adaptation*.py" -v` from the rebuild root, using the pinned
dependency environment. Local runs add a30s faulthandler process deadline.

No actual SDK/client/network/process/service construction, install or image build
occurred. Temporary test copies contain only allowlisted source and metadata.

# Historical Stage A proof

This is a source-only pinned derivative artifact. Exactly two upstream files are
eligible: SDK1.41.1 config.py and connection.py. A deterministic applicator validates
version, original hashes, exact patch context and final hashes before producing a
new two-file disposable overlay. Existing packages, locks and images stay unchanged.

The config derivative uses an explicit pure-model base across nested classes,
before eager defaults execute. It never constructs environment/dotenv/secret-source
objects and rejects unknown settings-source options. Required explicit binding,
namespace and nested retry/health/TLS policies fail closed. Token endpoint decoding
is removed for this fixed explicit development binding. Existing model validators,
namespace/field behavior and model serialization used by future spawn inputs are
tested, with the original arbitrary-types allowance preserved for Logger.

The connection derivative checks a process-local, non-picklable owned scope for
every new_conn invocation, including imported aliases. Retry/proxy are disabled
and message sizes fixed. Fake sync/async channel constructors exercise option
propagation, once closure, absent/foreign scope rejection, explicit cleanup failure
and timeout, plus refusal to treat a parent registry as a child scope. No parent or
child Worker lifecycle hook is added in this stage.

Validation copied only the two exact upstream files and distribution metadata to
new disposable scratch directories. Fresh derivative config modules used real
Pydantic pure validation with fake SDK logger/token/telemetry modules. Ambient
EnvSettingsSource/DotEnvSettingsSource/SecretsSettingsSource constructor traps cover
import-time defaults. Real channel/process imports are guarded; all exercised
channels are injected fakes. No SDK client/worker/channel/session, child process,
network/database operation, package installation or image build occurred.

Initial eight checks all stopped in common import setup because BaseModel lacked
upstream BaseSettings' arbitrary_types_allowed flag for logging.Logger. One
supported correction preserved that flag; eight checks then passed. Two added
async-timeout/imported-alias/serialization cases passed in a focused run. A final
strengthened foreign-PID close assertion passed in its single focused case. No
final10-test aggregate is claimed. Original failure and separate receipts remain
part of the private validation chronology.

Independent review found three finite issues, corrected within the same artifact:
the notice now reproduces the exact copyright and complete MIT terms from the
official pinned SDK release; timed-out close Tasks have a strong owner ledger and
bounded join surface; and mixed sync/async close calls share one exactly-once sweep
state. The notice links the pinned license/release provenance. No installed package
or additional upstream file was modified.

Seven focused fake regressions passed after correction: three new cases prove
cancellation-resistant Task retention/release/join, sync close rejection both before
and during an async sweep, and sync-then-async exactly-once closure. Four directly
affected existing ownership cases also passed. Final module count is13, with no
new full-suite aggregate asserted. Original8+2+1 evidence stays separate. All fake
tasks were released/joined; no physical native lifecycle is inferred.

This artifact is not a runnable receiver/default constructor. Worker/child scope
entry, hard-coded RPC/listener/event retries, PutWorkflow deadline, REST pool/proxy
and full physical shutdown remain later explicitly scoped derivative stages.
Current application UnsupportedReceiver remains correct. Independent review and
Main delivery are required before any new-image application or native invocation.

## Independent review correction (Stage B v2)

B found two defects despite v1's actual26-pass result: normal payload decode still
logged/fell back to empty input, and the three selected unary methods propagated
raw RPC exceptions. The old malformed fake could fail later on missing fields,
and its logger omitted traceback capture. V1 evidence remains valid only for its
assertions and does not override these findings.

Normal decode now fails closed. Negative JSON/schema cases share the complete
positive message skeleton, mutate only payload and assert exact payload_invalid,
no Action, one stream cancellation and no raw markers/exception logging. The fake
logger records actual formatted tracebacks if its exception method is called.
Selected unary errors are fixed ReceiverRpcError values raised outside the upstream
handler (context/cause both None); success identity, UNIMPLEMENTED, one attempt,
actual deadlines and cancellation are preserved. Sensitive detail/token markers
are absent from selected error serialization, formatted exception and captured logs.

Four affected cases passed initially in1.218s. After reading B's final report,
schema-invalid validation and traceback logger capture strengthened the fixtures;
FINAL focused4cases PASS in1.154s. New module now has14cases, with the same prior
StageA13cases retained; no corrected27case aggregate is claimed or locally rerun.
Main's hosted intended-head discovery uses the same test_receiver_adaptation*.py
command above. No native/runtime operation or additional upstream file was added.

## Stage C1: explicit queued event sends (partial)

C1 extends the accepted Stage B overlay from five to six exact upstream members,
adding only worker/action_listener_process.py. Config, connection, admin and action
listener derivative bytes remain at their accepted hashes. Dispatcher changes are
limited to selected event methods and their fixed EventDeliveryError definition.
Raw source, LF source, patch context, exact six-file surface and final hashes are
validated before any derivative output is created. The retained verified MIT
notice remains included. Installed SDK and application defaults are unchanged.

Normal and sync/async batch event sends now perform one invocation with timeout10s.
Both the dispatcher retry layer and child's recursive/nested-task layer are removed.
The child directly awaits the actual RPC. Request fields, timestamp, retry count,
should_not_retry, batch payload fallback and successful response identity survive.
A missing response never becomes ACK. A failure after invocation is uncertain even
for auth/deadline status; pre-invocation failures can be event_not_sent. Fixed
errors are raised outside the vendor handler, without cause/context or raw error
logs. Cancellation propagates. Explicit skipped action types are event_not_sent.
Duplicate queued STARTED items remain separate sends; no deduplication is claimed.

Admission is one strongly owned send Task at a time, with exact event identity in
unresolved_sends. Queue reads use nonblocking polling, so a canceled executor get
cannot later steal an event. No bulk dequeue remains; later items and STOP stay
ordered in the original queue on failure. A local sequence/classification/stop
receipt contains no payload/token/vendor response. Normal response observation
removes Task ownership only after task.result() is consumed. Any uncertain outcome
stops further admission. The12s local wait cancels once and reserves250ms for
settlement; a resistant Task remains strongly owned. join_sends accepts a bounded
later wait up to5s, observes late results/errors without resend or recancel, and
never changes terminal uncertainty into a retrospective delivery acknowledgement.

Actual focused fake evidence: initial12 new event cases plus the affected existing
six-file/drift fixture PASS13 in4.911s. After adding LF-hash refusal, cooperative
cancellation and selected-method AST assertions, final LF/cancellation/affected
config fixture PASS3 in1.508s; standalone AST case PASS1 in0.376s. There are14 new
event cases total. These targeted results are not a new full aggregate result.
The accepted Stage B27 result remains historical. Main's intended-head discovery
must cover test_receiver_adaptation*.py through ordinary CI.

Checks exercise actual disposable copied methods against isolated fake graphs:
three send variants with fields/deadline/metadata/identity; transient/auth/deadline/
unknown failure, None response and cancellation; sensitive exception serialization,
str/repr, formatted traceback and traceback-aware logger capture; preflight versus
post-invocation uncertainty; direct awaited normal/batch child calls; skipped
signals; duplicate STARTED sends; queue ordering/STOP; cancellation-resistant late
success/error and repeated cancellation with exact task/event retention; cooperative
cancel; no latent queue dequeue; six-member gates, new upstream drift, wrong LF or
final hash, missing/extra/duplicate manifest/patch members and unsafe targets.
All resistant fake tasks were explicitly released and joined in finally blocks.

One sandbox run stopped in Windows asyncio self-pipe socketpair initialization;
normal elevated tool approval allowed local IPC for fake checks. A later four-case
focused process ended with exit1 after two reported ok cases and no unittest
summary. The bounded isolated AST diagnostic passed; final three-case verification
then passed. Failed/incomplete attempts are not counted as aggregate passes.

This remains partial source preparation awaiting independent review and Main Git/
CI delivery. Entry event-send gather alone is bounded. Child status-to-parent,
stop-event wait, heartbeat/unsubscribe, asyncio.run/default executor teardown,
parent/REST/runner lifetimes and native execution remain open. A bounded send wait
is not physical whole-process shutdown or native readiness. No DB, credential,
image, installed SDK, native transport or actual provider operation occurred.

## Stage C1 v2 independent-review correction

B identified F1 P2 in v1: the active send waiter and join_sends, or two joins, could
both observe the same completed Task and index a deleted ledger entry. The prior
focused passes did not cover competing observers and do not supersede this finding.
The original evidence and incomplete attempts above remain historical.

Each bounded waiter now captures the shared task/state before yielding. The first
same-loop synchronous observation consumes result(), caches only a fixed safe
classification and removes outstanding ownership. Other observers return the cached
classification without consuming result again or touching a removed ledger entry.
State is retained only by outstanding ledger/current waiters; no permanent task
history/cache is introduced. The cancellation helper safely tolerates already
settled state. Exact unresolved Task/event ownership and single admission remain;
late success/error cannot overwrite a terminal uncertainty receipt. No RPC policy,
upstream surface, parent/REST/native behavior or accepted output elsewhere changed.

Two new actual copied-derivative tests use a gated CountingTask and await all distinct
observers before releasing completion. Six active-waiter-plus-two-join scenarios
cover success, error, send cancellation, resistant late success/error and active
waiter cancellation. Five two-join scenarios cover success/error/cancellation and
resistant late success/error with permanent terminal uncertainty. They assert one
RPC, exactly one result() observation, cached additional observation, coherent
remaining queue/STOP, strong pending Task/event identity and safe receipt/logs.
Fake-resistant tasks are released/joined in finally; the temporary task factory is
restored. No native transport is constructed.

The first v2 run's fake barrier counted calls rather than distinct observers, so
slow scheduling could expire the active wait before both joins started. Its failure
was diagnosed as2distinct waiters where3were required. Corrected the fake barrier
to wait for distinct observers before starting deadlines. The next combined run
reported both new cases ok then ended exit1 during the retained cancellation check
without a summary; it is incomplete, not an aggregate pass. Bounded isolated
cancellation test10 PASS1 in0.377s. FINAL two new gated cases PASS2 in2.309s,11
scenarios total. New event inventory is16, retained accepted inventory27; no43-case
aggregate was run locally or claimed. Main intended-head CI and B delta review
remain required. All v1/native/source-only limits continue to apply.

## Event fixture native import lifetime correction

A provider-only CI head inheriting C1 v2 failed with process exit139; the last
listed event test did not identify the failing operation. One bounded unchanged
immutable Linux comparator captured the actual fatal stack: event03 setUp imported
the copied child, whose multiprocessing.synchronize import faulted at the stdlib
SemLock.SEM_VALUE_MAX access.13StageA and2event cases had completed; this was not
a full suite pass. The retained container actually exited139/PID0/noOOM, without
watchdog expiry. A preceding Windows debug-allocator/GC diagnostic passed3 focused
cases and did not resolve the failure. All incomplete/failure history is preserved.

The fixture's whole-sys.modules snapshots were taken before the child's first
native multiprocessing import. Restoring them evicted modules lazily imported
under those guards; later cases reinitialized the native import graph. Preloading
multiprocessing.synchronize at test-module import puts this graph in both snapshots
before copied child loading. No process or synchronization primitive is constructed.
A cleanup registered before both guards asserts the same synchronize/_multiprocessing
module identities after restoration. All16event test bodies/assertions, including
safe errors, cancellation resistance, exact task/event retention and concurrent
observer scenarios remain; no skip, blanket retry or dependency change is added.
Product patch/manifest and its six derivative outputs are unchanged. This is a
fixture import-lifetime correction, not a product-task or whole-worker guarantee.

One changed Linux verification completed all43cases PASS in18.032s with the same
cached dependency image, debug allocator, development mode, faulthandler, START/STOP
boundaries and final GC. Actual container exit0/PID0/noOOM/no external timeout;
supervisor duration20.98798s. Both module identities survived all event fixture
restorations; all16existing event test bodies and helpers except additive setUp
registration are AST-identical to the accepted baseline. The immutable nine-file
verification packet retained seven original files and the corrected test/proof;
its hashes stayed unchanged. This result supports the narrow fixture correction,
not a universal interpreter/platform or native-worker guarantee. The final proof
paragraph was added after verification; tested event source bytes are unchanged.
Independent review, separate Main fix delivery and intended-head CI remain gates.
