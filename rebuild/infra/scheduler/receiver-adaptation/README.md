# Receiver derivative Stage C1 (partial)

This source artifact changes six copied files from exactly1.41.1: config.py,
connection.py, clients/dispatcher/dispatcher.py, clients/dispatcher/action_listener.py,
clients/admin.py and worker/action_listener_process.py. The accepted Stage A config/connection output bytes are retained. It is not installed automatically,
does not patch a running/imported SDK, and is not a runnable native receiver.
The application's UnsupportedReceiver default remains unchanged.

Run the applicator with two explicit disposable paths:

```text
python -B apply_patch.py /disposable/upstream /new/disposable/derivative
```

The source root must contain the six exact upstream files and the installed
`hatchet_sdk-1.41.1.dist-info/METADATA` with matching name/version. Destination must
be absent, separate and not an ancestor/descendant of source. The applicator checks
all original raw/LF hashes, exact unified-diff context and final derivative hashes
BEFORE creating output. It writes only those six files and returns their hashes.
The output is an overlay, not a complete installable package. Failures use a fixed
CLI message; no force, fuzzy patch, in-place, overwrite or version fallback exists.
Apply only to a new disposable copy or later reviewed NEW image-layer staging,
never to the retained installation/shared interpreter or old image.

Config semantics deliberately differ from upstream BaseSettings: all nested
classes inherit a local pure BaseModel base. Environment/dotenv/file-secret source
objects are never constructed, including eager TenacityConfig default evaluation.
Returning init-only sources from settings_customise_sources would be too late:
pydantic-settings constructs those source objects first. Pydantic validators,
fields/defaults, model_dump/model_validate, namespace application and required
arbitrary-type support for Logger are retained/tested. Unknown fields (including
BaseSettings `_env_file`/`_secrets_dir` arguments) reject instead of silently working.
This is not a blanket BaseSettings API or SDK compatibility claim.

ClientConfig now requires explicit token/tenant/endpoints/normalized namespace and
all four nested settings. Initial development binding is literal127.0.0.1:7077 and
http://127.0.0.1:8888 with TLS none, health off, debug off, embedded absent and one
Tenacity attempt with retry flags false. It does not decode token endpoint hints.
Message defaults are65536; connection policy always fixes send/receive65536, retry0
and HTTP-proxy0. TLS, remote hosts and other SDK modes are intentionally rejected.
Actual token authenticity is a later runtime gate, not established by these values.

Every call to the derivative new_conn, including already imported aliases, checks
a current ReceiverResources scope and its creating PID before channel construction.
Each parent/child process must establish its OWN scope in a later stage. Scopes are
not picklable and foreign-process use/closure rejects. No parent registry is treated
as child ownership. Constructors may be injected; explicit later default invocation
would lazily select grpc sync/async insecure_channel with fixed options. No native
channel was constructed by this proof. Up to16 exact channels are retained per
scope. No reconnect loop or Worker start is added.

Sync scopes close only sync channels; async channels in a sync close are unresolved
errors. A later async close sweeps only unattempted async resources. Once an async
sweep is scheduled it owns the close state, including the scheduling gap before
its coroutine runs. Sync close rejects while that sweep is pending; it cannot
claim settlement or start another sweep. Normal successful close stays idempotent.
Async scopes await their owned async closes within the configured wait and report
timeout/failure; they never call cleanup success for unresolved resources.
`unresolved` retains exact resource identities; `unresolved_tasks` separately keeps
strong references to timed-out close Tasks, including cancellation-resistant ones.
`await scope.join_unresolved(timeout=...)` lets the owner bound a settlement wait
without cancelling/reissuing close. An incomplete/failed join raises and retains
truthful ownership; successful physical completion clears that outstanding ledger.
Eventual exceptions are consumed without raw diagnostics. The owner must settle
outstanding tasks before loop shutdown; a bounded timeout is not forced cleanup.
Sync gRPC close is assumed supported synchronous shutdown; this stage's fake proof
is not a physical native termination guarantee. Cancellation-safe async scope exit
and fixed exceptions avoid vendor diagnostic echoes. A noncooperative close remains
an explicit unresolved resource, not an instruction to kill a guessed process.

Remaining stages require reviewed Worker/child scope entry and shutdown, exact
action-event resend policy, used REST pool policy,
native constructor, new-image identity and separately released native execution.
This patch intentionally fails closed when those unimplemented paths lack a scope.
No global rebinding, dependency resolution or installed source edit is used.

## Stage B RPC and stream policy

GetVersion, Register and PutWorkflow make one attempt with actual10s RPC deadlines.
UNIMPLEMENTED version compatibility and successful protocol results are retained.
Listener lifetime must be an explicit integer1..60 seconds before construction;
ListenV2 uses that lifetime, heartbeat/unsubscribe pass5s. There is one channel
and one stream acquisition per listener; reset/retry/backoff paths are removed.
EOF, stream/heartbeat/decode failure are terminal with fixed diagnostics. Valid
action mapping is preserved. Periodic successful heartbeats remain liveness calls.

Read tasks are strongly owned. Cancellation/interrupt/stop/close cancels the stream
once and waits at most250ms for reads. Resistant reads remain in unresolved_reads;
join_reads(timeout=...) performs a later bounded join (0<timeout<=5) without reissuing
cancel. Repeated cancellation cannot remove outstanding task ownership. The owner
must eventually settle these tasks before closing its loop. Channel closure is
still exclusively ReceiverResources. Stream cancellation failure is explicit.

This stage does not join the existing heartbeat or await the existing synchronous
unregister API's asynchronous call. Successful heartbeats may continue while the
later parent drains active work. Child code still catches terminal stream errors
and waits for parent STOP_LOOP. Stage C1 below supersedes the upstream event retry behavior.
REST/parent/child scope, logs and physical shutdown remain open.
No worker exit, event single-delivery or native readiness is claimed.

### Review correction

Selected GetVersion/Register/PutWorkflow failures now become fixed ReceiverRpcError
values (version_failed, worker_register_failed, workflow_register_failed), raised
after the upstream exception handler so neither context nor cause retains the
upstream diagnostic. Cancellation propagates and UNIMPLEMENTED stays compatible.
Normal malformed JSON/schema payloads fail with payload_invalid and never create
an Action. The focused fake logger records traceback diagnostics if exception
logging is invoked; malformed cases assert that none leaks.

## Stage C1 event boundary

Normal and both batch event methods make one RPC per explicit call with timeout10s.
No event retry, reconnect, nested send task or log-and-return-None remains.
Request mapping, timestamps, should_not_retry and response identity are preserved.
A failure before the stub invocation is event_not_sent. Any failure after invocation,
including auth/deadline/unknown errors or a missing response, is conservatively
event_delivery_uncertain. Fixed EventDeliveryError values are raised outside the
vendor exception handler without cause/context or copied diagnostics. Cancellation
stays cancellation. A server response is observed protocol success, not a durable
domain receipt, deduplication promise or proof that delivery occurred only once.

Child send_event directly awaits the dispatcher. Explicit non-sending action types
return event_not_sent. Duplicate STARTED queue items remain distinct explicit sends.
The queue is polled without an executor thread and consumes exactly one item at a
time. STOP remains ordered. Admission is one owned Task, held strongly with its
exact event in unresolved_sends before the first await. Later items stay queued on
failure. A safe terminal_delivery records only a local sequence, classification
and admission_stopped; it never copies payload, token, vendor text or responses.

The local send wait is12s, then one cancellation and at most250ms settlement.
Cancellation of the waiter does not propagate another cancellation to the send.
Resistant Tasks remain owned by unresolved_sends and step_action_events. Later
join_sends(timeout=...) accepts0<timeout<=5 and observes completed results/errors
once without resending or recancelling. It returns whether owned sends physically
settled; it never clears terminal uncertainty or means the event queue was drained.
A late success/error can settle a Task without rewriting the terminal receipt.
The owner must release/join resistant tasks before closing its event loop.

Entry event-send gather is replaced by the same bounded join. This does not bound
the whole child: parent terminal notification, stop-event wait, heartbeat cleanup,
listener shutdown, executor/asyncio.run teardown and parent/REST/runner ownership
remain C2/later gates. No native image/application/default change is included.

### C1 F1 correction: competing bounded observers

One admission loop remains the owner. Its active send wait and multiple concurrent
join_sends calls on the same event loop can safely overlap. Each captures the
same Task/state before awaiting. Observation is a synchronous idempotent transition:
the first observer consumes task.result(), stores only its safe classification in
that state and removes outstanding ownership; later observers reuse that status.
There is no unbounded task/result history: after ledger removal only current
waiters retain the state, and they release it on return. No raw response/error is
cached in a receipt. The cancellation helper tolerates already settled ownership.
Terminal uncertainty stays permanent even if another join observes a late success.
