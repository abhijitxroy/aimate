const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const hljs = require("../app/static/vendor/highlight.min.js");
const markdownit = require("../app/static/vendor/markdown-it.min.js");
const context = vm.createContext({window: {hljs, markdownit}, hljs, URL});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/static/vendor/highlight-powershell.min.js"), "utf8"), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/static/markdown.js"), "utf8"), context);

function highlight(source, language) {
  context.code = {textContent: source, innerHTML: "", dataset: {},
    classList: {add() {}}};
  context.requested = language;
  const result = vm.runInContext("highlightCodeElement(code, requested)", context);
  return {language: result, html: context.code.innerHTML, source: context.code.textContent};
}

test("highlights JSON, YAML and common project languages", () => {
  for (const [language, source] of [
    ["json", '{"name":"AiMate","ready":true,"count":42}'],
    ["yml", "name: AiMate\nready: true\ncount: 42\n"],
    ["py", 'def hello():\n    return "AiMate"\n'],
    ["js", 'const name = "AiMate";'],
    ["ts", 'const name: string = "AiMate";'],
    ["sql", "SELECT name FROM projects WHERE id = 42;"],
    ["ps1", 'Write-Host "AiMate"\n$ready = $true'],
    ["bash", 'echo "AiMate"\nexport READY=1'],
    ["html", '<div class="app">AiMate</div>'],
    ["css", ".app { color: #007cc0; }"],
  ]) {
    const result = highlight(source, language);
    assert.match(result.html, /class="hljs-/, language);
    assert.equal(result.source, source, `${language} source is unchanged`);
  }
});

test("escapes executable HTML in highlighted content", () => {
  for (const language of ["json", "yaml", "html", "python", "javascript"]) {
    const source = '<img src=x onerror=alert(1)><script>alert(1)</script>';
    const result = highlight(source, language);
    assert.doesNotMatch(result.html, /<(img|script)\b/i, language);
    assert.match(result.html, /&lt;/);
  }
});

test("detects unlabelled structured data conservatively", () => {
  assert.equal(highlight('{"ready":true}', "").language, "json");
  assert.equal(highlight("name: AiMate\nready: true", "").language, "yaml");
  assert.equal(highlight("An ordinary answer.", "").language, "text");
  assert.equal(highlight('{"partial":', "").language, "text");
  assert.equal(highlight('{"ready":true}', "text").language, "text");
});

test("unknown languages and large logs remain literal and fast", () => {
  for (const [language, source] of [["unknown-language", "<script>plain</script>"],
    ["python", "x".repeat(50001)]]) {
    const result = highlight(source, language);
    assert.equal(result.html, "");
    assert.equal(result.source, source);
  }
});

test("missing highlighter preserves readable source", () => {
  context.window.hljs = null;
  try {
    assert.equal(highlight('{"ready":true}', "json").html, "");
  } finally { context.window.hljs = hljs; }
});
