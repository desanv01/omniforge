# OF-011UI — local Cases workspace

Status: implemented, awaiting independent review. This is a bounded UI proof,
not a whole Phase1 acceptance, production authentication, or provider/run proof.

## Delivered behavior

- Memory-only prototype token entry with same-origin fixed loopback dev proxy.
- Generated SDK/DTO case list/create/detail and paginated grant-checked artifact
  list. Structured failures include request ID and revision-conflict guidance.
- Multipart import with explicit expected case revision, stable per-operation
  idempotency key, optional timezone-bearing capture time, and25MiB local limit.
- Saved hash/source/capture/import/publication/revision metadata and exact
  half-open range reads. Blob parsing uses the generated SDK, with byte-count
  verification. UTF8 replacement/boundary warnings, hex, unsupported media,
  empty artifact, pending publication, interruption and partial list states.
- Responsive layout and keyboard focus, native form labels and live errors.
  Future provider/DeepSeek setup is identified as planned, without fake controls.

## Actual validation

Executed on Windows with Node24.14.1, React19.3.1, Vite8.3.5, TypeScript6.0.3,
Playwright1.64.1 and installed Microsoft Edge in headless mode. Web dependencies
were installed once with a separate real package-lock; backend lock unchanged.

Production build and strict TypeScript compile passed. Four focused transport/
range checks passed: upload revision/key/auth placement, interrupted transport,
half-open/unsafe/oversized range bounds, invalid UTF8/boundaries/hex/unsupported
decoding. Synthetic browser create/import/partial text/hex/disconnect/auth-error
checks passed, including widths1440/768/375 and no horizontal document overflow,
no page errors, and empty localStorage/sessionStorage. Synthetic edge-state
verification passed for partial pagination, pending/empty/unsupported artifacts,
and interrupted reads with stale preview cleared. Synthetic suite:7 passed;
independent review then identified Close import could unmount an active request.
That control is now disabled during upload; focused delayed-upload test passed
and confirms Interrupt shows uncertain-outcome guidance and retry preserves the
same idempotency key. Final focused browser flow/upload regression:2 passed.
Final strict compile/production build passed after this correction. Desktop and
375px mobile screenshots were directly inspected and retained privately.

The coordinated actual backend test passed: browser→same-origin proxy→accepted
API→retained isolated PostgreSQL created a synthetic case, uploaded60 bytes,
observed saved SHA256 and null capture time, read exact9-byte text/hex, reloaded
to empty auth input, reauthenticated, read persisted case/artifact and full UTF8
bytes, disconnected and observed invalid-token error. Backend owner held schema
and runtime stable during proof, then received freeze release. No legacy data,
provider credentials, live provider or new/duplicate DB touched.

## Reproduce the bounded checks

From the source root, use the separately owned web package. Node must satisfy
the Vite engine range. The backend is not started or migrated by these commands.

```powershell
Set-Location apps/web
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm run dev
```

Keep that terminal running. In a second terminal at apps/web, use an installed
headless browser. The measured run used installed Edge; omit the channel variable
when Playwright Chromium is already installed. No visible browser window is used.

```powershell
$env:OF_BROWSER_CHANNEL='msedge'
node node_modules/@playwright/test/cli.js test --grep-invert 'coordinated local API'
```

The initial measured synthetic suite had seven tests. The independently requested
upload-close correction added one test, run separately and then with the main
browser flow: both passed. A complete eight-test synthetic rerun after that final
correction was not performed; the focused affected regression and final build
were executed. This distinction avoids implying an unexecuted aggregate result.

The live test is opt-in and skips by default. Coordinate with the backend owner
to start the accepted retained isolated API on loopback port64111, with its
accepted migration and artifact root, before running it. Set
OMNIFORGE_UI_TOKEN_FILE to the explicitly authorized private prototype token file
in the local environment, without printing its contents. Then run:

```powershell
node node_modules/@playwright/test/cli.js test live.spec.ts
```

The test reads that exact file into memory, creates synthetic retained data, and
does not bootstrap, migrate, delete, or clean a database. Auth is sent only in the
Authorization header through the fixed same-origin dev proxy on port64110.
Leave tracing disabled for the authenticated test. The measured live test ran
before the upload-close correction; the later correction changed only the
explicit close control and passed its focused synthetic regression. It did not
change the API operation, generated contract, revision, bytes, or idempotency
transport. No second live write was made merely to repeat accepted evidence.

After the proof, the UI owner stopped its Vite process and confirmed port64110
had no listener. Browser contexts closed. Backend settlement remained with its
exclusive runtime owner, who received proof completion and freeze release.

## Design provenance and limits

Required12ui Draft was attempted. Sandbox network failed before durable run;
network-enabled Draft and prescribed corpus resume both failed503 from the
service, explicitly uncharged. One bounded recovery exhausted; no candidate or
converted baseline was produced. Main reviewed the exact skill instructions and
directed original local implementation under existing human authorization.
UI/UX Pro Max was read/queried; its repeated marketing/academic layout matches
did not fit this application, so general native forms, readable hierarchy,
grid/responsive/focus guidance was used. No generated-design fidelity is claimed.
Private screenshot was visually inspected after the actual browser proof.

Prototype limitations: no durable retry-key journal across reload/navigation,
no deep-linked case routes, no production session management/CSP/packaging,
no user/grant-management UI, no whole-artifact hash recomputation in browser.
The backend verifies blob hash on ranges. The original capture offset provenance
follow-up is owned by OF-014; this proof uses only synthetic bytes and null
capture time. Capture display uses local time; original submitted timestamp
display awaits the additive contract. Provider/scheduler/full-system readiness
remains unverified. Independent review and Main integration are pending.

## Additive OF-014 contract compatibility

After the backend owner froze the additive capture-provenance generated contract,
the strict frontend compile found captured_at could also be omitted. The single
date-format helper now accepts undefined as well as null/string and preserves
its existing `Not recorded` output. Strict no-emit TypeScript compile then passed
against the updated generated client. No backend restart, live fixture rerun,
or new provenance-display feature is claimed by this compatibility adjustment.
