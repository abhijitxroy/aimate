const $ = selector => document.querySelector(selector);
let csrf = "", config = {}, cid = null, controller = null, busy = false;
let demo = false;
let chatgpt = {}, modelLoad = 0;
let activeSettings = "ai", checkingConnection = false;
let connectionReports = {};
const dirtyConnections = new Set();
const aiSecretFields = ["api_key", "aws_access_key", "aws_secret_key", "aws_session_token"];

function aiReady() {
  return Boolean(config.ai?.model && (config.ai.provider === "chatgpt"
    ? chatgpt.plan_enabled : config.ai.provider === "bedrock"
      ? config.ai.region && (config.ai.bedrock_auth === "iam" || config.ai.api_key_configured)
      : config.ai.api_key_configured));
}

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

function sourceBadge(name, service) {
  const report = connectionReports[service] || {};
  const status = demo ? "simulated" : report.status || "unchecked";
  const chip = element("span", "source-chip");
  chip.dataset.state = status;
  const dot = element("i", "connection-dot"); dot.dataset.state = status;
  chip.append(dot, document.createTextNode(name + " · " + (demo ? "Sample" : status === "passed" ? "Connected" : status === "failed" ? "Failed" : "Not checked")));
  return chip;
}

async function refreshState() {
  const state = await api("/api/state");
  csrf = state.csrf;
  config = state.config;
  demo = Boolean(state.demo);
  chatgpt = state.chatgpt || {};
  connectionReports = state.connection_checks || {};
  $("#demoBanner").hidden = !demo;
  $("#workspace").hidden = false;
  $("#loginScreen").hidden = true;
  $("#writeBadge").textContent = config.allow_writes ? "Changes need confirmation" : "Read mode";
  const bar = $("#sourceBar");
  bar.replaceChildren();
  for (const [key, label] of [["github", "GitHub"], ["jira", "Jira"], ["jenkins", "Jenkins"]]) {
    const publicGitHub = key === "github" && config.github?.url === "https://api.github.com" && config.github?.repos?.length;
    if (["jira", "jenkins"].includes(key) && !config[key]?.token_configured) continue;
    bar.append(sourceBadge(label, key));
  }
  bar.append(sourceBadge(demo ? "Scripted demo" : config.ai?.provider === "chatgpt" ? "ChatGPT" : config.ai?.provider === "bedrock" ? "Claude · Bedrock" : "Claude", "ai"));
  const ready = aiReady() && (config.github?.repos?.length || (config.jira?.projects?.length || (config.jira?.access === "all" && config.jira?.token_configured)) || config.jenkins?.jobs?.length);
  $("#setupHint").hidden = Boolean(demo || ready);
  $("#setupHint").textContent = "Connect AI + your project sources →";
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
  const body = element("div", "body");
  if (role === "assistant") renderAnswer(body, text);
  else body.textContent = text;
  root.append(body);
  $("#messages").append(root);
  scrollMessages();
  return {root, body, text, reads: 0};
}

function scrollMessages() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

function addSource(message, url) {
  let parsed;
  try { parsed = new URL(url); } catch { return; }
  if (!["https:", "http:"].includes(parsed.protocol)) return;
  const evidence = evidencePanel(message);
  let sources = evidence.querySelector(".sources");
  if (!sources) { sources = element("div", "sources"); evidence.append(sources); }
  if ([...sources.querySelectorAll("a")].some(a => a.href === parsed.href)) return;
  const link = element("a", "", parsed.pathname.split("/").filter(Boolean).slice(-2).join("/") || parsed.hostname);
  link.title = parsed.href;
  link.href = parsed.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  sources.append(link);
  updateEvidence(message);
}

function evidencePanel(message) {
  let panel = message.root.querySelector(".evidence");
  if (!panel) {
    panel = element("details", "evidence");
    panel.append(element("summary", "", "Sources & activity"));
    message.root.append(panel);
  }
  return panel;
}

function updateEvidence(message) {
  const panel = evidencePanel(message);
  const sources = panel.querySelectorAll(".sources a").length;
  panel.querySelector("summary").textContent = [
    sources ? `${sources} source${sources === 1 ? "" : "s"}` : "Activity",
    message.reads ? `${message.reads} step${message.reads === 1 ? "" : "s"}` : ""
  ].filter(Boolean).join(" · ");
}

function addTool(message, name, input = {}) {
  const panel = evidencePanel(message);
  let tools = panel.querySelector(".tool-list");
  if (!tools) { tools = element("div", "tool-list"); panel.append(tools); }
  const description = name === "propose_action" ? "Prepare change" : "Read";
  tools.append(element("div", "", `${description} · ${input.service || name}${input.path ? " · " + input.path : ""}`));
  message.reads++;
  updateEvidence(message);
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
        else { bot.text += "\n\n" + text; renderAnswer(bot.body, bot.text); }
      }
    }
    for (const msg of turn.messages) {
      if (!Array.isArray(msg.content)) continue;
      for (const block of msg.content) {
        if (block.type === "tool_use" && bot) addTool(bot, block.name, block.input);
        if (block.type === "responses" && bot) {
          for (const item of block.items || []) {
            if (item.type !== "function_call") continue;
            try { addTool(bot, item.name, JSON.parse(item.arguments)); } catch { /* invalid tool arguments */ }
          }
        }
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
  if (!demo && !aiReady()) {
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
        if (event.event === "text") {
          bot.text += event.delta;
          // Coalesce streamed deltas into one render per animation frame.
          if (!bot.renderFrame) bot.renderFrame = requestAnimationFrame(() => {
            bot.renderFrame = null; renderAnswer(bot.body, bot.text); scrollMessages();
          });
        }
        if (event.event === "source") addSource(bot, event.url);
        if (event.event === "tool") {
          $("#activity").textContent = event.name === "propose_action" ? "Preparing a change for review…" : `Reading ${event.input.service}: ${event.input.path}…`;
          addTool(bot, event.name, event.input);
        }
        if (event.event === "tool_done" && !event.ok) {
          bot.root.append(element("p", "error", event.message));
        }
        if (event.event === "action") drawAction(event.action, bot.root);
        if (event.event === "error") throw new Error(event.message);
        if (event.event === "done") {
          renderAnswer(bot.body, bot.text);
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
    if (bot?.renderFrame) cancelAnimationFrame(bot.renderFrame);
    if (bot) renderAnswer(bot.body, bot.text);
    busy = false; $("#send").disabled = false; $("#stop").hidden = true; controller = null;
  }
}

function openSettings() {
  dirtyConnections.clear();
  const form = $("#settingsForm");
  for (const input of form.elements) input.disabled = demo;
  form.reset();
  for (const input of form.elements) {
    if (!input.name) continue;
    const [section, key] = input.name.split(".");
    if (input.name === "allow_writes") { input.checked = Boolean(config.allow_writes); continue; }
    if (key === "token" || aiSecretFields.includes(key)) {
      input.value = "";
      input.placeholder = config[section]?.[key + "_configured"] ? "Saved · leave blank to keep" : "Enter your token/key";
      continue;
    }
    if (key === "clear_token" || key === "clear_aws") { input.checked = false; continue; }
    const value = config[section]?.[key];
    if (value !== undefined) input.value = Array.isArray(value) ? value.join("\n") : value;
  }
  if (!form.elements["github.url"].value) form.elements["github.url"].value = "https://api.github.com";
  if (!config.ai?.provider && !demo) form.elements["ai.provider"].value = "chatgpt";
  $("#settingsStatus").textContent = demo ? "Fixed fictional connections. Restart in live mode to configure real services." : "";
  form.elements["jira.mode"].value = config.jira?.mode || (config.jira?.auth === "basic" ? "advanced" : "simple");
  form.elements["jira.access"].value = config.jira?.access || "selected";
  updateJiraSetup();
  updateProvider();
  selectSettingsTab(activeSettings);
  for (const service of ["ai", "github", "jira", "jenkins"]) renderConnection(service);
  $("#settingsDialog").showModal();
}

async function updateProvider() {
  const form = $("#settingsForm"), selected = form.elements["ai.provider"].value === "chatgpt";
  if (!selected) {
    const sameProvider = form.elements["ai.provider"].value === config.ai?.provider;
    form.elements["ai.model"].value = sameProvider ? config.ai?.model || "" : "";
    form.elements["ai.api_key"].placeholder = sameProvider && config.ai?.api_key_configured
      ? "Saved · leave blank to keep" : "Enter this provider's key";
  }
  const generation = ++modelLoad;
  $("#chatgptConnection").hidden = !selected;
  $("#chatgptModelLabel").hidden = !selected;
  $("#apiModelLabel").hidden = selected;
  $("#apiCredentials").hidden = selected;
  $("#removeAIKey").hidden = selected;
  updateBedrock();
  $("#testAIButton").textContent = selected ? "Save & check model access" : "Save & test AI · billable";
  if (!selected) return;
  const accounts = $("#chatgptAccount");
  accounts.replaceChildren(element("option", "", "Add a ChatGPT account"));
  accounts.firstChild.value = "";
  for (const account of chatgpt.accounts || []) {
    const option = element("option", "", account.email + " · " + account.id.slice(-6));
    option.value = account.id;
    accounts.append(option);
  }
  accounts.value = chatgpt.active || "";
  $("#connectChatGPT").disabled = demo || !chatgpt.available || busy;
  $("#disconnectChatGPT").hidden = !chatgpt.connected;
  $("#disconnectChatGPT").disabled = busy;
  const picker = $("#chatgptModel");
  picker.replaceChildren(element("option", "", "Connect your account first"));
  picker.firstChild.value = "";
  $("#chatgptStatus").textContent = !chatgpt.available
    ? "Open the local live app at http://127.0.0.1:8765 to sign in."
    : chatgpt.plan_enabled ? "Signed in. Loading models available to your account…"
    : chatgpt.connected ? "Signed in, but ChatGPT plan usage is not enabled. Continue again to review permission."
    : "Connect your personal account. Sign-in and plan permission stay with OpenAI.";
  if (!chatgpt.plan_enabled) return;
  try {
    const result = await api("/api/chatgpt/models");
    if (generation !== modelLoad) return;
    picker.replaceChildren();
    for (const model of result.models) {
      const option = element("option", "", model.display_name);
      option.value = model.slug;
      picker.append(option);
    }
    if (result.models.some(m => m.slug === config.ai?.model)) picker.value = config.ai.model;
    $("#chatgptStatus").textContent = result.models.length
      ? "Plan access verified. Choose a model and save connections."
      : "No models are available to this account. Check your ChatGPT plan access.";
  } catch (error) {
    if (generation === modelLoad) $("#chatgptStatus").textContent = error.message;
  }
}
$("#settingsForm").elements["ai.provider"].onchange = updateProvider;
function updateBedrock() {
  const form = $("#settingsForm");
  const bedrock = form.elements["ai.provider"].value === "bedrock";
  const iam = bedrock && form.elements["ai.bedrock_auth"].value === "iam";
  $("#bedrockSettings").hidden = !bedrock;
  $("#awsCredentials").hidden = !iam;
  $("#aiKeyLabel").hidden = iam;
  $("#removeAIKey").hidden = iam || form.elements["ai.provider"].value === "chatgpt";
  form.elements["ai.bedrock_endpoint"].querySelector('[value="mantle"]').disabled = iam;
  if (iam) form.elements["ai.bedrock_endpoint"].value = "runtime";
}
$("#settingsForm").elements["ai.bedrock_auth"].onchange = updateBedrock;
function connectionEdited(event) {
  const service = event.target.closest("[data-settings-panel]")?.dataset.settingsPanel;
  if (!service) return;
  dirtyConnections.add(service);
  if (service !== "changes") renderConnection(service);
}
$("#settingsForm").addEventListener("input", connectionEdited);
$("#settingsForm").addEventListener("change", connectionEdited);
$("#connectChatGPT").onclick = async () => {
  $("#connectChatGPT").disabled = true;
  try {
    const result = await api("/api/chatgpt/start", {method: "POST",
      body: JSON.stringify({account: $("#chatgptAccount").value || null})});
    location.assign(result.url);
  } catch (error) {
    $("#chatgptStatus").textContent = error.message;
    $("#connectChatGPT").disabled = false;
  }
};
$("#disconnectChatGPT").onclick = async () => {
  try {
    const result = await api("/api/chatgpt/disconnect", {method: "POST"});
    await refreshState();
    await updateProvider();
    $("#chatgptStatus").textContent = result.message;
  } catch (error) { $("#chatgptStatus").textContent = error.message; }
};

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
const connectionLabels = {ai: "AI", github: "GitHub", jira: "Jira", jenkins: "Jenkins", changes: "change settings"};

function selectSettingsTab(service) {
  activeSettings = service;
  document.querySelectorAll("[data-settings-tab]").forEach(button => {
    const selected = button.dataset.settingsTab === service;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll("[data-settings-panel]").forEach(panel => {
    panel.hidden = panel.dataset.settingsPanel !== service;
  });
  $("#saveConnection").hidden = ["github", "jira", "jenkins"].includes(service);
  $("#saveConnection").textContent = service === "changes" ? "Save change settings" : `Save ${connectionLabels[service]} connection`;
  $("#settingsStatus").textContent = demo ? "Offline sample. Real credentials cannot be added here." : "Only this tab is saved.";
}
document.querySelectorAll("[data-settings-tab]").forEach(button => {
  button.onclick = () => selectSettingsTab(button.dataset.settingsTab);
  button.onkeydown = event => {
    const tabs = [...document.querySelectorAll("[data-settings-tab]")];
    const index = tabs.indexOf(button);
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault(); selectSettingsTab(tabs[next].dataset.settingsTab); tabs[next].focus();
  };
});

function renderConnection(service, override) {
  const saved = connectionReports[service];
  const expired = saved?.checked_at && Date.now() / 1000 - saved.checked_at > 3600;
  const report = override || (dirtyConnections.has(service)
    ? {status: "unchecked", message: "Inputs changed. Save & check to validate them."}
    : expired ? {status: "unchecked", message: "The previous check expired. Check access again."}
    : saved || {status: "unchecked", message: "Not checked. Save & check this connection."});
  const status = report.status || "unchecked";
  const dot = $(`[data-connection-dot="${service}"]`);
  dot.dataset.state = status;
  dot.setAttribute("aria-label", status);
  const summary = $(`[data-connection-summary="${service}"]`);
  summary.dataset.state = status;
  summary.replaceChildren();
  const light = element("span", "connection-dot"); light.dataset.state = status;
  const label = {passed: "✓ Connected · Pass", failed: "✕ Failed", checking: "Checking…", unchecked: "Not verified", simulated: "Sample only"}[status];
  summary.append(light, document.createTextNode(label));
  const output = $(`#test-${service}`);
  output.replaceChildren(element("p", status === "failed" ? "error" : "muted", report.message));
  if (report.checked_at) output.append(element("p", "hint", "Last checked: " + new Date(report.checked_at * 1000).toLocaleString() + " · valid for up to 1 hour"));
  if (report.details?.length) {
    const list = element("ul"); report.details.forEach(text => list.append(element("li", "", text)));
    if (service === "jira") {
      const details = element("details");
      details.append(element("summary", "", "Connection details"), list); output.append(details);
    } else output.append(list);
  }
  let targetsOutput = output;
  if (service === "jira" && report.targets?.length) {
    targetsOutput = element("details", "accessible-projects");
    targetsOutput.append(element("summary", "", `Accessible projects (${report.targets.length} shown)`));
    output.append(targetsOutput);
  }
  for (const target of report.targets || []) {
    const card = element("div", "connection-target");
    card.dataset.state = target.ok ? "passed" : "failed";
    card.append(element("h3", "", (target.ok ? "✓ " : "✕ ") + target.target),
                element("p", target.ok ? "" : "error", target.message));
    if (target.details?.length) {
      const list = element("ul"); target.details.forEach(text => list.append(element("li", "", text))); card.append(list);
    }
    for (const check of target.checks || []) {
      const row = element("p", "capability-check", `${check.ok ? "✓" : "✕"} ${check.name}: ${check.message}`);
      row.dataset.state = check.ok ? "passed" : "failed"; card.append(row);
    }
    targetsOutput.append(card);
  }
}

function updateJiraSetup() {
  const form = $("#settingsForm");
  const simple = form.elements["jira.mode"].value === "simple";
  $("#jiraAdvanced").hidden = simple;
  $("#jiraSimpleHint").hidden = !simple;
  $("#jiraProjectKeys").hidden = form.elements["jira.access"].value === "all";
}
$("#settingsForm").elements["jira.mode"].addEventListener("change", updateJiraSetup);
$("#settingsForm").elements["jira.access"].addEventListener("change", updateJiraSetup);
$("#settingsForm").elements["jira.auth"].addEventListener("change", () => {
  const form = $("#settingsForm");
  form.elements["jira.api_version"].value = form.elements["jira.auth"].value === "basic" ? "3" : "2";
});

function settingsData() {
  const data = {ai: {}, github: {}, jira: {}, jenkins: {}};
  for (const input of $("#settingsForm").elements) {
    if (!input.name) continue;
    if (input.name === "allow_writes") { data.allow_writes = input.checked; continue; }
    const [section, key] = input.name.split(".");
    let value = input.type === "checkbox" ? input.checked : input.value.trim();
    if (["repos", "projects", "jobs"].includes(key)) value = value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    data[section][key] = value;
  }
  if (data.jira.mode === "simple") Object.assign(data.jira, {auth: "bearer", api_version: "2", access: "all", projects: [], username: ""});
  if (data.ai.provider === "chatgpt") data.ai.model = $("#chatgptModel").value;
  return data;
}

async function saveConnection(service) {
  const data = settingsData();
  const body = service === "changes" ? {allow_writes: data.allow_writes} : data[service];
  await api(`/api/settings/${service}`, {method: "PUT", body: JSON.stringify(body)});
  dirtyConnections.delete(service);
  const form = $("#settingsForm");
  for (const input of form.elements) {
    if (!input.name?.startsWith(service + ".")) continue;
    const key = input.name.split(".")[1];
    if (key === "token" || aiSecretFields.includes(key)) input.value = "";
    if (key.startsWith("clear_")) input.checked = false;
  }
  await refreshState();
  for (const input of form.elements) {
    if (!input.name?.startsWith(service + ".")) continue;
    const key = input.name.split(".")[1];
    if (key === "token" || aiSecretFields.includes(key)) input.placeholder = config[service]?.[key + "_configured"] ? "Saved · leave blank to keep" : "Enter your token/key";
  }
  if (service !== "changes") renderConnection(service);
}

$("#settingsForm").onsubmit = async event => {
  event.preventDefault();
  const service = activeSettings;
  $("#saveConnection").disabled = true;
  try {
    await saveConnection(service);
    $("#settingsStatus").textContent = service === "changes" ? "Change settings saved." : "Saved. Check access to verify the connection.";
  } catch (error) {
    $("#settingsStatus").textContent = error.message;
    if (service !== "changes") renderConnection(service, {status: "failed", message: error.message});
  } finally { $("#saveConnection").disabled = demo; }
};
document.querySelectorAll("[data-test]").forEach(button => {
  button.onclick = async () => {
    if (checkingConnection) return;
    const service = button.dataset.test;
    checkingConnection = true;
    document.querySelectorAll("[data-test]").forEach(b => { b.disabled = true; });
    $("#saveConnection").disabled = true;
    try {
      if (!demo) await saveConnection(service);
      renderConnection(service, {status: "checking", message: "Checking saved credentials and configured targets…"});
      const result = await api(`/api/connections/${service}/test`, {method: "POST"});
      await refreshState();
      renderConnection(service, dirtyConnections.has(service)
        ? {status: "unchecked", message: "Inputs changed during the check. Save & check again."} : result);
      $("#settingsStatus").textContent = result.ok ? "Access check passed." : "Fix the failed checks shown above.";
    } catch (error) {
      renderConnection(service, {status: "failed", message: error.message});
      $("#settingsStatus").textContent = "Check failed. See the correction above.";
    } finally {
      checkingConnection = false;
      document.querySelectorAll("[data-test]").forEach(b => { b.disabled = demo; });
      $("#saveConnection").disabled = demo;
    }
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
  const outcome = new URLSearchParams(location.search).get("chatgpt");
  if (outcome) {
    history.replaceState(null, "", "/");
    if (!$("#workspace").hidden) {
      openSettings();
      $("#settingsForm").elements["ai.provider"].value = "chatgpt";
      await updateProvider();
      if (outcome === "failed") $("#chatgptStatus").textContent =
        "Sign-in could not be completed. Continue again and review OpenAI's account and plan permission.";
    } else $("#loginError").textContent = "Open your workspace to check the ChatGPT connection.";
  }
}
initialize().catch(error => { $("#loginError").textContent = error.message; });
