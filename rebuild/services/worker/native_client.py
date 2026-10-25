"""Partial offline receiver seam. No supported default native constructor yet.

Explicit injected adapters are trusted code, not proof of SDK transport behavior.
No SDK import, environment discovery, process creation or Worker.start here.
"""
import asyncio
from dataclasses import dataclass, field
import math
import re
from uuid import UUID


class UnsupportedReceiver(Exception):
    def __init__(self):
        super().__init__("Pinned receiver child-client injection is unsupported")


class ReceiverFailure(Exception):
    def __init__(self):
        super().__init__("Receiver construction failed")


class ReceiverCleanupFailure(Exception):
    def __init__(self):
        super().__init__("Receiver cleanup remains unresolved")


@dataclass(frozen=True)
class ReceiverConfig:
    tenant_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    namespace: str
    workflow_name: str
    worker_name: str
    grpc_target: str
    rest_origin: str
    cleanup_seconds: float

    def __post_init__(self):
        if (any(type(v) is not UUID for v in (self.tenant_id,self.workflow_id,self.workflow_version_id))
            or type(self.namespace) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}_",self.namespace)
            or any(type(v) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}",v)
                or v.startswith(self.namespace) for v in (self.workflow_name,self.worker_name))
            or len(self.namespace+self.workflow_name)>100 or len(self.namespace+self.worker_name)>100
            or type(self.grpc_target) is not str or type(self.rest_origin) is not str
            or self.grpc_target != "127.0.0.1:7077" or self.rest_origin != "http://127.0.0.1:8888"
            or type(self.cleanup_seconds) not in (int,float) or not math.isfinite(self.cleanup_seconds)
            or not 0<self.cleanup_seconds<=5):
            raise ValueError("Invalid explicit receiver configuration")

    @property
    def normalized_workflow_name(self):
        return self.namespace+self.workflow_name

    @property
    def normalized_worker_name(self):
        return self.namespace+self.worker_name


@dataclass(frozen=True)
class ReceiverPolicy:
    config: ReceiverConfig
    token: str = field(repr=False)
    # Immutable closed nested policy: the future adapter must propagate it to
    # registration, every listener child and every recreated transport.
    settings_sources: tuple = field(default=("explicit_init",),init=False)
    grpc_options: tuple = field(default=(("grpc.enable_retries",0),("grpc.enable_http_proxy",0)),init=False)
    tls: tuple = field(default=(("strategy","none"),),init=False)
    health: tuple = field(default=(("enabled",False),("bind_address",None)),init=False)
    telemetry: tuple = field(default=(("enabled",False),),init=False)
    retry: tuple = field(default=(("max_attempts",1),("retry_429",False),("retry_not_found",False),("retry_transport_errors",False)),init=False)
    rest: tuple = field(default=(("trust_env",False),("proxy",None),("middlewares",()),("retry_connection",False)),init=False)
    lifecycle: tuple = field(default=(("debug",False),("disable_log_capture",True),("embedded",None),("enable_force_kill_sync_threads",False)),init=False)

    def __post_init__(self):
        if (type(self.config) is not ReceiverConfig or type(self.token) is not str
            or not 1<=len(self.token)<=8192 or re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,2}",self.token) is None):
            raise ValueError("Explicit receiver authentication required")


class ReceiverOwnership:
    """Adapter registers each exact child/client/channel as it creates it.

    No children are spawned here. Close callbacks must use only their registered
    resource; process-name/PID guessing and borrowed-resource closure are forbidden.
    """
    def __init__(self,seconds):
        self._seconds=seconds
        self._resources=[]
        self._task=None
        self.unresolved=()

    def register(self,resource,*,kind,close,owned):
        if (self._task is not None or len(self._resources)>=16 or kind not in ("child","client","channel")
            or type(owned) is not bool or not callable(close)
            or any(value is resource for value,_,_,_ in self._resources)):
            raise ValueError("Invalid exact receiver resource ownership")
        self._resources.append((resource,kind,close,owned))

    async def _close(self):
        tasks=[]
        async def invoke(callback):
            await callback()
        for _,_,callback,owned in reversed(self._resources):
            if owned: tasks.append(asyncio.create_task(invoke(callback)))
        failed=False
        if tasks:
            done,pending=await asyncio.wait(tasks,timeout=self._seconds*.8)
            failed=any(t.cancelled() or t.exception() is not None for t in done)
            for task in pending: task.cancel()
            if pending:
                settled,remaining=await asyncio.wait(pending,timeout=self._seconds*.2)
                for task in settled:
                    if not task.cancelled(): task.exception()
                self.unresolved=tuple(remaining)
                for task in remaining:
                    task.add_done_callback(lambda t:None if t.cancelled() else t.exception())
            failed=failed or bool(pending)
        if failed: raise ReceiverCleanupFailure()

    async def close(self):
        if self._task is None: self._task=asyncio.create_task(self._close())
        cancelled=False
        while not self._task.done():
            try: await asyncio.shield(self._task)
            except asyncio.CancelledError: cancelled=True
            except ReceiverCleanupFailure: break
        if cancelled:
            error=asyncio.CancelledError()
            if self.unresolved: error.add_note("Receiver cleanup remains unresolved")
            raise error
        return self._task.result()


class ReceiverHandle:
    def __init__(self,value,ownership):
        self.value=value
        self.ownership=ownership

    def __repr__(self): return "ReceiverHandle(partial_offline_seam=True)"

    async def close(self):
        return await self.ownership.close()

    async def __aenter__(self): return self

    async def __aexit__(self,*exc): await self.close()


async def construct_receiver(config,token,*,constructor=None):
    policy=ReceiverPolicy(config,token)
    if constructor is None:
        # Worker and child constructors cannot be safely redirected by the
        # accepted SDK injection hooks. Fail before ANY SDK config import.
        raise UnsupportedReceiver()
    if not callable(constructor): raise ValueError("Explicit receiver adapter required")
    ownership=ReceiverOwnership(config.cleanup_seconds)
    try:
        value=await constructor(policy,ownership)
        if value is None: raise ReceiverFailure()
    except BaseException as error:
        try: await ownership.close()
        except ReceiverCleanupFailure:
            raise ReceiverCleanupFailure() from None
        if isinstance(error,asyncio.CancelledError): raise
        if not isinstance(error,Exception): raise
        raise ReceiverFailure() from None
    return ReceiverHandle(value,ownership)
