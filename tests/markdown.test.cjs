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

test("underline and colour escape content and reject arbitrary CSS", () => {
  const html = render("++<img src=x onerror=alert(1)>++ [colour:#FF7850]<script>x</script>[/colour]");
  assert.ok(html.includes('class="prompt-underline"'));
  assert.ok(html.includes('data-prompt-colour="#ff7850"'));
  assert.doesNotMatch(html, /<(script|img)\b|style=/);
  for (const invalid of ["red", "#fff", "url(https://example.com)", '#ffffff" onclick="alert(1)']) {
    assert.doesNotMatch(render(`[colour:${invalid}]Text[/colour]`), /data-prompt-colour=/);
  }
  const code = render("```\n++keep++ [colour:#ffffff]literal[/colour]\n```");
  assert.doesNotMatch(code, /prompt-underline|data-prompt-colour=/);
});

test("refuses executable, encoded, local and relative links", () => {
  for (const url of ["javascript:alert%281%29", "jav&#x61;script:alert%281%29",
    "data:text/html,hello", "file:///C:/secret", "/api/settings", "//example.com"]) {
    assert.doesNotMatch(render(`[Open](${url})`), /<a\b/, url);
  }
});

test("combines bold italic underline and colour without showing authoring tags", () => {
  const html=render("***++[colour:#ff7aaf]Hello[/colour]++***");
  for (const expected of ["<strong>","<em>",'class="prompt-underline"','data-prompt-colour="#ff7aaf"',"Hello"]) {
    assert.ok(html.includes(expected),expected);
  }
  assert.doesNotMatch(html, /\[\/?colour[:\]]|\+\+|\*\*\*/);
  const unsafe=render("++[colour:#ff7aaf]**<img src=x onerror=alert(1)>** [Open](javascript:alert%281%29)[/colour]++");
  assert.doesNotMatch(unsafe, /<(img|script|a)\b/);
  assert.ok(unsafe.includes("&lt;img"));
  const nested=render("[colour:#ff7aaf]++[colour:#79baff]Hello[/colour]++[/colour]");
  assert.ok(nested.includes('data-prompt-colour="#79baff"'));
  assert.doesNotMatch(nested, /\[\/?colour[:\]]/);
  const deep=render("[colour:#ff7aaf]".repeat(30)+"Text"+"[/colour]".repeat(30));
  assert.ok(deep.includes("Text"));
  assert.doesNotMatch(deep, /<(script|img)\b/);
});

test("handles incomplete streamed Markdown and keeps code literal", () => {
  assert.ok(render("## Working\n\n[Source](https://").includes("<h2>Working</h2>"));
  const html = render("```js\n[Not a link](javascript:alert(1))\n<script>\n");
  assert.ok(html.includes("&lt;script&gt;"));
  assert.doesNotMatch(html, /<a\b|<script\b/);
});
