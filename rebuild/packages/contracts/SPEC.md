# Contracts v1 — Phase 1 implementation target

Status: OF-010 accepted; OF-011 core implemented and awaiting independent review.
Health, capabilities, case create/list/read and artifact upload/list/association/
range routes are executable against explicitly configured isolated PostgreSQL.
The generated OpenAPI and TypeScript client cover these implemented routes only.
Provider, run and portable-export sections remain implementation targets.

## Common conventions

JSON DTOs use `schema_version: 1`, UUID strings for stable object IDs, positive
integer `revision`, and RFC3339 timezone-aware timestamps. Unknown historical
timestamps stay null with timezone provenance; import time never becomes capture
time. Immutable versions are addressed by ID + revision + content hash where
applicable. Additive optional fields may evolve v1; changed meanings require v2.

All authenticated resources require principal and case-grant checks before lookup
or content access. Case association/ownership is not authority. OF-011 uses a
high-entropy local bearer token whose SHA256 maps to a persisted principal, and
explicit case grants; arbitrary principal headers are ignored. A restricted private
file holds the prototype token. This is separate from provider secret resolution.
Never trust a caller-supplied principal header. Mutations require Idempotency-Key,
scoped to principal + operation + target. Persist request canonical-body digest
and response in the same DB transaction as the mutation. Same key/body returns the
canonical result; changed body returns 409. Artifact publication may advance a
durably accepted 202/pending response to 201/committed, including after recovery;
GET the association for current state. Its ID never changes. Do not expire keys while a related run
or publication is unresolved. Updates/cancels require expected_revision; stale
revision returns 409. Cancellation replay with the original idempotency key returns
its stored response. Numeric limits are server validated.

Errors: `{schema_version, code, category, message, retryable, request_id,
evidence_refs, details}`. Categories: validation (422), conflict (409), not_found
(404), forbidden (403), provider_auth (upstream failure 502), provider_rate_limit
(503), provider_timeout (504), unsupported (501), storage (503), internal (500).
Unauthenticated requests return 401. Details contain only allowlisted safe values;
no credentials, prompts, local paths, upstream bodies or raw validation inputs.
OF-011 preserves safe Allow/WWW-Authenticate/Retry-After headers, documents the
shared envelope/statuses, and sanitizes unexpected exceptions. Method rejection
uses method_not_allowed; 401 uses unauthenticated. Upload overflow uses 413 and
wrong multipart media type uses 415. Retryability describes policy, not an automatic retry.
Domain outcomes are never hidden in empty success responses.

## Routes and ownership

| Owner | Route | Result |
|---|---|---|
| OF-010 | GET /api/v1/system/health | 200 liveness, ready=false; dependencies not_connected, migration_version=null |
| OF-011 | GET /api/v1/capabilities | available/unsupported/unverified per feature, reason and proof timestamp |
| OF-011 | POST /api/v1/cases | 201 Case from title/objective/policy_profile_ref |
| OF-011 | GET /api/v1/cases, /cases/{id} | paged Case list / Case detail |
| OF-011 | POST /api/v1/cases/{id}/artifacts | 201 committed ArtifactAssociation; 202 pending publication |
| OF-011 | GET /api/v1/cases/{id}/artifacts | bounded grant-checked association page for reload |
| OF-011 | GET /api/v1/artifacts/{association_id} | metadata for precisely one authorized origin association |
| OF-011 | GET /api/v1/artifacts/{association_id}/ranges | exact bytes with hash/bounds; no normalization |
| OF-013 | POST /api/v1/cases/{id}/runs | 202 persisted queued Run before dispatch |
| OF-013 | GET /api/v1/runs/{id} | authoritative Run state |
| OF-013 | POST /api/v1/runs/{id}/cancel | idempotent cancel request/result |
| OF-013 | GET /api/v1/runs/{id}/events?after=N | persisted replay/SSE with increasing sequence |
| OF-014 | import/export schemas | portable bundle, no live routes required yet |

Health in OF-011 reports checked migration version, dependency states and reason;
liveness remains independent. A dependency can be ready only after its owning
probe passes. Capability readiness is granular: text, schema, stream, tool calls
and hosted search are separate checks. An installed SDK proves none of these.

Case: `{id, schema_version, revision, title, objective, status,
policy_profile_ref, created_at, updated_at}`. Pagination uses opaque stable cursors,
bounded page size and deterministic ordering. ScopeGrant separately records
principal, permitted operation, target/source boundaries, expiry and policy version.

## Evidence

Artifact identifies immutable bytes by sha256, bytes and media_type. Associations
carry `{id, case_id, artifact_id, source_id, sha256, bytes, media_type,
original_name, captured_at, imported_at, publication_status, warnings, revision,
schema_version}`. captured_at is nullable; original_name is metadata only, never a
filesystem destination. Same bytes reuse the blob while retaining different
source and case associations. Hash does not authenticate source or observation.
Sensitivity and source provenance remain on association/source records.

Upload is streamed multipart with a 25 MiB file limit,
enforced while reading even without Content-Length. Stage outside source, hash
and validate, publish content-addressed immutable bytes, commit association, expose
pending/committed/failed and reconciliation record across crash windows. DB and
filesystem are not one transaction. OF-011 keeps staged originals, partial invalid
uploads and uncommitted publication files for review/recovery. Reconciliation is an
explicit CLI limited to 20 records by default (maximum100), using row locks and
content locks. It publishes verified pending records and never deletes bytes.
Quota, garbage collection grace periods and reference checks remain future gates;
no cleanup or unattended production ingestion is accepted by this slice.

Artifact route IDs always address the association `id`. Global `artifact_id` is
byte identity only and has no API lookup route. Metadata never enumerates other
case/source associations, even when the caller already knows a global byte ID.
Unauthorized association metadata/ranges return404; case grant rejection returns403.
Case/artifact lists order UUIDs, use bounded base64 UUID cursors and require fresh
case reads for the current revision after mutation. Captured time stays null unless
an explicit timezone-aware timestamp is supplied.

Ranges use zero-based half-open byte bounds `[start_byte,end_byte)` with
`0 <= start < end <= bytes`, maximum 1 MiB; invalid bounds return 422,
missing committed blob returns storage error. Return exact octets with hash and
explicit start/end/total metadata headers; never empty-success on storage failure.
Text previews must expose decoding errors and link original bytes.

EvidenceLocation: `{id, artifact_id, association_id, sha256, kind, selector,
schema_version}`. Byte selectors use half-open offsets; line selectors use one-based
inclusive lines with encoding/newline interpretation; page/event/packet/address
selectors include parser/version or index manifest. OF-014 must verify selectors
resolve to immutable bytes or immutable derivation indexes. A citation is a
location ID plus expected hash, never display text alone.

Derivation: input artifacts/locations, tool and parser versions/digests, options,
output hashes, warnings and coverage (complete/partial/unknown). Empty complete
collection differs from empty interrupted collection. Observation records actual
source/tool output and coverage. Claim records interpretation with supporting and
contradicting location refs, verification state and uncertainty. Missing evidence
cannot become a clean negative. Findings, RuleVersion, DatasetVersion and
Evaluation retain immutable revisions; verdict, lifecycle and freshness remain
separate. Nullable metric denominators and unknown counts survive export.

## Run/event and recovery

Run: `{id, case_id, kind, schema_version, revision, status, outcome,
terminal_reason, attempt_id, input_refs, policy_version, budget, usage,
provider_profile_ref, output_refs, created_at, started_at, finished_at}`. Inputs
include immutable versions, hashes, source collection coverage and scope snapshot.
Lifecycle: queued -> claimed -> running -> waiting/running or terminal;
queued/claimed/running/waiting may enter cancel_requested -> canceled;
terminal states are succeeded/failed/canceled/interrupted/uncertain. Domain outcome
(including insufficient_data) is separate from successful execution.

Persist Run + ordered event before scheduler dispatch via transactional outbox.
Persist attempt and monotonic lease/fencing token before work; every publication
checks token and expected revision. Stale workers cannot publish. Recovered safe
reads/idempotent/reconciled operations may create a new attempt; unknown external
side effects become uncertain until reconciled. Success requires committed output
refs and terminal event in domain transaction. Cancellation preserves partial
outputs and known usage, rejects further tools, and never implies rollback.

RunEvent: `{run_id, sequence, type, attempt_id, occurred_at, payload,
schema_version}`. Sequence is increasing per run; store before delivery. SSE id is
sequence; resume from Last-Event-ID or after (reject conflicting cursors). Replay
duplicates are deduplicated by run_id/sequence; gaps trigger replay. Expired cursor
returns conflict with safe recovery hint. GET Run reconciles terminal state;
stream closure is never success. Events exclude raw secrets/provider bodies.

## Provider adapter and secrets

`answer(ReadOnlyContext, ProviderProfileRef, Budget) -> ProviderResult` is an
application interface, pending implementation OF-012. Context includes case,
immutable input/locations, scope, policy and cancellation token. Result contains
typed observations, claims, citations, usage and explicit outcome/reason. The only
initial tool is grant-checked read_evidence_range with exact bounds/hash. The
adapter cannot invoke host commands or infer scope from evidence text.

ProviderProfile: id/revision, endpoint, model, nonsecret settings, credential_ref,
capability checks with independent status/proof time. Profile pins do not silently
fail over. Endpoint must pass network policy before credentials are sent. Preserve
proxy/context/output/thinking/stream/header/priority/exclusion/retry metadata in
nonsecret legacy envelopes if unsupported; secret headers never enter envelopes.
Budgets bound calls, input/output tokens, wall time and tool bytes; reserve/check
before each action and record cumulative known usage across attempts. Usage values
are nullable and individually marked known/estimated/unknown with provenance;
unknown cost is not zero. Auth/rate-limit/timeout/schema/tool/stream failures remain
distinct. No automatic retry of uncertain external actions.

Credential values are resolved only at adapter execution through a reviewed
secret-store interface. OS credential storage, headless key supply, recovery and
redaction are unimplemented. No plaintext fallback, inline API keys in profile
DTOs, exports or logs. Live DeepSeek proof is separately authorized/budgeted after
credentials are configured; deterministic fixture results never stand in for it.

## Portable provenance and reuse

Every imported entity preserves source_system/entity/id/commit/schema_version,
source_revision, original timestamp/timezone provenance, migration_version and new
ID. Unique migration key makes replay idempotent; absent metadata stays unknown.
LegacyEnvelope preserves original state vocabulary and unsupported reason without
upgrading assertions. Phase12 reconciles all observed legacy tables plus files,
archives and transcripts; optional/retire never authorizes deletion.

OF-014 bundle: versioned JSON manifest plus Markdown report, immutable originals,
derivations, locations, observations/claims and legacy envelopes. Only relative
content-addressed paths; reject absolute paths, traversal, symlinks and hash/size
mismatch; validate before publication. No credentials or private host paths.
Reuse register for actual copied code/rules/prompts/assets/fixtures records URL,
release/commit/path, digest, author/license, modifications, purpose, dependencies,
privileges, fixtures, removal/upgrade route and verification date. Original
behavior implementation does not settle legacy license compatibility.

### OF-014 implemented prototype and timestamp correction

Forward migration0002_capture adds captured_at_original, captured_at_offset and
captured_at_provenance (supplied/unknown) to association DTO/storage. Existing rows
keep their original captured_at instant and receive unknown provenance with null
original/offset. New uploads accept an explicit RFC3339 string with offset and up
to six fractional digits, retain its exact text/offset token and normalize the
instant to UTC. No offset is fabricated from database/session timezone. Absent
capture time stays null/unknown; RFC3339 -00:00 is preserved literally and denotes
unknown local offset, not proof of a known source timezone.

Portable models and generated JSON Schemas are under packages/contracts/evidence
and export. Directory-bundle manifest v1 retains case/artifact/association/source
IDs, capture provenance, timezone-aware imported_at, derivations, original legacy
state envelopes, observations/claims and exact byte or UTF8 line citations.
Import here means validation/loading or idempotent directory round trip only;
no bulk/legacy/live database importer or export HTTP route is implemented.

Python runtime validators enforce cross-entity identities and source attribution,
capture consistency, coverage semantics, canonical paths, regular-file/directory
types, no symlinks/reparse points, SHA256/size, exact selectors and deterministic
Markdown. JSON Schema expresses structure and does not replace these checks.
Byte selectors are zero-based half-open; lines are one-based inclusive LF-delimited
UTF8, retaining CRLF and final-newline bytes. Parser failure is not an empty clean
result; complete and incomplete empty collections are distinct declarations.

Bundles contain explicitly selected original evidence and remain private/sensitive
unless separately reviewed for sharing. Metadata rejection catches obvious path/
credential shapes, not arbitrary opaque secrets. Original blob contents are not
scrubbed. Passing validation is integrity/structure evidence, not source
authenticity, permission or publication safety. See docs/phases/evidence-proof.md.

### OF-013-B1 implemented journal boundary

B1 admits only kind `synthetic-read-only-v1` and policy `local-read-only-v1`.
Admission uses POST /api/v1/cases/{case_id}/runs with Idempotency-Key and a bounded
list of immutable association refs (association_id, revision, lowercase SHA256).
Refs must belong to the authorized case and match committed association metadata;
the server enriches artifact/source/byte identity and coverage unknown. This is
metadata admission, not proof that all source bytes have just been read. Actual
tool admission uses the existing bound byte-integrity/grant seam.

Budget permits zero model calls/input/output/tool bytes and a bounded synthetic
wall-time declaration. No provider profile or arbitrary work kind is accepted.
The transaction persists queued Run revision1, event1, pending start intent and
canonical idempotency response together before returning202. Current case grants
are checked before replay, and altered body with same principal/target/key409.
A scope snapshot is a ceiling/declaration and never substitutes for current grants.
No scheduler import, request or dispatcher is invoked. Without scheduler
integration the run remains durably queued and scheduler health stays unverified.

GET /api/v1/runs/{run_id} returns grant-filtered persisted state; ungranted and
unknown run IDs both404, missing authentication401. POST /runs/{run_id}/cancel
requires Idempotency-Key and body expected_revision. Queued cancellation persists
cancel_requested and canceled events/revisions atomically and suppresses pending
start intents; no attempt exists in B1. Same-key cancellation replays the original
response after current grant check even if expected_revision is now stale; a new
key with stale revision409. A terminal run is not rewritten by a late cancel.

GET /runs/{run_id}/events returns bounded JSON replay only, after defaults0,
maximum100 events/page and monotonic per-run sequence IDs. Last-Event-ID may supply
the same cursor; conflicting explicit cursors409, malformed/negative422, future
cursor409. Run-row serialization allocates event sequence in the mutation's
transaction; no unlocked MAX(sequence)+1. There is no event retention or expired
cursor claim. SSE Accept is explicitly unsupported501 with shared safe error
envelope; it cannot silently become a stream success. Refresh Run for current
state and revision. Generated OpenAPI/client describe the executable routes.

Migration0003_runs creates only runs/run_events/run_outbox and preserves prior
tables. Statuses are limited to queued/cancel_requested/canceled, outbox command
start and states pending/suppressed. Attempt/output/scheduler execution tables,
leases/dispatch/claim, success publication and SSE remain later B2/B3 work.
B1's cancellation race fixture concerns synthetic pending-intent row locking/
suppression only; it is not an actual dispatcher/leased claim/attempt-admission
race. Durable intent is not scheduler submission or completed execution.

### OF-013-B2 synthetic execution boundary

Migration0004_run_execution extends B1 with run_attempts, run_outputs and
run_scheduler_executions, bounded outbox reservation/reconciliation fields and
additional execution lifecycle states. Existing B1 intents/history are retained;
no migration, import or API startup dispatches them. The fake-only driver requires
an explicit bounded Run UUID allowlist and never scans/drains arbitrary pending
intents. There is no public execution/claim endpoint or automatic worker process.

Outbox reservations persist before SchedulerPort.submit/lookup calls, which occur
outside the SQL transaction. Stable dispatch key and input hash bind each command.
Lost acknowledgement requires reconciliation; found executions may map multiple
external IDs to one dispatch. Confirmed absence permits bounded harmless
redelivery; unknown remains unresolved. Each intent has at most two submit
reservations and two lookup reservations. Only fake-v1 observations are supported;
there is no native scheduler idempotency/lookup or network recovery proof.
Acknowledgement/completed scheduler observation never makes a domain Run succeed.

Trusted execution functions accept caller transactions and expected revisions.
Claiming an explicitly mapped synthetic run persists attempt, monotonic fence,
database-time lease and event before work. Duplicate deliveries cannot create
competing live attempts. Work admission/heartbeat/publication check current case
write grant, scope/input snapshot, active attempt/fence/revision and live DB-time
lease plus synthetic wall budget. A heartbeat returns the new command token/version;
workers cannot silently guess revisions.
The live lease is rechecked using DB time after potentially blocking authority/input
locks, so a lock wait cannot renew or admit work after expiry.
Expired harmless attempts can be marked
interrupted and replaced under a higher fence, with at most two attempts. Unknown
effects instead remain uncertain; no provider/tool execution occurs in B2.

The only output is bounded synthetic JSON `{value: string}`. Publication stores
immutable output key/hash/content/attempt/fence and original command revision,
then output_refs, succeeded outcome and terminal event in the same transaction.
Same exact postcommit command replays canonical committed output; changed content,
fence/attempt or command revision conflicts. Same-run composite foreign keys bind
attempt/output/mapping identity. Run output refs are typed `{id,kind:run_output,
sha256}`. Existing no-dispatch usage provenance remains readable; newly claimed
synthetic work declares zero external provider/tool usage accurately.

GET Run/JSON event replay deserialize the richer states/attempt/output references;
no new HTTP execution operation is introduced. Active cancellation/settlement,
cleanup acknowledgement, SSE and actual integrated scheduler recovery remain B3.
Queued cancellation retains B1 behavior, while in-flight work cannot be falsely
reported as safely canceled by that queued-only operation. No live provider,
credential, profile/setup or additional dependency is enabled by this boundary.

### OF-012P case-scoped provider metadata

Migration0005_provider_profiles adds one append-only versions table. A profile ID
permanently belongs to one case; SQL triggers prohibit historical UPDATE/DELETE,
case rebinding, skipped revisions and activation. Existing tables and migrations
0001–0004 remain unchanged. No startup dispatch or enrollment occurs.

Authenticated `/api/v1/cases/{case_id}/provider-profiles` supports POST create,
GET bounded current-only list, GET `/{profile_id}`, PATCH `/{profile_id}` and
GET `/{profile_id}/diagnostics`. Case readers inspect metadata; current case
writers alone mutate. A profile outside the requested case returns404 after the
case grant check. IDs are server generated. No public owner, credential reference,
key, attach/reserve or enrollment field/endpoint exists. Strict mutation DTOs and
shared safe validation errors exclude rejected input values from responses.
Explicit metadata strings are user content, not a secret-detection guarantee.

Create requires a label and explicit model string, with no guessed model/default
support claim. Endpoint defaults to and only accepts exactly
`https://api.deepseek.com/chat/completions`; no custom host/header/proxy options.
Caps reuse the strict adapter Budget bounds: calls1–16, input_tokens1–1000000,
output_tokens1–100000, wall_seconds1–300 and tool_bytes0–1048576. Defaults are
calls2/input32768/output1024/wall30/tool_bytes32. These are request limits, not
tokenizer, price, cost-accounting or billing authorization.

Every new profile is disabled/unconfigured. PATCH requires expected_revision and
at least one nonnull allowed metadata change; absent fields carry forward.
Supplied caps replace the complete five-field cap object. Setting enabled=false
appends a disabled revision; enabled=true conflicts409 because no attached binding
exists. History remains private SQL metadata; public reads show current revision.
Metadata views expose credential_configured=false/binding_status=unconfigured,
never opaque credential targets.

Create/update require Idempotency-Key. Current principal/grant rows are checked
and share-locked through replay/mutation. Profile advisory locking serializes
current selection, revision comparison and append. Same-key/same-body replay
returns the original historical nonsecret response without appending, enabling
or restoring it; changed body409. A fresh-key stale revision409. Current execution
authority can never derive from a replayed historical response.

The internal closed Purpose enum recognizes configure/enroll/execute_diagnostic.
Only configure currently loads a nonsecret ProviderProfileView after current
writer/case/revision checks. Unknown purposes and unconfigured enrollment or
execution deny. The bound metadata callback freshly reloads and compares the
entire pinned view, including case/revision/endpoint/model/caps/binding status;
revocation/revision change/DB failure denies. Adapter Profile objects are explicitly
rejected because they carry no persisted case/caps/attached-binding proof.
`narrow_budget` accepts validated caller budgets only within every configured cap.
This is preparation for a later execution seam, not persisted provider execution.

Passive diagnostics report only persisted revision/disabled/unconfigured state,
deferred enrollment and unverified store/credential/tool/schema/stream/search
capabilities. They construct no OS store, prompt for no key and invoke no transport
or network probe. No credential reference/enrollment table or internal fake attach
path exists. The complete immutable operation/principal/case/profile/ref/expected-
revision binding and positive attached-authority proof are deferred together to a
separately reviewed enrollment bridge; reference possession is never authority.
