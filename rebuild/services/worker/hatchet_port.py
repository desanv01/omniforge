"""B3A injected asynchronous boundary. No SDK/client/session/channel constructed.

Not wired to the synchronous B2 fake dispatcher. Live engine guarantees remain
unproved; every lookup failure/empty/incomplete result is unknown, never absent.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import time
from urllib.parse import urlsplit

from services.worker.hatchet_contracts import (
    Binding, Collision, DispatchSpec, Observation, Policy, Result, STATUSES,
    TransportFailure, seconds, uuid_value, verify_observed_payload,
)


def _pinned():
    if version("hatchet-sdk") != "1.41.1":
        raise ValueError("Unverified SDK version")


def trigger_request(binding: Binding, spec: DispatchSpec):
    """Pure pinned serializer. options.key is intentionally not used for dedup."""
    _pinned()
    from hatchet_sdk.clients.admin import AdminClient
    from hatchet_sdk.types.trigger import TriggerWorkflowOptions
    admin = object.__new__(AdminClient)  # serializer only; no client constructor.
    return admin._prepare_workflow_request(binding.workflow_name, json.dumps(spec.payload(), sort_keys=True),
        TriggerWorkflowOptions(additional_metadata=spec.metadata(binding)))


def idempotency_definition(ttl_seconds=3600):
    """Candidate workflow-definition protobuf, not installed or engine-verified."""
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86400:
        raise ValueError("Invalid idempotency TTL")
    _pinned()
    from hatchet_sdk.types.idempotency import TTLBasedIdempotencyConfig
    return TTLBasedIdempotencyConfig(key_expression="input.dispatch_identity",
        ttl=timedelta(seconds=ttl_seconds)).to_proto()


class RawSdkClient:
    """Injected raw async gRPC trigger and aiohttp-compatible session.

    High-level SDK retry wrappers are bypassed. Caller supplies a retry-disabled
    raw channel, approved destination and already-authorized session/metadata.
    This class never discovers credentials, constructs clients or opens channels.
    """
    def __init__(self, *, trigger_rpc, session, base_url, grpc_metadata=(), sdk_attempts=1):
        if type(sdk_attempts) is not int or sdk_attempts != 1:
            raise ValueError("SDK attempts must be one")
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Explicit scheduler origin required")
        self._rpc, self._session = trigger_rpc, session
        self._base = base_url.rstrip("/")
        self._metadata = grpc_metadata
        self._session_policy()

    def _session_policy(self):
        # Pinned aiohttp private connection-retry flag must be disabled by the
        # external factory BEFORE injection. Do not silently mutate a live client.
        if (getattr(self._session, "trust_env", None) is not False
            or getattr(self._session, "_retry_connection", None) is not False
            or getattr(self._session, "auto_decompress", None) is not False
            or getattr(self._session, "_middlewares", None) not in ((), [])):
            raise ValueError("Retry-free explicit async transport required")

    async def trigger(self, binding, spec, timeout):
        seconds(timeout)
        try:
            async with asyncio.timeout(timeout):
                response = await self._rpc(trigger_request(binding, spec), timeout=timeout,
                                           metadata=self._metadata)
                return uuid_value(response.workflow_run_id)
        except TimeoutError:
            raise TimeoutError() from None
        except Exception as exc:
            _pinned()
            from hatchet_sdk.exceptions import IdempotencyCollisionError
            if isinstance(exc, IdempotencyCollisionError):
                raise Collision(exc.existing_run_external_id) from None
            import grpc
            from grpc_status import rpc_status
            from hatchet_sdk.contracts.v1 import workflows_pb2
            if isinstance(exc, grpc.RpcError) and exc.code() == grpc.StatusCode.ALREADY_EXISTS:
                try:
                    status = rpc_status.from_call(exc)
                    for detail in status.details:
                        if detail.Is(workflows_pb2.IdempotencyCollisionError.DESCRIPTOR):
                            info = workflows_pb2.IdempotencyCollisionError()
                            detail.Unpack(info)
                            raise Collision(info.existing_run_external_id) from None
                except Collision:
                    raise
                except Exception:
                    pass
            raise TransportFailure() from None

    async def _request(self, method, path, timeout, *, params=None, body=None):
        seconds(timeout)
        self._session_policy()
        import aiohttp
        try:
            async with asyncio.timeout(timeout):
                async with self._session.request(method, self._base + path, params=params,
                    json=body, allow_redirects=False,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                    timeout=aiohttp.ClientTimeout(total=timeout, connect=min(2, timeout),
                                                 sock_connect=min(2, timeout), sock_read=timeout)) as response:
                    if response.status not in (200, 201, 202, 204):
                        raise TransportFailure()
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise TransportFailure()
                    data = bytearray()
                    while True:
                        chunk = await response.content.read(min(8192, 65537-len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                        if len(data) > 65536:
                            raise TransportFailure()
                    if not data:
                        return {}
                    if response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                        raise TransportFailure()
                    value = json.loads(data)
                    if type(value) is not dict:
                        raise TransportFailure()
                    return value
        except TimeoutError:
            raise TimeoutError() from None
        except Exception:
            raise TransportFailure() from None

    async def list_runs(self, binding, params, timeout):
        return await self._request("GET", f"/api/v1/stable/tenants/{binding.tenant_id}/workflow-runs",
                                   timeout, params=params)

    async def get_run(self, root_id, timeout):
        return await self._request("GET", f"/api/v1/stable/workflow-runs/{uuid_value(root_id)}", timeout)

    async def cancel(self, binding, root_id, timeout):
        await self._request("POST", f"/api/v1/stable/tenants/{binding.tenant_id}/tasks/cancel",
                            timeout, body={"externalIds": [str(uuid_value(root_id))]})


class HatchetPort:
    def __init__(self, client, binding: Binding, policy: Policy = Policy(), *, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc)):
        self.client, self.binding, self.policy = client, binding, policy
        self.clock, self.now = clock, now

    def _remaining(self, end):
        remaining = end-self.clock()
        if remaining <= 0:
            raise TimeoutError()
        return min(remaining, self.policy.total_seconds)

    def _correlation(self, item, spec):
        if (uuid_value(item["tenantId"]) != self.binding.tenant_id
            or uuid_value(item["workflowId"]) != self.binding.workflow_id
            or uuid_value(item["workflowVersionId"]) != self.binding.workflow_version_id
            or item["status"] not in STATUSES):
            raise ValueError("Observation binding mismatch")
        metadata = item["additionalMetadata"]
        if type(metadata) is not dict or any(metadata.get(k) != v for k, v in spec.metadata(self.binding).items()):
            raise ValueError("Observation correlation mismatch")

    async def _details(self, spec, root_id, end):
        value = await self.client.get_run(root_id, self._remaining(end))
        root, tasks = value["run"], value["tasks"]
        self._correlation(root, spec)
        verify_observed_payload(root["input"], spec)
        if uuid_value(root["metadata"]["id"]) != root_id or type(tasks) is not list or not 1 <= len(tasks) <= 50:
            raise ValueError("Invalid root execution details")
        ids = set()
        for task in tasks:
            self._correlation(task, spec)
            if task["type"] != "TASK" or uuid_value(task["workflowRunExternalId"]) != root_id:
                raise ValueError("Task does not belong to root execution")
            ids.add(uuid_value(task["taskExternalId"]))
        return Observation(root_id, tuple(sorted(ids, key=str)), root["status"])

    async def submit(self, spec: DispatchSpec):
        end, candidates = self.clock()+self.policy.total_seconds, ()
        try:
            async with asyncio.timeout(self.policy.total_seconds):
                try:
                    root_id = uuid_value(await self.client.trigger(self.binding, spec, self._remaining(end)))
                except Collision as collision:
                    root_id = collision.existing_id
                candidates = (root_id,)
                observed = await self._details(spec, root_id, end)
                return Result("acknowledged", (observed,), candidates, "verified")
        except TimeoutError:
            return Result("unknown", candidate_ids=candidates, reason="deadline")
        except Exception:
            return Result("unknown", candidate_ids=candidates, reason="unresolved")

    async def lookup(self, spec: DispatchSpec):
        end = self.clock()+self.policy.total_seconds
        try:
            async with asyncio.timeout(self.policy.total_seconds):
                until, since = self.now()+timedelta(minutes=2), spec.created_at-timedelta(minutes=2)
                if since > until or until-since > timedelta(days=7):
                    return Result("unknown", reason="lookup_bound")
                roots, base = {}, None
                for page in range(self.policy.max_pages):
                    params = [("since", since.isoformat()), ("until", until.isoformat()),
                        ("offset", str(page*self.policy.page_size)), ("limit", str(self.policy.page_size)),
                        ("only_tasks", "true"), ("include_payloads", "false"),
                        ("workflow_ids", str(self.binding.workflow_id)), ("additional_metadata_operator", "AND")]
                    params += [("additional_metadata", f"{k}:{v}") for k, v in spec.metadata(self.binding).items()]
                    value = await self.client.list_runs(self.binding, params, self._remaining(end))
                    rows, pagination = value["rows"], value["pagination"]
                    if type(rows) is not list or len(rows) > self.policy.page_size:
                        return Result("unknown", reason="lookup_bound")
                    for row in rows:
                        self._correlation(row, spec)
                        if row["type"] != "TASK":
                            raise ValueError("Unsupported workflow shape")
                        root_id = uuid_value(row["workflowRunExternalId"])
                        roots.setdefault(root_id, set()).add(uuid_value(row["taskExternalId"]))
                    if len(roots) > self.policy.max_executions:
                        return Result("unknown", reason="lookup_bound")
                    current, nxt, count = (pagination[k] for k in ("current_page", "next_page", "num_pages"))
                    if type(current) is not int or type(count) is not int or count < 1:
                        return Result("unknown", reason="invalid_observation")
                    if base is None:
                        base = current
                        if base not in (0, 1):
                            return Result("unknown", reason="invalid_observation")
                    if current != base+page or count <= page:
                        return Result("unknown", reason="invalid_observation")
                    if nxt is None:
                        if count != page+1:
                            return Result("unknown", reason="invalid_observation")
                        if not roots:
                            return Result("unknown", reason="unresolved", lookup_complete=True)
                        found = tuple([await self._details(spec, root, end) for root in sorted(roots, key=str)])
                        if any(not roots[item.root_id].issubset(item.task_ids) for item in found):
                            raise ValueError("Lookup task identity does not match root details")
                        return Result("found", found, reason="verified", lookup_complete=True)
                    if type(nxt) is not int or nxt != current+1 or count <= page+1:
                        return Result("unknown", reason="invalid_observation")
                return Result("unknown", reason="lookup_bound")
        except TimeoutError:
            return Result("unknown", reason="deadline")
        except Exception:
            return Result("unknown", reason="invalid_observation")

    async def cancel(self, spec: DispatchSpec, root_id):
        end = self.clock()+self.policy.total_seconds
        try:
            async with asyncio.timeout(self.policy.total_seconds):
                root_id = uuid_value(root_id)
                observed = await self._details(spec, root_id, end)
                await self.client.cancel(self.binding, root_id, self._remaining(end))
                return Result("cancel_requested", (observed,), reason="verified")
        except TimeoutError:
            return Result("unknown", reason="deadline")
        except Exception:
            return Result("unknown", reason="unresolved")
