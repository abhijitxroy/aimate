/* Markdown authoring: saved text stays portable, no HTML or contenteditable. */
(() => {
  "use strict";
  const field = document.querySelector("#question");
  const toolbar = document.querySelector("#composerToolbar");
  const preview = document.querySelector("#composerPreview");
  const format = document.querySelector("#composerFormatting");
  let selection = [0, 0];
  for (const event of ["select", "keyup", "click", "input"]) field.addEventListener(event, () => {
    selection = [field.selectionStart, field.selectionEnd];
    if (!preview.hidden) renderPrompt(preview, field.value);
  });
  function replace(value, start, end, selectedStart = start, selectedEnd = start + value.length) {
    if (field.value.length - (end - start) + value.length > field.maxLength) {
      document.querySelector("#activity").textContent = "Message is too long. Attach the text as a file.";
      return;
    }
    field.setRangeText(value, start, end, "end");
    field.focus({preventScroll:true});
    field.setSelectionRange(selectedStart, selectedEnd);
    field.dispatchEvent(new Event("input", {bubbles:true}));
  }
  function wrap(before, after = before, fallback = "text") {
    const [start, end] = selection;
    const chosen = field.value.slice(start, end) || fallback;
    replace(before + chosen + after, start, end, start + before.length, start + before.length + chosen.length);
  }
  function lines(prefix, fallback = "text") {
    const [selectedStart, selectedEnd] = selection;
    const start = field.value.lastIndexOf("\n", selectedStart - 1) + 1;
    let end = field.value.indexOf("\n", selectedEnd);
    if (end < 0) end = field.value.length;
    const text = field.value.slice(start, end) || fallback;
    replace(text.split("\n").map((line, i) => typeof prefix === "function" ? prefix(line, i) : prefix + line).join("\n"), start, end);
  }
  function button(label, action, title = label) {
    const node = document.createElement("button");
    node.type = "button"; node.textContent = label; node.title = title; node.setAttribute("aria-label",title);
    node.onmousedown = event => event.preventDefault();
    node.onclick = action; toolbar.append(node); return node;
  }
  button("B", () => wrap("**"), "Bold");
  button("I", () => wrap("*"), "Italic");
  button("U", () => wrap("++"), "Underline");
  const colour = document.createElement("input");
  colour.type = "color"; colour.value = "#79baff"; colour.setAttribute("aria-label","Text colour");
  toolbar.append(colour);
  button("Colour", () => wrap("[colour:" + colour.value + "]", "[/colour]"), "Apply text colour");
  button("H", () => lines("## "), "Heading");
  button("¶", () => wrap("\n\n", "\n\n"), "Paragraph");
  button("•", () => lines("- "), "Bullet list");
  button("1.", () => lines((line,i) => `${i+1}. ${line}`), "Numbered list");
  button("→", () => lines("    "), "Indent");
  button("←", () => lines(line => line.replace(/^ {1,4}|\t/, "")), "Outdent");
  button("</>", () => wrap("```text\n", "\n```"), "Code block");
  button("—", () => wrap("\n\n---\n\n", "", ""), "Horizontal rule");
  button("Table", () => wrap("\n\n| Column | Value |\n| --- | --- |\n| ", " | Value |\n\n", "Item"));
  button("Info", () => lines("> "), "Quote");
  button("Note", () => wrap("\n\n> [!NOTE]\n> ", "\n\n"), "Information panel");
  button("Warning", () => wrap("\n\n> [!WARNING]\n> ", "\n\n"), "Warning panel");
  const wrapping = button("Wrap", () => {
    const on = field.wrap !== "off";
    field.wrap = on ? "off" : "soft";
    wrapping.setAttribute("aria-pressed", String(!on));
    field.style.whiteSpace = on ? "pre" : "pre-wrap";
  }, "Toggle line wrapping");
  wrapping.setAttribute("aria-pressed","true");
  const toggle = button("Preview", () => {
    preview.hidden = !preview.hidden;
    toggle.setAttribute("aria-pressed", String(!preview.hidden));
    if (!preview.hidden) renderPrompt(preview, field.value);
  }, "Preview formatted message");
  toggle.setAttribute("aria-pressed","false");
  format.addEventListener("toggle", () => {
    if (!format.open) { preview.hidden = true; toggle.setAttribute("aria-pressed","false"); }
  });
  document.addEventListener("aimate:state", () => {
    if (!field.value && !preview.hidden) renderPrompt(preview, "");
  });
})();
