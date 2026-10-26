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
