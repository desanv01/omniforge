"""Controlled harmless threads; every gate released and thread physically joined."""
import asyncio
import threading
import unittest
import test_receiver_adaptation_lifecycle as support

class ThreadProof(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(support.LifecycleProof.setUpClass.__func__)
    setUp=support.LifecycleProof.setUp
    assert_native_import_identity=support.LifecycleProof.assert_native_import_identity
    assert_safe_rpc_error=support.LifecycleProof.assert_safe_rpc_error
    parent=support.LifecycleProof.parent
    # Only thread-specific cases are collected here; shared fixtures, not old tests.
    __unittest_skip__=False
    async def test_08_queue_blocked_feeder_retained_then_late_join(self):
        gate=threading.Event();entered=threading.Event()
        class Queue(support.Queue):
            def join_thread(inner): entered.set();gate.wait();super().join_thread()
        queue=Queue();owner=self.child.LifecycleQueue(queue);owner.put('worker')
        try:
            self.assertFalse(await owner.settle(self.child.time.monotonic()+.02))
            operation=owner.close_operation
            self.assertFalse(operation.settled)
            self.assertFalse(await owner.settle(self.child.time.monotonic()+.01))
            self.assertIs(owner.close_operation,operation)
            self.assertEqual(queue.closed,1)
            gate.set();self.assertTrue(await owner.settle(self.child.time.monotonic()+1))
            self.assertEqual(queue.joined,1)
        finally:
            gate.set()
            if owner.close_operation: owner.close_operation.thread.join(1)

    async def test_09_cancelled_wait_is_not_physical_thread_join(self):
        gate=threading.Event();record=[]
        op=self.child.LifecycleThread(lambda:(gate.wait(),record.append('finished')))
        operations=[op];op.start()
        waiter=asyncio.create_task(op.join(self.child.time.monotonic()+1))
        try:
            await asyncio.sleep(0);waiter.cancel()
            with self.assertRaises(asyncio.CancelledError): await waiter
            self.assertFalse(op.settled);self.assertEqual(record,[])
            gate.set();self.assertTrue(await op.join(self.child.time.monotonic()+1))
            self.assertEqual(record,['finished']);self.assertIs(operations[0],op)
        finally: gate.set();op.thread.join(1)

    async def test_10_prepared_request_cleanup_physical_order(self):
        owner=self.parent();owner.worker_id='worker';order=[]
        class Prepared:
            settlement_snapshot={'cleanup_complete':True,'request_active':False}
            def close(inner): order.append('close')
        prepared=Prepared()
        class Workers:
            def prepare_pause_client(inner,*,owner_capture):
                order.append('capture');owner_capture(prepared);return prepared
            def pause_prepared(inner,worker,client):
                self.assertIs(client,prepared);order.append('request');return object()
        owner._client=support.support.Value(workers=Workers())
        try:
            self.assertTrue(await owner._pause_owned(self.child.time.monotonic()+1))
            self.assertEqual(order,['capture','request','close'])
            self.assertTrue(all(op.settled for op in owner.operations))
        finally:
            for op in owner.operations: op.thread.join(1)

    async def test_11_prepare_timeout_forbids_request_and_cleanup(self):
        gate=threading.Event();order=[];owner=self.parent();owner.worker_id='worker'
        class Prepared:
            def close(inner): order.append('close')
        class Workers:
            def prepare_pause_client(inner,*,owner_capture):
                owner_capture(Prepared());gate.wait();return owner.prepared
            def pause_prepared(inner,*a): order.append('request')
        owner._client=support.support.Value(workers=Workers())
        try:
            self.assertFalse(await owner._pause_owned(self.child.time.monotonic()+.02))
            self.assertEqual(order,[]);self.assertIsNotNone(owner.prepared)
            self.assertFalse(owner.operations[0].settled)
        finally:
            gate.set()
            for op in owner.operations: op.thread.join(1)

    async def test_12_parent_consumes_actual_rest2_prepared_methods(self):
        import test_receiver_rest_adaptation as rest_support
        harness=rest_support.RestProof(methodName='test_01_pause_generated_path_and_identity')
        rest_support.RestProof.setUpClass()
        harness.setUp()
        owner=self.parent();owner.worker_id='worker'
        owner._client=support.support.Value(workers=harness.workers.WorkersClient(harness.config))
        try:
            self.assertTrue(await owner._pause_owned(self.child.time.monotonic()+2))
            self.assertTrue(owner.prepared.settlement_snapshot['cleanup_complete'])
            self.assertEqual(len(harness.managers[0].calls),1)
            self.assertEqual(harness.managers[0].clear_calls,1)
            self.assertTrue(all(op.settled for op in owner.operations))
        finally:
            for op in owner.operations: op.thread.join(1)
            harness.doCleanups()
            rest_support.RestProof.tearDownClass()

    async def test_13_queue_failure_and_other_process_owner_remain_independent(self):
        class Bad(support.Queue):
            def join_thread(inner): raise RuntimeError('PRIVATE_VENDOR')
        first=self.child.LifecycleQueue(Bad());second=self.child.LifecycleQueue(support.Queue())
        try:
            deadline=self.child.time.monotonic()+1
            self.assertFalse(await first.settle(deadline))
            self.assertTrue(await second.settle(deadline))
            self.assertIsNot(first.close_operation,second.close_operation)
            self.assertTrue(first.close_operation.failed)
            self.assertFalse(await first.settle(deadline))
        finally:
            for owner in (first,second):
                if owner.close_operation: owner.close_operation.thread.join(1)

    async def test_14_request_error_physically_joins_then_cleans_once(self):
        owner=self.parent();owner.worker_id='worker';order=[]
        class Prepared:
            settlement_snapshot={'cleanup_complete':True,'request_active':False}
            def close(inner): order.append('close')
        prepared=Prepared()
        class Workers:
            def prepare_pause_client(inner,*,owner_capture): owner_capture(prepared);return prepared
            def pause_prepared(inner,*a): order.append('request');raise RuntimeError('PRIVATE')
        owner._client=support.support.Value(workers=Workers())
        try:
            self.assertFalse(await owner._pause_owned(self.child.time.monotonic()+1))
            self.assertTrue(owner.pause_uncertain)
            self.assertEqual(order,['request','close'])
            self.assertTrue(all(op.settled for op in owner.operations))
        finally:
            for op in owner.operations: op.thread.join(1)

    async def test_15_cleanup_hang_retains_exact_client_and_operation(self):
        gate=threading.Event();owner=self.parent();owner.worker_id='worker'
        class Prepared:
            settlement_snapshot={'cleanup_complete':False,'request_active':False}
            def close(inner): gate.wait()
        prepared=Prepared()
        class Workers:
            def prepare_pause_client(inner,*,owner_capture): owner_capture(prepared);return prepared
            def pause_prepared(inner,*a): return object()
        owner._client=support.support.Value(workers=Workers())
        try:
            self.assertFalse(await owner._pause_owned(self.child.time.monotonic()+.04))
            self.assertIs(owner.prepared,prepared)
            self.assertEqual(len(owner.operations),3)
            self.assertFalse(owner.operations[-1].settled)
            self.assertFalse(prepared.settlement_snapshot['cleanup_complete'])
        finally:
            gate.set()
            for op in owner.operations: op.thread.join(1)

if __name__=='__main__': unittest.main()
