# OF-012 provider contract and synthetic proof

Status: reviewable standalone implementation, awaiting independent review. API,
live provider and application secret setup integration remain PENDING. This is
not acceptance of Phase 1 or the full read-only investigator.

## Interface and authority

`services.api.providers.answer.answer(context, profile, budget, store=...,
transport=...) -> ProviderResult` uses typed frozen contracts under
`adapters/models/contracts.py`. ReadOnlyContext carries case, policy version,
objective, immutable locations, cancellation and application-bound authority
callbacks. Profile pins ID/revision/model/endpoint/credential reference. Changing
any of them requires application authorization; reference possession is not a grant.

The application must construct context from authorized persisted records and bind
`read_range(association_id, expected_sha256, start_byte, end_byte) -> bytes` to the
authenticated principal and case. Every invocation must perform a fresh grant,
association, committed-state, full-blob hash/size and exact bounds check. The backend
owner agreed to expose this seam; actual integration is pending. The provider does
not duplicate the database authority or infer a grant from model/evidence text.

The one tool reads exactly a supplied location's zero-based half-open range. It
returns original bytes as base64, without newline/encoding normalization. The adapter
checks location/hash/bounds and returned length. Verification of a complete blob's
hash belongs to the backend callable; hashing a slice cannot prove a full-blob hash.
Unknown associations/locations, altered hashes/ranges and citations without a
successful read fail closed. Observations retain partial/unknown coverage; claims
remain unverified with explicit uncertainty and independently checked supporting
and contradicting citations. No citation validation proves a claim is true.

## Adapter decision and current primary sources

Research checked on 2026-10-23:

- [Pydantic AI DeepSeek integration](https://pydantic.dev/docs/ai/models/deepseek/)
  documents OpenAIChatModel with explicit DeepSeekProvider API-key injection and a
  customizable HTTP client. This is a viable future SDK route. It also documents
  thinking/tool-history compatibility concerns; SDK installation alone is no proof.
- [DeepSeek tool calls](https://api-docs.deepseek.com/guides/tool_calls/) documents
  application-executed function calls and assistant/tool message round trips.
- [DeepSeek JSON output](https://api-docs.deepseek.com/guides/json_mode/) documents
  JSON-object mode and possible empty/truncated output. Valid JSON is not schema
  validity; this implementation validates the final document locally.
- [DeepSeek errors](https://api-docs.deepseek.com/quick_start/error_codes/) supplies
  authentication, balance, parameter, rate-limit and server-error distinctions.

Decision: implement the narrow direct Chat Completions transport with Python's
stdlib HTTPS and existing locked Pydantic validation. This avoids an unproved SDK
dependency/agent retry layer in the shared environment, while keeping transport
replaceable behind a Protocol. No SDK was installed or compatibility claimed.
The request supplies a JSON schema in the prompt, ordinary function tools,
`stream=false` and a bounded `max_tokens`; it does not request native strict schema,
hosted search, forced tool choice or automatic fallback. Tool-turn reasoning_content
is preserved when returned. Model IDs are explicit profile values, with no default
model guessed from documentation. Actual model behavior remains unverified.

## Credentials, endpoints and failures

Only `https://api.deepseek.com/chat/completions` is currently allowlisted. Other
hosts, path variants, ports, credentials in URLs, queries and redirects are rejected
before a secret read. Transport uses system TLS verification with no custom headers,
ambient proxy or plaintext environment/file credential fallback. Broader network
policies/proxy modes require separate owned implementation and proof; DNS/system
trust are OS dependencies, not an egress firewall.

The service calls the reviewed SecretStore.get only at execution after profile
authorization and endpoint validation, and clears the returned SecretValue in a
finally block. No OS store is instantiated during imports/tests. Immutable Python
copies in TLS/HTTP internals cannot be guaranteed erased. No logging/tracing is
enabled here; application logging must never capture request headers, local
variables or raw provider responses. There is no profile/setup API in this slice.

Auth, rate limit, timeout, insufficient balance, unavailable provider, invalid schema,
unsupported tool, evidence tool failure, forbidden reference, cancellation and budget
errors have fixed codes. Missing/denied/unavailable/unsupported/storage secret errors
remain distinct. Errors return accumulated usage and never raw exception messages or
upstream error bodies. No automatic retries or silent model/profile fallback occur.

## Budgets and accounting

Budgets cap calls, cumulative input/output reservations, wall duration, and tool
bytes. Each call reserves conservative UTF-8 request bytes plus framing allowance
as estimated input, and up to512 output tokens before dispatch. Reservations are
never refunded using missing usage; repeated rounds and repeated reads consume
cumulative limits. The request sends the remaining bounded output allowance.
Each response reconciles its charged input/output to the greater of that round's
reservation or reported known usage before any later credential read or dispatch.
Unknown rounds retain their full reservations, and smaller reported usage never
refunds a reservation. `charged_input`/`charged_output` expose these conservative
admission totals separately from raw reservations and provider usage. These input
reservations are estimates, not a proven tokenizer upper bound. A
provider-reported overrun fails the result while preserving reported usage; an
already consumed upstream request cannot be rolled back.

Input/output usage is individually known only when reported for every dispatched
request, otherwise null/unknown. Known subtotals remain available even when a round
has unknown usage. Calls, reserved input/output and tool bytes remain counted on
failures. The Measurement contract supports estimated values with provenance;
reported token values are attributed to the provider, not independently measured.
Price/cost is null/unknown; unknown cost is never represented as zero.

Cancellation/deadlines are checked before dispatch, before/after each tool and after
each provider response, preventing late publication and further tools. A remaining
timeout is passed to synchronous HTTPS I/O. This is a cooperative deadline/socket
timeout, **not a proven hard total interruption** of DNS, slow headers/body or a
blocked trusted backend callback. In-flight cancellation latency/hard worker
termination must be established by coordinated run/runtime integration before live
acceptance. No concurrent scheduler/runtime is created here.

## Executed validation and remaining gates

Run from source root using the backend owner's existing read-only interpreter:

```text
python -B -m unittest discover -s tests/contracts/providers -v
```

16 tests passed in1.197s in the corrected synthetic proof, including a regression for known usage above
its per-round reservation but below the total cap: input prevents the next store
read/dispatch; output reduces the next allowance and prevents an extra round;
unknown earlier rounds retain their reservations. The other checks cover exact non-normalized
bytes, ref/hash/range/citation rejection, profile/credential pin changes before store
access, no dispatch on missing/denied store, cumulative calls/output/tool bytes and
input reservations, unknown usage/known subtotals, cancellation, deadlines,
sanitized tool/provider exceptions, schema rejection and reported budget overruns.
Mocked stdlib HTTPS tests exercise status/error mapping, no redirect retry and body
size/invalid JSON rejection. Tests use synthetic in-memory SecretValue instances;
they neither read nor write Windows credentials or send HTTP requests.

Pending: independent review; backend-bound evidence seam and real grant rejection;
authorized profile/setup/UI paths; persisted run accounting/recovery; hard in-flight
interruption proof; and separately authorized/budgeted real DeepSeek text/tool/schema
behavior. Stream and hosted search remain unverified and unused. A live check needs
an explicitly configured profile/model, a credential reference populated through
reviewed authorized setup, exact synthetic input grants and a finite approved call
budget. Missing credentials leave it PENDING. Do not request, discover, import or
substitute a legacy credential as part of this standalone slice.
