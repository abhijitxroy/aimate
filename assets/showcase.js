"use strict";
// Browser-only sample: never calls an AI provider or project service.
const conversation = document.querySelector("#conversation");
const questionInput = document.querySelector("#demoQuestion");
const statusLine = document.querySelector("#demoStatus");
const sampleState = { comments: [], issues: [], builds: [] };
let fixture;
let fixturePromise;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function loadFixture() {
  if (!fixturePromise) {
    fixturePromise = fetch("demo-data/project.json", { credentials: "omit" })
      .then(response => {
        if (!response.ok) throw new Error("Sample unavailable");
        return response.json();
      })
      .then(data => { fixture = data; return data; })
      .catch(error => { fixturePromise = undefined; throw error; });
  }
  return fixturePromise;
}

function message(role, text) {
  document.querySelector("#demoWelcome")?.remove();
  const block = element("div", `message ${role}`);
  block.append(element("p", "message-label", role === "user" ? "YOU" : "AIMATE · SCRIPTED DEMO"));
  block.append(element("div", "message-body", text));
  conversation.append(block);
  return block;
}

function evidence(block, items) {
  const group = element("div", "evidence");
  for (const [label, value] of items) {
    const detail = element("details");
    detail.append(element("summary", "", label));
    detail.append(element("pre", "", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
    group.append(detail);
  }
  block.append(group);
}

function proposal(block, title, body, payload, apply) {
  const card = element("div", "action-card");
  const heading = element("div", "action-heading");
  const state = element("span", "action-state", "Awaiting review");
  heading.append(element("span", "", title), state);
  card.append(heading, element("p", "", body));
  const details = element("details");
  details.append(element("summary", "", "See the sample request"));
  details.append(element("pre", "", JSON.stringify(payload, null, 2)));
  card.append(details);
  const buttons = element("div", "action-buttons");
  const confirm = element("button", "confirm", "Confirm simulated change");
  const cancel = element("button", "", "Cancel");
  confirm.type = cancel.type = "button";
  let settled = false;
  function settle(accepted) {
    if (settled) return;
    settled = true;
    if (accepted) apply();
    state.textContent = accepted ? "Completed" : "Cancelled";
    buttons.remove();
    card.append(element("div", "action-result", accepted
      ? "Simulated change complete. No external service was changed."
      : "Cancelled. Nothing changed."));
    statusLine.textContent = accepted ? "Sample state updated for this visit." : "Proposal cancelled.";
  }
  confirm.addEventListener("click", () => settle(true));
  cancel.addEventListener("click", () => settle(false));
  buttons.append(confirm, cancel);
  card.append(buttons);
  block.append(card);
}

async function ask(question) {
  question = question.trim().slice(0, 500);
  if (!question) return;
  questionInput.value = "";
  message("user", question);
  try {
    await loadFixture();
    const q = question.toLowerCase();
    const wantsComment = /\b(comment|draft)\b/.test(q) && /\b(propose|draft|post|add|write|prepare)\b/.test(q);
    const wantsBuild = /\b(trigger|rerun|queue)\b/.test(q) && q.includes("build");
    const diagnosis = `Build #${fixture.build.number} failed in the test stage. The log reports:\n\nClient.__init__() got an unexpected keyword argument 'app'\n\nThe sample pairs Starlette 0.36.3 with httpx 0.28.1. Investigate a compatible dependency set, then rerun the tests. DEMO-123 and PR #7 track the same upgrade.`;
    let block;
    if (wantsBuild) {
      block = message("assistant", "Review this sample build request. Confirming adds it to the demo queue only.");
      proposal(block, "Queue a sample build", "Jenkins · demo/build", {
        service: "jenkins", method: "POST", path: "/job/demo/job/build/build"
      }, () => sampleState.builds.push({ job: "demo/build", simulated: true }));
    } else if (wantsComment || /\b(fail|failed|failure|investigate|log)\b/.test(q)) {
      block = message("assistant", diagnosis);
      evidence(block, [["Jenkins · build #42", fixture.console], ["GitHub · requirements", fixture.requirements],
        ["Jira · DEMO-123", fixture.issue], ["GitHub · PR #7", fixture.pulls[0]]]);
      if (wantsComment) {
        proposal(block, "Add a sample Jira comment", diagnosis, {
          service: "jira", method: "POST", path: "/rest/api/2/issue/DEMO-123/comment", body: { body: diagnosis }
        }, () => sampleState.comments.push({ body: diagnosis, simulated: true }));
      }
    } else if (/\b(create|open|add)\b/.test(q) && q.includes("issue")) {
      block = message("assistant", "Here’s a sample issue to capture the follow-up. Review it before confirming.");
      const payload = { title: "Review checkout dependency compatibility", body: "Investigate DEMO-123 and the dependency mismatch in build #42." };
      proposal(block, "Create a sample GitHub issue", `${payload.title}\n${payload.body}`, {
        service: "github", method: "POST", path: "/repos/demo/sample-service/issues", body: payload
      }, () => sampleState.issues.push({ ...payload, simulated: true }));
    } else if (/\b(architecture|readme|explain)\b/.test(q)) {
      block = message("assistant", "The fictional sample-service is a FastAPI order API.\n\nRoutes: POST /orders and GET /health.\nTests: Starlette TestClient.\nPipeline: install → test → package.\n\nThis summary comes from the sample README and repository metadata.");
      evidence(block, [["GitHub · README", fixture.readme], ["GitHub · repository", fixture.repository]]);
    } else if (/\b(issue|issues|attention|pull|comments|queue|status)\b/.test(q)) {
      block = message("assistant", `One issue needs attention: DEMO-123 — checkout tests fail after the HTTP client upgrade. Open PR #7 contains the related change.\n\nChanges during this visit:\n${sampleState.comments.length} simulated Jira comments\n${sampleState.issues.length} simulated GitHub issues\n${sampleState.builds.length} simulated build requests`);
      evidence(block, [["Jira · DEMO-123", fixture.issue], ["GitHub · PR #7", fixture.pulls[0]]]);
    } else {
      block = message("assistant", "This demo supports a few sample workflows. Try a question below, “Explain the architecture”, “Create a GitHub issue” or “Trigger the demo build”.\n\nFor general questions about your own project, run the local app and connect an AI provider.");
    }
    statusLine.textContent = "Scripted sample response. No AI or external service was called.";
  } catch {
    message("assistant", "The sample data couldn’t load. Check your connection and try again.");
    statusLine.textContent = "Sample data unavailable.";
  }
  conversation.scrollTop = conversation.scrollHeight;
}

document.querySelector("#demoForm").addEventListener("submit", event => {
  event.preventDefault();
  ask(questionInput.value);
});
questionInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    ask(questionInput.value);
  }
});
for (const button of document.querySelectorAll("[data-question]")) {
  button.addEventListener("click", () => ask(button.dataset.question));
}
document.querySelector("#resetDemo").addEventListener("click", () => {
  sampleState.comments.length = sampleState.issues.length = sampleState.builds.length = 0;
  conversation.replaceChildren();
  message("assistant", "Fresh start. Ask about the sample project or choose a question below.");
  questionInput.value = "";
  statusLine.textContent = "Demo reset. All simulated changes cleared.";
});
