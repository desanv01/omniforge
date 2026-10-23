# OF-012S-A standalone Windows credential adapter

Status: implemented and locally verified; awaiting independent review. Application
integration, provider setup UI and live DeepSeek proof remain pending.

## Interface and intended use

`adapters.secrets.SecretStore` exposes `get(CredentialRef) -> SecretValue`,
`put(CredentialRef, SecretValue) -> None`, and `delete(CredentialRef) -> bool`.
Generate a reference with `CredentialRef.new()`, persist only its `value` in the
provider profile, and reconstruct it with `CredentialRef(value)`. References are
opaque identifiers, not authorization. Setup must authorize insertion/removal;
provider execution must authorize the profile, endpoint and request before retrieval.
No adapter import performs credential reads or writes.

`WindowsSecretStore(mode="desktop")` uses only `CredReadW`, `CredWriteW`,
`CredDeleteW` and `CredFree` from the system32 Advapi32 DLL. It stores generic
credentials with local-machine persistence: same user, same computer across logon
sessions. It does not request roaming. Exact targets derive from canonical UUID4
references within the fixed OmniForge namespace. No enumeration or arbitrary target
names are exposed. New references and exact updates are supported; `put` replaces
the value at its reference. Coordinate concurrent setup changes in the application.

Values are opaque bytes, including NUL, between 1 and 2560 bytes. Setup/provider
code owns any explicit UTF-8 encoding/decoding. `SecretValue` hides the value from
normal `repr`/`str`, refuses pickle serialization, and requires explicit `reveal()`
at the execution boundary. Call `clear()` when finished. Native write buffers and
returned WinCred blobs are cleared before release. Python byte copies and caller
memory are not guaranteed erased. This wrapper cannot protect against deliberate
introspection, debug dumps, traceback-local capture or callers logging revealed
bytes. Production logging must disable those captures and never serialize secret
objects, provider bodies or secret-bearing headers/URLs.

## Failure and recovery

Fixed errors distinguish `missing`, `denied`, `unavailable`, `unsupported`, invalid
reference/value, and generic `storage`; messages exclude raw native exception text,
targets and values. Native 1168 means missing, 1312 unavailable and 5 denied; other
errors become storage. Unexpected native exceptions suppress their displayed cause.
Missing deletion returns false. Missing retrieval tells setup to request re-entry;
it never substitutes an environment variable, file, legacy key or empty value.

Re-enter the selected key through an authorized future setup flow under the
intended Windows identity, write it at the retained reference, and retry only through
explicit application policy. Do not automatically retry provider calls. Removal or
store loss leaves the profile reference intact but unusable until re-entry. This
adapter does not back up/export credentials or recover an original lost value.
Machine replacement, account/profile loss or corruption requires re-entry/revocation
according to provider policy. Legacy credentials are never imported automatically.

WinCred is scoped to the current token's logon credential set, not an OmniForge
process boundary. Other processes running as that user may retrieve generic
credentials. Use the intended desktop identity and trusted local software. No
cross-account access-denial experiment, reboot/logoff persistence test,
cross-machine restoration or credential-backup recovery has been demonstrated.
Other platforms and declared headless mode fail explicitly as unsupported; network
logons may have no credential set. A future headless/service adapter needs its own
identity, encrypted-key supply and recovery proof. This code cannot detect every
headless host; deployment must select the supported mode explicitly.

## Verification

Run from the rebuild root with CPython 3.11 and no added dependencies:

```powershell
python -B -m unittest discover -s tests/contracts/secrets -v
python -B -m tests.contracts.secrets.test_secret_store --live-wincred
```

The live switch authorizes only freshly generated synthetic values at a unique
`OmniForge/wincred:omniforge:test:<uuid4>` target. The test records the nonsecret
target before use, marks ownership only after a successful write, and cleans only
that owned exact target. It never enumerates or reads existing credential names.
Default discovery skips live credential operations. Synthetic comparisons use
boolean assertions so failures do not print values.

Executed on Windows x64 CPython 3.11.15: contract tests and explicit synthetic
lifecycle passed. The first sandbox live attempt returned denied on the initial
read, before any write. One authorized run outside the sandbox passed. The final
suite covers native structure layout, exact write/read/update equality, NUL and
maximum-size blobs, absent/deleted states, explicit re-entry, owned cleanup,
unsupported mode/platform, invalid inputs, error mapping, redacted repr/traceback,
pickle rejection, clearing write buffers on failure, and freeing/clearing read
buffers including malformed-blob rejection. Mock error tests are not evidence of
actual cross-account denial or real credential corruption.

## Primary sources checked 23 October 2026

- [Microsoft CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw): generic blob limit, structure, target and persistence semantics.
- [Microsoft CredReadW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw): current token/logon scope, missing/no-session errors, allocation ownership.
- [Microsoft CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew): exact creation/replacement and failure behavior.
- [Microsoft CredDeleteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-creddeletew) and [CredFree](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credfree): deletion and buffer release.
- [Python ctypes](https://docs.python.org/3.11/library/ctypes.html): WinDLL, argument/result typing and thread-local last-error handling.

This stdlib implementation avoids a dependency/global backend selector and its
fallback policies. Review must still assess the ctypes ABI and memory handling.
No third-party source code was copied. Shared ADR/SPEC/manifests remain owned by
their assigned integrator; their unimplemented status should change only after
review and actual application wiring.
