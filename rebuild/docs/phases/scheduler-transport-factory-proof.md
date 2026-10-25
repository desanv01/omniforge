# Explicit asynchronous transport factory

This prerequisite adds an inert-import construction/lifecycle seam around the
accepted RawSdkClient. It does not establish native scheduler readiness, live
authentication, workflow registration, engine behavior or process cleanup.

`open_transport(config, token, constructors=...)` is an explicit asynchronous
context manager. It accepts validated destinations and supplied authentication;
it never discovers environment configuration, tokens, proxies or credentials.
Injected constructors return resources with explicit owned/borrowed semantics.
Only owned resources are closed; an unsafe borrowed session is rejected without
mutation. Default constructors are lazy and were not executed by the proof.

TLS mode requires an explicit CA bundle and HTTPS REST origin. gRPC TLS verifies
against the supplied roots; REST uses a fresh TLS client context with supplied
roots. Plaintext development mode is restricted to literal loopback addresses
and HTTP; it supplies no production transport security. Scheme/resolver paths,
userinfo, query/fragment/path suffixes and control characters are rejected.

The accepted pinned SDK uses WorkflowServiceStub.TriggerWorkflow at
`/WorkflowService/TriggerWorkflow`. Its gRPC authorization metadata is
`authorization: bearer <supplied token>`; REST uses
`Authorization: Bearer <supplied token>`. The factory supplies this authentication
to the existing raw boundary and adds no SDK retry wrapper. Import is inert.

Lazy defaults require the accepted exact dependency pins: hatchet-sdk1.41.1,
grpcio1.84.1 and aiohttp3.14.5. gRPC disables retries and ambient HTTP proxy routing;
aiohttp disables connection retry before RawSdkClient injection, uses trust_env=False,
no middleware, no automatic decompression, an empty cookie jar and no proxy.
The existing raw boundary retains its operation-wide deadlines, redirect rejection,
response-body cap and conservative unknown results. This factory copies no transport
operations and introduces no automatic probe, registration or submission.

Owned close runs once across explicit close/context exit, including partial
construction, exceptions and cancellation. Cleanup has a configured bounded wait;
failure/timeout raises sanitized CleanupError codes. A noncooperative close task
remains explicitly retained in unresolved_cleanup until physically settled; it is
never represented as successfully closed or forcibly killed. Caller cancellation
does not detach the owned cleanup task. Lost construction/cleanup is not readiness.
Injected constructors are trusted: they must return created resources promptly and
honor the supplied retry options. A callback that creates a hidden resource and
raises before returning ownership cannot be recovered by this seam.

Validation used only injected fake channels, stubs and sessions. Thirteen initial
tests passed, followed by three added lifecycle tests; no final16-test aggregate
run is asserted. Checks cover explicit options/auth and actual RawSdkClient
assembly, configuration rejection, owned/borrowed cleanup, partial construction,
exception/cancellation, retry-policy rejection, bounded failures, repeated
cancellation, noncooperative cleanup tracking and inert import with real transport
imports/constructors guarded. A Windows sandbox local asyncio-IPC initialization
failure occurred before test setup; the bounded permitted run with local IPC then
passed. No network transport, native service, credential store or database was
accessed, and no dependency was installed for these checks.

Independent review and intended-head CI remain required. Actual default TLS/gRPC/
aiohttp construction, connection/authentication and native lifecycle proof belong
to a later explicitly owned runtime window.
