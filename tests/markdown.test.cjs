const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const markdownit = require("../app/static/vendor/markdown-it.min.js");
const context = vm.createContext({window: {markdownit}, URL});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/static/markdown.js"), "utf8"), context);
const render = text => {
  context.body = {innerHTML: ""};
  context.text = text;
  vm.runInContext("renderAnswer(body, text)", context);
  return context.body.innerHTML;
};

test("renders answer structure, code, tables and safe citations", () => {
  const html = render("## Overview\n\n**Ready** with `FastAPI`.\n\n1. Read\n2. Review\n\n```python\nprint('<hello>')\n```\n\n| Source | State |\n| --- | --- |\n| GitHub | Connected |\n\n[Source](https://github.com/abhijitxroy/aimate)");
  for (const expected of ["<h2>Overview</h2>", "<strong>Ready</strong>", "<code>FastAPI</code>",
    "<ol>", '<code class="language-python">', "&lt;hello&gt;", "<table>",
    'href="https://github.com/abhijitxroy/aimate"', 'target="_blank"', 'rel="noopener noreferrer"']) {
    assert.ok(html.includes(expected), expected);
  }
});

test("untrusted answers cannot introduce HTML, scripts or remote images", () => {
  const html = render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n![tracking](https://example.com/pixel.png)\n\n```html\n<iframe src="https://example.com"></iframe>\n```');
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("&lt;img"));
  assert.doesNotMatch(html, /<(script|img|iframe)\b/i);
});

test("refuses executable, encoded, local and relative links", () => {
  for (const url of ["javascript:alert%281%29", "jav&#x61;script:alert%281%29",
    "data:text/html,hello", "file:///C:/secret", "/api/settings", "//example.com"]) {
    assert.doesNotMatch(render(`[Open](${url})`), /<a\b/, url);
  }
});

test("handles incomplete streamed Markdown and keeps code literal", () => {
  assert.ok(render("## Working\n\n[Source](https://").includes("<h2>Working</h2>"));
  const html = render("```js\n[Not a link](javascript:alert(1))\n<script>\n");
  assert.ok(html.includes("&lt;script&gt;"));
  assert.doesNotMatch(html, /<a\b|<script\b/);
});
