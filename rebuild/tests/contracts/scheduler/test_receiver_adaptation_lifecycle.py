"""Actual lifecycle derivative under fake SDK/process/socket/Queue boundaries."""
import ast
import asyncio
import json
from pathlib import Path
from queue import Empty
import sys
import types
import unittest
from unittest.mock import patch
import test_receiver_adaptation_events as events
import test_receiver_adaptation_rpc as support


class Endpoint:
    def __init__(self): self.records=[];self.incoming=[];self.closed=False;self.failure=None
    def setblocking(self,value): self.blocking=value
    def send(self,raw):
        if self.failure: raise self.failure
        self.records.append(raw);return len(raw)
    def recvmsg(self,*a):
        if not self.incoming: raise BlockingIOError()
        return self.incoming.pop(0)
    def close(self): self.closed=True

class Queue:
    def __init__(self): self.items=[];self.closed=0;self.joined=0
    def put(self,value): self.items.append(value)
    def get_nowait(self):
        if not self.items: raise Empty()
        return self.items.pop(0)
    def close(self): self.closed+=1
    def join_thread(self): self.joined+=1
    def cancel_join_thread(self): raise AssertionError('Forbidden abandonment')

class Scope:
    def __init__(self): self.unresolved=[];self.unresolved_tasks=();self.entered=0;self.closed=0
    def __enter__(self): self.entered+=1;return self
    def _leave(self): self.entered-=1
    async def aclose(self): self.closed+=1


class LifecycleProof(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(support.RpcProof.setUpClass.__func__)
    assert_native_import_identity=events.EventProof.assert_native_import_identity
    assert_safe_rpc_error=support.RpcProof.assert_safe_rpc_error
    def setUp(self):
        events.EventProof.setUp(self)
        modules={}
        def module(name):
            if name in sys.modules and name.startswith('hatchet_sdk'): return sys.modules[name]
            if name not in modules:
                m=support.FakeModule(name);m.__path__=[];modules[name]=m
                if '.' in name:
                    parent,child=name.rsplit('.',1);setattr(module(parent),child,m)
            return modules[name]
        path=self.output/'hatchet_sdk/worker/worker.py'
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node,ast.ImportFrom) and node.module.startswith('hatchet_sdk'): module(node.module)
        modules['hatchet_sdk.worker.action_listener_process']=self.child
        guard=patch.dict(sys.modules,modules);guard.start();self.addCleanup(guard.stop)
        self.worker=support.load('lifecycle_worker',path)
        self.worker.socket=types.SimpleNamespace(AF_UNIX=1,SOCK_DGRAM=2,
            socketpair=lambda *a:(Endpoint(),Endpoint()))
        self.config=support.Value(disable_log_capture=True,debug=False,
            healthcheck=support.Value(enabled=False),otel=support.Value(include_task_name_in_start_step_run_span_name=False,individual_run_spans_for_bulk_run=False),embedded=None)
        self.scopes=[]
        self.child.ReceiverResources=Scope
        self.constructed=[]
        def client(**kw): self.constructed.append(kw);return support.Value()
        self.worker.Client=self.child.Client=client

    def parent(self,**changes):
        ctx=support.Value(Queue=Queue,Event=lambda:support.Value(set=lambda:None,is_set=lambda:False))
        self.worker.multiprocessing=types.SimpleNamespace(get_context=lambda mode:ctx)
        values=dict(name='empty',config=self.config,slot_config={'default':1},handle_kill=False,
            receiver_lifecycle_only=True,receiver_resources=Scope(),receiver_capture=lambda owner:self.scopes.append(owner))
        values.update(changes)
        return self.worker.Worker(**values)

    async def test_01_closed_mode_rejects_before_effects(self):
        for changes in ({'receiver_lifecycle_only':False},{'workflows':[object()]},
                        {'lifespan':lambda:None},{'debug':True},{'slot_config':{'durable':1}},
                        {'handle_kill':True},{'slot_config':{'default':True}},{'slot_config':{'default':1.0}}):
            with self.assertRaises(self.child.LifecycleError): self.parent(**changes)
        self.assertEqual(self.scopes,[]);self.assertEqual(self.constructed,[])
        owner=self.parent()
        self.assertEqual(len(owner.queues),3)
        with self.assertRaises(self.child.LifecycleError): owner.register_workflow(object())
        self.assertEqual(self.constructed,[])

    async def test_02_status_four_records_strict_and_abnormal_exit(self):
        endpoint=Endpoint();writer=self.child.LifecycleStatus(endpoint)
        self.assertFalse(endpoint.blocking)
        writer.send('starting','ok');writer.send('ready','ok')
        writer.send('terminal','stopped',stopped=True)
        writer.send('final','stopped',stopped=True,clean=True,settled=True)
        self.assertFalse(writer.send('final','stopped'))
        self.assertEqual(len(endpoint.records),4)
        self.assertLessEqual(sum(map(len,endpoint.records)),2048)
        receiver=Endpoint();receiver.incoming=[(raw,[],0,None) for raw in endpoint.records]
        reader=self.child.LifecycleStatus(receiver);reader.poll()
        process=support.Value(is_alive=lambda:False,exitcode=0)
        self.assertTrue(reader.outcome(process,True)['clean'])
        process.exitcode=9
        self.assertFalse(reader.outcome(process,True)['clean'])
        self.assertTrue(reader.outcome(process,True)['abnormal_exit'])

    async def test_03_status_loss_truncation_unknown_contradiction(self):
        endpoint=Endpoint();endpoint.failure=BlockingIOError()
        writer=self.child.LifecycleStatus(endpoint)
        self.assertFalse(writer.send('starting','ok'));self.assertTrue(writer.loss)
        record=[1,1,'starting','ok',False,False,0,0,0,False,False,False]
        for flag in (self.child.socket.MSG_TRUNC,self.child.socket.MSG_CTRUNC):
            endpoint=Endpoint();endpoint.incoming=[(json.dumps(record).encode(),[],flag,None)]
            reader=self.child.LifecycleStatus(endpoint);reader.poll();self.assertTrue(reader.loss)
        for mutation in ({6:65536},{6:True},{3:'count_unknown',9:True},{2:'final',11:True}):
            invalid=list(record)
            for key,value in mutation.items(): invalid[key]=value
            with self.assertRaises(self.child.LifecycleError): self.child.LifecycleStatus.validate(invalid,0,None)

    async def test_04_missing_status_exit_zero_incomplete(self):
        reader=self.child.LifecycleStatus(Endpoint())
        result=reader.outcome(support.Value(is_alive=lambda:False,exitcode=0),True)
        self.assertTrue(result['physical_exit']);self.assertFalse(result['clean'])

    async def test_05_listener_awaited_unsubscribe_once(self):
        calls=[]
        async def unsubscribe(*a,**kw): calls.append(kw);return object()
        stub=types.SimpleNamespace(Unsubscribe=unsubscribe)
        self.stub=stub
        config=support.Value(token='SYNTHETIC',listener_v2_timeout=1)
        self.listener.DispatcherStub=lambda conn:stub
        listener=self.listener.ActionListener(config,'worker')
        listener.heartbeat_task=asyncio.create_task(asyncio.sleep(0))
        deadline=self.child.time.monotonic()+1
        self.assertTrue(await listener.aclose(deadline))
        self.assertTrue(await listener.aclose(deadline))
        listener.cleanup()
        with self.assertRaises(self.listener.ReceiverListenerError): listener.unregister()
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['timeout'],5)

    async def test_06_partial_constructor_retained_owner(self):
        made=[]
        def queue():
            if made: raise RuntimeError('fake allocation failure')
            value=Queue();made.append(value);return value
        ctx=support.Value(Queue=queue,Event=lambda:None)
        self.worker.multiprocessing=types.SimpleNamespace(get_context=lambda mode:ctx)
        scope=Scope();captured=[]
        with self.assertRaises(RuntimeError):
            self.worker.Worker('empty',self.config,{'default':1},handle_kill=False,
                receiver_lifecycle_only=True,receiver_resources=scope,receiver_capture=captured.append)
        self.assertEqual(len(captured),1);owner=captured[0]
        self.assertTrue(owner.queue_allocation_unknown)
        self.assertEqual(owner.queues[0].queue,made[0])
        self.assertTrue(await owner.queues[0].settle(self.child.time.monotonic()+1))
        self.assertEqual((made[0].closed,made[0].joined),(1,1))

    async def test_07_child_rejects_any_action_without_callback_or_queues(self):
        child=self.child
        class Listener:
            worker_id='worker'
            async def __aiter__(inner): yield object()
            async def aclose(inner,deadline): return True
        class Dispatcher:
            def __init__(inner,config): pass
            async def get_action_listener(inner,*a): return Listener()
        child.DispatcherClient=Dispatcher
        queues=[Queue() for _ in range(3)];queues[1].put(self.stop)
        endpoint=Endpoint();captured=[];scope=Scope()
        state=await child.receiver_child_lifecycle(self.config,'empty',{'default':1},
            *queues,support.Value(is_set=lambda:False),endpoint,resources=scope,capture=captured.append)
        self.assertIs(captured[0],state)
        self.assertEqual(state['reason'],'unsupported_action')
        self.assertEqual(queues[0].items,[])
        self.assertEqual(scope.entered,0)
        self.assertFalse(json.loads(endpoint.records[-1])[11])
        for queue in queues: self.assertEqual((queue.closed,queue.joined),(1,1))

    async def test_08_child_normal_stop_physically_settles_queues_and_scope(self):
        class Listener:
            worker_id='worker'
            async def __aiter__(inner):
                await asyncio.Event().wait()
                yield None
            async def aclose(inner,deadline): return True
        class Dispatcher:
            def __init__(inner,config): pass
            async def get_action_listener(inner,*a): return Listener()
        self.child.DispatcherClient=Dispatcher
        queues=[Queue() for _ in range(3)];queues[1].put(self.stop)
        endpoint=Endpoint();scope=Scope()
        state=await self.child.receiver_child_lifecycle(self.config,'empty',{'default':1},
            *queues,support.Value(is_set=lambda:True),endpoint,resources=scope,capture=lambda state:None)
        self.assertTrue(state['settled'])
        final=json.loads(endpoint.records[-1]);self.assertTrue(final[11]);self.assertEqual(final[6:9],[0,0,0])
        self.assertEqual(scope.closed,1);self.assertEqual(scope.entered,0)
        self.assertTrue(endpoint.closed)

    async def test_09_actual_parent_start_shutdown_with_fake_process(self):
        owner=self.parent();endpoint,child_endpoint=Endpoint(),Endpoint()
        writer=self.child.LifecycleStatus(child_endpoint)
        writer.send('starting','ok');writer.send('ready','ok')
        writer.send('final','stopped',stopped=True,clean=True,settled=True)
        endpoint.incoming=[(raw,[],0,None) for raw in child_endpoint.records]
        class Process:
            exitcode=0
            joined=0
            def start(inner): pass
            def is_alive(inner): return False
            def join(inner,timeout): self.assertEqual(timeout,0);inner.joined+=1
        process=Process();owner.ctx.Process=lambda **kw:process
        self.worker.socket=types.SimpleNamespace(AF_UNIX=1,SOCK_DGRAM=2,
            socketpair=lambda *a:(endpoint,child_endpoint))
        async def version(): return '1.0.0'
        self.worker.Client=lambda **kw:support.Value(dispatcher=support.Value(get_version=version))
        self.worker.semver_less_than=lambda *a:False
        result=await owner._aio_start()
        self.assertTrue(result['clean'])
        self.assertEqual(process.joined,1)
        self.assertTrue(all(q.queue.closed==1 and q.queue.joined==1 for q in owner.queues))
        self.assertEqual(owner.resources.closed,1)
        self.assertTrue(endpoint.closed and child_endpoint.closed)

    async def test_10_legacy_version_never_enters_runner_or_lifespan(self):
        owner=self.parent()
        async def version(): return None
        self.worker.Client=lambda **kw:support.Value(dispatcher=support.Value(get_version=version))
        with self.assertRaises(self.child.LifecycleError): await owner._aio_start()
        self.assertIsNone(owner.process)
        self.assertEqual(owner.resources.closed,1)

    async def test_11_resistant_heartbeat_retained_prevents_unsubscribe(self):
        release,entered=asyncio.Event(),asyncio.Event();calls=[]
        async def resistant():
            entered.set()
            while not release.is_set():
                try: await release.wait()
                except asyncio.CancelledError: pass
        async def unsubscribe(*a,**kw): calls.append(True)
        stub=types.SimpleNamespace(Unsubscribe=unsubscribe)
        self.listener.DispatcherStub=lambda conn:stub
        listener=self.listener.ActionListener(support.Value(token='fake',listener_v2_timeout=1),'worker')
        listener.heartbeat_task=asyncio.create_task(resistant())
        try:
            await entered.wait()
            with self.assertRaises(self.listener.ReceiverListenerError): await listener.aclose(self.child.time.monotonic()+.02)
            self.assertIn(listener.heartbeat_task,listener._close_owned_tasks)
            self.assertFalse(listener.heartbeat_task.done());self.assertEqual(calls,[])
        finally:
            release.set();await asyncio.gather(listener.heartbeat_task,return_exceptions=True)
            await asyncio.gather(listener._lifecycle_close_task,return_exceptions=True)

    async def test_12_partial_client_failure_safe_and_no_runner_effect(self):
        owner=self.parent()
        def fail(**kw): raise RuntimeError('PRIVATE_CLIENT_BODY')
        self.worker.Client=fail
        with self.assertRaises(self.child.LifecycleError) as caught: await owner._aio_start()
        self.assertEqual(str(caught.exception),'lifecycle_start_failed')
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(owner.endpoint.closed and owner.child_endpoint.closed)
        self.assertEqual(owner.resources.closed,1)

    async def test_13_runner_guard_precedes_client_and_sender(self):
        path=self.output/'hatchet_sdk/worker/runner/run_loop_manager.py'
        # Imports are isolated fakes; class body is the actual selected derivative.
        modules={}
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node,ast.ImportFrom) and node.module.startswith('hatchet_sdk'):
                if node.module not in sys.modules:
                    modules[node.module]=support.FakeModule(node.module)
        with patch.dict(sys.modules,modules):
            runner=support.load('lifecycle_runner_guard',path)
        with self.assertRaisesRegex(RuntimeError,'unsupported_lifecycle_runner'):
            runner.WorkerActionRunLoopManager('empty',{},1,0,None,None,None,self.config,False,False,[],None)
        self.assertEqual(self.constructed,[])

    async def test_14_repeated_shutdown_shares_exact_sweep(self):
        owner=self.parent()
        await owner.exit_gracefully()
        sweep=owner.shutdown_task;deadline=owner._shutdown_deadline
        first_counts=[(q.queue.closed,q.queue.joined) for q in owner.queues]
        await owner.exit_gracefully()
        self.assertIs(owner.shutdown_task,sweep)
        self.assertEqual(owner._shutdown_deadline,deadline)
        self.assertEqual(first_counts,[(q.queue.closed,q.queue.joined) for q in owner.queues])
        self.assertEqual(owner.resources.closed,1)

    async def test_15_real_scope_retains_channel_after_partial_client_failure(self):
        connection=support.load('lifecycle_real_scope',self.output/'hatchet_sdk/connection.py')
        closed=[]
        class Channel:
            def close(inner): closed.append(True)
        scope=connection.ReceiverResources(sync_constructor=lambda **kw:Channel())
        owner=self.parent(receiver_resources=scope)
        self.config.host_port='127.0.0.1:7077'
        self.config.server_url='http://127.0.0.1:8888'
        self.config.tls_config=support.Value(strategy='none')
        def fail(**kw):
            connection.new_conn(self.config,False)
            raise RuntimeError('PRIVATE_PARTIAL_CLIENT')
        self.worker.Client=fail
        with self.assertRaises(self.child.LifecycleError): await owner._aio_start()
        self.assertEqual(closed,[True])
        self.assertEqual(scope.unresolved,[])
        with self.assertRaises(connection.ReceiverScopeError): connection.new_conn(self.config,False)

    async def test_16_peer_id_drained_before_parent_consumer_closes(self):
        owner=self.parent();owner.endpoint=Endpoint();owner.status=self.child.LifecycleStatus(owner.endpoint)
        queue=owner.queues[2].queue
        class Process:
            exitcode=0
            joined=False
            def is_alive(inner):
                if not inner.joined: self.assertEqual(queue.closed,0)
                return bool(queue.items)
            def join(inner,timeout): inner.joined=True
        queue.items=['worker']
        owner.process=Process()
        owner.process_start_attempted=owner.process_start_confirmed=True
        await owner.exit_gracefully()
        self.assertEqual(owner.worker_id,'worker')
        self.assertTrue(owner.process.joined)
        self.assertEqual(queue.closed,1)
        self.assertFalse(owner.result['clean']) # no final status, even exit0

    async def test_17_unsubscribe_failure_safe_no_chain(self):
        async def fail(*a,**kw): raise RuntimeError('PRIVATE_UNSUBSCRIBE')
        self.listener.DispatcherStub=lambda conn:support.Value(Unsubscribe=fail)
        listener=self.listener.ActionListener(support.Value(token='fake',listener_v2_timeout=1),'worker')
        with self.assertRaises(self.listener.ReceiverListenerError) as caught:
            await listener.aclose(self.child.time.monotonic()+1)
        self.assertEqual(str(caught.exception),'unsubscribe_failed')
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(caught.exception.__cause__)

    async def test_18_parent_stop_budget_not_reset_and_no_executor_in_lifecycle(self):
        owner=self.parent()
        owner._shutdown_deadline=self.child.time.monotonic()+.01
        # The AST verifies selected lifecycle branch has no executor or Runner call.
        for path,names in ((self.output/'hatchet_sdk/worker/worker.py',{'_aio_start','_shutdown','_pause_owned'}),):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            selected=[node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names]
            for node in selected:
                text=ast.unparse(node)
                for forbidden in ('to_thread','run_in_executor','legacy_aio_start','ThreadPoolExecutor','_setup_lifespan','_run_action_runner'):
                    self.assertNotIn(forbidden,text)

    async def test_19_process_start_failure_variants_keep_independent_cleanup(self):
        for mode in ('factory','before','after','observe','join'):
            with self.subTest(mode=mode):
                owner=self.parent();endpoint,child_endpoint=Endpoint(),Endpoint()
                self.worker.socket.socketpair=lambda *a:(endpoint,child_endpoint)
                calls=[]
                class Process:
                    pid=None if mode=='before' else 123
                    exitcode=0
                    def start(inner):
                        calls.append('start')
                        if mode in ('before','after'): raise RuntimeError('PRIVATE_START')
                    def is_alive(inner):
                        if mode=='observe': raise RuntimeError('PRIVATE_OBSERVE')
                        return False
                    def join(inner,timeout):
                        calls.append('join')
                        if mode=='join': raise RuntimeError('PRIVATE_JOIN')
                process=Process()
                def factory(**kw):
                    if mode=='factory': raise RuntimeError('PRIVATE_FACTORY')
                    return process
                owner.ctx.Process=factory
                async def version(): return 'modern'
                self.worker.Client=lambda **kw:support.Value(dispatcher=support.Value(get_version=version))
                self.worker.semver_less_than=lambda *a:False
                if mode in ('factory','before','after','observe'):
                    with self.assertRaises(self.child.LifecycleError) as caught: await owner._aio_start()
                    self.assertEqual(str(caught.exception),'lifecycle_start_failed')
                    self.assertIsNone(caught.exception.__context__)
                    self.assertIsNone(caught.exception.__cause__)
                else: await owner._aio_start()
                self.assertFalse(owner.result['clean'])
                self.assertTrue(endpoint.closed and child_endpoint.closed)
                self.assertTrue(all(q.queue.closed==1 and q.queue.joined==1 for q in owner.queues))
                if mode in ('factory','before','observe'): self.assertNotIn('join',calls)
                if mode in ('before','after'): self.assertTrue(owner.process_start_ambiguous)
                if mode in ('before','observe','join'):
                    self.assertEqual(owner.resources.closed,0)
                    self.assertIs(owner.process,process)
                else: self.assertEqual(owner.resources.closed,1)
                self.assertNotIn('PRIVATE',str(owner.result))

    async def test_20_stop_put_and_peer_read_failures_do_not_abort_sweep(self):
        for mode in ('stop','peer'):
            with self.subTest(mode=mode):
                owner=self.parent();owner.endpoint=Endpoint();owner.child_endpoint=Endpoint()
                owner.process_start_attempted=owner.process_start_confirmed=True
                owner.process=support.Value(pid=123,is_alive=lambda:False,join=lambda **kw:None,exitcode=0)
                if mode=='stop':
                    def fail(value): raise RuntimeError('PRIVATE_STOP')
                    owner.queues[1].queue.put=fail
                else:
                    def fail(): raise RuntimeError('PRIVATE_PEER')
                    owner.queues[2].queue.get_nowait=fail
                result=await owner.exit_gracefully()
                self.assertFalse(result['clean'])
                self.assertIn('stop_put_uncertain' if mode=='stop' else 'peer_read_failed',result['cleanup_failures'])
                self.assertTrue(all(q.queue.closed==1 and q.queue.joined==1 for q in owner.queues))
                self.assertEqual(owner.resources.closed,1)
                self.assertTrue(owner.endpoint.closed and owner.child_endpoint.closed)
                self.assertNotIn('PRIVATE',str(result))

    async def test_21_actual_child_rejects_sendable_event_before_send_task(self):
        calls=[]
        class Listener:
            worker_id='worker'
            async def __aiter__(inner):
                await asyncio.Event().wait();yield None
            async def aclose(inner,deadline): return True
        class Dispatcher:
            def __init__(inner,config): pass
            async def get_action_listener(inner,*a): return Listener()
            async def send_step_action_event(inner,*a): calls.append('forbidden');return object()
        self.child.DispatcherClient=Dispatcher
        action=support.Value(action_type='normal',worker_id='worker',job_id='job',step_run_id='run')
        event=self.child.ActionEvent(action,'completed','PRIVATE_PAYLOAD',True)
        queues=[Queue() for _ in range(3)];queues[1].put(event);queues[1].put(self.stop)
        endpoint=Endpoint();scope=Scope()
        state=await self.child.receiver_child_lifecycle(self.config,'empty',{'default':1},
            *queues,support.Value(is_set=lambda:False),endpoint,resources=scope,capture=lambda state:None)
        process=state['process']
        self.assertIs(process.unsent_lifecycle_event,event)
        self.assertEqual(process.terminal_delivery['classification'],'event_not_sent')
        self.assertEqual(process._event_sequence,0)
        self.assertEqual(process.step_action_events,set())
        self.assertEqual(process.unresolved_sends,{})
        self.assertEqual(calls,[])
        self.assertEqual(state['reason'],'event_uncertain')
        self.assertFalse(json.loads(endpoint.records[-1])[11])
        self.assertEqual(scope.closed,1)

if __name__=='__main__': unittest.main()
