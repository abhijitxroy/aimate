const $ = selector => document.querySelector(selector);
let csrf = "", config = {}, cid = null, controller = null, busy = false;
let demo = false;

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", "X-CSRF-Token": csrf, ...options.headers};
  const response = await fetch(path, {...options, headers, credentials: "same-origin"});
  if (response.status === 401) {
    $("#workspace").hidden = true;
    $("#loginScreen").hidden = false;
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({detail: `HTTP ${response.status}`}));
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return options.stream ? response : response.json();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function sourceBadge(name, ready) {
  const chip = element("span", `source-chip ${ready ? "" : "off"}`);
  chip.append(element("i", "dot"), document.createTextNode(name + (ready ? " configured" : " · Add")));
  return chip;
}

async function refreshState() {
  const state = await api("/api/state");
  csrf = state.csrf;
  config = state.config;
  demo = Boolean(state.demo);
  $("#demoBanner").hidden = !demo;
  $("#workspace").hidden = false;
  $("#loginScreen").hidden = true;
  $("#writeBadge").textContent = config.allow_writes ? "Changes need confirmation" : "Read mode";
  const bar = $("#sourceBar");
  bar.replaceChildren();
  for (const [key, label] of [["github", "GitHub"], ["jira", "Jira"], ["jenkins", "Jenkins"]]) {
    const publicGitHub = key === "github" && config.github?.url === "https://api.github.com" && config.github?.repos?.length;
    if (["jira", "jenkins"].includes(key) && !config[key]?.token_configured) continue;
    bar.append(sourceBadge(demo ? `${label} (sample)` : label, Boolean(config[key]?.token_configured || publicGitHub)));
  }
  bar.append(sourceBadge(demo ? "Scripted demo" : "AI", demo || Boolean(config.ai?.model && (config.ai.api_key_configured || config.ai.provider === "bedrock"))));
  const ready = config.ai?.model && (config.ai?.api_key_configured || config.ai?.provider === "bedrock") && config.github?.repos?.length;
  $("#setupHint").hidden = Boolean(demo || ready);
  $("#setupHint").textContent = "Connect AI + GitHub to start →";
  $("#setupHint").onclick = openSettings;
  const nav = $("#conversations");
  nav.replaceChildren();
  const mobileNav = $("#mobileConversations");
  mobileNav.replaceChildren();
  for (const thread of state.conversations) {
    const button = element("button", thread.id === cid ? "active" : "", thread.title);
    button.title = thread.title;
    button.onclick = () => !busy && openConversation(thread.id, thread.title);
    nav.append(button);
    const mobileButton = element("button", "", thread.title);
    mobileButton.onclick = () => {
      if (busy) return;
      $("#menuDialog").close();
      openConversation(thread.id, thread.title);
    };
    mobileNav.append(mobileButton);
  }
  return state;
}

function addMessage(role, text = "") {
  $("#welcome").hidden = true;
  const root = element("article", `message ${role}`);
  root.append(element("div", "who", role === "user" ? "YOU" : demo ? "AIMATE · SCRIPTED DEMO" : "AIMATE"));
  const body = element("div", "body", text);
  root.append(body);
  $("#messages").append(root);
  scrollMessages();
  return {root, body};
}

function scrollMessages() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

function addSource(message, url) {
  let parsed;
  try { parsed = new URL(url); } catch { return; }
  if (!["https:", "http:"].includes(parsed.protocol)) return;
  let sources = message.root.querySelector(".sources");
  if (!sources) { sources = element("div", "sources"); message.root.append(sources); }
  if ([...sources.querySelectorAll("a")].some(a => a.href === parsed.href)) return;
  const link = element("a", "", parsed.hostname + parsed.pathname);
  link.href = parsed.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  sources.append(link);
}

function drawAction(action, parent) {
  const card = element("section", "action-card");
  card.dataset.action = action.id;
  const label = action.operation.replaceAll("_", " ") + (demo ? " (simulated)" : "");
  card.append(element("h3", "", `${action.service} · ${label}`),
    element("p", "", `Status: ${action.status} · proposals expire after 30 minutes`),
    element("pre", "", JSON.stringify(action.preview, null, 2)));
  if (action.result) card.append(element("pre", "action-result", JSON.stringify(action.result, null, 2)));
  if (action.status === "unknown") {
    card.append(element("p", "", "The remote outcome is uncertain. Inspect the target before requesting this change again."));
  }
  if (action.status === "pending") {
    const buttons = element("div", "action-buttons");
    for (const decision of ["confirm", "cancel"]) {
      const button = element("button", decision === "confirm" ? "primary" : "", decision === "confirm" ? (demo ? "Confirm simulated change" : "Confirm change") : "Cancel");
      button.onclick = async () => {
        for (const b of buttons.children) b.disabled = true;
        try {
          const next = await api(`/api/actions/${action.id}/${decision}`, {method: "POST"});
          const replacement = drawAction(next);
          card.replaceWith(replacement);
          $("#activity").textContent = next.status === "completed" ? (demo ? "Simulated change completed. No external service was changed." : "Change completed. Ask a follow-up to continue.") : `Action ${next.status}.`;
        } catch (error) {
          card.append(element("p", "error", error.message));
          // A failed response can mean the operation ran. Reload its recorded state.
          if (cid) await openConversation(cid, $("#chatTitle").textContent, true).catch(() => {});
        }
      };
      buttons.append(button);
    }
    card.append(buttons);
  }
  if (parent) parent.append(card);
  return card;
}

async function openConversation(id, title = "Project conversation", allowBusy = false) {
  if (busy && !allowBusy) return;
  cid = id;
  const conversation = await api(`/api/conversations/${id}`);
  $("#messages").replaceChildren();
  $("#chatTitle").textContent = title;
  $("#welcome").hidden = Boolean(conversation.turns.length || conversation.actions.length);
  for (const turn of conversation.turns) {
    const user = turn.messages.find(m => m.role === "user" && typeof m.content === "string");
    if (user) addMessage("user", user.content);
    let bot;
    for (const msg of turn.messages) {
      if (msg.role !== "assistant" || !Array.isArray(msg.content)) continue;
      const text = msg.content.filter(b => b.type === "text").map(b => b.text).join("\n\n");
      if (text) {
        if (!bot) bot = addMessage("assistant", text);
        else bot.body.textContent += "\n\n" + text;
      }
    }
    for (const msg of turn.messages) {
      if (!Array.isArray(msg.content)) continue;
      for (const block of msg.content) {
        if (block.type === "tool_result") {
          try {
            const result = JSON.parse(block.content);
            if (result.source && bot) addSource(bot, result.source);
          } catch { /* plain text error / truncated result */ }
        }
      }
    }
  }
  if (conversation.actions.length) {
    const actionGroup = element("div", "message");
    for (const action of conversation.actions) drawAction(action, actionGroup);
    $("#messages").append(actionGroup);
  }
  await refreshState();
  scrollMessages();
}

async function ask(question) {
  if (busy || !question.trim()) return;
  if (!config.ai?.model || (!demo && !config.ai?.api_key_configured && config.ai?.provider !== "bedrock")) {
    openSettings(); $("#settingsStatus").textContent = "Add your AI credentials and model ID to start."; return;
  }
  busy = true;
  $("#send").disabled = true;
  $("#stop").hidden = false;
  controller = new AbortController();
  let bot;
  try {
    if (!cid) cid = (await api("/api/conversations", {method: "POST"})).id;
    addMessage("user", question);
    bot = addMessage("assistant");
    $("#question").value = "";
    $("#activity").textContent = "Reading your question…";
    const response = await api("/api/chat", {
      method: "POST", body: JSON.stringify({conversation: cid, question}),
      signal: controller.signal, stream: true
    });
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const packet = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        const line = packet.split("\n").find(l => l.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.event === "text") bot.body.textContent += event.delta;
        if (event.event === "source") addSource(bot, event.url);
        if (event.event === "tool") {
          $("#activity").textContent = event.name === "propose_action" ? "Preparing a change for review…" : `Reading ${event.input.service}: ${event.input.path}…`;
          let tools = bot.root.querySelector(".tool-list");
          if (!tools) { tools = element("div", "tool-list"); bot.root.append(tools); }
          tools.append(element("div", "", `↳ ${event.name} · ${event.input.service || ""}`));
        }
        if (event.event === "tool_done" && !event.ok) {
          bot.root.append(element("p", "error", event.message));
        }
        if (event.event === "action") drawAction(event.action, bot.root);
        if (event.event === "error") throw new Error(event.message);
        if (event.event === "done") {
          $("#activity").textContent = `Answer complete · ${event.usage.input_tokens.toLocaleString()} input / ${event.usage.output_tokens.toLocaleString()} output tokens`;
        }
        scrollMessages();
      }
    }
    await refreshState();
  } catch (error) {
    $("#activity").textContent = error.name === "AbortError" ? "Stopped. An incomplete answer is not saved." : error.message;
    if (bot && error.name !== "AbortError") bot.root.append(element("p", "error", error.message));
  } finally {
    busy = false; $("#send").disabled = false; $("#stop").hidden = true; controller = null;
  }
}

function openSettings() {
  const form = $("#settingsForm");
  for (const input of form.elements) input.disabled = demo;
  form.reset();
  for (const input of form.elements) {
    if (!input.name) continue;
    const [section, key] = input.name.split(".");
    if (input.name === "allow_writes") { input.checked = Boolean(config.allow_writes); continue; }
    if (key === "token" || key === "api_key") {
      input.value = "";
      input.placeholder = config[section]?.[key + "_configured"] ? "Saved · leave blank to keep" : "Enter your token/key";
      continue;
    }
    if (key === "clear_token") { input.checked = false; continue; }
    const value = config[section]?.[key];
    if (value !== undefined) input.value = Array.isArray(value) ? value.join("\n") : value;
  }
  if (!form.elements["github.url"].value) form.elements["github.url"].value = "https://api.github.com";
  $("#settingsStatus").textContent = demo ? "Fixed fictional connections. Restart in live mode to configure real services." : "";
  $("#settingsDialog").showModal();
}

$("#loginForm").onsubmit = async event => {
  event.preventDefault();
  try {
    const data = await api("/api/login", {method: "POST", body: JSON.stringify({password: $("#password").value})});
    csrf = data.csrf;
    $("#password").value = "";
    $("#loginError").textContent = "";
    await refreshState();
  } catch (error) { $("#loginError").textContent = error.message; }
};
$("#demoLogin").onclick = async () => {
  try {
    const data = await api("/api/demo/login", {method: "POST"});
    csrf = data.csrf;
    await refreshState();
  } catch (error) { $("#loginError").textContent = error.message; }
};
$("#chatForm").onsubmit = event => { event.preventDefault(); ask($("#question").value); };
$("#question").onkeydown = event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask($("#question").value); }
};
$("#stop").onclick = () => controller?.abort();
$("#newChat").onclick = async () => {
  if (busy) return;
  cid = null; $("#messages").replaceChildren(); $("#welcome").hidden = false;
  $("#chatTitle").textContent = "Ask your project"; $("#activity").textContent = "";
  await refreshState();
};
$("#openSettings").onclick = openSettings;
$("#headerSettings").onclick = openSettings;
$("#mobileMenu").onclick = () => $("#menuDialog").showModal();
document.querySelectorAll("[data-menu-action]").forEach(button => {
  button.onclick = () => {
    $("#menuDialog").close();
    document.getElementById(button.dataset.menuAction).click();
  };
});
$("#sourceBar").onclick = openSettings;
$("#logout").onclick = async () => {
  controller?.abort();
  await api("/api/logout", {method: "POST"});
  cid = null; csrf = ""; config = {};
  $("#messages").replaceChildren(); $("#welcome").hidden = false;
  $("#workspace").hidden = true; $("#loginScreen").hidden = false;
};
document.querySelectorAll("[data-question]").forEach(button => {
  button.onclick = () => ask(button.dataset.question);
});
document.querySelectorAll("[data-close]").forEach(button => {
  button.onclick = () => document.getElementById(button.dataset.close).close();
});
$("#settingsForm").onsubmit = async event => {
  event.preventDefault();
  const data = {ai: {}, github: {}, jira: {}, jenkins: {}};
  for (const input of event.target.elements) {
    if (!input.name) continue;
    if (input.name === "allow_writes") { data.allow_writes = input.checked; continue; }
    const [section, key] = input.name.split(".");
    let value = input.type === "checkbox" ? input.checked : input.value.trim();
    if (["repos", "projects", "jobs"].includes(key)) value = value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    data[section][key] = value;
  }
  try {
    await api("/api/settings", {method: "PUT", body: JSON.stringify(data)});
    await refreshState();
    for (const name of ["ai", "github", "jira", "jenkins"]) {
      event.target.elements[`${name}.${name === "ai" ? "api_key" : "token"}`].value = "";
      $(`#test-${name}`).textContent = "";
    }
    $("#settingsStatus").textContent = "Saved. Test each connection, then close to start.";
  } catch (error) { $("#settingsStatus").textContent = error.message; }
};
document.querySelectorAll("[data-test]").forEach(button => {
  button.onclick = async () => {
    const target = $(`#test-${button.dataset.test}`);
    button.disabled = true; target.textContent = "Checking…";
    try {
      const result = await api(`/api/connections/${button.dataset.test}/test`, {method: "POST"});
      target.textContent = result.targets
        ? result.targets.map(t => `${t.ok ? "✓" : "✕"} ${t.target}${t.message ? ": " + t.message : ""}`).join("\n")
        : "✓ " + result.message;
    } catch (error) { target.textContent = error.message; }
    finally { button.disabled = false; }
  };
});
$("#openAudit").onclick = async () => {
  $("#auditDialog").showModal();
  $("#auditContent").textContent = "Loading…";
  try {
    const data = await api("/api/audit");
    $("#auditContent").textContent = data.entries.length ? JSON.stringify(data.entries, null, 2) : "No confirmed actions yet.";
  } catch (error) { $("#auditContent").textContent = error.message; }
};
async function initialize() {
  const mode = await api("/api/mode");
  demo = Boolean(mode.demo);
  $("#demoLogin").hidden = !demo;
  $("#demoLoginHint").hidden = !demo;
  $("#loginForm").hidden = demo;
  $("#localPasswordHint").hidden = demo || Boolean(mode.hosted);
  await refreshState().catch(() => {});
}
initialize().catch(error => { $("#loginError").textContent = error.message; });
