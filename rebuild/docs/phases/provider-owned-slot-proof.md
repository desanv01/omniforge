# Caller-owned C slot: source-only artifact

This five-file slice implements a versioned Windows-x64 C resource ledger and an
inert C harness source. **No compiler, CMake, harness, DLL or native call has run.**
There is no real Win32 binding table or Python loader/adapter. Existing Python native
factories and policy/wrapper files remain unchanged and unavailable.

The caller allocates zeroed, aligned storage and strongly registers its exact
identity before initialization or acquisition. Initialization is idempotent for the
same identity/table and rejects a changed identity/table or dirty storage without
resetting the retained ledger. The caller must pin the slot, immutable C table,
associated DLL and inputs until no action/resource is retained. No destructor or
garbage-collection shortcut is provided.

A nonblocking MSVC interlocked compare-exchange guard serializes mutations AND
snapshot copying; interlocked exchange publishes before releasing the guard. A busy
snapshot returns before reading mutable state or touching its output. The C fake job
callback includes reentrant mutation/snapshot/init attempts intended to verify that
behavior in a later executable run. No claim of executed synchronization proof yet.

Actions have identity, exact sequence/kind/index/parameter and process-input binding.
The first process request's canonical launch values remain fixed even if its action
fails. Repeated same sequence returns recorded history, without another API call;
changed request is rejected. Every fresh attempt, including failed/invalid actions,
uses one of96 permanent records. Zero, UINT64_MAX, skipped/stale or excess sequences
are refused; records are never overwritten. Finite history is an explicit supported
limit: exhaustion prevents new operations, including cleanup, and requires retained
ownership/cleanup_unconfirmed. Later runtime integration must admit a bounded action
budget or separately reviewed cleanup reservation; it cannot pretend exhaustion frees
resources or reuse the slot. This slice has no unbounded runtime query loop.

Each C action records acquisition/initialization/once-destructive outcome before
return. C holds job, standard and PROCESS_INFORMATION outputs independently of Python
projection. Inline job/standard arrays and an aligned65536-byte attribute arena stay
in the slot; duplicate updates cannot replace referenced values. Larger attribute
requirements fail closed. Static assertions bound slot size to131072 bytes, alignment,
HANDLE/WCHAR/DWORD widths; these capacities are supported limits, not Windows guarantees.

The action table supports only selected job limits, three fixed NUL handles, fixed
suspended job-assigned dummy creation, exact membership/resume/termination and
root/job/exit/disposal observations. Process creation resets prior empty-job/root
observations. Failures stop further normal work while retaining cleanup/query actions.
Failed close remains unresolved and cannot be retried with a new sequence; exact
replay only reports its previous failure. Independent disposal remains allowed.
Raw partial outputs, contradictions and observation/disposal uncertainty do not become
successful closure. The slot itself never emits provider success or closed(owner).

The C harness uses native C fake functions, fake handle values and explicit counters,
not Python callbacks or real OS acquisition functions. Its six top-level scenario
functions contain checks for lost returned status, replay/request/identity/reset,
capacity/alignment/dirty storage, overflow/stale/full refusal, reentrant busy snapshot,
normal/one-sided/two-sided failed process outputs, process-parameter mismatch,
attribute-array retention through deletion after success/failure, failed/oversized
initialization and cleanup/close failure/replay. **These are source assertions,
not passed tests.** Compilation, warnings, API-shape compatibility and assertion
correctness remain unverified until an explicit inert-build/harness release.

CMake describes only an inert executable with source-relative paths. It requires
MSVC Windows x64, VS2022 v143 toolset14.44 and SDK10.0.26100.0, C11 and warnings as
errors, refusing silent toolchain substitution. No DLL, real table, install or runtime
target exists. Build configuration has not been invoked. Existing toolchain path
inventory is not proof that configure/compile/link succeeds.

This C boundary is intended to preserve a resource if Python is interrupted after
the C action returns. It neither masks arbitrary native faults nor proves physical
cleanup deadlines. Supported model excludes thread termination, access violation,
corrupted/unpinned pointers, table/input mutation, foreign handle changes and DLL
unload/process death while records exist. No SEH recovery is implemented. A stalled
native call keeps the guard/inputs/slot retained and snapshots busy; no mathematical
real-time guarantee is inferred.

Next gates: independent source review; separately released exact-toolchain compile+
inert harness with bounded correction evidence; independent executable/ABI review;
then separately owned Python snapshot/projection/closure reconciliation. Existing
JobOwner cannot consume this authoritative slot without that adapter. Native slot
resources/unknown actions must prevent Python closed/no-acquisition claims even when
Python sinks have not been projected. No mixed direct-wrapper and slot-owned closes.
Default factory enablement and real dummy-process/native return-interruption/closure
proof require a later exact runtime release and independently reviewed artifact.

Current original work/cleanup/settlement deadlines and delayed-settlement rejection
are unchanged; the C slot does not calculate time extensions, cross-clock bounds,
journal/capability authority, IPC, credentials/provider or actual-return delivery.
Process exit does not prove SQL COMMIT abortion. No whole-provider/Phase1 acceptance.

## V2 F1 correction: partition normal history from cleanup

This addendum supersedes V1's global-exhaustion cleanup limitation above; original
V1 source/evidence remains in its immutable packet. Independent review identified
that valid normal queries followed by a last-record process could prevent even the
first termination/delete/observation/close. V2 reserves32 of96 permanent records
independently before any acquisition. At most64 records are normal work/history.

Cleanup admission is partitioned further: one termination, one attribute deletion,
six independent handle closes, eight WAIT observations, eight ACTIVE observations
and one EXIT observation. Thus at most25 reserved records are consumed;7 remain
unused, not available to normal callers. Static assertions bound the combined pools.
No query can consume a destructive-action credit or another observation class's
credits. Duplicate/invalid cleanup attempts are refused before record allocation.
Exact prior-sequence replay still returns its original result without a new action.

Final observation credits become available after termination enters irreversible
cleanup, or after normal exhaustion when no process is possible. When a process
exists, ordinary queries cannot burn final polling credits before termination;
at64 normal records they refuse with OF_FULL and no native entry. Process admission
cannot take reserved history. Termination blocks further normal work. Attribute
deletion/standard closes during a normal successful lifecycle may use their dedicated
once credit; they are already completed rather than needing another cleanup attempt.

The retained finite observation limits do not guarantee a native process will signal
or a job will reachzero. If still active/unknown after the admitted polls, preserve
uncertainty within the original absolute cutoff; no extra grace or destructive retry.
The guarantee is admission of required cleanup attempts independent of normal history,
not guaranteed OS settlement or an unbounded query loop.

Harness source now includes eight top-level scenario functions. The updated simple
job exhaustion case admits a final active-count observation and close. A new case
fills normal history to63, acquires process/thread as record64, refuses ordinary
queries, then admits termination/delete/root+job+exit observations and all six close
attempts. Its second variant checks failed close replay/no retry and independent
remaining disposal. Another case exhausts eight root and eight job polls, refuses
further polls without native entry and still admits exit/delete/all closes after
the last admitted observations confirm closure. These are NOT executed test results.

V2 remains source-only: no compiler/CMake/harness/import/native operation ran.
Current deadline policy and all accepted Python files/defaults are unchanged.

## V3 bounded build-selection guard correction

The first authorized configure failed at the V2 minor-toolset guard before project
generation/build. CMake4.4.2 identified the requested14.44.35207 compiler/linker paths,
but its optional minor props-file version did not satisfy the source regex. The
compiler-derived MSVC_TOOLSET_VERSION143 is distinct from that optional reporting.
No harness scenario ran; the original failed output remains preserved privately.

V3 CMake retains Windows/MSVC/x64/compiler143, exact Visual Studio17 2022 generator,
platformv143 and requested `v143,version=14.44.35207`. It requires a new explicit
OF_EXPECTED_VS_INSTANCE absolute cache parameter and matching explicit generator
instance; both resolve to the approved VS2022 BuildTools instance. The source has no
personal-machine absolute path or ambient fallback. It normalizes Windows case/path
representation and requires actual selected cl.exe, C compiler linker and CMAKE_LINKER
to equal that instance's exact VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64 locations.
Requested and selected SDK must both be10.0.26100.0. Optional minor-version reporting
is no longer used as the exact pin. /W4 /WX, static assertions, inert-only target,
all C slot/harness source and native-unavailable Python defaults are unchanged.

This is a source correction only. No new configure/build/test/native operation has
run. Main's next reviewed command must explicitly supply OF_EXPECTED_VS_INSTANCE
alongside CMAKE_GENERATOR_INSTANCE; no value is discovered or defaulted by the project.
Independent delta review and a fresh bounded build window remain required.

## V4 bounded compiler-warning source correction

The V3 reviewed guard configured successfully with exact pinned selections. Its
Release /W4 /WX build then stopped on C4324 explicit-alignment padding in OF_SLOT
and C4389 at the harness's expected-life enum ternary comparison. No harness ran;
full V2/V3 failure evidence remains preserved privately.

V4 removes redundant explicit align specifiers from OF_SLOT/arena, using the natural
x64 HANDLE/uint64_t alignment and an explicit uint32_t field for the former four-byte
pre-arena padding. Existing compile-time assertions still require slot alignment8,
arena offset divisible by8, HANDLE/WCHAR/DWORD widths and total capacity. No packing,
warning suppression or weakened bound. The comparison casts its nonnegative expected
life enum to the stored uint32_t type; the expected state/branch/test remains the same.

Release checks are custom CHECK macros calling fprintf/abort on failure; they do not
use assert or depend on NDEBUG. Inspection confirms /DNDEBUG does not remove those
checks or side-effecting action calls. A comment makes that intent explicit. No
harness/policy action or deadline behavior, C implementation, CMake /W4 /WX or static
assertion was changed. This is source-only; no configure/compiler/test rerun occurred.
Independent delta and fresh bounded verification remain required.

## V4 final inert build evidence

After independent V4 source review, a fresh bounded verification window completed:

* CMake4.4.2 configured successfully, exit0, with Visual Studio17 2022 generator,
  x64, platformv143, selected MSVC toolset14.44.35207 and Windows SDK10.0.26100.0.
  Generated metadata confirmed the explicitly approved instance and exact selected
  compiler/linker locations before build. Compiler reported19.44.35227.0;
  MSBuild reported17.14.40+3e7442088.
* One Release build succeeded, exit0, **zero warnings and zero errors**, with /W4
  /WX /std:c11 /MT /guard:cf and existing width/alignment/capacity static assertions.
  Release NDEBUG did not remove the custom always-active CHECK macro or action calls.
* One CTest invocation ran the inert executable once, exit0: **1/1 test passed in
  0.03seconds**, total CTest time0.06seconds. Its final summary reported
  `owned_slot inert scenarios passed (C fake table only)`.

All eight scenario functions completed: lost-return replay/identity;
capacity/alignment/stale refusal; reentrant snapshot; partial process/parameter replay;
attribute retention/failed initialization; cleanup/no unchanged close retry;
normal exhaustion without cleanup starvation; bounded final polling with close credits.
These completion outcomes follow the exact sequential main calls, always-active
checks and final successful summary. They are not eight separate CTest tests,
processes or individually timestamped outcomes.

This updates the earlier source-only and failed-attempt status for V4. The historical
V2 configure failure and V3 warning-as-error build failure above remain part of the
evidence; they were preserved and corrected through separate reviewed source changes,
without disabling warnings, checks or bounds. V4 inputs remained frozen during the
successful run. Configure, build and test processes completed within their respective
120/120/20second bounds without timeout; no repeat of an unchanged failed input.

The executable exercised the actual C slot through injected C fake Win32 functions
and fake handle values. This establishes inert implementation/build evidence, not
real Job Object/process-tree/NUL/attribute acquisition, Python-return interruption,
native error/calling-convention behavior or physical cleanup deadlines. Standard
executable/CRT startup uses OS facilities; no real ownership API table was supplied.

Native defaults remain unavailable. Independently reviewed DLL/bindings, caller
pinning and Python projection/closure reconciliation, actual dummy descendants/
owner-crash/return-interruption proof, IPC completion, journal/cross-clock/current
authority/capability and one-use actual return remain separate open gates. No real
credential/enrollment/provider or whole-Phase1 acceptance follows from this result.
