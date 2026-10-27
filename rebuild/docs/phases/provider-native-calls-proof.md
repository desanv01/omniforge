# Injected Win32 call wrappers

This source implements selected Win32-shaped marshaling and result normalization
over explicitly injected symbols/error accessors. There is no DLL loader, kernel32
global, function-address/prototype construction or ambient discovery. Both existing
native_api and the new load_native_calls entrypoint remain unconditionally unavailable.
Manifest possession does not authorize native execution.

The wrapper reuses the accepted lazy ABI declarations. Additional metadata covers
SECURITY_ATTRIBUTES, CreateFileW and GetHandleInformation. Its default host-shape
check rejects non64-bit handles or non2-byte WCHAR before acquisition. This necessary
check is not independent Windows SDK size/offset/calling-convention acceptance. The
tests explicitly inject a model-only ABI check so fake-host ctypes layouts cannot
be mistaken for supported native execution.

Selected behavior includes immediate failure error snapshots, NULL versus file-handle
invalid sentinel, raw nonzero BOOL normalization, fixed job information classes,
three explicit inheritable NUL standard handles, exact creation-time job/inherited
handle arrays, retained writable attribute allocation/views, normal versus uncertain
initialization/destruction, explicit mutable command/Unicode environment, and
pre-registered PROCESS_INFORMATION outputs published before validation or exceptions.
The actual wrapper is composed with the unchanged JobOwner in inert tests.

Focused verification from source root using the existing pinned Python:

```text
python -B -m unittest discover -s tests/contracts/providers -p 'test_windows_*.py' -v
```

Final actual result: **44 tests passed in0.064seconds, exit0**:18 new raw-wrapper
tests plus26 unchanged ownership tests. The initial14 new-test run passed in0.160s
before adding declaration/query/initialization/conversion/mutated-array coverage.
No failing execution occurred. Tests use Python raw-function objects that mutate
actual wrapper ctypes output pointers; no native callback prototype or OS call.
Loader/prototype constructors are patched to fail in the no-native test.

Coverage includes raw error/sentinel distinctions and error-accessor exceptions;
partial standard handles; job acquisition followed by flag-check failure; partial
process outputs on failure/interruption/success contradiction; retained attribute
arrays through deletion; ambiguous initialization/deletion; query sizes; selected
arguments/flags/stdhandles; quoting/explicit environment and forbidden controls;
membership/root/accounting composition; disposal failure and no repeated close;
missing symbols/unsupported ABI; unconditionally unavailable native paths; original
delayed-settlement cutoff mismatch rejection without refreshing time.

The wrapper retains exact sink identities and native-shaped storage per invocation.
Unknown initialization/destruction retains backing storage, rather than freeing it
or repeating a possibly completed operation. Actual pointer-output buffers support
controlled exception-path publication. This is not proof against arbitrary asynchronous
interruption between acquisition and Python publication. Handle-return APIs and
initialization-state updates retain that unresolved native-release blocker. Finally,
errcheck or successful fake callbacks cannot establish atomic native ownership.

Future native release must independently resolve supported interruption exclusion or
a separately scoped publication shim, actual WinDLL/stdcall/use_last_error bindings,
ABI/alignment/UTF-16/error behavior, trusted selected DLL and operation-authority gates.
No real symbols are supplied by this module. Fake accessors do not prove Windows
last-error preservation, native call timing or descendant cleanup.

There is no process/Job Object/NUL handle opened, DLL loaded, pipe/IPC/DB/SDK/provider/
credential/network operation or dependency install in these tests. No controller,
journal, fresh authority, capability capture or one-use actual-return bridge is
implemented. Existing role/deadline policy is unchanged. Native ABI/dummy child and
grandchild/owner-crash proof, then separately owned IPC/clock/journal/return integration,
remain future exact releases. Process exit cannot prove SQL COMMIT abortion. Whole
provider/Phase1/native readiness is not established.

## V2 bounded attribute-retention correction

Independent review F1 identified that a duplicate per-key UpdateProcThreadAttribute
attempt could replace an earlier retained value array before a failed/raised raw
update. Current JobOwner uses each key once, but the exported wrapper also needs
that lifetime restriction. V2 rejects duplicate JOB_LIST/HANDLE_LIST attempts before
allocation, replacement or raw entry. An initial failed/raised attempt also reserves
its original array until completed attribute-list destruction.

The focused regression uses weak references, clears all raw recorded byref arguments,
forces garbage collection, and checks wrapper-owned exact array identity. It covers
both keys, first success/failure/exception and a duplicate configured to fail/raise;
the duplicate raw callback must never run. Original array survives through destruction
and becomes collectible only afterward. V1's44PASS result remains historical evidence;
V2 execution is reported separately in the private delivery appendix. Native defaults,
asynchronous-publication blocker and accepted timing policy are unchanged.

Actual V2 focused run:19 wrapper tests passed in0.195seconds, exit0, including the
12 duplicate-retention subcases. The unchanged26 ownership tests were not repeated
for this narrow guard; their previous44-total run remains V1 evidence only. No
failing execution occurred and no native operation was performed.
