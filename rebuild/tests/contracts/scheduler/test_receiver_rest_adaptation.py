"""Offline copied REST derivative: fake HTTP graph, no real SDK/network imports."""
import ast
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import sysconfig
import tempfile
import threading
import traceback
import types
import unittest
from unittest.mock import patch

ARTIFACT = Path(__file__).resolve().parents[3] / "infra/scheduler/receiver-rest-adaptation"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Value:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @classmethod
    def __class_getitem__(cls, item):
        return cls

    @classmethod
    def from_dict(cls, value):
        return cls(**value)


class Raw:
    status = 200
    reason = "OK"
    headers = {"content-type": "application/json"}

    def __init__(self, body=b'{"id":"worker"}', fail=()):
        self.body = body
        self.fail = set(fail)
        self.calls = []
        self.gate = None
        self.entered = threading.Event()

    @property
    def data(self):
        self.calls.append("read")
        self.entered.set()
        if self.gate is not None:
            if not self.gate.wait(2):
                raise RuntimeError("fake gate was not released")
        if "read" in self.fail:
            raise RuntimeError("PRIVATE_BODY PRIVATE_TOKEN")
        return self.body

    def close(self):
        self.calls.append("close")
        if "close" in self.fail:
            raise RuntimeError("PRIVATE_CLOSE")

    def release_conn(self):
        self.calls.append("release")
        if "release" in self.fail:
            raise RuntimeError("PRIVATE_RELEASE")


class Pool:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def close(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("PRIVATE_POOL")


class RestProof(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load("rest_proof_applicator", ARTIFACT / "apply_patch.py")
        cls.scratch = Path(tempfile.mkdtemp(prefix="receiver-rest-"))
        cls.source = cls.scratch / "upstream"
        cls.source.mkdir()
        installed = Path(sysconfig.get_paths()["purelib"])
        for name in cls.app.FILES:
            target = cls.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((installed / name).read_bytes())
        meta = cls.source / "hatchet_sdk-1.41.1.dist-info/METADATA"
        meta.parent.mkdir()
        meta.write_bytes((installed / meta.relative_to(cls.source)).read_bytes())
        cls.generated_path = installed / "hatchet_sdk/clients/rest/api/worker_api.py"
        cls.output = cls.scratch / "output"
        cls.hashes = cls.app.apply(cls.source, cls.output)

    @classmethod
    def tearDownClass(cls):
        # Only this test's verified disposable directory is removed.
        target = cls.scratch.resolve()
        parent = Path(tempfile.gettempdir()).resolve()
        if target.parent != parent or not target.name.startswith("receiver-rest-"):
            raise AssertionError("Refusing cleanup outside owned test scratch")
        shutil.rmtree(target)

    def setUp(self):
        self.modules = {}

        def module(name):
            if name not in self.modules:
                item = types.ModuleType(name)
                item.__path__ = []
                self.modules[name] = item
                if "." in name:
                    parent, child = name.rsplit(".", 1)
                    setattr(module(parent), child, item)
            return self.modules[name]

        self.module = module
        config_module = module("hatchet_sdk.clients.rest.configuration")

        class Configuration:
            def __init__(self, **kwargs):
                self.__dict__.update(dict(
                    verify_ssl=True, ssl_ca_cert=None, cert_file=None, key_file=None,
                    ca_cert_data=None, assert_hostname=None, tls_server_name=None,
                    socket_options=None, connection_pool_maxsize=2,
                    proxy=None, proxy_headers=None, retries=None,
                    client_side_validation=True,
                ))
                self.__dict__.update(kwargs)

            @property
            def debug(self):
                raise AssertionError("debug access is outside the receiver policy")

            @debug.setter
            def debug(self, value):
                raise AssertionError("debug setter mutates global diagnostics")

        config_module.Configuration = Configuration
        module("hatchet_sdk.config").ClientConfig = Value
        module("hatchet_sdk.utils.typing").JSONSerializableMapping = dict
        module("hatchet_sdk.clients.rest.api_response").ApiResponse = Value
        module("hatchet_sdk.clients.rest.api_response").T = Value
        module("hatchet_sdk.clients.rest.models").Worker = Value
        module("hatchet_sdk.logger").logger = Value(warning=lambda *a: self.fail("raw log"))
        exceptions = module("hatchet_sdk.clients.rest.exceptions")

        class ApiException(Exception):
            def __init__(self, *args, **kwargs):
                super().__init__("PRIVATE_BODY PRIVATE_TOKEN PRIVATE_URL")

            @classmethod
            def from_response(cls, **kwargs):
                return cls()

        for name in ("ApiValueError", "ApiException", "BadRequestException", "UnauthorizedException",
                     "ForbiddenException", "NotFoundException", "ServiceException"):
            setattr(exceptions, name, ApiException)
        for name, attr in (("update_worker_request", "UpdateWorkerRequest"), ("worker", "Worker"),
                           ("worker_list", "WorkerList")):
            setattr(module("hatchet_sdk.clients.rest.models." + name), attr, Value)
        module("hatchet_sdk.clients.rest.tenacity_utils").tenacity_retry = (
            lambda *a: self.fail("selected pause must not use tenacity"))
        graph = self
        urllib = module("urllib3")

        class FakeManager:
            def __init__(self, **kwargs):
                graph.managers.append(self)
                self.kwargs = kwargs
                self.calls = []
                self.clear_calls = 0
                self.fail_clear = False
                self.pools_by_key = {}
                self.raw = Raw()
                self.error = None
                self.gate = None
                self.entered = threading.Event()

            def connection_from_pool_key(self, pool_key, request_context=None):
                return self.pools_by_key.setdefault(pool_key, Pool())

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                self.connection_from_pool_key("origin")
                self.entered.set()
                if self.gate is not None:
                    if not self.gate.wait(2):
                        raise RuntimeError("fake gate was not released")
                if self.error:
                    raise self.error
                return self.raw

            def clear(self):
                # Deliberately does not close any concrete pool.
                self.clear_calls += 1
                if self.fail_clear:
                    raise RuntimeError("PRIVATE_CLEAR")

        self.managers = []
        urllib.PoolManager = FakeManager
        urllib.ProxyManager = lambda **kw: self.fail("proxy constructed")
        urllib.HTTPResponse = Raw
        urllib.Timeout = lambda **kw: Value(**kw)
        module("hatchet_sdk.clients.rest.api.worker_api")
        self.graph_patch = patch.dict(sys.modules, self.modules)
        self.graph_patch.start()
        self.addCleanup(self.graph_patch.stop)

        self.rest = load("hatchet_sdk.clients.rest.rest", self.output / self.app.FILES[3])
        module("hatchet_sdk.clients.rest").rest = self.rest
        self.api = load("hatchet_sdk.clients.rest.api_client", self.output / self.app.FILES[2])
        module("hatchet_sdk.clients.rest").api_client = self.api
        self.base = load("hatchet_sdk.clients.v1.api_client", self.output / self.app.FILES[1])

        # Execute the unchanged generated worker_update method body; omit only
        # annotations/decorator to avoid importing unrelated generated models.
        tree = ast.parse(self.generated_path.read_text(encoding="utf8"))
        klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WorkerApi")
        method = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == "worker_update")
        method.decorator_list = []
        method.returns = None
        for arg in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs):
            arg.annotation = None
        namespace = {"Worker": Value}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "generated-worker-update", "exec"), namespace)

        class WorkerApi:
            worker_update = namespace["worker_update"]

            def __init__(self, client):
                self.api_client = client

            def _worker_update_serialize(self, **kwargs):
                graph.serialized.append(kwargs)
                return ("PUT", "http://127.0.0.1:8888/worker", {"Authorization": "Bearer PRIVATE_TOKEN"},
                        {"isPaused": kwargs["update_worker_request"].isPaused}, [])

        self.serialized = []
        module("hatchet_sdk.clients.rest.api.worker_api").WorkerApi = WorkerApi
        self.workers = load("hatchet_sdk.features.workers", self.output / self.app.FILES[0])
        self.config = Value(tenant_id="tenant", server_url="http://127.0.0.1:8888",
                            token="PRIVATE_TOKEN", tls_config=Value(root_ca_file=None))

    def transport(self):
        return self.rest.RESTClientObject(self.module("hatchet_sdk.clients.rest.configuration").Configuration(retries=0))

    def worker(self, capture):
        worker = self.workers.WorkersClient(self.config)
        original = worker.client

        def client():
            result = original()
            capture(result)
            return result

        worker.client = client
        return worker

    def assert_safe(self, error):
        self.assertIsNone(error.__context__)
        self.assertIsNone(error.__cause__)
        text = json.dumps(error.__dict__) + str(error) + repr(error) + "".join(traceback.format_exception(error))
        self.assertNotIn("PRIVATE_", text)

    def test_01_pause_generated_path_and_identity(self):
        owners = []
        worker = self.workers.WorkersClient(self.config)
        result = worker.pause("worker", owner_capture=owners.append)
        self.assertEqual(result.id, "worker")
        owner = owners[0]
        manager = self.managers[0]
        self.assertEqual(len(manager.calls), 1)
        self.assertEqual(self.serialized[0]["worker"], "worker")
        self.assertIs(self.serialized[0]["update_worker_request"].isPaused, True)
        self.assertEqual(manager.calls[0][2]["headers"]["Authorization"], "Bearer PRIVATE_TOKEN")
        self.assertEqual(manager.calls[0][2]["body"], '{"isPaused": true}')
        self.assertTrue(owner.settlement_snapshot["cleanup_complete"])
        self.assertEqual(manager.raw.calls, ["read", "close", "release"])
        self.assertEqual(manager.pools_by_key["origin"].calls, 1)
        self.assertEqual(manager.clear_calls, 1)
        with self.assertRaises(TypeError):
            owner.settlement_snapshot["cleanup_complete"] = False
        # Worker-return identity independent of generated model construction.
        sentinel = object()
        worker._wa = lambda client: Value(worker_update=lambda **kw: sentinel)
        self.assertIs(worker.pause("worker"), sentinel)

    def test_02_explicit_builder_and_direct_policy(self):
        worker = self.workers.WorkersClient(self.config)
        self.assertEqual(worker.api_config.host, self.config.server_url)
        self.assertEqual(worker.api_config.access_token, self.config.token)
        self.assertEqual(worker.api_config.retries, 0)
        self.assertIsNone(worker.api_config.proxy)
        self.assertIsNone(worker.api_config.proxy_headers)
        Configuration = self.module("hatchet_sdk.clients.rest.configuration").Configuration
        for overrides in ({"retries": None}, {"retries": True}, {"retries": 1},
                          {"proxy": "PRIVATE_PROXY"}, {"proxy_headers": {}}):
            config = Configuration(retries=0)
            config.__dict__.update(overrides)
            with self.assertRaises(self.rest.ReceiverRestError):
                self.rest.RESTClientObject(config)
        self.assertEqual(self.managers, [])

    def test_03_all_request_serializations_fixed_policy(self):
        cases = [
            ("PUT", {}, {"ok": True}, None, "body", '{"ok": true}'),
            ("PUT", {"Content-Type": "application/x-www-form-urlencoded"}, None, {"a": "b"}, "encode_multipart", False),
            ("POST", {"Content-Type": "multipart/form-data"}, None, [("a", {"b": 1})], "encode_multipart", True),
            ("DELETE", {"Content-Type": "binary"}, b"raw", None, "body", b"raw"),
            ("PATCH", {"Content-Type": "text/plain"}, True, None, "body", "true"),
            ("GET", {}, None, None, "fields", {}),
            ("HEAD", {}, None, None, "fields", {}),
        ]
        for method, headers, body, params, key, expected in cases:
            with self.subTest(method=method, headers=headers):
                transport = self.transport()
                response = transport.request(method, "fake", headers, body, params)
                self.assertIs(response.response, transport.pool_manager.raw)
                kwargs = transport.pool_manager.calls[0][2]
                self.assertEqual(kwargs[key], expected)
                self.assertEqual(kwargs["retries"], 0)
                self.assertIs(kwargs["redirect"], False)
                self.assertIs(kwargs["preload_content"], False)
                self.assertEqual(vars(kwargs["timeout"]), {"connect": 2.0, "read": 5.0, "total": 8.0})
                self.assertTrue(transport.close())

    def test_04_timeouts_validate_before_send(self):
        for invalid in (True, False, 0, -1, 9, float("nan"), float("inf"), "5", (), (1,), (3, 1), (1, 6), (None, 1), [1, 2]):
            transport = self.transport()
            with self.subTest(value=invalid), self.assertRaises(self.rest.ReceiverRestError):
                transport.request("PUT", "fake", _request_timeout=invalid)
            self.assertEqual(transport.pool_manager.calls, [])
            self.assertTrue(transport.close())
        for supplied, expected in ((1, (1., 1., 1.)), ((1, 2), (1., 2., 3.))):
            result = self.rest.request_timeout(supplied)
            self.assertEqual((result.connect, result.read, result.total), expected)

    def test_05_selected_errors_one_attempt_safe(self):
        for failure in (RuntimeError("PRIVATE_TLS PRIVATE_TOKEN"), TimeoutError("PRIVATE_TIMEOUT"),
                        PermissionError("PRIVATE_AUTH"), ConnectionError("PRIVATE_URL")):
            owners = []
            def setup(owner):
                owners.append(owner)
                owner.rest_client.pool_manager.error = failure
            worker = self.worker(setup)
            with self.subTest(failure=type(failure).__name__), self.assertRaises(self.rest.ReceiverRestError) as caught:
                worker.pause("worker")
            self.assertEqual(caught.exception.code, "rest_delivery_uncertain")
            self.assert_safe(caught.exception)
            self.assertEqual(len(owners[0].rest_client.pool_manager.calls), 1)
            self.assertTrue(owners[0].settlement_snapshot["cleanup_complete"])

    def test_06_status_body_model_and_read_failure_cleanup(self):
        for status, body, failure in ((302, b"PRIVATE_REDIRECT", ()), (403, b'{"error":"PRIVATE_BODY"}', ()),
                                     (200, b"PRIVATE_INVALID_JSON", ()), (200, b"", ("read",))):
            owners = []
            def setup(owner):
                owners.append(owner)
                raw = owner.rest_client.pool_manager.raw = Raw(body, failure)
                raw.status = status
            worker = self.worker(setup)
            with self.subTest(status=status, failure=failure), self.assertRaises(self.rest.ReceiverRestError) as caught:
                worker.pause("worker")
            self.assertEqual(caught.exception.code, "rest_delivery_uncertain")
            self.assert_safe(caught.exception)
            raw = owners[0].rest_client.pool_manager.raw
            self.assertEqual(raw.calls, ["read", "close", "release"])
            self.assertEqual(len(owners[0].rest_client.pool_manager.calls), 1)

    def test_07_response_cleanup_independent_idempotent(self):
        for failure in ((), ("close",), ("release",), ("close", "release")):
            transport = self.transport()
            raw = transport.pool_manager.raw = Raw(b"", failure)
            response = transport.request("GET", "fake")
            self.assertEqual(response.read(), b"")
            self.assertEqual(response.read(), b"")
            complete = transport.close()
            transport.close()
            response.close()
            self.assertEqual(raw.calls, ["read", "close", "release"])
            self.assertEqual(complete, not failure)
            self.assertEqual(transport.settlement_snapshot["unresolved_response_count"], int(bool(failure)))

    def test_08_pool_close_and_clear_independent(self):
        transport = self.transport()
        manager = transport.pool_manager
        first = manager.connection_from_pool_key("one")
        self.assertIs(first, manager.connection_from_pool_key("one"))
        second = manager.connection_from_pool_key("two")
        first.fail = True
        manager.fail_clear = True
        self.assertFalse(transport.close())
        self.assertFalse(transport.close())
        self.assertEqual((first.calls, second.calls, manager.clear_calls), (1, 1, 1))
        self.assertEqual(transport.settlement_snapshot["unresolved_pool_count"], 1)
        self.assertFalse(transport.settlement_snapshot["cleanup_complete"])
        with self.assertRaises(self.rest.ReceiverRestError):
            transport.request("GET", "fake")
        self.assertEqual(manager.calls, [])

    def test_09_cleanup_failure_after_success_and_capture_failure(self):
        owners = []
        worker = self.worker(lambda owner: (owners.append(owner), setattr(owner.rest_client.pool_manager, "fail_clear", True)))
        with self.assertRaises(self.rest.ReceiverRestError) as caught:
            worker.pause("worker")
        self.assertEqual(caught.exception.code, "rest_cleanup_incomplete")
        self.assertTrue(caught.exception.response_observed)
        self.assert_safe(caught.exception)
        owner2 = []
        worker2 = self.workers.WorkersClient(self.config)
        def capture(client):
            owner2.append(client)
            raise RuntimeError("PRIVATE_CAPTURE")
        with self.assertRaises(self.rest.ReceiverRestError) as caught:
            worker2.pause("worker", owner_capture=capture)
        self.assertEqual(caught.exception.code, "rest_not_sent")
        self.assert_safe(caught.exception)
        self.assertEqual(owner2[0].rest_client.pool_manager.calls, [])
        self.assertTrue(owner2[0].settlement_snapshot["cleanup_complete"])

    def test_10_wrapper_construction_failure_and_raw_borrow(self):
        transport = self.transport()
        raw = transport.pool_manager.raw
        with patch.object(self.rest, "RESTResponse", side_effect=RuntimeError("PRIVATE_WRAPPER")):
            with self.assertRaises(RuntimeError):
                transport.request("GET", "fake")
        self.assertTrue(transport.close())
        self.assertEqual(raw.calls, ["close", "release"])
        transport2 = self.transport()
        response = transport2.request("GET", "fake")
        self.assertIs(response.response, transport2.pool_manager.raw)
        self.assertTrue(transport2.close())
        self.assertEqual(response.response.calls, ["close", "release"])

    def test_11_api_context_and_control_interruption(self):
        worker = self.workers.WorkersClient(self.config)
        owner = worker.client()
        with owner:
            pass
        with self.assertRaises(self.rest.ReceiverRestError):
            owner.__enter__()
        owners = []
        def setup(client):
            owners.append(client)
            client.rest_client.pool_manager.error = KeyboardInterrupt()
        worker = self.worker(setup)
        with self.assertRaises(KeyboardInterrupt):
            worker.pause("worker")
        self.assertTrue(owners[0].settlement_snapshot["cleanup_complete"])
        self.assertTrue(owners[0].settlement_snapshot["request_started"])

    async def test_12_aio_capture_cancellation_retains_actual_thread(self):
        owners = []
        release = threading.Event()
        entered = threading.Event()
        finished = threading.Event()
        worker = self.workers.WorkersClient(self.config)
        def capture(client):
            owners.append(client)
            client.rest_client.pool_manager.gate = release
            entered.set()
        original_pause = worker.pause
        def pause(*args, **kwargs):
            try:
                return original_pause(*args, **kwargs)
            finally:
                finished.set()
        worker.pause = pause
        task = asyncio.create_task(worker.aio_pause("worker", owner_capture=capture))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            manager = owners[0].rest_client.pool_manager
            self.assertTrue(await asyncio.to_thread(manager.entered.wait, 1))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(finished.is_set())
            self.assertTrue(owners[0].settlement_snapshot["request_active"])
            self.assertFalse(owners[0].settlement_snapshot["cleanup_complete"])
            self.assertEqual(len(manager.calls), 1)
        finally:
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait, 1))
            if not task.done():
                await task
        self.assertTrue(owners[0].settlement_snapshot["cleanup_complete"])

    def test_13_premature_close_never_claims_stop(self):
        transport = self.transport()
        release = threading.Event()
        manager = transport.pool_manager
        manager.gate = release
        errors = []
        def run():
            try:
                transport.request("GET", "fake").read()
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(manager.entered.wait(1))
            self.assertFalse(transport.close())
            self.assertTrue(thread.is_alive())
            self.assertEqual(manager.clear_calls, 0)
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(transport.close())
        self.assertFalse(transport.settlement_snapshot["cleanup_complete"])
        self.assertEqual(manager.clear_calls, 0)
        self.assertEqual(transport.settlement_snapshot["unresolved_pool_count"], 1)

    def test_14_artifact_exact_and_refusal(self):
        manifest = json.loads((ARTIFACT / "upstream-manifest.json").read_text())
        self.assertEqual(set(self.hashes), set(self.app.FILES))
        self.assertEqual(len(self.hashes), 4)
        for name, digest in self.hashes.items():
            self.assertEqual(digest, manifest["files"][name]["derivative_sha256"])
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())
        for destination in (self.output, self.source, self.source / "child", self.scratch):
            with self.assertRaises(ValueError):
                self.app.apply(self.source, destination)
        drift = self.scratch / "drift"
        shutil.copytree(self.source, drift)
        (drift / self.app.FILES[0]).write_bytes(b"drift")
        destination = self.scratch / "drift-output"
        with self.assertRaises(ValueError):
            self.app.apply(drift, destination)
        self.assertFalse(destination.exists())

    def test_15_manifest_and_patch_tampering_refused_before_output(self):
        artifact_copy = self.scratch / self._testMethodName
        shutil.copytree(ARTIFACT, artifact_copy)
        original_manifest = (artifact_copy / "upstream-manifest.json").read_text()
        original_patch = (artifact_copy / "receiver-rest-policy.patch").read_text(encoding="utf8")
        manifest = json.loads(original_manifest)
        mutations = []
        missing = json.loads(original_manifest)
        del missing["files"][self.app.FILES[0]]
        mutations.append(json.dumps(missing))
        extra = json.loads(original_manifest)
        extra["files"]["hatchet_sdk/extra.py"] = {}
        mutations.append(json.dumps(extra))
        bad_hash = json.loads(original_manifest)
        bad_hash["files"][self.app.FILES[0]]["derivative_sha256"] = "0" * 64
        mutations.append(json.dumps(bad_hash))
        bad_lf = json.loads(original_manifest)
        bad_lf["files"][self.app.FILES[0]]["upstream_lf_sha256"] = "0" * 64
        mutations.append(json.dumps(bad_lf))
        extra_hash = json.loads(original_manifest)
        extra_hash["files"][self.app.FILES[0]]["extra"] = "0" * 64
        mutations.append(json.dumps(extra_hash))
        wrong_version = json.loads(original_manifest)
        wrong_version["version"] = "other"
        mutations.append(json.dumps(wrong_version))
        mutations.append(original_manifest.replace('"distribution": "hatchet-sdk",', '"distribution": "hatchet-sdk", "distribution": "hatchet-sdk",'))
        for index, text in enumerate(mutations):
            (artifact_copy / "upstream-manifest.json").write_text(text)
            copied = load("rest_tampered_app", artifact_copy / "apply_patch.py")
            target = self.scratch / ("invalid-manifest-" + str(index))
            with self.assertRaises(ValueError):
                copied.apply(self.source, target)
            self.assertFalse(target.exists())
        (artifact_copy / "upstream-manifest.json").write_text(original_manifest)
        for index, text in enumerate((original_patch + original_patch,
                                     original_patch.replace("--- a/hatchet_sdk/features/workers.py", "--- a/../escape.py", 1),
                                     original_patch.replace("return await asyncio.to_thread(self.update, worker_id, opts)", "return altered", 1))):
            (artifact_copy / "receiver-rest-policy.patch").write_text(text, encoding="utf8")
            target = self.scratch / ("invalid-patch-" + str(index))
            with self.assertRaises(ValueError):
                copied.apply(self.source, target)
            self.assertFalse(target.exists())

    def test_16_body_read_is_active_until_physical_return(self):
        transport = self.transport()
        response = transport.request("GET", "fake")
        raw = response.response
        release = raw.gate = threading.Event()
        errors = []
        def read():
            try:
                response.read()
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=read)
        thread.start()
        try:
            self.assertTrue(raw.entered.wait(1))
            self.assertTrue(transport.settlement_snapshot["request_active"])
            self.assertFalse(transport.close())
            self.assertEqual(raw.calls, ["read"])
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(transport.settlement_snapshot["request_active"])
        self.assertFalse(transport.close())
        self.assertEqual(raw.calls, ["read", "close", "release"])

    def test_17_generated_none_and_empty_response_are_not_ack(self):
        worker = self.workers.WorkersClient(self.config)
        worker._wa = lambda client: Value(worker_update=lambda **kw: None)
        with self.assertRaises(self.rest.ReceiverRestError) as caught:
            worker.pause("worker")
        self.assertEqual(caught.exception.code, "rest_not_sent")
        self.assert_safe(caught.exception)
        owners = []
        worker = self.worker(lambda owner: (owners.append(owner), setattr(owner.rest_client.pool_manager, "raw", Raw(b""))))
        with self.assertRaises(self.rest.ReceiverRestError) as caught:
            worker.pause("worker")
        self.assertEqual(caught.exception.code, "rest_delivery_uncertain")
        self.assertEqual(owners[0].rest_client.pool_manager.raw.calls, ["read", "close", "release"])

    def test_18_cross_process_owner_refuses_admission_and_close(self):
        transport = self.transport()
        transport.pid = -1
        with self.assertRaises(self.rest.ReceiverRestError):
            transport.request("GET", "fake")
        self.assertFalse(transport.close())
        self.assertEqual(transport.pool_manager.calls, [])
        self.assertEqual(transport.pool_manager.clear_calls, 0)
        transport.pid = os.getpid()
        self.assertTrue(transport.close())

    def test_19_hanging_pool_close_does_not_block_snapshot(self):
        transport = self.transport()
        pool = transport.pool_manager.connection_from_pool_key("one")
        entered, release = threading.Event(), threading.Event()
        errors = []
        def blocked_close():
            pool.calls += 1
            entered.set()
            if not release.wait(2):
                raise RuntimeError("fake gate was not released")
        pool.close = blocked_close
        def close():
            try:
                transport.close()
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=close)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(transport.settlement_snapshot["cleanup_attempted"])
            self.assertFalse(transport.settlement_snapshot["cleanup_complete"])
            self.assertFalse(transport.close())
            self.assertEqual(pool.calls, 1)
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(transport.settlement_snapshot["cleanup_complete"])

    def test_20_control_during_cleanup_still_sweeps_other_owners(self):
        transport = self.transport()
        first = transport.pool_manager.connection_from_pool_key("one")
        second = transport.pool_manager.connection_from_pool_key("two")
        def interrupt():
            first.calls += 1
            raise KeyboardInterrupt()
        first.close = interrupt
        with self.assertRaises(KeyboardInterrupt):
            transport.close()
        self.assertEqual((first.calls, second.calls, transport.pool_manager.clear_calls), (1, 1, 1))
        self.assertFalse(transport.close())
        self.assertEqual(first.calls, 1)

    def test_21_source_symlink_guard_before_output(self):
        source_file = self.source / self.app.FILES[0]
        original = Path.is_symlink
        def linked(path):
            return path == source_file or original(path)
        target = self.scratch / "symlink-guard-output"
        with patch.object(Path, "is_symlink", linked), self.assertRaises(ValueError):
            self.app.apply(self.source, target)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
