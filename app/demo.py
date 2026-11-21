"""Offline showcase: fictional APIs and scripted responses, never a real LLM."""
import base64
import copy
import json
import re
from pathlib import Path

import httpx

from app.agent import propose
from app.connectors import Services, scrub


def demo_config():
    return {
        "allow_writes": True,
        "ai": {"provider": "demo", "model": "scripted-offline"},
        "github": {"url": "https://github.demo.invalid", "token": "demo-placeholder",
                   "repos": ["demo/sample-service"]},
        "jira": {"url": "https://jira.demo.invalid", "token": "demo-placeholder",
                 "auth": "bearer", "api_version": "2", "projects": ["DEMO"]},
        "jenkins": {"url": "https://jenkins.demo.invalid", "token": "demo-placeholder",
                    "username": "demo", "jobs": ["demo/build"]},
    }


class DemoBackend:
    def __init__(self):
        fixture = Path(__file__).resolve().parents[1] / "demo-data" / "project.json"
        self.data = json.loads(fixture.read_text(encoding="utf-8"))
        self.comments = []
        self.github_issues = []
        self.queued = []
        self.transport = httpx.MockTransport(self.respond)

    def services(self, config):
        # Reuse the real scope checks and request planning with an in-memory transport.
        return Services(config, transport=self.transport)

    def respond(self, request):
        host, path, method = request.url.host, request.url.path, request.method
        data = self.data
        result = None
        status = 200
        if host == "github.demo.invalid":
            root = "/repos/demo/sample-service"
            if method == "GET":
                if path == root:
                    result = data["repository"]
                elif path == root + "/pulls":
                    result = data["pulls"]
                elif path == root + "/issues":
                    result = self.github_issues
                elif path.startswith(root + "/contents/"):
                    filename = path.removeprefix(root + "/contents/")
                    text = {"README.md": data["readme"], "requirements.txt": data["requirements"]}.get(filename)
                    if text is not None:
                        result = {"name": filename, "encoding": "base64",
                                  "content": base64.b64encode(text.encode()).decode()}
            elif method == "POST" and path == root + "/issues":
                body = json.loads(request.content)
                result = {"number": len(self.github_issues) + 1, "state": "open", **body, "simulated": True}
                self.github_issues.append(result)
                status = 201
        elif host == "jira.demo.invalid":
            root = "/rest/api/2"
            if method == "GET":
                if path == root + "/project/DEMO":
                    result = {"key": "DEMO", "name": "Fictional demo project"}
                elif path == root + "/search":
                    result = {"issues": [data["issue"]], "total": 1, "startAt": 0, "maxResults": 50}
                elif path == root + "/issue/DEMO-123":
                    result = data["issue"]
                elif path == root + "/issue/DEMO-123/comment":
                    result = {"comments": self.comments, "total": len(self.comments)}
            elif method == "POST" and path == root + "/issue/DEMO-123/comment":
                result = {"id": str(len(self.comments) + 1), **json.loads(request.content), "simulated": True}
                self.comments.append(result)
                status = 201
        elif host == "jenkins.demo.invalid":
            root = "/job/demo/job/build"
            if method == "GET":
                if path == "/crumbIssuer/api/json":
                    result = {"crumbRequestField": "Jenkins-Crumb", "crumb": "fictional-crumb"}
                elif path == root + "/api/json":
                    result = {"name": "build", "lastCompletedBuild": data["build"],
                              "builds": [data["build"]], "simulatedQueue": self.queued}
                elif path in {root + "/42/api/json", root + "/lastCompletedBuild/api/json"}:
                    result = data["build"]
                elif path == root + "/42/consoleText":
                    return httpx.Response(200, text=data["console"])
            elif method == "POST" and path == root + "/build":
                result = {"queued": len(self.queued) + 1, "simulated": True}
                self.queued.append(result)
                status = 201
        if result is None:
            return httpx.Response(404, json={"message": "Unsupported demo endpoint"})
        return httpx.Response(status, json=copy.deepcopy(result))


async def run_demo_turn(store, cid, question, *, backend, **kwargs):
    """Supported scenarios are explicit; this is not general AI reasoning."""
    config = store.config()
    question = scrub(question, config)
    services = backend.services(config)
    q = question.lower()
    want_comment = "comment" in q and bool(re.search(r"\b(propose|post|add|write|prepare)\b", q))
    reads = []
    action = None
    preface = "DEMO — fictional data and scripted response; no AI provider or live service was called.\n\n"
    summary = ("Build #42 failed before a checkout test could send its request. The log reports "
               "`Client.__init__() got an unexpected keyword argument 'app'`. "
               "The sample requirements pair Starlette 0.36.3 with httpx 0.28.1. "
               "A compatible dependency set is the next change to investigate and test; "
               "this demo has not executed a fix or tests. Jira DEMO-123 and PR #7 refer to that upgrade.")
    if want_comment or "investigat" in q or "fail" in q or "build" in q:
        reads = [("jenkins", "/job/demo/job/build/42/api/json", None),
                 ("jenkins", "/job/demo/job/build/42/consoleText", None),
                 ("github", "/repos/demo/sample-service/contents/requirements.txt", None),
                 ("jira", "/rest/api/2/issue/DEMO-123", None),
                 ("github", "/repos/demo/sample-service/pulls", None)]
        answer = summary
        if want_comment:
            action = {"service": "jira", "operation": "comment_issue",
                      "payload": {"issue": "DEMO-123", "body": summary},
                      "reason": "Record the fictional build evidence in the demo issue"}
        elif "trigger" in q or "rerun" in q:
            action = {"service": "jenkins", "operation": "build_job",
                      "payload": {"job": "demo/build"},
                      "reason": "Demonstrate a simulated build request"}
    elif "architecture" in q or "readme" in q:
        reads = [("github", "/repos/demo/sample-service", None),
                 ("github", "/repos/demo/sample-service/contents/README.md", None)]
        answer = ("The fictional sample-service is a FastAPI order API with POST /orders and GET /health. "
                  "Its tests use Starlette TestClient; Jenkins runs install, test and package stages. "
                  "Only the sample README and metadata were inspected.")
    elif "create" in q and "issue" in q:
        reads = [("github", "/repos/demo/sample-service", None)]
        answer = "I prepared a sample GitHub issue. Confirming it creates an in-memory demo issue only."
        action = {"service": "github", "operation": "create_issue",
                  "payload": {"repo": "demo/sample-service", "title": "Review checkout dependency compatibility",
                              "body": "Fictional demo task: investigate DEMO-123 and build #42."},
                  "reason": "Demonstrate issue creation with a confirmation card"}
    elif any(word in q for word in ("issue", "attention", "pull", "comment")):
        reads = [("jira", "/rest/api/2/search", {"jql": "status != Done"}),
                 ("jira", "/rest/api/2/issue/DEMO-123/comment", None),
                 ("github", "/repos/demo/sample-service/pulls", None),
                 ("github", "/repos/demo/sample-service/issues", None)]
        answer = ("DEMO-123 needs attention: checkout tests fail after an HTTP client upgrade. "
                  "Open PR #7 contains the upgrade. "
                  f"There are {len(backend.comments)} simulated Jira comments and "
                  f"{len(backend.github_issues)} simulated GitHub issues in this session.")
    else:
        answer = ("Try: “Why did the build fail?”, “Explain the sample repository architecture”, "
                  "“Propose a Jira comment with the failure evidence”, “Create a sample GitHub issue”, "
                  "or “Trigger the demo build”. Other questions require live mode with an AI provider.")
    messages = [{"role": "user", "content": question}]
    sources = []
    for index, (service, path, params) in enumerate(reads):
        args = {"service": service, "path": path, "params": params or {}}
        yield {"event": "tool", "name": "api_read", "input": args}
        result = await services.read(service, path, params)
        sources.append(result["source"])
        messages.extend([
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"demo-{index}",
                                              "name": "api_read", "input": args}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"demo-{index}",
                                         "content": json.dumps(result)}]},
        ])
        yield {"event": "source", "url": result["source"]}
        yield {"event": "tool_done", "name": "api_read", "ok": True}
    if action:
        card = await propose(store, config, services, cid, action)
        yield {"event": "action", "action": card}
        answer += "\n\nReview the proposal card. Nothing has changed until you confirm; the result will be simulated."
    answer = preface + answer
    if sources:
        answer += "\n\nFictional source identifiers (not live websites):\n" + "\n".join(sources)
    for offset in range(0, len(answer), 100):
        yield {"event": "text", "delta": answer[offset:offset + 100]}
    messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
    store.save_turn(cid, messages)
    store.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'", (question[:100], cid))
    yield {"event": "done", "usage": {"input_tokens": 0, "output_tokens": 0}, "simulated": True}
