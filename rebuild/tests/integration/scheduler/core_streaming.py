"""SSE actual-socket and actual Response.__call__ proof; Backend alone executes.

The runner injects its sole loopback listener URL/app. This fixture never starts
or stops a listener/database. Buffering TestClient proves only compatibility.
"""
import asyncio
from contextlib import contextmanager, ExitStack
import hashlib
import http.client
import json
import secrets
import threading
import time
import unittest
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

from sqlalchemy import text
from starlette.requests import Request

from services.api.errors import Problem
from services.api.runs import repository as repo
from services.api.runs.routes import accepts_sse
from services.api.streams import PrincipalContext, StreamPolicy, StreamLimiter, StreamService
from tests.integration.scheduler import core_journal, core_cancellation


class CoreStreamingProof(unittest.TestCase):
    runtime_url = runtime_app = None  # Injected by the sole Backend proof runner.
    case = core_journal.RunJournalProof.case
    create = core_journal.RunJournalProof.create
    error = core_journal.RunJournalProof.error
    tables = core_cancellation.CoreCancellationProof.tables
    snapshot = classmethod(core_cancellation.CoreCancellationProof.snapshot.__func__)

    @classmethod
    def setUpClass(cls):
        parsed = urlsplit(cls.runtime_url or "")
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 64111
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username
            or parsed.password or cls.runtime_app is None):
            raise RuntimeError("Backend-owned explicit loopback HTTP runtime required; no socket proof skipped")
        cls.host,cls.port = parsed.hostname,parsed.port
        core_journal.RunJournalProof.setUpClass.__func__(cls)
        cls.baseline = cls.snapshot()

    @classmethod
    def tearDownClass(cls):
        try:
            for old,new in zip(cls.baseline,cls.snapshot()):
                if any(new.get(k) != v for k,v in old.items()):
                    raise AssertionError("Preexisting Run/cancellation/event history changed")
        finally:
            core_journal.RunJournalProof.tearDownClass.__func__(cls)

    def new(self):
        result = self.create(self.case())
        self.assertEqual(result.status_code,202)
        return UUID(result.json()["id"])

    def viewer(self, run_id):
        principal,token = uuid4(),secrets.token_urlsafe(48)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.app.state.engine.begin() as conn:
            case = conn.execute(text("SELECT case_id FROM runs WHERE id=:r"),{"r":run_id}).scalar_one()
            conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:p,'stream-synthetic-viewer',:hash)"),{"p":principal,"hash":digest})
            conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,false)"),{"p":principal,"c":case})
        return principal,token,digest,case

    def row(self, run_id):
        with self.app.state.engine.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM runs WHERE id=:r"),{"r":run_id}).mappings().one())

    def events(self, run_id, count, note=""):
        # Add only harmless synthetic fixture events to this new Run. No worker,
        # output, mutation of old rows or invented completion is performed.
        with self.app.state.engine.begin() as conn:
            row = repo.locked_run(conn,run_id)
            conn.execute(text("""INSERT INTO run_events(run_id,sequence,type,payload)
                SELECT :r,:start+n,'queued',CAST(:payload AS jsonb) FROM generate_series(0,:last) AS n"""),
                {"r":run_id,"start":row["next_event_sequence"],"last":count-1,"payload":json.dumps({"status":"queued","note":note})})
            conn.execute(text("UPDATE runs SET next_event_sequence=next_event_sequence+:count WHERE id=:r"),{"r":run_id,"count":count})

    @contextmanager
    def connection(self, run_id, *, token=None, params=None, headers=None, timeout=3):
        conn = http.client.HTTPConnection(self.host,self.port,timeout=timeout)
        request_headers = {**(self.auth if token is None else {"Authorization":"Bearer "+token}),"Accept":"text/event-stream"}
        request_headers.update(headers or {})
        path = f"/api/v1/runs/{run_id}/events"
        if params:
            path += "?"+urlencode(params)
        try:
            conn.request("GET",path,headers=request_headers)
            yield conn.getresponse()
        finally:
            conn.close()

    def frame(self, response, *, allow_closed=False):
        fields,total = {},0
        for _ in range(64):
            try:
                raw = response.readline(65537)
            except (http.client.IncompleteRead, ConnectionResetError):
                if allow_closed:
                    # Revocation/timeout can truncate a frame. It is discarded;
                    # no synthetic final ID or claim of clean chunked EOF.
                    return None
                raise
            total += len(raw)
            self.assertLessEqual(total,65536)
            if not raw:
                return None
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                if "data" in fields:
                    self.assertEqual(fields.get("event"),"run_event")
                    value = json.loads(fields["data"])
                    self.assertEqual(fields.get("id"),str(value["sequence"]))
                    return value
                fields = {}
            elif not line.startswith(":"):
                key,value = line.split(":",1)
                self.assertNotIn(key,fields)
                fields[key] = value.lstrip(" ")
        self.fail("No bounded complete persisted frame")

    def wait_released(self, total=0):
        deadline = time.monotonic()+2
        while time.monotonic()<deadline:
            if self.runtime_app.state.event_streams.limiter.snapshot()["total"] == total:
                return
            time.sleep(.025)
        self.fail("Actual listener stream reservation was not released")

    def test_01_actual_incremental_http_disconnect_reconnect_and_order(self):
        run_id = self.new()
        before = self.row(run_id)
        started = time.monotonic()
        with self.connection(run_id,params={"limit":3}) as response:
            self.assertEqual(response.status,200)
            self.assertTrue(response.getheader("Content-Type").startswith("text/event-stream"))
            self.assertEqual(response.getheader("Cache-Control"),"no-store")
            self.assertEqual(response.getheader("X-Accel-Buffering"),"no")
            self.assertIsNone(response.getheader("Content-Length"))
            first = self.frame(response)
            self.assertEqual(first["sequence"],1)
            self.assertLess(time.monotonic()-started,2)
            # The first event arrived before these rows even existed.
            self.events(run_id,2)
            self.assertEqual(self.frame(response)["sequence"],2)
        self.wait_released()
        with self.connection(run_id,params={"limit":1},headers={"Last-Event-ID":"2"}) as response:
            self.assertEqual(self.frame(response)["sequence"],3)
            self.assertEqual(response.read(),b"")
        after = self.row(run_id)
        for key in ("status","revision","outcome","output_refs","attempt_id","fence"):
            self.assertEqual(after[key],before[key])

    def test_02_cursor_and_authority_errors_arrive_before_sse_headers(self):
        run_id = self.new()
        cases = [({"after":"2"},{},409),({"after":"-1"},{},422),({"after":"1.0"},{},422),
                 ({"after":"0"},{"Last-Event-ID":"1"},409),({}, {"Last-Event-ID":"+1"},422)]
        for params,headers,status in cases:
            with self.connection(run_id,params=params,headers=headers) as response:
                self.assertEqual(response.status,status)
                self.assertTrue(response.getheader("Content-Type").startswith("application/json"))
                response.read()
        foreign = self.create(self.case(self.auth_b),auth=self.auth_b).json()["id"]
        for unavailable in (foreign,uuid4()):
            with self.connection(unavailable) as response:
                self.assertEqual(response.status,404)
                response.read()
        self.wait_released()

    def test_03_exact_token_rotation_closes_live_stream_and_reconnect(self):
        run_id = self.new()
        principal,token,_,_ = self.viewer(run_id)
        with self.connection(run_id,token=token) as response:
            self.assertEqual(self.frame(response)["sequence"],1)
            with self.app.state.engine.begin() as conn:
                conn.execute(text("UPDATE principals SET token_hash=:hash WHERE id=:p"),{"p":principal,"hash":hashlib.sha256(secrets.token_bytes(32)).hexdigest()})
            self.assertIsNone(self.frame(response,allow_closed=True))
        with self.connection(run_id,token=token) as response:
            self.assertEqual(response.status,401)
            self.assertEqual(response.getheader("WWW-Authenticate"),"Bearer")
            response.read()
        self.wait_released()

    def test_04_grant_revocation_and_principal_deletion_close_live_stream(self):
        for deleted in (False,True):
            run_id = self.new()
            principal,token,_,case = self.viewer(run_id)
            with self.connection(run_id,token=token) as response:
                self.assertEqual(self.frame(response)["sequence"],1)
                with self.app.state.engine.begin() as conn:
                    conn.execute(text("DELETE FROM case_grants WHERE principal_id=:p AND case_id=:c"),{"p":principal,"c":case})
                    if deleted:
                        conn.execute(text("DELETE FROM principals WHERE id=:p"),{"p":principal})
                self.assertIsNone(self.frame(response,allow_closed=True))
            with self.connection(run_id,token=token) as response:
                self.assertEqual(response.status,401 if deleted else 404)
                response.read()
        self.wait_released()

    def test_05_actual_per_principal_global_limits_and_disconnect_release(self):
        run_id = self.new()
        viewers = [self.viewer(run_id) for _ in range(5)]
        with ExitStack() as stack:
            for viewer in viewers[:4]:
                for _ in range(2):
                    response = stack.enter_context(self.connection(run_id,token=viewer[1]))
                    self.assertEqual(response.status,200)
                    self.assertEqual(self.frame(response)["sequence"],1)
            self.assertEqual(self.runtime_app.state.event_streams.limiter.snapshot()["total"],8)
            for token in (viewers[0][1],viewers[4][1]):
                with self.connection(run_id,token=token) as response:
                    self.assertEqual(response.status,429)
                    self.assertEqual(json.loads(response.read())["code"],"stream_limit")
            deadline = time.monotonic()+1
            while self.runtime_app.state.engine.pool.checkedout() and time.monotonic()<deadline:
                time.sleep(.025)
            self.assertEqual(self.runtime_app.state.engine.pool.checkedout(),0)
        self.wait_released()
        with self.connection(run_id,token=viewers[0][1],params={"limit":1}) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(self.frame(response)["sequence"],1)

    def test_06_media_quality_json_compatibility_and_safe_data_framing(self):
        for header in (None,"*/*","text/event-stream;q=0","text/event-stream;q=0,*/*;q=1",
                       "text/event-stream;q=NaN","text/event-stream;q=2","text/event-stream;q=0.2,application/json;q=0.9"):
            self.assertFalse(accepts_sse(header))
        for header in ("text/event-stream","text/*","text/event-stream;q=0.7,application/json;q=0.2"):
            self.assertTrue(accepts_sse(header))
        run_id = self.new()
        note = "safe\nid: 999\ndata: forged\r\n\u0001"
        self.events(run_id,1,note)
        with self.connection(run_id,headers={"Accept":"text/event-stream;q=0"}) as response:
            self.assertEqual(response.status,200)
            self.assertEqual([v["sequence"] for v in json.loads(response.read())["items"]],[1,2])
        with self.connection(run_id,params={"after":1,"limit":1}) as response:
            self.assertEqual(self.frame(response)["payload"]["note"],note)
            self.assertIsNone(self.frame(response))

    def test_07_actual_event_cap_and_json_history_gaps(self):
        run_id = self.new()
        self.events(run_id,104)
        with self.connection(run_id,params={"limit":100}) as response:
            ids = [self.frame(response)["sequence"] for _ in range(100)]
            self.assertEqual(ids,list(range(1,101)))
            self.assertIsNone(self.frame(response))
        with self.connection(run_id,params={"limit":5},headers={"Last-Event-ID":"100"}) as response:
            self.assertEqual([self.frame(response)["sequence"] for _ in range(5)],list(range(101,106)))
            self.assertIsNone(self.frame(response))

    def test_08_actual_heartbeat_has_no_event_id_or_state_effect(self):
        run_id = self.new()
        before = self.row(run_id)
        with self.connection(run_id,params={"after":1},timeout=7) as response:
            block,heartbeat = [],False
            deadline = time.monotonic()+6.5
            while time.monotonic()<deadline:
                raw = response.readline(8193)
                if not raw:
                    break
                line = raw.decode().rstrip("\r\n")
                if not line:
                    if any("heartbeat" in v for v in block):
                        self.assertTrue(all(v.startswith(":") for v in block))
                        heartbeat = True
                        break
                    block = []
                else:
                    block.append(line)
            self.assertTrue(heartbeat)
        self.wait_released()
        self.assertEqual(self.row(run_id),before)

    @staticmethod
    def read_resources(service):
        snapshot = service.resource_snapshot()
        return {key:snapshot[key] for key in ("active_reads","checked_out")}

    async def asgi_response(self, run_id, viewer, policy, *, blocked=False, read_page=None, disconnect=False):
        engine = self.app.state.engine
        limiter = StreamLimiter()
        service = StreamService(lambda:engine,read_page or repo.read_stream_page,policy=policy,limiter=limiter)
        scope = {"type":"http","http_version":"1.1","method":"GET","scheme":"http","path":"/stream-proof",
                 "raw_path":b"/stream-proof","query_string":b"","headers":[],"client":("127.0.0.1",1),"server":("127.0.0.1",64111),
                 "asgi":{"version":"3.0","spec_version":"2.3"}}
        disconnect_now = asyncio.Event()
        first_request = True
        async def receive():
            nonlocal first_request
            if first_request:
                first_request = False
                return {"type":"http.request","body":b"","more_body":False}
            await disconnect_now.wait()
            return {"type":"http.disconnect"}
        messages = []
        pool_counts_at_send = []
        read_resources_at_send = []
        async def send(message):
            # The response intentionally catches post-header exceptions. Record
            # observations here, assert outside its boundary so failures cannot
            # be mistaken for successful quiet stream termination.
            pool_counts_at_send.append(engine.pool.checkedout())
            read_resources_at_send.append(self.read_resources(service))
            messages.append(dict(message))
            if message["type"] == "http.response.body" and message.get("body"):
                if disconnect:
                    disconnect_now.set()
                if blocked:
                    await asyncio.Event().wait()
        request = Request(scope,receive)
        context = PrincipalContext(viewer[0],viewer[2])
        try:
            response = await service.open(request,context,run_id,0,100)
            started = time.monotonic()
            await asyncio.wait_for(response(scope,receive,send),timeout=2)
            elapsed = time.monotonic()-started
            self.assertTrue(pool_counts_at_send)
            self.assertEqual(pool_counts_at_send,[0]*len(pool_counts_at_send))
            self.assertEqual(read_resources_at_send,[{"active_reads":0,"checked_out":0}]*len(read_resources_at_send))
            self.assertEqual(limiter.snapshot()["total"],0)
            self.assertEqual(engine.pool.checkedout(),0)
            self.assertEqual(self.read_resources(service),{"active_reads":0,"checked_out":0})
            self.assertEqual(service.resource_snapshot()["pending_reads"],0)
            self.assertEqual(service.resource_snapshot()["global_admitted_reads"],0)
            return messages,elapsed
        finally:
            service.close()

    def test_09_actual_asgi_response_byte_event_and_time_caps(self):
        run_id = self.new()
        viewer = self.viewer(run_id)
        self.events(run_id,5,"x"*100)
        messages,_ = asyncio.run(self.asgi_response(run_id,viewer,StreamPolicy(max_events=2,lifetime_seconds=.8)))
        body = b"".join(v.get("body",b"") for v in messages)
        self.assertEqual(body.count(b"\nid: ")+int(body.startswith(b"id: ")),2)
        messages,_ = asyncio.run(self.asgi_response(run_id,viewer,StreamPolicy(max_bytes=128,lifetime_seconds=.8)))
        self.assertLessEqual(sum(len(v.get("body",b"")) for v in messages),128)
        messages,elapsed = asyncio.run(self.asgi_response(run_id,viewer,StreamPolicy(lifetime_seconds=.1)))
        self.assertLess(elapsed,1)

    def test_10_actual_asgi_backpressure_disconnect_release_and_no_db_wait(self):
        run_id = self.new()
        viewer = self.viewer(run_id)
        before = self.row(run_id)
        _,elapsed = asyncio.run(self.asgi_response(run_id,viewer,StreamPolicy(lifetime_seconds=.1),blocked=True))
        self.assertLess(elapsed,1)
        asyncio.run(self.asgi_response(run_id,viewer,StreamPolicy(lifetime_seconds=.8),disconnect=True))
        self.assertEqual(self.row(run_id),before)

    def test_11_actual_asgi_fetch_error_releases_concurrency_without_diagnostics(self):
        run_id = self.new()
        viewer = self.viewer(run_id)
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError("PRIVATE_STREAM_FAILURE")
            return repo.read_stream_page(*args)
        messages,_ = asyncio.run(self.asgi_response(run_id,viewer,StreamPolicy(lifetime_seconds=.8),read_page=fail_second))
        self.assertGreater(calls,1)
        self.assertNotIn(b"PRIVATE_STREAM_FAILURE",b"".join(v.get("body",b"") for v in messages))

    def test_12_read_helper_is_strict_rechecks_digest_and_preserves_history(self):
        run_id = self.new()
        viewer = self.viewer(run_id)
        before = self.row(run_id)
        with self.app.state.engine.connect() as conn:
            page = repo.read_stream_page(conn,viewer[0],viewer[2],run_id,0,10)
            self.assertEqual([v.sequence for v in page.items],[1])
            for bad_limit in (True,11,0):
                with self.assertRaises(Problem):
                    repo.read_stream_page(conn,viewer[0],viewer[2],run_id,0,bad_limit)
        self.assertEqual(self.row(run_id),before)
        self.assertNotIn(viewer[2],repr(PrincipalContext(viewer[0],viewer[2])))

    def test_13_abandoned_response_and_rejected_initialization_reserve_nothing(self):
        run_id = self.new()
        viewer = self.viewer(run_id)
        async def scenario():
            limiter = StreamLimiter()
            engine = self.app.state.engine
            service = StreamService(lambda:engine,repo.read_stream_page,policy=StreamPolicy(lifetime_seconds=.1),limiter=limiter)
            request = Request({"type":"http","method":"GET","path":"/stream-proof","headers":[],"query_string":b""})
            context = PrincipalContext(viewer[0],viewer[2])
            try:
                uninvoked = await service.open(request,context,run_id,0,1)
                self.assertIsNotNone(uninvoked)
                self.assertEqual(limiter.snapshot()["total"],0)
                self.assertEqual(engine.pool.checkedout(),0)
                with self.assertRaises(Exception):
                    await service.open(request,PrincipalContext(viewer[0],"0"*64),run_id,0,1)
                self.assertEqual(limiter.snapshot()["total"],0)
                self.assertEqual(engine.pool.checkedout(),0)
                self.assertEqual(self.read_resources(service),{"active_reads":0,"checked_out":0})
            finally:
                service.close()
        asyncio.run(scenario())

    def test_14_blocked_post_header_read_hits_database_timeout_and_releases(self):
        run_id = self.new()
        viewer = self.viewer(run_id)
        before = self.row(run_id)
        calls, sqlstates = 0, []
        def blocked_second(conn,*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                try:
                    conn.execute(text("SELECT pg_sleep(1)"))
                except Exception as exc:
                    # Capture evidence outside the quiet response boundary.
                    sqlstates.append(getattr(getattr(exc,"orig",None),"sqlstate",None))
                    raise
            return repo.read_stream_page(conn,*args)
        messages,elapsed = asyncio.run(self.asgi_response(run_id,viewer,
            StreamPolicy(lifetime_seconds=.8),read_page=blocked_second))
        self.assertGreaterEqual(calls,2)
        self.assertEqual(sqlstates,["57014"])
        self.assertLess(elapsed,1)
        body = b"".join(v.get("body",b"") for v in messages)
        for diagnostic in (b"pg_sleep",b"statement timeout",b"57014",b"QueryCanceled"):
            self.assertNotIn(diagnostic,body)
        self.assertEqual(self.row(run_id),before)

    async def physical_read_scenario(self,run_id,viewer,mode):
        core = self.app.state.engine
        entered,query_ended,release_finalizer = threading.Event(),threading.Event(),threading.Event()
        state = {"calls":0}
        def blocked(conn,*args):
            state["calls"] += 1
            if state["calls"] == 2:
                state["pid"] = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
                state["timeout"] = conn.execute(text("SHOW statement_timeout")).scalar_one()
                entered.set()
                try:
                    conn.execute(text("SELECT pg_sleep(1)"))
                except Exception as exc:
                    state["sqlstate"] = getattr(getattr(exc,"orig",None),"sqlstate",None)
                    raise
                finally:
                    query_ended.set()
                    # Explicit synthetic finalizer delay exposes premature slot
                    # release after coroutine cancellation. No thread kill.
                    if not release_finalizer.wait(.8):
                        state["finalizer_watchdog"] = True
            return repo.read_stream_page(conn,*args)
        limiter = StreamLimiter()
        policy = StreamPolicy(lifetime_seconds=.2 if mode == "deadline" else .8)
        service = StreamService(lambda:core,blocked,policy=policy,limiter=limiter)
        scope = {"type":"http","method":"GET","path":"/physical-read","headers":[],"query_string":b"",
                 "asgi":{"version":"3.0","spec_version":"2.3"}}
        disconnect_now = asyncio.Event()
        async def receive():
            await disconnect_now.wait()
            return {"type":"http.disconnect"}
        messages=[]
        async def send(message):
            messages.append(dict(message))
        task=None
        try:
            response=await service.open(Request(scope,receive),PrincipalContext(viewer[0],viewer[2]),run_id,0,100)
            start=time.monotonic()
            task=asyncio.create_task(response(scope,receive,send))
            witness=False
            deadline=start+.15
            while time.monotonic()<deadline:
                if entered.is_set():
                    with core.connect() as observer:
                        witness=observer.execute(text("""SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                            WHERE pid=:pid AND state='active' AND wait_event='PgSleep')"""),{"pid":state["pid"]}).scalar_one()
                    if witness:
                        break
                await asyncio.sleep(.005)
            self.assertTrue(witness,"Physical PostgreSQL sleep must be witnessed before cancellation/deadline")
            self.assertEqual(limiter.snapshot()["total"],1)
            self.assertEqual(self.read_resources(service),{"active_reads":1,"checked_out":1})
            if mode == "disconnect":
                disconnect_now.set()
            elif mode == "external":
                task.cancel()
                await asyncio.sleep(.01)
                task.cancel()
            timeout=time.monotonic()+.6
            while not query_ended.is_set() and time.monotonic()<timeout:
                await asyncio.sleep(.005)
            self.assertTrue(query_ended.is_set())
            await asyncio.sleep(.02)
            # Physical callback still owns its connection through the synthetic
            # finalizer. Assertions live outside swallowed response callbacks.
            self.assertFalse(task.done())
            self.assertEqual(limiter.snapshot()["total"],1)
            self.assertEqual(self.read_resources(service),{"active_reads":1,"checked_out":1})
            release_finalizer.set()
            await asyncio.wait_for(task,timeout=1.5)
            self.assertLess(time.monotonic()-start,policy.lifetime_seconds+1.5)
            self.assertEqual(state.get("sqlstate"),"57014")
            self.assertNotIn("finalizer_watchdog",state)
            timeout_value=state["timeout"]
            self.assertTrue(timeout_value.endswith("ms"))
            milliseconds=int(timeout_value[:-2])
            self.assertGreater(milliseconds,0)
            self.assertLessEqual(milliseconds,200 if mode=="deadline" else 250)
            self.assertEqual(self.read_resources(service),{"active_reads":0,"checked_out":0})
            self.assertEqual(service.resource_snapshot()["pending_reads"],0)
            self.assertEqual(service.resource_snapshot()["global_admitted_reads"],0)
            self.assertEqual(limiter.snapshot()["total"],0)
            with core.connect() as observer:
                active=observer.execute(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=:pid AND state='active')"),{"pid":state["pid"]}).scalar_one()
            self.assertFalse(active)
            body=b"".join(v.get("body",b"") for v in messages)
            for diagnostic in (b"pg_sleep",b"57014",b"statement timeout"):
                self.assertNotIn(diagnostic,body)
        finally:
            release_finalizer.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait_for(asyncio.shield(task),timeout=2)
            service.close()

    def test_15_deadline_during_witnessed_physical_sql_waits_for_settlement(self):
        run_id=self.new()
        before=self.row(run_id)
        asyncio.run(self.physical_read_scenario(run_id,self.viewer(run_id),"deadline"))
        self.assertEqual(self.row(run_id),before)

    def test_16_disconnect_during_witnessed_physical_sql_retains_slot(self):
        run_id=self.new()
        before=self.row(run_id)
        asyncio.run(self.physical_read_scenario(run_id,self.viewer(run_id),"disconnect"))
        self.assertEqual(self.row(run_id),before)

    def test_17_repeated_cancel_during_witnessed_physical_sql_retains_slot(self):
        run_id=self.new()
        before=self.row(run_id)
        asyncio.run(self.physical_read_scenario(run_id,self.viewer(run_id),"external"))
        self.assertEqual(self.row(run_id),before)

    async def preheader_read_scenario(self,run_id,viewer,shutdown=False):
        engine=self.app.state.engine
        entered,release,ended=threading.Event(),threading.Event(),threading.Event()
        state={}
        def blocked(conn,*args):
            state["pid"]=conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            entered.set()
            try:
                conn.execute(text("SELECT pg_sleep(1)"))
            finally:
                ended.set()
                release.wait(1)
            return repo.read_stream_page(conn,*args)
        limiter=StreamLimiter()
        service=StreamService(lambda:engine,blocked,limiter=limiter)
        request=Request({"type":"http","method":"GET","path":"/preheader","headers":[],"query_string":b""})
        task=asyncio.create_task(service.open(request,PrincipalContext(viewer[0],viewer[2]),run_id,0,1))
        drain=None
        try:
            witness=False
            until=time.monotonic()+.2
            while time.monotonic()<until:
                if entered.is_set():
                    with engine.connect() as observer:
                        witness=observer.execute(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=:pid AND wait_event='PgSleep' AND state='active')"),{"pid":state["pid"]}).scalar_one()
                    if witness: break
                await asyncio.sleep(.005)
            self.assertTrue(witness)
            if shutdown:
                self.assertFalse(service.close())
                drain=asyncio.create_task(service.aclose())
                await asyncio.sleep(.01)
                drain.cancel()
            else:
                task.cancel()
                await asyncio.sleep(.01)
                task.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(task.done())
            if drain is not None: self.assertFalse(drain.done())
            self.assertEqual(limiter.snapshot()["total"],0)
            self.assertEqual(self.read_resources(service),{"active_reads":1,"checked_out":1})
            release.set()
            results=await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),timeout=1.5)
            self.assertIsInstance(results[0],BaseException)
            if drain is not None:
                await asyncio.wait_for(asyncio.gather(drain,return_exceptions=True),timeout=1.5)
            self.assertTrue(ended.is_set())
            self.assertEqual(self.read_resources(service),{"active_reads":0,"checked_out":0})
            self.assertEqual(service.resource_snapshot()["pending_reads"],0)
            self.assertEqual(service.resource_snapshot()["global_admitted_reads"],0)
            self.assertTrue(service.close())
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            if drain is not None: await asyncio.gather(drain,return_exceptions=True)
            await service.aclose()

    def test_18_canceled_preheader_read_settles_without_stream_slot(self):
        run_id=self.new()
        asyncio.run(self.preheader_read_scenario(run_id,self.viewer(run_id)))

    def test_19_physical_read_admission_is_process_wide_before_queue(self):
        run_id=self.new()
        viewer=self.viewer(run_id)
        engine=self.app.state.engine
        release=threading.Event()
        count=0
        guard=threading.Lock()
        def held(conn,*args):
            nonlocal count
            with guard: count+=1
            release.wait(1.5)  # Synthetic finalizer/admission hold, no network.
            return repo.read_stream_page(conn,*args)
        async def scenario():
            services=[StreamService(lambda:engine,held,limiter=StreamLimiter()) for _ in range(2)]
            context=PrincipalContext(viewer[0],viewer[2])
            request=Request({"type":"http","method":"GET","path":"/admission","headers":[],"query_string":b""})
            tasks=[asyncio.create_task(services[i%2].open(request,context,run_id,0,1)) for i in range(8)]
            try:
                until=time.monotonic()+1
                while count<8 and time.monotonic()<until: await asyncio.sleep(.005)
                self.assertEqual(count,8)
                self.assertEqual(services[0].resource_snapshot()["global_admitted_reads"],8)
                with self.assertRaises(Problem) as caught:
                    await services[0].open(request,context,run_id,0,1)
                self.assertEqual(caught.exception.status,503)
                self.assertEqual(count,8)
                self.assertEqual(sum(self.read_resources(s)["active_reads"] for s in services),8)
                self.assertEqual(sum(s.limiter.snapshot()["total"] for s in services),0)
                release.set()
                await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=1.5)
                for service in services:
                    self.assertEqual(self.read_resources(service),{"active_reads":0,"checked_out":0})
                    self.assertEqual(service.resource_snapshot()["pending_reads"],0)
                    self.assertEqual(service.resource_snapshot()["global_admitted_reads"],0)
            finally:
                release.set()
                await asyncio.gather(*tasks,return_exceptions=True)
                for service in services: await service.aclose()
        asyncio.run(scenario())

    def test_20_shutdown_drains_physical_read_before_dispose(self):
        run_id=self.new()
        asyncio.run(self.preheader_read_scenario(run_id,self.viewer(run_id),shutdown=True))


if __name__ == "__main__":
    unittest.main()
