"""Actual PostgreSQL enrollment/authority proof using only injected fake I/O."""
import hashlib
import json
import secrets
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adapters.models.contracts import Budget, Profile, ReadOnlyContext
from adapters.models.mock import ScriptedMock
from adapters.secrets.enrollment import EnrollmentRequest, EnrollmentBinding
from adapters.secrets.store import CredentialRef, SecretValue
from infra.core.enroll_profile import enroll_profile
from services.api.app import create_app
from services.api.errors import Problem
from services.api.profiles import bindings, repository
from services.api.profiles.authority import Purpose, load_profile, bind_authorize_profile
from services.api.providers.answer import answer
from services.api.settings import Settings


class FakeStore:
    def __init__(self, engine):
        self.engine = engine
        self.puts = self.gets = 0
        self.references = []
        self.values = []
        self.on_put = self.on_get = None

    def put(self, reference, value):
        assert self.engine.pool.checkedout() == 0, "Transaction leaked across fake put"
        assert reference.value.startswith("wincred:omniforge:v1:")
        self.puts += 1
        self.references.append(reference)
        self.values.append(value)
        assert value.reveal() == b"synthetic-binding-fixture"
        if self.on_put:
            self.on_put()

    def get(self, reference):
        assert reference == self.references[-1]
        self.gets += 1
        value = SecretValue(b"synthetic-binding-fixture")
        self.values.append(value)
        if self.on_get:
            self.on_get()
        return value

    def delete(self, reference):
        raise AssertionError("No fake or real credential deletion")


def final_response():
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({
        "observations": [], "claims": [], "outcome": "insufficient_data", "reason": "Synthetic binding fixture only"})}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 20}}


class ProviderBindingProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(Settings.from_env()); cls.engine = cls.app.state.engine
        cls.client = TestClient(cls.app, raise_server_exceptions=False)
        cls.principals = (uuid4(), uuid4()); cls.tokens = []; cls.auth = []; cls.cases = []
        with cls.engine.begin() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one() == "omniforge_rebuild"
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0007_run_delivery"
            for principal in cls.principals:
                token = secrets.token_urlsafe(48); cls.tokens.append(token)
                cls.auth.append({"Authorization": "Bearer "+token})
                conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:p,'binding-fake-fixture',:h)"),
                             {"p": principal, "h": hashlib.sha256(token.encode()).hexdigest()})
        for auth in cls.auth:
            r = cls.client.post("/api/v1/cases", json={"title": "Binding fake fixture"},
                                headers={**auth,"Idempotency-Key":str(uuid4())})
            assert r.status_code == 201
            cls.cases.append(UUID(r.json()["id"]))
        with cls.engine.begin() as conn:
            conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:b,:ca,false),(:a,:cb,true)"),
                         {"a":cls.principals[0],"b":cls.principals[1],"ca":cls.cases[0],"cb":cls.cases[1]})

    @classmethod
    def tearDownClass(cls):
        cls.client.close(); cls.engine.dispose()

    def url(self, profile=None, case=None):
        return f"/api/v1/cases/{case or self.cases[0]}/provider-profiles" + ("/"+str(profile) if profile else "")

    def profile(self):
        r=self.client.post(self.url(),json={"label":"Binding fake","model":"explicit-fixture-model"},
                           headers={**self.auth[0],"Idempotency-Key":str(uuid4())})
        self.assertEqual(r.status_code,201,r.text); return r.json()

    def current(self,p):
        r=self.client.get(self.url(p["id"]),headers=self.auth[0]); self.assertEqual(r.status_code,200); return r.json()

    def update(self,p,**changes):
        r=self.client.patch(self.url(p["id"]),json={"expected_revision":self.current(p)["revision"],**changes},
                            headers={**self.auth[0],"Idempotency-Key":str(uuid4())})
        self.assertEqual(r.status_code,200,r.text); return r.json()

    def request(self,p,operation=None):
        return EnrollmentRequest(operation_id=operation or uuid4(),principal_id=self.principals[0],case_id=self.cases[0],
                                 profile_id=UUID(p["id"]),expected_revision=p["revision"])

    def enrollment(self,request):
        with self.engine.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM provider_enrollments WHERE operation_id=:o"),
                                     {"o":request.operation_id}).mappings().one())

    def enroll(self,p,*,request=None,store=None,input_hook=None,token=None):
        request=request or self.request(p); store=store or FakeStore(self.engine); values=[]; inputs=[]
        def hidden_input():
            self.assertEqual(self.engine.pool.checkedout(),0)
            self.assertEqual(self.enrollment(request)["state"],"pending")
            inputs.append(True)
            value=SecretValue(b"synthetic-binding-fixture"); values.append(value)
            if input_hook: input_hook()
            return value
        result=enroll_profile(self.engine,bearer_token=self.tokens[0] if token is None else token,
                              request=request,store=store,hidden_input=hidden_input)
        return result,request,store,values,inputs

    def grant(self,write):
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE case_grants SET can_write=:w WHERE principal_id=:p AND case_id=:c"),
                         {"w":write,"p":self.principals[0],"c":self.cases[0]})

    def bound(self,p,**kwargs):
        current=self.current(p)
        return load_profile(self.engine,self.principals[0],self.cases[0],UUID(p["id"]),current["revision"],
                            Purpose.EXECUTE_DIAGNOSTIC,bearer_token=self.tokens[0],**kwargs)

    def callback(self,bound):
        return bind_authorize_profile(self.engine,self.principals[0],self.cases[0],bound,
                                      Purpose.EXECUTE_DIAGNOSTIC,bearer_token=self.tokens[0])

    def context(self,callback):
        return ReadOnlyContext(self.cases[0],"local-read-only-v1","Synthetic binding fixture",(),
            lambda *args: (_ for _ in ()).throw(AssertionError("No evidence tool requested")),callback,lambda:False)

    def test_01_atomic_disabled_attachment_explicit_activation_and_bound_mock(self):
        p=self.profile(); result,req,store,values,inputs=self.enroll(p)
        self.assertEqual(result.attached_revision,2); self.assertEqual((store.puts,len(inputs)),(1,1))
        self.assertFalse(values[0]._buffer); self.assertEqual(self.enrollment(req)["state"],"attached")
        configured=self.current(p); self.assertTrue(configured["credential_configured"]); self.assertFalse(configured["enabled"])
        self.assertEqual(configured["binding_status"],"attached")
        with self.assertRaises(Problem): self.bound(p)
        active=self.update(p,enabled=True); self.assertEqual(active["revision"],3)
        bound=self.bound(p); callback=self.callback(bound); self.assertTrue(callback(bound.profile))
        mock=ScriptedMock([final_response()]); response=answer(self.context(callback),bound.profile,bound.budget,store=store,transport=mock)
        self.assertIsNone(response.error); self.assertEqual(response.answer.outcome,"insufficient_data")
        self.assertEqual((store.gets,mock.calls,response.usage.calls),(1,1,1)); self.assertFalse(store.values[-1]._buffer)
        self.assertEqual(response.usage.cost.state,"unknown")
        for payload in (configured,active,self.client.get(self.url(p["id"])+"/diagnostics",headers=self.auth[1]).json()):
            self.assertNotIn("wincred:",json.dumps(payload)); self.assertNotIn("credential_ref",payload)

    def test_02_replay_current_auth_and_no_reactivation_or_input(self):
        p=self.profile(); receipt,req,store,_,_=self.enroll(p)
        activation_key=str(uuid4()); activation_body={"expected_revision":2,"enabled":True}
        def activate():
            return self.client.patch(self.url(p["id"]),json=activation_body,
                                     headers={**self.auth[0],"Idempotency-Key":activation_key})
        original=activate(); self.assertEqual(original.status_code,200)
        disabled=self.update(p,enabled=False)
        self.assertEqual(activate().json(),original.json()); self.assertEqual(self.current(p),disabled)
        def no_input(): raise AssertionError("Replay must not prompt")
        repeated=enroll_profile(self.engine,bearer_token=self.tokens[0],request=req,store=store,hidden_input=no_input)
        self.assertEqual(repeated,receipt); self.assertEqual(store.puts,1); self.assertEqual(self.current(p),disabled)
        try:
            self.grant(False)
            self.assertEqual(activate().status_code,403)
            with self.assertRaises(Problem): enroll_profile(self.engine,bearer_token=self.tokens[0],request=req,store=store,hidden_input=no_input)
        finally: self.grant(True)
        for token in ("invalid-local-auth",self.tokens[1]):
            with self.assertRaises(Problem): enroll_profile(self.engine,bearer_token=token,request=req,store=store,hidden_input=no_input)
        for changed in (replace(req,expected_revision=2),replace(req,profile_id=UUID(self.profile()["id"])),
                        replace(req,case_id=self.cases[1])):
            with self.assertRaises(Problem): enroll_profile(self.engine,bearer_token=self.tokens[0],request=changed,store=store,hidden_input=no_input)
        self.assertEqual(store.puts,1)

    def test_03_revoke_or_revise_during_input_zero_put_and_clear(self):
        for kind in ("revoke","revision","token"):
            with self.subTest(kind=kind):
                p=self.profile(); req=self.request(p); store=FakeStore(self.engine); supplied=[]
                old_hash=hashlib.sha256(self.tokens[0].encode()).hexdigest()
                def hidden():
                    self.assertEqual(self.engine.pool.checkedout(),0)
                    value=SecretValue(b"synthetic-binding-fixture"); supplied.append(value)
                    if kind=="revoke": self.grant(False)
                    elif kind=="revision": self.update(p,label="Changed during input")
                    else:
                        with self.engine.begin() as conn:
                            conn.execute(text("UPDATE principals SET token_hash=:h WHERE id=:p"), {"h":hashlib.sha256(b"new-synthetic-token").hexdigest(),"p":self.principals[0]})
                    return value
                try:
                    with self.assertRaises(Problem): enroll_profile(self.engine,bearer_token=self.tokens[0],request=req,store=store,hidden_input=hidden)
                finally:
                    self.grant(True)
                    with self.engine.begin() as conn:
                        conn.execute(text("UPDATE principals SET token_hash=:h WHERE id=:p"),{"h":old_hash,"p":self.principals[0]})
                self.assertEqual(store.puts,0); self.assertFalse(supplied[0]._buffer)
                self.assertEqual(self.enrollment(req)["state"],"unresolved"); self.assertFalse(self.current(p)["credential_configured"])

    def test_04_postput_revoke_revision_or_exception_never_attach(self):
        for kind in ("revoke","revision","put_error"):
            with self.subTest(kind=kind):
                p=self.profile(); req=self.request(p); store=FakeStore(self.engine)
                def after_put():
                    if kind=="revoke": self.grant(False)
                    elif kind=="revision": self.update(p,label="Changed during fake put")
                    else: raise RuntimeError("SENSITIVE_FAKE_ERROR")
                store.on_put=after_put
                try:
                    with self.assertRaises(Problem) as error: self.enroll(p,request=req,store=store)
                finally: self.grant(True)
                self.assertEqual(store.puts,1); self.assertFalse(store.values[-1]._buffer)
                self.assertNotIn("SENSITIVE_FAKE_ERROR",error.exception.message)
                self.assertEqual(self.enrollment(req)["state"],"unresolved"); self.assertFalse(self.current(p)["credential_configured"])

    def test_05_postput_db_outage_retains_pending_and_blocks_retry(self):
        p=self.profile(); req=self.request(p); store=FakeStore(self.engine)
        outage=patch.object(self.engine,"begin",side_effect=RuntimeError("synthetic DB outage"))
        store.on_put=lambda: outage.start()
        try:
            with self.assertRaises(Problem): self.enroll(p,request=req,store=store)
        finally: outage.stop()
        self.assertEqual(self.enrollment(req)["state"],"pending"); self.assertEqual(store.puts,1)
        self.assertFalse(store.values[-1]._buffer); self.assertFalse(self.current(p)["credential_configured"])
        store.on_put=None
        with self.assertRaises(Problem): self.enroll(p,request=req,store=store)
        self.assertEqual(store.puts,1)

    def test_06_full_tuple_guards_and_no_cross_profile_ref(self):
        p=self.profile(); receipt,req,store,_,_=self.enroll(p); row=self.enrollment(req)
        another=self.profile(); second=self.request(another)
        fresh=EnrollmentBinding(**asdict(second),credential_ref=CredentialRef.new())
        self.assertEqual(bindings.reserve(self.engine,self.tokens[0],fresh).disposition,"ready")
        mutations=[("UPDATE provider_enrollments SET principal_id=:other WHERE operation_id=:o",self.principals[1]),
                   ("UPDATE provider_enrollments SET expected_revision=2 WHERE operation_id=:o",None),
                   ("DELETE FROM provider_enrollments WHERE operation_id=:o",None)]
        for sql,other in mutations:
            with self.assertRaises(DBAPIError):
                with self.engine.begin() as conn: conn.execute(text(sql),{"o":req.operation_id,"other":other})
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                values=repository.dto(repository.current(conn,self.cases[0],UUID(another["id"]))).model_dump(mode="json")
                repository.append(conn,self.principals[0],self.cases[0],values,UUID(another["id"]),2,binding=bindings.row_binding(row))
        for field,value in (("operation_id",uuid4()),("principal_id",self.principals[1]),("case_id",self.cases[1]),
                            ("profile_id",UUID(p["id"])),("credential_ref",store.references[0]),("expected_revision",2)):
            with self.assertRaises(Problem): bindings.authorize_put(self.engine,self.tokens[0],replace(fresh,**{field:value}))
        self.assertEqual(self.enrollment(second)["state"],"pending")
        bindings.unresolved(self.engine,fresh)

    def test_07_one_concurrent_operation_one_input_put_and_receipt(self):
        p=self.profile(); req=self.request(p); store=FakeStore(self.engine); entered=threading.Event(); release=threading.Event(); inputs=[]
        def hidden():
            self.assertEqual(self.engine.pool.checkedout(),0); inputs.append(True); entered.set()
            self.assertTrue(release.wait(5)); return SecretValue(b"synthetic-binding-fixture")
        def first(): return enroll_profile(self.engine,bearer_token=self.tokens[0],request=req,store=store,hidden_input=hidden)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(first)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(Problem): self.enroll(p,request=req,store=store)
            finally: release.set()
            self.assertEqual(future.result(timeout=10).attached_revision,2)
        self.assertEqual((len(inputs),store.puts),(1,1)); self.assertEqual(self.enrollment(req)["state"],"attached")

    def test_08_exact_current_adapter_caps_case_ref_and_token_authority(self):
        p=self.profile(); _,_,store,_,_=self.enroll(p); self.update(p,enabled=True)
        budget=Budget(calls=1,input_tokens=32768,output_tokens=512,tool_bytes=0,wall_seconds=10)
        bound=self.bound(p,requested_budget=budget); callback=self.callback(bound)
        self.assertTrue(callback(bound.profile)); self.assertEqual(bound.budget,budget)
        for changes in ({"id":uuid4()},{"revision":2},{"model":"other-model"},{"endpoint":"https://example.invalid"},
                        {"credential_ref":CredentialRef.new()}): self.assertFalse(callback(replace(bound.profile,**changes)))
        for field in Budget.model_fields:
            widened=Budget(**{**bound.caps.model_dump(),field:getattr(bound.caps,field)+1})
            with self.assertRaises(Problem): self.bound(p,requested_budget=widened)
        wrong=bind_authorize_profile(self.engine,self.principals[0],self.cases[1],bound,Purpose.EXECUTE_DIAGNOSTIC,bearer_token=self.tokens[0])
        self.assertFalse(wrong(bound.profile))
        for token in (None,"invalid-local-auth",self.tokens[1]):
            with self.assertRaises(Problem): load_profile(self.engine,self.principals[0],self.cases[0],UUID(p["id"]),3,Purpose.EXECUTE_DIAGNOSTIC,bearer_token=token)
        old_hash=hashlib.sha256(self.tokens[0].encode()).hexdigest()
        try:
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE principals SET token_hash=:h WHERE id=:p"),
                             {"h":hashlib.sha256(b"rotated-synthetic-binding-token").hexdigest(),"p":self.principals[0]})
            self.assertFalse(callback(bound.profile))
        finally:
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE principals SET token_hash=:h WHERE id=:p"),{"h":old_hash,"p":self.principals[0]})
        with patch.object(self.engine,"begin",side_effect=RuntimeError("synthetic callback outage")):
            self.assertFalse(callback(bound.profile))
        self.update(p,caps={**bound.caps.model_dump(),"calls":1})
        self.assertFalse(callback(bound.profile))
        current=self.bound(p); self.assertEqual(current.profile.credential_ref,store.references[-1]); self.assertEqual(current.caps.calls,1)
        self.update(p,model="revised-model"); self.assertFalse(self.callback(current)(current.profile))
        current=self.bound(p)
        self.update(p,enabled=False); self.assertFalse(self.callback(current)(current.profile))

    def test_09_actual_callback_denies_before_get_after_get_and_before_publication(self):
        for boundary in ("before_get","during_get","before_publish"):
            for change in ("grant","disable","model","fresh_ref"):
                with self.subTest(boundary=boundary,change=change):
                    p=self.profile(); _,_,store,_,_=self.enroll(p); self.update(p,enabled=True)
                    bound=self.bound(p); callback=self.callback(bound)
                    def mutate():
                        if change=="grant": self.grant(False)
                        elif change=="disable": self.update(p,enabled=False)
                        elif change=="model": self.update(p,model="changed-during-boundary")
                        else: self.enroll(self.current(p))
                    mock=ScriptedMock([final_response()])
                    if boundary=="before_get": mutate()
                    elif boundary=="during_get": store.on_get=mutate
                    else:
                        original=mock.complete
                        def complete(*args):
                            result=original(*args); mutate(); return result
                        mock.complete=complete
                    try:
                        result=answer(self.context(callback),bound.profile,bound.budget,store=store,transport=mock)
                    finally: self.grant(True)
                    self.assertEqual(result.error,"forbidden"); self.assertIsNone(result.answer)
                    expected=1 if boundary=="before_publish" else 0
                    self.assertEqual((result.usage.calls,mock.calls),(expected,expected))
                    self.assertEqual(store.gets,0 if boundary=="before_get" else 1)
                    if store.gets: self.assertFalse(store.values[-1]._buffer)
                    if expected: self.assertEqual((result.usage.input_tokens.value,result.usage.output_tokens.value),(30,20))

    def test_10_passive_bound_diagnostics_and_public_ref_rejection(self):
        p=self.profile(); _,_,store,_,_=self.enroll(p); self.update(p,enabled=True)
        with patch("adapters.secrets.windows.WindowsSecretStore",side_effect=AssertionError("No OS store")) as os_store, \
             patch("services.api.providers.answer.answer",side_effect=AssertionError("No probe")) as probe:
            r=self.client.get(self.url(p["id"])+"/diagnostics",headers=self.auth[1]); self.assertEqual(r.status_code,200)
            body=r.json(); self.assertTrue(body["enabled"] and body["credential_configured"])
            self.assertEqual(body["binding_status"],"attached")
            self.assertEqual({f["status"] for f in body["features"].values()},{"unverified"})
            os_store.assert_not_called(); probe.assert_not_called()
        for payload in ({"credential_ref":store.references[-1].value},{"binding_operation_id":str(uuid4())},
                        {"attach":True},{"key":"SENSITIVE_FAKE_INPUT"}):
            r=self.client.patch(self.url(p["id"]),json={"expected_revision":3,**payload},headers={**self.auth[0],"Idempotency-Key":str(uuid4())})
            self.assertEqual(r.status_code,422); self.assertNotIn("SENSITIVE_FAKE_INPUT",r.text); self.assertNotIn("wincred:",r.text)
        self.assertEqual((store.puts,store.gets),(1,0))

    def test_11_reservation_current_auth_writer_case_and_revision_before_input(self):
        p=self.profile(); req=self.request(p); store=FakeStore(self.engine)
        denied=[(replace(req,principal_id=self.principals[1]),self.tokens[1]),
                (replace(req,case_id=self.cases[1]),self.tokens[0]),
                (replace(req,expected_revision=2),self.tokens[0]),(req,"invalid-local-auth")]
        def no_input(): raise AssertionError("Denied reservation cannot prompt")
        for request,token in denied:
            with self.assertRaises(Problem):
                enroll_profile(self.engine,bearer_token=token,request=request,store=store,hidden_input=no_input)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM provider_enrollments WHERE operation_id=:o"),{"o":req.operation_id}).scalar_one(),0)
        self.assertEqual(store.puts,0)
        fresh=EnrollmentBinding(**asdict(req),credential_ref=CredentialRef.new())
        bindings.reserve(self.engine,self.tokens[0],fresh)
        self.assertEqual(self.current(p)["binding_status"],"pending")
        bindings.unresolved(self.engine,fresh)
        self.assertEqual(self.current(p)["binding_status"],"unresolved")
        with self.assertRaises(Problem):
            enroll_profile(self.engine,bearer_token=self.tokens[0],request=req,store=store,hidden_input=no_input)
        self.assertEqual(store.puts,0)

    def test_12_attachment_transaction_and_deferred_full_binding_guard(self):
        p=self.profile(); req=self.request(p); store=FakeStore(self.engine)
        with patch("services.api.profiles.bindings.receipt",side_effect=RuntimeError("synthetic precommit failure")):
            with self.assertRaises(Problem): self.enroll(p,request=req,store=store)
        self.assertEqual(store.puts,1); self.assertFalse(store.values[-1]._buffer)
        self.assertEqual(self.current(p)["revision"],1)
        self.assertEqual(self.enrollment(req)["state"],"unresolved")
        # A version carrying a valid pending tuple cannot commit without exact
        # attached state; the deferred trigger joins the complete operation tuple.
        other=self.profile(); pending_req=self.request(other)
        candidate=EnrollmentBinding(**asdict(pending_req),credential_ref=CredentialRef.new())
        bindings.reserve(self.engine,self.tokens[0],candidate)
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                row=repository.current(conn,self.cases[0],UUID(other["id"]),locked=True)
                repository.append(conn,self.principals[0],self.cases[0],repository.dto(row).model_dump(mode="json"),
                                  UUID(other["id"]),2,binding=candidate)
        self.assertEqual(self.current(other)["revision"],1); self.assertEqual(self.enrollment(pending_req)["state"],"pending")
        bindings.unresolved(self.engine,candidate)
