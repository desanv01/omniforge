"""Factory tests use injected resources only; default transports are guarded."""
import asyncio
from dataclasses import replace
import importlib
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.worker import hatchet_factory as factory
from services.worker.hatchet_port import RawSdkClient


class Channel:
    def __init__(self):
        self.closed = 0
        self.error = self.stall = False

    async def close(self):
        self.closed += 1
        if self.error:
            raise RuntimeError("PRIVATE_FACTORY_TOKEN")
        if self.stall:
            await asyncio.Event().wait()


class Session(Channel):
    trust_env = False
    auto_decompress = False
    _middlewares = ()
    _retry_connection = True

    def __init__(self,headers):
        super().__init__()
        self.headers = headers


class FactoryProof(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Any accidental default constructor selection fails before network or
        # credential discovery. All actual calls below inject all three hooks.
        self.guards = [patch.object(factory,"_default_channel",side_effect=AssertionError("Real channel forbidden")),
            patch.object(factory,"_default_session",side_effect=AssertionError("Real session forbidden")),
            patch.object(factory,"_default_stub",side_effect=AssertionError("Real stub forbidden")),
            patch.object(factory,"_pins",side_effect=AssertionError("Default dependency path forbidden"))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)
        self.config = factory.TransportConfig("127.0.0.1:7070","http://127.0.0.1:8080","development",cleanup_seconds=.1)
        self.channel = Channel()
        self.session = None
        self.options = None
        self.owned = True
        self.session_error = False

    def hooks(self):
        def channel(config,options):
            self.options = options
            return factory.Resource(self.channel,self.owned)
        def session(config,headers):
            if self.session_error:
                raise RuntimeError("PRIVATE_FACTORY_TOKEN")
            self.session = Session(headers)
            if not self.owned:
                self.session._retry_connection = False
            return factory.Resource(self.session,self.owned)
        return factory.Constructors(channel,session,lambda ch:SimpleNamespace(TriggerWorkflow=self.rpc))

    async def rpc(self,*args,**kwargs):
        raise AssertionError("No RPC operation authorized by construction test")

    async def test_01_assembles_actual_raw_client_with_fixed_retry_auth_and_owned_close(self):
        async with factory.open_transport(self.config,"synthetic-token",constructors=self.hooks()) as transport:
            self.assertIs(type(transport.client),RawSdkClient)
            self.assertEqual(dict(self.options)["grpc.enable_retries"],0)
            self.assertEqual(dict(self.options)["grpc.enable_http_proxy"],0)
            self.assertEqual(self.session.headers,{"Authorization":"Bearer synthetic-token"})
            self.assertEqual(transport.client._metadata,(("authorization","bearer synthetic-token"),))
            self.assertIs(self.session._retry_connection,False)
            self.assertNotIn("synthetic-token",repr(transport))
        await transport.close()
        self.assertEqual((self.channel.closed,self.session.closed),(1,1))
        self.assertIsNone(transport.client)

    async def test_02_invalid_destinations_and_tls_modes_reject_before_constructors(self):
        invalid = [("evil:7070","http://127.0.0.1","development"),
            ("127.0.0.1:7070","http://evil.example","development"),
            ("127.0.0.1:7070","https://127.0.0.1","development"),
            ("user:secret@evil:7070","https://evil","tls"),
            ("127.0.0.1:7070\n","http://127.0.0.1","development"),
            ("dns:///evil:7070","https://evil","tls"),
            ("evil:7070","https://evil/path","tls")]
        for args in invalid:
            with self.assertRaisesRegex(ValueError,"Invalid explicit"):
                factory.TransportConfig(*args)
        with self.assertRaises(ValueError):
            factory.TransportConfig("evil:7070","https://evil","tls")
        with self.assertRaises(ValueError):
            async with factory.open_transport(self.config,"bad\r\nsecret",constructors=self.hooks()):
                self.fail("Invalid credentials admitted")
        self.assertEqual(self.channel.closed,0)

    async def test_03_tls_explicit_ca_and_options_pass_to_injected_constructor(self):
        config = factory.TransportConfig("scheduler.example:443","https://scheduler.example","tls",
            ca_pem=b"-----BEGIN CERTIFICATE-----\nSYNTHETIC\n-----END CERTIFICATE-----",cleanup_seconds=.1)
        async with factory.open_transport(config,"token",constructors=self.hooks()):
            self.assertEqual(self.options,factory.GRPC_OPTIONS)
        self.assertNotIn("SYNTHETIC",repr(config))

    async def test_04_borrowed_resources_are_neither_mutated_nor_closed(self):
        self.owned = False
        async with factory.open_transport(self.config,"token",constructors=self.hooks()):
            self.assertIs(self.session._retry_connection,False)
        self.assertEqual((self.channel.closed,self.session.closed),(0,0))

    async def test_05_partial_session_failure_closes_only_created_channel_and_sanitizes(self):
        self.session_error = True
        with self.assertRaises(factory.ConstructionError) as caught:
            async with factory.open_transport(self.config,"token",constructors=self.hooks()):
                self.fail("Failed initialization yielded")
        self.assertNotIn("PRIVATE",str(caught.exception))
        self.assertEqual(self.channel.closed,1)

    async def test_06_partial_stub_failure_closes_channel(self):
        hooks = replace(self.hooks(),stub=lambda _:(_ for _ in ()).throw(RuntimeError("PRIVATE_FACTORY_TOKEN")))
        with self.assertRaises(factory.ConstructionError):
            async with factory.open_transport(self.config,"token",constructors=hooks):
                self.fail("Failed stub yielded")
        self.assertEqual(self.channel.closed,1)

    async def test_07_rejected_session_policy_closes_both_resources(self):
        original = self.hooks()
        def invalid(config,headers):
            resource = original.session(config,headers)
            resource.value.trust_env = True
            return resource
        with self.assertRaises(factory.ConstructionError):
            async with factory.open_transport(self.config,"token",constructors=replace(original,session=invalid)):
                self.fail("Unsafe session admitted")
        self.assertEqual((self.channel.closed,self.session.closed),(1,1))

    async def test_08_body_exception_closes_owned_resources(self):
        with self.assertRaisesRegex(RuntimeError,"synthetic body"):
            async with factory.open_transport(self.config,"token",constructors=self.hooks()):
                raise RuntimeError("synthetic body")
        self.assertEqual((self.channel.closed,self.session.closed),(1,1))

    async def test_09_body_cancellation_closes_before_cancel_propagates(self):
        entered = asyncio.Event()
        async def task():
            async with factory.open_transport(self.config,"token",constructors=self.hooks()):
                entered.set()
                await asyncio.Event().wait()
        running = asyncio.create_task(task())
        await entered.wait()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertEqual((self.channel.closed,self.session.closed),(1,1))

    async def test_10_cleanup_failure_is_explicit_and_sanitized_once(self):
        self.channel.error = True
        with self.assertRaises(factory.CleanupError) as caught:
            async with factory.open_transport(self.config,"token",constructors=self.hooks()) as transport:
                pass
        self.assertEqual(caught.exception.codes,("channel_close_failed",))
        self.assertNotIn("PRIVATE",str(caught.exception))
        with self.assertRaises(factory.CleanupError):
            await transport.close()
        self.assertEqual((self.channel.closed,self.session.closed),(1,1))

    async def test_11_stalled_cleanup_is_bounded_and_reported_unresolved(self):
        self.channel.stall = True
        start = time.monotonic()
        with self.assertRaises(factory.CleanupError) as caught:
            async with factory.open_transport(self.config,"token",constructors=self.hooks()):
                pass
        self.assertLess(time.monotonic()-start,.5)
        self.assertEqual(caught.exception.codes,("channel_close_timeout",))
        self.assertEqual(self.session.closed,1)

    async def test_12_cancel_during_async_initialization_settles_created_resource(self):
        entered = asyncio.Event()
        async def session(config,headers):
            entered.set()
            await asyncio.Event().wait()
        hooks = replace(self.hooks(),session=session)
        async def run():
            async with factory.open_transport(self.config,"token",constructors=hooks):
                self.fail("Canceled initialization yielded")
        task = asyncio.create_task(run())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.channel.closed,1)

    async def test_13_module_reload_has_no_transport_or_dependency_discovery(self):
        # Compile/execute in a fresh namespace while imports of real transport
        # packages/config constructors are blocked. No default is called.
        import builtins
        from pathlib import Path
        original = builtins.__import__
        def guarded(name,*args,**kwargs):
            if name.split('.')[0] in ("grpc","aiohttp","hatchet_sdk"):
                raise AssertionError("Real transport import forbidden")
            return original(name,*args,**kwargs)
        module = SimpleNamespace()
        namespace = {"__name__":"factory_import_purity"}
        import types
        actual = types.ModuleType(namespace["__name__"])
        sys.modules[actual.__name__] = actual
        try:
            with patch("builtins.__import__",side_effect=guarded),patch("importlib.metadata.version",side_effect=AssertionError("Version discovery forbidden")):
                exec(compile(Path(factory.__file__).read_text(),factory.__file__,"exec"),actual.__dict__)
            self.assertTrue(callable(actual.open_transport))
        finally:
            del sys.modules[actual.__name__]

    async def test_14_repeated_cancel_during_close_does_not_duplicate_or_detach(self):
        entered,release=asyncio.Event(),asyncio.Event()
        async def close():
            self.channel.closed+=1
            entered.set()
            await release.wait()
        self.channel.close=close
        async def run():
            async with factory.open_transport(self.config,"token",constructors=self.hooks()):
                pass
        task=asyncio.create_task(run())
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual((self.channel.closed,self.session.closed),(1,1))

    async def test_15_borrowed_retry_policy_is_rejected_without_mutation_or_close(self):
        hooks=self.hooks()
        session=Session({"Authorization":"Bearer token"})
        hooks=replace(hooks,session=lambda config,headers:factory.Resource(session,False))
        with self.assertRaises(factory.ConstructionError):
            async with factory.open_transport(self.config,"token",constructors=hooks):
                self.fail("Unsafe borrowed session admitted")
        self.assertIs(session._retry_connection,True)
        self.assertEqual(session.closed,0)
        self.assertEqual(self.channel.closed,1)

    async def test_16_noncooperative_close_is_retained_as_unresolved_until_settled(self):
        release=asyncio.Event()
        async def close():
            self.channel.closed+=1
            try: await release.wait()
            except asyncio.CancelledError: await release.wait()
        self.channel.close=close
        with self.assertRaises(factory.CleanupError):
            async with factory.open_transport(self.config,"token",constructors=self.hooks()) as transport:
                pass
        self.assertEqual(len(transport.unresolved_cleanup),1)
        self.assertFalse(transport.unresolved_cleanup[0].done())
        release.set()
        await asyncio.gather(*transport.unresolved_cleanup)
        self.assertEqual(self.channel.closed,1)


if __name__ == "__main__":
    unittest.main()
