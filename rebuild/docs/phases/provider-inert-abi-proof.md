# Inert DLL export source and injected artifact admission

This seven-path slice is source/fake preparation. The accepted C ledger and injected
slot client remain unchanged. No C compilation, DLL build/load, native binding or
actual process/JobObject/file/attribute ownership operation has been performed for
this slice. Existing native defaults remain unavailable.

The optional CMake `OF_BUILD_INERT_DLL` switch defaults OFF. Explicit future builds
can produce `owned_slot_inert_exports` and `owned_slot_export_harness`, preserving
the accepted executable target and reviewed MSVC/x64/C11/SDK/warnings-as-errors pins.
The new harness includes the wrapper translation unit so it can inspect the private
guard without introducing public test exports. Its assertions are source only,
not passing compiled evidence.

Four versioned C data-buffer exports are declared: descriptor, init, apply and
snapshot. Init receives no API table; all ownership methods come from one internal
static const C-fake table. No external function pointers, Python callbacks, real
ownership table, DllMain or module-load ownership acquisition is provided. A
nonblocking wrapper-wide guard protects a current-call stack context; reentry and
cross-slot contention return BUSY without replacing it or touching output. The
context is cleared before releasing the guard. Per-slot persistent history stays
in the unchanged core. Fake numeric handles are distinct within a slot and may be
equal across slots; they never identify OS resources or imply shared authority.

Descriptor wire schema v1 is fixed at **142 little-endian uint32 words /568 bytes**:
six header words `(0x4942464F, 1, 568, 142, 6, 136)`, then136 payload words in the
exact `OF_INERT_FIELDS` header order. There is no bootstrap C-struct parsing or
returned pointer. Wrong output size/alignment fails without writing. C layout
entries use sizeof/alignof/offsetof; Python expectations and test fixture are
independent fixed declarations. Payload covers scalar widths/alignments/signedness,
calling convention, all thin-field offsets, arrays, UUID.bytes convention, UTF-16LE,
enums, opaque storage, arena, flags and finite credits. Unknown/trailing/truncated/
wrong-endian metadata is rejected rather than used to synthesize declarations.

Independent opaque-layout calculation under the fixed MSVC-x64 contract:

| Region | Offset/end |
|---|---|
| guard/version/magic,36-byte ID, alignment to API pointer | API56, end64 |
| sequence/counters/cleanup buckets/uncertainty | handles144 |
| six handles and three six-u32 arrays | end264 |
| once/state fields, aligned launch sequence, attribute/observation state | SIZE_T336 |
| attribute size/job/standard arrays and PROCESS_INFORMATION | launch400 |
|4100-byte launch | end4500 |
|4096-WCHAR command | end12692 |
|1024-WCHAR environment | end14740 |
| explicit four-byte padding | arena14744 |
|65536-byte arena | records80280 |
|96 records of64 bytes | slot86424, alignment8 |

These are source expectations guarded by new static assertions, not measurements
from an actual DLL. Thin source expectations remain ID36/4, launch4100/4,
request32/8, result32/8 and snapshot184/8. C callbacks use WINAPI; exports explicitly
use __cdecl with int32 return status and checked uint64 capacity. Actual export names,
calling convention/prototypes and executable ABI require future build/load evidence.
Launch buffers must be bounded, zero-padded valid UTF-16 with no controls/unpaired
surrogates. Typed buffers must be correctly aligned, owned, immutable while entered
and disjoint; arbitrary invalid/unmapped pointers and foreign mutation are unsupported.

Artifact admission has no real loader, lookup or prototype construction. A trusted
Main-reviewed receipt supplies exact source/binary/toolchain/configuration/target,
dependency closure and immutable-storage custody assertions. These are explicit
trust inputs, not an authenticity check implemented by this module. Path syntax
rejects relative/noncanonical/traversal/stream/device/trailing-dot aliases; no claim
of resolving filesystem aliases, reparse points, case-sensitive-volume identity or
replacement races follows. Actual custody and dependency identity must be established
before any future load. Hash-before-load and post-load descriptor checking do not
solve TOCTOU or make arbitrary native code safe.

A process-lifetime root retains the lease before the trusted injected loader enters.
The returned module/export objects are pinned before validation; rejected returns
are pinned too. Descriptor output backing remains rooted. Validation invokes only
the descriptor fake, never init/apply/snapshot. There is no release/unload/reload API;
same case-insensitive selected path is denied even with changed hashes. Rooted
metadata/lease is returned, never a slot Backend or Invocation. The existing strict
model_only client descriptor is not relabeled or bypassed.

Loader exceptions conservatively record `load_unknown`: the attempt and inputs are
retained, but an unpublished module object is not magically recovered. Fake tests
explicitly demonstrate that gap. Descriptor exceptions after module publication
leave `rejected_pinned`. No automatic retry, unload, reconstruction by module name,
false closure or slot admission follows. Process-lifetime rooting after a successful
Python publication does not settle interruption during the real loader return.

Focused fake verification uses the existing pinned Python with `-B`:

```text
python -B -m unittest discover -s tests/contracts/providers -p test_slot_artifact.py -v
```

Initial actual result: **15 tests passed in0.145seconds, exit0**, before subsequent
path-alias rejection and corresponding focused test additions. No failed run.
Final actual result after path-alias tightening: **15 tests passed in0.158seconds,
exit0**. No failed execution. Tests cover all142
descriptor words individually (including header), strict sizes/types/endian,
receipt rejection before loader entry, exact returned provenance, invalid export
contracts, status separate from output, before/after-return exceptions, root/GC
retention, no duplicate load and no native constructor/slot calls. Independent weak
references ensure fakes do not mask module/export lifetime. Test-only fake teardown
clears roots; no such production release exists.

The new C harness source covers fixed descriptor values, wrong-size/null/alignment,
overlap/identity/refusal, private wrapper guard and core-slot BUSY untouched output,
two-slot fake isolation, recorded INVALID/exact replay versus unrecorded cleanup
refusal, malformed UTF-16, full fake launch/observations/disposal and nonzero CLOSED
values. None has executed. Existing accepted C executable/client tests were not repeated.

Next gates remain: independent source review; explicitly owned exact DLL/harness build
with frozen sources/toolchain and actual child statuses; import/export/hash/dependency
review; separate exact load window and bootstrap-lifetime solution; separately owned
typed client binding/pinning/projection/policy integration. Real native ownership,
return interruption/cancellation, descendants/crash/error/timing, IPC/journal/clock
transfer/fresh authority/capability/one-use actual return, credentials/enrollment/live
provider and whole Phase1 remain open. Native faults, unsafe thread kill, foreign
memory/handle mutation, module unload in use and process death are not recovery
guarantees. Original64/32 credits, finite observations, deadlines and permanent
failure latches are preserved in the unchanged core/client.

## V2 synchronized reservation correction

Independent source review F1 identified a race between the original root-membership
check and insertion: overlapping callers could both load and one could replace the
other's process-lifetime root. The original15-test results above remain historical
sequential fake evidence; they did not establish overlapping admission safety.

V2 allocates a candidate lease before locking, then uses one reservation lock only
for the indivisible casefolded-key check/insertion. Existing selected/loading/
rejected_pinned/load_unknown/pinned_validated roots cannot be overwritten. The lock
is released before any injected loader or descriptor callback, so same-key reentry
refuses without replacing the root. No candidate construction is performed under
the reservation lock. This synchronizes Python admission; it does not solve real
loader-return publication or prove module identity/lifetime at a native boundary.

Actual focused new reservation checks: **2 tests passed in0.063seconds, exit0**.
Final updated artifact file: **18 tests passed in0.470seconds, exit0**. No failed
execution. The aggregate was justified by the changed Python admission and three
new methods; no old client or C build/test suite was repeated.

The overlapping regression synchronizes two candidate constructions before either
reservation, holds the winning fake loader entered and requires loser refusal
while it is still held. It asserts exactly one loader entry, unchanged winner root,
and winner module/export retention after caller references drop. Fakes retain only
weak references to generated objects; test-only root clearing then permits their
collection. Both created test threads use finite barriers/events and are joined in
a finally block. A separate case refuses synchronous same-key reentry in both
loader and descriptor callbacks. Another checks every permanent root state with
changed-hash input and no loader call. These remain Python fake-thread evidence,
not native acquisition, DLL loading or asynchronous publication guarantees.

## First compiled window and C4127 source correction

The separately authorized first build configured successfully and compiled/linked
the inert DLL target. Its aggregate Release build then stopped in the new harness
at the constant-condition `CHECK(OF_D_COUNT ==136 && OF_INERT_BYTES ==568)`:
MSVC warning C4127 became error C2220 under /WX. Configure child exited0 in13.25s;
build child exited1 in8.75s, both within their120s bounds and without timeout. These
are actual failed-build results, not a successful harness or accepted DLL artifact.
The partial DLL is retained with the failed operation; no new harness executable,
CTest run, export/import inspection or DLL loading occurred. The old accepted
executable was not built or run.

The bounded source correction replaces only that invariant runtime CHECK with an
equivalent C11 `_Static_assert`, preserving both136 payload fields and568 bytes.
All runtime descriptor checks, fake-flow behavior, /W4 /WX and build targets remain
unchanged. No warning is disabled and the always-active CHECK macro is unchanged.
This correction has not been compiled or tested; warning removal and harness
execution require independent source review and a fresh separately owned build.
Prior Python15/18-test results and the original failed build remain preserved;
no unchanged Python suite was rerun for this C-only invariant correction.

## Corrected compiled fake proof

The constant descriptor invariant was moved to an equivalent C11 static assertion without changing either required value or suppressing compiler warnings. The original failed harness build remains part of the evidence history. A fresh, independently bounded build of the corrected frozen source configured and built both new targets successfully under CMake4.4.2, VS2022 x64, MSVC14.44.35207 (compiler19.44.35227.0), SDK10.0.26100.0, C11, Release /MT, /W4 /WX and compiler CFG.

Exactly one newly selected CTest passed: owned_slot_export_harness,0.05s (CTest total0.08s). Its four scenario functions cover descriptor checks, refusals/guards, isolation/replay/recorded INVALID and fake flow; final context/guard cleanup also passed. The harness directly includes the export translation unit. It does not load the DLL. The previously accepted standalone harness was not rebuilt or rerun. All ten frozen source/build input identities stayed unchanged across configure, build, test and static inspection.

Static dumpbin inspection reports a PE32+ x64 DLL with CFG characteristic and exactly four named exports: of_inert_descriptor_v1, of_inert_init_v1, of_inert_apply_v1 and of_inert_snapshot_v1. The only imported DLL is KERNEL32.dll. Its import list includes CRT/system support functions such as TerminateProcess, LoadLibraryExW, GetProcAddress, CreateFileW and CloseHandle; inspection alone does not establish attribution or prove that those functions are never called. No CreateProcessW or Job Object creation/assignment/termination imports were listed. This is static binary evidence, not execution of the DLL or dependency custody acceptance for a later load.

Artifact SHA256: DLL b5fb9813b17f9a59ba5e01d613d520797c52f01c8b066dd06d0e09f596700300 (118272bytes); fake harness283c52cbe6009040c2049985d0f8bfdfa730524ba63b9b79258082fa11643e5b (165888bytes). All four operation roots exited0 and were observed absent afterward; no timeout occurred and no descendant-enumeration claim is made. Binaries and private operating evidence are retained outside the public source repository.

Actual DLL loading, dynamic prototype calls, Python bootstrap/publication lifetime, compiled client binding, real Win32 ownership, policy/IPC/authority/provider execution and whole-phase acceptance remain unverified. The existing18 Python artifact fake tests remain the previously accepted result; they were not rerun for this C-only correction. Independent compiled/static evidence review is required before delivery acceptance.
