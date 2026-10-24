# OF-012P — persisted nonsecret profile metadata

24 October2026. Implemented and tested; awaiting independent review. Metadata API
and configuration authority only. No credential enrollment or paid execution.

`migrations/versions/0005_provider_profiles.py` adds the case-scoped append-only
provider_profile_versions table after0004. All twelve prior tables preserved their
original columns and every existing row across migration. SQL triggers enforce
permanent profile/case identity, sequential revisions and immutable history.
Database constraints keep every profile disabled; there is no credential-ref
column, enrollment table, bridge or public attachment shortcut in this slice.

`services/api/profiles` implements strict DTOs, serialized repository, routes,
passive diagnostics and a closed-purpose metadata authority seam. Case readers
inspect metadata; current writers mutate. Authentication/grants precede idempotent
replay. Replay returns historical metadata without restoring it. Concurrent same
key creation produces one profile; competing expected revisions produce one append
and one409. The endpoint is fixed and model explicitly supplied. Budget dimensions
and bounds reuse the existing adapter DTO; conservative defaults are2 calls,
32768 input tokens,1024 output tokens,32 tool bytes and30 seconds. No cost or
tokenizer accounting is implied. Arbitrary metadata strings are not secret-scanned.

Configure authority pins and rechecks the full current metadata view and writer
grant. The callback rejects adapter Profile execution objects. Unknown purpose,
reader-only grant, stale/current changes, disabled/unconfigured execution and DB
outage fail closed. Caller budgets can only narrow the configured caps. Enroll and
execute_diagnostic remain denied because no complete attached binding exists.
Positive attached-authority proof is deliberately deferred with the enrollment
bridge; a synthetic reference cannot activate a profile through these routes.

The actual PostgreSQL run passed **19 tests in8.656s**: ten new tests in
`tests.integration.core.profiles`, eight directly affected core tests and the
accepted deterministic-provider regression. The new family covers two principals/
two cases, reader/writer and cross-case access, defaults, append/disable/history,
replay/stale/changed-body conflicts, grant revocation before replay, concurrent
requests, strict cap bounds/types and safe rejected-input errors, direct SQL history
guards, current-only pagination, fresh application reload, complete metadata
comparison, cap narrowing and deny-on-outage behavior.

Passive diagnostics and attempted activation ran under store-constructor,
provider-entrypoint and socket tripwires: zero calls. Diagnostics retain unverified
store presence/credential validity/provider capabilities and unsupported enrollment.
The separate existing provider regression uses an in-memory synthetic store/mock
transport; it is not a profile-backed or live-provider proof. No OS credential
constructor/get/put/delete, hidden input, actual key or upstream request occurred.

Actual OpenAPI/client regeneration succeeded with existing pinned openapi-ts0.99.0;
TypeScript6.0.3 strict compilation passed. No dependencies, locks or environments
changed. No scheduler source, B3 feature, API/worker listener or old intent dispatch
was involved. Retained pre-proof rows/history were checked again after the tests;
the owned isolated database was then stopped and retained. Private receipts and
exact file hashes remain in the coordination handoff, outside public source.
