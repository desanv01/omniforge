# OF-012I — deterministic provider through actual core authority

24 October2026. Implemented proof awaiting independent review. The existing
accepted provider and core authority source are unchanged; this adds only the
focused integration test and this public-safe evidence document.

The test creates two synthetic cases through the authenticated API in TestClient,
persists identical artifact bytes as distinct origin associations in the isolated
PostgreSQL core, and binds read_range to an authenticated principal and one case.
The accepted provider answer loop uses ScriptedMock and an in-memory synthetic
SecretValue store. No HTTPS transport or Windows credential-store object is
constructed. The only live service used is the explicitly configured new core DB;
no legacy database, real model key or provider network is involved.

The positive path checks the actual returned bytes and the base64 tool payload
against a binary fixture containing CRLF, multibyte UTF8 and invalid UTF8 bytes.
The final answer cites the location that was actually read with its expected
SHA256. Two mock calls report70input/45output tokens and12tool bytes; monetary cost
remains null/unknown. These token counts come from the scripted provider response,
not a real model or independent tokenizer.

Negative cases reach the actual bound core callback, using otherwise matching
mock locations/tool arguments: known foreign association over the same blob404,
expected hash mismatch409, out-of-bounds range422, full-blob corruption503, then
revoked current case grant404 through the same previously bound reader. Each
provider boundary returns sanitized tool_failure with no answer, preserves the
first-round30/20usage and makes no second mock/store call. The corruption is outside
the selected range, establishing that the callback checks the full blob before
returning bytes. Only a newly authored synthetic blob is faulted; its exact bytes
are restored in finally and the restored hash/range asserted. Staging originals
are retained. The revoked grant belongs only to this new synthetic fixture.

Run from the source root using the existing locked Python environment and an
explicit private configuration for the retained isolated core:

```powershell
$env:OMNIFORGE_CONFIG = '<private-runtime-config-file>'
python -B -m tests.integration.core.provider_integration
```

The command is intended for the assigned sole core runtime owner. Do not bootstrap
another database or start a second API. The test asserts current_database is
omniforge_rebuild and migration0002_capture, then reads only the local prototype
API token from the configuration file's private directory. Token values are never
logged, placed in URLs or committed. Data/credentials/test receipts stay outside
source. No dependency install, migration or unrelated test suite is required.

Actual execution: the prepared test ran once and passed, 1test/0failures/0errors;
unittest reported0.706s, full import/runner elapsed3.453s. No diagnostic/correction
or retest was needed. The retained DB was verified before start and gracefully
stopped with exit0 afterward; no API listener was started. Container, volume,
fixture rows/files, original bytes and private receipts remain preserved.

This establishes deterministic provider/core authorization integration only.
It does not establish semantic truth of the mock answer, source authenticity,
live DeepSeek capability, profile/setup UI authorization, OS credential-store
integration, scheduler/run persistence, hard in-flight cancellation or hostile
concurrent filesystem safety. The profile authorization callback is an explicit
synthetic full-profile equality decision. Pending-publication denial has core
coverage from the preceding slice but is not a separate negative provider case
in this proof. No broader Phase1 completion is implied.
