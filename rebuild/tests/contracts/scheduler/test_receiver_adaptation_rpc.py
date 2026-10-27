"""Offline actual derivative methods; fake module graph, no SDK/native imports."""
import ast
import asyncio
import importlib.util
import json
import shutil
from pathlib import Path
import sys
import sysconfig
import tempfile
import traceback
import types
import unittest
from unittest.mock import patch

ARTIFACT=Path(__file__).resolve().parents[3]/"infra/scheduler/receiver-adaptation"

class ValueType(type):
    def __getattr__(cls,name): return cls

class Value(metaclass=ValueType):
    def __init__(self,*args,**kwargs): self.__dict__.update(kwargs)
    @classmethod
    def __class_getitem__(cls,item): return cls
    @classmethod
    def model_validate(cls,value): return cls(**value)
    @classmethod
    def model_validate_json(cls,value): return cls(**json.loads(value))

class FakeModule(types.ModuleType):
    def __getattr__(self,name):
        if name.startswith("__"): raise AttributeError(name)
        return Value

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

class RpcProof(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=load("rpc_applicator",ARTIFACT/"apply_patch.py")
        cls.scratch=Path(tempfile.mkdtemp(prefix="receiver-rpc-"))
        cls.source=cls.scratch/"upstream";cls.source.mkdir()
        installed=Path(sysconfig.get_paths()["purelib"])
        for name in cls.app.FILES:
            target=cls.source/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((installed/name).read_bytes())
        meta=cls.source/"hatchet_sdk-1.41.1.dist-info/METADATA"
        meta.parent.mkdir();meta.write_bytes((installed/meta.relative_to(cls.source)).read_bytes())
        cls.output=cls.scratch/"output";cls.app.apply(cls.source,cls.output)

    def setUp(self):
        modules={}
        def module(name):
            if name not in modules:
                m=FakeModule(name);m.__path__=[];modules[name]=m
                if "." in name:
                    parent,child=name.rsplit(".",1);setattr(module(parent),child,m)
            return modules[name]
        for file in self.app.FILES[2:5]:
            for node in ast.walk(ast.parse((self.output/file).read_text())):
                if isinstance(node,ast.ImportFrom) and node.module.startswith(("hatchet_sdk","google","grpc","pydantic")):
                    module(node.module)
        grpc=module("grpc");aio=module("grpc.aio")
        class RpcError(Exception):
            def __init__(inner,code="UNAVAILABLE"):
                super().__init__('PRIVATE_DETAIL PRIVATE_TOKEN '+code)
                inner.status=code
            def code(inner): return inner.status
            def details(inner): return 'PRIVATE_DETAIL PRIVATE_TOKEN'
        grpc.RpcError=RpcError;aio.AioRpcError=RpcError
        grpc.StatusCode=types.SimpleNamespace(UNIMPLEMENTED="UNIMPLEMENTED",UNAVAILABLE="UNAVAILABLE")
        tenacity=module("tenacity")
        tenacity.retry=lambda **kw:lambda f:f
        for name in ("wait_exponential_jitter","stop_after_attempt","retry_if_exception"):
            setattr(tenacity,name,lambda *a,**k:None)
        pydantic=module("pydantic");pydantic.BaseModel=Value;pydantic.ConfigDict=dict
        pydantic.field_validator=lambda *a,**kw:lambda f:f
        self.logs=[]
        module("hatchet_sdk.logger").logger=types.SimpleNamespace(**{k:lambda *a,**kw:self.logs.append(a) for k in ("debug","info","warning","warn","error","exception")})
        module("hatchet_sdk.logger").logger.exception=lambda *a,**kw:self.logs.append((a,traceback.format_exc()))
        module("hatchet_sdk.utils.api_auth").create_authorization_header=lambda token:(("authorization","bearer "+token),)
        module("hatchet_sdk.utils.proto_enums").convert_proto_enum_to_python=lambda value,*a:value
        module("hatchet_sdk.runnables.action").ActionType=types.SimpleNamespace(START_BATCH="batch")
        class Payload(Value):
            @classmethod
            def model_validate_json(cls,value):
                parsed=json.loads(value)
                if not isinstance(parsed,dict) or 'schema_invalid' in parsed:
                    raise ValueError('PRIVATE_VALIDATION '+value)
                return cls(**parsed)
        module("hatchet_sdk.runnables.action").ActionPayload=Payload
        self.actions=[]
        proof=self
        class RecordedAction(Value):
            def __init__(inner,**kwargs):
                super().__init__(**kwargs);proof.actions.append(inner)
        module("hatchet_sdk.runnables.action").Action=RecordedAction
        self.channels=[];self.stub=None
        def new_conn(*a): self.channels.append(a);return object()
        module("hatchet_sdk.connection").new_conn=new_conn
        module("hatchet_sdk.contracts.dispatcher_pb2_grpc").DispatcherStub=lambda channel:self.stub
        module("hatchet_sdk.clients.event_ts").ThreadSafeEvent=asyncio.Event
        class EOF: pass
        self.EOF=EOF
        module("hatchet_sdk.clients.event_ts").UnexpectedEOF=EOF
        async def read(stream,interrupt):
            try: return await stream.read()
            finally: interrupt.set()
        module("hatchet_sdk.clients.event_ts").read_with_interrupt=read
        guard=patch.dict(sys.modules,modules);guard.start();self.addCleanup(guard.stop)
        self.listener=load("hatchet_sdk.clients.dispatcher.action_listener",self.output/"hatchet_sdk/clients/dispatcher/action_listener.py")
        self.dispatcher=load("rpc_dispatcher",self.output/"hatchet_sdk/clients/dispatcher/dispatcher.py")
        self.admin=load("rpc_admin",self.output/"hatchet_sdk/clients/admin.py")
        self.config=Value(token="PRIVATE_TOKEN",namespace="of_",listener_v2_timeout=60,worker_preset_labels={})
        self.RpcError=RpcError
        self.calls=[]

    def assigned_action(self,payload='{}'):
        fields={key:None for key in ('tenant_id','workflow_run_id','job_id','job_name','job_run_id','task_id','task_run_external_id','action_id','task_name','child_workflow_index','child_workflow_key','parent_workflow_run_id','priority','workflow_version_id','workflow_id','durable_task_invocation_count','triggering_event_external_id','triggering_event_key','batchStartPayload','batchKey')}
        assigned=Value(**fields,action_type='normal',action_payload=payload,retry_count=0,additional_metadata='{}')
        assigned.HasField=lambda name:False
        return assigned

    def assert_safe_rpc_error(self,error,code):
        self.assertEqual(str(error),code)
        self.assertIsNone(error.__context__)
        self.assertIsNone(error.__cause__)
        serialized=json.dumps({'type':type(error).__name__,'message':str(error)})
        self.assertNotIn('PRIVATE',serialized+repr(error)+''.join(traceback.format_exception(error))+str(self.logs))

    def make_listener(self,stream=None):
        proof=self
        class Stub:
            def ListenV2(inner,*args,**kw): proof.calls.append(("listen",kw));return stream
            async def Heartbeat(inner,*args,**kw): proof.calls.append(("heartbeat",kw))
            def Unsubscribe(inner,*args,**kw): proof.calls.append(("unsubscribe",kw));return Value()
        self.stub=Stub()
        listener=self.listener.ActionListener(self.config,"worker")
        async def no_heartbeat(): pass
        listener.start_heartbeater=no_heartbeat
        return listener

    async def test_01_unary_deadlines_single_attempt_and_compatibility(self):
        proof=self
        class Stub:
            async def GetVersion(inner,*a,**kw):
                proof.calls.append(("version",kw))
                if proof.error: raise proof.error
                return Value(version="1.2.3")
            async def Register(inner,*a,**kw):
                proof.calls.append(("register",kw))
                if proof.error: raise proof.error
                return Value(worker_id="worker")
            def PutWorkflow(inner,*a,**kw):
                proof.calls.append(("put",kw))
                if proof.error: raise proof.error
                return proof.response
        self.stub=Stub();client=self.dispatcher.DispatcherClient(self.config);client.aio_client=self.stub
        admin=self.admin.AdminClient(self.config,None,None);admin.client=self.stub
        self.response=object();self.error=None
        self.assertEqual(await client.get_version(),"1.2.3")
        self.assertIs(admin.put_workflow(Value()),self.response)
        await client.get_action_listener("worker",[],[],{},[])
        for code in ("UNAVAILABLE","UNIMPLEMENTED","AUTH","DEADLINE"):
            self.error=self.RpcError(code)
            if code=="UNIMPLEMENTED": self.assertIsNone(await client.get_version())
            else:
                with self.assertRaises(self.dispatcher.ReceiverRpcError) as caught: await client.get_version()
                self.assert_safe_rpc_error(caught.exception,'version_failed')
            with self.assertRaises(self.admin.ReceiverRpcError) as caught: admin.put_workflow(Value())
            self.assert_safe_rpc_error(caught.exception,'workflow_register_failed')
            with self.assertRaises(self.dispatcher.ReceiverRpcError) as caught: await client.get_action_listener("worker",[],[],{},[])
            self.assert_safe_rpc_error(caught.exception,'worker_register_failed')
        self.assertEqual(len(self.calls),15)
        self.assertTrue(all(kw["timeout"]==10 for _,kw in self.calls))
        self.assertTrue(all(kw["metadata"]==(("authorization","bearer PRIVATE_TOKEN"),) for _,kw in self.calls))
        self.assertEqual(len(self.channels),1) # only successful Register constructed listener

    async def test_02_invalid_lifetime_before_construction(self):
        for value in (None,True,0,-1,61,1.5):
            self.config.listener_v2_timeout=value
            with self.assertRaises(self.listener.ReceiverListenerError): self.make_listener()
        self.assertEqual(self.channels,[])

    async def test_03_one_acquisition_no_reset_after_elapsed_time(self):
        class Stream:
            def cancel(inner): pass
        listener=self.make_listener(Stream())
        first=await listener.get_listen_client()
        listener.last_connection_attempt=-1e20
        with self.assertRaises(self.listener.ReceiverListenerError): await listener.get_listen_client()
        self.assertIs(first,listener._stream)
        self.assertEqual(len(self.channels),1)
        self.assertEqual(self.calls[0][1]["timeout"],60)

    async def test_04_eof_rpc_and_malformed_are_terminal_safe(self):
        proof=self
        for result,expected in ((self.EOF(),'stream_eof'),(RuntimeError("PRIVATE_BODY"),'stream_failed'),(self.assigned_action("{PRIVATE_PAYLOAD"),'payload_invalid'),(self.assigned_action('{"schema_invalid":"PRIVATE_SCHEMA"}'),'payload_invalid')):
            class Stream:
                cancelled=0
                async def read(inner):
                    if isinstance(result,Exception): raise result
                    return result if isinstance(result,proof.EOF) else Value(data=result)
                def cancel(inner): inner.cancelled+=1
            stream=Stream();listener=self.make_listener(stream)
            with self.assertRaises(self.listener.ReceiverListenerError) as caught:
                await anext(listener.__aiter__())
            self.assertNotIn("PRIVATE",str(caught.exception))
            self.assertEqual(str(caught.exception),expected)
            self.assertEqual(self.actions,[])
            self.assertEqual(stream.cancelled,1)
            self.assertEqual(listener.unresolved_reads,())
            with self.assertRaises(self.listener.ReceiverListenerError): await listener.get_listen_client()
        self.assertNotIn("PRIVATE",str(self.logs))

    async def test_05_resistant_read_bounded_retained_then_joined(self):
        entered,release=asyncio.Event(),asyncio.Event()
        class Stream:
            cancelled=0
            async def read(inner):
                entered.set()
                while not release.is_set():
                    try: await release.wait()
                    except asyncio.CancelledError: pass
                return Value(data=None)
            def cancel(inner): inner.cancelled+=1
        stream=Stream();listener=self.make_listener(stream)
        iterator=listener.__aiter__();running=asyncio.create_task(anext(iterator))
        try:
            await entered.wait();listener.stop_stream()
            with self.assertRaises(self.listener.ReceiverListenerError): await asyncio.wait_for(running,1)
            self.assertEqual(stream.cancelled,1)
            self.assertEqual(len(listener.unresolved_reads),1)
            retained=listener.unresolved_reads[0]
            with self.assertRaises(self.listener.ReceiverListenerError): await listener.join_reads(.01)
            self.assertIs(listener.unresolved_reads[0],retained)
            release.set();self.assertTrue(await listener.join_reads(.5))
            self.assertEqual(listener.unresolved_reads,())
        finally:
            release.set()
            await asyncio.gather(running,*listener.unresolved_reads,return_exceptions=True)

    async def test_06_heartbeat_failure_and_unsubscribe_deadlines(self):
        listener=self.make_listener()
        async def fail(*a,**kw):
            self.calls.append(("heartbeat",kw));raise RuntimeError("PRIVATE_BODY")
        self.stub.Heartbeat=fail
        await listener.heartbeat()
        self.assertEqual(listener.terminal_code,"heartbeat_failed")
        self.assertFalse(listener.run_heartbeat)
        listener.unregister()
        self.assertEqual([kw["timeout"] for _,kw in self.calls],[5,5])
        self.assertEqual(self.logs,[])

    async def test_07_patch_five_outputs_and_stable_stage_a(self):
        hashes=self.app.apply(self.source,self.scratch/"second-output")
        self.assertEqual(len(hashes),8)
        self.assertEqual(hashes["hatchet_sdk/config.py"],"bbe5c491989020a316902d3aa9da18b425527714f341062090366d81c8fafbbe")
        self.assertEqual(hashes["hatchet_sdk/connection.py"],"92460665b88db933efc08f382c8aa30b7be7ed6e1b3b8da9af7a671f2d1be8f9")
        for index,name in enumerate(self.app.FILES[2:]):
            path=self.source/name;raw=path.read_bytes()
            try:
                path.write_bytes(raw+b"# drift\n")
                target=self.scratch/("drift-"+str(index))
                with self.assertRaises(ValueError): self.app.apply(self.source,target)
                self.assertFalse(target.exists())
            finally: path.write_bytes(raw)

    async def test_08_valid_mapping_then_generator_close(self):
        assigned=self.assigned_action()
        class Stream:
            cancelled=0
            async def read(inner): return Value(data=assigned)
            def cancel(inner): inner.cancelled+=1
        stream=Stream();listener=self.make_listener(stream);iterator=listener.__aiter__()
        action=await anext(iterator)
        self.assertEqual(action.action_type,'normal')
        self.assertEqual(action.worker_id,'worker')
        self.assertEqual(action.retry_count,0)
        await iterator.aclose()
        self.assertEqual(stream.cancelled,1)
        self.assertEqual(listener.unresolved_reads,())

    async def test_09_repeated_cancellation_retains_resistant_reader(self):
        entered,cancelled,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
        class Stream:
            async def read(inner):
                entered.set()
                while not release.is_set():
                    try: await release.wait()
                    except asyncio.CancelledError: cancelled.set()
                return Value()
            def cancel(inner): pass
        listener=self.make_listener(Stream());running=asyncio.create_task(anext(listener.__aiter__()))
        try:
            await entered.wait();running.cancel();await cancelled.wait();running.cancel()
            with self.assertRaises(asyncio.CancelledError): await running
            self.assertEqual(listener.terminal_code,'listener_cancelled')
            self.assertEqual(len(listener.unresolved_reads),1)
            with self.assertRaises(self.listener.ReceiverListenerError): await listener.join_reads(.01)
            release.set();await listener.join_reads(.5)
        finally:
            release.set();await asyncio.gather(running,*listener.unresolved_reads,return_exceptions=True)

    async def test_10_acquisition_failure_and_stop_before_read(self):
        listener=self.make_listener()
        def fail(*a,**kw): raise RuntimeError('PRIVATE_DIAGNOSTIC')
        self.stub.ListenV2=fail
        with self.assertRaises(self.listener.ReceiverListenerError) as caught: await listener.get_listen_client()
        self.assertEqual(str(caught.exception),'stream_acquire_failed')
        with self.assertRaises(self.listener.ReceiverListenerError): await listener.get_listen_client()
        self.assertEqual(len(self.channels),1)
        listener=self.make_listener();listener.stop_stream()
        with self.assertRaises(self.listener.ReceiverListenerError): await anext(listener.__aiter__())
        self.assertEqual(listener.unresolved_reads,())

    async def test_11_manifest_surface_and_extra_patch_reject_before_output(self):
        artifact=self.scratch/'mutated-artifact';artifact.mkdir()
        for name in ('apply_patch.py','upstream-manifest.json','receiver-policy.patch'):
            shutil.copyfile(ARTIFACT/name,artifact/name)
        app=load('mutated_rpc_app',artifact/'apply_patch.py')
        manifest=artifact/'upstream-manifest.json';raw=manifest.read_text()
        mutations=[raw.replace('"files": {','"files": {"extra": {},'),raw.replace('"stage":','"stage": "duplicate", "stage":')]
        for index,value in enumerate(mutations):
            manifest.write_text(value)
            target=self.scratch/('surface-'+str(index))
            with self.assertRaises(ValueError): app.apply(self.source,target)
            self.assertFalse(target.exists())
        manifest.write_text(raw)
        patchfile=artifact/'receiver-policy.patch'
        patchfile.write_text(patchfile.read_text(encoding='utf-8')+'--- a/unexpected.py\n+++ b/unexpected.py\n',encoding='utf-8')
        target=self.scratch/'unexpected-patch'
        with self.assertRaises(ValueError): app.apply(self.source,target)
        self.assertFalse(target.exists())

    async def test_12_stream_cancel_failure_is_safe_and_reads_settle(self):
        entered=asyncio.Event()
        class Stream:
            async def read(inner): entered.set();await asyncio.Event().wait()
            def cancel(inner): raise RuntimeError('PRIVATE_CANCEL')
        listener=self.make_listener(Stream());running=asyncio.create_task(anext(listener.__aiter__()))
        await entered.wait();listener.stop_stream()
        with self.assertRaises(self.listener.ReceiverListenerError) as caught: await running
        self.assertEqual(str(caught.exception),'stream_cancel_failed')
        self.assertEqual(listener.unresolved_reads,())

    async def test_13_manifest_missing_and_final_hash_mismatch(self):
        artifact=self.scratch/'bad-hash-artifact';artifact.mkdir()
        for name in ('apply_patch.py','upstream-manifest.json','receiver-policy.patch'):
            shutil.copyfile(ARTIFACT/name,artifact/name)
        app=load('bad_hash_rpc_app',artifact/'apply_patch.py')
        manifest=artifact/'upstream-manifest.json';original=json.loads(manifest.read_text())
        import copy
        for index in (0,1):
            value=copy.deepcopy(original)
            name='hatchet_sdk/clients/admin.py'
            if index==0: del value['files'][name]
            else: value['files'][name]['derivative_sha256']='0'*64
            manifest.write_text(json.dumps(value))
            target=self.scratch/('bad-hash-'+str(index))
            with self.assertRaises(ValueError): app.apply(self.source,target)
            self.assertFalse(target.exists())

    async def test_14_selected_rpc_cancellation_is_preserved(self):
        class Stub:
            async def GetVersion(inner,*a,**kw): raise asyncio.CancelledError()
            async def Register(inner,*a,**kw): raise asyncio.CancelledError()
            def PutWorkflow(inner,*a,**kw): raise asyncio.CancelledError()
        client=self.dispatcher.DispatcherClient(self.config);client.aio_client=Stub()
        admin=self.admin.AdminClient(self.config,None,None);admin.client=Stub()
        with self.assertRaises(asyncio.CancelledError): await client.get_version()
        with self.assertRaises(asyncio.CancelledError): await client.get_action_listener('worker',[],[],{},[])
        with self.assertRaises(asyncio.CancelledError): admin.put_workflow(Value())
        self.assertEqual(self.channels,[])

if __name__=="__main__": unittest.main()
