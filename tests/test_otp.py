"""RFC vectors, enrollment boundary, recovery and persistent replay protection."""
import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from test_app import create_app, fixture_config
from app.otp import Authenticator, code_for_counter, matching_counter
from app.store import Store


class OtpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.app = create_app(self.store)
        self.client = TestClient(self.app)
        self.headers = {"X-CSRF-Token": self.client.post(
            "/api/login", json={"password": self.store.password}).json()["csrf"]}
        self.now = 1700000010

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def post(self, endpoint, data):
        return self.client.post(endpoint, json=data, headers=self.headers)

    def enroll(self):
        setup = self.post("/api/auth/otp/setup", {"verification": self.store.password})
        self.assertEqual(setup.status_code, 200)
        result = setup.json()
        self.assertTrue(result["qr"].startswith("data:image/svg+xml;base64,"))
        self.secret = result["secret"]
        self.code = code_for_counter(self.secret, self.now // 30)
        with patch("app.otp.time.time", return_value=self.now):
            enabled = self.post("/api/auth/otp/enable", {"code": self.code})
        self.assertEqual(enabled.status_code, 200)
        return enabled.json()["recovery_codes"]

    def test_rfc6238_sha1_vectors_and_window(self):
        secret = base64.b32encode(b"12345678901234567890").decode()
        for when, code in [(59, "94287082"), (1111111109, "07081804"),
                           (1111111111, "14050471"), (1234567890, "89005924"),
                           (2000000000, "69279037"), (20000000000, "65353130")]:
            self.assertEqual(code_for_counter(secret, when // 30, digits=8), code)
        code = code_for_counter(secret, 100)
        self.assertEqual(matching_counter(secret, code, now=3030), 100)
        self.assertIsNone(matching_counter(secret, code, now=3060))
        self.assertIsNone(matching_counter(secret, code, now=3000, after=100))
        self.assertIsNone(matching_counter(secret, "１２３４５６", now=3000))

    def test_enrollment_requires_password_csrf_session_binding_and_expiry(self):
        self.assertEqual(self.client.post("/api/auth/otp/setup",
                                         json={"verification": self.store.password}).status_code, 403)
        self.assertEqual(self.post("/api/auth/otp/setup", {"verification": "wrong"}).status_code, 400)
        setup = self.post("/api/auth/otp/setup", {"verification": self.store.password}).json()
        secret = setup["secret"]
        other = TestClient(self.app)
        other_headers = {"X-CSRF-Token": other.post(
            "/api/login", json={"password": self.store.password}).json()["csrf"]}
        code = code_for_counter(secret, int(__import__("time").time() // 30))
        self.assertEqual(other.post("/api/auth/otp/enable", headers=other_headers,
                                    json={"code": code}).status_code, 400)
        with patch("app.otp.time.time", return_value=__import__("time").time() + 601):
            self.assertEqual(self.post("/api/auth/otp/enable", {"code": code}).status_code, 400)
        self.assertFalse(self.client.get("/api/mode").json()["otp_enabled"])
        other.close()

    def test_login_replay_recovery_encryption_and_restart(self):
        other = TestClient(self.app)
        other.post("/api/login", json={"password": self.store.password})
        codes = self.enroll()
        self.assertEqual(other.get("/api/state").status_code, 401)
        self.assertTrue(self.client.get("/api/mode").json()["otp_enabled"])
        self.assertEqual(self.client.post("/api/login", json={"password": self.store.password}).status_code, 403)
        authenticator = Authenticator(self.store)
        with patch("app.otp.time.time", return_value=self.now):
            self.assertFalse(authenticator.verify(self.code))
        next_code = code_for_counter(self.secret, self.now // 30 + 1)
        with patch("app.otp.time.time", return_value=self.now + 30):
            response = other.post("/api/login/otp", json={"code": next_code})
            self.assertEqual(response.status_code, 200)
            self.assertIn("httponly", response.headers["set-cookie"].lower())
            self.assertEqual(other.post("/api/login/otp", json={"code": next_code}).status_code, 401)
        reopened = Store(self.directory.name)
        restored = Authenticator(reopened)
        with patch("app.otp.time.time", return_value=self.now + 30):
            self.assertFalse(restored.verify(next_code))
        self.assertTrue(restored.verify(codes[0]))
        self.assertFalse(restored.verify(codes[0]))
        self.assertEqual(restored.status()["recovery_remaining"], 7)
        self.assertEqual(other.post("/api/login/otp", json={"code": codes[1]}).status_code, 200)
        packed = self.store.rows("SELECT encrypted FROM login_otp")[0]["encrypted"]
        self.assertNotIn(self.secret, packed)
        self.assertNotIn(codes[0].replace("-", ""), packed)
        public = str(self.client.get("/api/state").json())
        self.assertNotIn(self.secret, public)
        self.assertNotIn(codes[0], public)
        self.assertEqual(self.post("/api/auth/otp/setup", {"verification": self.store.password}).status_code, 400)
        reopened.db.close()
        other.close()

    def test_otp_rate_limit_and_local_only_developer_override(self):
        self.enroll()
        for _ in range(8):
            self.assertEqual(self.client.post("/api/login/otp", json={"code": "bad"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login/otp", json={"code": "bad"}).status_code, 429)
        with patch.dict(os.environ, {"AIMATE_DEV_LOGIN": "1"}):
            local = TestClient(self.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
            self.assertEqual(local.post("/api/login", json={"password": self.store.password}).status_code, 200)
            self.assertEqual(local.post("/api/dev/login").status_code, 200)
            self.assertTrue(local.get("/api/mode").json()["dev_login"])
            self.assertEqual(self.client.post("/api/dev/login").status_code, 403)
            self.assertEqual(self.client.post("/api/login", json={"password": self.store.password}).status_code, 403)
            with patch.dict(os.environ, {"APP_PUBLIC_URL": "https://aimate.example",
                                         "APP_PASSWORD": "hosted-password"}):
                hosted = create_app(self.store)
            remote = TestClient(hosted, base_url="https://aimate.example", client=("127.0.0.1", 50000))
            self.assertFalse(remote.get("/api/mode").json()["dev_login"])
            self.assertEqual(remote.post("/api/login", json={"password": self.store.password}).status_code, 403)
            self.assertEqual(remote.post("/api/dev/login").status_code, 403)
            local.close()
            remote.close()

    def test_production_requires_enrollment_and_cannot_enable_dev_bypass(self):
        with patch.dict(os.environ, {"AIMATE_ENV":"production", "AIMATE_DEV_LOGIN":"1"}):
            with self.assertRaisesRegex(ValueError, "Production requires an enrolled authenticator"):
                create_app(self.store)
        self.enroll()
        with patch.dict(os.environ, {"AIMATE_ENV":"production", "AIMATE_DEV_LOGIN":"1"}):
            production = create_app(self.store)
        with TestClient(production, base_url="http://127.0.0.1", client=("127.0.0.1",50000)) as client:
            self.assertFalse(client.get("/api/mode").json()["dev_login"])
            self.assertEqual(client.get("/api/mode").json()["environment"], "production")
            self.assertEqual(client.post("/api/dev/login").status_code,403)
            self.assertEqual(client.post("/api/login",json={"password":self.store.password}).status_code,403)
            with patch("app.otp.time.time",return_value=self.now+30):
                code=code_for_counter(self.secret,self.now//30+1)
                self.assertEqual(client.post("/api/login/otp",json={"code":code}).status_code,200)

    def test_production_delegated_user_requires_own_otp_and_rejects_replay(self):
        grant=self.post("/api/access/grants",{"name":"Reader","role":"viewer"}).json()
        self.enroll()
        with patch.dict(os.environ,{"AIMATE_ENV":"production"}):
            production=create_app(self.store)
        with TestClient(production) as client:
            payload={"role":"viewer","code":grant["code"]}
            self.assertEqual(client.post("/api/access/login",json=payload).status_code,401)
            now=__import__("time").time()
            own_code=code_for_counter(grant["authenticator_secret"],int(now//30))
            with patch("app.otp.time.time",return_value=now):
                response=client.post("/api/access/login",json={**payload,"otp":own_code})
                self.assertEqual(response.status_code,200)
                self.assertEqual(client.get("/api/state").json()["access"]["role"],"viewer")
                self.assertEqual(client.post("/api/access/login",json={**payload,"otp":own_code}).status_code,401)
            self.assertEqual(client.post("/api/access/login",json={**payload,"role":"admin","otp":own_code}).status_code,401)
        rows=self.store.rows("SELECT encrypted FROM access_grant_otp")
        self.assertNotIn(grant["authenticator_secret"],str(rows))
