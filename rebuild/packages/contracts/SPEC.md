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
