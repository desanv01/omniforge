# Disposable native inert-load probe — source preparation

This three-new-path slice supplies a C-only probe source, separate pinned CMake
target and this proof document. **No configure/build/test/load or runtime assertion
has executed for this probe.** Source preparation is not compiled ABI acceptance.
Existing accepted ABI/core/client/shared CMake and Python model_only behavior are
unchanged. No real provider or OS ownership table is added.

The executable is built separately from the inert DLL. Its CMake target compiles
only inert_load_probe.c and includes accepted type declarations. It does not compile
or link the target core/wrapper implementations or the target import library.
Every target call uses an actual resolved address. Exact MSVC/x64/toolset/SDK/
instance/C11 /W4 /WX /MT /guard:cf gates are preserved; linker CFG is explicit.
No CTest registration can automatically run a load. All source remains unbuilt.

Proposed strict invocation shape, with operator-supplied values:

```text
inert_load_probe.exe --artifact ABSOLUTE_DLL_PATH --operation 32lowerhex --generation 32lowerhex --receipt 64lowerhex
```

Only canonical ASCII drive-absolute backslash paths below1024 WCHARs ending exactly
owned_slot_inert_exports.dll are admitted. Relative/traversal/empty components,
forward slashes, device components, alternate streams and trailing-dot/space
components are refused. Operation and generation decode16 nonzero opaque bytes
each; receipt is a nonzero64-lowerhex operation-manifest identifier. It is **not**
an in-probe target binary hash verifier or an authenticity token. Before launch,
the separately named operator must verify the actual binary hash/size, immutable
custody/file/reparse/alias identity, dependency/import/forwarder inventory and
parent ownership prerequisites. Syntax alone cannot authorize loading. No load is
released until those checks are independently accepted; a prior pathname hash or
an open file handle alone does not establish mapped-byte identity. Wrong actual
hash/custody must be refused by that operator before launching the probe.

Native bootstrap control flow retains static module, pin outputs, symbols, typed
bindings and every ID/slot/request/result/snapshot/descriptor exporter:

1. LoadLibraryExW once from the exact supplied path with explicit
   DLL_LOAD_DIR|SYSTEM32 dependency search flags. No fallback or reload.
2. Resolve descriptor by its exact name; FROM_ADDRESS|PIN must succeed and yield
   the original HMODULE. Then resolve/pin the other three symbols and require the
   same containing module for each. No target export runs before these checks.
3. Copy fixed MSVC-x64 function-pointer representations into independently declared
   __cdecl int32-return bindings. Descriptor takes uint32 byte count; init takes
   uint64 capacity. Width assertions and memcpy avoid cast/aliasing diagnostics;
   this is explicitly platform-specific source, not a portable pointer guarantee.
4. Call descriptor into568-byte8-aligned backing, check return status before bytes,
   then compare all142 little-endian words with a separately literal fixture. The
   fixture is not generated from returned data, OF_INERT_FIELDS or sizeof expressions.
5. Only then execute minimal fake init/snapshot, JOB, identical request replay,
   ACTIVE0, CLOSE and final snapshot through dynamically bound exports. Assert
   exact sequence/class/count/lifecycle progress, replay without another record,
   nonzero retained CLOSED job value, other resources ABSENT and no process/attrs.
6. Emit one bounded ASCII result line with operation/generation/receipt, numerical
   stage/error/status, pass flag and optional raw descriptor hex; normal exit0 is
   required too. Missing/partial output or output failure cannot establish success.

Only the probe's own loader/pin/symbol/error-report APIs are real; slot ownership
methods in the reviewed DLL are C fakes. No process launch/JobObject/real handles
are requested through the target. HMODULE and executable pointers never appear in
result output or cross a process boundary.

There is no FreeLibrary path, Python callback or custom DllMain. Original module
reference and all pins remain in static C state through failure and process exit.
PIN's documented guarantee starts on success; before that, initial-reference
retention relies on this supported single-thread/no-foreign-unload native flow.
Pinning a foreign forwarded symbol rejects it after retaining that pin; no such
artifact should pass the operator's prior forwarder inventory. Failures never imply
no dependency initialization occurred. Search flags do not prove dependency trust.

This avoids the particular Python return-publication boundary for this native
disposable probe only. A rooted Python attempt still cannot own an unpublished
HMODULE. The probe is not slot_artifact's real loader, a ctypes invocation test,
slot_client Backend/Invocation or policy bridge. Another Python-loaded bootstrap DLL
would need its own prior native lifetime ownership. A later already-owned native
host/bootstrap and explicit typed Python source allocation remain unresolved gates.

Supported interruption is cooperative operation-level settlement or termination
of the exact owned disposable process by its separately assigned operator. This
source has no watchdog, subprocess runner, thread kill, cancellation injection or
claim of a hard native completion deadline. Parent process/start-publication
ownership and physical completion wait must be independently established before
execution. START_UNKNOWN forbids replacement; PID/name discovery creates no new
authority. Native faults, foreign memory/handle mutation, process death and arbitrary
instruction/thread interruption are not recovery guarantees. No PASS is accepted
without complete matching-nonce output plus independently observed exit0.

Next evidence gates: independent source review; distinct reviewed exact probe
build/import/hash evidence; accepted inert target build/export/dependency receipt;
immutable custody and parent ownership; separate exact load release. Only then can
runtime assertions, actual descriptor and dynamic C calling behavior be reported.
Old C executable/private-TU harness and Python fake tests are not repeated or
substituted for that proof. Raw descriptor output can later be checked by an
offline Python parser without importing any DLL.

Real Win32 ownership/error/return interruption/descendants/crash/timing, typed Python
binding/lifetime/projection/policy closure, IPC/journal/clock/current authority/
capability/one-use provider return, enrollment/credentials/live provider and whole
Phase1 remain open. No source preparation resets deadlines/credits/failure latches.

## Compiled probe evidence

A separate bounded build of the frozen probe source completed successfully with CMake4.4.2, Visual Studio2022 x64, MSVC14.44.35207 (compiler19.44.35227.0), SDK10.0.26100.0, C11, /W4 /WX /MT and compiler/linker CFG. Configure, standalone Release build and static dumpbin inspection each exited0 without timeout or retry. All five source/header/proof input hashes stayed unchanged across the three operations.

Actual compile/link tracking records show one probe translation unit/object plus standard Windows SDK libraries. Neither the target DLL import library nor its core/export-wrapper implementation was linked. Static inspection reports a PE32+ x64 executable with CFG, no exports and KERNEL32.dll as its only imported DLL. Loader/pin/symbol and CRT/system support imports are retained; this inventory alone makes no claim about runtime behavior or dependency custody.

The executable is141824bytes, SHA25663607a2447b8d2811bc7fa3e06d4ccb82a9e5a137fab130697fcaf51484acffb. All three operation roots exited and were observed absent afterward; no independent descendant-emptiness claim is made. Private output/toolchain/command evidence and the binary are retained outside public source. No previous ABI tests were repeated.

The probe has NEVER been executed, including with invalid arguments. All dynamic assertions, target DLL loading and pinning, cross-DLL descriptor/call behavior, custody and parent ownership remain unverified. This compiled/static preparation does not close Python publication, native client/policy/provider or phase acceptance. Independent review of this evidence is required before delivery acceptance, and a separate operation release is required before execution.
