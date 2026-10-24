# OF-013-B3A — offline Hatchet boundary

Status: awaiting independent review. Offline adapter only; no real scheduler,
application execution, active-cancel cleanup, SSE or parent OF013 acceptance.

## Implemented boundary

The new asynchronous HatchetPort takes an injected client, pinned workflow/tenant/
version/namespace binding, bounded dispatch identity and policy. No module import
creates a Hatchet client, gRPC channel, HTTP session or credential/config lookup.
SDK imports occur only in pure serializer helpers or explicit operations. SDK
selection remains1.41.1; no dependency/lock/environment changes were made.

Submission sends a server-bound Run/key/input hash/generation and derived physical
dispatch identity. A normal or collision execution ID must pass detail lookup,
tenant/workflow/version/metadata and actual root-input verification before it is
acknowledged. Root execution and task IDs remain separate. All five native states
QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED are retained as broker observations;
none proves application success or cleanup. A known but unverified ID is only a
candidate for later durable reconciliation, not an authorized execution mapping.

Observed input must have the exact permitted keys and primitive types before
value comparison. Generation is an integer0/1; equal-valued booleans/floats/strings
are rejected. The optional SDK-shaped wrapper is exactly `{input,overrides}` with
overrides=null and the same strict inner payload; extra/missing keys do not widen
authority.

Lookup uses exact workflow ID and metadata AND filters, explicit time window,
maximum2 pages of50, maximum2 root executions and bounded task details. It validates
pagination, all correlation fields and task/root relationships and rechecks root
details. Empty, lagging, malformed, inconsistent, oversized or incomplete results
are unknown. It never returns absent and never automatically resubmits. No implicit
tenant-wide/default-day scan or SDK auto-pagination is used.

Cancellation first verifies the exact root belongs to this dispatch, then requests
only that ID. Repeated requests are allowed, but even observed CANCELLED produces
cancel_requested with cleanup_proved=false. There is no active domain cancellation
transaction, handler-finally acknowledgement or resource rollback in this adapter.

## Deadlines, retries and safe failures

Each port operation has one monotonic/asyncio total deadline shared across trigger,
pages, detail reads and cancel. RawSdkClient passes a deadline to the injected raw
async gRPC callable and uses aiohttp total/connect/read limits plus asyncio timeout
around HTTP response/body reads. It does not use uninterruptible background threads
or return while a timed-out await silently continues. Body reads are bounded64KiB;
redirects and compressed responses reject. Response objects close on timeout/error.

SDK attempts must be1. High-level SDK Tenacity helpers are bypassed by this raw
transport. The injected HTTP session must have trust_env=false, auto_decompress=false,
no middleware and its pinned `_retry_connection` flag already false; the adapter
validates these without mutating a live session. No HTTP connection retries or
redirect following are requested. The future external raw-gRPC factory must also
disable channel retries (including service configuration); no channel was created
or its network behavior measured in this offline slice. This private aiohttp flag
and raw SDK serializers are version-sensitive integration seams, not stable API
promises. Caller owns approved destination, authorization and session lifecycle.

Only fixed safe failure/result codes escape; no raw upstream body/exception/token/
local path is emitted. An outer task cancellation propagates, allowing response
cleanup rather than being misrepresented as scheduler success. Submit timeout may
mean accepted upstream and stays unknown; no hidden submission retry is added.

## Pinned source/serializer facts checked

Hatchet SDK1.41.1 AdminClient's pure trigger serializer forwards input and metadata,
but ignores TriggerWorkflowOptions.key. Identical request bytes with/without that
key were verified. It is not used as native root-run idempotency.

The separate workflow-definition TTL idempotency protobuf supports
`input.dispatch_identity` and TTL; pure construction checks expression/TTL, without
registering a workflow. The CEL expression, installed engine support, collision/
TTL expiry and safe recovery-generation behavior remain real-runtime gates.
SDK IdempotencyCollisionError is decoded as a candidate ID and still requires full
correlation verification. Exact REST route/filter/body shapes follow the pinned
generated SDK; actual engine semantics remain unproved here.

## Actual offline checks

Using the existing task-private pinned environment, unittest initially ran16 checks:
15 passed and one test-only assertion failed because two fast calls shared one
Windows monotonic tick. The test was corrected to inject deterministic elapsed
time; that one focused test passed in0.100s. Adapter implementation did not change
for that correction. The other15 passing results remain applicable; no unchanged
full-suite rerun is represented as a new green aggregate.

Coverage includes no-client constructor guards/pure pinned serialization,
input/hash/collision correlation, distinct root/task IDs, metadata AND filters,
complete pagination and overflow/mismatch/empty/lag behavior, bounded policy and
generation, exact cancellation and no-cleanup verdict, all broker statuses,
actual cancellation of stalled async operation/body await, response closure,
transport deadline forwarding, one SDK attempt, body bounds and failure redaction.
The test transports are in-memory doubles; no vendor/DB/provider connection,
credential access, installed service, image build or container operation occurred.

Independent review found a P2 type-coercion gap in the original observed-input
dictionary equality: Python considers False==0, True==1 and1.0==1. The correction
validates exact keys/primitive types and wrapper shape before equality. Only two
new focused regression methods were run: both passed in0.282s. They cover malformed
boolean/float/string generations for both0/1 and direct/wrapped payloads across
normal submit, collision submit and cancel, valid integer controls and malformed
wrapper rejection. Invalid input never sends cancellation. Original15 passing
checks and corrected test05 evidence remain distinct; no final18-test aggregate
or full unchanged suite rerun is claimed. Final independent closure is pending.

Windows sandbox asyncio setup first stalled in its internal socketpair creation
before test setup. The owned process was stopped; a bounded diagnostic identified
the local IPC issue, and the offline suite ran with that IPC permission. This is
not scheduler connectivity evidence or a product/runtime correction.

Ordinary CI from rebuild root, after an explicitly assigned task-local SDK lock
setup (do not install into the root/backend environment):

```
python -B -m unittest tests.contracts.scheduler.test_hatchet_port -v
```

## Required next bridge and limits

This asynchronous Result/native-status contract deliberately does not modify or
implement B2's synchronous fake SchedulerPort. B2 hardcodes fake-v1 mappings and
accepted/completed observations, and assumes acknowledged mapping before worker
claim. A separately assigned B3B bridge must handle real kinds/statuses, persisted
candidate IDs/generation/hash/workflow binding, early delivery before submit ACK,
late ACK bookkeeping, bounded recovery budgets and domain cleanup generations.
Do not wire this class into B2 and infer compatibility from its method names.

Backend exclusively owns post-metadata migrations/SPEC/OpenAPI/API/SSE/cancel
transactions; worker-only combined lock/runtime factory and real proof require
their own assignment. Real metadata search lag/paging, dedup/collision/TTL, cancel
delivery/finally, core-connected Linux worker and interruption/recovery remain
B3C gates. Retained resources/tokens were not inspected or reused by this slice.

Primary pinned source inspected: SDK1.41.1 clients/admin.py, types/trigger.py,
types/idempotency.py, generated REST workflow-runs/task APIs and models, config.py,
connection.py and clients/rest/tenacity_utils.py. Hatchet remains an external MIT
dependency. Original adapter code copies no vendor implementation; it invokes the
existing pinned pure serializer. Upgrade requires equivalent offline and real
compatibility checks before changing the boundary.
