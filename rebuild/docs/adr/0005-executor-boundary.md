# ADR 0005 — API never becomes arbitrary host executor

Status: boundary selected; container/remote executor proof deferred.

Control plane validates principals, scope, policy, budget and immutable inputs.
Untrusted parsing/scanning/browser tools run in separately configured isolated
workers, initially Docker if available. Pin executor images by digest; specify
mounts, network allowlist, CPU/memory/time/output limits and per-run identity.
Read-only evidence ingestion does not imply permission to run commands in evidence.

No executor exists here. Docker availability and isolation are not asserted from
legacy runtime evidence. Without an approved container/remote worker, arbitrary
execution reports unsupported; never fall back to host shell. Podman or remote
workers can implement the same boundary after their own proof. Native Windows
core and Linux workers may have different operational prerequisites. Executor
privileges and recovery need dedicated later acceptance.
