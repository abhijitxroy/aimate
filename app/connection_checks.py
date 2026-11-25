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
        ai = config.get("ai", {})
        if ai.get("analysis_model") and ai["analysis_model"] != ai.get("model"):
            for label, model in (("Standard", ai.get("model")), ("Analysis", ai["analysis_model"])):
                selected = {**config, "ai": {**ai, "model": model, "analysis_model": ""}}
                # Simple setup still uses its configured Standard model; do not revalidate an inference request.
                checked = await check_connection(service, selected, services, client_factory, chatgpt)
                report["targets"].append({"target": label + " · " + str(model),
                    "ok": checked["ok"], "status": checked["status"], "message": checked["message"],
                    "details": checked.get("details", []), "checks": []})
            passed = sum(t["ok"] for t in report["targets"])
            report.update(ok=passed == 2, status="passed" if passed == 2 else "partial" if passed else "failed",
                          counts={"passed": passed, "total": 2, "unit": "models"},
                          message=f"{passed} of 2 configured models passed access checks.")
            return report
        client = None
        try:
            ai = config.get("ai", {})
            if ai.get("provider") in {"bedrock", "bedrock-openai"}:
                report["details"] = ["Region: " + str(ai.get("region", "")),
                                     "Endpoint: Bedrock " + str(ai.get("bedrock_endpoint", "runtime")),
                                     "Requested model: " + str(ai.get("model", ""))]
                if ai.get("provider") == "bedrock-openai":
                    report["details"].append("Protocol: Bedrock OpenAI-compatible Responses API")
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
                client = await asyncio.to_thread(client_factory, config)
                response = await client.messages.create(model=model, max_tokens=16,
                                                       messages=[{"role": "user", "content": "Reply OK."}])
                report.update(ok=True, model=response.model, message="Connected. The model answered.",
                              details=["Model: " + response.model,
                                       "Reply: " + "".join(b.text for b in response.content if getattr(b, "type", "") == "text")[:160],
                                       "A small billable inference request was completed."])
        except Exception as exc:
            report["message"] = ai_error(exc)
            if config.get("ai", {}).get("provider") == "bedrock" and config["ai"].get("bedrock_mode") == "simple":
                if getattr(exc, "status_code", None) in {400, 403, 404} and not report["message"].startswith("AWS could not authenticate"):
                    report["message"] += " Open Advanced to select a model/profile and region allowed by your AWS account."
        finally:
            if client:
                await client.close()
    else:
        try:
            fields = {"github": [("url", "API base URL"), ("repos", "OWNER/REPO entries")],
                      "jira": [("url", "site URL"), ("token", "PAT / API token")],
                      "jenkins": [("url", "controller URL"), ("username", "username"),
                                  ("token", "API token")]}[service]
            configured = config.get(service, {})
            if service == "jenkins" and configured.get("access") != "all":
                fields = fields + [("jobs", "job names")]
            if service == "jira" and configured.get("access") != "all":
                fields = fields + [("projects", "project keys")]
            if service == "jira" and configured.get("auth") == "basic":
                fields = fields + [("username", "Cloud email")]
            missing = [label for key, label in fields if not configured.get(key)]
            if missing:
                raise ValueError("Add " + ", ".join(missing) + " for " + service + ", then save & check again.")
            section = services.section(service)
            targets = section.get({"github": "repos", "jira": "projects", "jenkins": "jobs"}[service], [])
            if not targets and not (service in {"jira", "jenkins"} and section.get("access") == "all"):
                raise ValueError({"github": "Add at least one repository as OWNER/REPO.",
                                  "jira": "Add at least one Jira project key.",
                                  "jenkins": "Add at least one Jenkins job name."}[service])
            if section.get("token"):
                identity_path = ("/user" if service == "github" else
                                 "/rest/api/" + section.get("api_version", "2") + "/myself" if service == "jira" else
                                 "/whoAmI/api/json")
                try:
                    identity = await services.request(service, "GET", identity_path)
                except ValueError as exc:
                    if service == "jenkins" and "HTTP 404" in str(exc):
                        raise ValueError("Jenkins API not found (HTTP 404). Open Controller & account and enter the full controller URL, including any path after the hostname.") from None
                    raise
                if service == "jenkins" and not identity.get("authenticated"):
                    raise ValueError("Jenkins did not authenticate this token. Check the username and API token.")
                name = identity.get("login") or identity.get("displayName") or identity.get("name")
                if not name:
                    raise ValueError("The service did not return an authenticated account. Check the URL and authentication type.")
                report["details"] = ["Authenticated account: " + str(name),
                                     "Only read access is tested. No changes were made."]
            else:
                report["details"] = ["Public access without a PAT. Token and write access are not verified."]
            if service == "jira" and section.get("access") == "all":
                version = section.get("api_version", "2")
                path = "/rest/api/" + version + ("/project/search" if version == "3" else "/project")
                data = await services.request(service, "GET", path, params={"maxResults": 50} if version == "3" else None)
                projects = data if isinstance(data, list) else data.get("values")
                if not isinstance(projects, list):
                    raise ValueError("Jira did not return a project list. Check the site URL and authentication method.")
                rows = [{"target": str(p.get("key", "")), "ok": True, "message": str(p.get("name", "Accessible")), "details": [], "checks": []}
                        for p in projects if isinstance(p, dict) and p.get("key")]
                report.update(ok=True, targets=rows[:15], message="Connected. " + str(len(rows)) + " accessible projects found" + (" on this page." if version == "3" else "."))
                report["details"].append("All projects and issues permitted by your Jira account are available to the assistant.")
                if len(rows) > 15 or (isinstance(data, dict) and not data.get("isLast", True)):
                    report["details"].append("Showing the first 15 projects; the assistant can " + ("fetch additional pages." if version == "3" else "list all accessible projects."))
                report["status"] = "passed"
                return report
            if service == "jenkins" and section.get("access") == "all":
                result = await services.read("jenkins", "/api/json")
                jobs = result["data"].get("jobs")
                if not isinstance(jobs, list):
                    raise ValueError("Jenkins did not return a job list. Check the controller URL and Job/Read permission.")
                rows = [{"target": str(j.get("fullName") or j.get("name", "")), "ok": True,
                         "message": "Accessible folder" if "Folder" in j.get("_class", "") else "Accessible job",
                         "details": [], "checks": []} for j in jobs if isinstance(j, dict) and j.get("name")]
                report.update(ok=True, status="passed", targets=rows[:15],
                              message=f"Connected. {len(rows)} accessible top-level jobs/folders found.")
                report["details"].append("The assistant can discover nested jobs and read builds permitted by this Jenkins account.")
                report["details"].append("Build and abort permissions are checked when a reviewed action runs.")
                return report
            limit = asyncio.Semaphore(4)

            async def read(path, params=None):
                async with limit:
                    return await services.read(service, path, params)

            async def target_check(target):
                row = {"target": target, "ok": False, "status": "failed", "checks": [], "details": []}
                try:
                    path = ("/repos/" + target if service == "github" else
                            "/rest/api/" + section.get("api_version", "2") + "/project/" + target if service == "jira" else
                            services.job_path(target) + "/api/json")
                    result = await read(path)
                    row["url"] = result["source"]
                    data = result["data"]
                    row["ok"] = True
                    row["status"] = "passed"
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
                            row["status"] = "partial"
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
            report["status"] = "passed" if report["ok"] else (
                "partial" if passed or any(t["status"] == "partial" for t in report["targets"]) else "failed")
            report["counts"] = {"passed": passed, "total": len(targets),
                                "unit": {"github": "repos", "jira": "projects", "jenkins": "jobs"}[service]}
            report["message"] = f"{passed} of {len(targets)} targets passed all read checks."
            if report["status"] == "partial" and len(targets) == 1:
                checks = report["targets"][0]["checks"]
                report["counts"] = {"passed": sum(c["ok"] for c in checks), "total": len(checks), "unit": "checks"}
                report["message"] = f"Repository accessible; {report['counts']['passed']} of {len(checks)} feature checks passed."
        except Exception as exc:
            report["message"] = failure(exc)
    if report["status"] != "partial":
        report["status"] = "passed" if report["ok"] else "failed"
    return report
