"""Recheck live account authority throughout long-running AI/tool requests."""
import time


def bind_factory(factory, check):
    def create(config):
        if check:
            check()
        services = factory(config)
        if hasattr(services, "access_check"):
            services.access_check = check
        return services
    return create


def lease(owner, sessions, session):
    token, role, grant = session["token"], session.get("role", "admin"), session.get("grant")

    def check():
        if sessions.get(token) is not session or time.time() - session["created"] >= 12 * 3600:
            raise ValueError("Session ended. Sign in again before continuing.")
        if grant:
            rows = owner.rows("SELECT role,revoked,expires FROM access_grants WHERE id=?", (grant,))
            if not rows or rows[0]["revoked"] or rows[0]["expires"] <= time.time():
                raise ValueError("Access expired or was revoked. This request has stopped.")
            if rows[0]["role"] != role:
                raise ValueError("Your role changed. Refresh and ask again with your current permissions.")
    return check
