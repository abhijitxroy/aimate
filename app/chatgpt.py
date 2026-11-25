"""Local OAuth public client for ChatGPT plan usage. No API-key fallback."""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PERMISSION = "chatgpt.tokens.use.direct"


def protect(data, store, decrypt=False):
    """Windows binds OAuth storage to the current OS user; Unix uses the app cipher."""
    if os.name != "nt":
        return store.cipher.decrypt(data) if decrypt else store.cipher.encrypt(data)
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    method = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("ChatGPT credentials could not be opened by this Windows account")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


class ChatGPT:
    def __init__(self, store, transport=None):
        self.store, self.transport = store, transport
        self.pending = {}
        self.lock = asyncio.Lock()
        store.execute("CREATE TABLE IF NOT EXISTS chatgpt_auth (id INTEGER PRIMARY KEY CHECK(id=1), encrypted TEXT)")
        if not self.record():
            self.save({"host_id": "urn:uuid:" + str(uuid.uuid4()), "accounts": {}, "active": None})

    def client(self):
        return httpx.AsyncClient(transport=self.transport, timeout=90, follow_redirects=False)

    def record(self):
        rows = self.store.rows("SELECT encrypted FROM chatgpt_auth WHERE id=1")
        if not rows:
            return {}
        return json.loads(protect(base64.b64decode(rows[0]["encrypted"]), self.store, decrypt=True))

    def save(self, record):
        value = base64.b64encode(protect(json.dumps(record).encode(), self.store)).decode()
        self.store.execute("INSERT OR REPLACE INTO chatgpt_auth VALUES (1, ?)", (value,))

    def status(self):
        record = self.record()
        account = record.get("accounts", {}).get(record.get("active"), {})
        return {
            "connected": bool(account.get("access_token")),
            "plan_enabled": bool(account.get("access_token") and PERMISSION in account.get("scopes", [])),
            "active": record.get("active"),
            "accounts": [{"id": key, "email": a.get("email", "ChatGPT account"),
                          "signed_in": bool(a.get("access_token"))}
                         for key, a in record.get("accounts", {}).items()],
        }

    def start(self, origin, session_token, account_id=None):
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path:
            raise ValueError("Open AiMate at http://127.0.0.1:8765 for local ChatGPT sign-in")
        record = self.record()
        account = record["accounts"].get(account_id) if account_id else None
        if account_id and not account:
            raise ValueError("Saved ChatGPT account not found")
        state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
        redirect_uri = origin + "/auth/callback"
        now = time.time()
        self.pending = {key: value for key, value in self.pending.items() if value["expires"] > now}
        # One outstanding attempt per AiMate session.
        self.pending = {key: value for key, value in self.pending.items() if value["session"] != session_token}
        self.pending[state] = {"nonce": nonce, "verifier": verifier, "redirect_uri": redirect_uri,
                               "expires": now + 600, "session": session_token, "account": account}
        params = {"client_id": account["client_id"] if account else "dynamic_agent_client",
                  "ext_agent_host_id": record["host_id"], "response_type": "code",
                  "redirect_uri": redirect_uri, "scope": SCOPE, "resource": RESOURCE,
                  "state": state, "nonce": nonce, "code_challenge_method": "S256",
                  "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
        if account:
            if account.get("id_token"):
                params["id_token_hint"] = account["id_token"]
            if account.get("email"):
                params["login_hint"] = account["email"]
        else:
            params["agent_name_hint"] = "AiMate"
        return AUTHORIZE + "?" + urlencode(params)

    async def verify_identity(self, token, client_id, nonce=None):
        async with self.client() as client:
            response = await client.get(ISSUER + "/.well-known/jwks.json")
            response.raise_for_status()
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"RS256", "ES256"}:
                raise ValueError("Unsupported ID-token signature")
            keys = [key for key in response.json()["keys"] if key.get("kid") == header.get("kid")]
            if len(keys) != 1:
                raise ValueError("ID-token signing key not found")
            key = jwt.PyJWK.from_dict(keys[0]).key
            claims = jwt.decode(token, key, algorithms=[header["alg"]], audience=client_id,
                                issuer=ISSUER, leeway=5, options={"require": ["sub", "exp", "iat", "iss", "aud"]})
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise ValueError("Missing account identity")
            if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
                raise ValueError("ID-token nonce mismatch")
            return claims
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise ValueError("ChatGPT identity could not be verified; sign in again") from None

    async def token_request(self, data):
        async with self.client() as client:
            response = await client.post(TOKEN, data=data)
        if response.status_code != 200:
            raise ValueError("ChatGPT authorization could not be completed. Sign in again and check plan permission.")
        try:
            tokens = response.json()
            if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
                raise ValueError()
            if tokens.get("token_type", "").lower() != "bearer":
                raise ValueError()
            if not isinstance(tokens.get("expires_in"), (int, float)) or tokens["expires_in"] <= 0:
                raise ValueError()
            return tokens
        except (ValueError, TypeError, AttributeError):
            raise ValueError("ChatGPT returned an invalid token response; sign in again") from None

    async def callback(self, params, session_alive, origin):
        async with self.lock:
            attempt = self.pending.pop(params.get("state", ""), None)
            if (not attempt or attempt["expires"] <= time.time() or not session_alive(attempt["session"])
                    or attempt["redirect_uri"] != origin + "/auth/callback"):
                raise ValueError("Sign-in expired or could not be verified. Return to AiMate and try again.")
            if params.get("error"):
                raise ValueError("ChatGPT sign-in was declined. Return to AiMate to try again.")
            account = attempt["account"]
            issued = params.get("client_id") or (account["client_id"] if account else None)
            if (not issued or not issued.startswith("oaiapp_") or
                    (account and issued != account["client_id"]) or not params.get("code")):
                raise ValueError("ChatGPT registration was incomplete. Sign in again.")
            tokens = await self.token_request({"grant_type": "authorization_code", "client_id": issued,
                "code": params["code"], "code_verifier": attempt["verifier"],
                "redirect_uri": attempt["redirect_uri"], "resource": RESOURCE})
            claims = await self.verify_identity(tokens.get("id_token", ""), issued, attempt["nonce"])
            if account and (claims["sub"], claims["iss"]) != (account["subject"], account["issuer"]):
                raise ValueError("ChatGPT returned a different account; saved credentials were not replaced")
            record = self.record()
            profile = {"client_id": issued, "subject": claims["sub"], "issuer": claims["iss"],
                       "email": claims.get("email", "ChatGPT account"), "host_id": record["host_id"]}
            self.update_tokens(profile, tokens)
            record["accounts"][issued] = profile
            record["active"] = issued
            self.save(record)
            return PERMISSION in profile["scopes"]

    @staticmethod
    def update_tokens(profile, tokens):
        for key in ("access_token", "refresh_token", "id_token"):
            if tokens.get(key):
                profile[key] = tokens[key]
        profile["scopes"] = tokens["scope"].split() if "scope" in tokens else profile.get("scopes", [])
        profile["expires_at"] = time.time() + tokens["expires_in"]

    async def access_token(self, expected_account=None):
        async with self.lock:
            record = self.record()
            if expected_account and record["active"] != expected_account:
                raise ValueError("ChatGPT account changed; start a new question")
            account = record["accounts"].get(record["active"], {})
            if not account.get("access_token") or PERMISSION not in account.get("scopes", []):
                raise ValueError("Continue with ChatGPT in Settings and enable plan usage")
            if account["expires_at"] <= time.time() + 60:
                if not account.get("refresh_token"):
                    raise ValueError("ChatGPT sign-in expired. Continue with your saved account in Settings.")
                tokens = await self.token_request({"grant_type": "refresh_token",
                    "client_id": account["client_id"], "refresh_token": account["refresh_token"], "resource": RESOURCE})
                if tokens.get("id_token"):
                    claims = await self.verify_identity(tokens["id_token"], account["client_id"])
                    if (claims["sub"], claims["iss"]) != (account["subject"], account["issuer"]):
                        raise ValueError("Refreshed ChatGPT identity did not match")
                self.update_tokens(account, tokens)
                self.save(record)
                if PERMISSION not in account["scopes"]:
                    raise ValueError("ChatGPT plan usage is no longer enabled; sign in again")
            return account["access_token"]

    async def models(self):
        token = await self.access_token()
        async with self.client() as client:
            response = await client.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + token})
        if response.status_code != 200:
            raise ValueError("ChatGPT models are unavailable for this account. Check your plan access and sign in again.")
        models = response.json().get("models", [])
        return [{"slug": m["slug"], "display_name": m.get("display_name", m["slug"])}
                for m in models if m.get("visibility") == "list" and isinstance(m.get("slug"), str)]

    async def disconnect(self):
        async with self.lock:
            record = self.record()
            account = record["accounts"].get(record["active"], {})
            revoked = not bool(account.get("refresh_token"))
            if account.get("refresh_token"):
                try:
                    async with self.client() as client:
                        discovery = await client.get(ISSUER + "/.well-known/openid-configuration")
                        discovery.raise_for_status()
                        endpoint = discovery.json().get("revocation_endpoint", "")
                        if not endpoint.startswith(ISSUER + "/"):
                            raise ValueError("Invalid revocation endpoint")
                        result = await client.post(endpoint, data={"token": account["refresh_token"],
                            "token_type_hint": "refresh_token", "client_id": account["client_id"]})
                        revoked = result.status_code == 200
                except (httpx.HTTPError, ValueError, KeyError):
                    revoked = False
            for key in ("access_token", "refresh_token", "id_token", "expires_at", "scopes"):
                account.pop(key, None)
            self.pending.clear()
            self.save(record)
            return {"message": "ChatGPT disconnected." if revoked else
                    "Disconnected locally. Remote revocation was not confirmed; disconnect AiMate in ChatGPT Settings too."}


async def response_events(connection, payload, expected_account=None):
    """Never retry inference automatically; partial output is not a completed answer."""
    if callable(getattr(connection, "response_events", None)):
        async for event in connection.response_events(payload, expected_account):
            yield event
        return
    token = await connection.access_token(expected_account)
    async with connection.client() as client:
        async with client.stream("POST", RESOURCE + "/responses", json=payload,
                                 headers={"Authorization": "Bearer " + token}) as response:
            if response.status_code != 200:
                raise ValueError("ChatGPT request refused. Check your account's plan access, model and usage limits.")
            data, size, completed = [], 0, False
            async for line in response.aiter_lines():
                status = connection.status()
                if not status["connected"] or (expected_account and status["active"] != expected_account):
                    raise ValueError("ChatGPT disconnected or switched accounts; this answer was not saved")
                size += len(line)
                if size > 4_000_000:
                    raise ValueError("ChatGPT response exceeded the local limit")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    raw = "\n".join(data)
                    data = []
                    if raw == "[DONE]":
                        continue
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind in {"error", "response.failed", "response.incomplete"}:
                        code = event.get("response", {}).get("error", {}).get("code", "")
                        if code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable"}:
                            raise ValueError("ChatGPT plan usage is unavailable or its limit was reached. Check ChatGPT Settings → Usage.")
                        raise ValueError("ChatGPT did not complete this answer. Check access and try a narrower question.")
                    if kind == "response.completed":
                        completed = True
                    yield event
            if not completed:
                raise ValueError("ChatGPT stream stopped before completion; this answer was not saved")
