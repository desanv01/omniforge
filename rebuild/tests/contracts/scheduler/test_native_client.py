"""Fake-only partial receiver seam; no real SDK/Worker/process construction."""
import asyncio
import builtins
from dataclasses import replace
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from uuid import UUID

from services.worker.native_client import (ReceiverConfig,ReceiverPolicy,ReceiverFailure,
    ReceiverCleanupFailure,UnsupportedReceiver,construct_receiver)


class NativeClientProof(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config=ReceiverConfig(UUID(int=1),UUID(int=2),UUID(int=3),"of_b3c_","Harmless","receiver",
            "127.0.0.1:7077","http://127.0.0.1:8888",.05)
        original=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name.split('.')[0] in ("hatchet_sdk","grpc","aiohttp","multiprocessing","subprocess"):
                raise AssertionError("Native construction/import forbidden in offline proof")
            return original(name,*args,**kwargs)
        guard=patch("builtins.__import__",side_effect=guarded)
        guard.start()
        self.addCleanup(guard.stop)

    async def test_01_closed_policy_and_exact_names_to_fake_constructor(self):
        seen=[]
        async def adapter(policy,owner):
            seen.append(policy)
            return object()
        handle=await construct_receiver(self.config,"synthetic-token",constructor=adapter)
        policy=seen[0]
        self.assertEqual(policy.config.normalized_workflow_name,"of_b3c_Harmless")
        self.assertEqual(policy.config.normalized_worker_name,"of_b3c_receiver")
        self.assertEqual(policy.settings_sources,("explicit_init",))
        self.assertEqual(dict(policy.grpc_options),{"grpc.enable_retries":0,"grpc.enable_http_proxy":0})
        self.assertEqual(dict(policy.retry)["max_attempts"],1)
        self.assertFalse(dict(policy.rest)["trust_env"])
        self.assertNotIn("synthetic-token",repr(policy))
        await handle.close()

    async def test_02_default_fails_before_sdk_import_or_constructor(self):
        with self.assertRaises(UnsupportedReceiver):
            await construct_receiver(self.config,"token")

    async def test_03_invalid_explicit_config_and_auth_reject_before_adapter(self):
        for changes in ({"namespace":"UPPER_"},{"namespace":"missing"},{"workflow_name":"of_b3c_double"},
            {"grpc_target":"localhost:7077"},{"rest_origin":"http://host.docker.internal:8888"},
            {"workflow_version_id":"not-uuid"},{"cleanup_seconds":True}):
            with self.assertRaises(ValueError): replace(self.config,**changes)
        async def forbidden(*args): self.fail("Invalid token reached adapter")
        with self.assertRaises(ValueError):
            await construct_receiver(self.config,"bad\nheader",constructor=forbidden)

    async def test_04_owned_exact_resources_once_borrowed_never_closed(self):
        closed=[]
        async def adapter(policy,owner):
            for kind in ("child","client","channel"):
                async def close(k=kind): closed.append(k)
                owner.register(object(),kind=kind,close=close,owned=True)
            async def borrowed(): self.fail("Borrowed resource closed")
            owner.register(object(),kind="channel",close=borrowed,owned=False)
            return object()
        handle=await construct_receiver(self.config,"token",constructor=adapter)
        await handle.close()
        await handle.close()
        self.assertCountEqual(closed,["child","client","channel"])

    async def test_05_partial_adapter_failure_closes_registered_resource_safely(self):
        closed=[]
        async def adapter(policy,owner):
            async def close(): closed.append(True)
            owner.register(object(),kind="client",close=close,owned=True)
            raise RuntimeError("PRIVATE_NATIVE_TOKEN")
        with self.assertRaises(ReceiverFailure) as caught:
            await construct_receiver(self.config,"token",constructor=adapter)
        self.assertEqual(closed,[True])
        self.assertNotIn("PRIVATE",str(caught.exception))

    async def test_06_cancel_during_construction_settles_registered_child(self):
        entered=asyncio.Event()
        closed=[]
        async def adapter(policy,owner):
            async def close(): closed.append(True)
            owner.register(object(),kind="child",close=close,owned=True)
            entered.set()
            await asyncio.Event().wait()
        task=asyncio.create_task(construct_receiver(self.config,"token",constructor=adapter))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(closed,[True])

    async def test_07_cleanup_failure_explicit_no_raw_diagnostics(self):
        async def adapter(policy,owner):
            async def close(): raise RuntimeError("PRIVATE_NATIVE_TOKEN")
            owner.register(object(),kind="client",close=close,owned=True)
            return object()
        handle=await construct_receiver(self.config,"token",constructor=adapter)
        with self.assertRaises(ReceiverCleanupFailure) as caught: await handle.close()
        self.assertNotIn("PRIVATE",str(caught.exception))

    async def test_08_timeout_keeps_noncooperative_exact_resource_visible(self):
        release=asyncio.Event()
        async def adapter(policy,owner):
            async def close():
                try: await release.wait()
                except asyncio.CancelledError: await release.wait()
            owner.register(object(),kind="child",close=close,owned=True)
            return object()
        handle=await construct_receiver(self.config,"token",constructor=adapter)
        with self.assertRaises(ReceiverCleanupFailure): await handle.close()
        self.assertEqual(len(handle.ownership.unresolved),1)
        release.set()
        await asyncio.gather(*handle.ownership.unresolved)

    async def test_09_ambient_values_are_not_read_or_temporarily_modified(self):
        import os
        async def adapter(policy,owner):
            self.assertEqual(policy.config.grpc_target,"127.0.0.1:7077")
            self.assertEqual(policy.token,"explicit-token")
            return object()
        with patch.dict(os.environ,{"HATCHET_CLIENT_TOKEN":"ambient-secret","HATCHET_CLIENT_HOST_PORT":"evil:1"}):
            async with await construct_receiver(self.config,"explicit-token",constructor=adapter): pass
            self.assertEqual(os.environ["HATCHET_CLIENT_HOST_PORT"],"evil:1")

    async def test_10_import_is_inert_under_native_import_guards(self):
        import services.worker.native_client as module
        fresh=types.ModuleType("native_client_import_proof")
        sys.modules[fresh.__name__]=fresh
        try:
            exec(compile(Path(module.__file__).read_text(),module.__file__,"exec"),fresh.__dict__)
            self.assertTrue(callable(fresh.construct_receiver))
        finally: del sys.modules[fresh.__name__]


if __name__ == "__main__": unittest.main()
