"""Session-only vault reauthentication; locks survive neither logout nor restart."""
import hmac
import time

DURATION = 300


def unlocked(session):
    return session.get("role") == "admin" and session.get("vault_until", 0) > time.monotonic()


def status(session, authenticator):
    return {"unlocked": unlocked(session),
            "seconds_remaining": max(0, int(session.get("vault_until", 0) - time.monotonic())),
            "otp": authenticator.status()["enabled"], "duration": DURATION}


def lock(session):
    session.pop("vault_until", None)


def unlock(session, verification, authenticator, password):
    now = time.monotonic()
    recent = [stamp for stamp in session.get("vault_attempts", []) if now - stamp < 60]
    if len(recent) >= 5:
        raise ValueError("Too many unlock attempts. Wait one minute.")
    session["vault_attempts"] = recent + [now]
    valid = isinstance(verification, str) and (
        authenticator.verify(verification) if authenticator.status()["enabled"]
        else hmac.compare_digest(verification.encode(), password.encode()))
    if not valid:
        raise ValueError("Vault remains locked. Use your workspace password or a fresh authenticator code.")
    session["vault_attempts"] = []
    session["vault_until"] = now + DURATION
    return status(session, authenticator)
