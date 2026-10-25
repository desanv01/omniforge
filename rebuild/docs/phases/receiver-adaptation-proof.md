# Receiver derivative Stage A proof

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
