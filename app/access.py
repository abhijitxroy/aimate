"""Server-enforced workspace roles and revocable, high-entropy access codes."""
import hashlib
import secrets
import time
import base64
from urllib.parse import quote, urlencode

ROLES = {"admin", "developer", "viewer", "reviewer"}
ADMIN_OPERATIONS = {"delete_file", "delete_issue", "merge_pull_request", "abort_build"}
DEVELOPER_OPERATIONS = {"create_issue","comment_issue","update_issue","create_branch",
                        "write_file","create_pull_request","transition_issue","build_job"}


def permits_operation(role, operation):
    return role == "admin" or (role == "developer" and operation in DEVELOPER_OPERATIONS)


def capabilities(role, config):
    return {"role": role, "configure": role == "admin",
            "configure_connections": True,
            "write": role in {"admin", "developer"} and bool(config.get("allow_writes")),
            "manage_records": True,
            "audit": role in {"admin", "developer"}}


def issue(store, body):
    role, name = body.get("role"), body.get("name", "")
    if role not in {"developer", "viewer", "reviewer"} or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Choose Developer, Viewer or Reviewer and a name.")
    code, ident = secrets.token_urlsafe(32), secrets.token_hex(16)
    expiry = time.time() + 30 * 86400
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    uri = "otpauth://totp/" + quote("AiMate:" + name.strip(),safe="") + "?" + urlencode(
        {"secret":secret,"issuer":"AiMate","algorithm":"SHA1","digits":6,"period":30})
    import qrcode
    import qrcode.image.svg
    qr = qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage,box_size=6,border=4).to_string()
    store.execute("INSERT INTO access_grants VALUES (?,?,?,?,?,?)",
                  (ident, name.strip(), role, hashlib.sha256(code.encode()).hexdigest(), expiry, 0))
    store.execute("INSERT INTO access_grant_otp VALUES (?,?,?)",
                  (ident,store.cipher.encrypt(secret.encode()).decode(),-1))
    store.execute("INSERT INTO access_audit (grant_id,operation,after_role,created) VALUES (?,?,?,?)",
                  (ident,"created",role,time.time()))
    return {"id": ident, "code": code, "expires": expiry, "role": role,
            "authenticator_secret":secret,"qr":"data:image/svg+xml;base64,"+base64.b64encode(qr).decode()}


def verify_otp(store, ident, code):
    from app.otp import matching_counter
    with store.lock:
        rows=store.rows("SELECT encrypted,last_counter FROM access_grant_otp WHERE id=?",(ident,))
        if not rows:
            return False
        secret=store.cipher.decrypt(rows[0]["encrypted"].encode()).decode()
        counter=matching_counter(secret,code,after=rows[0]["last_counter"])
        if counter is None:
            return False
        store.execute("UPDATE access_grant_otp SET last_counter=? WHERE id=?",(counter,ident))
        return True


def change_role(store, ident, role):
    if role not in {"developer","viewer","reviewer"}:
        raise ValueError("Choose Developer, Viewer or Reviewer. Owner administration cannot be self-assigned.")
    rows=store.rows("SELECT role,revoked FROM access_grants WHERE id=?",(ident,))
    if not rows or rows[0]["revoked"]:
        raise ValueError("Active user access was not found.")
    store.execute("UPDATE access_grants SET role=? WHERE id=?",(role,ident))
    store.execute("INSERT INTO access_audit (grant_id,operation,before_role,after_role,created) VALUES (?,?,?,?,?)",
                  (ident,"role_changed",rows[0]["role"],role,time.time()))


def verify(store, role, code):
    if role not in {"developer", "viewer", "reviewer"} or not isinstance(code, str) or not 20 <= len(code) <= 100:
        return None
    rows = store.rows("SELECT id,name,role FROM access_grants WHERE digest=? AND role=? AND revoked=0 AND expires>?",
                      (hashlib.sha256(code.encode()).hexdigest(), role, time.time()))
    return rows[0] if rows else None


def authorize(role, method, path):
    if role == "admin":
        return
    # Personal connection settings are available to every account. The global
    # execution switch and identity management remain administrator-only.
    admin_paths = ("/api/settings/changes", "/api/access/grants", "/api/auth/otp", "/api/vault")
    if any(path == prefix or path.startswith(prefix + "/") for prefix in admin_paths):
        raise PermissionError("Administrator access is required.")
    if path == "/api/audit" and role not in {"developer"}:
        raise PermissionError("Audit log requires Developer or Administrator access.")
    if role in {"viewer", "reviewer"} and method not in {"GET", "HEAD"}:
        permitted = {"/api/chat", "/api/conversations", "/api/logout", "/api/connections/sync",
                     "/api/attachments/pdf", "/api/feedback", "/api/settings",
                     "/api/chatgpt/start", "/api/chatgpt/disconnect", "/api/usage/rates"}
        personal_records = any(path == prefix or path.startswith(prefix + "/") for prefix in
                               ("/api/conversations", "/api/groups", "/api/knowledge", "/api/todos"))
        connections = path.startswith("/api/settings/") or (
            path.startswith("/api/connections/") and path.endswith("/test"))
        private_delete = method == "DELETE" and path.startswith("/api/conversations/private-")
        if path not in permitted and not personal_records and not connections and not private_delete:
            raise PermissionError("This account can read and ask questions; changes are disabled.")
