# Phase 1 — bounded scaffold and next proofs

OF-010 provides eight ADRs, normative draft contracts, locked minimal Python
dependencies, health API and one offline smoke. Independent acceptance is pending.
This is a runnable scaffold, not a completed Phase1 gate.

Direct dependencies selected from public PyPI metadata on 23 October 2026:
FastAPI 0.161.1, Pydantic 2.14.1, Uvicorn 0.54.0; dev HTTPX2 2.16.0.
All report compatibility with selected Python 3.11. Exact transitive versions and
distribution SHA256 values are in uv.lock. uv 0.11.25 resolves/synchronizes the
environment; this is not independent upstream signature/attestation verification.
Only the native Windows CPython 3.11 environment is measured. Linux and other
Python minors are unverified. Interpreter is not vendored; patch-level supply and
artifact verification remain installation work.

Primary references consulted:

- [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [FastAPI package metadata](https://pypi.org/pypi/fastapi/json)
- [Pydantic package metadata](https://pypi.org/pypi/pydantic/json)
- [Uvicorn package metadata](https://pypi.org/pypi/uvicorn/json)
- [HTTPX2 package metadata](https://pypi.org/pypi/httpx2/json)
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)

Regenerate the implemented OpenAPI snapshot after route/model changes:

```powershell
uv run --locked --no-sync python -c "import json; from pathlib import Path; from services.api.app import app; Path('packages/contracts/openapi.json').write_text(json.dumps(app.openapi(), indent=2, sort_keys=True)+'\n', encoding='utf-8')"
uv run --locked --no-sync python -m services.api.smoke
```

## Proposed next finite assignments for Main

These are ownership proposals, not dispatched work. OF-010 review acceptance
precedes changes to shared contracts. Main assigns one install/runtime/DB owner for
OF-011 and registers owners before integration. Coordinate changes to root
pyproject.toml/uv.lock through that owner; other tasks must not resolve concurrently.

| Task | Exclusive proposed file ownership | Dependencies and proof |
|---|---|---|
| OF-011 API/runtime owner | services/api/** except provider/run modules reserved below; migrations/**; infra/core/**; root pyproject.toml/uv.lock; packages/contracts/openapi.json; packages/contracts/generated/**; tests/integration/core/** | Accepted OF-010. Select isolated DB/artifact roots/port; lock SQLAlchemy/Alembic/driver after primary checks. Implement case transaction, grant/error/idempotency/revision handling, streamed artifact/hash/range/reconciliation proof and generated client. Own backend aggregate router integration. |
| OF-011 UI owner, separately assigned after API snapshot | apps/web/**; tests/e2e/core/**; web dependency manifest/lock | OF-011 API snapshot/client. Use required design skills. One browser create/read and artifact viewer with loading/empty/partial/error/interrupted/unsupported states; no hand-coded duplicate DTOs. UI installs owned separately, no DB/runtime duplicate. |
| OF-012 provider owner | adapters/models/**; services/api/providers/**; tests/contracts/providers/**; docs/phases/provider-proof.md | OF-011 stable read evidence/grants and accepted contracts. Mock cited result/budgets/errors first; exact SDK selection via dependency owner. Bounded real DeepSeek tool round trip separately configured/authorized, with redacted receipt and known/estimated/unknown usage. No scheduler or secret-store implementation without assignment. |
| OF-013 scheduler owner | services/worker/**; services/api/runs/**; infra/scheduler/**; tests/integration/scheduler/**; docs/phases/scheduler-proof.md | OF-011 persistence/migrations and accepted run contract. Submit schema needs to DB owner. Own isolated scheduler runtime once assigned. Interrupt/recover fixture, fence stale attempt, idempotent cancel, persisted replay and duplicate-output reconciliation. Hatchet remains candidate until measured. |
| OF-014 portable schema owner | packages/contracts/evidence/**; packages/contracts/export/**; tests/fixtures/evidence/**; tests/contracts/evidence/**; docs/phases/evidence-proof.md | OF-011 artifact DTO/publication contract. Implement JSON Schemas and synthetic corpus: text/JSON/CSV malformed/truncated, duplicate bytes/distinct origins, exact ranges, complete/incomplete empty, interrupted publication. Round-trip manifest/Markdown validation, path/hash/size rejection and provenance preservation. |

Provider/scheduler owners submit DTO and dependency changes to API/runtime owner;
they do not edit the same OpenAPI, migration head or lock concurrently. Contract
changes route through Main and affected owners. Independent C review follows each
finite delivery. No new coordinator, schedule or live provider authorization is
created by this proposal.

Pending Phase1 acceptance: browser/API/PostgreSQL transaction; hashed artifact and
duplicate-origin association; mocked cited provider result; separately evidenced
real provider check or explicit pending; failed/canceled histories; observed
scheduler interruption/recovery; portable fixture corpus; generated client equality.
Secret store, container isolation and operational recovery remain explicit later
proofs. No full Phase1 acceptance follows from the health smoke alone.
