# Receiver REST derivative REST2 (partial)

This separate artifact modifies four copied `hatchet-sdk==1.41.1` files:
features/workers.py, clients/v1/api_client.py, clients/rest/api_client.py and
clients/rest/rest.py. It does not install a package, modify the retained SDK or
make a runnable native receiver. The application default remains UnsupportedReceiver.
The sibling receiver-adaptation artifact has a disjoint source path set and a
different owner. Neither artifact edits or merges the other.

Run `python -B apply_patch.py UPSTREAM_ROOT NEW_DISPOSABLE_OUTPUT` with explicit
paths. The source must contain the exact four upstream files and distribution
METADATA. The output must be absent, separate and outside the source ancestry.
Raw/LF hashes, version/manifest identity, exact paths, unique JSON/patch entries,
patch context, final hashes and source symlink guards are checked before writing.
The result contains exactly four files, not an importable full installation.
A later separately reviewed image assembly must verify disjoint overlays and
final file identities. There is no automatic composition or native entry change.

BaseRestClient explicitly supplies retries=0 and proxy/proxy_headers=None.
RESTClientObject rejects direct callers with unspecified/nonzero retries or proxy
configuration before manager construction. Every request branch passes retries=0,
redirect=False, preload_content=False and finite connect/read/total timeouts.
The defaults are 2/5/8 seconds. Scalar and tuple overrides can tighten these caps;
booleans, nonfinite, nonpositive, malformed or widening values reject before send.
No environment discovery or global HTTP debug setter is used.

One RESTClientObject admits one request. The derivative is intentionally narrower
than general generated-client reuse. GET/list feature retry wrappers are unchanged
and outside the selected receiver pause contract. The selected pause uses the
unchanged generated worker_update timeout seam, exact worker ID/isPaused=True,
one HTTP request and its original successful Worker response. A 3xx is a failure
with no follow-up request. Success is an observed server response, not a durable
domain receipt or proof that the parent stopped admission.

`pause(worker_id, *, owner_capture=None)` optionally calls owner_capture with the
exact ApiClient before sending; `aio_pause` forwards that hook through to_thread.
An unsuccessful hook sends nothing and closes the client. The parent must retain
the captured owner in its own process. The flat, read-only `settlement_snapshot`
contains only booleans and resource counts: admission_closed, request_started,
request_active, response_observed, unresolved_response_count, unresolved_pool_count,
cleanup_attempted and cleanup_complete. response_observed means an HTTPResponse
was obtained, including an error status, not that a validated success was obtained.
Owner objects and native handles are process-local; request/close reject foreign PID.
Snapshot callbacks do not make a lifecycle supervisor or support pickling handles.

RESTResponse owns raw response close and release in that order, each once, even
on read failure. No unread-body drain is used. Cached bytes/status/headers remain
available for generated deserialization. Explicit raw-response borrowers must
finish before ApiClient closes; raw streaming compatibility is not promised.
ApiClient context exit performs one idempotent cleanup sweep, explicitly closing
each observed concrete pool, then clearing its manager. Clear alone does not prove
pool closure. Independent failures do not skip other resources. Control interruptions
propagate after independent cleanup attempts. Failed resources retain strong owners
and cannot become clean by repeating close. Close calls execute outside the snapshot
lock, so a hanging vendor close remains observable. The same resource is not closed
again while its first close is pending.

An early client close during a request or body read stops new admission and latches
an incomplete sweep, retaining the exact request/response/pool references. It does
not retry cleanup after the request returns, cancel the request or claim physical
shutdown. A normal supervising parent should join the request before its one sweep.

Pause normalizes ordinary vendor failures to fixed ReceiverRestError codes after
leaving their handlers: rest_not_sent (proven no pool invocation),
rest_delivery_uncertain (invocation started without validated success), or
rest_cleanup_incomplete (validated result followed by failed cleanup).
Errors expose only code/request_started/response_observed/cleanup_complete, with no
raw cause/context/body/URL/token or diagnostic logging. Cancellation and control
interruptions remain control interruptions; they are not converted into delivery ACKs.
ApiClient context cleanup never suppresses an existing operation exception.

Transport timeouts do **not** bound DNS, complete response wall time, model parsing,
vendor close or physical thread completion. Cancelling aio_pause's asyncio view
does not stop its to_thread request. No thread is detached to claim a hard deadline.
C2 must integrate captured owners, admission, parent/child receipts, event uncertainty,
overall supervision deadline and truthful thread/task/channel/pool/process settlement.
Native entry/image/authority/DB/network, actual enrollment and live provider proof
are separate unreleased gates. This artifact changes no parent worker lifecycle.

Focused offline checks load copied derivative modules and the unchanged generated
worker_update method body using fake model/HTTP graphs. Run from the rebuild root:
`python -B -m unittest discover -s tests/contracts/scheduler -p test_receiver_rest_adaptation.py -v`.
No real SDK import or external connection is required. Windows asyncio uses local
socketpair IPC. Tests gate, release and join their fake threads and restrict cleanup
to the explicitly created disposable directory.

REST2 adds a separate synchronous prepared path for future C2 integration:

```python
# C2 must register and own each thread operation BEFORE starting it.
client = workers.prepare_pause_client(owner_capture=retain_partial_client)
# Physically join the preparation thread before launching a request thread.
result = workers.pause_prepared(worker_id, client)
# Physically join that request thread before launching the one cleanup sweep.
complete = client.close()
```

`prepare_pause_client(*, owner_capture: Callable[[ApiClient], None]) -> ApiClient`
requires a synchronous capture callback. The exact partial ApiClient already has
an accessible REST owner, immutable snapshot and close method at capture time,
before manager creation or later header/property initialization. The manager is
attached to that REST owner before the manager's upstream constructor executes.
Failed/blocked construction therefore remains observable to the capturing caller.
Capture failure aborts before manager/request side effects. If a concrete manager
constructor fails, its retained partial owner remains conservatively incomplete
even if its clear method returns; that return cannot prove all init resources closed.
Header/property failure after manager initialization also preserves the exact owner
for the caller's later cleanup. Prepared construction does not auto-close on failure.

`pause_prepared(worker_id: str, client: ApiClient) -> Worker` validates the exact
ApiClient type, local PID, full initialization, binding to this WorkersClient by
object identity and unclaimed/open transport state before invocation. It atomically
claims admission once. A failed preflight still consumes that prepared claim;
there is no automatic retry. External/unprepared, partial, foreign owner/PID,
already used or closed clients are refused. No native handle or identity token
is serialized. This is a local API contract, not protection against malicious
same-process mutation of Python private attributes.

The prepared request does not call client.close on success, ordinary failure or
control interruption. Ordinary errors remain fixed safe not-sent/uncertain errors.
The generated response read retains its existing response-close/release behavior;
concrete pools and client sweep stay under the caller's ownership. The parent
must physically join request execution before its one cleanup operation. Existing
pause/aio_pause remains a separate auto-close path; its external owner_capture
still runs after complete construction, while an internal early capture now
retains partial construction for its own finally cleanup. BaseRestClient.client
accepts the optional construction-only capture keyword; custom overrides must
forward it to retain the partial-construction guarantee.

Snapshots additionally expose construction_active, construction_complete,
prepared_admission and prepared_claimed. prepared_admission becomes true only
after all initialization succeeds and binding is installed. An early close while
construction is active latches incomplete cleanup, never clears a concurrently
initializing manager, and prevents successful prepared dispatch. Repeated close
does not erase that uncertainty. No source code automatically starts a thread or
installs a supervisor. Preparation can block in manager/config/header work;
request and cleanup can also block. C2 must retain the exact preparation operation
before launch, record the callback in a thread-safe local ledger, physically join
preparation before dispatch and request before cleanup, and report unresolved
operations at its supervisor deadline. Cancelling an asyncio observation is not
thread completion. No event-loop synchronous constructor or Future timeout may
be presented as a hard completion bound.
