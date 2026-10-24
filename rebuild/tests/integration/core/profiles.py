"""Actual PostgreSQL metadata authority proof; no enrollment or live provider."""
import hashlib
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adapters.models.contracts import Budget, Profile
from adapters.secrets.store import CredentialRef
from services.api.app import create_app
from services.api.errors import Problem
from services.api.profiles.authority import Purpose, bind_authorize_profile, load_profile, narrow_budget
from services.api.profiles.contracts import ProviderProfileView, default_caps
from services.api.settings import Settings


class ProfileMetadataProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(Settings.from_env())
        cls.engine = cls.app.state.engine
        cls.client = TestClient(cls.app, raise_server_exceptions=False)
        cls.a, cls.b = uuid4(), uuid4()
        cls.auth = []
        with cls.engine.begin() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one() == "omniforge_rebuild"
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0007_run_delivery"
            for principal in (cls.a, cls.b):
                token = secrets.token_urlsafe(48)
                cls.auth.append({"Authorization": "Bearer " + token})
                conn.execute(text("INSERT INTO principals(id,label,token_hash) VALUES(:id,'profile-metadata-fixture',:hash)"),
                             {"id": principal, "hash": hashlib.sha256(token.encode()).hexdigest()})
        cls.cases = []
        for auth in cls.auth:
            result = cls.client.post("/api/v1/cases", json={"title": "Profile metadata fixture"},
                                     headers={**auth, "Idempotency-Key": str(uuid4())})
            assert result.status_code == 201, result.text
            cls.cases.append(UUID(result.json()["id"]))
        with cls.engine.begin() as conn:
            conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:b,:ca,false),(:a,:cb,true)"),
                         {"a": cls.a, "b": cls.b, "ca": cls.cases[0], "cb": cls.cases[1]})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()

    def url(self, case=None, profile=None):
        return f"/api/v1/cases/{case or self.cases[0]}/provider-profiles" + ("/"+str(profile) if profile else "")

    def create(self, body=None, key=None, case=None, auth=None):
        return self.client.post(self.url(case), json=body or {"label": "Synthetic profile", "model": "explicit-fixture-model"},
                                headers={**(auth or self.auth[0]), "Idempotency-Key": key or str(uuid4())})

    def profile(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def update(self, profile, body, key=None, auth=None, case=None):
        return self.client.patch(self.url(case, profile["id"]), json=body,
                                 headers={**(auth or self.auth[0]), "Idempotency-Key": key or str(uuid4())})

    def test_01_defaults_reader_writer_and_case_scope(self):
        p = self.profile()
        self.assertEqual(p["revision"], 1)
        self.assertEqual(p["caps"], default_caps().model_dump())
        self.assertFalse(p["enabled"] or p["credential_configured"])
        self.assertEqual(p["binding_status"], "unconfigured")
        self.assertEqual(self.client.get(self.url(profile=p["id"]), headers=self.auth[1]).json(), p)
        self.assertEqual(self.create(auth=self.auth[1]).status_code, 403)
        self.assertEqual(self.update(p, {"expected_revision": 1, "label": "denied"}, auth=self.auth[1]).status_code, 403)
        # A can write both cases, yet a foreign profile still cannot rebind.
        self.assertEqual(self.client.get(self.url(self.cases[1], p["id"]), headers=self.auth[0]).status_code, 404)
        self.assertEqual(self.update(p, {"expected_revision": 1, "label": "denied"}, case=self.cases[1]).status_code, 404)
        foreign = self.create(case=self.cases[1], auth=self.auth[1]).json()
        self.assertNotIn(foreign["id"], [x["id"] for x in self.client.get(self.url(), headers=self.auth[1]).json()["items"]])
        self.assertEqual(self.client.get(self.url(), headers={"X-Principal-ID": str(self.a)}).status_code, 401)

    def test_02_append_disable_replay_and_stale(self):
        p = self.profile()
        key = str(uuid4())
        body = {"expected_revision": 1, "label": "Revision two", "model": "revised-fixture-model"}
        updated = self.update(p, body, key)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["revision"], 2)
        disabled = self.update(p, {"expected_revision": 2, "enabled": False}).json()
        self.assertEqual(disabled["revision"], 3)
        self.assertEqual(self.update(p, body, key).json(), updated.json())
        self.assertEqual(self.client.get(self.url(profile=p["id"]), headers=self.auth[0]).json(), disabled)
        self.assertEqual(self.update(p, {**body, "label": "Changed"}, key).status_code, 409)
        self.assertEqual(self.update(p, body).json()["code"], "stale_revision")
        self.assertEqual(self.update(p, {"expected_revision": 3, "enabled": True}).json()["code"], "profile_unconfigured")
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT revision,label,enabled FROM provider_profile_versions WHERE profile_id=:p ORDER BY revision"), {"p": p["id"]}).all()
        self.assertEqual(rows, [(1, p["label"], False), (2, "Revision two", False), (3, "Revision two", False)])

    def test_03_current_grant_before_create_and_update_replay(self):
        case, principal = self.cases[0], self.a
        create_key, update_key = str(uuid4()), str(uuid4())
        p = self.create(key=create_key).json()
        body = {"expected_revision": 1, "label": "Grant replay fixture"}
        self.assertEqual(self.update(p, body, update_key).status_code, 200)
        try:
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"), {"p": principal, "c": case})
            self.assertEqual(self.create(key=create_key).status_code, 403)
            self.assertEqual(self.update(p, body, update_key).status_code, 403)
            self.assertEqual(self.client.get(self.url(profile=p["id"]), headers=self.auth[0]).status_code, 200)
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM case_grants WHERE principal_id=:p AND case_id=:c"), {"p": principal, "c": case})
            self.assertEqual(self.client.get(self.url(profile=p["id"]), headers=self.auth[0]).status_code, 403)
        finally:
            with self.engine.begin() as conn:
                conn.execute(text("INSERT INTO case_grants(principal_id,case_id,can_write) VALUES(:p,:c,true) ON CONFLICT(principal_id,case_id) DO UPDATE SET can_write=true"), {"p": principal, "c": case})

    def test_04_concurrent_idempotency_and_expected_revision(self):
        key = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(lambda _: self.create(key=key), range(2)))
        self.assertEqual([x.status_code for x in created], [201, 201])
        self.assertEqual(created[0].json(), created[1].json())
        p = created[0].json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda label: self.update(p, {"expected_revision": 1, "label": label}), ("First", "Second")))
        self.assertEqual(sorted(x.status_code for x in responses), [200, 409])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM provider_profile_versions WHERE profile_id=:p"), {"p": p["id"]}).scalar_one(), 2)

    def test_05_strict_caps_endpoint_and_safe_validation(self):
        base = {"label": "Input fixture", "model": "explicit-fixture-model"}
        invalid = [{**base, "credential_ref": "SENSITIVE_FIXTURE"}, {**base, "key": "SENSITIVE_FIXTURE"},
                   {**base, "owner": str(self.a)}, {**base, "id": str(uuid4())}, {**base, "enabled": True},
                   {**base, "endpoint": "https://example.invalid"}, {"label": "No model"},
                   {**base, "model": "not\nprintable"}, {**base, "model": " surrounding "}]
        bounds = {"calls": (0, 17), "input_tokens": (0, 1000001), "output_tokens": (0, 100001),
                  "wall_seconds": (0, 301), "tool_bytes": (-1, 1048577)}
        for name, values in bounds.items():
            for value in (*values, True, "2", 2.0):
                invalid.append({**base, "caps": {**default_caps().model_dump(), name: value}})
        for body in invalid:
            with self.subTest(body_keys=tuple(body)):
                response = self.create(body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["code"], "invalid_request")
                self.assertNotIn("SENSITIVE_FIXTURE", response.text)
        p = self.profile()
        for extra in ({"credential_ref": "SENSITIVE_FIXTURE"}, {"case_id": str(self.cases[1])},
                      {"label": None}, {"enabled": "false"}, {}):
            self.assertEqual(self.update(p, {"expected_revision": 1, **extra}).status_code, 422)
        maximum = Budget(calls=16, input_tokens=1000000, output_tokens=100000, wall_seconds=300, tool_bytes=1048576)
        self.assertEqual(self.create({**base, "caps": maximum.model_dump()}).status_code, 201)

    def test_06_passive_diagnostics_and_no_effects(self):
        p = self.profile()
        # Tripwires: constructor or any outbound adapter call would fail the test.
        with patch("adapters.secrets.windows.WindowsSecretStore", side_effect=AssertionError("No store construction")) as store, \
             patch("services.api.providers.answer.answer", side_effect=AssertionError("No provider call")) as provider, \
             patch("socket.create_connection", side_effect=AssertionError("No outbound socket")) as network:
            # Existing PostgreSQL pool is connected; diagnostics use only it.
            response = self.client.get(self.url(profile=p["id"])+"/diagnostics", headers=self.auth[1])
            self.assertEqual(response.status_code, 200, response.text)
            diagnostic = response.json()
            self.assertEqual(diagnostic["features"]["enrollment"]["status"], "unverified")
            self.assertEqual({v["status"] for k,v in diagnostic["features"].items() if k != "enrollment"}, {"unverified"})
            self.assertIn("no credential-store or transport", diagnostic["provenance"])
            self.assertEqual(self.update(p, {"expected_revision": 1, "enabled": True}).status_code, 409)
            store.assert_not_called(); provider.assert_not_called(); network.assert_not_called()
        for value in (p, diagnostic):
            self.assertFalse({"credential_ref", "owner", "created_by", "token_hash"} & value.keys())

    def test_07_closed_authority_full_snapshot_and_budget(self):
        p = self.profile()
        args = (self.engine, self.a, self.cases[0], UUID(p["id"]), 1)
        snapshot = load_profile(*args, Purpose.CONFIGURE)
        bound = bind_authorize_profile(self.engine, self.a, self.cases[0], snapshot, Purpose.CONFIGURE)
        self.assertTrue(bound(snapshot))
        for field, value in (("model", "forged-model"), ("case_id", self.cases[1]), ("revision", 2),
                             ("caps", default_caps().model_copy(update={"calls": 3}))):
            self.assertFalse(bound(snapshot.model_copy(update={field: value})))
        fake_profile = Profile(UUID(p["id"]), 1, p["endpoint"], p["model"], CredentialRef("wincred:omniforge:test:" + str(uuid4())))
        self.assertFalse(bound(fake_profile))
        for purpose in ("arbitrary", Purpose.ENROLL, Purpose.EXECUTE_DIAGNOSTIC):
            with self.assertRaises(Problem) as denied:
                load_profile(*args, purpose)
            self.assertEqual(denied.exception.status, 403)
        with self.assertRaises(Problem):
            load_profile(self.engine, self.b, self.cases[0], UUID(p["id"]), 1, Purpose.CONFIGURE)
        caps = snapshot.caps
        lowered = Budget(**{**caps.model_dump(), "calls": 1, "tool_bytes": 0})
        self.assertEqual(narrow_budget(caps, lowered), lowered)
        for field in Budget.model_fields:
            increased = Budget(**{**caps.model_dump(), field: getattr(caps, field)+1})
            with self.assertRaises(Problem):
                narrow_budget(caps, increased)
        self.assertEqual(self.update(p, {"expected_revision": 1, "enabled": False}).status_code, 200)
        self.assertFalse(bound(snapshot))
        with self.assertRaises(Problem) as stale:
            load_profile(*args, Purpose.CONFIGURE)
        self.assertEqual(stale.exception.status, 409)

    def test_08_database_guards_and_history_identity(self):
        p = self.profile()
        statements = ["UPDATE provider_profile_versions SET label='rewrite' WHERE profile_id=:p",
                      "DELETE FROM provider_profile_versions WHERE profile_id=:p",
                      "INSERT INTO provider_profile_versions SELECT profile_id,revision+1,:other,created_by,schema_version,label,endpoint,model,calls,input_tokens,output_tokens,wall_seconds,tool_bytes,enabled,created_at FROM provider_profile_versions WHERE profile_id=:p",
                      "INSERT INTO provider_profile_versions SELECT profile_id,revision+2,case_id,created_by,schema_version,label,endpoint,model,calls,input_tokens,output_tokens,wall_seconds,tool_bytes,enabled,created_at FROM provider_profile_versions WHERE profile_id=:p",
                      "INSERT INTO provider_profile_versions SELECT profile_id,revision+1,case_id,created_by,schema_version,label,endpoint,model,calls,input_tokens,output_tokens,wall_seconds,tool_bytes,true,created_at FROM provider_profile_versions WHERE profile_id=:p"]
        for statement in statements:
            with self.subTest(operation=statement.split()[0]), self.assertRaises(DBAPIError):
                with self.engine.begin() as conn:
                    conn.execute(text(statement), {"p": p["id"], "other": self.cases[1]})
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM provider_profile_versions WHERE profile_id=:p"), {"p": p["id"]}).scalar_one(), 1)

    def test_09_current_only_bounded_page_and_fresh_process_state(self):
        p = self.profile()
        revised = self.update(p, {"expected_revision": 1, "label": "Current only"}).json()
        items, cursor = [], None
        while True:
            result = self.client.get(self.url(), headers=self.auth[1], params={"limit": 1, **({"cursor": cursor} if cursor else {})})
            self.assertEqual(result.status_code, 200)
            page = result.json(); items.extend(page["items"]); cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(len(items), len({item["id"] for item in items}))
        self.assertEqual([item for item in items if item["id"] == p["id"]], [revised])
        for params in ({"cursor": "invalid"}, {"limit": 0}, {"limit": 101}):
            self.assertEqual(self.client.get(self.url(), headers=self.auth[0], params=params).status_code, 422)
        fresh = create_app(Settings.from_env())
        with TestClient(fresh) as client:
            self.assertEqual(client.get(self.url(profile=p["id"]), headers=self.auth[0]).json(), revised)

    def test_10_authority_revocation_and_outage_fail_closed(self):
        p = self.profile()
        snapshot = ProviderProfileView.model_validate(p)
        bound = bind_authorize_profile(self.engine, self.a, self.cases[0], snapshot, Purpose.CONFIGURE)
        self.assertTrue(bound(snapshot))
        try:
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE case_grants SET can_write=false WHERE principal_id=:p AND case_id=:c"), {"p": self.a, "c": self.cases[0]})
            self.assertFalse(bound(snapshot))
        finally:
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE case_grants SET can_write=true WHERE principal_id=:p AND case_id=:c"), {"p": self.a, "c": self.cases[0]})
        with patch.object(self.engine, "begin", side_effect=RuntimeError("synthetic outage")):
            self.assertFalse(bound(snapshot))
