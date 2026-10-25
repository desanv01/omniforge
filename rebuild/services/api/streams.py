"""Bounded authenticated SSE; persisted events only, no Run mutation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import math
import re
import threading
import time
from uuid import UUID, uuid4

from fastapi.responses import Response
from sqlalchemy import create_engine, event, text

from services.api.errors import Problem, response as error_response
from services.api.runs.contracts import RunEventPage


@dataclass(frozen=True)
class PrincipalContext:
    principal_id: UUID
    token_digest: str = field(repr=False)

    def __post_init__(self):
        if type(self.principal_id) is not UUID or type(self.token_digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.token_digest):
            raise ValueError("Server-owned authenticated context required")


@dataclass(frozen=True)
class StreamPolicy:
    poll_seconds: float = .25
    heartbeat_seconds: float = 5
    batch_events: int = 10
    max_events: int = 100
    max_bytes: int = 1048576
    lifetime_seconds: float = 30
    per_principal: int = 2
    total_streams: int = 8

    def __post_init__(self):
        for value, low, high in ((self.poll_seconds, .25, 30), (self.heartbeat_seconds, 5, 30),
                                 (self.lifetime_seconds, 0, 30)):
            if type(value) not in (int, float) or not math.isfinite(value) or value > high or value < low or value <= 0:
                raise ValueError("Bounded stream timing required")
        for value, maximum in ((self.batch_events, 10), (self.max_events, 100), (self.max_bytes, 1048576),
                               (self.per_principal, 2), (self.total_streams, 8)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Bounded stream limits required")


class StreamLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._leases = {}

    def reserve(self, principal_id, policy):
        with self._lock:
            if (len(self._leases) >= policy.total_streams or
                sum(value == principal_id for value in self._leases.values()) >= policy.per_principal):
                return None
            lease = uuid4()
            self._leases[lease] = principal_id
            return lease

    def release(self, lease):
        with self._lock:
            self._leases.pop(lease, None)

    def snapshot(self):
        with self._lock:
            counts = {}
            for principal in self._leases.values():
                counts[principal] = counts.get(principal, 0) + 1
            return {"total": len(self._leases), "principals": counts}


PROCESS_LIMITER = StreamLimiter()
READ_PERMITS = threading.BoundedSemaphore(8)
READ_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="omniforge-stream-read")
READ_GUARD = threading.Lock()
READ_ADMITTED = 0


class StreamService:
    def __init__(self, engine_callable, read_page, policy=None, limiter=None):
        self.engine = engine_callable
        self.read_page = read_page
        self.policy = policy or StreamPolicy()
        if type(self.policy) is not StreamPolicy:
            raise ValueError("Validated stream policy required")
        self.limiter = limiter if limiter is not None else PROCESS_LIMITER
        self._guard = threading.Lock()
        self._read_engine = None
        self._executor = None
        self._physical = set()
        self._active_reads = 0
        self._closing = False
        self._overruns = 0

    def _resources(self):
        # No connection is opened at app import/construction. Each service owns
        # its pool/executor; eight admitted jobs never queue in a shared executor.
        if self._read_engine is None:
            self._read_engine = create_engine(self.engine().url, pool_size=8, max_overflow=0,
                pool_timeout=.05, pool_pre_ping=False, hide_parameters=True,
                connect_args={"connect_timeout": 1,
                              "options": "-c statement_timeout=250 -c lock_timeout=250"})
            self._executor = READ_EXECUTOR
            @event.listens_for(self._read_engine, "before_cursor_execute")
            def remaining_timeout(conn, cursor, statement, parameters, context, executemany):
                deadline = conn.info.get("stream_deadline")
                if deadline is None or statement.startswith("SET LOCAL"):
                    return
                milliseconds = min(250, max(1, int((deadline-time.monotonic())*1000)))
                if time.monotonic() >= deadline:
                    raise Problem(503, "stream_read_deadline", "storage", "Event read deadline reached", True)
                # Native cursor avoids recursive SQLAlchemy event dispatch.
                cursor.execute(f"SET LOCAL statement_timeout='{milliseconds}ms'")
                cursor.execute(f"SET LOCAL lock_timeout='{milliseconds}ms'")

    def resource_snapshot(self):
        with READ_GUARD:
            admitted = READ_ADMITTED
        with self._guard:
            return {"active_reads": self._active_reads, "pending_reads": len(self._physical),
                    "checked_out": self._read_engine.pool.checkedout() if self._read_engine else 0,
                    "settlement_overruns": self._overruns, "global_admitted_reads": admitted}

    def close(self):
        with self._guard:
            self._closing = True
            if self._physical:
                return False
            if self._read_engine:
                self._read_engine.dispose()
            return True

    async def aclose(self):
        # Fail closed: app shutdown cannot declare read ownership settled while
        # a physical operation remains. This is not a Python thread-kill promise.
        with self._guard:
            self._closing = True
            pending = list(self._physical)
        try:
            if pending:
                await self._join(asyncio.gather(*(asyncio.wrap_future(future) for future in pending),
                                                 return_exceptions=True))
        finally:
            self.close()
        return True

    async def _join(self, future):
        canceled = False
        began = time.monotonic()
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                canceled = True
            except Exception:
                break
        if time.monotonic()-began > 1.5:
            with self._guard:
                self._overruns += 1
        if canceled:
            # Retrieve physical failure even when caller cancellation wins.
            if future.done() and not future.cancelled():
                future.exception()
            raise asyncio.CancelledError
        return future.result()

    def _read(self, context, run_id, after, limit, deadline):
        with self._read_engine.begin() as conn:
            conn.info["stream_deadline"] = deadline
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise Problem(503, "stream_read_deadline", "storage", "Event read deadline reached", True)
            timeout = min(250, max(1, int(remaining*1000)))
            conn.execute(text(f"SET LOCAL statement_timeout='{timeout}ms'"))
            conn.execute(text(f"SET LOCAL lock_timeout='{timeout}ms'"))
            page = RunEventPage.model_validate(self.read_page(conn, context.principal_id, context.token_digest, run_id, after, limit))
        if page.run_id != run_id:
            raise Problem(409, "event_binding_conflict", "conflict", "Event replay unavailable")
        expected = after + 1
        for event in page.items:
            if event.run_id != run_id or event.sequence != expected:
                raise Problem(409, "event_gap", "conflict", "Event replay unavailable")
            expected += 1
        return page

    async def fetch(self, context, run_id, after, limit, deadline=None):
        global READ_ADMITTED
        deadline = deadline if deadline is not None else time.monotonic()+self.policy.lifetime_seconds
        with self._guard:
            if self._closing or len(self._physical) >= 8:
                raise Problem(503, "stream_read_limit", "storage", "Event read unavailable", True)
            if not READ_PERMITS.acquire(blocking=False):
                raise Problem(503, "stream_read_limit", "storage", "Event read unavailable", True)
            with READ_GUARD:
                READ_ADMITTED += 1
            try:
                self._resources()
            except BaseException:
                with READ_GUARD:
                    READ_ADMITTED -= 1
                READ_PERMITS.release()
                raise
            # The lock prevents a fast worker from finishing before registration.
            def work():
                with self._guard:
                    self._active_reads += 1
                try:
                    return self._read(context, run_id, after, limit, deadline)
                finally:
                    with self._guard:
                        self._active_reads -= 1
            try:
                physical = self._executor.submit(work)
            except BaseException:
                with READ_GUARD:
                    READ_ADMITTED -= 1
                READ_PERMITS.release()
                raise
            self._physical.add(physical)
        def completed(done):
            global READ_ADMITTED
            with self._guard:
                self._physical.discard(done)
            with READ_GUARD:
                READ_ADMITTED -= 1
            READ_PERMITS.release()
        physical.add_done_callback(completed)
        # Raw asyncio cancellation must not cancel/abandon the worker future.
        return await self._join(asyncio.wrap_future(physical))

    async def open(self, request, context, run_id, after, limit):
        if (type(context) is not PrincipalContext or type(run_id) is not UUID or
            type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100):
            raise Problem(422, "invalid_stream_request", "validation", "Invalid event stream request")
        policy = self.policy
        cap = min(limit, policy.max_events)
        async with asyncio.timeout(policy.lifetime_seconds):
            await self.fetch(context, run_id, after, min(policy.batch_events, cap))
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return EventStreamResponse(self, context, run_id, after, cap, policy, request_id)


class EventStreamResponse(Response):
    media_type = "text/event-stream"

    def __init__(self, service, context, run_id, after, cap, policy, request_id):
        super().__init__(content=b"", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        self.raw_headers = [(key, value) for key, value in self.raw_headers if key != b"content-length"]
        self.service, self.context, self.run_id = service, context, run_id
        self.after, self.cap, self.policy, self.request_id = after, cap, policy, request_id

    async def __call__(self, scope, receive, send):
        # Reserve at lifecycle entry, not at object construction: abandoned or
        # rejected responses cannot leak a concurrency slot before __call__.
        lease = self.service.limiter.reserve(self.context.principal_id, self.policy)
        if lease is None:
            error = error_response(self.request_id, 429, "stream_limit", "conflict", "Stream limit reached", True,
                                   headers={"Retry-After": "1"})
            await error(scope, receive, send)
            return
        tasks = []
        started = finished = False
        deadline = asyncio.get_running_loop().time() + self.policy.lifetime_seconds
        try:
            async with asyncio.timeout_at(deadline):
                await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
                started = True
                async def disconnected():
                    while True:
                        if (await receive())["type"] == "http.disconnect":
                            return
                body_deadline = deadline-min(.05, self.policy.lifetime_seconds/10)
                tasks = [asyncio.create_task(self._pump(send, body_deadline)), asyncio.create_task(disconnected())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                if tasks[0] in done:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    finished = True
        except (Exception, asyncio.CancelledError):
            # Post-header failures terminate quietly. No token/DB/transport
            # diagnostics or synthetic event IDs are emitted to the stream.
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                settling = asyncio.gather(*tasks, return_exceptions=True)
                # Repeated external cancellation cannot abandon the physical
                # read join performed inside a canceled pump's fetch().
                while not settling.done():
                    try:
                        await asyncio.shield(settling)
                    except asyncio.CancelledError:
                        continue
            try:
                remaining = deadline-asyncio.get_running_loop().time()
                if started and not finished and remaining > 0:
                    # Auth/read failure still closes HTTP framing cleanly when
                    # transport permits, without extending the total deadline.
                    await asyncio.wait_for(send({"type": "http.response.body", "body": b"", "more_body": False}), remaining)
            except (Exception, asyncio.CancelledError):
                pass
            finally:
                self.service.limiter.release(lease)

    async def _pump(self, send, deadline):
        emitted = used = 0
        cursor = self.after
        heartbeat = time.monotonic()
        async def write(frame):
            nonlocal used
            if used + len(frame) > self.policy.max_bytes:
                return False
            await send({"type": "http.response.body", "body": frame, "more_body": True})
            used += len(frame)
            return True
        if not await write(b": connected\n\n"):
            return
        while emitted < self.cap and asyncio.get_running_loop().time() < deadline:
            page = await self.service.fetch(self.context, self.run_id, cursor,
                                            min(self.policy.batch_events, self.cap-emitted), deadline=deadline)
            for event in page.items:
                data = json.dumps(event.model_dump(mode="json"), ensure_ascii=True, allow_nan=False, separators=(",", ":"))
                frame = f"id: {event.sequence}\nevent: run_event\ndata: {data}\n\n".encode("utf-8")
                if not await write(frame):
                    return
                cursor = event.sequence
                emitted += 1
            if emitted >= self.cap:
                return
            now = time.monotonic()
            if now-heartbeat >= self.policy.heartbeat_seconds:
                if not await write(b": heartbeat\n\n"):
                    return
                heartbeat = now
            if not page.has_more:
                remaining = deadline-asyncio.get_running_loop().time()
                if remaining > 0:
                    await asyncio.sleep(min(self.policy.poll_seconds, remaining))
