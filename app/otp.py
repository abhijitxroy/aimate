"""Single-workspace authenticator login; seeds never enter project/AI settings."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode


def code_for_counter(secret, counter, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return str(number % (10 ** digits)).zfill(digits)


def matching_counter(secret, code, *, now=None, after=-1):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code.strip()):
        return None
    counter = int((time.time() if now is None else now) // 30)
    for candidate in (counter, counter - 1, counter + 1):
        if candidate > after and candidate >= 0 and hmac.compare_digest(
                code.strip(), code_for_counter(secret, candidate)):
            return candidate
    return None


class Authenticator:
    def __init__(self, store):
        self.store = store
        store.execute("CREATE TABLE IF NOT EXISTS login_otp (id INTEGER PRIMARY KEY CHECK(id=1), encrypted TEXT NOT NULL)")

    def _read(self):
        rows = self.store.rows("SELECT encrypted FROM login_otp WHERE id=1")
        return json.loads(self.store.cipher.decrypt(rows[0]["encrypted"].encode())) if rows else {}

    def _save(self, state):
        encrypted = self.store.cipher.encrypt(json.dumps(state).encode()).decode()
        self.store.execute("INSERT OR REPLACE INTO login_otp VALUES (1,?)", (encrypted,))

    def status(self):
        with self.store.lock:
            state = self._read()
            return {"enabled": bool(state.get("secret")),
                    "recovery_remaining": len(state.get("recovery", []))}

    def _consume(self, state, code):
        if not isinstance(code, str) or not state.get("secret"):
            return False
        counter = matching_counter(state["secret"], code, after=state.get("last_counter", -1))
        if counter is not None:
            state["last_counter"] = counter
            return True
        normalized = code.strip().lower().replace("-", "").replace(" ", "")
        if not re.fullmatch(r"[0-9a-f]{24}", normalized):
            return False
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        for saved in state.get("recovery", []):
            if hmac.compare_digest(digest, saved):
                state["recovery"].remove(saved)
                return True
        return False

    def verify(self, code):
        with self.store.lock:
            state = self._read()
            if not self._consume(state, code):
                return False
            self._save(state)
            return True

    def begin(self, session, verification):
        # Build the QR before changing state, so a missing dependency cannot
        # consume a recovery code or replace the pending enrollment.
        import qrcode
        import qrcode.image.svg

        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        uri = "otpauth://totp/" + quote("AiMate:Workspace", safe="") + "?" + urlencode(
            {"secret": secret, "issuer": "AiMate", "algorithm": "SHA1", "digits": 6, "period": 30})
        qr = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage,
                         box_size=6, border=4).to_string()
        image = "data:image/svg+xml;base64," + base64.b64encode(qr).decode()
        with self.store.lock:
            state = self._read()
            if state.get("secret"):
                if not self._consume(state, verification):
                    raise ValueError("Enter a fresh authenticator code or an unused recovery code.")
            elif not isinstance(verification, str) or not hmac.compare_digest(
                    verification.encode(), self.store.password.encode()):
                raise ValueError("Enter your development password to set up OTP.")
            state["pending"] = {"secret": secret, "expires": time.time() + 600,
                                "session": hashlib.sha256(session.encode()).hexdigest()}
            self._save(state)
        return {"secret": secret, "qr": image}

    def enable(self, session, code):
        with self.store.lock:
            state = self._read()
            pending = state.get("pending", {})
            if (pending.get("expires", 0) < time.time() or not hmac.compare_digest(
                    pending.get("session", ""), hashlib.sha256(session.encode()).hexdigest())):
                raise ValueError("Setup expired. Start again.")
            counter = matching_counter(pending["secret"], code)
            if counter is None:
                raise ValueError("Code did not match. Check your authenticator and device time.")
            codes = [secrets.token_hex(12) for _ in range(8)]
            self._save({"secret": pending["secret"], "last_counter": counter,
                        "recovery": [hashlib.sha256(code.encode()).hexdigest() for code in codes]})
            return ["-".join(code[i:i + 6] for i in range(0, 24, 6)) for code in codes]
