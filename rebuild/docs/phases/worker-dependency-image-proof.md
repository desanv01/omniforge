# Linux worker dependency image proof

25 October 2026. **Build and restricted dependency smoke passed; independent review pending.** This proves installed imports for the accepted dependency image only. No native worker, scheduler/API service, database connection or provider operation was started.

The build used exactly the four accepted worker-runtime bundle files, without a new resolution or dependency change. Base remained `python@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3` (Linux amd64, CPython3.11.15/bookworm). Hashed requirements SHA256 remained `7d9cc462731eed0358e577419b887a89074c18e496bfb1baf0dd1d03fafb8771`. The isolated build installed binary wheels with require-hashes and exited0 in47.073s on its sole attempt.

Docker reported resulting image identity `sha256:60b312b112f163ae20d3e7dab6432d454222390305fd8855b7f5c9f4109595e7`. A new owner-labelled container then executed one dependency-only assertion/import command with:

- Linux x86_64, UID/GID65532 and bytecode disabled.
- Network none, no mounts, no published ports and a read-only root filesystem.
- All capabilities dropped, no-new-privileges and no restart policy.
- One CPU,512MiB memory with no extra swap,64 PIDs and an external60-second wall limit; pip check had an internal20-second limit.

Actual result: exit0, no OOM,6.133s measured inside the script and7.772s including Docker attach overhead. Self maximum RSS was115,612KiB; the pip subprocess maximum RSS was51,972KiB. These are separate process measurements, not an aggregate peak or production sizing benchmark.

`pip check` returned0 with `No broken requirements found.` Its non-root cache-location warning disabled caching; it did not report a dependency failure. The smoke imported Hatchet SDK, SQLAlchemy, Psycopg, Pydantic and FastAPI plus `psycopg_binary`, `psycopg.pq`, `grpc._cython.cygrpc` and `pydantic_core._pydantic_core`, without constructing clients, connections, engines, sessions or application services in the smoke code. Psycopg selected its binary pq implementation; native libpq version was180006.

| Distribution | Installed version |
|---|---|
| hatchet-sdk |1.41.1|
| SQLAlchemy |2.1.6|
| psycopg / psycopg-binary |3.3.6|
| Pydantic |2.14.1|
| FastAPI |0.161.1|

Container and image are retained; final container state was exited/exit0. Previous fixture resources, original source, shared environments and database were untouched. The image default remains `python --version`; no worker auto-start was added.

Remaining separate gates: immutable worker source/config selection, live transport factory/retry policy, DB permissions and actual core-connected execution, real scheduler registration/search/dedup/cancel behavior, process termination/finally/recovery, SSE integration and performance. Import success and pip metadata consistency do not establish those capabilities, dependency vulnerability status, Linux arm64 support or full Phase1 readiness. Repeating this completed build/smoke is unnecessary while its relevant inputs remain unchanged.
