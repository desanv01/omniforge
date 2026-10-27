# Injected diagnostic supervision — Stage A

Implementation candidate awaiting independent review. Exactly three new provider
modules, one new focused test file and this proof. Existing answer/model/profile/
Secrets/Run/shared contracts remain unchanged. No native process, IPC, database,
configuration, store or provider implementation is selected or invoked here.

diagnostic_protocol defines frozen selected Reservation/Observation primitives,
strict UUID/round/hash and numeric bounds, individual nullable token usage,
max(reserved, reported-known) charges and canonical replay digests. It accepts no
raw response/exception/key payload. diagnostic_child is only a thin injected facade;
it does not run answer.py or wire the real observer. diagnostic_supervisor is an
event controller. Its command tuples request external actions; they execute none.
Injected clock and explicit acknowledgment/closed events model trusted future
adapters, not an untrusted IPC parser or native exit verification.

The original monotonic deadline starts before admission. A pinned lower cap can
shorten it, never extend it. Stop/cancel/deadline/durability/protocol/authority failure
permanently prohibits release and delivery. Pending reservation requests are counted
conservatively as possible dispatch even before their acknowledgment; every confirmed
committed row is therefore included. Attempted/provider-accepted calls are not inferred;
accepted-request lower bound stays0 without external evidence. Exact duplicate
acknowledgments release once; failed acknowledgment stops without retry. Exact usage
replay cannot double charge or refund. Missing/unacknowledged usage keeps aggregate
unknown and acknowledged known subtotals separate. Reserved dimensions stay charged.

A candidate may commit after local stop/deadline. Its history can be recorded, but
no late acknowledgment returns local success. Child cleanup precedes final current
authority check; authority helper remains owned through that check and is disposed
after acknowledgment. Local success follows confirmed helper disposal and another
original-deadline/stop check. A safe child result never overrides a stopped controller.
There is no claim local stop atomically aborts an overlapping database COMMIT.

Policy uses at most30s work (lower cap applies),2s termination/verification, then at
most2s settlement-only grace. Selected commands retain owned resource identities until
explicit close events. Settlement helper itself must close within its grace; the final
0.5s is reserved for termination/verification. Missing close evidence produces
cleanup_unconfirmed, never a settled claim. The original authority/child must close
before a settlement helper is proposed; no new execution starts through settlement.

Focused offline command, from source root with existing prepared Python:

```text
python -B -m unittest discover -s tests/contracts/providers -p test_diagnostic_supervision.py -v
```

Tests use virtual time and in-memory commands/receipts only, including stalled
bootstrap/reservation/transport/observer/candidate/authority boundaries, late candidate
commit, unavailable durable stop, lost reserve acknowledgment, duplicate release/usage
acknowledgments, permanent observer-failure latch, original lower-cap deadline, final
authority/disposal ordering, disposal timeout, settlement helper hang/outage, budget/
unknown usage and malformed primitive/foreign acknowledgment rejection. No sleeps,
threads/processes, OS credentials, HTTP, database, key/config reads or installations.
Final focused execution:14 tests passed in0.004s, exit0. An earlier12-test run passed
before two additional boundary tests were added; it is not the final freeze evidence.

Backend's promised conn-bound authentication/grant/profile/binding locks, fresh DB
clock, reservation/usage journal and candidate transaction remain unimplemented by
this slice. The trusted evidence helper/answer runner's cumulative tool-byte ceiling
is not metered by the token controller. Native containment, nonblocking IPC, actual
process cleanup, durable readback/replay, observer hookup, authorized actual enrollment,
cost exposure approval and conditional live proof require separately owned reviewed
work. Fake event acknowledgments prove controller policy only. Provider readiness,
strict token/invoice limits, hard OS interruption and whole Phase1 are not established.

## V2 finite review correction

F1: Supervisor now accepts strict calls_cap1..2 at initialization and trusted
admission can monotonically narrow calls/input/output/wall ceilings before the first
reservation. A supplied larger cap never enlarges the original caller cap. Any
admission after a reservation fails closed; the trusted adapter must convey every
effective cap through initialization/admission. Omitted admission dimensions preserve
already validated initialization values. One-call diagnostics reject a second new
reservation before recording/emitting reserve or release. Exact replay still does
not consume another call. bool/non-integer/out-of-range caps are rejected.

F2: A settlement helper's actual deadline is min(overall stop+4 ceiling,
actual helper start+2), including its own cleanup. Original owners must close before
it starts, and no helper starts at/after the original cleanup cutoff. Thus early
closure does not give nearly4seconds of helper lifetime. Missing acknowledgment
remains unsettled; recorded acknowledgment without close remains owned. Termination
is latched once for either case, reserving0.5seconds for verified closure; repeated
ticks cannot append repeated termination. Failure to close by its own deadline
retains cleanup_unconfirmed without delivery.

Corrected focused execution:19tests passed in0.006s, exit0, including one/two-call
caps, invalid caps, all-dimension narrowing, admission freeze, early recorded and late
unacknowledged helper closure, repeated-tick single termination and original14cases.
The v1 snapshot/report and14test result remain historical evidence; no v1 native
runtime success was claimed. Scope remains the same five injected-only files.
