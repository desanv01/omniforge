"""Actual copied C1 methods, isolated fake transports; no native construction."""
import ast
import asyncio
import copy
import json
import multiprocessing.synchronize
from pathlib import Path
from queue import Queue
import shutil
import sys
import traceback
import types
import unittest
from unittest.mock import patch

import test_receiver_adaptation_rpc as support


# Keep this native stdlib import graph alive before either whole-sys.modules
# snapshot. Loading it inside the copied child's fixture import lets restoration
# evict/reinitialize _multiprocessing between cases (Linux crash at SemLock).
_SYNCHRONIZE_MODULE = sys.modules['multiprocessing.synchronize']
_MULTIPROCESSING_EXTENSION = sys.modules['_multiprocessing']


class EventProof(unittest.IsolatedAsyncioTestCase):
    setUpClass = classmethod(support.RpcProof.setUpClass.__func__)
    assert_safe_rpc_error = support.RpcProof.assert_safe_rpc_error

    def setUp(self):
        # Registered first, so this runs after both module guards restore state.
        self.addCleanup(self.assert_native_import_identity)
        support.RpcProof.setUp(self)
        modules = {}

        def module(name):
            if name in sys.modules and name.startswith('hatchet_sdk'):
                return sys.modules[name]
            if name not in modules:
                m = support.FakeModule(name)
                m.__path__ = []
                modules[name] = m
                if '.' in name:
                    parent, child = name.rsplit('.', 1)
                    setattr(module(parent), child, m)
            return modules[name]

        path = self.output / 'hatchet_sdk/worker/action_listener_process.py'
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and node.module.startswith(('hatchet_sdk', 'aiohttp', 'prometheus_client')):
                module(node.module)
        modules['hatchet_sdk.clients.dispatcher.dispatcher'] = self.dispatcher
        module('hatchet_sdk.runnables.action').ActionType = types.SimpleNamespace(
            START_STEP_RUN='normal', CANCEL_STEP_RUN='cancel', START_BATCH='batch')
        self.stop = object()
        module('hatchet_sdk.utils.typing').STOP_LOOP = self.stop
        class Timestamp(support.Value):
            def GetCurrentTime(inner): inner.now_observed = True
        self.dispatcher.Timestamp = Timestamp
        guard = patch.dict(sys.modules, modules)
        guard.start()
        self.addCleanup(guard.stop)
        self.child = support.load('event_child', path)

    def assert_native_import_identity(self):
        self.assertIs(sys.modules.get('multiprocessing.synchronize'), _SYNCHRONIZE_MODULE)
        self.assertIs(sys.modules.get('_multiprocessing'), _MULTIPROCESSING_EXTENSION)

    def action(self, kind='normal'):
        return support.Value(action_type=kind, worker_id='worker', job_id='job',
            job_run_id='job-run', step_id='step', step_run_id='run', action_id='action',
            retry_count=2, batch_id='batch')

    def event(self, kind='normal'):
        return self.child.ActionEvent(self.action(kind), 'completed', 'PRIVATE_PAYLOAD', True)

    def owner(self, dispatcher):
        # Do not invoke vendor constructor, Client, signal handlers or health server.
        obj = self.child.WorkerActionListenerProcess.__new__(self.child.WorkerActionListenerProcess)
        obj.dispatcher_client = dispatcher
        obj.running_step_runs = {}
        obj.step_action_events = set()
        obj.unresolved_sends = {}
        obj.terminal_delivery = None
        obj._event_sequence = 0
        obj.event_queue = Queue()
        obj._parent_is_dead = lambda: False
        return obj

    async def test_01_dispatcher_fields_response_deadline_and_one_call(self):
        calls = []
        response = object()
        class Stub:
            async def SendStepActionEvent(inner, event, **kw):
                calls.append((event, kw)); return response
            async def SendBatchActionEvent(inner, event, **kw):
                calls.append((event, kw)); return response
        class SyncStub:
            def SendBatchActionEvent(inner, event, **kw):
                calls.append((event, kw)); return response
        client = self.dispatcher.DispatcherClient(self.config)
        client.aio_client = Stub(); client.client = SyncStub()
        self.assertIs(await client.send_step_action_event(self.action(), 'completed', 'payload', True), response)
        normal = calls[0][0]
        self.assertEqual((normal.worker_id, normal.job_id, normal.job_run_id, normal.task_id,
            normal.task_run_external_id, normal.action_id, normal.retry_count,
            normal.should_not_retry, normal.event_payload, normal.event_type),
            ('worker', 'job', 'job-run', 'step', 'run', 'action', 2, True, 'payload', 'completed'))
        self.assertTrue(normal.event_timestamp.now_observed)
        items = [support.Value(task_run_external_id='run', payload=None, should_not_retry=True)]
        self.assertIs(await client.aio_send_batch_action_event(self.action(), 'failed', items), response)
        self.assertIs(client.send_batch_action_event(self.action(), 'failed', items), response)
        for event, kw in calls:
            self.assertEqual(kw, {'timeout': 10, 'metadata': (('authorization', 'bearer PRIVATE_TOKEN'),)})
        for event, _ in calls[1:]:
            self.assertEqual((event.batch_id, event.items[0].task_run_external_id,
                event.items[0].event_payload, event.items[0].retry_count,
                event.items[0].should_not_retry), ('batch', 'run', '', 2, True))
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.channels, [])

    async def test_02_post_invocation_errors_none_and_cancellation(self):
        for mode in ('normal', 'batch', 'sync'):
            for failure in ('UNAVAILABLE', 'UNAUTHENTICATED', 'DEADLINE_EXCEEDED', 'unknown', 'none', 'cancel'):
                with self.subTest(mode=mode, failure=failure):
                    calls = []
                    def result(*a, **kw):
                        calls.append(kw)
                        if failure == 'none': return None
                        if failure == 'cancel': raise asyncio.CancelledError()
                        raise self.RpcError(failure)
                    async def aio(*a, **kw): return result(*a, **kw)
                    stub = types.SimpleNamespace(SendStepActionEvent=aio, SendBatchActionEvent=aio)
                    client = self.dispatcher.DispatcherClient(self.config)
                    client.aio_client = stub
                    client.client = types.SimpleNamespace(SendBatchActionEvent=result)
                    try:
                        if mode == 'normal': await client.send_step_action_event(self.action(), 'failed', None, False)
                        elif mode == 'batch': await client.aio_send_batch_action_event(self.action(), 'failed', [])
                        else: client.send_batch_action_event(self.action(), 'failed', [])
                    except asyncio.CancelledError:
                        self.assertEqual(failure, 'cancel')
                    except self.dispatcher.EventDeliveryError as error:
                        self.assertNotEqual(failure, 'cancel')
                        self.assert_safe_rpc_error(error, 'event_delivery_uncertain')
                    else: self.fail('Missing response/failure must not become ACK')
                    self.assertEqual(len(calls), 1)
                    self.assertIs(client.aio_client, stub)
        self.assertEqual(self.channels, [])

    async def test_03_preflight_failure_safe_before_stub(self):
        for mode in ('normal', 'batch', 'sync'):
            client = self.dispatcher.DispatcherClient(self.config)
            def fail(): raise ValueError('PRIVATE_DETAIL PRIVATE_TOKEN')
            client._get_or_create_aio_client = client._get_or_create_client = fail
            try:
                if mode == 'normal': await client.send_step_action_event(self.action(), 'failed', None, False)
                elif mode == 'batch': await client.aio_send_batch_action_event(self.action(), 'failed', [])
                else: client.send_batch_action_event(self.action(), 'failed', [])
            except self.dispatcher.EventDeliveryError as error:
                self.assert_safe_rpc_error(error, 'event_not_sent')
            else: self.fail('Expected preflight error')
        self.assertEqual(self.channels, [])

    async def test_04_child_direct_await_no_nested_task_and_skips(self):
        for batch in (False, True):
            entered, release = asyncio.Event(), asyncio.Event()
            calls = []
            response = object()
            async def send(*args):
                calls.append(args); entered.set(); await release.wait(); return response
            owner = self.owner(types.SimpleNamespace(send_step_action_event=send, aio_send_batch_action_event=send))
            event = self.child.QueuedBatchActionEvent(self.action(), 'failed', []) if batch else self.event()
            running = asyncio.create_task(owner.send_event(event))
            try:
                await entered.wait()
                self.assertFalse(running.done())
                self.assertFalse(owner.step_action_events)
                # The direct sender must never call create_task itself.
                with patch.object(self.child.asyncio, 'create_task', side_effect=AssertionError('nested send')):
                    release.set()
                    self.assertIs(await running, response)
                self.assertEqual(len(calls), 1)
                if not batch: self.assertTrue(calls[0][-1])
            finally:
                release.set(); await asyncio.gather(running, return_exceptions=True)
        for kind in ('cancel', 'batch', 'unknown'):
            self.assertEqual(await owner.send_event(self.event(kind)), 'event_not_sent')
        self.assertEqual(len(calls), 1)

    async def test_05_child_failure_none_and_cancel_are_truthful(self):
        for failure in ('error', 'none', 'cancel'):
            calls = []
            async def send(*args):
                calls.append(args)
                if failure == 'error': raise RuntimeError('PRIVATE_DETAIL PRIVATE_TOKEN')
                if failure == 'cancel': raise asyncio.CancelledError()
                return None
            owner = self.owner(types.SimpleNamespace(send_step_action_event=send))
            try: await owner.send_event(self.event())
            except asyncio.CancelledError: self.assertEqual(failure, 'cancel')
            except self.dispatcher.EventDeliveryError as error:
                self.assertNotEqual(failure, 'cancel')
                self.assert_safe_rpc_error(error, 'event_delivery_uncertain')
            else: self.fail('Missing response must not become ACK')
            self.assertEqual(len(calls), 1)

    async def test_06_single_admission_queue_order_stop_and_duplicate_items(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def send(*args):
            calls.append(args); entered.set(); await release.wait(); return object()
        owner = self.owner(types.SimpleNamespace(send_step_action_event=send))
        first = self.event(); first.type = self.child.STEP_EVENT_TYPE_STARTED
        for event in (first, first, self.stop, self.event()): owner.event_queue.put(event)
        running = asyncio.create_task(owner.start_event_send_loop())
        try:
            await entered.wait()
            self.assertEqual(len(calls), 1)
            self.assertEqual(owner.event_queue.qsize(), 3)
            self.assertEqual(len(owner.unresolved_sends), 1)
            release.set(); await running
            self.assertEqual(len(calls), 2)
            self.assertEqual(owner.event_queue.qsize(), 1)
            self.assertFalse(owner.unresolved_sends)
            self.assertFalse(owner.step_action_events)
        finally:
            release.set(); await asyncio.gather(running, return_exceptions=True)

    async def test_07_failure_stops_admission_preserves_queue_and_safe_terminal(self):
        calls = []
        async def send(*args):
            calls.append(args); raise RuntimeError('PRIVATE_PAYLOAD PRIVATE_TOKEN')
        owner = self.owner(types.SimpleNamespace(send_step_action_event=send))
        second = self.event()
        for event in (self.event(), second, self.stop): owner.event_queue.put(event)
        await owner.start_event_send_loop()
        self.assertEqual(len(calls), 1)
        self.assertIs(owner.event_queue.get_nowait(), second)
        self.assertIs(owner.event_queue.get_nowait(), self.stop)
        self.assertEqual(owner.terminal_delivery, {'sequence': 1,
            'classification': 'event_delivery_uncertain', 'admission_stopped': True})
        self.assertNotIn('PRIVATE', json.dumps(owner.terminal_delivery) + str(self.logs))
        await owner.start_event_send_loop()
        self.assertEqual(len(calls), 1)

    async def resistant(self, late_error=False, repeat_cancel=False):
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        cancellations = []
        async def send(*args):
            entered.set()
            try: await release.wait()
            except asyncio.CancelledError:
                cancellations.append(1); cancelled.set(); await release.wait()
            if late_error: raise RuntimeError('PRIVATE_LATE PRIVATE_TOKEN')
            return object()
        owner = self.owner(types.SimpleNamespace(send_step_action_event=send))
        event = self.event(); owner.event_queue.put(event); owner.event_queue.put(self.stop)
        with patch.object(self.child, 'EVENT_SEND_WAIT_SECONDS', .02), patch.object(self.child, 'EVENT_SEND_SETTLE_SECONDS', .04):
            running = asyncio.create_task(owner.start_event_send_loop())
            try:
                await entered.wait()
                if repeat_cancel: running.cancel()
                await cancelled.wait()
                if repeat_cancel: running.cancel()
                start = asyncio.get_running_loop().time()
                if repeat_cancel:
                    with self.assertRaises(asyncio.CancelledError): await running
                else: await running
                self.assertLess(asyncio.get_running_loop().time() - start, .3)
                self.assertEqual(len(owner.unresolved_sends), 1)
                task, state = next(iter(owner.unresolved_sends.items()))
                self.assertIs(state['event'], event)
                self.assertIn(task, owner.step_action_events)
                self.assertEqual(cancellations, [1])
                self.assertFalse(await owner.join_sends(.01))
                self.assertEqual(owner.event_queue.qsize(), 1)
                receipt = dict(owner.terminal_delivery)
                release.set(); self.assertTrue(await owner.join_sends(.5))
                self.assertEqual(owner.terminal_delivery, receipt)
                self.assertFalse(owner.step_action_events)
                self.assertEqual(cancellations, [1])
            finally:
                release.set()
                await asyncio.gather(running, *owner.step_action_events, return_exceptions=True)
                await owner.join_sends(.5)

    async def test_08_timeout_resistant_late_success(self):
        await self.resistant()

    async def test_09_timeout_resistant_late_error(self):
        await self.resistant(late_error=True)

    async def test_10_repeated_cancel_no_storm_strong_ownership(self):
        await self.resistant(repeat_cancel=True)

    async def test_11_queue_poll_cancel_does_not_consume_late_item(self):
        owner = self.owner(None)
        running = asyncio.create_task(owner._get_event(1))
        await asyncio.sleep(.02); running.cancel()
        with self.assertRaises(asyncio.CancelledError): await running
        item = self.event(); owner.event_queue.put(item)
        self.assertIs(await owner._get_event(.1), item)
        for timeout in (0, -1, 6):
            with self.assertRaises(ValueError): await owner.join_sends(timeout)

    async def test_12_six_file_gates_retained_outputs_and_child_drift(self):
        manifest = json.loads((support.ARTIFACT / 'upstream-manifest.json').read_text())
        self.assertEqual(len(self.app.FILES), 6)
        retained = {'hatchet_sdk/config.py': 'bbe5c491989020a316902d3aa9da18b425527714f341062090366d81c8fafbbe',
            'hatchet_sdk/connection.py': '92460665b88db933efc08f382c8aa30b7be7ed6e1b3b8da9af7a671f2d1be8f9',
            'hatchet_sdk/clients/dispatcher/action_listener.py': '5e3e2402d1c72511a1998367ae7016bc3ffe743ab444ce8b9a7bd3e37b8adc0b',
            'hatchet_sdk/clients/admin.py': '86283c077515e88af4173c067670f7f74c50b450438f56e20fb75f8c37b63c6c'}
        for name, expected in retained.items():
            self.assertEqual(self.app.sha((self.output / name).read_bytes()), expected)
        child = self.source / 'hatchet_sdk/worker/action_listener_process.py'
        raw = child.read_bytes()
        try:
            child.write_bytes(raw + b'# drift\n')
            target = self.scratch / 'child-drift'
            with self.assertRaises(ValueError): self.app.apply(self.source, target)
            self.assertFalse(target.exists())
        finally: child.write_bytes(raw)
        artifact = self.scratch / 'event-bad-artifact'; artifact.mkdir()
        for name in ('apply_patch.py', 'receiver-policy.patch', 'upstream-manifest.json'):
            shutil.copyfile(support.ARTIFACT / name, artifact / name)
        app = support.load('event_bad_app', artifact / 'apply_patch.py')
        name = 'hatchet_sdk/worker/action_listener_process.py'
        for mode in ('missing', 'extra', 'duplicate', 'final', 'lf'):
            data = copy.deepcopy(manifest)
            if mode == 'missing': del data['files'][name]
            if mode == 'extra': data['files']['extra'] = {}
            if mode == 'final': data['files'][name]['derivative_sha256'] = '0' * 64
            if mode == 'lf': data['files'][name]['upstream_lf_sha256'] = '0' * 64
            text = json.dumps(data)
            if mode == 'duplicate': text = text.replace('"files": {', '"files": {"extra": {}, "extra": {},')
            (artifact / 'upstream-manifest.json').write_text(text)
            target = self.scratch / ('event-bad-' + mode)
            with self.assertRaises(ValueError): app.apply(self.source, target)
            self.assertFalse(target.exists())
        (artifact / 'upstream-manifest.json').write_text(json.dumps(manifest))
        patchfile = artifact / 'receiver-policy.patch'
        original = patchfile.read_text(encoding='utf-8')
        for mode in ('missing', 'duplicate', 'extra'):
            section = original[original.index('--- a/' + name):]
            text = original.replace(section, '') if mode == 'missing' else original + (section if mode == 'duplicate' else '--- a/extra\n+++ b/extra\n')
            patchfile.write_text(text, encoding='utf-8')
            target = self.scratch / ('event-patch-' + mode)
            with self.assertRaises(ValueError): app.apply(self.source, target)
            self.assertFalse(target.exists())
        with self.assertRaises(ValueError): self.app.apply(self.source, self.source / 'unsafe')
        with self.assertRaises(ValueError): self.app.apply(self.source, self.output)

    async def test_13_cooperative_cancel_and_prestart_cancel(self):
        entered = asyncio.Event()
        async def send(*args):
            entered.set(); await asyncio.Event().wait()
        owner = self.owner(types.SimpleNamespace(send_step_action_event=send))
        event = self.event(); owner.event_queue.put(event); owner.event_queue.put(self.stop)
        running = asyncio.create_task(owner.start_event_send_loop())
        await entered.wait(); running.cancel()
        with self.assertRaises(asyncio.CancelledError): await running
        self.assertFalse(owner.unresolved_sends)
        self.assertEqual(owner.terminal_delivery['classification'], 'event_delivery_uncertain')
        self.assertEqual(owner.event_queue.qsize(), 1)
        # Cancel an owned send before its coroutine starts: no dispatch occurred.
        task = asyncio.create_task(owner.send_event(event))
        owner.unresolved_sends[task] = {'event': event, 'sequence': 2,
            'began': False, 'cancel_requested': False}
        owner.step_action_events.add(task)
        owner._cancel_send_once(task)
        self.assertTrue(await owner.join_sends(.5))
        self.assertTrue(task.cancelled())
        self.assertFalse(owner.step_action_events)

    async def test_14_selected_method_surface_has_no_retry_or_reconnect(self):
        path = self.output / 'hatchet_sdk/clients/dispatcher/dispatcher.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        selected = {'send_step_action_event', '_try_send_step_action_event',
            'send_batch_action_event', 'aio_send_batch_action_event', '_try_aio_send_batch_action_event'}
        methods = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected]
        self.assertEqual(len(methods), 5)
        for node in methods:
            self.assertFalse(node.decorator_list)
            text = ast.unparse(node)
            for forbidden in ('new_conn', 'sleep(', 'logger.', '.close(', 'self.aio_client =', 'self.aio_channel ='):
                self.assertNotIn(forbidden, text)

    async def competing_observers(self, mode, active_waiter):
        entered, release, cancelled, waiting = (asyncio.Event() for _ in range(4))
        calls, sends = [], []
        class CountedTask(asyncio.Task):
            observations = 0
            def result(inner):
                inner.observations += 1
                return super().result()
        async def send(*args):
            calls.append(args); entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                if mode not in ('resistant_success', 'resistant_error'):
                    raise
                await release.wait()
            if mode in ('error', 'resistant_error'):
                raise RuntimeError('PRIVATE_DETAIL PRIVATE_TOKEN')
            if mode == 'cancel':
                raise asyncio.CancelledError()
            return object()
        owner = self.owner(types.SimpleNamespace(send_step_action_event=send))
        event = self.event()
        loop = asyncio.get_running_loop()
        prior_factory = loop.get_task_factory()
        def factory(loop, coro, context=None):
            cls = CountedTask if coro.__qualname__.endswith('WorkerActionListenerProcess.send_event') else asyncio.Task
            task = cls(coro, loop=loop, context=context)
            if cls is CountedTask: sends.append(task)
            return task
        real_wait = asyncio.wait
        waiters = []
        expected_waiters = 3 if active_waiter else 2
        async def gated_wait(tasks, **kwargs):
            waiters.append(asyncio.current_task())
            if len(set(waiters)) >= expected_waiters: waiting.set()
            # Start deadlines only after distinct observers captured ownership;
            # slow Windows scheduling must not turn this into a timeout-only test.
            await waiting.wait()
            return await real_wait(tasks, **kwargs)
        running = None
        joins = []
        loop.set_task_factory(factory)
        try:
            with patch.object(self.child.asyncio, 'wait', gated_wait), patch.object(self.child, 'EVENT_SEND_WAIT_SECONDS', .04):
                if active_waiter:
                    for item in (event, self.stop, self.event()): owner.event_queue.put(item)
                    running = asyncio.create_task(owner.start_event_send_loop())
                else:
                    state = {'event': event, 'sequence': 1, 'began': False, 'cancel_requested': False}
                    task = asyncio.create_task(owner.send_event(event, ownership=state))
                    owner.unresolved_sends[task] = state
                    owner.step_action_events.add(task)
                    owner.terminal_delivery = {'sequence': 1,
                        'classification': 'event_delivery_uncertain', 'admission_stopped': True}
                await asyncio.wait_for(entered.wait(), .5)
                task = sends[0]
                state = owner.unresolved_sends[task]
                self.assertIs(state['event'], event)
                joins = [asyncio.create_task(owner.join_sends(.5)) for _ in range(2)]
                await asyncio.wait_for(waiting.wait(), .5)
                # All competing observers have captured the same state before release.
                self.assertEqual(len(set(waiters[:expected_waiters])), expected_waiters)
                if mode.startswith('resistant_'):
                    if not active_waiter: owner._cancel_send_once(task)
                    await asyncio.wait_for(cancelled.wait(), .5)
                    receipt = dict(owner.terminal_delivery)
                    self.assertIs(owner.unresolved_sends[task]['event'], event)
                    self.assertFalse(task.done())
                elif mode == 'waiter_cancel':
                    running.cancel()
                    await asyncio.wait_for(cancelled.wait(), .5)
                    receipt = dict(owner.terminal_delivery)
                else:
                    receipt = dict(owner.terminal_delivery) if owner.terminal_delivery else None
                release.set()
                self.assertEqual(await asyncio.gather(*joins), [True, True])
                if running is not None:
                    if mode == 'waiter_cancel':
                        with self.assertRaises(asyncio.CancelledError): await running
                    else: await running
                self.assertEqual(len(calls), 1)
                self.assertEqual(task.observations, 1)
                self.assertFalse(owner.unresolved_sends)
                self.assertFalse(owner.step_action_events)
                # Additional observers use the safe shared state, never result() again.
                outcome = owner._observe_send(task, state)
                self.assertEqual(task.observations, 1)
                self.assertEqual(outcome, 'event_delivery_uncertain' if mode in ('error', 'cancel', 'resistant_error', 'waiter_cancel') else 'server_response')
                self.assertNotIn('PRIVATE', json.dumps({'outcome': outcome, 'terminal': owner.terminal_delivery}) + str(self.logs))
                if receipt is not None: self.assertEqual(owner.terminal_delivery, receipt)
                if active_waiter:
                    self.assertEqual(owner.event_queue.qsize(), 1 if mode == 'success' else 2)
        finally:
            release.set()
            if running is not None: await asyncio.gather(running, return_exceptions=True)
            await asyncio.gather(*joins, *sends, return_exceptions=True)
            await owner.join_sends(.5)
            loop.set_task_factory(prior_factory)

    async def test_15_active_waiter_and_two_joins_observe_result_once(self):
        for mode in ('success', 'error', 'cancel', 'resistant_success', 'resistant_error', 'waiter_cancel'):
            with self.subTest(mode=mode):
                await self.competing_observers(mode, active_waiter=True)

    async def test_16_two_joins_observe_result_once_preserve_terminal(self):
        for mode in ('success', 'error', 'cancel', 'resistant_success', 'resistant_error'):
            with self.subTest(mode=mode):
                await self.competing_observers(mode, active_waiter=False)


if __name__ == '__main__':
    unittest.main()
