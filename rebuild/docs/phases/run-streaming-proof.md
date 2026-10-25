# OF-013-B3B3 — bounded authenticated Run event streaming

25 October2026. Implemented with actual socket and focused physical-read evidence;
frozen for independent final review. Acceptance/hosted CI remains pending.

JSON stays the events endpoint default. SSE uses persisted event sequence IDs,
safe single-line JSON data and comments without IDs. Reconnect follows the last
complete event, preserving durable order without fabricated expired cursors.
Server context retains only principal/digest, and every batch rechecks exact
current authentication and case grant. Revocation closes a stream but cannot
recall already authorized buffered data.

Default bounds:250ms poll/5s heartbeat/10events per batch/100events/1MiB/30s per
connection,2 per principal/8 process-wide. The query limit can lower total SSE
events. ASGI lifecycle ownership covers blocked sends and disconnects, with
reservation release and short database transactions before response waits.

Validation separates actual loopback socket HTTP incremental/disconnect evidence
from controlled actual-ASGI response send/backpressure/limit evidence. TestClient
can prove only bounded compatibility. All18 prior tables/history and0008 remain
preserved; no new migration, cancellation mutation, native runtime, provider,
external credential, UI feature or dependency installation belongs to this slice.

The original combined run passed22 tests,0failures/errors/skips,14.406s including
actual standard-policy HTTP at127.0.0.1:64111. It proved incremental arrival before
later rows existed, disconnect/reconnect/order, cursor/auth errors before headers,
token rotation, principal deletion/grant revocation, per-principal/global limits,
safe quality/JSON/framing,100event cap/replay and5s heartbeat without IDs. Controlled
actual Response.__call__ checks separately proved byte/event/time caps, blocked
send/disconnect, immediate read failure, helper/context privacy and abandoned
response cleanup. Two old501 assertions became bounded one-event SSE compatibility
checks; all their other cursor/auth/cancellation assertions remain.

C then found that cancellation of a coroutine could abandon its synchronous SQL
thread. The original green run is retained as partial evidence, not falsely
promoted as coverage of that window. A pause settled the DB/listener; no P2 changes
ran during the pause. After explicit resume, the corrected lifecycle tracks and
joins physical Futures across repeated cancellation. Process-wide8-job admission
occurs before executor scheduling, including pre-header reads and multiple service
instances; overload rejects503. Dedicated read pools avoid the old shared pool's
long checkout/preping settings. Every statement rechecks remaining wire time.
Shutdown stops admission, joins jobs and then disposes; a busy synchronous close
cannot falsely claim completion.

Focused post-correction execution passed11 tests,0failures/errors/skips,5.281s.
Only affected oldASGI9–11/actualHTTP1 and new14–20 ran; the22 aggregate was not
repeated. Actual PostgreSQL backend PID/wait_event PgSleep was observed before
deadline, disconnect or repeated cancellation. SQLSTATE57014 and an explicitly
synthetic delayed finalizer demonstrated slot/read ownership retained until
physical completion. Tests also covered canceled pre-header reads, process-wide
admission saturation across services, shutdown drain and no abandoned tasks.
Afterward active/pending/global-admitted/checked-out read counts and stream slots
were0; no settlement overrun was observed. No local final20-test aggregate is
claimed: unchanged earlier evidence plus the focused correction evidence apply.

Wire emission remains bounded by30s. A1.5s healthy-local resource-settlement target
is separate and is not a hard guarantee over DNS/socket/OS stalls or thread death.
Unexpected lingering physical work stays visibly accounted/fail-closed without
unbounded executor replacement; guaranteed hard termination would need a separately
reviewed transport/isolation design. Synthetic finalizer delay is not native
scheduler/process termination proof.

The portable `tests.integration.core.streaming_runner` discovers the final20-case
fixture, refuses missing/zero/skipped cases, prebinds the explicit loopback port,
injects the actual listener and joins/stops it in finally. It has no Docker/start/
bootstrap/migration/config discovery and prints no credentials. Packaging was
syntax-checked locally; hosted intended-head CI validates its complete integration.
The already accepted22 cases were not rerun merely for packaging.

All original columns/row fingerprints in18 application tables match both the
original pre-stream and resumed snapshots. Schema0008/migrations0001–0008/root
lock unchanged. Original cancellation/profile/enrollment/submission history,
including pending/unresolved rows, is preserved. Fixtures add only their new
synthetic records/events; streaming product code is read-only. No success/state
change follows a transport close. The exact database stopped/preserved exit0;
both actual HTTP proof listeners stopped/joined and their port closed.

Actual pinned OpenAPI/client generation and strict TypeScript compilation passed;
no public contract changed during the internal P2 correction. Exact versioned
source/receipts and chronology are in private coordination evidence, excluded from
public Git. Final independent C source/evidence review and Main delivery/CI remain
required. No native worker/provider/OS-store/enrollment/image operation occurred.
