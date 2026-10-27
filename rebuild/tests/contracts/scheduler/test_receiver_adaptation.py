"""Copied six-file derivative proof; no SDK/client/channel/process construction."""
import asyncio
import ast
import builtins
import importlib.util
import json
from pathlib import Path
import sys
import sysconfig
import tempfile
import types
import unittest
from unittest.mock import patch


ARTIFACT=Path(__file__).resolve().parents[3]/"infra"/"scheduler"/"receiver-adaptation"


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


class AdaptationProof(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.applicator=load("receiver_patch_applicator",ARTIFACT/"apply_patch.py")
        cls.scratch=Path(tempfile.mkdtemp(prefix="receiver-adaptation-"))
        cls.source=cls.scratch/"upstream"
        cls.source.mkdir()
        installed=Path(sysconfig.get_paths()["purelib"])
        for name in cls.applicator.FILES:
            target=cls.source/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((installed/name).read_bytes())
        metadata=cls.source/"hatchet_sdk-1.41.1.dist-info"/"METADATA"
        metadata.parent.mkdir();metadata.write_bytes((installed/metadata.parent.name/"METADATA").read_bytes())
        cls.derivative=cls.scratch/"derivative"
        cls.hashes=cls.applicator.apply(cls.source,cls.derivative)

    def setUp(self):
        modules={}
        for name in ("hatchet_sdk","hatchet_sdk.utils"):
            module=types.ModuleType(name);module.__path__=[];modules[name]=module
        logger=types.ModuleType("hatchet_sdk.logger")
        logger.logger=types.SimpleNamespace(debug=lambda *a,**k:None)
        modules[logger.__name__]=logger
        token=types.ModuleType("hatchet_sdk.token")
        def forbidden(*args,**kwargs): raise AssertionError("Ambient/JWT/real transport path selected")
        token.get_addresses_from_jwt=token.get_tenant_id_from_jwt=forbidden
        modules[token.__name__]=token
        otel=types.ModuleType("hatchet_sdk.utils.opentelemetry");otel.OTelAttribute=str
        modules[otel.__name__]=otel
        self.modules=patch.dict(sys.modules,modules)
        self.modules.start();self.addCleanup(self.modules.stop)
        # Source objects themselves must never be constructed, including eager
        # TenacityConfig at import. BaseModel avoids BaseSettings discovery.
        import pydantic_settings.main as settings
        original_import=builtins.__import__
        def import_guard(name,*args,**kwargs):
            if name.split('.')[0] in ("grpc","aiohttp","multiprocessing","subprocess"):
                raise AssertionError("Real native transport/process path forbidden")
            return original_import(name,*args,**kwargs)
        guard=patch("builtins.__import__",side_effect=import_guard)
        guard.start();self.addCleanup(guard.stop)
        self.traps=[]
        for name in ("EnvSettingsSource","DotEnvSettingsSource","SecretsSettingsSource"):
            guard=patch.object(settings,name,side_effect=forbidden)
            guard.start();self.addCleanup(guard.stop)
        self.config=load("hatchet_sdk.config",self.derivative/"hatchet_sdk/config.py")
        self.connection=load("receiver_derivative_connection",self.derivative/"hatchet_sdk/connection.py")

    def values(self):
        return dict(token="eySyntheticOnly",tenant_id="00000000-0000-0000-0000-000000000001",
            host_port="127.0.0.1:7077",server_url="http://127.0.0.1:8888",namespace="of_b3c_",
            tls_config={"strategy":"none"},healthcheck={"enabled":False},otel={},
            tenacity={"max_attempts":1,"retry_429":False,"retry_not_found":False,"retry_transport_errors":False})

    async def test_01_exact_six_file_derivative_hashes_and_import_defaults(self):
        manifest=json.loads((ARTIFACT/"upstream-manifest.json").read_text())
        self.assertEqual(set(self.hashes),set(self.applicator.FILES))
        for name,value in self.hashes.items(): self.assertEqual(value,manifest["files"][name]["derivative_sha256"])
        self.assertEqual(self.config.TenacityConfig().max_attempts,1)
        self.assertFalse(self.config.HealthcheckConfig().enabled)

    async def test_02_explicit_nested_settings_and_no_jwt_endpoint_fallback(self):
        value=self.config.ClientConfig(**self.values())
        self.assertEqual(value.host_port,"127.0.0.1:7077")
        self.assertEqual(value.namespace,"of_b3c_")
        self.assertEqual(value.grpc_max_recv_message_length,65536)
        dumped=value.model_dump()
        self.assertEqual(dumped["tenacity"]["max_attempts"],1)
        self.assertEqual(dumped["tls_config"]["server_name"],"127.0.0.1")
        self.assertEqual(self.config.ClientConfig.model_validate(dumped).namespace,"of_b3c_")
        for key in ("_env_file","_secrets_dir","unknown_receiver_option"):
            with self.assertRaises(ValueError): self.config.ClientConfig(**{**self.values(),key:"ambient"})
        for key in self.values():
            data=self.values();del data[key]
            with self.assertRaises(ValueError): self.config.ClientConfig(**data)

    async def test_03_bad_policy_and_endpoint_reject(self):
        for changes in ({"host_port":"evil:7077"},{"namespace":"UPPER_"},{"embedded":{}},{"debug":True},
            {"tenacity":{"max_attempts":5}},{"tls_config":{"strategy":"tls"}}):
            with self.assertRaises(ValueError): self.config.ClientConfig(**{**self.values(),**changes})

    async def test_04_no_scope_or_foreign_process_fails_before_channel(self):
        config=self.config.ClientConfig(**self.values())
        with self.assertRaises(self.connection.ReceiverScopeError): self.connection.new_conn(config,False)
        scope=self.connection.ReceiverResources(sync_constructor=lambda **k:self.fail("Channel selected"))
        scope.pid=-1
        with self.assertRaises(self.connection.ReceiverScopeError): scope.__enter__()
        with self.assertRaises(self.connection.ReceiverScopeError): scope.close()
        with self.assertRaises(self.connection.ReceiverScopeError): await scope.aclose()

    async def test_05_exact_sync_async_options_owned_once(self):
        calls=[];closed=[]
        class Sync:
            def close(inner): closed.append("sync")
        class Async:
            async def close(inner): closed.append("async")
        def sync(**kw): calls.append(kw);return Sync()
        def async_(**kw): calls.append(kw);return Async()
        config=self.config.ClientConfig(**self.values())
        scope=self.connection.ReceiverResources(sync_constructor=sync,async_constructor=async_)
        async with scope:
            self.connection.new_conn(config,False);self.connection.new_conn(config,True)
        await scope.aclose()
        self.assertCountEqual(closed,["sync","async"])
        for call in calls:
            self.assertEqual(call["options"],self.connection.OPTIONS)
            self.assertEqual(call["interceptors"],())
            self.assertEqual(dict(call["options"])["grpc.enable_retries"],0)
            self.assertEqual(dict(call["options"])["grpc.enable_http_proxy"],0)

    async def test_06_partial_constructor_and_close_failure_are_safe(self):
        config=self.config.ClientConfig(**self.values())
        def fail(**kw): raise RuntimeError("PRIVATE_UPSTREAM_DIAGNOSTIC")
        with self.connection.ReceiverResources(sync_constructor=fail):
            with self.assertRaises(self.connection.ReceiverScopeError) as caught: self.connection.new_conn(config,False)
            self.assertNotIn("PRIVATE",str(caught.exception))
        class Bad:
            def close(inner): raise RuntimeError("PRIVATE_UPSTREAM_DIAGNOSTIC")
        scope=self.connection.ReceiverResources(sync_constructor=lambda **k:Bad())
        with self.assertRaises(self.connection.ReceiverScopeError):
            with scope: self.connection.new_conn(config,False)
        self.assertEqual(len(scope.unresolved),1)

    async def test_07_scope_not_picklable_and_no_parent_registry_for_child(self):
        import pickle
        scope=self.connection.ReceiverResources()
        with self.assertRaises(self.connection.ReceiverScopeError): pickle.dumps(scope)
        with scope:
            with self.assertRaises(self.connection.ReceiverScopeError): self.connection.ReceiverResources().__enter__()

    async def test_08_hash_version_context_and_existing_target_reject(self):
        with self.assertRaises(ValueError): self.applicator.apply(self.source,self.derivative)
        with self.assertRaises(ValueError): self.applicator.apply(self.source,self.source)
        original=(self.source/"hatchet_sdk/connection.py").read_bytes()
        try:
            (self.source/"hatchet_sdk/connection.py").write_bytes(original+b"# drift\n")
            with self.assertRaises(ValueError): self.applicator.apply(self.source,self.scratch/"mismatch")
            self.assertFalse((self.scratch/"mismatch").exists())
        finally: (self.source/"hatchet_sdk/connection.py").write_bytes(original)
        with self.assertRaises(ValueError): self.applicator.patched(b"one\n",["@@ -1 +1 @@\n","-wrong\n","+two\n"])
        metadata=self.source/"hatchet_sdk-1.41.1.dist-info/METADATA"
        raw=metadata.read_bytes()
        try:
            metadata.write_bytes(raw.replace(b"Version: 1.41.1",b"Version: 9.9.9"))
            with self.assertRaises(ValueError): self.applicator.apply(self.source,self.scratch/"wrong-version")
        finally: metadata.write_bytes(raw)

    async def test_09_async_close_timeout_is_explicit_and_scope_is_left(self):
        config=self.config.ClientConfig(**self.values())
        closed=[]
        class Stalled:
            async def close(inner):
                try: await asyncio.Event().wait()
                finally: closed.append(True)
        scope=self.connection.ReceiverResources(async_constructor=lambda **kw:Stalled(),close_seconds=.02)
        with self.assertRaises(self.connection.ReceiverScopeError):
            async with scope: self.connection.new_conn(config,True)
        self.assertEqual(len(scope.unresolved),1)
        await asyncio.sleep(0)
        self.assertEqual(closed,[True])
        with self.assertRaises(self.connection.ReceiverScopeError): self.connection.new_conn(config,False)

    async def test_10_imported_new_conn_alias_and_spawn_serialization_inputs(self):
        config=self.config.ClientConfig(**self.values())
        alias=self.connection.new_conn
        calls=[]
        class Sync:
            def close(inner): calls.append("close")
        with self.connection.ReceiverResources(sync_constructor=lambda **kw:Sync()):
            alias(config,False)
        with self.assertRaises(self.connection.ReceiverScopeError): alias(config,False)
        serialized=config.model_dump()
        copied=self.config.ClientConfig.model_validate(serialized)
        self.assertEqual(copied.host_port,config.host_port)
        self.assertEqual(copied.tenacity.max_attempts,1)
        self.assertEqual(copied.apply_namespace("Harmless"),"of_b3c_Harmless")
        self.assertEqual(calls,["close"])

    async def test_11_resistant_close_task_is_owned_and_joined_without_reissue(self):
        config=self.config.ClientConfig(**self.values())
        release=asyncio.Event()
        calls=[]
        class Resistant:
            async def close(inner):
                calls.append(True)
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
        scope=self.connection.ReceiverResources(async_constructor=lambda **kw:Resistant(),close_seconds=.02)
        try:
            with self.assertRaises(self.connection.ReceiverScopeError):
                async with scope:
                    channel=self.connection.new_conn(config,True)
            await asyncio.sleep(0)
            self.assertEqual(scope.unresolved,[channel])
            self.assertEqual(len(scope.unresolved_tasks),1)
            task=scope.unresolved_tasks[0]
            self.assertFalse(task.done())
            with self.assertRaises(self.connection.ReceiverScopeError):
                await scope.join_unresolved(timeout=.01)
            self.assertIs(scope.unresolved_tasks[0],task)
            self.assertEqual(calls,[True])
            release.set()
            self.assertTrue(await scope.join_unresolved(timeout=.2))
            self.assertTrue(task.done())
            self.assertEqual(scope.unresolved_tasks,())
            self.assertEqual(scope.unresolved,[])
            scope.close()
            await scope.aclose()
            self.assertEqual(calls,[True])
        finally:
            release.set()
            if scope.unresolved_tasks:
                await asyncio.gather(*scope.unresolved_tasks,return_exceptions=True)

    async def test_12_sync_close_during_async_sweep_cannot_claim_settled(self):
        config=self.config.ClientConfig(**self.values())
        entered,release=asyncio.Event(),asyncio.Event()
        calls=[]
        class Async:
            async def close(inner):
                calls.append("async")
                entered.set()
                await release.wait()
        class Sync:
            def close(inner): calls.append("sync")
        scope=self.connection.ReceiverResources(sync_constructor=lambda **kw:Sync(),async_constructor=lambda **kw:Async())
        with scope:
            self.connection.new_conn(config,False)
            self.connection.new_conn(config,True)
            running=asyncio.create_task(scope.aclose())
            try:
                await asyncio.sleep(0)
                self.assertIsNotNone(scope._closing)
                with self.assertRaises(self.connection.ReceiverScopeError): scope.close()
                await entered.wait()
                with self.assertRaises(self.connection.ReceiverScopeError): scope.close()
                self.assertFalse(running.done())
                release.set()
                await running
                scope.close()
                await scope.aclose()
                self.assertCountEqual(calls,["async","sync"])
            finally:
                release.set()
                await running

    async def test_13_sync_then_async_close_completes_only_unswept_resources(self):
        config=self.config.ClientConfig(**self.values())
        calls=[]
        class Sync:
            def close(inner): calls.append("sync")
        class Async:
            async def close(inner): calls.append("async")
        scope=self.connection.ReceiverResources(sync_constructor=lambda **kw:Sync(),async_constructor=lambda **kw:Async())
        async with scope:
            self.connection.new_conn(config,False)
            self.connection.new_conn(config,True)
            with self.assertRaises(self.connection.ReceiverScopeError): scope.close()
            self.assertEqual(calls,["sync"])
            await scope.aclose()
            self.assertEqual(scope.unresolved,[])
            scope.close()
        self.assertCountEqual(calls,["sync","async"])


if __name__=="__main__": unittest.main()
