const $ = selector => document.querySelector(selector);
let csrf = "", config = {}, cid = null, controller = null, busy = false;
let demo = false;
let initializingChat = null, openingChat = null, restoringChat = null, queuedAsk = false, navigationVersion = 0;
const pagesPreview = Boolean(window.AiMatePagesPreview);
let access = {role:"admin",configure:true,write:false,manage_records:true,audit:true};
let privateChat = false, feedbackMessage = null, feedbackRating = "positive", vaultEditId = null;
let activeModelSelection = null;
let pendingAttachments = [];
let loginUsesOtp = false, recoveryLogin = false, loginOptions = {};
let chatgpt = {}, modelLoad = 0;
let activeSettings = "ai", checkingConnection = false;
let connectionReports = {}, connectionDefaults = {};
let connectionSync = null;
let bedrockCatalog = [], bedrockPresetEndpoint = "", bedrockCatalogLoad = 0;
let conversationGroups = [], conversationList = [], editingGroup = null;
let archiveView = false;
let expandedGroups = new Set();
try { expandedGroups = new Set(JSON.parse(localStorage.getItem("aimate.groups") || "[]")); } catch {}
const dirtyConnections = new Set();
const aiSecretFields = ["api_key", "aws_access_key", "aws_secret_key", "aws_session_token"];
function renderAppearance() {
  document.querySelectorAll("[data-theme-choice]").forEach(button => {
    button.setAttribute("aria-pressed", button.dataset.themeChoice === document.documentElement.dataset.theme);
  });
}
$("#openAppearance").onclick = () => { renderAppearance(); $("#appearanceDialog").showModal(); };
document.querySelectorAll("[data-theme-choice]").forEach(button => {
  button.onclick = () => window.AiMateAppearance.apply(button.dataset.themeChoice);
});
window.addEventListener("aimate-theme", renderAppearance);
document.querySelectorAll(".sidebar-tools > button").forEach(button => {
  const label = button.querySelector("span")?.textContent;
  if (label) { button.title = label; button.setAttribute("aria-label", label); }
});
try { $("#sidebarTools").open = localStorage.getItem("aimate.toolsOpen") === "true"; } catch {}
$("#sidebarTools").ontoggle = () => {
  try { localStorage.setItem("aimate.toolsOpen", $("#sidebarTools").open); } catch {}
};
document.addEventListener("contextmenu", event => {
  if (event.defaultPrevented || $("#workspace").hidden ||
      event.target.closest("input, textarea, select, [contenteditable], a, .body, pre, code") ||
      window.getSelection()?.toString()) return;
  event.preventDefault();
  conversationContext.hidden = true;
});
let sidebarExpandedWidth = 280;
try { sidebarExpandedWidth = Number(localStorage.getItem("aimate.sidebarExpandedWidth")) || 280; } catch {}
function setSidebarWidth(width, persist = true) {
  const collapsed = width < 160;
  const maximum = innerWidth > 650 ? Math.floor(innerWidth / 2) : Math.max(200, sidebarExpandedWidth, width);
  width = collapsed ? 64 : Math.round(Math.max(200, Math.min(maximum, width)));
  $("#workspace").style.setProperty("--sidebar-width", `${width}px`);
  $("#workspace").classList.toggle("sidebar-collapsed", collapsed);
  $("#sidebarResize").setAttribute("aria-valuemax", maximum);
  $("#sidebarResize").setAttribute("aria-valuenow", width);
  $("#expandSidebar").setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
  $("#expandSidebar").setAttribute("aria-expanded", !collapsed);
  $("#expandSidebar").title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  if (!collapsed) sidebarExpandedWidth = width;
  if (persist) try {
    localStorage.setItem("aimate.sidebarWidth", width);
    localStorage.setItem("aimate.sidebarExpandedWidth", sidebarExpandedWidth);
  } catch {}
}
try { setSidebarWidth(Number(localStorage.getItem("aimate.sidebarWidth")) || 224, innerWidth > 650); } catch {}
$("#expandSidebar").onclick = () => setSidebarWidth($("#workspace").classList.contains("sidebar-collapsed") ? sidebarExpandedWidth : 64);
window.addEventListener("resize", () => {
  if (innerWidth > 650) setSidebarWidth($("#workspace").classList.contains("sidebar-collapsed") ? 64 : sidebarExpandedWidth, false);
});
$("#sidebarResize").ondblclick = () => setSidebarWidth(224);
$("#sidebarResize").onkeydown = event => {
  if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
  event.preventDefault();
  const current = $("#sidebar").getBoundingClientRect().width;
  const next = event.key === "Home" ? 224 : event.key === "ArrowRight" ? (current < 200 ? 200 : current + 20) : (current <= 200 ? 64 : current - 20);
  setSidebarWidth(next);
};
$("#sidebarResize").onpointerdown = event => {
  if (event.button !== 0) return;
  event.preventDefault();
  const handle = event.currentTarget;
  handle.setPointerCapture(event.pointerId);
  document.body.classList.add("resizing-sidebar");
  handle.onpointermove = move => setSidebarWidth(move.clientX);
  const stop = () => { document.body.classList.remove("resizing-sidebar"); handle.onpointermove = null; };
  handle.onpointerup = stop; handle.onlostpointercapture = stop;
};

let historySearchTimer, historySearchVersion = 0;
function selectHelpPage(topic) {
  document.querySelectorAll("[data-help-tab]").forEach(button => {
    const selected = button.dataset.helpTab === topic;
    button.setAttribute("aria-selected", selected);
    button.setAttribute("aria-pressed", selected);
    button.tabIndex = selected ? 0 : -1;
    $(`#help-${button.dataset.helpTab}`).hidden = !selected;
  });
}
function openHelp(topic = "guide") {
  selectHelpPage(topic);
  $("#helpDialog").showModal();
}
$("#openHelp").onclick = () => openHelp();
document.querySelectorAll("[data-help-tab]").forEach(button => {
  button.onclick = () => selectHelpPage(button.dataset.helpTab);
  button.onkeydown = event => {
    const tabs = [...document.querySelectorAll("[data-help-tab]")], index = tabs.indexOf(button);
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length :
      event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length :
      event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault(); tabs[next].click(); tabs[next].focus();
  };
});
document.querySelectorAll("[data-help-action]").forEach(button => {
  button.onclick = () => { $("#helpDialog").close(); document.getElementById(button.dataset.helpAction).click(); };
});
document.addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key === "/" &&
      !$("#workspace").hidden && !document.querySelector("dialog[open]")) {
    event.preventDefault(); openHelp("shortcuts");
  }
});
function openHistorySearch() {
  $("#historySearchDialog").showModal();
  $("#historySearchInput").focus();
}
$("#searchHistory").onclick = openHistorySearch;
document.addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && !$("#workspace").hidden) {
    if (document.querySelector("dialog[open]")) return;
    event.preventDefault(); openHistorySearch();
  }
});
function highlightHistoryText(text, query) {
  const fragment = document.createDocumentFragment();
  const words = [...new Set(query.trim().split(/\s+/).filter(Boolean))];
  const expression = new RegExp(words.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "gi");
  let end = 0;
  for (const match of text.matchAll(expression)) {
    fragment.append(document.createTextNode(text.slice(end, match.index)), element("mark", "", match[0]));
    end = match.index + match[0].length;
  }
  fragment.append(document.createTextNode(text.slice(end))); return fragment;
}
$("#historySearchInput").oninput = () => {
  clearTimeout(historySearchTimer);
  const version = ++historySearchVersion, query = $("#historySearchInput").value.trim();
  $("#historySearchResults").replaceChildren();
  $("#historySearchStatus").textContent = query ? "Searching…" : "Search your previous work.";
  if (!query) return;
  historySearchTimer = setTimeout(async () => {
    try {
      const data = await api(`/api/history/search?q=${encodeURIComponent(query)}`);
      if (version !== historySearchVersion) return;
      $("#historySearchStatus").textContent = data.results.length ? `${data.results.length}${data.more ? "+" : ""} chats found` : "No saved chats match.";
      for (const result of data.results) {
        const button = element("button", "history-search-result"); button.type = "button";
        const title = element("strong"); title.append(highlightHistoryText(result.title, query));
        const meta = [result.area || "Standalone", result.archived ? "Archived" : "", result.created ? new Date(result.created * 1000).toLocaleDateString() : ""].filter(Boolean).join(" · ");
        const excerpt = element("p"); excerpt.append(highlightHistoryText(result.snippet, query));
        button.append(title, element("small", "", meta), excerpt);
        button.onclick = async () => {
          if (busy) { $("#historySearchStatus").textContent = "Wait for the current reply or stop it before opening another chat."; return; }
          try {
            await openConversation(result.id, result.title);
            $("#historySearchDialog").close();
            const target = [...$("#messages").children].find(item => item.dataset.turnId === String(result.turn_id) && (!result.role || item.classList.contains(result.role)));
            if (target) { target.scrollIntoView({block:"center", behavior:"smooth"}); target.classList.add("search-hit"); setTimeout(() => target.classList.remove("search-hit"), 2100); }
          } catch (error) { $("#historySearchStatus").textContent = error.message; }
        };
        $("#historySearchResults").append(button);
      }
    } catch (error) { if (version === historySearchVersion) $("#historySearchStatus").textContent = error.message; }
  }, 180);
};

function aiReady() {
  return Boolean(config.ai?.model && (config.ai.provider === "chatgpt"
    ? chatgpt.plan_enabled : config.ai.provider === "bedrock"
      ? config.ai.region && (config.ai.bedrock_auth === "iam" || config.ai.api_key_configured)
      : config.ai.api_key_configured));
}

function shortModelName(model) {
  if (!model) return "Not configured";
  const claude = model.match(/claude-(haiku|sonnet|opus|fable)-(\d+)(?:[-.](\d{1,2})(?!\d))?/i);
  if (claude) return `${claude[1][0].toUpperCase() + claude[1].slice(1)} ${claude[2]}${claude[3] ? "." + claude[3] : ""}`;
  const accountModel = chatgpt.models?.find?.(item => item.slug === model);
  return accountModel?.display_name || model.replace(/^(?:us\.|eu\.|global\.)/, "").replace(/^anthropic\./, "").replace(/-\d{8}.*$/, "").replace(/:.*$/, "");
}

function updateModelInfo(message, used) {
  const route = used.route === "analysis" ? "Analysis" : "Standard";
  const mode = used.mode === "auto" ? "Auto" : route;
  const total = used.usage ? (used.usage.input_tokens || 0) + (used.usage.output_tokens || 0) : null;
  const label = `${mode}${total === null ? "" : ` · 🔥 ${total.toLocaleString()}`}`;
  const details = [`${used.mode === "auto" ? "Auto → " : ""}${route} · ${used.model}`];
  if (used.usage) details.push(`${(used.usage.input_tokens || 0).toLocaleString()} input / ${(used.usage.output_tokens || 0).toLocaleString()} output tokens`);
  if (used.notice) details.push(used.notice);
  if (!message.modelInfo) {
    message.modelInfo = element("details", "model-info");
    message.root.append(message.modelInfo);
  }
  const summary = element("summary");
  summary.title = details.join("\n");
  summary.setAttribute("aria-label", `${mode}${total === null ? "" : `, ${total.toLocaleString()} tokens used`}. Show model and token details`);
  summary.append(element("span", "model-name", mode));
  if (total !== null) {
    const flame = element("span", "model-flame", "🔥");
    flame.setAttribute("aria-hidden", "true");
    summary.append(element("span", "model-name", "·"), flame,
      element("span", "model-name", total.toLocaleString()));
  }
  const panel = element("div", "model-details");
  panel.append(element("span", "model-route", mode === "Auto" ? `Auto selected ${route}` : `${route} mode`),
    element("code", "model-id", used.model));
  if (used.usage) {
    const tokens = element("div", "model-token-counts");
    for (const [name, value] of [["Input", used.usage.input_tokens], ["Output", used.usage.output_tokens]]) {
      const metric = element("div");
      metric.append(element("small", "", name), element("strong", "", (value || 0).toLocaleString()));
      tokens.append(metric);
    }
    panel.append(tokens);
  }
  if (used.notice) panel.append(element("p", "hint", used.notice));
  message.modelInfo.replaceChildren(summary, panel);
  message.modelDetails = used;
  return label;
}

document.addEventListener("click", event => {
  document.querySelectorAll(".model-info[open]").forEach(panel => {
    if (!panel.contains(event.target)) panel.open = false;
  });
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    document.querySelectorAll(".model-info[open]").forEach(panel => { panel.open = false; });
  }
});

function renderModelSelection(event = null) {
  const mode = $("#modelMode").value;
  const key = JSON.stringify([mode, config.ai?.provider, config.ai?.model, config.ai?.analysis_model, demo]);
  if (event) activeModelSelection = {key, route: event.route, model: event.model};
  if (activeModelSelection?.key !== key) activeModelSelection = null;
  const route = activeModelSelection?.route || (mode === "analysis" ? "analysis" : "standard");
  const model = activeModelSelection?.model || (route === "analysis" ? config.ai?.analysis_model : config.ai?.model);
  const unavailable = demo || !config.ai?.analysis_model;
  const picker = $("#modelMode");
  for (const option of picker.options) {
    const label = option.value === "auto" ? "Auto" : option.value === "analysis" ? "Analysis" : "Standard";
    const selectedModel = option.value === "auto" ? model : option.value === "analysis" ? config.ai?.analysis_model : config.ai?.model;
    option.textContent = pagesPreview ? label : demo ? `${label} · Demo` : `${label} · ${shortModelName(selectedModel)}`;
    option.disabled = option.value === "analysis" && unavailable;
    option.title = option.value === "auto" ? "Auto: AiMate chooses Standard for lookups and Analysis for debugging or complex tasks." : selectedModel || "Set an Analysis model in Settings → AI model → Advanced.";
  }
  picker.title = pagesPreview ? "Backend not connected. No AI model is running." : demo ? "Scripted demo" : `${mode === "auto" ? "Auto: AiMate chooses Standard for lookups and Analysis for debugging or complex tasks.\n" : ""}${model || "No model configured"}${mode === "auto" && activeModelSelection ? " · Auto selected " + route : ""}${unavailable ? "\nAnalysis unavailable: configure it in Settings → AI model → Advanced." : ""}`;
  picker.setAttribute("aria-label", `Model selection: ${mode === "auto" ? "Auto · " + shortModelName(model) : picker.selectedOptions[0].textContent}`);
}
$("#modelMode").onchange = () => renderModelSelection();

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

function conversationEmoji(title) {
  const existing = title.match(/^\s*(\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic})*)/u);
  if (existing) return existing[1];
  const topics = [
    [/\b(security|password|vault|privacy|auth|login|sign.?in|pat|token access)\b/i, "🔐"],
    [/\b(debug|bug|failure|failed|error|fix|troubleshoot|warning)\b/i, "🐛"],
    [/\b(jenkins|build|pipeline|ci\/cd|deployment|deploy|logs?)\b/i, "⚙️"],
    [/\b(pull requests?|pr|github|git|repos?|repositories|commits?|branches|merge)\b/i, "📦"],
    [/\b(jira|issues?|tickets?|tasks?|todo|to-do|checklist)\b/i, "📋"],
    [/\b(ai|aimate|claude|bedrock|chatgpt|models?|assistant|who are you|your name)\b/i, "🤖"],
    [/\b(usage|billing|cost|budget|spend|tokens?)\b/i, "💰"],
    [/\b(architecture|design|flow|diagram|plan|roadmap)\b/i, "🧩"],
    [/\b(test|tests|testing|validation|coverage)\b/i, "🧪"],
    [/\b(code|coding|python|javascript|typescript|api|implement|function)\b/i, "💻"],
    [/\b(data|database|sql|metrics|report|analysis|analyze)\b/i, "📊"],
    [/\b(readme|docs?|documentation|notes|diary|knowledge|explain)\b/i, "📖"],
    [/\b(ui|theme|style|color|colour|layout|page|website)\b/i, "🎨"],
    [/\b(performance|optimi[sz]|speed|latency)\b/i, "⚡"],
  ];
  return topics.find(([pattern]) => pattern.test(title))?.[1] || "💬";
}

function conversationButton(thread, className = "") {
  const button = element("button", "conversation-link " + className);
  button.type = "button";
  button.setAttribute("aria-label", thread.title);
  const emoji = thread.icon || conversationEmoji(thread.title);
  const icon = element("span", "conversation-emoji" + (/^[A-Za-z0-9]{1,3}$/.test(emoji) ? " conversation-monogram" : ""), emoji);
  icon.setAttribute("aria-hidden", "true");
  const label = !/^[A-Za-z0-9]{1,3}$/.test(emoji) && thread.title.trimStart().startsWith(emoji)
    ? thread.title.trimStart().slice(emoji.length).trimStart() : thread.title;
  button.append(icon, element("span", "conversation-label", label));
  const sameTitles = conversationList.filter(item => item.title === thread.title &&
    (item.group_id || null) === (thread.group_id || null) && Boolean(item.archived) === Boolean(thread.archived))
    .sort((a, b) => a.created - b.created || a.id.localeCompare(b.id));
  if (sameTitles.length > 1) {
    const number = sameTitles.findIndex(item => item.id === thread.id) + 1;
    const marker = element("span", "conversation-duplicate", String(number));
    marker.title = `Separate chat ${number} of ${sameTitles.length} · ${new Date(thread.created * 1000).toLocaleString()}`;
    marker.setAttribute("aria-label", marker.title);
    button.append(marker);
  }
  if (thread.pinned) {
    const pin = element("span", "conversation-pin", "★");
    pin.setAttribute("aria-hidden", "true");
    button.append(pin);
  }
  return button;
}

function sourceBadge(name, service) {
  const report = connectionReports[service] || {};
  const status = pagesPreview ? "unchecked" : demo ? "simulated" : report.status || "unchecked";
  const chip = element("button", "source-chip");
  chip.type = "button";
  chip.dataset.service = service;
  chip.dataset.state = status;
  const dot = element("i", "connection-dot"); dot.dataset.state = status;
  const counts = report.counts;
  const partial = "Partial" + (counts ? ` · ${counts.passed}/${counts.total} ${counts.unit}` : "");
  const statusLabel = pagesPreview ? "Backend not connected" : demo ? "Sample" : status === "passed" ? "Connected" : status === "partial" ? partial : status === "failed" ? "Failed" : "Not checked";
  chip.append(dot, document.createTextNode(name));
  chip.title = statusLabel + (report.message ? " · " + report.message : "");
  if (report.checked_at) chip.title += " · Last verified " + new Date(report.checked_at * 1000).toLocaleString();
  if (report.stale && service !== "ai") chip.title += " · Refreshing automatically";
  chip.setAttribute("aria-label", `${name}: ${statusLabel}. Open connection details`);
  chip.onclick = event => { event.stopPropagation(); activeSettings = service; openSettings(); };
  return chip;
}

function renderSourceBar() {
  const bar = $("#sourceBar");
  bar.replaceChildren();
  bar.append(element("span", "source-bar-label", "Connections"));
  for (const [key, label] of [["github", "GitHub"], ["jira", "Jira"], ["jenkins", "Jenkins"]]) {
    if (["jira", "jenkins"].includes(key) && !config[key]?.token_configured) continue;
    bar.append(sourceBadge(label, key));
  }
  bar.append(sourceBadge(pagesPreview ? "ChatGPT" : demo ? "Scripted demo" : config.ai?.provider === "chatgpt" ? "ChatGPT" : config.ai?.provider === "bedrock" ? "Claude · Bedrock" : "Claude", "ai"));
}

async function syncConnections() {
  if (demo || $("#workspace").hidden || document.hidden) return;
  if (connectionSync) return connectionSync;
  connectionSync = (async () => {
    try {
      const result = await api("/api/connections/sync", {method: "POST"});
      connectionReports = result.connection_checks || {};
      renderSourceBar();
      for (const service of ["ai", "github", "jira", "jenkins"]) renderConnection(service);
    } catch { /* Keep last verified evidence while the local server is unavailable. */ }
    finally { connectionSync = null; }
  })();
  return connectionSync;
}

async function refreshState() {
  const state = await api("/api/state");
  csrf = state.csrf;
  config = state.config;
  $(".footnote").textContent = state.public_showcase
    ? "Personal sources only. Use your local office workspace for authorized work connections."
    : "The assistant uses your configured scope and token permissions. Review its evidence and proposed changes.";
  access = state.access || {role:"admin",configure:true,write:!!config.allow_writes,manage_records:true,audit:true};
  demo = Boolean(state.demo);
  $("#tab-changes").hidden = demo || !access.audit;
  $("#openAccess").hidden = !access.configure;
  $("#openVault").hidden = !access.configure;
  $("#openFeedbackLog").hidden = !access.audit;
  $("#adminWriteControls").hidden = !access.configure;
  $(".admin-security").hidden = !access.configure;
  $("#newGroup").hidden = !access.manage_records;
  chatgpt = state.chatgpt || {};
  connectionReports = state.connection_checks || {};
  connectionDefaults = state.connection_defaults || {};
  $("#modelMode").querySelector('[value="analysis"]').disabled = !config.ai?.analysis_model || demo;
  if ($("#modelMode").value === "analysis" && (!config.ai?.analysis_model || demo)) $("#modelMode").value = "auto";
  renderModelSelection();
  $("#demoBanner").hidden = !demo;
  if (pagesPreview) {
    $("#demoBanner").textContent = "Interface preview · Backend not connected · Changes last until you reload";
    $(".footnote").textContent = "Use your local AiMate workspace for live AI and authorized project access.";
  }
  $("#workspace").hidden = false;
  $("#loginScreen").hidden = true;
  $("#writeBadge").textContent = config.allow_writes ? "Changes need confirmation" : "Read mode";
  $("#accessModeLabel").textContent = pagesPreview ? "Interface preview" : demo ? "Demo · Read only" : `${{admin:"Admin",developer:"Developer",viewer:"Viewer",reviewer:"Reviewer"}[access.role]} · ${access.write ? "Read & write" : "Read"}`;
  $("#accessMode").title = pagesPreview ? "No live services or AI calls." : demo ? "Offline sample workspace." : config.allow_writes
    ? "Read project sources and confirm permitted proposed changes."
    : access.configure ? "Read project sources and update configuration. Write proposals are disabled." : "Read your project sources and manage personal connections. External changes are disabled.";
  renderSourceBar();
  void syncConnections();
  const ready = aiReady() && (config.github?.repos?.length || (config.jira?.projects?.length || (config.jira?.access === "all" && config.jira?.token_configured)) || config.jenkins?.jobs?.length || (config.jenkins?.access === "all" && config.jenkins?.token_configured));
  $("#setupHint").hidden = Boolean(demo || ready);
  $("#setupHint").textContent = "Connect AI + your project sources →";
  $("#setupHint").onclick = openSettings;
  const nav = $("#conversations");
  $("#chatMenu").hidden = !cid;
  for (const button of $("#chatMenu").querySelectorAll("button")) button.disabled = busy && button.id !== "continueChat";
  for (const id of ["pinChat","renameChat","moveChat","archiveChat"])
    $("#"+id).hidden = privateChat || !access.manage_records;
  $("#continueChat").hidden = privateChat;
  $("#deleteChat").hidden = !privateChat && !access.manage_records;
  nav.replaceChildren();
  conversationGroups = state.groups || []; conversationList = state.conversations;
  $("#pinChat").textContent = conversationList.find(thread => thread.id === cid)?.pinned ? "Unpin chat" : "Pin chat";
  $("#archiveChat").textContent = conversationList.find(thread => thread.id === cid)?.archived ? "Restore" : "Archive";
  $("#archiveView").textContent = archiveView ? "Back to conversations" : "Archived chats";
  $("#archiveView").setAttribute("aria-pressed", String(archiveView));
  const activeGroup = state.conversations.find(thread => thread.id === cid)?.group_id || null;
  $("#chatLocation").hidden = !activeGroup;
  $("#chatLocation").textContent = activeGroup ? groupPath(activeGroup) : "";
  renderConversationTree(nav, activeGroup);
  const mobileNav = $("#mobileConversations");
  mobileNav.replaceChildren();
  for (const thread of state.conversations.filter(t => Boolean(t.archived) === archiveView)) {
    const mobileButton = conversationButton(thread);
    mobileButton.title = thread.group_id ? groupPath(thread.group_id) : "Standalone chat";
    mobileButton.onclick = () => {
      if (busy) return;
      $("#menuDialog").close();
      openConversation(thread.id, thread.title);
    };
    mobileNav.append(mobileButton);
  }
  return state;
}

function groupPath(id) {
  const parts = [];
  for (let group = conversationGroups.find(g => g.id === id); group && parts.length < 8;
       group = conversationGroups.find(g => g.id === group.parent)) parts.unshift(group.name);
  return parts.join(" / ");
}
function groupOptions(select, rootLabel) {
  select.replaceChildren();
  const root = element("option", "", rootLabel); root.value = ""; select.append(root);
  for (const group of [...conversationGroups].sort((a,b) => groupPath(a.id).localeCompare(groupPath(b.id)))) {
    const option = element("option", "", groupPath(group.id)); option.value = group.id; select.append(option);
  }
}
function isGroupBelow(id, ancestor) {
  for (let group = conversationGroups.find(g => g.id === id); group;
       group = conversationGroups.find(g => g.id === group.parent)) {
    if (group.parent === ancestor) return true;
  }
  return false;
}
function renderConversationTree(nav, activeGroup) {
  const ancestors = new Set();
  for (let group = conversationGroups.find(g => g.id === activeGroup); group;
       group = conversationGroups.find(g => g.id === group.parent)) ancestors.add(group.id);
  function fill(parent, node) {
    for (const group of conversationGroups.filter(g => g.parent === parent)) {
      if (archiveView && !conversationList.some(t => t.archived && (t.group_id === group.id || isGroupBelow(t.group_id, group.id)))) continue;
      const folder = element("details", "conversation-group"); folder.dataset.group = group.id;
      folder.open = expandedGroups.has(group.id) || ancestors.has(group.id);
      const summary = element("summary", "");
      summary.append(element("span", "group-name", group.name));
      summary.title = `${group.kind}: ${groupPath(group.id)}`;
      const add = element("button", "group-action", "＋"); add.type = "button";
      add.setAttribute("aria-label", "New chat in " + group.name);
      add.onclick = async event => {
        event.preventDefault(); event.stopPropagation();
        if (busy) return;
        try {
          const created = await api("/api/conversations", {method:"POST",body:JSON.stringify({group_id:group.id})});
          await openConversation(created.id);
        } catch (error) { $("#activity").textContent = error.message; }
      };
      const manage = element("button", "group-action", "⋯"); manage.type = "button";
      manage.setAttribute("aria-label", "Manage " + group.name);
      manage.onclick = event => { event.preventDefault(); event.stopPropagation(); openGroupDialog(group.id); };
      manage.hidden = !access.manage_records;
      summary.append(add, manage); folder.append(summary);
      const children = element("div", "group-children"); fill(group.id, children);
      if (!children.children.length) children.append(element("p", "group-empty", "No chats yet"));
      folder.append(children);
      folder.ontoggle = () => {
        if (folder.open) expandedGroups.add(group.id); else expandedGroups.delete(group.id);
        try { localStorage.setItem("aimate.groups", JSON.stringify([...expandedGroups])); } catch {}
      };
      node.append(folder);
    }
    for (const thread of conversationList.filter(t => (t.group_id || null) === parent && Boolean(t.archived) === archiveView)) {
      const row = element("div", "conversation-row" + (thread.id === cid ? " active" : ""));
      const button = conversationButton(thread, thread.id === cid ? "active" : "");
      button.title = thread.title;
      button.onclick = () => !busy && openConversation(thread.id, thread.title);
      const menu = element("button", "conversation-more", "⋯");
      menu.type = "button"; menu.setAttribute("aria-label", "Actions for " + thread.title);
      menu.onclick = event => { event.stopPropagation(); const rect = menu.getBoundingClientRect(); showConversationContext(thread, rect.right, rect.bottom); };
      row.oncontextmenu = event => { event.preventDefault(); showConversationContext(thread, event.clientX, event.clientY); };
      row.append(button, menu); node.append(row);
    }
  }
  fill(null, nav);
  if (!conversationList.some(t => Boolean(t.archived) === archiveView)) nav.append(element("p", "group-empty", archiveView ? "No archived chats" : "No conversations yet"));
}
function openGroupDialog(id = null) {
  if (busy) return;
  editingGroup = id;
  const group = conversationGroups.find(g => g.id === id);
  $("#groupDialogTitle").textContent = group ? "Group settings" : "New project / group";
  $("#groupName").value = group?.name || "";
  $("#groupPlacement").hidden = false;
  groupOptions($("#groupParent"), "Top level");
  if (group) {
    for (const option of [...$("#groupParent").options]) {
      if (option.value === id || isGroupBelow(option.value, id)) option.remove();
    }
  }
  $("#groupParent").value = group?.parent || "";
  $("#groupKind").value = group?.kind || "project";
  $("#groupKind").closest("label").hidden = Boolean(group);
  $("#removeGroup").hidden = !group;
  $("#saveGroup").textContent = group ? "Save changes" : "Create";
  $("#groupError").textContent = "";
  $("#groupDialog").showModal(); $("#groupName").focus();
}
$("#newGroup").onclick = () => openGroupDialog();
$("#groupForm").onsubmit = async event => {
  event.preventDefault(); $("#saveGroup").disabled = true;
  try {
    const payload = {name: $("#groupName").value.trim(), parent: $("#groupParent").value || null};
    if (!editingGroup) Object.assign(payload, {kind: $("#groupKind").value, parent: $("#groupParent").value || null});
    const result = await api(editingGroup ? `/api/groups/${editingGroup}` : "/api/groups", {
      method: editingGroup ? "PATCH" : "POST", body: JSON.stringify(payload)});
    expandedGroups.add(result.id); $("#groupDialog").close(); await refreshState();
  } catch (error) { $("#groupError").textContent = error.message; }
  finally { $("#saveGroup").disabled = false; }
};
$("#removeGroup").onclick = async () => {
  if (!editingGroup || busy) return;
  try { await api(`/api/groups/${editingGroup}`, {method:"DELETE"}); $("#groupDialog").close(); await refreshState(); }
  catch (error) { $("#groupError").textContent = error.message; }
};

function addMessage(role, text = "", turnId = null) {
  $("#welcome").hidden = true;
  const root = element("article", `message ${role}`);
  if (turnId !== null) root.dataset.turnId = turnId;
  const heading = element("div", "message-heading");
  heading.append(element("div", "who", role === "user" ? "YOU" : demo && !pagesPreview ? "AiMate · Scripted demo" : "AiMate"));
  const body = element("div", "body");
  if (role === "assistant") renderAnswer(body, text);
  else renderDataValue(body, text);
  const message = {root, body, text, turnId, conversationId: cid, reads: 0};
  if (role === "user") {
    const edit = element("button", "message-action", "Edit");
    edit.type = "button";
    edit.setAttribute("aria-label", "Edit your message");
    edit.dataset.editMessage = "";
    edit.disabled = busy;
    edit.onclick = () => editMessage(message, edit);
    heading.append(edit);
  }
  const action = element("button", "message-action", "Copy");
  action.type = "button";
  action.setAttribute("aria-label", role === "user" ? "Copy your message" : "Copy AiMate reply");
  action.onclick = async () => {
    if (!message.text) return;
    try {
      if (role === "user") await navigator.clipboard.writeText(message.text);
      else await copyFormatted(message.text);
      action.textContent = "Copied";
    } catch {
      action.textContent = "Copy failed";
    }
    setTimeout(() => { action.textContent = "Copy"; }, 1800);
  };
  heading.append(action);
  if(role === "assistant") {
    const feedback=element("button","message-action","Feedback");feedback.type="button";
    feedback.onclick=()=> {
      if(privateChat || !message.turnId) {$("#activity").textContent="Feedback is available for saved, completed answers.";return;}
      feedbackMessage=message;feedbackRating="positive";$("#feedbackComment").value="";$("#feedbackError").textContent="";setFeedbackRating("positive");$("#feedbackDialog").showModal();
    };
    heading.append(feedback);
  }
  root.append(heading, body);
  $("#messages").append(root);
  scrollMessages();
  return message;
}

function editMessage(message, action) {
  if (busy || message.root.querySelector(".message-editor")) return;
  const editor = element("div", "message-editor");
  const input = element("textarea");
  input.value = message.editText || message.text;
  input.maxLength = 30000;
  input.rows = Math.min(10, Math.max(3, (message.editText || message.text).split("\n").length));
  input.setAttribute("aria-label", "Edit message");
  const controls = element("div", "message-edit-controls");
  const cancel = element("button", "", "Cancel");
  const send = element("button", "primary", "Save & resend");
  cancel.type = send.type = "button";
  const close = () => { editor.remove(); message.body.hidden = false; action.hidden = false; };
  cancel.onclick = close;
  input.onkeydown = event => { if (event.key === "Escape") close(); };
  send.onclick = async () => {
    const question = input.value.trim();
    if (busy || !question) { input.focus(); return; }
    send.disabled = cancel.disabled = true;
    try {
      if (message.turnId) {
        const updated = await api(`/api/conversations/${message.conversationId}/edit`, {method: "POST",
          body: JSON.stringify({turn_id: message.turnId, question})});
        await openConversation(updated.id, $("#chatTitle").textContent);
      } else close();
      await ask(question);
    } catch (error) {
      $("#activity").textContent = error.message;
      send.disabled = cancel.disabled = false;
    }
  };
  controls.append(cancel, send);
  editor.append(input, controls);
  message.body.hidden = true;
  action.hidden = true;
  message.body.after(editor);
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
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
  if (action.service === "settings" && action.operation === "update_github_repositories" && action.status === "completed") {
    card.classList.add("action-completed");
    card.append(element("span", "success", demo ? "✓ Simulated change completed" : "✓ Completed"));
    const connection = element("button", "", "Check connection");
    connection.type = "button";
    connection.onclick = () => {
      activeSettings = "github";
      openSettings();
      const details = $("#test-github .connection-details");
      if (details) details.open = true;
      const repository = action.preview?.repository;
      const target = [...$("#test-github").querySelectorAll(".connection-target")]
        .find(item => item.dataset.target === repository);
      if (target) {
        target.open = true;
        target.scrollIntoView({block: "nearest"});
      }
    };
    card.append(connection);
    if (parent) parent.append(card);
    return card;
  }
  const label = action.operation.replaceAll("_", " ") + (demo ? " (simulated)" : "");
  card.append(element("h3", "", `${action.service} · ${label}`),
    element("p", "", `Status: ${action.status} · proposals expire after 30 minutes`),
    element("pre", "", JSON.stringify(action.preview, null, 2)));
  if (action.result) card.append(element("pre", "action-result", JSON.stringify(action.result, null, 2)));
  for (const pre of card.querySelectorAll("pre")) {
    const code = element("code", "", pre.textContent);
    pre.replaceChildren(code); highlightCodeElement(code, "json");
  }
  if (action.status === "unknown") {
    card.append(element("p", "", "The remote outcome is uncertain. Inspect the target before requesting this change again."));
  }
  if (action.status === "pending") {
    const buttons = element("div", "action-buttons");
    for (const decision of ["confirm", "cancel"]) {
      const button = element("button", decision === "confirm" ? "primary" : "", decision === "confirm" ? (demo ? "Confirm simulated change" : "Confirm change") : "Cancel");
      button.disabled = !demo && (action.service === "settings" ? !access.configure : !access.manage_records);
      if (!demo && access.role !== "admin" && ["delete_issue","delete_file","merge_pull_request","abort_build"].includes(action.operation)) {
        button.disabled = true;
        button.title = "Administrator access required";
      }
      button.onclick = async () => {
        for (const b of buttons.children) b.disabled = true;
        try {
          const next = await api(`/api/actions/${action.id}/${decision}`, {method: "POST"});
          const replacement = drawAction(next);
          card.replaceWith(replacement);
          if (next.service === "settings" && next.status === "completed") await refreshState();
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

function openConversation(id, title = "Project conversation", allowBusy = false) {
  if (busy && !allowBusy) return Promise.resolve();
  const pending = loadConversation(id, title, ++navigationVersion);
  openingChat = pending;
  return pending.finally(() => { if (openingChat === pending) openingChat = null; });
}

async function loadConversation(id, title, version) {
  const conversation = await api(`/api/conversations/${id}`);
  if (version !== navigationVersion) return;
  privateChat = Boolean(conversation.private);
  cid = id;
  archiveView = Boolean(conversationList.find(t => t.id === id)?.archived);
  try {
    if (privateChat) localStorage.removeItem("aimate.conversation");
    else localStorage.setItem("aimate.conversation", id);
  } catch { /* storage may be unavailable */ }
  $("#messages").replaceChildren();
  $("#chatTitle").textContent = conversation.title || title;
  $("#privateToggle").setAttribute("aria-pressed",String(privateChat));
  $("#welcome").hidden = Boolean(conversation.turns.length || conversation.actions.length);
  for (const turn of conversation.turns) {
    const user = turn.messages.find(m => m.role === "user" && typeof m.content === "string");
    if (user) {
      const savedFiles = (turn.usage?.attachments || []).map(file =>
        ({...file, ...(turn.attachment_previews || []).find(preview => preview.name === file.name)}));
      const message = addMessage("user", savedFiles.length ? turn.usage.display_question : user.content, turn.id);
      message.editText = user.content;
      if (savedFiles.length) renderAttachmentCards(message.body, savedFiles, false);
    }
    let bot;
    for (const msg of turn.messages) {
      if (msg.role !== "assistant" || !Array.isArray(msg.content)) continue;
      const text = msg.content.filter(b => b.type === "text").map(b => b.text).join("\n\n");
      if (text) {
        if (!bot) bot = addMessage("assistant", text, turn.id);
        else { bot.text += "\n\n" + text; renderAnswer(bot.body, bot.text); }
      }
    }
    if (bot && turn.usage?.model) {
      updateModelInfo(bot, turn.usage);
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
  if (busy || (!question.trim() && !pendingAttachments.length)) return;
  const pending = initializingChat || restoringChat || openingChat;
  if (pending) {
    if (queuedAsk) return;
    queuedAsk = true;
    try { await pending; }
    catch (error) { $("#activity").textContent = error.message; return; }
    finally { queuedAsk = false; }
    return ask(question);
  }
  if (pagesPreview) {
    $("#activity").textContent = "Backend not connected. Open your local AiMate workspace for live AI and project access.";
    return;
  }
  if (!demo && !aiReady()) {
    openSettings(); $("#settingsStatus").textContent = "Add your AI credentials and model ID to start."; return;
  }
  const attachments = [...pendingAttachments];
  const submittedQuestion = [question.trim() || "Read the attached files.", ...attachments.map(file => `\nAttached ${file.kind === "image" ? "image" : "file"}: ${file.name}\n${file.text || ""}`)].join("\n");
  if (submittedQuestion.length > 30000) {
    $("#activity").textContent = "Message and attached files exceed 30,000 characters. Remove a file or shorten the message.";
    return;
  }
  busy = true;
  document.querySelectorAll("[data-edit-message]").forEach(button => { button.disabled = true; });
  $("#send").disabled = true;
  $("#modelMode").disabled = true;
  $("#stop").hidden = false;
  controller = new AbortController();
  let bot;
  try {
    if (!cid) {
      cid = (await api("/api/conversations", {method: "POST",body:JSON.stringify({private:privateChat})})).id;
      if(!privateChat) try { localStorage.setItem("aimate.conversation", cid); } catch { /* optional browser persistence */ }
    }
    const userMessage = addMessage("user", question.trim() || "Read the attached files.");
    if (attachments.length) renderAttachmentCards(userMessage.body, attachments, false);
    bot = addMessage("assistant");
    $("#question").value = "";
    pendingAttachments = []; renderPendingAttachments();
    $("#activity").textContent = "Reading your question…";
    const response = await api("/api/chat", {
      method: "POST", body: JSON.stringify({conversation: cid, question: submittedQuestion, model_mode: $("#modelMode").value,
        attachments:attachments.filter(file=>file.kind !== "image").map(({name,size})=>({name,size})),
        images:attachments.filter(file=>file.kind === "image").map(({name,data})=>({name,data})),
        display_question:question.trim() || "Read the attached files."}),
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
        if (event.event === "model") {
          renderModelSelection(event);
          updateModelInfo(bot, event);
          $("#activity").textContent = "Thinking…";
        }
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
          if (bot.modelDetails) updateModelInfo(bot, {...bot.modelDetails, usage:event.usage});
          $("#activity").textContent = "Answer complete";
        }
        scrollMessages();
      }
    }
    const saved = await api(`/api/conversations/${cid}`);
    userMessage.turnId = saved.turns.at(-1)?.id || null;
    bot.turnId = userMessage.turnId;
    await refreshState();
  } catch (error) {
    $("#activity").textContent = error.name === "AbortError" ? "Stopped. An incomplete answer is not saved." : bot ? "Request failed. See the details above." : error.message;
    if (bot && error.name !== "AbortError") bot.root.append(element("p", "error", error.message));
  } finally {
    if (bot?.renderFrame) cancelAnimationFrame(bot.renderFrame);
    if (bot) renderAnswer(bot.body, bot.text);
    busy = false; $("#send").disabled = false; $("#modelMode").disabled = false; $("#stop").hidden = true; controller = null;
    document.querySelectorAll("[data-edit-message]").forEach(button => { button.disabled = false; });
    void syncConnections();
  }
}

function openSettings() {
  dirtyConnections.clear();
  const form = $("#settingsForm");
  for (const input of form.elements) input.disabled = demo || !(access.configure_connections ?? access.configure);
  form.elements.allow_writes.disabled = demo || !access.configure;
  $("#openAudit").disabled = !access.audit;
  $("#saveConnection").hidden = !(access.configure_connections ?? access.configure);
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
  $("#settingsStatus").textContent = pagesPreview ? "Backend not connected. Credentials cannot be saved on this preview." : demo ? "Fixed fictional connections. Restart in live mode to configure real services." : "";
  form.elements["jira.mode"].value = config.jira?.mode || (config.jira?.auth === "basic" ? "advanced" : "simple");
  form.elements["jira.access"].value = config.jira?.access || "selected";
  form.elements["jenkins.mode"].value = config.jenkins?.mode || "simple";
  form.elements["jenkins.access"].value = config.jenkins?.access || (config.jenkins?.jobs?.length ? "selected" : "all");
  for (const key of ["url", "username"]) {
    if (!form.elements["jenkins." + key].value) form.elements["jenkins." + key].value = connectionDefaults.jenkins?.[key] || "";
  }
  $("#jenkinsAccount").open = !form.elements["jenkins.url"].value || !form.elements["jenkins.username"].value;
  form.elements["ai.bedrock_mode"].value = config.ai?.bedrock_mode ||
    (config.ai?.provider === "bedrock" && (config.ai?.model || config.ai?.bedrock_auth === "iam" || config.ai?.bedrock_endpoint === "mantle") ? "advanced" : "simple");
  if (!form.elements["ai.region"].value) form.elements["ai.region"].value = "us-east-2";
  updateJenkinsSetup();
  updateJiraSetup();
  updateProvider();
  selectSettingsTab(activeSettings);
  for (const service of ["ai", "github", "jira", "jenkins"]) renderConnection(service);
  $("#settingsDialog").showModal();
  if (!demo && access.configure) void loadOtpStatus().catch(() => {});
}

async function updateProvider() {
  const form = $("#settingsForm"), selected = form.elements["ai.provider"].value === "chatgpt";
  bedrockPresetEndpoint = "";
  $("#analysisModelLabel").hidden = selected;
  $("#chatgptAnalysisLabel").hidden = !selected;
  if (!selected) {
    const sameProvider = form.elements["ai.provider"].value === config.ai?.provider;
    form.elements["ai.model"].value = sameProvider ? config.ai?.model || "" : "";
    form.elements["ai.analysis_model"].value = sameProvider ? config.ai?.analysis_model || "" : "";
    form.elements["ai.api_key"].placeholder = sameProvider && config.ai?.api_key_configured
      ? "Saved · leave blank to keep" : "Enter this provider's key";
  }
  const generation = ++modelLoad;
  $("#chatgptAnalysisModel").replaceChildren(element("option", "", "Use Standard only"));
  $("#chatgptAnalysisModel").firstChild.value = "";
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
    const analysisPicker = $("#chatgptAnalysisModel");
    analysisPicker.replaceChildren(element("option", "", "Use Standard only"));
    analysisPicker.firstChild.value = "";
    for (const model of result.models) {
      const option = element("option", "", model.display_name);
      option.value = model.slug;
      picker.append(option);
      const analysisOption = element("option", "", model.display_name);
      analysisOption.value = model.slug;
      analysisPicker.append(analysisOption);
    }
    if (result.models.some(m => m.slug === config.ai?.model)) picker.value = config.ai.model;
    analysisPicker.value = config.ai?.analysis_model || "";
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
  const simple = bedrock && form.elements["ai.bedrock_mode"].value === "simple";
  const iam = bedrock && !simple && form.elements["ai.bedrock_auth"].value === "iam";
  $("#bedrockSetup").hidden = !bedrock;
  $("#bedrockSimpleHint").hidden = !simple;
  $("#bedrockSettings").hidden = !bedrock || simple;
  $("#bedrockModelChoices").hidden = !bedrock || simple;
  $("#bedrockAnalysisLabel").hidden = !bedrock;
  $("#apiModelLabel").hidden = simple || form.elements["ai.provider"].value === "chatgpt" || (bedrock && $("#bedrockModel").value !== "custom");
  $("#analysisModelLabel").hidden = form.elements["ai.provider"].value === "chatgpt" || (bedrock && $("#bedrockAnalysisModel").value !== "custom");
  $("#awsCredentials").hidden = !iam;
  $("#aiKeyLabel").hidden = iam;
  $("#removeAIKey").hidden = iam || form.elements["ai.provider"].value === "chatgpt";
  form.elements["ai.bedrock_endpoint"].querySelector('[value="mantle"]').disabled = iam;
  if (iam) form.elements["ai.bedrock_endpoint"].value = "runtime";
  if (bedrock) void populateBedrockModels();
}
function renderBedrockModels() {
  const form = $("#settingsForm");
  for (const [pickerId, field, optional] of [["bedrockModel", "ai.model", false], ["bedrockAnalysisModel", "ai.analysis_model", true]]) {
    const picker = $("#" + pickerId), current = form.elements[field].value;
    picker.replaceChildren();
    if (optional) { const option = element("option", "", "Use Standard only"); option.value = ""; picker.append(option); }
    for (const model of bedrockCatalog) {
      const option = element("option", "", model.label + " · " + model.source);
      option.value = model.id; option.title = model.id; picker.append(option);
    }
    const custom = element("option", "", "Custom model / profile ID"); custom.value = "custom"; picker.append(custom);
    picker.value = current && bedrockCatalog.some(m => m.id === current) ? current : optional && !current ? "" : "custom";
  }
  $("#apiModelLabel").hidden = form.elements["ai.bedrock_mode"].value === "simple" || $("#bedrockModel").value !== "custom";
  $("#analysisModelLabel").hidden = $("#bedrockAnalysisModel").value !== "custom";
}
async function populateBedrockModels(discover = false) {
  const endpoint = $("#settingsForm").elements["ai.bedrock_endpoint"].value;
  if (!discover && bedrockPresetEndpoint === endpoint && bedrockCatalog.length) { renderBedrockModels(); return; }
  const generation = ++bedrockCatalogLoad;
  $("#refreshBedrockModels").disabled = true;
  try {
    const result = await api("/api/bedrock/models" + (discover ? "?discover=true" : ""));
    if (generation !== bedrockCatalogLoad || $("#settingsForm").elements["ai.provider"].value !== "bedrock") return;
    if (discover && (dirtyConnections.has("ai") || endpoint !== config.ai?.bedrock_endpoint)) {
      $("#bedrockModelsHint").textContent = "Save your Bedrock settings first, then refresh the selected region and endpoint.";
      return;
    }
    const presets = result.presets.map(m => ({...m, id: endpoint === "mantle" ? m.id.replace(/^us\./, "") : m.id.startsWith("us.") ? m.id : "us." + m.id}));
    bedrockCatalog = [...new Map([...presets, ...result.models].map(m => [m.id, m])).values()];
    bedrockPresetEndpoint = endpoint;
    $("#bedrockModelsHint").textContent = result.message;
    renderBedrockModels();
  } catch (error) { $("#bedrockModelsHint").textContent = error.message; }
  finally { if (generation === bedrockCatalogLoad) $("#refreshBedrockModels").disabled = false; }
}
$("#refreshBedrockModels").onclick = () => {
  if (dirtyConnections.has("ai")) { $("#bedrockModelsHint").textContent = "Save your AI connection first, then refresh models."; return; }
  void populateBedrockModels(true);
};
for (const [pickerId, field] of [["bedrockModel", "ai.model"], ["bedrockAnalysisModel", "ai.analysis_model"]]) {
  $("#" + pickerId).onchange = () => {
    const value = $("#" + pickerId).value;
    if (value !== "custom") $("#settingsForm").elements[field].value = value;
    if (field === "ai.model") $("#apiModelLabel").hidden = value !== "custom";
    else $("#analysisModelLabel").hidden = value !== "custom";
  };
}
$("#settingsForm").elements["ai.bedrock_endpoint"].onchange = () => {
  bedrockPresetEndpoint = "";
  updateBedrock();
};
$("#settingsForm").elements["ai.region"].onchange = () => {
  bedrockPresetEndpoint = "";
  updateBedrock();
};
$("#settingsForm").elements["ai.bedrock_auth"].onchange = updateBedrock;
$("#settingsForm").elements["ai.bedrock_mode"].onchange = () => {
  const form = $("#settingsForm");
  if (form.elements["ai.bedrock_mode"].value === "advanced" && !form.elements["ai.model"].value) {
    form.elements["ai.model"].value = "us.anthropic.claude-haiku-5-5";
  }
  updateBedrock();
};
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
  const button = $("#loginForm").querySelector('[type="submit"]');
  button.disabled = true;
  try {
    const role = $("#loginRole").value;
    const data = await api(role !== "admin" ? "/api/access/login" : loginUsesOtp ? "/api/login/otp" : loginOptions.dev_login ? "/api/dev/login" : "/api/login", {method: "POST",
      body: JSON.stringify(role !== "admin" ? {role,code:$("#accessCode").value.trim(),otp:$("#loginOtp").value.trim()} : loginUsesOtp ? {code:$("#loginOtp").value.trim()} : {password: $("#password").value})});
    csrf = data.csrf;
    $("#password").value = "";
    $("#loginOtp").value = "";
    $("#accessCode").value = "";
    $("#loginError").textContent = "";
    await refreshState();
    await restoreConversation();
  } catch (error) { $("#loginError").textContent = error.message; }
  finally { button.disabled = false; }
};
function configureLogin(mode, authenticator = false) {
  loginOptions = mode;
  loginUsesOtp = Boolean(mode.otp_enabled) && (!mode.dev_login || authenticator);
  recoveryLogin = false;
  $("#passwordLogin").hidden = loginUsesOtp;
  $("#password").required = !loginUsesOtp;
  $("#otpLogin").hidden = !loginUsesOtp;
  $("#loginOtp").required = loginUsesOtp;
  $("#loginOtp").inputMode = "numeric";
  $("#loginOtp").placeholder = "6-digit code";
  $("#otpLoginLabel").textContent = "Authenticator code";
  $("#useRecoveryCode").hidden = !loginUsesOtp;
  $("#useRecoveryCode").textContent = "Use a recovery code";
  $("#useDevLogin").hidden = !mode.otp_enabled || !mode.dev_login || mode.demo;
  $("#useDevLogin").textContent = loginUsesOtp ? "Continue in dev mode" : "Use authenticator instead";
  $("#localPasswordHint").hidden = loginUsesOtp || Boolean(mode.demo || mode.hosted);
  $("#password").value = ""; $("#loginOtp").value = "";
  updateLoginRole();
}
function updateLoginRole() {
  const delegated = $("#loginRole").value !== "admin";
  const bypass = loginOptions.dev_login && !loginUsesOtp && !delegated;
  $("#accessCodeLogin").hidden = !delegated; $("#accessCode").required = delegated;
  $("#passwordLogin").hidden = delegated || loginUsesOtp || bypass; $("#password").required = !delegated && !loginUsesOtp && !bypass;
  $("#loginForm").querySelector('[type="submit"]').textContent = bypass ? "Open dev workspace →" : "Open workspace →";
  if (bypass) $("#localPasswordHint").hidden = true;
  const needsOtp = delegated ? loginOptions.environment === "production" : loginUsesOtp;
  $("#otpLogin").hidden = !needsOtp; $("#loginOtp").required = needsOtp;
  if (delegated) { $("#localPasswordHint").hidden=true; $("#useRecoveryCode").hidden=true; $("#useDevLogin").hidden=true; }
}
$("#loginRole").onchange = () => configureLogin(loginOptions);
async function loadAccessGrants() {
  const data = await api("/api/access/grants"), list=$("#accessGrantList");list.replaceChildren();
  for(const grant of data.grants) {
    const row=element("div","access-grant");row.append(element("span","",`${grant.name} · ${grant.role}${grant.revoked ? " · Revoked" : ""}`));
    if(!grant.revoked) {
      const role=element("select","access-role");
      role.setAttribute("aria-label","Role for "+grant.name);
      for(const [value,label] of [["viewer","Viewer"],["reviewer","Reviewer"],["developer","Developer"]]) {
        const option=element("option","",label);option.value=value;role.append(option);
      }
      role.value=grant.role;
      role.onchange=async()=>{role.disabled=true;try{await api(`/api/access/grants/${grant.id}`,{method:"PATCH",body:JSON.stringify({role:role.value})});await loadAccessGrants();}catch(error){role.value=grant.role;role.disabled=false;$("#accessError").textContent=error.message;}};
      row.append(role);
      const revoke=element("button","","Revoke");revoke.type="button";
      revoke.onclick=async()=>{try{await api(`/api/access/grants/${grant.id}`,{method:"DELETE"});await loadAccessGrants();}catch(error){$("#accessError").textContent=error.message;}};
      row.append(revoke);
    }
    list.append(row);
  }
}
$("#openAccess").onclick=async()=>{
  $("#newAccessCode").hidden=true;$("#accessCodeValue").textContent="";$("#accessAuthenticatorSecret").textContent="";$("#accessAuthenticatorQr").removeAttribute("src");$("#accessError").textContent="";
  $("#accessDialog").showModal();try{await loadAccessGrants();}catch(error){$("#accessError").textContent=error.message;}
};
$("#accessForm").onsubmit=async event=>{
  event.preventDefault();try {
    const result=await api("/api/access/grants",{method:"POST",body:JSON.stringify({name:$("#accessName").value,role:$("#accessRole").value})});
    $("#accessCodeValue").textContent=result.code;$("#accessAuthenticatorSecret").textContent=result.authenticator_secret;$("#accessAuthenticatorQr").src=result.qr;$("#newAccessCode").hidden=false;await loadAccessGrants();
  }catch(error){$("#accessError").textContent=error.message;}
};
$("#copyAccessCode").onclick=async()=>{try{await navigator.clipboard.writeText($("#accessCodeValue").textContent);$("#copyAccessCode").textContent="Copied";}catch{$("#accessError").textContent="Select the code to copy it."; }};
$("#accessDialog").onclose=()=>{$("#accessCodeValue").textContent="";$("#accessAuthenticatorSecret").textContent="";$("#accessAuthenticatorQr").removeAttribute("src");$("#newAccessCode").hidden=true;};
$("#useRecoveryCode").onclick = () => {
  recoveryLogin = !recoveryLogin;
  $("#otpLoginLabel").textContent = recoveryLogin ? "Recovery code" : "Authenticator code";
  $("#loginOtp").inputMode = recoveryLogin ? "text" : "numeric";
  $("#loginOtp").placeholder = recoveryLogin ? "Your unused recovery code" : "6-digit code";
  $("#loginOtp").value = "";
  $("#useRecoveryCode").textContent = recoveryLogin ? "Use authenticator code" : "Use a recovery code";
  $("#loginOtp").focus();
};
$("#useDevLogin").onclick = () => configureLogin(loginOptions, !loginUsesOtp);
$("#demoLogin").onclick = async () => {
  try {
    const data = await api("/api/demo/login", {method: "POST"});
    csrf = data.csrf;
    await refreshState();
    await restoreConversation();
  } catch (error) { $("#loginError").textContent = error.message; }
};
$("#chatForm").onsubmit = event => { event.preventDefault(); ask($("#question").value); };
$("#privateToggle").onclick=async()=>{
  if(busy) return;
  const next=!privateChat;
  if(cid) {cid=null;$("#messages").replaceChildren();$("#welcome").hidden=false;try{localStorage.removeItem("aimate.conversation");}catch{}}
  privateChat=next;$("#privateToggle").setAttribute("aria-pressed",String(next));
  $("#chatTitle").textContent=next ? "Private chat" : "Ask your project";
  $("#activity").textContent=next ? "Session only · no saved history or cross-chat recall. Your AI provider receives the prompt." : "";
};
function setFeedbackRating(rating) {
  feedbackRating=rating;$("#feedbackPositive").setAttribute("aria-pressed",String(rating==="positive"));
  $("#feedbackNegative").setAttribute("aria-pressed",String(rating==="negative"));
  $("#feedbackCategory").value=rating==="positive" ? "helpful" : "accuracy";
}
$("#feedbackPositive").onclick=()=>setFeedbackRating("positive");
$("#feedbackNegative").onclick=()=>setFeedbackRating("negative");
$("#feedbackForm").onsubmit=async event=>{
  event.preventDefault();try{
    await api("/api/feedback",{method:"POST",body:JSON.stringify({conversation:cid,turn:feedbackMessage.turnId,rating:feedbackRating,category:$("#feedbackCategory").value,comment:$("#feedbackComment").value})});
    $("#feedbackDialog").close();$("#activity").textContent="Feedback saved. Thank you.";
  }catch(error){$("#feedbackError").textContent=error.message;}
};
$("#openFeedbackLog").onclick=async()=>{try{
  const data=await api("/api/feedback");$("#auditContent").textContent=data.entries.length ? JSON.stringify(data.entries,null,2) : "No feedback yet.";$("#auditDialog").querySelector("h2").textContent="Feedback";$("#auditDialog").showModal();
}catch(error){$("#settingsStatus").textContent=error.message;}};
let vaultTimer = null, vaultViewVersion = 0;
async function loadVault() {
  const version = ++vaultViewVersion;
  clearTimeout(vaultTimer);
  const status = await api("/api/vault/status");
  if (version !== vaultViewVersion || !$("#vaultDialog").open) return;
  $("#vaultUnlockForm").hidden = status.unlocked;
  $("#lockVault").hidden = !status.unlocked;
  $("#vaultEditor").hidden = !status.unlocked;
  $("#vaultEntries").replaceChildren();
  $("#vaultLockStatus").textContent = status.unlocked ? "Unlocked · locks automatically after 5 minutes" : "Locked · AI access also disabled";
  $("#vaultUnlockLabel").textContent = status.otp ? "Fresh authenticator code" : "Workspace password";
  if (!status.unlocked) return;
  vaultTimer = setTimeout(() => { void lockPrivateVault(); }, Math.max(1,status.seconds_remaining) * 1000);
  const data=await api("/api/vault"),list=$("#vaultEntries");
  if (version !== vaultViewVersion || !$("#vaultDialog").open) return;
  list.replaceChildren();
  for(const entry of data.entries) {
    const card=element("article","knowledge-card");card.append(element("h3","",entry.name),element("p","hint",entry.ai_access ? "AI access allowed" : "Private"));
    const value=element("pre","vault-revealed");value.hidden=true;card.append(value);
    const controls=element("div","knowledge-actions");
    const reveal=element("button","","Reveal"),edit=element("button","","Replace"),remove=element("button","error","Delete");
    for(const button of [reveal,edit,remove])button.type="button";
    reveal.onclick=async()=>{try{
      if(!value.hidden){value.textContent="";value.hidden=true;reveal.textContent="Reveal";return;}
      const result=await api(`/api/vault/${entry.id}/reveal`,{method:"POST"});
      if (version !== vaultViewVersion || !$("#vaultDialog").open) return;
      value.textContent=result.value;value.hidden=false;reveal.textContent="Hide";
      setTimeout(()=>{value.textContent="";value.hidden=true;reveal.textContent="Reveal";},30000);
    }catch(error){$("#vaultError").textContent=error.message;}};
    edit.onclick=()=>{vaultEditId=entry.id;$("#vaultName").value=entry.name;$("#vaultValue").value="";$("#vaultAiAccess").checked=Boolean(entry.ai_access);$("#vaultEditor").open=true;$("#vaultValue").focus();};
    remove.onclick=async()=>{if(!confirm(`Delete vault entry “${entry.name}”?`))return;try{await api(`/api/vault/${entry.id}`,{method:"DELETE"});await loadVault();}catch(error){$("#vaultError").textContent=error.message;}};
    controls.append(reveal,edit,remove);card.append(controls);list.append(card);
  }
}
$("#openVault").onclick=async()=>{vaultEditId=null;$("#vaultForm").reset();$("#vaultError").textContent="";$("#vaultEditor").open=false;$("#vaultDialog").showModal();try{await loadVault();}catch(error){$("#vaultError").textContent=error.message;}};
$("#vaultForm").onsubmit=async event=>{
  event.preventDefault();try{
    await api(vaultEditId ? `/api/vault/${vaultEditId}` : "/api/vault",{method:vaultEditId ? "PATCH" : "POST",body:JSON.stringify({name:$("#vaultName").value,value:$("#vaultValue").value,ai_access:$("#vaultAiAccess").checked})});
    vaultEditId=null;$("#vaultForm").reset();$("#vaultEditor").open=false;await loadVault();
  }catch(error){$("#vaultError").textContent=error.message;}
};
async function lockPrivateVault() {
  vaultViewVersion++;
  clearTimeout(vaultTimer);
  $("#vaultVerification").value = ""; $("#vaultValue").value = "";
  $("#vaultEntries").replaceChildren(); $("#vaultEditor").hidden = true;
  $("#lockVault").hidden = true; $("#vaultUnlockForm").hidden = false;
  $("#vaultLockStatus").textContent = "Locked · AI access also disabled";
  try { await api("/api/vault/lock", {method:"POST"}); }
  catch (error) { if ($("#vaultDialog").open) $("#vaultError").textContent = error.message; }
}
$("#lockVault").onclick = lockPrivateVault;
$("#vaultUnlockForm").onsubmit = async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button"); button.disabled = true;
  try {
    await api("/api/vault/unlock", {method:"POST",body:JSON.stringify({verification:$("#vaultVerification").value})});
    $("#vaultVerification").value = ""; $("#vaultError").textContent = "";
    if (!$("#vaultDialog").open) { await lockPrivateVault(); return; }
    await loadVault();
  } catch (error) { $("#vaultError").textContent = error.message; }
  finally { button.disabled = false; }
};
$("#vaultDialog").onclose=()=>{
  vaultViewVersion++;
  $("#vaultVerification").value = ""; $("#vaultValue").value = "";
  $("#vaultEntries").replaceChildren(); $("#vaultEditor").hidden = true;
};
document.addEventListener("visibilitychange", () => {
  if (document.hidden && !$("#lockVault").hidden) void lockPrivateVault();
});
function chatInputAvailable(target) {
  return !$("#workspace").hidden && !document.querySelector("dialog[open], .conversation-context:not([hidden])") &&
    !target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]');
}
function insertQuestion(text) {
  const field = $("#question");
  const room = field.maxLength - (field.value.length - (field.selectionEnd - field.selectionStart));
  field.setRangeText(text.slice(0, Math.max(0, room)), field.selectionStart, field.selectionEnd, "end");
  field.focus({preventScroll: true});
  field.dispatchEvent(new Event("input", {bubbles: true}));
  if (text.length > room) $("#activity").textContent = "Input limit reached · some text was omitted.";
}
async function addTextFiles(files) {
  for (const file of files) {
    if (pendingAttachments.length >= 6) { $("#activity").textContent = "Attach up to 6 files per message."; break; }
    if (/^image\/(png|jpeg|webp|gif)$/.test(file.type) || /\.(png|jpe?g|webp|gif)$/i.test(file.name)) {
      if (file.size > 12 * 1024 * 1024 || pendingAttachments.filter(item=>item.kind === "image").length >= 4) {
        $("#activity").textContent = "Use up to 4 images, under 12 MB each."; continue;
      }
      try {
        const source = await fileDataUrl(file), picture = new Image();
        picture.src = source; await picture.decode();
        const ratio = Math.min(1, 2048 / Math.max(picture.width, picture.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(picture.width * ratio));
        canvas.height = Math.max(1, Math.round(picture.height * ratio));
        const context = canvas.getContext("2d");
        context.fillStyle = "#fff"; context.fillRect(0,0,canvas.width,canvas.height);
        context.drawImage(picture,0,0,canvas.width,canvas.height);
        const preview = canvas.toDataURL("image/jpeg", .9), data = preview.split(",")[1];
        if (data.length + pendingAttachments.reduce((n,item)=>n+(item.data?.length || 0),0) > 8_000_000) {
          $("#activity").textContent = "Images are too large together. Remove one or use a smaller screenshot."; continue;
        }
        pendingAttachments.push({id:crypto.randomUUID(),name:file.name || "Screenshot.jpg",size:Math.ceil(data.length * .75),kind:"image",preview,data});
        renderPendingAttachments(); $("#activity").textContent = "Image attached."; $("#question").focus({preventScroll:true});
      } catch { $("#activity").textContent = "This image could not be read. Try a PNG or JPEG."; }
      continue;
    }
    if (/\.pdf$/i.test(file.name)) {
      if (file.size > 4 * 1024 * 1024) { $("#activity").textContent = "Use a PDF under 4 MB."; continue; }
      try {
        $("#activity").textContent = "Reading PDF…";
        const data = (await fileDataUrl(file)).split(",")[1];
        const result = await api("/api/attachments/pdf",{method:"POST",body:JSON.stringify({name:file.name,data})});
        if (result.text.length + pendingAttachments.reduce((n,item)=>n+(item.text?.length || 0),0) > 28000) throw new Error("Combined file text exceeds 28,000 characters.");
        pendingAttachments.push({...result,id:crypto.randomUUID()});
        renderPendingAttachments(); $("#activity").textContent = "PDF attached."; $("#question").focus({preventScroll:true});
      } catch(error) { $("#activity").textContent = error.message; }
      continue;
    }
    if (!/\.(txt|log|md|csv|json|ya?ml|xml|html|css|[jt]sx?|py|sh|ps1|sql|toml|ini|cfg|c|cpp|h|java|go|rs)$/i.test(file.name) || file.size > 1024 * 1024) {
      $("#activity").textContent = "Attach an image, PDF, or text/code/log file. Binary files cannot be read.";
      continue;
    }
    const text = await file.text();
    if (text.includes("\0")) { $("#activity").textContent = "This file contains binary data. Use a text file."; continue; }
    if (pendingAttachments.length >= 6) { $("#activity").textContent = "Attach up to 6 files per message."; break; }
    if (text.length + pendingAttachments.reduce((total, item) => total + (item.text?.length || 0), 0) > 28000) {
      $("#activity").textContent = "Attached files exceed 28,000 characters. Use a smaller file or excerpt."; continue;
    }
    pendingAttachments.push({id:crypto.randomUUID(), name:file.name, size:file.size, text});
    renderPendingAttachments();
    $("#question").focus({preventScroll:true});
  }
}
function fileDataUrl(file) {
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error("Could not read this file."));reader.readAsDataURL(file);});
}
function renderAttachmentCards(container, files, removable = true) {
  for (const file of files) {
    const card = element("div", "attachment-card");
    const icon = element("span", "attachment-file-icon");
    if (file.kind === "image" && /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(file.preview || "")) {
      const image = document.createElement("img"); image.src=file.preview; image.alt=file.name; image.className="attachment-preview"; icon.append(image);
    } else icon.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>';
    icon.setAttribute("aria-hidden", "true");
    const info = element("div", "attachment-info");
    const name = element("strong", "", file.name); name.title = file.name;
    info.append(name, element("small", "", `${file.size < 1024 ? file.size + " B" : (file.size / 1024).toFixed(1) + " KB"} · ${file.kind === "image" ? "Image" : file.kind === "pdf" ? "PDF" : "Text file"}`));
    card.append(icon, info);
    if (removable) {
      const remove = element("button", "attachment-remove", "×"); remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.onclick = () => { pendingAttachments = pendingAttachments.filter(item => item.id !== file.id); renderPendingAttachments(); };
      card.append(remove);
    }
    container.append(card);
  }
}
function renderPendingAttachments() {
  const container = $("#attachmentCards"); container.replaceChildren();
  renderAttachmentCards(container, pendingAttachments);
  container.hidden = !pendingAttachments.length;
  $("#question").required = !pendingAttachments.length;
}
$("#attachText").onclick = () => $("#textAttachment").click();
$("#textAttachment").onchange = async event => {
  await addTextFiles(event.target.files);
  event.target.value = "";
};
document.addEventListener("keydown", event => {
  if (event.defaultPrevented || event.isComposing || !chatInputAvailable(event.target)) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
    $("#question").focus({preventScroll: true}); return;
  }
  if (event.ctrlKey || event.metaKey || event.altKey || event.key.length !== 1 ||
      (event.key === " " && event.target.closest?.("button, a, summary"))) return;
  event.preventDefault();
  insertQuestion(event.key);
});
document.addEventListener("paste", event => {
  if ($("#workspace").hidden || document.querySelector("dialog[open]")) return;
  if (event.target !== $("#question") && !chatInputAvailable(event.target)) return;
  const files = [...(event.clipboardData?.files || [])];
  if (files.length) {
    event.preventDefault(); void addTextFiles(files); return;
  }
  const text = event.clipboardData?.getData("text/plain");
  if (text && event.target !== $("#question")) { event.preventDefault(); insertQuestion(text); }
});
document.addEventListener("dragover", event => {
  if (!$("#workspace").hidden && !document.querySelector("dialog[open]") && event.dataTransfer?.types.includes("Files")) event.preventDefault();
});
document.addEventListener("drop", event => {
  if (!$("#workspace").hidden && !document.querySelector("dialog[open]") && event.dataTransfer?.files.length &&
      (event.target.closest?.(".composer") || chatInputAvailable(event.target))) {
    event.preventDefault(); void addTextFiles([...event.dataTransfer.files]);
  }
});
$("#question").onkeydown = event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask($("#question").value); }
};
$("#stop").onclick = () => controller?.abort();
$("#newChat").onclick = async () => {
  if (busy) return;
  navigationVersion++;
  archiveView = false; pendingAttachments = []; renderPendingAttachments();
  cid = null; $("#messages").replaceChildren(); $("#welcome").hidden = false;
  privateChat = false;$("#privateToggle").setAttribute("aria-pressed","false");
  try { localStorage.removeItem("aimate.conversation"); } catch { /* optional browser persistence */ }
  $("#chatTitle").textContent = "Ask your project"; $("#activity").textContent = "";
  await refreshState();
};
$("#archiveView").onclick = async () => {
  if (busy) return;
  archiveView = !archiveView;
  await refreshState();
};
async function setChatArchived(thread) {
  await api(`/api/conversations/${thread.id}`, {method:"PATCH", body:JSON.stringify({archived:!thread.archived})});
  if (!thread.archived && cid === thread.id) {
    cid = null; $("#messages").replaceChildren(); $("#welcome").hidden = false;
    $("#chatTitle").textContent = "Ask your project";
    try { localStorage.removeItem("aimate.conversation"); } catch {}
  }
  $("#activity").textContent = thread.archived ? "Conversation restored." : "Conversation archived.";
  await refreshState();
}
$("#archiveChat").onclick = async () => {
  const thread = conversationList.find(t => t.id === cid);
  if (!thread || busy) return;
  $("#chatMenu").open = false;
  try { await setChatArchived(thread); } catch (error) { $("#activity").textContent = error.message; }
};
let conversationAction = "rename", conversationActionId = null;
async function copyFormatted(markdown) {
  if (window.ClipboardItem && navigator.clipboard.write) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        "text/plain": new Blob([markdown], {type: "text/plain"}),
        "text/html": new Blob([answerMarkdown.render(markdown)], {type: "text/html"}),
      })]);
      return;
    } catch { /* Fall back to portable Markdown when rich clipboard is unavailable. */ }
  }
  await navigator.clipboard.writeText(markdown);
}
function openConversationAction(action, targetId = cid) {
  if (!targetId || busy) return;
  $("#chatMenu").open = false;
  conversationAction = action; conversationActionId = targetId;
  const removing = action === "delete";
  const moving = action === "move";
  $("#conversationDialogTitle").textContent = removing ? "Delete conversation?" : moving ? "Move conversation" : "Rename conversation";
  $("#conversationNameLabel").hidden = removing || moving;
  $("#conversationGroupLabel").hidden = !moving;
  groupOptions($("#conversationGroup"), "Workspace · standalone");
  $("#conversationGroup").value = conversationList.find(thread => thread.id === targetId)?.group_id || "";
  $("#conversationName").value = conversationList.find(thread => thread.id === targetId)?.title || $("#chatTitle").textContent;
  $("#conversationName").required = !removing && !moving;
  $("#conversationDeleteHint").hidden = !removing;
  $("#conversationActionSubmit").textContent = removing ? "Delete conversation" : moving ? "Move chat" : "Save name";
  $("#conversationActionSubmit").className = removing ? "danger-button" : "primary";
  $("#conversationActionError").textContent = "";
  $("#conversationDialog").showModal();
  if (!removing && !moving) { $("#conversationName").focus(); $("#conversationName").select(); }
}
$("#renameChat").onclick = () => openConversationAction("rename");
$("#moveChat").onclick = () => openConversationAction("move");
$("#deleteChat").onclick = () => openConversationAction("delete");
const conversationContext = element("div", "conversation-context");
conversationContext.hidden = true;
conversationContext.setAttribute("role", "menu");
conversationContext.setAttribute("aria-label", "Conversation actions");
document.body.append(conversationContext);
function showConversationContext(thread, x, y) {
  if (busy) return;
  conversationContext.replaceChildren();
  for (const [label, action] of [["Rename", "rename"], ["Change icon", "icon"], ["Move to project / workspace", "move"],
    [thread.pinned ? "Unpin" : "Pin", "pin"], ["Copy chat", "copy"], ["Export (.md)", "md"],
    ["Export (.txt)", "txt"], [thread.archived ? "Restore" : "Archive", "archive"], ["Delete", "delete"]]) {
    if (thread.private && !["copy","md","txt","delete"].includes(action)) continue;
    if (!access.manage_records && !["copy","md","txt"].includes(action) && !(thread.private && action === "delete")) continue;
    const button = element("button", action === "delete" ? "error" : "", label);
    const paths = {
      rename:'<path d="m16 3 5 5-12 12-6 1 1-6ZM14 5l5 5"/>',
      icon:'<circle cx="12" cy="12" r="9"/><path d="M8 14s1 3 4 3 4-3 4-3M8 9h.01M16 9h.01"/>',
      move:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Zm4 6h10m-3-3 3 3-3 3"/>',
      pin:'<path d="m16 3 5 5-4 1-3 5-4 1-1 4-4-4 4-1 1-4 5-3ZM5 19l-3 3"/>',
      copy:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
      md:'<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>',
      txt:'<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>',
      archive:thread.archived ? '<path d="M4 8h16v13H4ZM3 3h18v5H3Zm9 14V11m-3 3 3-3 3 3"/>' : '<path d="M4 8h16v13H4ZM3 3h18v5H3Zm6 10h6"/>',
      delete:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    };
    const icon = element("span", "menu-action-icon");
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[action]}</svg>`;
    button.replaceChildren(icon, element("span", "", label));
    button.type = "button"; button.setAttribute("role", "menuitem");
    button.onclick = async () => {
      conversationContext.hidden = true;
      if (action === "icon") { openConversationIcon(thread); return; }
      if (["rename", "move", "delete"].includes(action)) { openConversationAction(action, thread.id); return; }
      try {
        if (action === "archive") { await setChatArchived(thread); }
        else if (action === "pin") {
          await api(`/api/conversations/${thread.id}`, {method:"PATCH",body:JSON.stringify({pinned:!thread.pinned})});
          await refreshState();
        } else {
          const chat = await api(`/api/conversations/${thread.id}`);
          const text = conversationMarkdown(chat);
          if (action === "copy") { await copyFormatted(text); $("#activity").textContent = "Chat copied."; }
          else { downloadFile(text, `AiMate-${chat.id.slice(0,8)}.${action}`, action === "md" ? "text/markdown;charset=utf-8" : "text/plain;charset=utf-8"); $("#activity").textContent = `Chat exported (.${action}).`; }
        }
      } catch (error) { $("#activity").textContent = error.message; }
    };
    conversationContext.append(button);
  }
  conversationContext.hidden = false;
  conversationContext.style.left = Math.max(8, Math.min(x, innerWidth - conversationContext.offsetWidth - 8)) + "px";
  conversationContext.style.top = Math.max(8, Math.min(y, innerHeight - conversationContext.offsetHeight - 8)) + "px";
  conversationContext.firstChild.focus({preventScroll:true});
}
let conversationIconId = null;
const emojiCatalog = [
  ["💬","chat conversation"],["🐛","bug debug insect"],["📦","package repository box"],["📋","ticket task clipboard"],["🤖","robot ai"],["💰","money billing"],
  ["🧩","puzzle integration"],["🧪","test science lab"],["💻","computer code laptop"],["📊","chart data report"],["📖","book diary reading"],["🎨","art design"],
  ["⚡","energy performance lightning"],["🔐","security lock"],["🚀","rocket launch"],["⭐","star favorite"],
  ["🩺","health medical doctor"],["❤️","health heart love"],["💊","health medicine pill"],["🏥","health hospital"],["🧘","health wellness yoga"],
  ["🏫","school education"],["🎓","school graduation college"],["📚","school books learning"],["✏️","school pencil writing"],
  ["🏢","office building work"],["💼","office briefcase business"],["🗂️","office folders organization"],["📅","office calendar schedule"],
  ["🍔","food burger"],["🍕","food pizza"],["🍎","food apple fruit"],["🍲","food meal soup"],["☕","food coffee drink"],["🍰","food cake dessert"],
  ["🌸","flower blossom"],["🌹","flower rose"],["🌻","flower sunflower"],["🌷","flower tulip"],["💐","flower bouquet"],["🌼","flower daisy"],
  ["📝","notes text memo writing"],["📓","notes notebook journal"],["📔","notes notebook diary"],["📒","notes notebook ledger"],["📃","notes text page document"],
  ["📕","book reading red"],["📗","book reading green"],["📘","book reading blue"],["📙","book reading orange"],
  ["🏠","home house personal"],["🌍","world travel earth"],["✈️","travel flight plane"],["🚗","travel car transport"],["🚆","travel train rail transport"],["🚲","travel cycle bicycle bike transport"],["🚌","travel bus transport"],["🎵","music song"],["🎮","game gaming"],
  ["⚽","sport football"],["🏃","sport run fitness"],["🐶","dog animal pet"],["🐱","cat animal pet"],["🌿","plant nature garden"],["🔧","tools engineering"],
];
function renderEmojiChoices() {
  const query = $("#emojiSearch").value.trim().toLowerCase();
  const category = $("#emojiCategory").value;
  const matches = emojiCatalog.filter(([emoji, names]) =>
    (!category || names.includes(category)) && (!query || query.split(/\s+/).every(word => names.includes(word) || emoji.includes(word))));
  const choices = $("#conversationIconChoices"); choices.replaceChildren();
  for (const [emoji, names] of matches) {
    const button = element("button", "", emoji); button.type = "button"; button.title = names;
    button.setAttribute("aria-label", `Use ${names.split(" ").slice(0,2).join(" ")} ${emoji}`);
    button.onclick = () => { $("#conversationIconValue").value = emoji; $("#conversationIconError").textContent = ""; };
    choices.append(button);
  }
  $("#emojiSearchStatus").textContent = query && !matches.length ? "No match. You can paste any emoji below." : "";
}
function setIconMode(monogram) {
  $("#emojiIconMode").setAttribute("aria-pressed", !monogram);
  $("#monogramIconMode").setAttribute("aria-pressed", monogram);
  $("#emojiIconPanel").hidden = monogram;
  $("#conversationIconLabel").textContent = monogram ? "Initials" : "Emoji";
  $("#conversationIconValue").maxLength = monogram ? 3 : 16;
  $("#conversationIconValue").placeholder = monogram ? "AR, CI, DEV…" : "Paste an emoji, or choose above";
  $("#conversationIconHint").textContent = monogram ? "1–3 letters or numbers. Leave blank for the topic icon." : "Leave blank to use the topic icon.";
}
$("#emojiSearch").oninput = renderEmojiChoices;
$("#emojiCategory").onchange = renderEmojiChoices;
$("#emojiIconMode").onclick = () => { $("#conversationIconValue").value = ""; setIconMode(false); };
$("#monogramIconMode").onclick = () => { $("#conversationIconValue").value = ""; setIconMode(true); $("#conversationIconValue").focus(); };
function openConversationIcon(thread) {
  conversationIconId = thread.id;
  $("#conversationIconValue").value = thread.icon || "";
  $("#conversationIconError").textContent = "";
  $("#emojiSearch").value = "";
  $("#emojiCategory").value = "";
  setIconMode(Boolean(thread.icon && /^[A-Za-z0-9]{1,3}$/.test(thread.icon)));
  renderEmojiChoices();
  $("#conversationIconDialog").showModal();
}
$("#automaticConversationIcon").onclick = () => { $("#conversationIconValue").value = ""; };
$("#conversationIconForm").onsubmit = async event => {
  event.preventDefault();
  if (busy || !conversationIconId) return;
  let icon = $("#conversationIconValue").value.trim();
  if ($("#monogramIconMode").getAttribute("aria-pressed") === "true") {
    if (icon && !/^[A-Za-z0-9]{1,3}$/.test(icon)) { $("#conversationIconError").textContent = "Use 1–3 letters or numbers."; return; }
    icon = icon.toUpperCase();
  }
  try {
    await api(`/api/conversations/${conversationIconId}`, {method:"PATCH",
      body:JSON.stringify({icon:icon || null})});
    $("#conversationIconDialog").close();
    await refreshState();
  } catch (error) { $("#conversationIconError").textContent = error.message; }
};
document.addEventListener("click", event => {
  if (!conversationContext.contains(event.target)) conversationContext.hidden = true;
});
document.addEventListener("keydown", event => {
  if (conversationContext.hidden) return;
  if (event.key === "Escape") { conversationContext.hidden = true; event.preventDefault(); }
  else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    const items = [...conversationContext.children], index = items.indexOf(document.activeElement);
    items[(index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    event.preventDefault();
  }
});
$("#conversationActionForm").onsubmit = async event => {
  event.preventDefault();
  if (!conversationActionId || busy) return;
  $("#conversationActionSubmit").disabled = true;
  try {
    if (conversationAction === "delete") {
      await api(`/api/conversations/${conversationActionId}`, {method: "DELETE"});
      if (cid === conversationActionId) {
        cid = null; $("#messages").replaceChildren(); $("#welcome").hidden = false;
        $("#chatTitle").textContent = "Ask your project";
        try { localStorage.removeItem("aimate.conversation"); } catch {}
      }
      $("#activity").textContent = "Conversation deleted.";
    } else if (conversationAction === "move") {
      await api(`/api/conversations/${conversationActionId}`, {method:"PATCH",
        body:JSON.stringify({group_id:$("#conversationGroup").value || null})});
      $("#activity").textContent = "Conversation moved.";
    } else {
      const result = await api(`/api/conversations/${conversationActionId}`, {method: "PATCH",
        body: JSON.stringify({title: $("#conversationName").value.trim()})});
      if (cid === conversationActionId) $("#chatTitle").textContent = result.title;
      $("#activity").textContent = "Conversation renamed.";
    }
    $("#conversationDialog").close();
    await refreshState();
  } catch (error) { $("#conversationActionError").textContent = error.message; }
  finally { $("#conversationActionSubmit").disabled = false; }
};
function conversationMarkdown(conversation) {
    const lines = ["# " + conversation.title.replace(/([\\`*_{}[\]<>#+.!|])/g, "\\$1"), ""];
    for (const turn of conversation.turns) {
      const user = turn.messages.find(m => m.role === "user" && typeof m.content === "string");
      if (user) lines.push("## You", "", user.content, "");
      const answers = turn.messages.filter(m => m.role === "assistant" && Array.isArray(m.content))
        .flatMap(m => m.content.filter(b => b.type === "text").map(b => b.text));
      if (answers.length) lines.push("## AiMate", "", answers.join("\n\n"), "");
      const sources = new Set();
      for (const message of turn.messages) for (const block of Array.isArray(message.content) ? message.content : []) {
        if (block.type !== "tool_result") continue;
        try {
          const source = JSON.parse(block.content).source;
          if (source && ["https:", "http:"].includes(new URL(source).protocol)) sources.add(source);
        } catch {}
      }
      if (sources.size) lines.push("Sources:", ...Array.from(sources, url => "- <" + url + ">"), "");
    }
    if (conversation.actions.length) {
      lines.push("## Reviewed actions", "");
      for (const action of conversation.actions) lines.push(`- ${action.service}: ${action.operation} — ${action.status}`);
    }
    return lines.join("\n");
}
$("#copyChat").onclick = async () => {
  if (!cid || busy) return;
  $("#chatMenu").open = false;
  try {
    await copyFormatted(conversationMarkdown(await api(`/api/conversations/${cid}`)));
    $("#activity").textContent = "Chat copied with formatting. Plain-text paste includes Markdown.";
  } catch (error) { $("#activity").textContent = "Copy failed: " + error.message; }
};
function downloadFile(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = element("a"); link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("#exportChat").onclick = async () => {
  if (!cid) return;
  $("#chatMenu").open = false;
  try {
    const chat = await api(`/api/conversations/${cid}`);
    downloadFile(conversationMarkdown(chat), "AiMate-" + chat.id.slice(0,8) + ".md", "text/markdown;charset=utf-8");
    $("#activity").textContent = "Chat exported as Markdown.";
  } catch (error) { $("#activity").textContent = error.message; }
};
$("#pinChat").onclick = async () => {
  if (!cid) return;
  $("#chatMenu").open = false;
  try {
    const pinned = Boolean(conversationList.find(thread => thread.id === cid)?.pinned);
    await api(`/api/conversations/${cid}`, {method:"PATCH",body:JSON.stringify({pinned:!pinned})});
    await refreshState();
  } catch (error) { $("#activity").textContent = error.message; }
};
$("#continueChat").onclick = async () => {
  if (!cid) return;
  $("#chatMenu").open = false;
  try {
    controller?.abort();
    for (let attempt=0; busy && attempt<100; attempt++) await new Promise(resolve=>setTimeout(resolve,30));
    if (busy) throw new Error("Stop the current answer before continuing.");
    const chat = await api(`/api/conversations/${cid}/continue`, {method:"POST"});
    await openConversation(chat.id);
    $("#activity").textContent = "Continued in a new chat. Relevant saved context can be recalled.";
    $("#question").focus();
  } catch (error) { $("#activity").textContent = error.message; }
};
let knowledgeRecords = [], recordId = null;
function knowledgeView(editing = false) {
  editing = editing && access.manage_records;
  $("#manageKnowledge").hidden = !access.manage_records;
  $("#knowledgeEditor").hidden = !editing;
  $("#knowledgeCards").hidden = editing;
  $("#viewKnowledge").setAttribute("aria-pressed", String(!editing));
  $("#manageKnowledge").setAttribute("aria-pressed", String(editing));
}
$("#viewKnowledge").onclick = () => knowledgeView();
$("#manageKnowledge").onclick = () => knowledgeView(true);
function renderKnowledge() {
  const list = $("#knowledgeList"); list.replaceChildren();
  const cards = $("#knowledgeCards"); cards.replaceChildren();
  const query = $("#knowledgeSearch").value.toLowerCase();
  const matches = knowledgeRecords.filter(r => (r.key + " " + r.value).toLowerCase().includes(query));
  $("#knowledgeCount").textContent = query ? `${matches.length} of ${knowledgeRecords.length} records` : `${knowledgeRecords.length} saved record${knowledgeRecords.length === 1 ? "" : "s"}`;
  for (const record of matches) {
    const button = element("button", record.id === recordId ? "active" : "");
    button.append(element("b", "", record.key), element("small", "", record.group_id ? groupPath(record.group_id) : "Workspace"));
    button.onclick = () => editRecord(record); list.append(button);
    const card = element("article", "knowledge-card");
    const heading = element("div", "knowledge-card-head");
    const edit = element("button", "", "Edit"); edit.type = "button";
    edit.hidden = !access.manage_records;
    edit.setAttribute("aria-label", `Edit ${record.key}`);
    edit.onclick = () => { editRecord(record); knowledgeView(true); $("#recordKey").focus(); };
    heading.append(element("h3", "", record.key), edit);
    const value = element("div", "knowledge-value");
    renderDataValue(value, record.value);
    const footer = element("div", "knowledge-card-footer");
    const copy = element("button", "", "Copy"); copy.type = "button";
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(record.value); copy.textContent = "Copied"; }
      catch { $("#knowledgeError").textContent = "Clipboard unavailable. Select the value to copy."; }
    };
    footer.append(element("small", "", record.group_id ? groupPath(record.group_id) : "Workspace"), copy);
    card.append(heading, element("small", "knowledge-value-label", "VALUE"), value, footer); cards.append(card);
  }
  if (!list.children.length) list.append(element("p", "hint", "No records yet."));
  if (!cards.children.length) cards.append(element("p", "hint", query ? "No matching records." : "Your saved records will appear here. Add your first fact or link."));
}
function editRecord(record = null) {
  recordId = record?.id || null;
  $("#recordKey").value = record?.key || "";
  $("#recordValue").value = record?.value || "";
  groupOptions($("#recordGroup"), "Workspace");
  $("#recordGroup").value = record ? record.group_id || "" : conversationList.find(c => c.id === cid)?.group_id || "";
  $("#deleteRecord").hidden = !record;
  $("#knowledgeError").textContent = ""; renderKnowledge();
}
async function loadKnowledge() {
  knowledgeRecords = (await api("/api/knowledge")).records; renderKnowledge();
}
$("#openKnowledge").onclick = async () => {
  $("#knowledgeDialog").showModal();
  try { await loadKnowledge(); editRecord(); knowledgeView(); } catch (error) { $("#knowledgeError").textContent = error.message; }
};
$("#knowledgeSearch").oninput = renderKnowledge;
$("#newRecord").onclick = () => { editRecord(); $("#recordKey").focus(); };
$("#knowledgeForm").onsubmit = async event => {
  event.preventDefault();
  try {
    const result = await api(recordId ? `/api/knowledge/${recordId}` : "/api/knowledge", {
      method:recordId ? "PATCH" : "POST", body:JSON.stringify({
        key:$("#recordKey").value,value:$("#recordValue").value,group_id:$("#recordGroup").value || null})});
    await loadKnowledge(); editRecord(knowledgeRecords.find(r => r.id === result.id)); knowledgeView();
  } catch (error) { $("#knowledgeError").textContent = error.message; }
};
$("#deleteRecord").onclick = async () => {
  if (!recordId) return;
  try { await api(`/api/knowledge/${recordId}`, {method:"DELETE"}); await loadKnowledge(); editRecord(); }
  catch (error) { $("#knowledgeError").textContent = error.message; }
};
let todoTasks = [], todoFilter = "open", todoEditId = null;
function resetTodoEditor() {
  todoEditId = null; $("#todoTitle").value = ""; $("#saveTodo").textContent = "Add task"; $("#cancelTodoEdit").hidden = true;
}
function renderTodos() {
  const list = $("#todoList"); list.replaceChildren();
  const open = todoTasks.filter(task => !task.completed).length;
  $("#todoCount").textContent = `${open} open · ${todoTasks.length - open} completed`;
  for (const button of $("#todoFilters").querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.filter === todoFilter));
  for (const task of todoTasks.filter(t => todoFilter === "all" || Boolean(t.completed) === (todoFilter === "completed"))) {
    const row = element("div", "todo-row" + (task.completed ? " completed" : ""));
    const label = element("label", "todo-label"), checkbox = element("input");
    checkbox.type = "checkbox"; checkbox.checked = Boolean(task.completed);
    checkbox.disabled = !access.manage_records;
    checkbox.onchange = async () => {
      checkbox.disabled = true;
      try { await api(`/api/todos/${task.id}`, {method:"PATCH", body:JSON.stringify({completed:checkbox.checked})}); await loadTodos(); }
      catch (error) { $("#todoError").textContent = error.message; checkbox.checked = Boolean(task.completed); checkbox.disabled = false; }
    };
    const text = element("span", "todo-text", task.title);
    text.id = `todo-text-${task.id}`;
    label.append(checkbox, text);
    const expand = element("button", "todo-expand", "Show more");
    expand.type = "button";
    expand.setAttribute("aria-expanded", "false");
    expand.setAttribute("aria-controls", text.id);
    expand.onclick = () => {
      const expanded = row.classList.toggle("expanded");
      expand.textContent = expanded ? "Show less" : "Show more";
      expand.setAttribute("aria-expanded", String(expanded));
    };
    const edit = element("button", "", "Edit"), remove = element("button", "error", "Delete"), copy = element("button", "", "Copy");
    edit.type = remove.type = copy.type = "button";
    edit.hidden = remove.hidden = !access.manage_records;
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(task.title); copy.textContent = "Copied"; }
      catch { $("#todoError").textContent = "Clipboard unavailable. Select the task text to copy."; }
    };
    edit.onclick = () => { todoEditId = task.id; $("#todoTitle").value = task.title; $("#saveTodo").textContent = "Save"; $("#cancelTodoEdit").hidden = false; $("#todoTitle").focus(); };
    remove.onclick = async () => {
      try { await api(`/api/todos/${task.id}`, {method:"DELETE"}); if (todoEditId === task.id) resetTodoEditor(); await loadTodos(); }
      catch (error) { $("#todoError").textContent = error.message; }
    };
    const actions = element("div", "todo-actions"); actions.append(expand, copy, edit, remove);
    row.append(label, actions); list.append(row);
  }
  if (!list.children.length) list.append(element("p", "hint", todoFilter === "completed" ? "No completed tasks yet." : "Nothing here yet. Add a task above."));
}
async function loadTodos() { todoTasks = (await api("/api/todos")).tasks; renderTodos(); }
$("#openTodos").onclick = async () => {
  $("#todoForm").hidden = !access.manage_records;
  $("#todoDialog").showModal(); $("#todoError").textContent = ""; resetTodoEditor();
  try { await loadTodos(); } catch (error) { $("#todoError").textContent = error.message; }
};
$("#todoFilters").onclick = event => { const button = event.target.closest("[data-filter]"); if (button) { todoFilter = button.dataset.filter; renderTodos(); } };
$("#cancelTodoEdit").onclick = resetTodoEditor;
$("#todoForm").onsubmit = async event => {
  event.preventDefault(); $("#saveTodo").disabled = true; $("#todoError").textContent = "";
  try {
    await api(todoEditId ? `/api/todos/${todoEditId}` : "/api/todos", {method:todoEditId ? "PATCH" : "POST", body:JSON.stringify({title:$("#todoTitle").value})});
    resetTodoEditor(); await loadTodos();
  } catch (error) { $("#todoError").textContent = error.message; }
  finally { $("#saveTodo").disabled = false; }
};
let usageReport = null;
const tokenTotal = row => row.input_tokens + row.output_tokens + row.cache_read_input_tokens + row.cache_creation_input_tokens;
const usd = value => new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",maximumFractionDigits:4}).format(value);
const numberLabel = value => value.toLocaleString();
async function loadUsage() {
  try {
    $("#usageError").textContent = "";
    usageReport = await api(`/api/usage?days=${$("#usageDays").value}&offset=${-new Date().getTimezoneOffset()}`);
    const totals = usageReport.totals, summary = $("#usageSummary"); summary.replaceChildren();
    const cards = [["Reported tokens",numberLabel(tokenTotal(totals))],["Usage entries",numberLabel(totals.requests)],
      ["Estimated cost", totals.requests && !totals.unpriced_requests ? usd(totals.estimated_usd) : totals.requests > totals.unpriced_requests ? usd(totals.estimated_usd) + " + unpriced" : "Rates not set"]];
    for (const [label,value] of cards) {
      const card = element("div"); card.append(element("small","",label),element("strong","",value)); summary.append(card);
    }
    const table = element("table"), head = element("tr");
    for (const label of ["Model","Entries","Input","Output","Cached / written","Est. USD"]) head.append(element("th","",label));
    table.append(head);
    for (const row of usageReport.models) {
      const tr = element("tr");
      for (const value of [row.model,numberLabel(row.requests),numberLabel(row.input_tokens),numberLabel(row.output_tokens),
        numberLabel(row.cache_read_input_tokens) + " / " + numberLabel(row.cache_creation_input_tokens),
        row.unpriced_requests ? "Unpriced" + (row.requests > row.unpriced_requests ? " + " + usd(row.estimated_usd) : "") : usd(row.estimated_usd)]) tr.append(element("td","",value));
      tr.onclick = () => { $("#rateModel").value = row.model; setRateFields(); }; table.append(tr);
    }
    $("#usageModels").replaceChildren(table);
    if (!usageReport.models.length) $("#usageModels").append(element("p","hint","No reported usage in this period."));
    const options = $("#usageModelOptions"); options.replaceChildren();
    for (const model of new Set([...usageReport.models.map(r=>r.model),config.ai?.model,config.ai?.analysis_model].filter(Boolean))) {
      const option = element("option"); option.value=model; options.append(option);
    }
    $("#usageCoverage").textContent = usageReport.coverage + " Days use your device timezone.";
    renderUsageChart();
  } catch (error) { $("#usageError").textContent = error.message; }
}
function renderUsageChart() {
  if (!usageReport) return;
  const chart = $("#usageChart"); chart.replaceChildren();
  const cost = $("#usageMetric").value === "cost";
  if (cost && usageReport.totals.unpriced_requests === usageReport.totals.requests) {
    chart.append(element("p","hint","Add model rates to show cost estimates.")); return;
  }
  const rows = [];
  for (let i=usageReport.days-1;i>=0;i--) {
    const date = new Date(); date.setDate(date.getDate()-i);
    const key = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
    rows.push(usageReport.daily.find(r=>r.date===key) || {date:key,input_tokens:0,output_tokens:0,
      cache_read_input_tokens:0,cache_creation_input_tokens:0,estimated_usd:0,unpriced_requests:0});
  }
  const maximum = Math.max(1e-8,...rows.map(r=>cost ? r.estimated_usd : tokenTotal(r)));
  for (const row of rows) {
    const column = element("div","usage-column"), bar = element("i");
    const value = cost ? row.estimated_usd : tokenTotal(row);
    bar.style.height = Math.max(1,value/maximum*130)+"px";
    column.title = row.date + ": " + (cost ? usd(value) + (row.unpriced_requests ? " · includes unpriced requests" : "") : numberLabel(value)+" tokens");
    column.append(bar,element("small","",row.date.slice(5))); chart.append(column);
  }
  if (!rows.length) chart.append(element("p","hint","Your activity will appear here."));
}
function setRateFields() {
  const rate = usageReport?.rates.find(r=>r.model===$("#rateModel").value);
  for (const [id,key] of [["rateInput","input"],["rateOutput","output"],["rateRead","cache_read"],["rateWrite","cache_write"]]) $("#"+id).value=rate ? rate[key] : "";
}
$("#openUsage").onclick = () => { $("#usageDialog").showModal(); void loadUsage(); };
$("#usageDays").onchange = loadUsage;
$("#usageMetric").onchange = renderUsageChart;
$("#rateModel").oninput = setRateFields;
$("#usageRateForm").onsubmit = async event => {
  event.preventDefault();
  try {
    await api("/api/usage/rates",{method:"POST",body:JSON.stringify({model:$("#rateModel").value,
      input:Number($("#rateInput").value),output:Number($("#rateOutput").value),
      cache_read:Number($("#rateRead").value),cache_write:Number($("#rateWrite").value)})});
    await loadUsage();
  } catch (error) { $("#usageError").textContent=error.message; }
};
$("#exportUsage").onclick = () => {
  if (!usageReport) return;
  const csv = [["Day","Input tokens","Output tokens","Cache read tokens","Cache write tokens","Usage entries","Estimated USD","Unpriced entries"],
    ...usageReport.daily.map(r=>[r.date,r.input_tokens,r.output_tokens,r.cache_read_input_tokens,r.cache_creation_input_tokens,r.requests,r.estimated_usd,r.unpriced_requests])];
  downloadFile(csv.map(row=>row.join(",")).join("\r\n"),"AiMate-usage.csv","text/csv;charset=utf-8");
  const modelCsv = [["Model","Input tokens","Output tokens","Cache read tokens","Cache write tokens","Usage entries","Estimated USD","Unpriced entries"],
    ...usageReport.models.map(r=>[r.model,r.input_tokens,r.output_tokens,r.cache_read_input_tokens,r.cache_creation_input_tokens,r.requests,r.estimated_usd,r.unpriced_requests])];
  const cell = value => '"' + String(value).replace(/^[=+@-]/,"'$&").replaceAll('"','""') + '"';
  downloadFile(modelCsv.map(row=>row.map(cell).join(",")).join("\r\n"),"AiMate-usage-models.csv","text/csv;charset=utf-8");
};
document.addEventListener("aimate:choice", event => {
  if (busy) return;
  $("#question").value = event.detail;
  $("#question").focus();
});
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
  archiveView = false; pendingAttachments = []; renderPendingAttachments();
  $("#messages").replaceChildren(); $("#welcome").hidden = false;
  $("#workspace").hidden = true; $("#loginScreen").hidden = false;
  configureLogin(await api("/api/mode"));
};
document.querySelectorAll("[data-question]").forEach(button => {
  button.onclick = () => ask(button.dataset.question);
});
document.querySelectorAll("[data-close]").forEach(button => {
  button.onclick = () => document.getElementById(button.dataset.close).close();
});
async function loadOtpStatus() {
  try {
    const status = await api("/api/auth/otp");
    $("#otpStatus").textContent = status.enabled ? `Enabled · ${status.recovery_remaining} recovery codes remaining` : "Not set up · development password";
    $("#otpStatus").className = status.enabled ? "hint success" : "hint";
    $("#openOtpSetup").textContent = status.enabled ? "Replace authenticator" : "Set up OTP";
    return status;
  } catch (error) { $("#otpStatus").textContent = error.message; throw error; }
}
$("#openOtpSetup").onclick = async () => {
  try {
    const status = await loadOtpStatus();
    $("#otpVerifyLabel").textContent = status.enabled ? "Fresh OTP or unused recovery code" : "Development password";
    $("#otpVerification").type = status.enabled ? "text" : "password";
    $("#otpVerification").value = "";
    $("#otpVerifyForm").hidden = false;
    $("#otpPairForm").hidden = true;
    $("#otpRecoveryPanel").hidden = true;
    $("#otpSetupError").textContent = "";
    $("#otpDialog").showModal();
  } catch (error) { $("#settingsStatus").textContent = error.message; }
};
$("#otpVerifyForm").onsubmit = async event => {
  event.preventDefault();
  const button = $("#otpVerifyForm").querySelector("button"); button.disabled = true;
  try {
    const result = await api("/api/auth/otp/setup", {method:"POST",
      body:JSON.stringify({verification:$("#otpVerification").value})});
    $("#otpVerification").value = "";
    $("#otpQr").src = result.qr;
    $("#otpSecret").textContent = result.secret;
    $("#otpConfirmCode").value = "";
    $("#otpVerifyForm").hidden = true; $("#otpPairForm").hidden = false;
    $("#otpSetupError").textContent = "";
    $("#otpConfirmCode").focus();
  } catch (error) { $("#otpSetupError").textContent = error.message; }
  finally { button.disabled = false; }
};
$("#otpPairForm").onsubmit = async event => {
  event.preventDefault();
  const button = $("#otpPairForm").querySelector("button"); button.disabled = true;
  try {
    const result = await api("/api/auth/otp/enable", {method:"POST",
      body:JSON.stringify({code:$("#otpConfirmCode").value.trim()})});
    $("#otpQr").removeAttribute("src"); $("#otpSecret").textContent = ""; $("#otpConfirmCode").value = "";
    $("#otpPairForm").hidden = true; $("#otpRecoveryPanel").hidden = false;
    $("#otpRecoveryCodes").textContent = result.recovery_codes.join("\n");
    $("#savedRecoveryCodes").checked = false; $("#finishOtpSetup").disabled = true;
    $("#otpSetupError").textContent = "";
    configureLogin(await api("/api/mode"));
    await loadOtpStatus();
  } catch (error) { $("#otpSetupError").textContent = error.message; }
  finally { button.disabled = false; }
};
$("#downloadRecoveryCodes").onclick = () => {
  downloadFile("AiMate recovery codes — each can be used once. Keep private.\n\n" +
    $("#otpRecoveryCodes").textContent, "AiMate-recovery-codes.txt", "text/plain;charset=utf-8");
};
$("#savedRecoveryCodes").onchange = () => { $("#finishOtpSetup").disabled = !$("#savedRecoveryCodes").checked; };
function closeOtpSetup(event) {
  if (!$("#otpRecoveryPanel").hidden && !$("#savedRecoveryCodes").checked) {
    event?.preventDefault();
    $("#otpSetupError").textContent = "Save your recovery codes before closing.";
    return;
  }
  $("#otpDialog").close();
}
$("#otpDialog").querySelector("[data-close]").onclick = closeOtpSetup;
$("#otpDialog").oncancel = closeOtpSetup;
$("#finishOtpSetup").onclick = closeOtpSetup;
$("#otpDialog").onclose = () => {
  $("#otpQr").removeAttribute("src"); $("#otpSecret").textContent = "";
  $("#otpRecoveryCodes").textContent = ""; $("#otpVerification").value = ""; $("#otpConfirmCode").value = "";
  $("#otpRecoveryPanel").hidden = true;
};
const connectionLabels = {ai: "AI", github: "GitHub", jira: "Jira", jenkins: "Jenkins", changes: "admin settings"};

function selectSettingsTab(service) {
  if (demo && service === "changes") service = "ai";
  activeSettings = service;
  document.querySelectorAll("[data-settings-tab]").forEach(button => {
    const selected = button.dataset.settingsTab === service;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll("[data-settings-panel]").forEach(panel => {
    panel.hidden = panel.dataset.settingsPanel !== service;
  });
  $("#saveConnection").hidden = !(access.configure_connections ?? access.configure) || ["github", "jira", "jenkins"].includes(service);
  $("#saveConnection").textContent = service === "changes" ? "Save admin settings" : `Save ${connectionLabels[service]} connection`;
  $("#settingsStatus").textContent = pagesPreview ? "Backend not connected. Open your local workspace to configure services." : demo ? "Offline sample. Real credentials cannot be added here." : "Only this tab is saved.";
}
document.querySelectorAll("[data-settings-tab]").forEach(button => {
  button.onclick = () => selectSettingsTab(button.dataset.settingsTab);
  button.onkeydown = event => {
    const tabs = [...document.querySelectorAll("[data-settings-tab]")].filter(tab => !tab.hidden);
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
  const report = override || (dirtyConnections.has(service)
    ? {status: "unchecked", message: "Inputs changed. Save & check to validate them."}
    : saved || {status: "unchecked", message: "Not checked. Save & check this connection."});
  const status = report.status || "unchecked";
  const dot = $(`[data-connection-dot="${service}"]`);
  dot.dataset.state = status;
  dot.setAttribute("aria-label", status);
  const summary = $(`[data-connection-summary="${service}"]`);
  summary.dataset.state = status;
  summary.replaceChildren();
  const light = element("span", "connection-dot"); light.dataset.state = status;
  const label = {passed: "✓ Connected · Pass", partial: "◐ Partial access", failed: "✕ Failed", checking: "Checking…", unchecked: "Not verified", simulated: "Sample only"}[status];
  summary.append(light, document.createTextNode(label));
  const output = $(`#test-${service}`);
  const wasOpen = Boolean(output.querySelector(".connection-details")?.open);
  output.replaceChildren(element("p", status === "failed" ? "error" : status === "passed" ? "success" : status === "partial" ? "warning" : "muted", report.message));
  if (!report.checked_at && !report.details?.length && !report.targets?.length) return;
  const details = element("details", "connection-details");
  details.open = wasOpen;
  const toggle = element("summary", "", wasOpen ? "Hide details" : "Show details");
  details.append(toggle);
  details.ontoggle = () => { toggle.textContent = details.open ? "Hide details" : "Show details"; };
  output.append(details);
  if (report.checked_at) details.append(element("p", "hint", "Last verified: " + new Date(report.checked_at * 1000).toLocaleString() +
    (service === "ai" ? " · also updated by successful answers" : " · refreshed automatically")));
  if (report.details?.length) {
    const list = element("ul"); report.details.forEach(text => list.append(element("li", "", text)));
    details.append(list);
  }
  for (const target of report.targets || []) {
    const card = element("details", "connection-target");
    card.dataset.target = target.target;
    const targetStatus = target.status || (target.ok ? "passed" : "failed");
    card.dataset.state = targetStatus;
    card.append(element("summary", "", (targetStatus === "partial" ? "◐ " : target.ok ? "✓ " : "✕ ") + target.target),
                element("p", targetStatus === "failed" ? "error" : "", target.message));
    if (target.details?.length) {
      const list = element("ul"); target.details.forEach(text => list.append(element("li", "", text))); card.append(list);
    }
    for (const check of target.checks || []) {
      const row = element("p", "capability-check", `${check.ok ? "✓" : "✕"} ${check.name}: ${check.message}`);
      row.dataset.state = check.ok ? "passed" : "failed"; card.append(row);
    }
    details.append(card);
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

function updateJenkinsSetup() {
  const form = $("#settingsForm");
  $("#jenkinsAdvanced").hidden = form.elements["jenkins.mode"].value === "simple";
  $("#jenkinsJobNames").hidden = form.elements["jenkins.access"].value === "all";
  const url = form.elements["jenkins.url"].value.trim();
  const username = form.elements["jenkins.username"].value.trim();
  let host = "";
  try { if (url) { const parsed = new URL(url); host = parsed.hostname + parsed.pathname.replace(/\/$/, ""); } } catch { host = "check URL"; }
  $("#jenkinsAccountSummary").textContent = url && username ? `· ${username} · ${host}` : "· set once";
}
for (const key of ["mode", "access", "url", "username"]) {
  $("#settingsForm").elements["jenkins." + key].addEventListener("input", () => {
    try { updateJenkinsSetup(); } catch { $("#jenkinsAccountSummary").textContent = "· check URL"; }
  });
}

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
  if (data.jenkins.mode === "simple") Object.assign(data.jenkins, {access: "all", jobs: []});
  if (data.ai.provider === "bedrock" && data.ai.bedrock_mode === "simple") Object.assign(data.ai, {
    region: "us-east-2", bedrock_auth: "bearer", bedrock_endpoint: "runtime",
    model: "us.anthropic.claude-haiku-5-5"
  });
  if (data.ai.provider === "chatgpt") {
    data.ai.model = $("#chatgptModel").value;
    data.ai.analysis_model = $("#chatgptAnalysisModel").value;
  }
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
      $("#settingsStatus").textContent = result.status === "partial" ? "Partially connected. See which targets or features need attention." : result.ok ? "Access check passed." : "Fix the failed checks shown above.";
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
  $("#auditDialog h2").textContent = "Audit log";
  $("#auditDialog").showModal();
  $("#auditContent").textContent = "Loading…";
  try {
    const data = await api("/api/audit");
    $("#auditContent").textContent = data.entries.length ? JSON.stringify(data.entries, null, 2) : "No confirmed actions yet.";
  } catch (error) { $("#auditContent").textContent = error.message; }
};
function restoreConversation() {
  if (restoringChat) return restoringChat;
  const pending = loadPreviousConversation();
  restoringChat = pending;
  return pending.finally(() => { if (restoringChat === pending) restoringChat = null; });
}

async function loadPreviousConversation() {
  if (cid || $("#workspace").hidden) return;
  const version = navigationVersion;
  let previous;
  try { previous = localStorage.getItem("aimate.conversation"); } catch { return; }
  if (!previous) return;
  const state = await api("/api/state");
  if (version !== navigationVersion) return;
  const conversation = state.conversations.find(item => item.id === previous);
  if (conversation) await openConversation(previous, conversation.title);
}

async function initialize() {
  const mode = await api("/api/mode");
  configureLogin(mode);
  demo = Boolean(mode.demo);
  $("#demoLogin").hidden = !demo;
  $("#demoLoginHint").hidden = !demo;
  $("#loginForm").hidden = demo;
  $("#localPasswordHint").hidden = demo || Boolean(mode.hosted || mode.dev_login);
  if (pagesPreview) {
    $("#demoLogin").textContent = "Open interface preview →";
    $("#demoLoginHint").textContent = "No live AI or service access. Preview changes last until you reload.";
    $(".help-note").textContent = "This interface preview keeps records in memory until you reload. It makes no model or service calls and cannot save credentials.";
  }
  if (mode.dev_login && !demo) {
    const session = await api("/api/dev/login", {method:"POST"});
    csrf = session.csrf;
  }
  await refreshState().catch(() => {});
  await restoreConversation();
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
setInterval(() => { void syncConnections(); }, 60_000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) void syncConnections(); });
window.addEventListener("focus", () => { void syncConnections(); });
initializingChat = initialize().catch(error => { $("#loginError").textContent = error.message; })
  .finally(() => { initializingChat = null; });
