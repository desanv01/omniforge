# Receiver derivative Stage A

This source artifact changes ONLY copied `hatchet_sdk/config.py` and
`hatchet_sdk/connection.py` from exactly1.41.1. It is not installed automatically,
does not patch a running/imported SDK, and is not a runnable native receiver.
The application's UnsupportedReceiver default remains unchanged.

Run the applicator with two explicit disposable paths:

```text
python -B apply_patch.py /disposable/upstream /new/disposable/derivative
```

The source root must contain the two exact upstream files and the installed
`hatchet_sdk-1.41.1.dist-info/METADATA` with matching name/version. Destination must
be absent, separate and not an ancestor/descendant of source. The applicator checks
both original byte hashes, exact unified-diff context and final derivative hashes
BEFORE creating output. It writes only those two files and returns their hashes.
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
registration deadlines, version/listener/event resend policy, used REST pool policy,
native constructor, new-image identity and separately released native execution.
This patch intentionally fails closed when those unimplemented paths lack a scope.
No global rebinding, dependency resolution or installed source edit is used.
