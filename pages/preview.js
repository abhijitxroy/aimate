/* GitHub Pages uses the real interface with an isolated, in-memory preview.
   No credentials, service calls, model calls, or shared chat storage. */
(() => {
  "use strict";
  const destination = window.AiMateDeployment?.appUrl;
  if (destination) {
    try {
      const url = new URL(destination);
      if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash ||
          url.origin === location.origin) throw new Error("Use a separate HTTPS app URL.");
      location.replace(url.href);
      return;
    } catch (error) {
      console.error("AiMate app URL is invalid:", error.message);
    }
  }
  window.AiMatePagesPreview = true;
  const originalFetch = window.fetch.bind(window);
  const unavailable = "Backend not connected. This page previews AiMate’s interface. Open your local AiMate workspace for live AI and project access.";
  const chats = new Map(), groups = new Map(), records = new Map(), tasks = new Map();
  const config = {
    allow_writes: false,
    ai: {provider: "chatgpt", model: "", analysis_model: "", region: "us-east-2", bedrock_auth: "api_key"},
    github: {base_url: "https://api.github.com", repos: [], token_configured: false},
    jira: {base_url: "", projects: [], access: "all", token_configured: false},
    jenkins: {base_url: "", username: "", jobs: [], access: "all", token_configured: false},
  };
  const json = (value, status = 200) => new Response(JSON.stringify(value), {
    status, headers: {"Content-Type": "application/json"},
  });
  const create = data => ({...data, id: crypto.randomUUID(), created: Date.now() / 1000});
  function collection(map, id, method, data, defaults = {}) {
    if (method === "POST" && !id) {
      const item = create({...defaults, ...data}); map.set(item.id, item); return json(item);
    }
    const item = map.get(id);
    if (!item) return json({detail: "Preview item not found."}, 404);
    if (method === "GET") return json(item);
    if (method === "PATCH") { Object.assign(item, data); return json(item); }
    if (method === "DELETE") { map.delete(id); return json({deleted: true}); }
    return json({detail: unavailable}, 503);
  }
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return originalFetch(input, options);
    const method = (options.method || "GET").toUpperCase();
    let data = {};
    try { data = options.body ? JSON.parse(options.body) : {}; }
    catch { return json({detail: "Invalid preview request."}, 400); }
    const path = url.pathname;
    if (path === "/api/mode") return json({demo: true, hosted: true, environment: "preview", otp_enabled: false});
    if (path === "/api/state") return json({
      csrf: "pages-preview", config, demo: true, pages_preview: true,
      access: {role: "reviewer", configure: false, configure_connections: false, write: false, manage_records: true, audit: false},
      chatgpt: {available: false, plan_enabled: false, reason: unavailable},
      connection_checks: {}, connection_defaults: {},
      conversations: [...chats.values()], groups: [...groups.values()],
    });
    if (path === "/api/logout" || path === "/api/demo/login") return json({csrf: "pages-preview"});
    const match = path.match(/^\/api\/(conversations|groups|knowledge|todos)(?:\/([^/]+))?$/);
    if (match) {
      const [, type, id] = match;
      const map = {conversations: chats, groups, knowledge: records, todos: tasks}[type];
      if (method === "GET" && !id) return json({
        [type === "knowledge" ? "records" : type === "todos" ? "tasks" : type]: [...map.values()],
      });
      return collection(map, id, method, data, type === "conversations"
        ? {title: "New conversation", group_id: null, pinned: false, archived: false, turns: [], actions: [], private: false}
        : type === "todos" ? {completed: false} : {});
    }
    if (path === "/api/history/search") {
      const query = (url.searchParams.get("q") || "").toLowerCase();
      return json({results: [...chats.values()].filter(c => c.title.toLowerCase().includes(query))
        .map(c => ({...c, snippet: "Interface preview · no AI messages", area: "Preview"})), more: false});
    }
    if (path === "/api/usage") return json({
      days: Math.min(90, Math.max(1, Number(url.searchParams.get("days")) || 30)),
      totals: {requests: 0, input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0,
        cache_creation_input_tokens: 0, estimated_usd: 0, unpriced_requests: 0},
      models: [], daily: [], rates: [], coverage: "Preview only. No model calls or charges.",
    });
    if (path === "/api/bedrock/models") return json({presets: [], models: [], message: unavailable});
    if (path === "/api/chatgpt/models") return json({models: [], message: unavailable});
    if (method === "GET" && (path === "/api/audit" || path === "/api/feedback")) return json({entries: []});
    return json({detail: unavailable}, 503);
  };
})();
