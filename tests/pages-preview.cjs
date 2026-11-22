const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");

function preview() {
  let networkCalls = 0;
  const window = {AiMateDeployment: {appUrl: ""}, fetch: () => {
    networkCalls++; throw new Error("Unexpected network request");
  }};
  vm.runInNewContext(fs.readFileSync("pages/preview.js", "utf8"), {
    window, URL, Response, crypto: webcrypto, console,
    location: {href: "https://example.github.io/aimate/", origin: "https://example.github.io"},
  });
  return {window, calls: () => networkCalls};
}

test("preview cannot invoke AI, save credentials, or perform service writes", async () => {
  const {window, calls} = preview();
  for (const path of ["/api/chat", "/api/settings", "/api/connections/test", "/api/actions/x/confirm", "/api/chatgpt/start"]) {
    const response = await window.fetch(path, {method: "POST", body: JSON.stringify({token: "test-secret"})});
    assert.equal(response.status, 503);
    assert.match((await response.json()).detail, /Backend not connected/);
  }
  assert.equal(calls(), 0);
  const state = await (await window.fetch("/api/state")).json();
  assert.equal(state.chatgpt.plan_enabled, false);
  assert.equal(state.config.github.token_configured, false);
  assert.equal(state.config.allow_writes, false);
});

test("preview records are isolated in memory and new tabs start empty", async () => {
  const {window} = preview();
  const chat = await (await window.fetch("/api/conversations", {method: "POST", body: "{}"})).json();
  await window.fetch(`/api/conversations/${chat.id}`, {method: "PATCH", body: '{"title":"My preview"}'});
  const state = await (await window.fetch("/api/state")).json();
  assert.equal(state.conversations[0].title, "My preview");
  const fresh = preview();
  assert.equal((await (await fresh.window.fetch("/api/state")).json()).conversations.length, 0);
});
