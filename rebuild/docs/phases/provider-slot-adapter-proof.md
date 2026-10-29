# Injected Python slot client

This three-file slice supplies a model-only ownership/action channel over explicitly
injected init/apply/snapshot functions. It does not load or locate a DLL, construct
foreign callbacks/prototypes, enable native defaults or integrate JobOwner/Supervisor.
Without a backend construction raises NativeUnavailable. An injected artifact lease
is only a lifetime object, not artifact provenance or operation permission.

A module-rooted invocation registry strongly retains each unresolved role's opaque
aligned slot exporter, exact token/UUID identity, backend/lease and immutable pending
request/result/UTF-16/snapshot backing. This is independent of disposable caller
references and GC cycles. Explicit release requires known terminal native-resource
disposition; local interruption/failure is retained as failure, never delivery success.
Only the test harness removes unresolved fake roots during fixture teardown; production
has no force-release or GC finalizer.

The fixed model descriptor checks exact field sets/types, capacities/budgets/enums,
little-endian Windows-width thin sizes/offsets and calling-convention label. The
large C slot stays opaque. Thin strings are bounded UTF-16LE, copied before entry;
UUIDs use opaque .bytes consistently, and invocation integer generation stays distinct
from each role UUID. Memory ranges are owned, checked for overlap and pinned before
backend calls. Descriptor/model acceptance is NOT compiled Windows ABI validation.

Return codes are checked separately from output buffers. BUSY/refused output can be
untouched/old and is not interpreted as success. One pending request captures its
original sequence/kind/index/parameter/input; snapshot identity/count/class/lifecycle
progress must be the one expected transition. Unknown original return can perform
at most one identical history lookup requiring replay=1, never a new acquisition.
Definitively unrecorded work is not executed automatically; a later cleanup command
may use the still-unconsumed C sequence under a distinct local command identity.
If history itself loses its return, no unchanged lookup retry is issued.

Interrupted projection keeps all original records/buffers rooted, including partial
native resources. Reconciliation recovers ownership only; permanent invocation and
per-role failure latches prevent normal-work revival, including settlement after
its own interruption. Init/apply/snapshot entry is serialized for each session;
reentrant calls cannot start new work or read a closed state during entry.

Closure uses C lifecycle states, not zero numeric handles: the C ledger keeps values
after OF_CLOSED. Failed close remains unresolved; the client rejects another close
on a closed/failed entry. Pending/BUSY/unknown actions, unresolved attributes or
resources, snapshot uncertainty or missing process/root/job evidence block release.
No-acquisition requires known initialized idle history, not missing Python projection.
Original work/cleanup/settlement cutoffs and delayed-settlement rejection remain;
normal credit exhaustion preserves the accepted C cleanup-phase count mapping.

Focused command with the existing pinned Python, from source root:

```text
python -B -m unittest discover -s tests/contracts/providers -p test_slot_client.py -v
```

Final actual run: **22 tests passed in0.250seconds, exit0**. Initial19 tests passed
in0.336seconds before additional serialization/settlement-stop/history-followup cases
and related source tightening. No failed execution occurred. No accepted C build or
old Python suite was repeated; this change adds new files only.

Fakes mutate the actual client's owned model buffers but retain only copied
bytes/addresses/values, preventing fake argument retention from masking GC ownership.
Coverage includes root/exporter/backend/lease lifetime after caller-reference drop,
explicit post-closure collection, exact UUID/ABI/type/field/offset/enum validation,
overlap/bounded strings, lifecycle closure with nonzero closed handle, lost return/
one history lookup, unrecorded refusal/no retry, stale closed BUSY bytes, unexpected
identity/progress/class/resource mutation, partial projection/GC, init-return loss
without reinit, failed history/no retry, close failure, original deadlines, bounded
BUSY recovery, normal capacity and settlement delay/local-failure cases. A test patches
DLL/prototype constructors to fail if invoked. These are Python model tests, not C
ABI, actual Win32, real concurrency or asynchronous signal-delivery evidence.

Supported client use is a single serialized invocation owner with trusted injected
callbacks and immutable registered memory/table/inputs. Native faults, unsafe thread
termination, foreign handle/input mutation, unpinned storage, DLL unload and process
death are not recoverable guarantees. No GIL/finally/errcheck claim is made. A stalled
backend or exhausted original cutoff retains unresolved ownership; no forced unlock,
reset, role replacement or time extension is provided.

Actual exported-ABI comparison, inert DLL build/load identity and lifetime, loader-
return interruption, real table/native process/descendant/crash/timing evidence,
Python policy closure integration, IPC/clock/journal/current authority/capability and
one-use actual return remain separately reviewed releases. No DB/credential/provider/
enrollment operation or whole-Phase1 readiness follows from this ownership client.

## V2 recorded INVALID correction

Independent source review F1 identified that accepted C INVALID has two forms:
admission refusal without a record, and a completed execute-guard failure with a
new record (for example repeating LIMIT_SET). V2 separates statuses impossible for
a recorded action (BUSY/STALE/FULL) from dual-form INVALID. Zero progress still
requires exact unchanged refusal state. One-record progress can finalize INVALID
only when returned result, last snapshot, counts/class and lifecycles are coherent.
It remains a permanent failure; resolution of pending enables cleanup, not work.

The model now faithfully records INVALID for repeated LIMIT_SET without another
limit-setting effect. Five new focused tests passed in0.010seconds, exit0: returned
recorded INVALID with cleanup, lost-return exact replay without effect, unrecorded
INVALID/no advance/no retry, incoherent result rejection and impossible recorded
BUSY rejection. Final full client run: **27 tests passed in0.250seconds, exit0**,
including all original22 cases. No failed execution or native operation. Original
22-test evidence above remains history; no C rebuild or old suite was repeated.
All unavailable native/artifact/policy-integration limits remain unchanged.
