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
