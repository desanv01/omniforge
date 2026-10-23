# ADR 0001 — Python control plane

Status: selected for the OF-010 prototype; production suitability pending Phase 1.

Context: HTTP metadata reads/writes, journal orchestration and typed analysis are
control-plane workloads. Isolated asynchronous tools belong outside the API.
Use CPython 3.11, FastAPI and Pydantic with exact uv locks. This reuses an available
interpreter without modifying its environment or downloading another runtime.
Measured installation/smoke results are recorded privately by the owner; selected
dependencies and public reproduction steps belong in docs/phases/phase1.md.

Hypothesis: Python ecosystem fit outweighs packaging/worker overhead. Health and
schema proof establish only the minimal HTTP stack. OF-011 must prove PostgreSQL
transactions/migrations, generated client and browser behavior. Packaging/resource
measurement remains Phase11. Go is a fallback if measured costs are unacceptable;
do not develop a competing implementation. Python 3.10 exists locally but is not
the selected target. Newer interpreters are not implicitly supported by the lock.
