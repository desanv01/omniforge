# OF-013-B1 — durable queued Run journal

24 October2026. Implemented and tested, awaiting independent review. B1 persists
admission/cancellation/history only. It does not dispatch a scheduler, claim an
attempt, run tools/provider work, publish outputs or serve SSE.

## Supported API boundary

POST `/api/v1/cases/{case_id}/runs` accepts only kind synthetic-read-only-v1 and
policy local-read-only-v1. The body contains at most32 unique immutable association
refs (UUID/revision/lowercase SHA256) and a synthetic budget: integer-zero model
calls/input/output/tool bytes, with integer wall_seconds1..60. Unknown fields,
unsupported kinds/policies/provider profiles and coercible bool/string/float body
versions/budgets reject. The server verifies current write grant and matching
case-bound committed association metadata, then snapshots artifact/source/byte
identity with coverage unknown. It does not infer source authenticity or read
every input blob merely by admitting metadata.

A single database transaction persists Run queued/revision1, event1, pending start
intent and canonical idempotency response before HTTP202. Idempotency remains
principal+operation+target+key scoped. Same key/body replays; changed body409;
fresh grants precede even replay. Grant rows are held shared through admission
commit; model input/scope snapshots never supply authority. No API import starts
work or imports Hatchet. Scheduler/provider health remains unverified.

GET `/api/v1/runs/{id}` grant-filters state. Unknown and ungranted run IDs404;
missing/invalid bearer401 and arbitrary principal headers cannot identify a user.
Queued cancel POST requires expected_revision plus Idempotency-Key. It serializes
on the Run row, checks current write authority, appends cancel_requested and
canceled events, advances revision1 to3 and suppresses the pending start intent
in one transaction. Same-key replay returns the original response despite now-
stale revision; a new stale key409. Late cancel of an already canceled Run with
current revision returns unchanged terminal state, adding no events/output.
This is safe because no dispatcher or attempt exists in B1.

GET `/api/v1/runs/{id}/events` returns bounded JSON only: maximum100/page,
ascending per-run sequence and next_after/has_more. Cursor0 starts history;
after and Last-Event-ID are bounded ASCII decimal strings, with no signs,
whitespace, fractions or exponent coercion. Conflicting cursors409, invalid422,
future409. No events are expired/deleted. Explicit text/event-stream Accept
returns safe unsupported501. Stream closure/replay pagination implies no run
completion. The generated client/OpenAPI describe these actual endpoints.

## Persistence and schema

Forward0003_runs adds only runs, run_events and run_outbox, preserving existing
tables and old migration files. FKs/indexes connect cases/principals and journal
rows; event(run_id,sequence) is primary/ordered identity. Run-row serialization,
not an unlocked MAX+1, allocates events in the state transaction. Stable dispatch
key is unique and contains the logical run ID. JSON types/byte/count bounds are
enforced in DDL as well as typed API admission; payloads contain safe status/ID
refs, not evidence bytes, credentials or arbitrary provider content.

B1 DDL permits only queued/cancel_requested/canceled and start outbox
pending/suppressed. Nullable attempt references remain empty, fence0 and outputs
empty. Attempt/lease/output/external-execution tables, dispatcher claims, network
acknowledgements and recovery are later migrations/tasks. Pending outbox means
durable intent, never submission or success. Existing staged publication behavior
and quota/recovery limits are unchanged.

## Actual proof and reproduction

The sole core runtime owner verified and reused the retained isolated rebuild DB,
without bootstrap or legacy/Phase0 access. Migration asserted actual prior0002,
compared counts and ordered row fingerprints of all6 existing core tables before/
after, and verified exactly the3 B1 tables were added. All prior counts/fingerprints
were unchanged and version advanced to0003_runs. Old0001/0002 files and dependency
lock stayed unchanged.

With an explicit private config for that owned runtime and the existing locked
Python environment, source-root commands are:

```powershell
python -B -m infra.core.migrate
python -B -m unittest tests.integration.scheduler.core_journal -v
python -B -m unittest tests.integration.core.check tests.integration.core.provider_integration -v
python -B -m infra.core.generate_client
infra/core/client-tooling/node_modules/.bin/tsc -p infra/core/client-tooling/tsconfig.json
```

Run only under the coordinated sole-owner runtime window; do not create a second
database or rerun migrations merely to inspect the evidence. Actual execution
used one combined unittest runner for the7 journal,8 affected core and1 provider
tests: **16 passed,0failures/errors**,11.639s test execution (14.776s full runner).
No runtime failure/correction/retest was needed. Strict generated TypeScript compile
also passed. The historical provider fixture's only compatibility delta was its
expected migration0002 to0003; its original accepted result remains preserved.

The7 B1 checks establish concurrent identical admission gives one Run/event/outbox;
body/principal/key conflict handling; fresh-app persisted reload; rollback after
Run/event/outbox writes and before commit leaves no partial admission/idempotency;
cross-case/hash/revision/pending-input/grant and strict-body rejection; concurrent
cancel/replay/stale/late-terminal handling; current authority before replay;
per-run JSON paging/cursors/restart and explicit SSE501; actual Run-row lock wait
and subsequent pending-intent suppression. The race fixture observes a PostgreSQL
Lock waiter blocked by the exact holding backend PID before releasing it. It is
not a dispatcher/leased-claim/attempt-admission race; those belong to B2.

Final domain receipt contains4 queued/4 canceled runs,4 pending/4 suppressed
intents,0 attempt refs and0 published outputs. Those are retained synthetic
histories, not unfinished execution accidentally reported as complete. Existing
core/provider checks cover health/error/OpenAPI equality, persisted cases,
artifact provenance/grants/hash/ranges/recovery/limits, non-UTC capture and actual
deterministic provider authority. No live model, OS credential-store or Hatchet
call was made by this proof. No API listening process was started.

The owned database was gracefully stopped and exact-ID inspect confirmed exit0;
container, volume, data, original/failed evidence and private config remain
preserved. No source/private paths or secret values belong in public commits.

## Review and remaining gates

Backend owns migration/aggregate/auth closures/shared schema/client/runtime;
scheduler owner owns runs contracts/repository/router and journal fixtures. Their
RunBindings explicitly share the existing engine/principal/grant/idempotency
callbacks; no copied or weaker identity path is added. Independent C reviews the
combined frozen source and actual receipts before Main acceptance/integration.

Parent OF-013 remains incomplete: actual scheduler dispatch/mapping reconciliation,
attempt claims/leases/fencing, current authority before real tool/publication,
output+terminal event commit, interruption/recovery/cancellation settlement,
worker dependency lock/image and SSE remain pending. B1's injected transaction
rollback and fresh-app reload are not process-kill, power-loss, backup/restore or
scheduler recovery proof. No B2 work starts under this delivery automatically.
