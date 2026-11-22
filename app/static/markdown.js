/* Local markdown-it 15.0.3; raw HTML and remote images are never rendered. */
const answerMarkdown = window.markdownit({html: false, breaks: false, linkify: false})
  .disable("image");
answerMarkdown.validateLink = url => {
  try { return ["https:", "http:"].includes(new URL(url).protocol); }
  catch { return false; }
};
const renderAnswerLink = answerMarkdown.renderer.rules.link_open ||
  ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options));
answerMarkdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet("target", "_blank");
  tokens[index].attrSet("rel", "noopener noreferrer");
  return renderAnswerLink(tokens, index, options, env, renderer);
};

function renderAnswer(body, text) {
  // Only the parser's escaped output enters this HTML sink. Never enable html
  // or add plugins that accept raw model-supplied HTML.
  body.innerHTML = answerMarkdown.render(text);
  if (typeof body.querySelectorAll !== "function") return;
  for (const table of body.querySelectorAll("table")) {
    const scroll = document.createElement("div"); scroll.className = "answer-table"; scroll.tabIndex = 0;
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
    const language = code?.className.replace("language-", "") || "text";
    let rich = null;
    if (["chart", "metrics", "poll"].includes(language)) {
      try { rich = richAnswerBlock(language, JSON.parse(code.textContent)); } catch { /* Incomplete or invalid structured data stays literal code. */ }
    }
    if (rich) { pre.replaceWith(rich); continue; }
    const shell = document.createElement("div"); shell.className = "answer-code";
    const toolbar = document.createElement("div"); toolbar.className = "code-toolbar";
    const label = document.createElement("span"); label.textContent = language;
    const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy code";
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(code?.textContent || pre.textContent); copy.textContent = "Copied"; }
      catch { copy.textContent = "Copy failed"; }
    };
    toolbar.append(label, copy); pre.replaceWith(shell); shell.append(toolbar, pre);
  }
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
