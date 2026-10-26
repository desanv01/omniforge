# Receiver derivative Stage B (partial)

This source artifact changes five copied files from exactly1.41.1: config.py,
connection.py, clients/dispatcher/dispatcher.py, clients/dispatcher/action_listener.py
and clients/admin.py. The accepted Stage A config/connection output bytes are retained. It is not installed automatically,
does not patch a running/imported SDK, and is not a runnable native receiver.
The application's UnsupportedReceiver default remains unchanged.

Run the applicator with two explicit disposable paths:

```text
python -B apply_patch.py /disposable/upstream /new/disposable/derivative
```

The source root must contain the five exact upstream files and the installed
`hatchet_sdk-1.41.1.dist-info/METADATA` with matching name/version. Destination must
be absent, separate and not an ancestor/descendant of source. The applicator checks
all original byte hashes, exact unified-diff context and final derivative hashes
BEFORE creating output. It writes only those five files and returns their hashes.
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
and waits for parent STOP_LOOP. Event methods retain upstream retries and channel
reset behavior; REST/parent/child scope, logs and physical shutdown remain open.
No worker exit, event single-delivery or native readiness is claimed.

### Review correction

Selected GetVersion/Register/PutWorkflow failures now become fixed ReceiverRpcError
values (version_failed, worker_register_failed, workflow_register_failed), raised
after the upstream exception handler so neither context nor cause retains the
upstream diagnostic. Cancellation propagates and UNIMPLEMENTED stays compatible.
Normal malformed JSON/schema payloads fail with payload_invalid and never create
an Action. The focused fake logger records traceback diagnostics if exception
logging is invoked; malformed cases assert that none leaks.
