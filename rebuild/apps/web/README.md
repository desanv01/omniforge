# Local Cases workspace

React/Vite/TypeScript frontend for the generated core contract. Run from this
directory with Node matching Vite's engines (verified Node24.14.1):

```powershell
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm run dev
```

Development binds only127.0.0.1:64110 and proxies `/api` to the fixed loopback
API127.0.0.1:64111. The backend owner starts the isolated runtime separately;
this frontend never bootstraps/migrates a database. `vite preview` serves build
assets only and has no authenticated API proxy; use the dev command for the
current local end-to-end prototype. Deployment/packaging is not part of this slice.

Enter the separately supplied local prototype token into the password field.
The client closure retains it in memory; no URL, browser storage, analytics,
console or source file receives it. Reload or Disconnect requires re-entry.
Redirects fail closed; authenticated requests request no-store caching.
This is a local trusted-user prototype, not production accounts or a hardened
multiuser web server. Do not expose the dev server beyond loopback.

The UI imports every DTO and operation from `packages/contracts/generated`.
Binary reads use the generated operation with `parseAs: 'blob'`; the browser
checks the requested half-open byte count before decoding. Full-artifact SHA256
comes from saved metadata, not a partial-range hash calculated by this UI.
UTF8 failures and partial boundaries are explicit, and hex preserves byte values.
Preview is bounded to64KiB; upload is bounded to25MiB. Unknown capture time remains
null, separate from imported time. Provider/DeepSeek and run configuration remain
future work, with no fabricated routes or results.

Identical failed/uncertain create or upload attempts retain the same idempotency
key while the form remains mounted and input/revision is unchanged. Navigating
away or reloading discards that volatile key. After an interrupted mutation,
refresh/read persisted state before starting another operation. Closing this
prototype is not a durable retry journal. A409 requires refresh and user review.

Headless checks, with the dev server already running:

```powershell
$env:OF_BROWSER_CHANNEL='msedge' # omit when Playwright Chromium is installed
npm test
```

The coordinated live check skips unless `OMNIFORGE_UI_TOKEN_FILE` points to an
explicitly approved private prototype token file and the backend owner has
started the isolated API. It creates synthetic retained data and never deletes
or migrates anything. Do not enable tracing/screenshots of auth entry or log
request headers. Screenshots taken after connection stay in ignored test-results.

Primary toolchain references: [React versions](https://react.dev/versions),
[Vite guide](https://vite.dev/guide/), [Vite React plugin](https://github.com/vitejs/vite-plugin-react/tree/main/packages/plugin-react),
[Hey API fetch client](https://heyapi.dev/docs/openapi/typescript/clients/fetch),
[Playwright browsers](https://playwright.dev/docs/browsers).
Exact dependencies/integrity are recorded in the separate package-lock.json.
TS6.0.3 retains the backend generator's verified compiler compatibility.
