/* Local markdown-it 15.0.3; raw HTML and remote images are never rendered. */
const answerMarkdown = window.markdownit({html: false, breaks: false, linkify: false})
  .disable("image");
answerMarkdown.validateLink = url => {
  try { return ["https:", "http:"].includes(new URL(url).protocol); }
  catch { return false; }
};
// Parse nested authoring formats through the same safe inline parser.
answerMarkdown.inline.ruler.before("emphasis", "aimate_format", (state, silent) => {
  const depth = state.env.aimateFormatDepth || 0;
  if (depth >= 8) return false;
  const source = state.src.slice(state.pos, state.pos + 4000);
  const underline = source.match(/^\+\+([^\n]+?)\+\+/);
  const colour = !underline && source.match(/^\[colour:(#[0-9a-fA-F]{6})\]/);
  let content, length, meta;
  if (underline) {
    content=underline[1];length=underline[0].length;meta={underline:true};
  } else if (colour) {
    const tags=/\[colour:#[0-9a-fA-F]{6}\]|\[\/colour\]/g;
    tags.lastIndex=colour[0].length;
    let nesting=1, tag;
    while ((tag=tags.exec(source))) {
      nesting+=tag[0] === "[/colour]" ? -1 : 1;
      if (nesting === 0) {
        content=source.slice(colour[0].length,tag.index);
        length=tags.lastIndex;meta={colour:colour[1].toLowerCase()};break;
      }
    }
  }
  if (!content) return false;
  if (!silent) {
    const token = state.push("aimate_format", "span", 0);
    token.content = content;
    token.meta = meta;
    token.children = [];
    state.md.inline.parse(token.content, state.md, {...state.env, aimateFormatDepth:depth + 1}, token.children);
  }
  state.pos += length;
  return true;
});
answerMarkdown.renderer.rules.aimate_format = (tokens, index, options, env, renderer) => {
  const token = tokens[index], text = renderer.renderInline(token.children, options, env);
  return token.meta.underline ? `<span class="prompt-underline">${text}</span>`
    : `<span data-prompt-colour="${token.meta.colour}">${text}</span>`;
};
const renderAnswerLink = answerMarkdown.renderer.rules.link_open ||
  ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options));
answerMarkdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet("target", "_blank");
  tokens[index].attrSet("rel", "noopener noreferrer");
  return renderAnswerLink(tokens, index, options, env, renderer);
};
answerMarkdown.inline.ruler.before("emphasis","answer_tone",(state,silent)=>{
  const depth=state.env.aimateFormatDepth || 0;
  if(depth>=8) return false;
  const match=state.src.slice(state.pos,state.pos+2000).match(/^\[tone:(success|warning|danger|info)\]([^\n]+?)\[\/tone\]/);
  if(!match) return false;
  if(!silent) {
    const token=state.push("answer_tone","span",0);token.meta={tone:match[1]};token.children=[];
    state.md.inline.parse(match[2],state.md,{...state.env,aimateFormatDepth:depth+1},token.children);
  }
  state.pos+=match[0].length;return true;
});
answerMarkdown.renderer.rules.answer_tone=(tokens,index,options,env,renderer)=>
  `<span class="answer-tone-${tokens[index].meta.tone}">${renderer.renderInline(tokens[index].children,options,env)}</span>`;

function renderAnswer(body, text) {
  // Only the parser's escaped output enters this HTML sink. Never enable html
  // or add plugins that accept raw model-supplied HTML.
  body.innerHTML = answerMarkdown.render(text);
  if (typeof body.querySelectorAll !== "function") return;
  for (const span of body.querySelectorAll("[data-prompt-colour]")) {
    if (/^#[0-9a-f]{6}$/.test(span.dataset.promptColour)) span.style.color = span.dataset.promptColour;
  }
  for (const table of body.querySelectorAll("table")) {
    const scroll = document.createElement("div"); scroll.className = "answer-table"; scroll.tabIndex = 0;
    if (window.AiMateFeatures?.modernTables !== false) scroll.classList.add("answer-table-modern");
    scroll.setAttribute("aria-label", "Scrollable table");
    table.replaceWith(scroll); scroll.append(table);
  }
  const callouts = {NOTE: ["ℹ", "note"], TIP: ["✦", "tip"], WARNING: ["⚠", "warning"], CAUTION: ["!", "danger"], SUCCESS: ["✓", "success"]};
  for (const quote of body.querySelectorAll("blockquote")) {
    const paragraph = quote.querySelector("p"), first = paragraph?.firstChild;
    const match = first?.nodeType === 3 && first.textContent.match(/^\[!(NOTE|TIP|WARNING|CAUTION|SUCCESS)\]\s*/);
    if (!match) continue;
    first.textContent = first.textContent.slice(match[0].length);
    const [icon, kind] = callouts[match[1]];
    quote.classList.add("answer-callout", kind);
    const title = document.createElement("div"); title.className = "callout-title";
    title.textContent = icon + " " + match[1].toLowerCase().replace(/^./, c => c.toUpperCase());
    quote.prepend(title);
  }
  for (const pre of body.querySelectorAll("pre")) {
    const code = pre.querySelector("code");
    const language = code?.className.match(/\blanguage-([\w+.-]+)/)?.[1]?.toLowerCase() || "";
    let rich = null;
    if (["chart", "metrics", "poll"].includes(language)) {
      try { rich = richAnswerBlock(language, JSON.parse(code.textContent)); } catch { /* Incomplete or invalid structured data stays literal code. */ }
    }
    if (rich) { pre.replaceWith(rich); continue; }
    decorateCodeBlock(pre, code, language);
  }
  window.AiMateAnswerLabels?.render(body);
}

function codeLanguage(source, requested = "") {
  const aliases = {yml: "yaml", py: "python", js: "javascript", ts: "typescript",
    ps1: "powershell", ps: "powershell", sh: "bash", "c#": "csharp", "c++": "cpp"};
  const language = String(requested).trim().toLowerCase();
  if (language) return aliases[language] || language;
  // Conservative detection for unlabelled data; never rewrite or format its text.
  try {
    if (/^[\s]*[\[{]/.test(source) && JSON.parse(source) !== null) return "json";
  } catch { /* Partial JSON remains readable literal text. */ }
  if ((source.match(/^\s*[\w.-]+:\s/gm) || []).length >= 2) return "yaml";
  return "text";
}

function highlightCodeElement(code, requested = "") {
  const source = code.textContent || "", language = codeLanguage(source, requested);
  code.classList.add("syntax-code");
  code.dataset.language = language;
  // Bound synchronous work during streamed answers and large log rendering.
  if (!window.hljs || source.length > 50000 || !window.hljs.getLanguage(language)) return language;
  try {
    // highlight.js escapes source text and emits only its own token spans.
    code.innerHTML = window.hljs.highlight(source, {language, ignoreIllegals: true}).value;
  } catch { code.textContent = source; }
  return language;
}

function decorateCodeBlock(pre, code, requested = "") {
    if (!code) return;
    const language = highlightCodeElement(code, requested);
    const names = {json: "JSON", yaml: "YAML", python: "Python", javascript: "JavaScript",
      typescript: "TypeScript", powershell: "PowerShell", bash: "Shell", sql: "SQL",
      xml: "HTML / XML", html: "HTML", css: "CSS", cpp: "C++", csharp: "C#", text: "Text"};
    const shell = document.createElement("div"); shell.className = "answer-code";
    const toolbar = document.createElement("div"); toolbar.className = "code-toolbar";
    const label = document.createElement("span"); label.textContent = names[language] || language;
    const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy code";
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(code?.textContent || pre.textContent); copy.textContent = "Copied"; }
      catch { copy.textContent = "Copy failed"; }
    };
    toolbar.append(label, copy); pre.replaceWith(shell); shell.append(toolbar, pre);
}

function renderDataValue(body, text) {
  if (/^```/m.test(text)) { renderAnswer(body, text); return; }
  const language = codeLanguage(text);
  if (language === "text") { body.textContent = text; return; }
  const pre = document.createElement("pre"), code = document.createElement("code");
  code.textContent = text; pre.append(code); body.replaceChildren(pre);
  decorateCodeBlock(pre, code, language);
}

function renderPrompt(body, text) {
  const formatted = /(\*\*|__|\+\+|\[colour:|(^|\s)\*[^*]+\*(?=\s|$)|^#{1,6} |^> |^\s*[-*] |^\d+\. |^```|^ {4}\S|^\|.*\||^---$)/m.test(text);
  // Markdown emits layout newlines between HTML blocks. They are not additional
  // user-authored breaks; raw prose and code still retain their own whitespace.
  body.classList?.toggle("formatted-prompt", formatted);
  if (formatted) renderAnswer(body, text);
  else renderDataValue(body, text);
}

function richAnswerBlock(kind, data) {
  const make = (tag, className, text) => {
    const node = document.createElement(tag); node.className = className;
    if (text !== undefined) node.textContent = text; return node;
  };
  const short = value => typeof value === "string" && value.trim().length > 0 && value.length <= 300;
  if (kind === "metrics") {
    if (!Array.isArray(data) || !data.length || data.length > 8 ||
        !data.every(m => m && short(m.label) && (short(m.value) || typeof m.value === "number" && Number.isFinite(m.value)))) return null;
    const grid = make("div", "answer-metrics");
    for (const metric of data) {
      const status = ["success", "warning", "danger"].includes(metric.status) ? metric.status : "neutral";
      const card = make("div", "metric-card " + status);
      card.append(make("span", "metric-label", metric.label), make("strong", "metric-value", metric.value)); grid.append(card);
    }
    return grid;
  }
  if (kind === "chart") {
    if (!data || !short(data.title) || !Array.isArray(data.labels) || !Array.isArray(data.values) ||
        !data.values.length || data.values.length > 20 || data.labels.length !== data.values.length ||
        !data.labels.every(short) || !data.values.every(v => typeof v === "number" && Number.isFinite(v) && v >= 0) ||
        data.unit !== undefined && !short(data.unit)) return null;
    const figure = make("figure", "answer-chart"); figure.setAttribute("aria-label", data.title);
    figure.append(make("figcaption", "", data.title));
    const max = Math.max(...data.values, 1);
    for (let i = 0; i < data.values.length; i++) {
      const row = make("div", "chart-row"), track = make("div", "chart-track"), bar = make("div", "chart-bar");
      bar.style.width = (data.values[i] / max * 100) + "%";
      const value = data.values[i].toLocaleString() + (data.unit ? " " + data.unit : "");
      row.title = data.labels[i] + ": " + value; track.append(bar);
      row.append(make("span", "chart-label", data.labels[i]), track, make("span", "chart-value", value)); figure.append(row);
    }
    return figure;
  }
  if (kind === "poll") {
    if (!data || !short(data.question) || !Array.isArray(data.options) || data.options.length < 2 ||
        data.options.length > 6 || !data.options.every(short)) return null;
    const card = make("section", "answer-choices");
    card.append(make("p", "choice-title", data.question));
    const choices = make("div", "choice-buttons");
    for (const option of data.options) {
      const button = make("button", "", option); button.type = "button";
      button.onclick = () => document.dispatchEvent(new CustomEvent("aimate:choice", {detail: option}));
      choices.append(button);
    }
    card.append(choices, make("small", "hint", "Choose an option, then press Ask.")); return card;
  }
  return null;
}
