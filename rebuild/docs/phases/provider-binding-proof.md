# OF-012P — local operation-bound enrollment and diagnostic authority

24 October2026. Implemented and tested; frozen for independent backend review.
Consumes the independently accepted corrected Secrets helper. No actual credential
enrollment or whole-phase acceptance is implied.

Migration0006_profile_bindings adds provider_enrollments and four nullable internal
binding columns to profile versions. It preserves the thirteen prior application
tables and immutable migrations0001–0005. Complete operation/principal/case/profile/
fresh-ref/expected-revision foreign keys and triggers prevent ref transplantation,
tuple changes and historical rewriting. A deferred constraint requires the exact
attached operation before any bound version commits. Attachment atomically appends
a disabled revision and settles pending to attached; activation remains a separate
current-writer metadata update. Attached/unresolved enrollment records are retained.

The trusted local callable requires explicit authentication and injected input and
store. It provides no CLI, default prompt/store or authentication discovery. A
separately owned helper generates the fresh reference. Backend callbacks commit
reservation before input, freshly authorize after input immediately before put and
recheck after put before attachment. Authentication, writer grant, current profile
revision and the whole binding tuple govern each boundary. No transaction spans
input/store I/O. Ref possession and a historical receipt do not confer authority.

Settled same-request replay returns the original nonsecret receipt after current
authentication/writer/profile checks and never prompts, writes, appends or enables.
Pending/unresolved replay requires explicit recovery. Post-put conflict/revocation/
failure leaves unresolved, or last-durable pending if DB failure prevents settlement.
No automatic uncertain retry, credential read/delete or orphan cleanup exists.

EXECUTE_DIAGNOSTIC loading requires the explicit current local bearer token,
writer grant, enabled current revision and complete attached tuple. BoundProfile
pins the exact adapter Profile, case, full metadata digest, binding, caps and a
validated narrowed budget. Every provider callback freshly reloads/authenticates;
changed token/grant/case/revision/model/ref/caps/disabled state or outage denies.
Configure remains metadata-only. The provider's accepted callback boundaries run
before retrieval, after retrieval before dispatch and before answer publication.

Public metadata/diagnostics omit refs and input values. Binding state is separate
from actual store presence/key validity; every provider/store capability and actual
enrollment remain unverified. No HTTP key/ref attachment route or live probe exists.
Arbitrary valid user metadata strings are not a secret-scanning guarantee.

This task's local invocation is injected fake input/store only; provider integration
uses mock transport and synthetic values. No actual hidden prompt, OS credential
operation, provider request, global readiness, run scheduler integration, paid cost
accounting or hard interruption is claimed. Actual enrollment/live proof needs its
separate authorization and observed evidence.

## Observed validation

The sole combined actual-PostgreSQL run passed **31 tests in14.578s**: twelve new
binding tests, ten affected metadata tests, eight core tests and the accepted
deterministic-provider regression. The helper owner's original sixteen offline
tests and two focused alias regressions are separate evidence; they were not
duplicated here. Independent review first corrected the helper's original-ref
aliasing gap; the combined proof waited for Main's exact accepted hash release.

New tests prove disabled atomic attachment and separate activation; canonical
enrollment/activation replay without reactivation; current auth/writer/case/revision
before reservation/replay; zero put and supplied-value clearing when grant, revision
or token changes during input; post-put grant/revision/put failures never attach;
DB outage retains pending and blocks uncertain replay; immutable complete tuples
and cross-profile ref denial; one concurrent operation prompts/writes once; exact
adapter/caps/case/token authority; cap-only/model changes, disabled state and outage
denial; rollback of attachment/profile together and deferred attached-state checks.
Input/put fixtures assert zero checked-out DB connections across their I/O.

The actual bound callback was exercised at three provider boundaries (before get,
during fake get before dispatch, and after mock response before publication), each
against grant revocation, disable, model revision and fresh-ref enrollment changes.
Unauthorized dispatch counts remain zero; a response already dispatched retains
reported partial usage and no published answer. Retrieved synthetic values clear.
This is mock action-boundary evidence, not cancellation of an in-flight paid call.

Original columns and row fingerprints across all thirteen pre-existing tables
remain preserved after migration and tests. Nullable binding columns were added to
profile history without altering its original data. Migrations0001–0005 are byte
unchanged. Complete Run family counts/content remain unchanged. Failure fixtures
retain one pending and ten unresolved synthetic intents; no automatic recovery is
performed. Eight synthetic current profiles remain enabled as test metadata, not
usable enrolled OS credentials or provider readiness. The exact owned database is
stopped/preserved with exit0; no API or worker listener was started.

Actual pinned OpenAPI/client generation and strict TypeScript compilation passed.
Dependencies, root lock and environment were unchanged. Exact source/dependency
hashes, test/migration receipts and retained-row evidence are in the private
coordination handoff, excluded from public source. Independent backend review and
Main's delivery/CI remain required.
