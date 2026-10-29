# Inert probe supervisor — source preparation only

Status: **UNCOMPILED, MODELS UNEXECUTED, CUSTODY AND PROBE UNEXECUTED**.
This four-file packet implements one ordinary C-only disposable probe supervisor.
Independent source review, separate exact build/model release, custody-only
preflight/review and Main's one positive operation release remain required.
No existing accepted probe, DLL, client, shared CMake or dependency lock changes.

The standalone CMake has two targets: `inert_probe_supervisor` and
`inert_probe_supervisor_model`. It pins VS2022/x64/v14314.44.35207,
SDK10.0.26100.0 and explicit matching BuildTools/compiler/linker paths; C11,
/W4 /WX, static CRT and compile/link CFG remain enabled. It registers no CTest,
post-build run or custom execution. The model includes the production state
machine with SP_MODEL; the complete native adapter and wmain are preprocessor
excluded, with no target/probe import library or loader entrypoint. No runtime
API table or generic launcher is exposed. Actual warnings/imports/linkage are
unverified until the separately released build.

## Exact file and protocol contracts

The native executable accepts exactly `--manifest <absolute ASCII path>`.
Paths are bounded below240characters, uppercase drive-letter absolute local
paths; no quotes, device/reserved components, stream syntax, dot/trailing-dot/
trailing-space/tilde aliases or UNC forms. Runtime checks require fixed local
drives, no reparse ancestors and canonical handle paths/file IDs. Capsule,
control and evidence must be sibling directories with those exact leaf names.
The probe application/target/supervisor basenames are fixed in source. Only the
operator-approved manifest can select a capsule; it cannot select another
application, argument vector, job policy or arbitrary environment.

Manifest is <=4096bytes, ASCII, LF only, no embedded NUL/duplicate/extra fields,
one final LF. Ordered schema:

```text
OF_PROBE_MANIFEST_V1
operation=<32 lowercase nonzero hex>
generation=<32 lowercase nonzero hex>
capsule=<absolute path ending in capsule>
control=<sibling control path>
evidence=<sibling evidence path>
systemroot=<installed Windows directory>
supervisor_sha256=<64 lowercase nonzero hex from accepted supervisor build>
supervisor_size=<canonical decimal,4096..524288>
probe_sha256=63607a2447b8d2811bc7fa3e06d4ccb82a9e5a137fab130697fcaf51484acffb
target_sha256=b5fb9813b17f9a59ba5e01d613d520797c52f01c8b066dd06d0e09f596700300
preflight_sha256=<accepted private custody/system/window evidence receipt hash>
trust=ordinary-local-window-v1
```

Probe size is fixed141824bytes and target size118272bytes. These are prior
compiled/static evidence anchors, never present custody proof. The SHA256 of
the complete manifest bytes is passed as the frozen probe's `--receipt`.
The preflight hash is an operator-reviewed evidence reference, not a signature,
permission granted by this program, or proof inferred from well-formed hex.
Main must verify it refers to independently accepted actual custody/system
evidence for these exact copies and the trusted immutable window. No fake
fixture, placeholder hash or declaration alone releases an operation.

READY is <=1024bytes with exact LF-terminated ordered fields:

```text
OF_PROBE_READY_V1
operation=<manifest value>
generation=<manifest value>
manifest=<manifest SHA256>
owner=<native BCryptGenRandom128-bit instance nonce>
expiry=<supervisor-owned GetTickCount64 absolute milliseconds, canonical decimal>
supervisor=<accepted binary SHA256>
preflight=<manifest receipt reference>
```

Permit and cancel are each <512bytes. Their exact ordered schema is their
respective `OF_PROBE_PERMIT_V1` or `OF_PROBE_CANCEL_V1` first line followed by
`operation`, `generation`, `manifest`, `owner`, `expiry` in that order, exactly
as READY, with one final LF and no other bytes. Main echoes expiry opaquely;
it must not compare a Python/tool clock against that native boot-relative
number. Nonces correlate an operation; the trusted control directory/window
provides authorization, not secrecy of stdout. Matching permit is consumed once
in native memory before CreateProcess. No reset, second create or repair of a
partial/foreign/stale/duplicate permit exists.

The operator creates files with create-new semantics and never overwrites a
record. READY is published only by the supervisor. Main publishes a complete
permit separately after READY/session validation and continued ACTIVE control;
the launch command must never auto-create one. The reader deliberately refuses
sharing conflicts/partial bytes rather than waiting for a writer to finish.
Prepare/flush/close the complete control record in a reserved staging file before
publishing it under the final absent name without replacement, or otherwise
prove the complete record is visible before its first read. This publication
detail must be accepted in the later exact operation instructions; no runtime
release or hard atomic-filesystem guarantee is inferred here. A malformed cancel
also stops/fails; an absent cancel is pending. Existing cancel never authorizes
another operation. Outer start ambiguity withholds permit and forbids replacement.

## Owned operation and clocks

One static C record roots resource states (NONE/ENTERED/OPEN/CLOSED/FAILED),
static PROCESS_INFORMATION, attribute bytes, job/standard-handle arrays, pipe
buffers, custody identities and control messages. Outputs of acquisitions land
in that existing storage. Numeric closed handles are retained and failed closes
are not retried. Failed CreateProcess outputs remain ENTERED/unusable, never
interpreted as acquired handles. Start possible/one create is latched before
entry, with START_UNKNOWN retained on failed/ambiguous creation.

The unnamed non-inheritable job sets and reads back both exact flags
KILL_ON_JOB_CLOSE|ACTIVE_PROCESS and ActiveProcessLimit=1. No breakaway is set.
Only NUL input and the two pipe write handles are inheritable; creation carries
that exact HANDLE_LIST and JOB_LIST. Arrays persist through attribute deletion.
Native CreateProcess uses the fixed full application path, fixed quoted arguments,
clean Unicode SystemRoot/WINDIR-only environment and evidence cwd, suspended,
no-window, extended-startup flags. Caller account privileges remain ambient;
this is not a restricted-token security sandbox. Parent copies of child pipe
write handles close after creation. Exact job membership precedes the sole
ResumeThread, which must return previous count1. Nested-job refusal fails closed.

GetTickCount64 is the sole clock, checked for backward movement and addition
overflow. Preflight10s includes native admission/setup. READY has30s from native
preparation completion. Work20s begins before CreateProcess; settlement10s starts
at first stop observation or the original work deadline, whichever is earlier.
Deadlines never refresh. Post-custody recheck/disposal also cannot produce a pass
after the original applicable cutoff. Native 100ms loop pauses bound responsive
checks, not OS scheduling or a blocked native/filesystem call. Sleep and kernel
stalls can exceed an operation budget; there is no hard real-time claim.

Stop/cancel/timeout/output/API failure latches nonpassing. It permits one exact
TerminateJobObject request, followed by root-handle signal, exit query and exact
job accounting. No PID/name reopen, taskkill, thread kill, console injection or
recursive supervisor is used. Root signal without job-empty, or job-empty without
root signal, cannot pass. Synchronous single-reader pipe reads are bounded by
PeekNamedPipe availability and <=256byte chunks; no pending wait/read handle is
closed. Child output must drain to EOF, or be explicitly failed, before disposal.
Close errors stay failed even if another cleanup succeeds. Attribute deletion is
the documented void API: source records normal return, not an invented status
code or arbitrary native-fault recovery guarantee.

On settlement timeout the state remains UNKNOWN, exact resources remain rooted,
and the native owner parks without another launch or automatic retry. Its tool
session must be retained. A separately directed safe-settlement action is still
needed; this packet supplies no recovery controller, and killing that parked
owner is outside supported cancellation. Supervisor death, unsafe thread kill,
memory corruption, hostile same-user/admin/system mutation, DLL injection,
machine shutdown and indefinite OS stalls are outside this ordinary positive
proof. Job kill-on-close is defense, not observed completion after observer loss.
An earlier uncertainty latch is never cleared for passing; if later observations
do establish physical settlement and all handles dispose, the owner may exit
failure rather than park with no resources. That cannot authorize replacement.

## Custody implementation and explicit external evidence

Native admission holds canonical non-reparse ancestors through the volume root,
the manifest and all three capsule files. Files use GENERIC_READ/READ_CONTROL
with FILE_SHARE_READ only; ancestors omit delete sharing. It queries volume/file
IDs, final long paths, directory/file state, no pending delete and file link count1.
No-write/delete sharing supplements the trusted immutable namespace/window; it
does not prove absence of prior writable mappings, directory child creation,
privileged mutation or that LoadLibrary maps a retained read handle.

Owner/DACL checks use bounded64KiB security storage and <=128ACEs. Trusted
mutation principals are the current user, SYSTEM, builtin Administrators and
TrustedInstaller. Null/unreadable DACL, untrusted effective write/delete-child/
ownership/DACL mutation or unsupported ACE kind refuses admission. Inherit-only
ACEs are not treated as current-object effective grants; every actual component
and copied binary is independently checked. ACL security bytes are fingerprinted
and rechecked through retained handles. This intentionally strict policy may
reject an actual machine layout; it must not be weakened or silently repaired.

Files have only the default data stream. Capsule enumeration is <=64entries
and admits exactly the three fixed files; control/evidence initially empty.
No `.local`, sidecar manifest, extra DLL, directory or reparse entry is admitted
in the capsule. Hash reads are bounded by expected size and a524288byte native
buffer. Minimal PE inspection checks x64/CFG, no delay/CLR imports, bounded import
names; probe/target must import only KERNEL32.dll and target must expose the four
exact named non-forwarded exports. Supervisor permits only KERNEL32/ADVAPI32/
bcrypt imports. Actual compiler-produced inventory still needs independent static
review before operation; the program does not establish embedded-manifest,
CRT behavioral or complete transitive system provenance by this minimal parser.

Installed SystemRoot/System32 paths are held and checked, but OS build,
KnownDLL/API-set/SxS configuration, system signatures and manifest/forwarder
inventory are part of the separately accepted private preflight receipt. The
program does not recursively scan Windows or measure a runtime module inventory.
All project writers must ACK the fresh capsule is immutable for the window;
trusted local account/admin/system, filesystem and unchanged installed Windows
image are explicit assumptions. Unknown configuration/dependency stops release.
No existing artifact ACL, source, credential or DB is modified.

Native initial evidence `custody.before.txt` and later `custody.after.txt` contain
bounded handle-index/volume/file-ID/ACL-hash/path rows (<=65536bytes). The latter
formats the retained identity fingerprints only after the post-run live recheck;
it is not a second reopening or independent system inventory. Originals and new
copies remain separately identified in the operator's preflight evidence.

## Exact result and source-only model matrix

Child stdout/stderr are individually<=4096bytes, total<=8192. Exactly one ASCII
OF_INERT_LOAD_V1 record must match all identities, stage12/error0/code0/pass1 and
exactly1136lowercase descriptor hex characters. One LF or CRLF terminator is
accepted; duplicate/trailing/partial lines are refused. All142words are compared
to a fixed independent literal supervisor fixture. Empty stderr, root signal,
exit0, successful zero-member accounting, unfailed recheck and disposal are
required. Fake target slot CLOSE is not native job/process settlement.

Raw child logs are create-new `child.stdout`/`child.stderr`. `final.txt` is
<=2048bytes: first line OF_PROBE_FINAL_V1; ordered fields operation, generation,
manifest, owner, expiry, state, first_failure, first_error, unknown, created,
root_signal, job_empty, exit_seen, exit, job_flags, job_limit, member, creates,
resumes, terminates, preflight_end, ready_end, work_end, settle_end, last_clock,
disposed, stdout_bytes, stderr_bytes, candidate. State is UNKNOWN/FAILED/SETTLED;
numbers use decimal. A candidate1 file cannot prove its own successful flush/close.
Final stdout confirmation OF_PROBE_CONFIRM_V1 carries operation/generation/
manifest/owner/pass/unknown; tool-observed supervisor exit0 plus matching final
confirmation and file are necessary. Missing outer observation remains UNKNOWN.

The compile-time model source invokes the same parsers, prepare/permit/launch/
observe/dispose/run functions. Scripted adapters model effects only; they do not
exercise the excluded native custody/PE/ACL/Win32 adapters. Named assertions cover
strict/extra manifest fields, path/decimal/time overflow, missing/partial/stale/
duplicate permit, pre/post-creation cancel, setup/partial acquisition, job flag
refusal, creation/member/resume failures, root/job disagreement, WAIT/query/close
failure, missing EOF/output overflow/malformed/trailing descriptor output,
settlement timeout with retained handles, whole-run missing-permit timeout and
whole-run positive synthetic bytes/physical-state flow. Assertions remain
**UNEXECUTED**, and literal inspection is not compilation or model PASS.

Documented contracts informing this source: [GetTickCount64](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-gettickcount64),
[creation-time job assignment](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812/),
[UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[FindFirstStreamW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirststreamw),
[GetKernelObjectSecurity](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getkernelobjectsecurity),
[BCryptHash](https://learn.microsoft.com/en-us/windows/win32/api/bcrypt/nf-bcrypt-bcrypthash),
[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject).

No compilation, model execution, custody preflight, child process, DLL load,
Python loader/client/policy, credential/provider or Phase1 completion is claimed.
Main retains the independent review and every subsequent operation release.

## Recorded compiled model and static evidence

The frozen four-file packet configured and built successfully under CMake4.4.2, Visual Studio2022 x64, exact MSVC14.44.35207 (compiler19.44.35227.0), SDK10.0.26100.0, C11, /W4 /WX, Release /MT and compiler/linker CFG. The two targets and their static inspections passed without timeout, warning suppression or retry. Four input identities matched before and after all five operations.

The model executable ran exactly once: exit0 in0.203s, empty stderr, reporting completion of schema/permit/acquisition/lifecycle/output source cases. Its five ordered groups exercise parsers, permit admission,11 injected acquisition-stage failures and partial cleanup, lifecycle/settlement failures and bounded output/whole-run paths. This is assertion-based injected model evidence, not real Win32 resource or physical-settlement proof. No accepted earlier tests were repeated.

Actual compile/link records show the model test translation unit includes the shared implementation under SP_MODEL, with native adapters and wmain excluded. It links only its model object and standard SDK libraries. Static inspection reports both binaries as PE32+ x64 with CFG and no exports. The model imports KERNEL32.dll only, without CreateProcess, Job Object or BCrypt APIs; static CRT support imports remain and do not establish runtime attribution. The native supervisor imports bcrypt.dll, ADVAPI32.dll and KERNEL32.dll as declared. No target/probe DLL implementation or import library is linked.

Artifact SHA256 identities: native supervisor119d162999e3ce136db37550826319cbc1dbd74e1a88306f67dda689e549b339 (187392bytes); model18adc20f0a756581127de80b92081840f8008afcbeaca8502826c8ce70c4da5f (169984bytes). Both hashes were unchanged after the model run. All five operation roots exited0 and were observed absent; no descendant-emptiness claim is made. Full private commands, diagnostics, tool hashes and generated metadata remain outside public source.

The real supervisor was NEVER executed, including invalid arguments. Real probe launch, custody preflight, READY/permit exchange, DLL loading and native ownership outcomes remain unexecuted. Independent review of this compiled/static/model evidence precedes delivery acceptance; custody/system-window review and a separate ordinary positive operation release remain required. No Python/client/policy/provider or whole-phase acceptance follows.

## Ancestor ACL precision successor — source preparation only

The earlier compiled/static/model section describes the earlier frozen packet.
Its native119d1629/187392byte and model18adc20f artifacts are historical evidence;
they do not implement or verify this changed source. **This successor delta is
UNCOMPILED, focused model assertions UNEXECUTED.** A new accepted exact native
binary hash/size and coordinated collector binding are required before any later
custody operation. No collector source, CMake, ABI, probe/DLL, client or lock is
changed by this native three-file packet.

This section supersedes the original all-directory mutation-predicate description
for the successor source only. The common pure predicate now distinguishes:

| Role | Directory/kind context | Conservative risk mask |
|---|---|---|
| EXISTING_CHAIN_DIRECTORY | Existing intermediate directory resolving an existing protected descendant, not a mutation/search endpoint |0x500D0152|
| STRICT_DIRECTORY | Immediate creation parent, operation root, capsule/control/evidence, immediate file parent, Windows/System32 endpoint or stronger retained role |0x500D0156|
| FILE | Manifest, binary or control file; directory role cannot be used |0x500D0156|

Only directory bit0x4 FILE_ADD_SUBDIRECTORY is removed from the first role's
predicate. File bit0x4 remains append-data risk. Directory0x2, DELETE_CHILD,
DELETE, WRITE_DAC, WRITE_OWNER, WRITE_EA, WRITE_ATTRIBUTES and generic ALL/WRITE
remain risks. No trustee SID, account, root or path whitelist is added. The
current-user/SYSTEM/Administrators/TrustedInstaller trusted set is unchanged.
Unknown role, role/kind mismatch or an endpoint requesting the chain role refuses
even with a read-only mask. Same directory can retain the stricter role.

This is a conservative ACL-admission predicate, not Windows effective-access
calculation or machine clearance. Ordinary allow/deny support and unsupported
object/callback/conditional ACE refusals remain. A deny does not cancel another
risky allow. Inherit-only ACE is not current-object effective access; OI/CI/
NO_PROPAGATE and effective inherited child ACEs are evaluated in each actual
object's context. An effective untrusted0x4 at a strict endpoint still refuses.
Owner/DACL validity and API metadata guards remain necessary before policy
authorization. The directory/file interpretation follows Microsoft's
[File Access Rights Constants](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)
and [ACE Inheritance Rules](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules).

`chain_endpoint` is common to production/model source. The actual traversal opens
existing components with the same sharing/reparse/identity checks; only internal
prefixes receive the chain role. The terminal directory or immediate parent of a
file is strict. Missing prefix aborts, never creates/adopts a substitute. All
required existing descendants must resolve before admission can reach READY or
new scope-output use; intermediate authorization is not standalone launch authority.

The common `authorize_path` stores role/kind/endpoint, original handle, immutable
path and pending/authorized/failed state. It never treats 'seen path' as sufficient
authorization. Every reuse goes through the same retained handle, native canonical
metadata and file-ID comparison and exact security-fingerprint comparison before
stronger ACE evaluation. Stronger role/endpoint is recorded before validation;
failure keeps it pending/failed, with irreversible operation failure. A weaker
later request cannot downgrade it, adopt a changed fingerprint, reopen/replace a
handle or recover failed authorization. Unknown cached role also refuses.

`revalidate_cached_directories` is common production/model code, iterating retained
strongest roles. Native prelaunch/post-run rechecks call it; existing manifest and
binary rechecks retain FILE. Native ACL parsing/hash/ID and actual filesystem APIs
remain outside SP_MODEL. That separation is explicit: injected metadata fixtures
exercise the real cache/state transition and predicate, not Windows API behavior.

Admission now has explicit manifest, operation-root and scope phases. The immediate
manifest parent is strict before parsing. After parsing, `operation_root_path`
derives the common capsule/control/evidence parent from the fixed sibling layout,
independent of manifest placement. It is strictly held/promoted and registered
before scope admission or READY. Both require the exact registered root path,
strict authorized state and open retained handle, with no failure latch. Original
10second preflight origin is unchanged, and interphase checks do not renew it.
The later job flags, exact inheritance, permit/clock/work/stop/output/physical
settlement machinery and its limits remain unchanged.

Custody rows retain the earlier ID/security/path fields and add strongest `role`,
`risk_mask`, `validations`, `authorized`, `pending` and `policy_failed`. Auxiliary
`ace_role`, `ace_index`, `ace_type`, `ace_flags`, `ace_mask` and `intersection` refer
to the last ACE actually evaluated in that entry, not a full ACL/effective-access
report. If a later ID/security comparison refuses before ACE evaluation, its
previous ACE fields remain bound to their recorded `ace_role`; UNKNOWN means no
such ACE has been evaluated. A role label alone does not certify authorization.
The original65536byte receipt cap remains enforced, including expanded rows.

The model executable source adds a focused `--ancestor-acl` argument. If separately
released, that branch runs only three new groups (predicate, retained cache and
ordering), with a distinct completion line; the no-argument historical groups
remain available and are not automatically rerun by the focused branch. No CMake
execution/test registration or dependency was added. This is source preparation,
not permission to run either branch.

Focused literal assertions reach actual common functions for observed0x4 across
all roles, two injected untrusted SID labels, retained prohibited bits/combinations,
read-only behavior, generic rights, unknown role/kind/endpoint mismatch, descriptor/
owner/DACL bounds, inheritance/unsupported ACEs and deny-plus-allow behavior.
Trustee classification is injected; native SID/group/effective-access computation
is not tested or inferred. Cache assertions cover same-handle strict upgrade
refusal, no downgrade/reset, changed handle/path/ID/security, stale role, metadata/
owner/descriptor/ACE refusal and strongest-role final recheck. Ordering assertions
use actual component classification and root derivation, including a manifest on
another drive, refusal before root admission, weak-to-strict failure before scopes/
READY and successful synthetic strict promotion. All remain **UNEXECUTED**.

The paired private collector correction, independent combined source review,
necessary new focused model/build/static evidence, actual fixed-parent diagnostic,
custody/system/window evidence and a separate Main operation release remain
distinct gates. No unseen ACL is cleared, no actual control/permit/capsule is
created, and no permission repair, trust expansion or source-only result releases
a real supervisor/probe/DLL operation. Python/client/provider/Phase1 remains open.

## F1 failure-emission admission correction — successor v2 source only

Independent review of the preceding source successor found an unguarded failure
route: after manifest parsing and failed root/scope admission, wmain could still
attempt evidence-file creation during finalization. Failure exit/candidate0 did
not authorize or undo those writes. This was a source finding, not an actual
runtime reproduction. The original finding and frozen v1 source remain historical.
The following correction is **UNCOMPILED and model assertions UNEXECUTED**, pending
independent delta review; no earlier binary implements it.

The actual common emission-admission record now has UNADMITTED, LIVE, CLOSED and
REFUSED phases. It commits only after strict operation-root and both control and
evidence parent authorization, complete preceding scope validation, exact retained
parent-path lookup and successful same-handle checks. It captures the root/parent
indices, immutable parent names and every retained ancestor handle relevant to
either output path. A failed root, failed evidence parent or scope refusal before
that commit cannot authorize any new file. A nonempty parsed pathname is never
output permission. Operation failure is not cleared to establish or use admission.

The common `file_emission_allowed` gate requires the committed record, appropriate
resource lifecycle, unchanged strongest authorized policy/handle records and the
exact immediate parent. It permits only control/ready.txt and evidence/
custody.before.txt, child.stdout, child.stderr, custody.after.txt and final.txt.
Other parents, capsule outputs and unlisted names refuse.
Control READY is additionally restricted to LIVE admission and the READY stage;
closed admission permits only the fixed evidence names.
The native open_file namespace-creation choke point invokes this gate before **every CREATE_NEW**;
other constructive dispositions are refused. Consequently all write_new callers,
including custody and failure finalization, have the same gate immediately before
the real CreateFile call. Existing read-only OPEN_EXISTING operations are unchanged.

LIVE requires all captured namespace directory handles still OPEN with matching
original values, valid strongest roles and no pending/failed authorization. It
supports already-admitted bounded failure/UNKNOWN evidence while the native owner
retains resources. It does not turn an unsuccessful operation into success.

Normal dispose closes the directory handles before final evidence, as before.
The correction explicitly transitions LIVE to CLOSED only after complete clean
operation-resource disposal and matching CLOSED states for those same captured
handles, with the same accepted policy/path records. Failed or incomplete disposal,
or failed namespace revalidation, transitions to REFUSED. UNADMITTED remains
unadmitted; no later emitter can bootstrap admission or reopen a directory handle.

CLOSED is a **historical output-admission receipt**, not an assertion that closed
handles still protect the namespace or that ACLs were freshly rechecked. Its use
requires the original trusted immutable namespace/window to continue through final
file flush/close, stdout confirmation and outer observation. Strong ancestor and
strict parent ACL/owner protections exclude untrusted namespace replacement/name
creation within that supported model; trusted user/admin/system mutation remains
excluded. If that continuing window cannot be established, the operation must not
be released. This adds no recovery/hostile-mutation guarantee and no inferred ACL
clearance after handle closure. Previously valid unrelated operation failure may
still emit diagnostics under CLOSED without clearing its failure latch.

The disposed flag refers to the pre-emission operation resources. Authorized
create-new diagnostic handles are then separately rooted, flushed and closed by
write_new. Their close/error checks and mandatory final stdout/tool exit checks
remain necessary; a candidate file cannot certify its own close. Captured
namespace records are not replaced by these new diagnostic file handles.

The common `finalize_output` routing is also shared with the model: admitted
records select O_EMIT; otherwise only bounded inherited-stdout diagnostics are
selected. The native diagnostic is one fixed ASCII OF_PROBE_DIAGNOSTIC_V1 line
(<512bytes from bounded IDs/numeric fields), carrying operation/generation/manifest/
owner, stage, first_failure, first_error, unknown, emission phase and pass=0. It
opens no pathname and creates no file. Such a line is not READY, confirmation or
passing evidence. Direct O_EMIT file paths still hit the central gate, independent
of the routing decision. Timing, one-shot CREATE_NEW, failure/UNKNOWN and physical
settlement requirements remain unchanged.

The focused --ancestor-acl source branch now has a fourth group,
emission_admission_cases, using the actual common establishment, gate, clean-close
transition and final routing. Injected file-effect counts occur only after that
gate, without native I/O. Prepared cases reproduce parsed-manifest/root refusal,
early scope refusal, actual evidence-parent policy refusal and refusal after
parent checks but before admission commit: dispose/finalize must leave zero file
effects and select outer diagnostics. Additional cases cover admitted LIVE output,
admitted CLOSED finalization despite the live-root guard being false, unrelated
failed outcome without failure reset, failed close and changed namespace security
refusing further output, and foreign parent/unlisted filename rejection.

No case was compiled or executed. These are source assertions through the real
gate, not filesystem/Windows evidence. The private collector, CMake, shared
contracts and old artifacts remain unchanged by this correction. Independent delta
review and a new exact build/focused model/static acceptance must still precede
collector rebinding, actual diagnostics/collection or any native operation release.

## Successor ancestor ACL build and focused model evidence

The independently reviewed source correction was compiled using the pinned Windows x64 MSVC toolchain. One configure and the two-target Release build passed (7.516s and 10.781s). Static inspections of both produced executables passed. C11, /W4 /WX /MT and compile/link CFG were retained; both outputs are x64 PE32+ with no exports.

The successor supervisor is 195072 bytes, SHA256 `29a32c86bac2841b2ee6a16dfbda7a8ae5715276104d02c96eaf2c5eaa1ca2e6`. It was never executed. The model is 205824 bytes, SHA256 `9ce1033f0aea2224282d9cfdb9f45720d8a7d72c485650d6a99d36efb3902687`. Its single `--ancestor-acl` invocation exited zero in 0.235s and completed the four predicate, cache, order and emission groups. These exercise shared decisions with injected facts and synthetic effects, excluding native adapters and wmain. Historical no-argument tests and CTest were not rerun.

A separate frozen collector model invocation exited zero in 2.172s and reported 131 cases, zero native calls and execution_allowed=false. It branched before native helper compilation and live collection. Its results establish model behavior, not actual ACL permissions or custody. All six step stderr logs were empty. Exact root processes were absent afterward; descendants were not enumerated and no broader physical-settlement claim follows.

Supervisor imports include bcrypt, ADVAPI32 and KERNEL32; the model imports KERNEL32. Static CRT loader/file/termination imports remain and do not imply native execution. Original failed diagnostics and earlier binary identities remain historical evidence. The collector's old binary binding remains unchanged pending coordinated acceptance of this successor. Actual corrected-chain observation, strict endpoint/custody/system/window acceptance, real supervisor/probe execution, DLL loading and provider/client integration remain open.
