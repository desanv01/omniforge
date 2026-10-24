# OF-013-A — isolated Hatchet feasibility proof

Status: **AWAITING INDEPENDENT REVIEW**. Standalone deployment/recovery proved;
application scheduler integration and full Phase1 acceptance remain pending.
Measured 24 October 2026 (Asia/Kuala_Lumpur).

## Result and boundary

Windows CPython3.11.15 successfully drives a self-hosted Linux/amd64 Hatchet Lite
v0.110.5 engine with Python SDK1.41.1 in Linux Docker workers. The engine release's
own Python manifest supplies that SDK version. Native Windows worker creation
fails because the SDK unconditionally registers POSIX `signal.SIGQUIT`; no signal
monkeypatch or vendor-source edit is used. A Linux worker is required for this pair.

The actual bounded fixture queued one synthetic job before a worker existed,
committed its synthetic publication, killed the worker before completion
acknowledgement, restarted Lite, and observed a second attempt reach COMPLETED.
Exactly one publication survived. Repeated cancellation reached CANCELLED and
blocked further publication; an intentional error reached FAILED after two
attempts. An isolated running-attempt witness rejected token1 after token2 was
claimed, independently of terminal-state rejection.

The first aggregate command exited1 on a transient404 when reading the failure
run immediately after dispatch. Its receipt remains failed and retained. A separate
read-only scheduler reconciliation of the same three IDs confirmed COMPLETED,
CANCELLED and FAILED; it submitted no additional scheduler work. This reflects
Hatchet's documented lagging REST reads. The bounded poll now tolerates only
NotFound for reads within its existing deadline; dispatch is never retried.

The SQLite journal is a **synthetic publication witness**, not application
persistence. Its terminal success is written only after scheduler COMPLETED and
an existing publication. It proves the fixture algorithm and scheduler behavior;
it does not prove accepted-core outbox delivery, authorization, leases, atomic
Run/Event/output transactions, SSE replay, artifact publication or provider effects.
SDK callbacks and queue acknowledgement are not application durable success.

Hatchet remains a viable candidate behind ADR0004, awaiting review and domain
integration. Deployment/recovery passed after the supported Linux-worker
correction, so the conditional Temporal comparison was not triggered.

## Reproducible inputs and footprint

* Lite image: `ghcr.io/hatchet-dev/hatchet/hatchet-lite@sha256:cc81f078a5285d7d2051ec4a4fa459d033e1face4ca5983d82612b00da6e3fa3`.
* Existing local PostgreSQL16.13 image content ID:
  `sha256:32ebb7185baf2c9d38f91684417d140c0745aeff5082dfbb62edb330c2af6197`.
* Official Linux Python3.11.15 bookworm base:
  `python@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3`.
* Owned worker image: `omniforge-rebuild-scheduler-of013a-worker:locked`, built
  from `worker.Dockerfile` and `requirements.txt` with pip `--require-hashes`.
  The exact observed image identity is retained in private delivery evidence.
* Scheduler-only `pyproject.toml`, universal `uv.lock` and exported hashed
  requirements pin SDK1.41.1 plus28 packages. Root backend lock/env were untouched.
* Prefix `omniforge-rebuild-scheduler-of013a` exclusively labels owned PostgreSQL,
  Lite, two worker containers, pgdata/config volumes and internal/ingress bridges.
* Only Lite publishes `127.0.0.1:63151` HTTP and `127.0.0.1:63152` gRPC. PostgreSQL
  has no host port. Initial internal-only bridge suppressed published ports;
  one distinguishing check showed in-container HTTP200 plus empty runtime port
  bindings. Adding the dedicated ingress bridge restored loopback HTTP200.
* PostgreSQL stays internal. Workers have only the internal bridge, no host ports,
  a read-only fixture-source mount and their private synthetic witness directory.
  Lite's ingress bridge permits outbound networking; no deny-egress claim is made.
* Resource limits: PostgreSQL512MiB/1CPU, Lite1536MiB/2CPU, each worker512MiB/1CPU.
  No concurrency benchmark, production capacity or hardened executor is proved.
* Runtime config, password, two-hour worker token, logs and fixture DB stay in an
  explicitly supplied private root outside source, ACL restricted during bootstrap.
  No preexisting credentials are read. Vendor fixture admin defaults remain a
  development-only limitation; this is not a production deployment profile.

All owned service containers were stopped and preserved after proof. PostgreSQL,
Lite and second worker exit0; first worker exit137 is the deliberate kill. Volumes,
networks, images and private files remain for independent review; no deletion.

## Commands and evidence

Run from rebuild root with a separate scheduler Python environment; supply a new
private runtime root outside source to `infra/scheduler/runtime.py prepare`.
The helper refuses existing names. Existing retained resources must be inspected
and resumed rather than recreated. Token creation uses the owned Lite admin
command with a two-hour expiry and captures stdout directly into a private file;
never print the token or commit runtime configuration.

Actual command families, each successful unless explicitly noted:

1. Primary release/source inspection, exact Docker pull; `uv lock` and `uv sync
   --locked --project infra/scheduler` into a new private venv. An earlier install
   request was rejected before execution because it referenced the shared Phase1
   interpreter; corrected to the standalone base Python/new private environment.
2. `python infra/scheduler/runtime.py prepare <new-private-root>`; isolated PG
   readiness, migrations, Lite startup, captured private token, loopback HTTP200.
3. `uv export --locked --format requirements-txt --no-dev --no-emit-project`;
   Docker build with the measured Python digest and scheduler-only context.
4. `python -m tests.integration.scheduler.check`: original native-worker startup
   failed before dispatch on SIGQUIT; supported Linux correction then proved
   recovery/cancel, but exited1 on first failure-status404.
5. `python -m tests.integration.scheduler.reconcile`: exit0, `redispatched=false`,
   states COMPLETED/CANCELLED/FAILED, failure attempts2, running fence rejected.
6. AST parse of the initial four owned Python modules: passed. Independent review
   found raw SDK exception traceback leakage at the CLI boundary. Both commands
   now return1 with a fixed safe message and preserve private receipts/evidence.
   A no-network regression injects a secret-bearing exception and checks both CLI
   paths emit no raw text or traceback. No recovery redispatch or broad rerun.
7. `python infra/scheduler/runtime.py settle <private-root>`: exit0; owned Lite/PG
   stopped-preserved. Worker settlement recorded by fixture finally block.

Private receipts preserve commands, identities, raw logs and original failure.
Reviewer should inspect retained state/evidence before authorizing further runtime;
this finite test is not designed to blindly reuse existing worker names.

## Required backend integration seam

Submitted to Main and the backend owner; no shared schema/API/lock edits made:

* Persist authorized principal-scoped idempotent Run + first ordered event + outbox
  in one core transaction before dispatch; use a stable dispatch key and reconcile
  acknowledgement loss without assuming scheduler exactly-once execution.
* Persist attempts, increasing fencing token and lease before work; every output
  and terminal mutation checks fence, expected revision and cancel state atomically.
* Unique publication identity with request/output hash; reconcile existing output
  after redelivery. Commit output refs, Run terminal transition and terminal event
  together. Preserve partial output and known/unknown usage on cancellation.
* Explicit scheduler-execution mapping and recovery policy; unknown external
  effects become uncertain. Scheduler retries only safe/reconciled operations.
* Grant-checked Run read/cancel and persisted per-run event cursor/replay, matching
  SPEC and generated API/client under the backend owner's integration.

## Primary sources and reuse

Consulted current primary documentation and pinned source before execution:

* [Hatchet releases](https://github.com/hatchet-dev/hatchet/releases/tag/v0.110.5)
* [Lite deployment](https://docs.hatchet.run/self-hosting/hatchet-lite)
* [Docker workers](https://docs.hatchet.run/v1/docker)
* [Retry policies and lagging REST reads](https://docs.hatchet.run/v1/retry-policies)
* [Pinned Lite startup](https://github.com/hatchet-dev/hatchet/blob/v0.110.5/hack/lite/start.sh)
* [Pinned SDK manifest](https://github.com/hatchet-dev/hatchet/blob/v0.110.5/sdks/python/pyproject.toml)
* [Docker bridge networking](https://docs.docker.com/engine/network/drivers/bridge/)
* [Docker internal networks](https://docs.docker.com/reference/cli/docker/network/create/)

Hatchet is MIT; installed as an external pinned dependency, not copied vendor
source. Fixture declarations use documented SDK APIs; standalone registration
uses the pinned SDK's internal admin client and must be revisited on upgrade.
No downloaded compose/start script was executed directly. Original fixture/runtime
code remains in the assigned scheduler/worker directories. Upgrade/remove route:
replace the task-local pins/images and rerun an independently reviewed equivalent
fixture before application adoption; retained data is never implicitly deleted.
