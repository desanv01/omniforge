"""Explicit owned async transports; import is inert, construction is opt-in.

Injected constructors transfer ownership explicitly. Borrowed resources are never
mutated or closed. No SDK configuration, environment, token or proxy discovery.
This seam performs no probe, registration, submission or readiness check.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib.metadata import version
import ipaddress
import math
import re
from urllib.parse import urlsplit

from services.worker.hatchet_port import RawSdkClient


GRPC_OPTIONS = (("grpc.enable_retries",0),("grpc.enable_http_proxy",0),
                ("grpc.max_receive_message_length",65536))
PINS = {"hatchet-sdk":"1.41.1","aiohttp":"3.14.5","grpcio":"1.84.1"}


class ConstructionError(Exception):
    def __init__(self):
        super().__init__("Explicit transport construction failed")


class CleanupError(Exception):
    def __init__(self,codes):
        self.codes = tuple(codes)
        super().__init__("Transport cleanup unresolved")


def _host(value):
    if not value or not value.isascii() or "%" in value:
        raise ValueError("Explicit transport destination required")
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        if len(value)>253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",part) for part in value.split(".")):
            raise ValueError("Explicit transport destination required") from None
        return False


@dataclass(frozen=True)
class TransportConfig:
    grpc_target: str
    rest_origin: str
    mode: str
    ca_pem: bytes | None = field(default=None,repr=False)
    cleanup_seconds: float = 1.0

    def __post_init__(self):
        try:
            if type(self.grpc_target) is not str or type(self.rest_origin) is not str or self.mode not in ("tls","development"):
                raise ValueError()
            if any(ord(c)<=32 or ord(c)>=127 for c in self.grpc_target+self.rest_origin):
                raise ValueError()
            grpc = urlsplit("//"+self.grpc_target)
            rest = urlsplit(self.rest_origin)
            if (grpc.username or grpc.password or grpc.path or grpc.query or grpc.fragment or not grpc.port
                or rest.username or rest.password or rest.path not in ("","/") or rest.query or rest.fragment
                or rest.scheme not in ("http","https")):
                raise ValueError()
            grpc_local,rest_local = _host(grpc.hostname),_host(rest.hostname)
            if rest.port is not None and not 1<=rest.port<=65535:
                raise ValueError()
            if self.mode == "development":
                if not grpc_local or not rest_local or rest.scheme != "http" or self.ca_pem is not None:
                    raise ValueError()
            elif (rest.scheme != "https" or type(self.ca_pem) is not bytes or not 1<=len(self.ca_pem)<=65536
                  or not self.ca_pem.startswith(b"-----BEGIN CERTIFICATE-----")):
                raise ValueError()
            if (type(self.cleanup_seconds) not in (int,float) or not math.isfinite(self.cleanup_seconds)
                or not 0<self.cleanup_seconds<=5):
                raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise ValueError("Invalid explicit transport configuration") from None


@dataclass(frozen=True)
class Resource:
    value: object = field(repr=False)
    owned: bool = True

    def __post_init__(self):
        if type(self.owned) is not bool or not callable(getattr(self.value,"close",None)):
            raise ValueError("Explicit async resource ownership required")


def _pins():
    if any(version(name)!=pin for name,pin in PINS.items()):
        raise ConstructionError()


def _default_channel(config,options):
    _pins()
    import grpc
    if config.mode == "development":
        value = grpc.aio.insecure_channel(config.grpc_target,options=options,interceptors=())
    else:
        credentials = grpc.ssl_channel_credentials(root_certificates=config.ca_pem)
        value = grpc.aio.secure_channel(config.grpc_target,credentials,options=options,interceptors=())
    return Resource(value)


def _default_stub(channel):
    _pins()
    from hatchet_sdk.contracts.workflows_pb2_grpc import WorkflowServiceStub
    return WorkflowServiceStub(channel)


async def _default_session(config,headers):
    _pins()
    import aiohttp
    import ssl
    tls = False
    if config.mode == "tls":
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        tls.load_verify_locations(cadata=config.ca_pem.decode("ascii"))
    # Connector ownership transfers to the session. No ambient trust/proxy/cookie
    # discovery, redirects or SDK retry wrapper is introduced here.
    connector = aiohttp.TCPConnector(ssl=tls,limit=2)
    try:
        session = aiohttp.ClientSession(connector=connector,connector_owner=True,
            headers=headers,trust_env=False,auto_decompress=False,middlewares=(),
            proxy=None,trace_configs=[],cookie_jar=aiohttp.DummyCookieJar())
    except BaseException:
        await connector.close()
        raise
    return Resource(session)


@dataclass(frozen=True)
class Constructors:
    channel: object = _default_channel
    session: object = _default_session
    stub: object = _default_stub

    def __post_init__(self):
        if not all(callable(v) for v in (self.channel,self.session,self.stub)):
            raise ValueError("Explicit transport constructors required")


class Transport:
    def __init__(self,seconds):
        self.client = None
        self._resources = []
        self._cleanup_task = None
        self._seconds = seconds
        self.cleanup_codes = ()
        self.unresolved_cleanup = ()

    def __repr__(self):
        return "Transport(owned_resources="+str(sum(r.owned for _,r in self._resources))+")"

    async def _close(self):
        tasks = {}
        codes = []
        for name,resource in reversed(self._resources):
            if resource.owned:
                async def close_one(value=resource.value):
                    await value.close()
                tasks[asyncio.create_task(close_one())] = name
        if tasks:
            reserve = min(.05,self._seconds/4)
            done,pending = await asyncio.wait(tasks,timeout=self._seconds-reserve)
            for task in done:
                if task.cancelled() or task.exception() is not None:
                    codes.append(tasks[task]+"_close_failed")
            for task in pending:
                codes.append(tasks[task]+"_close_timeout")
                task.cancel()
            if pending:
                settled,unresolved = await asyncio.wait(pending,timeout=reserve)
                for task in settled:
                    if not task.cancelled():
                        task.exception()
                self.unresolved_cleanup = tuple(unresolved)
                for task in unresolved:
                    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self.client = None
        self.cleanup_codes = tuple(sorted(codes))
        if codes:
            raise CleanupError(self.cleanup_codes)

    async def close(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._close())
        interrupted = False
        while not self._cleanup_task.done():
            try:
                await asyncio.shield(self._cleanup_task)
            except asyncio.CancelledError:
                interrupted = True
            except CleanupError:
                break
        if interrupted:
            error = asyncio.CancelledError()
            if self.cleanup_codes:
                error.add_note("Transport cleanup unresolved")
            raise error
        return self._cleanup_task.result()


@asynccontextmanager
async def open_transport(config,token,*,constructors=None):
    if (type(config) is not TransportConfig or type(token) is not str or not 1<=len(token)<=8192
        or re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,2}",token) is None
        or (constructors is not None and type(constructors) is not Constructors)):
        raise ValueError("Explicit transport inputs required")
    hooks = constructors or Constructors()
    transport = Transport(config.cleanup_seconds)
    try:
        channel = hooks.channel(config,GRPC_OPTIONS)
        if type(channel) is not Resource:
            raise ConstructionError()
        transport._resources.append(("channel",channel))
        stub = hooks.stub(channel.value)
        session = hooks.session(config,{"Authorization":"Bearer "+token})
        # Default session owns a temporary connector until ClientSession accepts
        # it. Injected session constructors may also be asynchronous.
        if hasattr(session,"__await__"):
            session = await session
        if type(session) is not Resource:
            raise ConstructionError()
        transport._resources.append(("session",session))
        if session.owned:
            session.value._retry_connection = False
        if getattr(session.value,"headers",{}).get("Authorization") != "Bearer "+token:
            raise ConstructionError()
        transport.client = RawSdkClient(trigger_rpc=stub.TriggerWorkflow,session=session.value,
            base_url=config.rest_origin,grpc_metadata=(("authorization","bearer "+token),),sdk_attempts=1)
        token = None
    except asyncio.CancelledError as cancelled:
        try:
            await transport.close()
        except CleanupError:
            cancelled.add_note("Transport cleanup unresolved")
        raise
    except Exception:
        await transport.close()
        raise ConstructionError() from None
    try:
        yield transport
    finally:
        await transport.close()
