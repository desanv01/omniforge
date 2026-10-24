# OF-012P-AUTHBOUNDARY — current authority around retrieval and publication

Status: implemented and synthetic verification passed; awaiting independent review. This
small change consumes the existing authorize_profile(Profile) callback. It does
not implement persisted profile ownership, setup, actual-core grant changes,
live-provider compatibility or durable run publication.

The provider service now checks authority again after SecretStore.get returns,
inside the returned value's try/finally and before transport dispatch/call count.
A denied, changed or failing authority prevents dispatch and clears the retrieved
SecretValue. A fixed forbidden result contains no answer or raw authority error.
The callback must return the boolean True; truthy non-boolean values fail closed.
The existing initial and per-loop authorization decisions remain in place.

After parsing/validating the final result and citations, the service checks current
authority again before returning an answer, followed by the existing cancellation/
deadline checkpoint. A grant/profile change or callback exception here prevents
successful publication while preserving already dispatched call counts and reported
usage. All authority checks use the same safe failure wrapper; an authority error
cannot be misclassified from a raw exception as a credential-store result.

Reservations/charges are unchanged: cumulative per-round charged input/output
retain max(reserved, reported-known), with no refund for unknown/smaller reports.
Reservations taken before retrieval remain even if the new post-get check denies;
that denial does not count a provider call or invent token usage. If a later get
denies, earlier known/unknown usage and known subtotals survive. Secret clearing is
best effort under the existing wrapper; immutable copies are not guaranteed erased.

Synthetic new contract tests cover deny/revision/ref mutation during retrieval,
callback exception after retrieval, denial/exception before final publication,
second-retrieval revocation retaining prior usage, unknown-round subtotal retention
and non-boolean authority rejection. They use in-memory synthetic SecretValue
objects, explicit scripted model responses and no database/store/network access.
The existing next-loop revocation fixture has one additional True in its callback
sequence to authorize the new intervening post-get check; its original expected
one-dispatch/forbidden assertions are retained. No baseline behavior assertion is
weakened or removed.

Commands from source root with the existing prepared interpreter:

```text
python -B -m unittest discover -s tests/contracts/providers -p test_authority.py -v
python -B -m unittest discover -s tests/contracts/providers -v
```

Executed once each: new focused authority suite6tests passed in0.063s, exit0;
affected combined provider contracts22tests passed in0.637s, exit0.
Detailed execution and exact frozen hashes are in the private owner delivery.
Independent review and actual intended-head CI remain separate acceptance gates.

These are cooperative action-boundary checks. They do not make grant revocation,
secret retrieval and network dispatch one atomic transaction; they do not abort
already in-flight upstream work, prove exact tokenizer/cost caps or establish
fenced persisted run publication. The trusted backend callback remains responsible
for fresh authenticated principal/case/profile authorization. Profile DB/API,
actual setup, runtime hard interruption and live-provider proof remain pending.
