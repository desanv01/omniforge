# Bound credential enrollment helper

Status: initial 16 injected-only tests passed; two focused aliasing-correction
regressions passed afterward. Independent correction review and backend
transactional integration proof pending. No actual enrollment occurred.

`adapters.secrets.enrollment` has no CLI, prompt, store constructor, database,
network operation or import-time I/O. The trusted local backend bridge supplies
all input/store/callback dependencies. This extends sequencing beyond the accepted
standalone setup helper without changing that helper or the Windows adapter.

## Frozen in-process interface

- `EnrollmentRequest`: frozen operation_id, principal_id, case_id, profile_id
  (UUID objects) and expected_revision (positive integer, not bool).
- `EnrollmentBinding`: those fields plus credential_ref, omitted from repr.
  Only canonical production `wincred:omniforge:v1:<uuid4>` references are accepted.
- `EnrollmentReceipt`: request fields plus positive attached_revision and fixed
  status `attached`; no credential reference. Backend sets the recorded resulting
  revision and verifies its authority/provenance.
- `Reservation`: disposition `ready`, `settled` or `blocked`, with binding only
  for ready, receipt only for settled, and neither for blocked.
- Keyword-only `enroll_new(request, reserve, hidden_input, authorize_put, store)`
  returns `EnrollmentBinding` after a single successful put, or an
  `EnrollmentReceipt` for settled replay. No success here attaches or activates.

The helper generates the fresh reference internally. No caller-reference argument,
existing credential lookup, test-reference binding, enumeration, replacement,
delete, implicit retry or fallback is exposed. WinCred's underlying exact-target
put has no atomic create-if-absent; fresh UUID generation limits collision risk
without proving impossibility of collision or same-user process interference.

## Sequence and backend responsibilities

1. Generate a fresh reference/candidate with the request tuple. Invoke
   `reserve(candidate) -> Reservation` before input. Backend authenticates current
   local principal/writer/current profile and exact tuple, checks replay, then
   commits a ready pending reservation and closes its transaction before returning.
2. Ready requires the exact complete candidate binding. Hidden input returns an
   owned `SecretValue`, never raw secret arguments/env/files. The future trusted
   terminal caller must provide a hidden-input implementation with the accepted
   TTY/echo-fallback controls; this helper supplies no real input implementation.
3. Immediately after input, revalidate tuple integrity and invoke
   `authorize_put(binding) -> EnrollmentBinding`. Backend freshly checks current
   authentication, writer grant, profile revision and complete pending tuple,
   closes its transaction and returns that exact binding. Exceptions, malformed
   or changed tuples, false/None permission and invalid/cleared values deny the
   put. Primitive snapshots also detect mutation bypassing frozen dataclasses.
4. Perform one `store.put(fresh_ref, value)`. Backend independently reauthenticates
   and rechecks the tuple/revision after successful return before transactionally
   attaching the reference/appending a profile revision. Activation is separate.
   No DB transaction may span human input or OS I/O.

Settled replay accepts only an exact request receipt and returns before input,
authorize_put or put. Backend must check **current** authentication/writer authority
before replay lookup; the receipt is historical and cannot reactivate disabled
profiles. Pending/unresolved maps to blocked and requires explicit recovery,
never repeated prompting/put. The helper cannot authenticate a database receipt;
callbacks and store must be trusted application code, not caller-supplied HTTP
functions. Frozen DTOs and UUID possession do not confer authority.

`EnrollmentError` exposes fixed `denied`, `recovery_required` or `uncertain` codes
and messages. A put attempt that raises or is interrupted is uncertain, even if
the store reported denial: the helper cannot establish external completion. It
does not re-read/delete/retry. Backend captures the ready reservation and records
unresolved when possible; DB outage leaves the last durable pending intent. A
post-put attach failure likewise cannot be reported as configured by this helper.

Returned SecretValue buffers are cleared on every exit after delivery to the
helper. The input callback owns any allocation it does not return (including its
own exception path). Immutable Python copies, debug dumps, traceback-local capture
and deliberate introspection are not guaranteed erased or redacted; normal errors
suppress raw callback/store exception chaining and no values are logged here.
Authority checks do not eliminate sub-instruction races or undo completed writes.

## Actual bounded unit verification

Executed once from the rebuild root using stdlib only:

```text
python -B -m unittest discover -s tests/contracts/secrets -p test_enrollment.py -v
```

Result: 16 tests passed, 0.013 seconds, exit zero. Tests inject fake input/store/
callbacks only; generated v1 references label fake in-memory operations, with no
Windows store construction or credential read/write. Coverage includes exact
reserve/input/authorize/put order; fresh reference and buffer clearing; settled
receipt replay; pending recovery; revoked-during-input zero writes; changes to
each binding field; false/None authorization; frozen-dataclass mutation bypass;
request mutation; safe uncertain put failures/interruption without retry; reserve/
input failure; invalid request/ref/value/reservation cases; and safe traceback
formatting. No tests from other suites or live-store lifecycle were rerun.

This verifies local sequencing and validation, not PostgreSQL commits/grants,
post-put attachment or real TTY/OS/provider behavior. Backend owns the separate
actual-database fake-store integration proof. Actual enrollment and provider calls
remain separately authorized future work.

### Bounded aliasing correction

Independent review found that reserve could return an equal binding with a
distinct CredentialRef object, while retaining the original candidate reference.
Mutation of that original reference during input/authorization could evade checks
of the returned binding, although put used the original reference. The helper now
also revalidates the original write reference against its captured primitive value
after input and immediately before put.

Added two regressions using an equal cloned reservation and retained original ref:
mutation during input and mutation during authorize_put. Both assert denied,
zero put and delivered-value clearing. Only these two new tests were executed
after correction: 2 passed in 0.002 seconds, exit zero. The original 16-test pass
remains historical evidence for the pre-correction snapshot; the complete expanded
18-test suite was not rerun locally. No real input/store/DB operation occurred.
