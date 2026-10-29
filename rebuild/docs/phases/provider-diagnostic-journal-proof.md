# Provider diagnostic journal — source and inert evidence

## Current API schema contract promotion (28 October 2026)

The API now requires exactly **0009_provider_diagnostics**, and no-argument
`python -m infra.core.migrate` selects that exact revision. Closed explicit targets
`--target 0008_run_cancellation` and `--target 0009_provider_diagnostics` remain
distinct; an already0009 database cannot be downgraded to0008, and unknown/ahead
revisions fail. The four current core/profile/binding/provider integration fixture
expectations move together to0009. The isolated journal runner still explicitly
seeds at0008 before applying0009 and checking its same-target no-op.

**Worker schema9 source compatibility now awaits independent review and actual
SQL permission proof.** Its exact requirement is0009 with twenty application-table
coverage and explicit denial of both journal tables; existing grant columns remain
unchanged. Actual worker-role SQL/native readiness is not established by source
acceptance or API compatibility. No retained database, volume or configuration is
migrated or cut over by this source change. Earlier0008-only statements below are
historical and superseded by this source contract, not runtime acceptance.

Completed prerequisite evidence: PR44's intended-head and postmerge isolated
synthetic PostgreSQL runs each passed all eighteen journal cases. Postmerge was
verified at e26996ab9cce591dd1b5a84b07669764915df96d. All eighteen original tables
had nonempty synthetic baselines; original projections were preserved and the
runner observed zero checked-out connections and disposed its pool. Independent
review accepted that bounded SQL evidence. This establishes the staged synthetic
schema/journal proof only. It does not establish native termination, live-provider
behavior, real credential enrollment, real clock/provenance/capability producers,
committed ACK publication or final return atomicity; external capture is unknown.

This subsequent API/default promotion is source and inert checks only pending
independent review and Main's intended-head full core/provider/profile/binding,
Run/cancellation/streaming/browser regression plus staged journal CI. The worker
remains excluded from actual0009 runtime readiness. Main owns workflow target changes
and actual CI release. Historical source-only and0008-default statements below
describe the earlier packets and are superseded by this current contract and the
completed PR44 proof; their original failure/result history remains retained.

Focused promotion verification passed all **35 inert tests**, including exact0009
default/API agreement, distinct explicit0008/0009 selection, ahead/unknown denial,
and the runner's explicit0008→0009→0009 calls. The worker's then-current0008 contract
was checked without starting it. Later worker9 source checks supersede that
historical expectation. No integration fixture, database or migration was executed
during this API promotion source task.

Subsequent worker9 source verification passed64 focused inert checks covering
settings/startup, complete authority/projection/denial/failure boundaries and these
journal contracts. Worker exact9 and unchanged staged8→9 migration sequence are
covered together. Actual worker-role SQL, session settlement and native readiness
remain separate; the disposable controller/harness has not been released here.

## Historical initial journal source packet

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

## Staged schema source packet (28 October 2026)

This later packet prepares the reviewed, byte-preserved 0009 migration together
with a closed migration CLI and a separate synthetic CI runner. Historical commands
above describe their original release. No-argument `python -m infra.core.migrate`
now targets **0008_run_cancellation**. The only other accepted target is
`--target 0009_provider_diagnostics`. Unknown targets fail before configuration or
migration I/O; an unknown current revision or a database ahead of the target fails
without downgrade, stamp, reset or seed. Same-target calls delegate the normal
Alembic no-op. API and worker guards remain exactly 0008; this is no global schema
promotion or claim that either service operates at 0009.

Main owns the workflow and independent config generator. The runner requires
GITHUB_ACTIONS=true, exact job postgres-provider-journal and positive decimal run
ID/attempt, explicit canonical RUNNER_TEMP and GITHUB_WORKSPACE paths with neither
containing the other, and a fresh root directly under RUNNER_TEMP named
omniforge-journal-ci-*. OMNIFORGE_CONFIG must select that root's config.json;
OMNIFORGE_JOURNAL_CI_MANIFEST must select manifest.json there. Manifest fields are
closed: schema_version integer1, purpose omniforge-provider-journal-ci-v1, run_id,
run_attempt, job, root, config and workspace, all matching the current trusted job.
Config fields are exactly database_url and artifact_root, the latter root/artifacts.
No auth-token is made or accepted. The URL is postgresql+psycopg with exact host
127.0.0.1, port5432, database AND user omniforge_rebuild_journal_ci, static public
test password ephemeral-journal-ci-only and no URL options. Marker/prefix alone
does not authorize a database. Trusted Main workflow provenance remains a required
boundary; these metadata checks are not a cryptographic attestation of CI.

The separately released command will be
`python -B -m tests.integration.core.provider_diagnostics_runner`. It first requires
the exact connected database/user/session-user and an empty public schema, records
the cluster identity, applies 0008, seeds representative synthetic metadata into
all eighteen original tables, captures ordered column projections, counts and row
hash multisets plus schema/constraint/index digests, then explicitly applies 0009.
It compares preservation, repeats the same target without reseeding, and runs the
injected-engine matrix. Empty baseline tables fail; incomplete setup is reported
separately. One runner invocation owns this lifecycle; there is no phase handoff or
retained configuration discovery. Baseline includes completed synthetic Run output,
an active cancellation with unknown cleanup receipt and an untouched queued intent.
Those are test metadata, never native scheduler or process evidence.

Seventeen deferred PostgreSQL cases cover lifecycle and exact replay; observed
grant revocation and exact profile-lock timeout; empty candidate denial; concurrent
exact admission; constraints, foreign keys and immutable history; token rotation;
profile disable/revision serialization; concurrent exact reserve/observe; changed
replay denial; partial/unknown usage with truthful overshoot; both stop/candidate
orders and discarded candidate ACK; fresh final authority; settlement after work
expiry/revoke with wrong capability/context/purpose/extended cutoff/conflicting
batch denial and exact replay; observed profile-lock release before bound followed
by elapsed decision time and fresh-clock denial; conflicting concurrent
admit/reserve/observe winners; and explicit rollback with no committed readback.
The exact lock-holder/contender/key barriers remain required. The start barrier in
concurrent replay cases does not itself prove overlap. Future waits, database-clock
polls, lock/statement timeouts and pool acquisition are bounded. The discarded-ACK
and rollback cases simulate specific transaction outcomes, not an actual unknown
network COMMIT. Native transport uncertainty remains unproved.

Each fixture cleanup checks preservation and checked-out connections even after
setup failure. Runner finally independently attempts final projection checks,
zero-checkout verification, pool disposal and an exclusive flushed/fsynced
journal-proof.json containing only synthetic projection digests, fixed failure
categories and test identifiers. It does not persist SQL tracebacks, URL/password,
synthetic bearer values or capabilities. Receipt write failure returns74 rather
than success. Alembic's separate engine now has finally disposal on connect or
migration failure; a secondary disposal exception cannot mask the original
failure. A disposal attempt is not independent proof that an unavailable database
stopped. CI job/service termination and local retained-container stop evidence are
different observations and remain Main's separately released responsibility.

Actual evidence for this source packet: 31 inert tests first passed; after adding
failure cleanup regressions, 33 tests ran with one error because the sandbox denied
the test's temporary receipt write and directory cleanup. That test was corrected
to inject receipt I/O and fsync, and all **33 inert tests passed**. Existing seventeen
journal/authority checks remain included. These tests inject target readers,
migration application, URL parsing, engine/context operations and receipt writes;
they do not connect, migrate or execute PostgreSQL fixture cases. AST validation
and exact hashes are recorded in the private delivery report. No actual SQL,
container, service, enrollment, store/provider or native operation ran. Real
cutoff/provenance/capability/ACK producers remain unavailable by default, prepared
values remain non-ACKs, external capture remains unknown, and runtime readiness,
global promotion, authority/native/live-provider and whole Phase1 remain open.

## Schema packet v2: first-failure stop and commit boundary correction

Independent B source review required F1/F2 corrections before any SQL release.
The runner now enables unittest failfast, including errors from setup and cleanup;
an unexpected skip also stops further cases. Expected exceptions caught inside a
test remain expected outcomes. Receipt records planned, started, passed and
unexecuted test IDs plus aborted and actual partial count. It never labels later
unexecuted cases as passed or skipped. Test cleanup and independent final
projection/pool/disposal/receipt attempts still run after the first failure.
A new inert end-to-end runner check injects a first barrier assertion failure and
a second mutation case: only the first starts, its cleanup runs, the second is
unexecuted, and final preservation/pool disposal/failed receipt are asserted.

Deferred case12's v2 operation-prelock approach was rejected by independent B: it
reversed authority/profile-before-operation hierarchy on the contender transaction.
The v3 correction removes that prelock and its unused helper option. Both holder
and contender invoke normal public candidate/stop entrypoints. The holder retains
its candidate or stop transaction while a second connection requests the opposite
operation. Before committing the holder, the fixture observes the exact contender
PID blocked by that exact holder on the SHA-derived PROFILE advisory key, matching
the production serialization path. Stop-first yields diagnostic_conflict for
candidate; candidate-first yields original_prepared for stop. Both histories retain
the expected candidate presence and execution_permission=false. All current
token/grant/profile/binding checks and trusted entry cutoffs precede operation
acquisition normally; there is no raw internal operation call or forced reverse
lock order. Finite futures, exact wait observation and cleanup remain in place.

New deferred case18 prepares candidate inside an open transaction, marks a modeled
parent local-stop event, observes database time past the fixed work expiry while
the transaction remains active, then commits. It retains/discards the prepared
value without real publication. Default committed publication is explicitly denied;
expired exact candidate replay and final-authority checks are denied. A separate
synthetic capability settles stopped history within the original bounded grace;
readback retains candidate_digest and execution_permission=false. This is a
controlled late durable commit and delayed/unconsumed ACK model. It does not prove
an unknown network COMMIT outcome, actual parent stop, IPC capture or native return.
The rollback case17 remains separate. The runner now requires all eighteen planned
cases to execute successfully without skips or unexecuted IDs.

Focused v2 verification: **34 inert tests passed**, including the new first-failure
mutation prevention/cleanup/receipt check; original33 remain included. All eighteen
PostgreSQL cases remain SOURCE ONLY and unexecuted. No migration bytes, API/worker
guards, Main workflow/config, default-unavailable producers or runtime permissions
changed. Independent B delta review and Main's separate actual SQL release remain
required. Original v1 evidence and its sandbox-temp failure chronology are retained.

V3 changes only the deferred fixture/profile-wait explanation; F1 and late-commit
case18 remain unchanged and B accepted those source portions. Focused static AST
checks confirm both normal entrypoints, no internal operation call, exact
profile-key/holder/contender barrier and specific outcomes in both orders. The
unchanged inert suite was not rerun; its latest actual result remains34PASS for v2.
All eighteen actual SQL cases remain unexecuted pending B delta and Main release.
