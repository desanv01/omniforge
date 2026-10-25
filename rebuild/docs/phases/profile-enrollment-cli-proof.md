# Explicit profile enrollment terminal entrypoint

Status: implemented and verified with injected-only tests; independent review and
delivery CI pending. No actual enrollment, configuration read, OS credential
operation or provider call occurred during this task.

`infra.core.enroll_profile_cli` connects terminal input to the accepted
`infra.core.enroll_profile.enroll_profile` callable. It introduces no separate
reservation, authentication SQL, binding, attachment or activation state machine.
Importing the module performs no configuration read, input, engine construction
or Windows credential-store construction.

## Explicit invocation contract

Actual human invocation remains a separately authorized setup gate. From the
rebuild root, the command shape is:

```text
python -B -m infra.core.enroll_profile_cli --config "<absolute-config-path>" --principal-id "<canonical-uuid>" --case-id "<canonical-uuid>" --profile-id "<canonical-uuid>" --operation-id "<canonical-uuid>" --expected-revision "<positive-integer>"
```

All six options are required exactly once as separate flag/value pairs. No
abbreviations, duplicate options, extra arguments, key/token/ref flags, discovery,
import, search, rotation or activation command is accepted. IDs must be canonical
UUID strings; expected revision is between 1 and 2147483647. Configuration is an
explicit absolute path, never inferred from environment or a token file. Argument
errors never repeat submitted values or paths.

Before input or configuration access, stdin and stderr must be TTY and stdout
must pass an empty write/flush check. The CLI prompts for a hidden local bearer
token (1–256 printable non-whitespace ASCII characters). It rejects getpass
echo-fallback warnings before fallback input, overriding an outer ignore filter.
It then lazily constructs an engine from only the chosen configuration using
accepted Settings/engine_for and the accepted desktop Windows store. Factories
are dependencies injected by every automated test; none runs against real config.

The bridge authenticates token-to-principal, current writer/case/profile/revision
before requesting the hidden provider credential. Caller-supplied principal ID is
not authority. The accepted bridge/helper reserve before input, freshly authorize
after input/before put, and recheck before atomic disabled attachment. This CLI
does not replace or skip those checks. Its provider input callback accepts one
nonblank strict UTF-8 value, at most 2560 bytes, and cannot be prompted twice.
No credential values traverse arguments, environment, files, HTTP or output.

Settled replay still requests current hidden bearer authentication but does not
prompt for a provider key, put, attach or activate again. Pending/unresolved replay
requires explicit recovery; no retry/read/delete is implemented. Successful output
is an allowlisted JSON receipt with schema version, operation/case/profile IDs,
expected/attached revisions and `attached` status. It excludes credential reference,
token, key, configuration path and connection string. An attached historical receipt
does not assert present credential availability or activate a profile.

## Errors, cleanup and limits

Malformed input, exceptions and interruptions use fixed diagnostics without raw
exception strings, traceback or secret repr. Before bridge invocation, failures
report that enrollment did not complete. Once the bridge is invoked, failures,
invalid receipts or lost output conservatively report uncertain completion and
forbid automatic retry. This can overstate uncertainty for a pre-put denial; it
does not infer that a credential was written. No rollback/delete/reconciliation is
attempted by this entrypoint. Output may be partially delivered before a failure.

Engine disposal is attempted once on every resource-owning path, before success
output. Disposal failure prevents success; interruption during failure cleanup is
also sanitized. The CLI reports failure rather than claiming resources closed
when disposal fails. All supplied SecretValue buffers are cleared on exit, even
if an injected bridge fails to clear them; raw input/token references are dropped.
Python immutable strings, encoded byte copies, exceptions held by callees, debug
locals or diagnostic dumps are not guaranteed erased/redacted. Keep those captures
disabled; normal safe output is not a whole-process memory isolation guarantee.

Real Windows console echo behavior, actual configuration permissions/database
availability, native store behavior, live provider compatibility and cost remain
unexecuted. No cross-account boundary or interruption recovery is inferred. Backend
remains owner of persisted authorization/binding correctness; its separately
accepted actual-PG fake-store proof is not rerun here.

## Actual focused verification

Existing CPython 3.11 environment, no installation or runtime start:

```text
python -B -m unittest discover -s tests/contracts/secrets -p test_profile_cli.py -v
```

Initial run: 18 tests passed in 1.441 seconds, exit zero. It covers parser/TTY/
output preflight, hidden auth/provider handoff, noecho warning refusal, invalid
and oversized values, sanitized factory/bridge failures, interruptions, output
loss, one-prompt enforcement, receipt validation, owned engine disposal and value
clearing. It also invokes the accepted bridge/helper with fake binding callbacks
and store for new/settled/pending flows; no SQL or connection executes.

Source review then identified an interruption gap during failure cleanup. The
diagnostic and cleanup handlers now also catch KeyboardInterrupt. Only three
new/affected tests were run afterward: auth interruption/EOF before resources,
maximum token and 2560-byte UTF-8 credential, and interrupted cleanup/diagnostics.
All three passed in 0.009 seconds, exit zero. The expanded 21-test suite was not
rerun locally; the 18-test result records the initial snapshot. CI discovery can
run all tests without the live-store flag. No other accepted suite was repeated.

Tests inject terminal streams, synthetic random token/key strings, engine/store
factories and input. Default factories/real getpass are guarded against accidental
use. Import is checked with configuration reads forbidden. No actual hidden input,
configuration read, database engine/client construction, credential access or
provider call was used for these results.
