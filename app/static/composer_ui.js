/* Markdown authoring: inline editor styling is optional; saved text stays portable. */
(() => {
  "use strict";
  if (window.AiMateFeatures?.composerFormatting === false) {
    document.querySelector("#composerFormatting").hidden = true;
    document.querySelector("#formatToggle").hidden = true;
    return;
  }
  const field = document.querySelector("#question");
  const toolbar = document.querySelector("#composerToolbar");
  const advanced = document.querySelector("#composerAdvanced");
  const preview = document.querySelector("#composerPreview");
  const toggle=document.querySelector("#formatToggle"),section=document.querySelector("#composerFormatting");
  let visible=true;
  try {visible=localStorage.getItem("aimate.formatting.visible") !== "false";} catch {}
  function showFormatting() {
    section.hidden=!visible;
    toggle.setAttribute("aria-pressed",String(visible));
    toggle.setAttribute("aria-expanded",String(visible));
    toggle.title=visible ? "Hide formatting" : "Show formatting";
  }
  toggle.onclick=()=>{
    visible=!visible;showFormatting();
    try {localStorage.setItem("aimate.formatting.visible",String(visible));} catch {}
  };
  showFormatting();
  let previewToggle;
  let selection = [0, 0];
  const formats=window.AiMateComposerFormats;
  const formatKeys={"Bold":"bold","Italic":"italic","Underline":"underline",
    "Apply text colour":"colour","Heading":"heading","Bullet list":"bullet",
    "Numbered list":"numbered","Indent":"indent","Code block":"code",
    "Horizontal rule":"rule","Insert table":"table","Quote":"quote",
    "Information panel":"note","Warning panel":"warning"};
  function updateFormats() {
    const current=formats?.inspect(field.value,field.selectionStart,field.selectionEnd);
    for (const node of document.querySelectorAll("#composerFormatting [data-format]")) {
      node.setAttribute("aria-pressed",String(Boolean(current?.states[node.dataset.format])));
    }
  }
  function fitEditor() {
    if(window.AiMateRichComposer?.enabled) {window.AiMateRichComposer.fit();return;}
    const scroll = field.scrollTop;
    field.style.height = "0px";
    const limit = Math.max(72, Math.min(240, window.innerHeight * .24));
    field.style.height = Math.max(46, Math.min(field.scrollHeight, limit)) + "px";
    field.style.overflowY = field.scrollHeight > field.clientHeight ? "auto" : "hidden";
    field.scrollTop = scroll;
  }
  function revealSelection() {
    if(window.AiMateRichComposer?.enabled) {window.AiMateRichComposer.reveal();return;}
    // Measure wrapped source up to the insertion, including tables and panels.
    const mirror = document.createElement("div");
    const style = getComputedStyle(field);
    Object.assign(mirror.style, {
      position:"fixed", visibility:"hidden", pointerEvents:"none",
      width:field.clientWidth+"px", font:style.font, lineHeight:style.lineHeight,
      letterSpacing:style.letterSpacing, whiteSpace:field.wrap === "off" ? "pre" : "pre-wrap",
      overflowWrap:"break-word", padding:style.padding, boxSizing:"border-box",
    });
    mirror.textContent = field.value.slice(0, field.selectionEnd) + "\u200b";
    document.body.append(mirror);
    const bottom = mirror.getBoundingClientRect().height;
    mirror.remove();
    const top = bottom - parseFloat(style.lineHeight);
    if (bottom > field.scrollTop + field.clientHeight) field.scrollTop = bottom - field.clientHeight;
    else if (top < field.scrollTop) field.scrollTop = Math.max(0, top);
  }
  for (const event of ["select", "keyup", "click", "input"]) field.addEventListener(event, () => {
    selection = [field.selectionStart, field.selectionEnd];
    if (event === "input") fitEditor();
    if (!preview.hidden) renderPrompt(preview, field.value);
    updateFormats();
  });
  function replace(value, start, end, selectedStart = start, selectedEnd = start + value.length) {
    if (field.value.length - (end - start) + value.length > field.maxLength) {
      document.querySelector("#activity").textContent = "Message is too long. Attach the text as a file.";
      return;
    }
    field.setRangeText(value, start, end, "end");
    if(!window.AiMateRichComposer?.enabled) {
      preview.hidden = false;
      previewToggle?.setAttribute("aria-pressed","true");
    }
    field.focus({preventScroll:true});
    field.setSelectionRange(selectedStart, selectedEnd);
    field.dispatchEvent(new Event("input", {bubbles:true}));
    revealSelection();
  }
  function wrap(before, after = before, fallback = "text") {
    const [start, end] = selection;
    const chosen = field.value.slice(start, end) || fallback;
    replace(before + chosen + after, start, end, start + before.length, start + before.length + chosen.length);
  }
  function toggleInline(kind, marker) {
    const [start,end]=selection;
    const range=formats?.inspect(field.value,start,end).ranges[kind];
    if (!range) { wrap(marker);return; }
    const content=field.value.slice(range.from+range.prefix,range.to-range.suffix);
    replace(content,range.from,range.to,
      Math.max(range.from,start-range.prefix),Math.min(range.from+content.length,end-range.prefix));
  }
  function lines(prefix, fallback = "text") {
    const [selectedStart, selectedEnd] = selection;
    const start = selectedStart === 0 ? 0 : field.value.lastIndexOf("\n", selectedStart - 1) + 1;
    const boundary = selectedEnd > selectedStart && field.value[selectedEnd - 1] === "\n" ? selectedEnd - 1 : selectedEnd;
    let end = field.value.indexOf("\n", boundary);
    if (end < 0) end = field.value.length;
    const text = field.value.slice(start, end) || fallback;
    replace(text.split("\n").map((line, i) => typeof prefix === "function" ? prefix(line, i) : prefix + line).join("\n"), start, end);
  }
  function button(label, action, title = label, extra = false) {
    const node = document.createElement("button");
    node.type = "button"; node.textContent = label; node.title = title; node.setAttribute("aria-label",title);
    if (formatKeys[title]) { node.dataset.format=formatKeys[title];node.setAttribute("aria-pressed","false"); }
    node.onmousedown = event => event.preventDefault();
    node.onclick = action; (extra ? advanced : toolbar).append(node); return node;
  }
  const bold=button("B", () => toggleInline("bold","**"), "Bold"); bold.className="format-bold";
  const italic=button("I", () => toggleInline("italic","*"), "Italic"); italic.className="format-italic";
  const underline=button("U", () => toggleInline("underline","++"), "Underline"); underline.className="format-underline";
  const colour = document.createElement("input");
  colour.type = "color"; colour.value = "#79baff"; colour.setAttribute("aria-label","Text colour");
  toolbar.append(colour);
  button("Colour", () => wrap("[colour:" + colour.value + "]", "[/colour]"), "Apply text colour");
  button("H", () => lines("## "), "Heading",true);
  button("¶", () => wrap("\n\n", "\n\n"), "Paragraph",true);
  button("•", () => lines("- "), "Bullet list");
  button("1.", () => lines((line,i) => `${i+1}. ${line}`), "Numbered list");
  button("→", () => lines("    "), "Indent",true);
  button("←", () => lines(line => line.replace(/^ {1,4}|\t/, "")), "Outdent",true);
  button("</>", () => wrap("```text\n", "\n```"), "Code block");
  button("—", () => wrap("\n\n---\n\n", "", ""), "Horizontal rule",true);
  button("Table", () => wrap("\n\n| Column | Value |\n| --- | --- |\n| ", " | Value |\n\n", "Item"), "Insert table",true);
  button("Info", () => lines("> "), "Quote",true);
  button("Note", () => wrap("\n\n> [!NOTE]\n> ", "\n\n"), "Information panel",true);
  button("Warning", () => wrap("\n\n> [!WARNING]\n> ", "\n\n"), "Warning panel",true);
  const wrapping = button("Wrap", () => {
    const on = field.wrap !== "off";
    field.wrap = on ? "off" : "soft";
    wrapping.setAttribute("aria-pressed", String(!on));
    field.style.whiteSpace = on ? "pre" : "pre-wrap";
    fitEditor(); revealSelection();
  }, "Toggle line wrapping",true);
  wrapping.setAttribute("aria-pressed","true");
  previewToggle = button("Preview", () => {
    preview.hidden = !preview.hidden;
    previewToggle.setAttribute("aria-pressed", String(!preview.hidden));
    if (!preview.hidden) renderPrompt(preview, field.value);
  }, "Preview formatted message");
  previewToggle.setAttribute("aria-pressed","false");
  const more = button("More", () => {
    advanced.hidden = !advanced.hidden;
    more.setAttribute("aria-expanded",String(!advanced.hidden));
  }, "More formatting");
  more.setAttribute("aria-expanded","false"); more.setAttribute("aria-controls","composerAdvanced");
  field.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.isComposing) return;
    const action={b:bold,i:italic,u:underline}[event.key.toLowerCase()];
    if (!action) return;
    event.preventDefault(); selection=[field.selectionStart,field.selectionEnd]; action.click();
  });
  document.addEventListener("aimate:state", () => {
    if (!field.value) { preview.hidden=true;previewToggle.setAttribute("aria-pressed","false"); }
    fitEditor();
    updateFormats();
  });
  window.addEventListener("resize", fitEditor);
  fitEditor();
  updateFormats();
})();
