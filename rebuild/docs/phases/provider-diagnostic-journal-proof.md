# Provider diagnostic journal — source and inert evidence

OF-012P-JOURNAL-A implements a connection-bound authority seam and additive journal
source. Independent review is pending. Migration 0009 is source only; no database
connection, schema application, credential store, provider call or native execution
was performed in this task.

`load_profile_conn` retains current token/writer/profile/binding/budget checks on
the caller's supplied connection. Existing `load_profile` keeps its transaction
wrapper, configure behavior and invalid-purpose denial before opening a transaction.
Journal normal decisions acquire authority before the operation and ordered rounds;
settlement acquires only operation/round locks and cannot call normal authority in
reverse order. Fixed ceilings and shrinking post-lock statement bounds accompany
fresh clock_timestamp checks against an injected fixed absolute cutoff. No sampled
remaining duration is added to a later clock to extend work.

The operation/round tables retain immutable invocation identity, budget, expiry,
capability digest, reservations, exact usage and candidate/stop history. Reservation
commit means possible dispatch; exact replay adds no row/charge or new capability.
Observation charges are max(reservation, known reported usage); missing dimensions
remain unknown with known subtotals. Overshoot is retained and stops further work.
Candidate and final authority require nonempty fully observed reservations. A
candidate is history, never proof of timely local delivery or atomic cancellation.

Settlement uses a private operation/invocation-bound 32-byte injected capability,
hashed at rest, and a conservative cutoff no later than work expiry plus four
seconds. It can close and fill only missing exact-reservation observations, not
refund, overwrite conflicts, reserve, reopen, candidate-commit, authenticate normal
execution, read evidence/store, call a provider or deliver. Its exact consumed batch
replay has no effects; changed batch or capability conflicts. Raw capability is
excluded from repr and nonsecret payloads. A prepared admission decision is internal
to the trusted caller, not permission to bootstrap or dispatch before commit.

Every external trust boundary defaults unavailable: registered command/context
provenance, conservative cutoff producer, capability issuer and post-commit receipt
publisher. Missing prerequisites deny before journal mutation. Injected callbacks
are trusted internal interfaces, not an alternate ACL or wire-provided booleans.
Returned `Decision` objects are explicitly prepared; only a separately trusted
publisher after exact commit/pending-channel validation may emit a committed receipt
and capture a capability once. Real InvocationContext/Token/channel/native-clock
adapter and one-use return bridge are absent and remain fail-closed prerequisites.
Current process delayed-launch rejection is unchanged. No default engine, CLI,
store/provider factory or production runtime integration is provided.

## Executed inert checks

Fourteen focused contract/order tests passed with the existing pinned interpreter,
including three affected authority extraction/wrapper tests. Tests use finite
statement-recording stubs and injected deterministic capabilities/cutoffs, never a
database or OS store. They check default-denial before mutation, strict identities,
same-connection authority/lock/clock order, elapsed deadline through capability
issuance, expiry/replay nonextension, foreign invocation/request digest rejection,
prepared-versus-committed one-use publisher boundary, exact reservation/usage replay,
unknown totals/charges, overshoot stop, nonempty candidate, candidate retained after
stop and final-authority denial, and capability-only settlement without reverse
authentication/duplicate effects. Fake SQL state recording does not prove real SQL,
row locking, triggers, concurrent commit ordering or IPC/native validity.

The initial test fixture used an invalid opaque reference, then the test namespace
accepted by CredentialRef but denied by EnrollmentBinding. The fixture was corrected
to a syntactically valid synthetic v1 reference; no credential existed or was read.
Both setup failures are retained in the private delivery chronology. Subsequent
tests passed; no unchanged retries or real enrollment occurred.

## Deferred PostgreSQL and integration evidence

`tests/integration/core/provider_diagnostics.py` is unexecuted fixture source requiring
explicit Backend engine injection and separately applied isolated schema 0009.
It has no environment discovery, engine construction or migration application.
It prepares fresh synthetic principal/case/profile/binding metadata without a store,
preserves original projections of all eighteen existing tables, and defines real
SQL lifecycle/replay, concurrent admission/capability issuance, grant-revocation
barrier, post-profile-lock-wait expiry and zero-round candidate checks. Its cutoff
and capability issuers are labeled synthetic. These functions have not run here.

Remaining real evidence includes migration syntax/constraint/trigger execution,
two-connection token/profile/revoke/expiry/digest races, both stop/candidate commit
orders, settlement misuse and captured original-projection preservation. No real
clock mapping, post-commit publisher/channel capture, process closure, actual return,
paid provider, enrollment or invoice claim follows from this source slice. Database
version guards outside this reserved scope remain unchanged; an actual runtime
release must explicitly settle compatibility and ownership before applying 0009.
External capture is still unresolved and cannot be waived by these inert tests.

## F1/F2 source correction, independent delta review pending

The v1 fourteen-test freeze is retained as historical evidence. B identified that
the original fixed pre-lock ceiling could outlive a short/expired absolute cutoff,
and the deferred fixture's started event did not establish an actual SQL lock wait.
Neither was an executed PostgreSQL or native result.

Execution-capable decisions now validate the trusted fixed cutoff and reject expired
time before any authority/operation lock. A narrow internal `before_statement` seam
in the connection-bound authority loader rearms shrinking bounds before each nested
token/grant/profile acquisition on the same supplied physical connection. Operation
advisory/row locks and ordered round acquisition likewise receive fresh pre-stage
bounds, with pinned-row checks and fresh post-lock guards retained. No earlier
remaining duration is added to a later clock. Historical readback alone retains its
independent fixed policy. SQL timeout/clock checks do not guarantee OS scheduling or
COMMIT completion before the cutoff; external parent/native controls remain absent.

The focused inert module now passes seventeen tests, including expired-before-lock
denial, ten-millisecond authority budget consumed across token/grant statements with
no subsequent profile acquisition, and elapsed operation lock stages on both normal
and settlement paths with no later row lock after expiry. Supplied timeout limits
are asserted, not only mutation denial. Default wrapper behavior remains covered.

Deferred PostgreSQL fixture source now obtains the exact contender backend PID and
observes `pg_locks`/`pg_blocking_pids` for that PID and its exact holder before release.
Profile barrier also matches the actual Python advisory key. Grant holder owns only
the named new grant conflict. Bounded polling cadence is not itself evidence; failure
to observe the wait fails the test. Revocation must return precisely403/profile_forbidden.
An observed profile wait past the short remaining budget must yield lock/statement
timeout SQLSTATE55P03/57014, not an arbitrary domain Problem. Fresh post-lock expiry
is covered by the inert stage checks; this timeout fixture does not pretend to show
a successful lock acquisition after its deadline. Concurrent admission still checks
one durable row/capability result without claiming its start barrier proves overlap.

All seventeen inert tests passed; no PG fixture, migration or live/native operation
was executed for this correction. Real PostgreSQL timing, barriers, triggers and
schema remain a separately released future gate. B owns F1/F2 closure after review.

## First delivery packaging: schema promotion withheld

B's v2 source review closed F1/F2. The first staged delivery contains only the
authority extraction, journal repository/contracts, seventeen inert tests, deferred
PostgreSQL fixture source and this document. It deliberately omits migration 0009
from the active migration directory. The local immutable 0009 schema proposal is
withheld until separately reviewed schema/runtime promotion; current delivered
database head and runtime guards remain 0008_run_cancellation.

These five files have no import or test dependency on the withheld migration file.
Inert tests inject statement recorders and require no diagnostic tables. The
PostgreSQL fixture explicitly requires a future separately applied schema 0009 and
must not run against the current database. Repository callbacks for real cutoff,
registered provenance, capability capture and committed receipt publication remain
unavailable by default. Importable source and passing inert checks do not establish
a usable journal, completed integration or production execution capability. Main's
separate inert CI step does not authorize migration application or deferred SQL.
