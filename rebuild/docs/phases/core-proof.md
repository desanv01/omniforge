# OF-011 — local persistence and artifact foundation

Status: implemented, awaiting independent review. No browser/UI, live provider,
scheduler or executor proof is claimed. Health remains `ready=false` for the full
core while provider/scheduler are unverified. Database readiness requires the exact
Alembic migration; artifact readiness checks the configured directories/access.
Each range read also checks actual full blob SHA256/size before returning bytes.

## Runtime and authentication

The prototype uses a new database/container/volume with rebuild-specific names,
loopback-only published PostgreSQL port, independent artifact root and private
configuration/token/password files outside source. `infra/core/bootstrap.py`
requires a previously absent directory and resource names, installs a restricted
Windows ACL, generates 48-byte random bearer/password values and never prints them.
The current prototype reuses an identified local PostgreSQL16.13 image by exact
image ID rather than pulling/upgrading the legacy image. This is not a statement
that16.13 is the newest patch or a production security baseline. The local image
digest is recorded by bootstrap; a distributable/current official image choice is
pending operational packaging. Docker's local admin and the Windows user/admin/
SYSTEM remain trusted. This prototype is not enterprise identity or encrypted
provider secret storage.

With CPython3.11, installed dependencies and Docker available, from source root:

```powershell
python -m infra.core.bootstrap prepare <new-private-runtime-directory>
$env:OMNIFORGE_CONFIG = '<private-runtime-directory>/config.json'
python -m infra.core.migrate
python -m infra.core.bootstrap seed <private-runtime-directory>
python -m infra.core.serve --port <available-loopback-port>
```

Use the isolated project environment, not an unrelated global Python. See
pyproject.toml/uv.lock for exact dependencies and README for uv sync usage. No
migration runs automatically on API import. `serve` fixes127.0.0.1 and disables
access logs. Select an available port before starting; no server remains held by
this delivery. The owner stopped/preserved the proof database after checks.
Do not rerun prepare on retained resources or delete them to restart a proof.

Browser integration should use a same-origin local dev proxy and generated SDK.
The user reads the private auth-token locally and enters it into a password input;
retain it in memory only, send Authorization: Bearer, never URL/query/log/storage.
No permissive CORS or arbitrary principal header is enabled. Reload requires
re-entry in this minimal prototype. The authenticated case list and paged artifact
list recover persisted state after entry. Future provider secrets use the reviewed
separate store adapter, not this temporary local-auth file.

## Migration and transactions

Alembic0001_core creates principals, cases, grants, artifacts, source associations
and idempotency journal. Foreign-key lookup columns are indexed. Stable IDs are
UUIDs, timestamps timezone-aware, revisions explicit. Creator receives its case
grant within the case transaction; owner association alone is not authority.
Transactional advisory locks serialize idempotency keys. Case row locks fence
concurrent uploads by expected revision. Same-key changed input409; stale revision
409; lost/unknown auth401; missing case write grant403. Association lookup filters
grants before returning source data and returns404 for inaccessible associations.

Streaming multipart permits exactly one `file`, bounded headers and wire overhead,
25MiB file maximum, and rejects truncated streams. File bytes are fsynced to
staging; pending association plus idempotency response commit before publication.
Content-addressed publication verifies stage and destination, preserves stage,
and commits metadata after atomic filesystem replacement. A crash after rename
leaves a visible pending record and recoverable blob. Filesystem rename and DB
commit are explicitly separate. Reconciler uses bounded locked batches, verifies
hash/size and advances pending metadata/idempotency response; it does not delete.

```powershell
python -m infra.core.reconcile --limit 20
```

Invalid/oversize uploads, replay uploads and uncommitted publication stages remain
on disk by design. This retains evidence but needs quota/staging lifecycle and
reference-aware cleanup before sustained ingestion. No automatic retry loop,
retirement/deletion or scheduler durability is implied. Synthetic fault fixtures
exercise before/after filesystem publication rollback; they are not a process-
kill/power-loss/filesystem durability or backup/restore demonstration.

## Actual verification and client toolchain

Focused integration fixtures run against the explicit new PostgreSQL only:

```powershell
python -m tests.integration.core.check
python -m services.api.smoke
```

Observed: six initial integration tests passed; after adding the per-case artifact
list/path normalization, only the affected error/OpenAPI test and new reload/list/
grant/path test were rerun and passed. Updated offline smoke passed. Coverage:
persisted read through a fresh app, concurrent same-key replay and changed-body
conflict, revision race, unauthorized principal/grants, distinct origins for same
blob, exact byte/hash ranges and invalid bounds, 25MiB streamed limit/truncation,
two controlled publication crash windows/reconciliation, custom errors/headers and
generated OpenAPI equality. No browser proof was executed.

Direct additions: SQLAlchemy2.1.6, Alembic1.20.1, Psycopg[binary]3.3.6,
python-multipart0.0.32. Existing accepted dependency versions retained. Real uv
lock/sync succeeds. Exact npm toolchain: @hey-api/openapi-ts0.99.0 and TypeScript
6.0.3, with package-lock.json. TypeScript7.0.2 failed generator compiler-API access;
the supported6.x pin resolved it. Unmaintained openapi-typescript-codegen was
considered from upstream notice and never installed. Generated fetch/core client
is bundled locally, with MIT notice. No separate runtime client package needed.

```powershell
npm ci --prefix infra/core/client-tooling --ignore-scripts --no-audit --no-fund
python -m infra.core.generate_client
infra/core/client-tooling/node_modules/.bin/tsc -p infra/core/client-tooling/tsconfig.json
```

Actual generation and strict no-emit compile passed. OpenAPI servers use `/`;
SDK operations use relative API paths and typed errors, multipart serializer and
bearer authentication. UI must explicitly configure client baseUrl/auth and select
arrayBuffer/blob response parsing for binary ranges. Do not edit generated files.

## Primary sources and actual reuse

- [SQLAlchemy PostgreSQL/Psycopg dialect](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)
- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Streaming multipart callbacks](https://multipart.fastapiexpert.com/)
- [Official PostgreSQL image](https://hub.docker.com/_/postgres)
- [Hey API generator](https://heyapi.dev/docs/openapi/typescript/get-started)
- [Hey API fetch client](https://heyapi.dev/docs/openapi/typescript/clients/fetch)
- Current package JSON metadata: PyPI sqlalchemy/alembic/psycopg/python-multipart;
  npm @hey-api/openapi-ts/typescript. Exact URLs/digests appear in lockfiles.

Actual reused code: Hey API bundled fetch/core runtime in
packages/contracts/generated/{client,core}, generated by @hey-api/openapi-ts0.99.0
from the locally authored OpenAPI. Author/copyright Hey API, MIT LICENSE.md from
the installed exact npm package, retained in generated/THIRD_PARTY_NOTICES.txt.
No manual modifications. Digest/integrity of generator and transitive dependencies
recorded in infra/core/client-tooling/package-lock.json. Purpose: typed local
HTTP client; access: caller-supplied endpoint/token only, no privileged host access.
Fixtures: strict compile, OpenAPI equality; browser transport remains pending.
Upgrade/removal: change pinned toolchain and regenerate, or replace generated
client at shared contract boundary. Verification date:23October2026. Other API,
schema and fixture source in this slice was authored for these behavior contracts;
no legacy code/rules/prompts/samples copied. Whole-project license compatibility
and final distribution review remain Main's integration gate.
