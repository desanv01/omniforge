# Provider process adapter: injected first slice

This slice defines closed dummy launch/role/deadline contracts and an injected
Windows Job Object ownership state machine. It does not execute native operations.
The native factory always raises NativeUnavailable, including when a manifest or
operation object is supplied. Explicit injection is required. Imports do not load a
DLL, read configuration, discover an interpreter or start a process.

The selected creation contract sets kill-on-close without breakaway, supplies a
creation-time JOB_LIST and explicit HANDLE_LIST, creates suspended, verifies exact
job membership, then permits a single explicit resume. Each role has its own
generation token and retained acquisition ledger. Job/process/thread handles are
not inherited. Selected model standard handles are valid inheritable handles;
the job is excluded from the inherited list. These are injected table assertions,
not evidence that CreateProcess or nested-job assignment works on Windows.

Output sinks are registered before acquisition. Partial standard/process/thread
outputs survive known call failure or interruption. Attribute allocation and pointed
values remain retained through successful destruction. The expected failed sizing
probe is handled separately from initialization failure. Ambiguous resume is
possibly-run. Failed closes and termination are not retried unchanged. A failed
observation remains uncertain. Known independent disposal attempts still occur
after a close failure. Contradictory output, clock loss/regression and lost cleanup
evidence cannot become confirmed closure.

Root exit alone is insufficient: closure requires a signaled exact root, zero active
process accounting for the retained exact job, no pending modeled I/O, and successful
attribute/handle disposal before the absolute cutoff. The tree count is observed
before job-handle close. Failures retain ownership and uncertainty, blocking role
replacement. Normal dispose and stop share a once-only termination request.

Work uses the original effective absolute deadline. Stop computes its single
two-second original-owner cleanup cutoff; timeouts are not multiplied by handle.
Settlement requires original-owner closure/no-acquisition proof before that cutoff
and receives min(original cleanup cutoff+2, actual helper start+2). Its final half
second is reserved for termination/disposal. Settlement can occur after work expiry
but cannot resume original work. No acquisition proof is not successful provider work.

Focused verification, using the existing pinned Python environment:

```text
python -B -m unittest discover -s tests/contracts/providers -p test_windows_job.py -v
```

Final actual result: **26 tests passed in 0.031 seconds, exit 0**. An initial
22-test suite passed in 0.034 seconds before adding clock-loss, contradictory-output
and individual-handle failure coverage. There were no failing test executions.
The fakes cover before/after acquisition failures, interruption, startup expiry,
no resume before containment, exact inheritance/flags, unsupported limits, malformed
attribute probe, ambiguous resume, root/grandchild disagreement, accounting lag,
failed observations, pending modeled I/O, attribute/handle disposal failures,
once termination, stale tokens, separate child/authority jobs, no-acquisition
settlement and its strict deadline/reserved disposal window. Lazy declaration tests
reject any DLL construction; only Python ctypes type declarations are inspected.

The lazy declarations describe fixed-width Win32 structures and function signatures;
they are not an implemented native call table. Independent ABI/layout/argtype/error
review remains required. Fakes prove state-machine decisions against the injected
contract, not OS cleanup, crash safety, native timing or a security sandbox. Native
operation is intentionally unavailable in this release, even with a trusted manifest.

No pipe stack, endpoint creation, threads, sockets, database, credentials, provider,
enrollment, arbitrary-command product entrypoint or live runtime is implemented or
tested. The manifest is a trusted dummy-only selection, not a runtime permission.
The current Supervisor and its delivery transition are unchanged. A later delivery
bridge must enforce the reviewed one-use external stop/failure/deadline predicate
compatible with its delivered proposal state; live() cannot supply that positive
gate. Journal, fresh Backend authority, observer wiring and delivery remain separate
gates. OS process exit cannot establish that a database commit was aborted.

Future IPC, harmless dummy child/grandchild and dummy-owner crash proof each require
an exact separate release and independent acceptance. No native proof or whole
provider/Phase1 readiness follows from this injected slice.
