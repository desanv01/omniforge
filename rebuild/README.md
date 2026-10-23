# OmniForge rebuild

OmniForge is being rebuilt as a personal evidence and investigation workspace.
This Phase 1 foundation provides a local Python API, PostgreSQL case records,
explicit case grants, bounded artifact uploads, exact byte-range access and
recoverable artifact publication. A separate Windows credential adapter is ready
for provider integration. The React interface is under development.

The browser journey, model investigation, scheduler recovery and complete product
installation are still being implemented. An available API endpoint does not mean
those capabilities have passed their acceptance checks. Health reports process
liveness separately from dependency and capability readiness.

## Run the offline contract check

Use CPython 3.11 and uv. From this directory:

```powershell
uv sync --locked --python <python-3.11-executable>
uv run --locked --no-sync python -m services.api.smoke
```

The check uses an in-process client without a server listener, database or model
call. Dependency installation itself requires the package registry or a cache.

## Run the local core

The current Windows development bootstrap requires Docker and the exact existing
PostgreSQL image documented in [the core proof](docs/phases/core-proof.md).
It is not yet a general installer. Use a new private directory outside this source;
never point the bootstrap at legacy data or an existing runtime directory.

```powershell
uv run --locked --no-sync python -m infra.core.bootstrap prepare <new-private-directory>
$env:OMNIFORGE_CONFIG = '<new-private-directory>/config.json'
# Wait for the newly created database to become healthy before migration.
uv run --locked --no-sync python -m infra.core.migrate
uv run --locked --no-sync python -m infra.core.bootstrap seed <new-private-directory>
uv run --locked --no-sync python -m infra.core.serve --port <available-unprivileged-port>
```

For an existing development runtime, reuse its recorded container and private
configuration; do not repeat `prepare`. The server binds to loopback and disables
access logs. The private `auth-token` is the temporary local API credential, distinct
from a model API key. Send it in an Authorization Bearer header; never put it in a
URL, source file or diagnostic output. Browser integration keeps it in memory.
No environment file is automatically loaded; `OMNIFORGE_CONFIG` selects the private
configuration explicitly. Do not expose this prototype on a public interface.

A future native PostgreSQL profile can avoid Docker for the core. Arbitrary tool
execution has no host fallback and remains unsupported until its isolated executor
is implemented. Provider credentials have no plaintext fallback: the reviewed
Windows adapter requires the intended desktop user, and provider setup is pending.

## Evidence and verification

- [Core proof](docs/phases/core-proof.md): observed PostgreSQL/auth/artifact tests,
  isolation, exact versions and limits.
- [Credential-store proof](docs/phases/secret-store-proof.md): synthetic Windows
  lifecycle tests, identity scope and manual re-entry limitations.
- [Phase 1 plan](docs/phases/phase1.md): remaining browser/provider/scheduler proofs.
- [API and evidence contracts](packages/contracts/SPEC.md): lifecycle, origin,
  grants and error semantics. [OpenAPI](packages/contracts/openapi.json) and its
  generated client describe implemented endpoints.
- [Architecture decisions](docs/adr): selected boundaries and unverified candidates.

Artifact stages, including failed and replayed uploads, are retained. Quotas and
safe garbage collection are required before sustained ingestion. Controlled fault
injection demonstrates publication reconciliation, not power-loss recovery or a
complete backup restore. Model/provider readiness and scheduler recovery remain
unverified; no live DeepSeek result is implied by offline tests.

Legacy source and history remain separate. Runtime data, credentials, imported
samples and private coordination evidence must stay outside tracked source. The
bundled generated client retains its upstream license notice in
`packages/contracts/generated/THIRD_PARTY_NOTICES.txt`.
