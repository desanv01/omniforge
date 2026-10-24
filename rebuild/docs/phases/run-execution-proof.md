# OF-013-B2 — fenced synthetic execution with a fake scheduler port

24 October2026. Implemented/tested, awaiting independent review. This is an actual
PostgreSQL domain-execution proof with an in-memory fake port. No real scheduler,
provider/tool/network execution, API listener, profile setup or B3 feature is added.

## Domain and dispatch boundary

Migration0004_run_execution adds attempts, immutable synthetic outputs and external
execution mappings, and extends the B1 Run/outbox lifecycle. Same-run composite
foreign keys bind current attempts, attempt events, output attempt/fence and
execution-to-outbox identity. Existing B1 rows and pending intents are preserved;
no startup/migration scans or dispatches them. Dispatcher requires an explicit
bounded allowlist of new Run UUIDs, rejecting outside IDs before SQL/port calls.

Reservation commits before submit/lookup, so a scheduler-port call holds no Run
transaction lock. Outbox claims use DB-time leases and token comparison. Stable
dispatch/input identities persist; acknowledgement loss goes to reconciliation,
not blind retry. Confirmed absence permits a bounded harmless retry; unknown stays
reconcile_required. Each intent admits at most2 submit reservations and2 lookups.
The fake port intentionally permits duplicate execution identities; the mapping
UPSERT atomically checks existing Run/outbox ownership before acknowledging a
conflict. An external-ID collision cannot acknowledge the wrong Run. These are
fake-v1 observations, not measured native Hatchet idempotency/search semantics.

Execution requires a reconciled mapping, current write grant, unchanged scoped
input metadata, expected revision and eligible domain status. Claim persists the
attempt, higher fence, DB-time lease and event before work. At most2 synthetic
attempts are admitted. Work admission/renewal/publication recheck current scope,
grants, active attempt/fence/revision, lease and original wall budget. Heartbeats
return fresh command tokens/revisions and cap deadlines at the original started
time plus budget. Lease expiry can mark harmless work interrupted; replacement
attempt fences reject the old token even when it supplies the current revision.
Failed/uncertain effects do not automatically retry.

Output is only bounded synthetic JSON `{value: string}`, at most1024 characters
and8192 canonical UTF8 JSON bytes. Key/hash/content, producing attempt/fence and
original command revision persist with output_refs, terminal succeeded state and
terminal event in one transaction. Precommit failure rolls all of them back.
Exact postcommit command replay returns the committed result; changed content,
output key, command revision or stale attempt conflicts. A duplicate concurrent
publication yields one output and terminal revision. Current grants still precede
canonical replay. Zero external provider/tool usage is stated accurately; old B1
no-dispatch usage remains readable. Scheduler completed observations alone never
make the Run succeed or fabricate output.

Existing GET Run/JSON events deserialize these richer states/refs. No HTTP
execution/claim endpoint is exposed. B1 queued cancellation remains supported;
active cancellation/cleanup settlement, SSE and real scheduler recovery are B3.

## Actual executed proof

The backend owner reused only the identified retained isolated core database.
Forward migration checked actual0003, preserved counts/ordered row fingerprints
for all9 existing tables' original columns, and added exactly3 B2 tables. New
outbox default fields are additive; comparison explicitly projects original
columns. Before/after the entire proof, all8 retained B1 Runs/events/outbox rows
(including new default fields) remained unchanged and no old intent was dispatched.

The combined first run passed **26tests,0failures/errors**:10 new B2 execution,
7 B1 journal,8 affected core and1 deterministic provider integration. Unittest
reported14.436s (16.214s full import/runner). No runtime correction/retest was
needed. Source review before that first run tightened canonical output byte bounds
and atomic mapping ownership; these were not failed runtime attempts. The actual
generated OpenAPI client passed strict TypeScript compilation without dependency
changes. The provider regression used its separately frozen authorization-boundary
source; this delivery does not replace that task's independent review.

The10 new checks exercise concurrent dispatch without holding a SQL lock during
the port call; one live attempt under duplicate delivery; submit/ack loss and
reconciliation; bounded pre-submit loss/redelivery/unknown outcomes; DB-time
renewal/expiry/new fence; exact committed-output replay/conflict; precommit output/
terminal rollback and ignored postcommit acknowledgement; revoked scope/grant and
canceled rejection; failed/uncertain nonretry; concurrent one-output publication;
attempt/dispatch authority caps; and colliding scheduler execution IDs across Runs.

Faults are injected exceptions, discarded control-flow acknowledgements and
deliberately expired reservations, not killed operating-system processes. Real
DB-time lease expiry was observed using short bounded waits. No real scheduler
restart, provider I/O or hard in-flight interruption/cleanup timing is claimed.

Source-root reproduction uses the existing locked environment, explicit private
core configuration and sole-owner runtime window:

```powershell
python -B -m infra.core.migrate
python -B -m unittest tests.integration.scheduler.core_execution -v
python -B -m unittest tests.integration.scheduler.core_journal tests.integration.core.check tests.integration.core.provider_integration -v
python -B -m infra.core.generate_client
infra/core/client-tooling/node_modules/.bin/tsc -p infra/core/client-tooling/tsconfig.json
```

Do not bootstrap another database or drain retained intents to reproduce a review.
Actual execution used one combined runner; no unchanged suite was repeated.
Existing core/provider fixture migration expectations advanced0003 to0004 only;
their accepted historical snapshots remain preserved separately.

## Retained state and limits

Initial combined-proof synthetic domain snapshot:31 Runs (14queued,9canceled,2running,3succeeded,
1failed,1uncertain,1interrupted),10attempts,3outputs and11mappings; outbox9pending,
9suppressed,11acknowledged,2reconcile_required. Unfinished/running journal fixtures
are retained history and do not imply a live worker; no worker process/daemon
exists here. Expiry/recovery is explicit, not a background service. No cleanup
or terminal-state fabrication was performed to make that history appear complete.

The owned DB was gracefully stopped, exact-ID inspection exit0; its volume,
configuration, original data and all receipts remain preserved. No API listener
or other owned service remains running. No new dependency/lock, legacy/Phase0
database, credential-store/provider key or unrelated process was touched.

Main/C review and delivery are pending. B3 remains responsible for actual scheduler
runtime integration, active cancellation/cleanup acknowledgement, observable
settlement and SSE/reconnect; profile/setup/live-provider proofs remain separate.
This does not complete parent OF-013 or whole Phase1. Hostile concurrent file
mutation, power-loss/backup recovery and sustained-ingestion quota/cleanup are
also outside this bounded synthetic execution proof.

### C review correction — lease expiry across an authority-lock wait

Independent review found that the initial live-lease check preceded potentially
blocking authority/input locks. A call could wait beyond expiry while the grant
remained unchanged, then admit work or renew the expired lease. The corrected
guard retains Run/attempt lock order and rechecks the live lease using DB time
after the blocking authority checks and wall-budget check, before returning.
It changes no DDL, DTO, API shape, dependency or generated client.

The new focused test covers admission, renewal and publication with separate new
synthetic runs. It holds the unchanged grant row, observes an actual PostgreSQL
waiter blocked by the exact holder PID, observes database time crossing the
original lease while the lock is held, then releases it. Each operation returns
409 lease_expired; Run revision/event sequence, attempt deadline and output count
remain unchanged. Three directly affected lease/fence/publication regression
methods were included. **All4 focused methods passed in5.921s**, with no further
correction/retry. The original26-test receipt remains preserved; the full suite
was not repeated. No migration or client regeneration was needed.

All retained B1 history remained unchanged after this check. The new synthetic
fixtures bring the retained journal to37runs/17attempts/6outputs;5running records
are unfinished metadata without any live worker. The exact owned database was
again stopped with exit0, preserving its volume/data and all original receipts.
Corrected source/results remain subject to C's delta review before acceptance.
