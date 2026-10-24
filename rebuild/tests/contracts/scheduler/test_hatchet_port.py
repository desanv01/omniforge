"""Offline B3A checks. All RPC/HTTP objects are in-memory injected doubles.

The pinned SDK is used only for pure protobuf/serializer/retry-policy checks.
No token/config/session/channel/client connection is created.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from services.worker.hatchet_contracts import Binding, Collision, DispatchSpec, Policy, TransportFailure
from services.worker.hatchet_port import HatchetPort, RawSdkClient, idempotency_definition, trigger_request


class FakeClient:
    def __init__(self, binding, spec):
        self.binding, self.spec = binding, spec
        self.root, self.task = uuid4(), uuid4()
        self.trigger_calls, self.list_calls, self.get_calls, self.cancel_calls = [], [], [], []
        common = {"tenantId": str(binding.tenant_id), "workflowId": str(binding.workflow_id),
                  "workflowVersionId": str(binding.workflow_version_id),
                  "additionalMetadata": spec.metadata(binding), "status": "RUNNING"}
        self.row = {**deepcopy(common), "type": "TASK", "workflowRunExternalId": str(self.root),
                    "taskExternalId": str(self.task)}
        self.details = {"run": {**deepcopy(common), "metadata": {"id": str(self.root)},
                                "input": spec.payload()}, "tasks": [deepcopy(self.row)]}
        self.pages = [{"rows": [deepcopy(self.row)], "pagination": {"current_page": 0, "next_page": None, "num_pages": 1}}]
        self.trigger_error = self.get_error = self.list_error = self.cancel_error = None

    async def trigger(self, binding, spec, timeout):
        self.trigger_calls.append(timeout)
        if self.trigger_error:
            raise self.trigger_error
        return self.root

    async def list_runs(self, binding, params, timeout):
        self.list_calls.append((params, timeout))
        if self.list_error:
            raise self.list_error
        return deepcopy(self.pages[len(self.list_calls)-1])

    async def get_run(self, root_id, timeout):
        self.get_calls.append((root_id, timeout))
        if self.get_error:
            raise self.get_error
        return deepcopy(self.details)

    async def cancel(self, binding, root_id, timeout):
        self.cancel_calls.append((root_id, timeout))
        if self.cancel_error:
            raise self.cancel_error


class Body:
    def __init__(self, data, stall=False):
        self.data, self.stall = data, stall
        self.canceled = False

    async def read(self, count):
        if self.stall:
            try:
                await asyncio.Event().wait()
            finally:
                self.canceled = True
        chunk, self.data = self.data[:count], self.data[count:]
        return chunk


class Response:
    def __init__(self, data, *, status=200, headers=None, stall=False):
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.content = Body(data, stall)
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True


class Session:
    trust_env = False
    auto_decompress = False
    _retry_connection = False
    _middlewares = ()

    def __init__(self, response):
        self.response, self.calls = response, []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class HatchetPortProof(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.binding = Binding(uuid4(), uuid4(), uuid4(), "omniforge-b3:read", "omniforge-b3")
        self.spec = DispatchSpec(uuid4(), "run:synthetic:start:v1", "a"*64, 0, datetime.now(timezone.utc))
        self.client = FakeClient(self.binding, self.spec)

    def port(self, **options):
        return HatchetPort(self.client, self.binding, Policy(**options))

    async def test_01_import_and_pure_serializers_create_no_clients(self):
        import aiohttp
        import grpc
        import hatchet_sdk
        import services.worker.hatchet_port as module
        with patch.object(grpc, "insecure_channel", side_effect=AssertionError("network constructor")), \
             patch.object(grpc, "secure_channel", side_effect=AssertionError("network constructor")), \
             patch.object(aiohttp, "ClientSession", side_effect=AssertionError("client constructor")), \
             patch.object(hatchet_sdk, "Hatchet", side_effect=AssertionError("client constructor")):
            importlib.reload(module)
            request = trigger_request(self.binding, self.spec)
            self.assertEqual(json.loads(request.input), self.spec.payload())
            self.assertEqual(json.loads(request.additional_metadata), self.spec.metadata(self.binding))
            self.assertEqual(request.name, self.binding.workflow_name)
            definition = idempotency_definition(3600)
            self.assertEqual(definition.expression, "input.dispatch_identity")
            self.assertEqual(definition.ttl_ms, 3600000)
        from hatchet_sdk.clients.admin import AdminClient
        from hatchet_sdk.types.trigger import TriggerWorkflowOptions
        admin = object.__new__(AdminClient)
        keyed = admin._prepare_workflow_request(self.binding.workflow_name, "{}", TriggerWorkflowOptions(key="not-a-global-idempotency-key"))
        plain = admin._prepare_workflow_request(self.binding.workflow_name, "{}", TriggerWorkflowOptions())
        self.assertEqual(keyed.SerializeToString(), plain.SerializeToString())

    async def test_02_submit_verifies_root_input_and_preserves_task_identity(self):
        result = await self.port().submit(self.spec)
        self.assertEqual(result.state, "acknowledged")
        self.assertEqual(result.executions[0].root_id, self.client.root)
        self.assertEqual(result.executions[0].task_ids, (self.client.task,))
        self.assertNotEqual(self.client.root, self.client.task)
        self.assertFalse(result.executions[0].domain_completion_proved)
        self.assertEqual(len(self.client.trigger_calls), 1)
        self.client.details["run"]["input"]["input_hash"] = "b"*64
        self.assertEqual((await self.port().submit(self.spec)).state, "unknown")

    async def test_03_collision_requires_full_correlated_existing_root(self):
        self.client.trigger_error = Collision(self.client.root)
        good = await self.port().submit(self.spec)
        self.assertEqual(good.state, "acknowledged")
        self.client.details["run"]["additionalMetadata"]["of_run_id"] = str(uuid4())
        bad = await self.port().submit(self.spec)
        self.assertEqual(bad.state, "unknown")
        self.assertEqual(bad.executions, ())
        self.assertEqual(bad.candidate_ids, (self.client.root,))

    async def test_04_empty_lagged_error_and_oversized_lookup_never_absent(self):
        self.client.pages[0]["rows"] = []
        self.assertEqual((await self.port().lookup(self.spec)).state, "unknown")
        self.client.list_error = RuntimeError("PRIVATE_UPSTREAM_BODY")
        value = await self.port().lookup(self.spec)
        self.assertEqual(value.state, "unknown")
        self.assertNotIn("PRIVATE_UPSTREAM_BODY", repr(value))
        self.client.list_error = None
        self.client.list_calls.clear()
        self.client.pages[0]["rows"] = [self.client.row]*51
        self.assertEqual((await self.port(page_size=50).lookup(self.spec)).reason, "lookup_bound")

    async def test_05_exact_and_filters_and_complete_bounded_pagination(self):
        self.client.pages = [
            {"rows": [deepcopy(self.client.row)], "pagination": {"current_page": 1, "next_page": 2, "num_pages": 2}},
            {"rows": [deepcopy(self.client.row)], "pagination": {"current_page": 2, "next_page": None, "num_pages": 2}},
        ]
        # Windows can return one monotonic tick for several fast in-memory calls.
        # Inject deterministic elapsed time to verify the shared deadline budget.
        ticks = iter((0.0, 0.1, 0.2, 0.3))
        port = HatchetPort(self.client, self.binding, Policy(page_size=1), clock=lambda: next(ticks))
        result = await port.lookup(self.spec)
        self.assertEqual(result.state, "found")
        self.assertTrue(result.lookup_complete)
        self.assertEqual(len(result.executions), 1)
        self.assertEqual(len(self.client.get_calls), 1)
        first, second = self.client.list_calls
        self.assertIn(("additional_metadata_operator", "AND"), first[0])
        self.assertIn(("include_payloads", "false"), first[0])
        self.assertIn(("workflow_ids", str(self.binding.workflow_id)), first[0])
        self.assertIn(("offset", "1"), second[0])
        self.assertGreater(first[1], second[1])

    async def test_06_pagination_overflow_inconsistency_and_mismatch_unknown(self):
        self.client.pages[0]["pagination"] = {"current_page": 0, "next_page": 1, "num_pages": 2}
        value = await self.port(max_pages=1).lookup(self.spec)
        self.assertEqual(value.reason, "lookup_bound")
        self.assertEqual(value.executions, ())
        self.client.list_calls.clear()
        self.client.pages[0]["pagination"] = {"current_page": 0, "next_page": None, "num_pages": 2}
        self.assertEqual((await self.port().lookup(self.spec)).state, "unknown")
        for key, replacement in (("tenantId", str(uuid4())), ("workflowVersionId", str(uuid4())), ("type", "DAG")):
            self.client.list_calls.clear()
            row = deepcopy(self.client.row)
            row[key] = replacement
            self.client.pages[0] = {"rows": [row], "pagination": {"current_page": 0, "next_page": None, "num_pages": 1}}
            self.assertEqual((await self.port().lookup(self.spec)).state, "unknown")

    async def test_07_lookup_task_id_and_execution_bounds(self):
        self.client.pages[0]["rows"][0]["taskExternalId"] = str(uuid4())
        self.assertEqual((await self.port().lookup(self.spec)).state, "unknown")
        self.client.list_calls.clear()
        rows = []
        for _ in range(3):
            row = deepcopy(self.client.row)
            row["workflowRunExternalId"] = str(uuid4())
            rows.append(row)
        self.client.pages[0]["rows"] = rows
        self.assertEqual((await self.port().lookup(self.spec)).reason, "lookup_bound")

    async def test_08_cancel_verifies_exact_root_and_never_proves_cleanup(self):
        self.client.details["run"]["status"] = "CANCELLED"
        port = self.port()
        for _ in range(2):
            result = await port.cancel(self.spec, self.client.root)
            self.assertEqual(result.state, "cancel_requested")
            self.assertFalse(result.executions[0].cleanup_proved)
        self.assertEqual([item[0] for item in self.client.cancel_calls], [self.client.root]*2)
        self.client.details["run"]["workflowId"] = str(uuid4())
        self.assertEqual((await port.cancel(self.spec, self.client.root)).state, "unknown")
        self.assertEqual(len(self.client.cancel_calls), 2)

    async def test_09_completed_status_is_only_a_broker_observation(self):
        self.client.details["run"]["status"] = "COMPLETED"
        result = await self.port().submit(self.spec)
        self.assertEqual(result.executions[0].native_status, "COMPLETED")
        self.assertFalse(result.executions[0].domain_completion_proved)
        self.assertFalse(result.executions[0].cleanup_proved)
        for status in ("FAILED", "CANCELLED", "QUEUED", "RUNNING"):
            self.client.details["run"]["status"] = status
            self.assertEqual((await self.port().submit(self.spec)).executions[0].native_status, status)

    async def test_10_overall_deadline_cancels_stalled_operation_no_retry(self):
        canceled = []
        async def stall(*args):
            self.client.trigger_calls.append(1)
            try:
                await asyncio.Event().wait()
            finally:
                canceled.append(True)
        self.client.trigger = stall
        value = await self.port(total_seconds=0.03).submit(self.spec)
        self.assertEqual((value.state, value.reason), ("unknown", "deadline"))
        self.assertEqual(canceled, [True])
        self.assertEqual(len(self.client.trigger_calls), 1)

    async def test_11_raw_rpc_passes_real_deadline_and_single_attempt(self):
        calls = []
        async def rpc(request, **kwargs):
            calls.append((request, kwargs))
            return SimpleNamespace(workflow_run_id=str(self.client.root))
        raw = RawSdkClient(trigger_rpc=rpc, session=Session(Response(b"{}")), base_url="http://127.0.0.1:63151")
        self.assertEqual(await raw.trigger(self.binding, self.spec, 0.2), self.client.root)
        self.assertEqual(calls[0][1]["timeout"], 0.2)
        self.assertEqual(len(calls), 1)
        from hatchet_sdk.clients.rest.tenacity_utils import tenacity_retry
        from hatchet_sdk.config import TenacityConfig
        attempts = []
        def fail():
            attempts.append(1)
            raise RuntimeError("synthetic")
        with self.assertRaises(RuntimeError):
            tenacity_retry(fail, TenacityConfig(max_attempts=1))()
        self.assertEqual(attempts, [1])

    async def test_12_raw_http_deadline_bytes_no_redirect_no_retry(self):
        response = Response(json.dumps({"rows": [], "pagination": {}}).encode())
        session = Session(response)
        raw = RawSdkClient(trigger_rpc=None, session=session, base_url="http://127.0.0.1:63151")
        await raw.list_runs(self.binding, [("limit", "1")], 0.2)
        args, kwargs = session.calls[0]
        self.assertEqual(args[0], "GET")
        self.assertEqual(kwargs["timeout"].total, 0.2)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["headers"]["Accept-Encoding"], "identity")
        self.assertTrue(response.closed)
        session._retry_connection = True
        with self.assertRaises(ValueError):
            await raw.get_run(self.client.root, 0.2)
        self.assertEqual(len(session.calls), 1)

    async def test_13_http_body_stall_is_actually_canceled_and_closed(self):
        response = Response(b"", stall=True)
        session = Session(response)
        raw = RawSdkClient(trigger_rpc=None, session=session, base_url="http://127.0.0.1:63151")
        with self.assertRaises(TimeoutError):
            await raw.get_run(self.client.root, 0.03)
        self.assertTrue(response.content.canceled)
        self.assertTrue(response.closed)
        self.assertEqual(len(session.calls), 1)

    async def test_14_http_failure_body_and_bounds_are_sanitized(self):
        for response in (Response(b"PRIVATE_UPSTREAM_BODY", status=403),
                         Response(b"{}", status=302), Response(b"x"*65537),
                         Response(b"{}", headers={"Content-Encoding": "gzip"})):
            raw = RawSdkClient(trigger_rpc=None, session=Session(response), base_url="http://127.0.0.1:63151")
            with self.assertRaises(TransportFailure) as caught:
                await raw.get_run(self.client.root, 0.2)
            self.assertNotIn("PRIVATE_UPSTREAM_BODY", str(caught.exception))
            self.assertTrue(response.closed)

    async def test_15_pinned_collision_exception_gets_verified(self):
        from hatchet_sdk.exceptions import IdempotencyCollisionError
        async def rpc(*args, **kwargs):
            raise IdempotencyCollisionError(str(self.client.root))
        raw = RawSdkClient(trigger_rpc=rpc, session=Session(Response(b"{}")), base_url="http://127.0.0.1:63151")
        with self.assertRaises(Collision) as caught:
            await raw.trigger(self.binding, self.spec, 0.2)
        self.assertEqual(caught.exception.existing_id, self.client.root)

    async def test_16_bounded_policy_generation_and_window(self):
        for kwargs in ({"sdk_attempts": 2}, {"max_pages": 3}, {"page_size": 51},
                       {"total_seconds": float("nan")}, {"total_seconds": True}):
            with self.assertRaises(ValueError):
                Policy(**kwargs)
        other = DispatchSpec(self.spec.run_id, self.spec.dispatch_key, self.spec.input_hash, 1, self.spec.created_at)
        self.assertNotEqual(other.dispatch_identity, self.spec.dispatch_identity)
        for generation in (True, 2, "1"):
            with self.assertRaises(ValueError):
                DispatchSpec(self.spec.run_id, self.spec.dispatch_key, self.spec.input_hash, generation, self.spec.created_at)
        for origin in ("http://user:password@localhost", "http://localhost/path", "http://localhost?query=secret"):
            with self.assertRaises(ValueError):
                RawSdkClient(trigger_rpc=None, session=Session(Response(b"{}")), base_url=origin)

    async def test_17_observed_generation_types_never_acknowledge_or_cancel(self):
        for generation, bad_values in ((0, (False, 0.0, "0")), (1, (True, 1.0, "1"))):
            spec = DispatchSpec(self.spec.run_id, self.spec.dispatch_key, self.spec.input_hash,
                                generation, self.spec.created_at)
            for wrapped in (False, True):
                for bad in bad_values:
                    with self.subTest(generation=generation, wrapped=wrapped, observed_type=type(bad).__name__):
                        client = FakeClient(self.binding, spec)
                        malformed = {**spec.payload(), "generation": bad}
                        client.details["run"]["input"] = ({"input": malformed, "overrides": None}
                                                           if wrapped else malformed)
                        port = HatchetPort(client, self.binding)
                        normal = await port.submit(spec)
                        self.assertEqual((normal.state, normal.executions), ("unknown", ()))
                        client.trigger_error = Collision(client.root)
                        collision = await port.submit(spec)
                        self.assertEqual((collision.state, collision.executions), ("unknown", ()))
                        canceled = await port.cancel(spec, client.root)
                        self.assertEqual((canceled.state, canceled.executions), ("unknown", ()))
                        self.assertEqual(client.cancel_calls, [])

    async def test_18_valid_integer_payload_and_exact_wrapper_shape(self):
        for generation in (0, 1):
            spec = DispatchSpec(self.spec.run_id, self.spec.dispatch_key, self.spec.input_hash,
                                generation, self.spec.created_at)
            for wrapped in (False, True):
                with self.subTest(generation=generation, wrapped=wrapped):
                    client = FakeClient(self.binding, spec)
                    client.details["run"]["input"] = ({"input": spec.payload(), "overrides": None}
                                                       if wrapped else spec.payload())
                    port = HatchetPort(client, self.binding)
                    self.assertEqual((await port.submit(spec)).state, "acknowledged")
                    client.trigger_error = Collision(client.root)
                    self.assertEqual((await port.submit(spec)).state, "acknowledged")
                    self.assertEqual((await port.cancel(spec, client.root)).state, "cancel_requested")
                    self.assertEqual([item[0] for item in client.cancel_calls], [client.root])
            for malformed in ({"input": spec.payload(), "overrides": False},
                              {"input": spec.payload(), "overrides": None, "extra": 0},
                              {"input": {**spec.payload(), "extra": 0}, "overrides": None}):
                client = FakeClient(self.binding, spec)
                client.details["run"]["input"] = malformed
                port = HatchetPort(client, self.binding)
                self.assertEqual((await port.submit(spec)).state, "unknown")
                self.assertEqual((await port.cancel(spec, client.root)).state, "unknown")
                self.assertEqual(client.cancel_calls, [])


if __name__ == "__main__":
    unittest.main()
