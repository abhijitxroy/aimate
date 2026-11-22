"""Read-only connection diagnostics. Never test writes or return upstream error bodies."""
import asyncio
import time

import httpx

from app.agent import ai_error

SERVICES = {"ai", "github", "jira", "jenkins"}


def failure(exc):
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "Request timed out. Check the service URL, VPN/proxy and network, then retry."
    if isinstance(exc, httpx.HTTPError):
        return "Cannot reach the service. Check its HTTPS URL, VPN/proxy and certificate configuration."
    return "Connection check failed. Check the connection fields and service availability."


async def check_connection(service, config, services, client_factory, chatgpt):
    report = {"ok": False, "status": "failed", "checked_at": time.time(), "targets": []}
    if service == "ai":
        client = None
        try:
            ai = config.get("ai", {})
            model = ai.get("model")
            if not model:
                raise ValueError("Choose an AI model before checking access.")
            if ai.get("provider") == "chatgpt":
                models = await chatgpt.models()
                found = next((m for m in models if m["slug"] == model), None)
                if not found:
                    raise ValueError("The selected model is unavailable. Sign in, select an available model and save.")
                report.update(ok=True, model=model, message="Account and model access verified.",
                              details=["Model: " + found.get("display_name", model),
                                       "Verified through the account catalog; an AI answer was not requested."])
            else:
                client = client_factory(config)
                response = await client.messages.create(model=model, max_tokens=16,
                                                       messages=[{"role": "user", "content": "Reply OK."}])
                report.update(ok=True, model=response.model, message="Connected. The model answered.",
                              details=["Model: " + response.model,
                                       "Reply: " + "".join(b.text for b in response.content if getattr(b, "type", "") == "text")[:160],
                                       "A small billable inference request was completed."])
        except Exception as exc:
            report["message"] = ai_error(exc)
        finally:
            if client:
                await client.close()
    else:
        try:
            fields = {"github": [("url", "API base URL"), ("repos", "OWNER/REPO entries")],
                      "jira": [("url", "site URL"), ("token", "PAT / API token"), ("projects", "project keys")],
                      "jenkins": [("url", "controller URL"), ("username", "username"),
                                  ("token", "API token"), ("jobs", "job names")]}[service]
            configured = config.get(service, {})
            if service == "jira" and configured.get("auth") == "basic":
                fields = fields + [("username", "Cloud email")]
            missing = [label for key, label in fields if not configured.get(key)]
            if missing:
                raise ValueError("Add " + ", ".join(missing) + " for " + service + ", then save & check again.")
            section = services.section(service)
            targets = section.get({"github": "repos", "jira": "projects", "jenkins": "jobs"}[service], [])
            if not targets:
                raise ValueError({"github": "Add at least one repository as OWNER/REPO.",
                                  "jira": "Add at least one Jira project key.",
                                  "jenkins": "Add at least one Jenkins job name."}[service])
            if section.get("token"):
                identity_path = ("/user" if service == "github" else
                                 "/rest/api/" + section.get("api_version", "2") + "/myself" if service == "jira" else
                                 "/whoAmI/api/json")
                identity = await services.request(service, "GET", identity_path)
                if service == "jenkins" and not identity.get("authenticated"):
                    raise ValueError("Jenkins did not authenticate this token. Check the username and API token.")
                name = identity.get("login") or identity.get("displayName") or identity.get("name")
                if not name:
                    raise ValueError("The service did not return an authenticated account. Check the URL and authentication type.")
                report["details"] = ["Authenticated account: " + str(name),
                                     "Only read access is tested. No changes were made."]
            else:
                report["details"] = ["Public access without a PAT. Token and write access are not verified."]
            limit = asyncio.Semaphore(4)

            async def read(path, params=None):
                async with limit:
                    return await services.read(service, path, params)

            async def target_check(target):
                row = {"target": target, "ok": False, "checks": [], "details": []}
                try:
                    path = ("/repos/" + target if service == "github" else
                            "/rest/api/" + section.get("api_version", "2") + "/project/" + target if service == "jira" else
                            services.job_path(target) + "/api/json")
                    result = await read(path)
                    row["url"] = result["source"]
                    data = result["data"]
                    row["ok"] = True
                    row["message"] = "Accessible"
                    if service == "github":
                        row["details"] = [
                            "Private repository" if data.get("private") else "Public repository",
                            "Default branch: " + str(data.get("default_branch", "not reported")),
                            "Authentication: saved PAT" if section.get("token") else "Authentication: public access (no PAT)",
                        ]
                        permissions = data.get("permissions", {})
                        row["details"].append("Repository reports push access." if permissions.get("push") else
                                              "Write access is not verified; changes are checked when confirmed.")

                        async def capability(label, suffix):
                            try:
                                await read(path + suffix, {"per_page": 1})
                                return {"name": label, "ok": True, "message": "Read access verified"}
                            except Exception as exc:
                                return {"name": label, "ok": False, "message": failure(exc)}
                        row["checks"] = await asyncio.gather(
                            capability("Code", "/contents"), capability("Issues", "/issues"),
                            capability("Pull requests", "/pulls"), capability("Actions", "/actions/runs"))
                        row["ok"] = all(c["ok"] for c in row["checks"])
                        if not row["ok"]:
                            row["message"] = "Repository connected; some features are unavailable"
                    elif service == "jira":
                        row["details"] = ["Project: " + str(data.get("name", target)),
                                          "Authentication: " + ("Data Center PAT" if section.get("auth", "bearer") == "bearer" else "Cloud email + API token"),
                                          "Project metadata is readable; issue visibility can vary by ticket."]
                    else:
                        row["details"] = ["Job: " + str(data.get("fullName", target)),
                                          "Buildable: " + str(data.get("buildable", "not reported")),
                                          "Job metadata is readable; triggering builds requires separate permissions."]
                except Exception as exc:
                    row["message"] = failure(exc)
                return row

            report["targets"] = await asyncio.gather(*(target_check(t) for t in targets))
            passed = sum(t["ok"] for t in report["targets"])
            report["ok"] = passed == len(targets)
            report["message"] = f"{passed} of {len(targets)} targets passed all read checks."
        except Exception as exc:
            report["message"] = failure(exc)
    report["status"] = "passed" if report["ok"] else "failed"
    return report
