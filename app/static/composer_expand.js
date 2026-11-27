/* Optional larger draft view. Keep the original editor and its state intact. */
(() => {
  "use strict";
  if (window.AiMateFeatures?.composerExpand === false) return;
  const form = document.querySelector("#chatForm");
  const field = document.querySelector("#question");
  if (!form || !field) return;
  const button = document.createElement("button");
  button.type = "button";
  button.id = "composerExpand";
  button.className = "composer-expand-toggle";
  button.setAttribute("aria-controls", "chatForm");
  form.prepend(button);
  form.classList.add("composer-expand-ready");
  let expanded = false;
  let previousFocus;
  let scrollTop = 0;
  const inertStates = new Map();
  const paths = {
    expand: "M8 3H3v5m0-5 6 6m7 12h5v-5m0 5-6-6",
    restore: "M3 9h6V3m0 6L3 3m18 12h-6v6m0-6 6 6",
  };
  function render() {
    const label = expanded ? "Restore editor" : "Expand editor";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-expanded", String(expanded));
    button.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
      stroke-linejoin="round" aria-hidden="true"><path d="${paths[expanded ? "restore" : "expand"]}"/></svg>`;
  }
  function setExpanded(value) {
    if (value === expanded) return;
    const scroller = form.querySelector(".cm-scroller") || field;
    const currentScroll = scroller.scrollTop;
    if (value) {
      previousFocus = document.activeElement;
      scrollTop = currentScroll;
      // Disable only siblings along the form's ancestor path, never the editor.
      for (let node = form; node.parentElement && node !== document.body; node = node.parentElement) {
        for (const sibling of node.parentElement.children) {
          if (sibling === node || ["SCRIPT", "LINK", "STYLE", "DIALOG"].includes(sibling.tagName)) continue;
          inertStates.set(sibling, sibling.inert);
          sibling.inert = true;
        }
      }
      form.setAttribute("role", "dialog");
      form.setAttribute("aria-modal", "true");
      form.setAttribute("aria-label", "Expanded message editor");
    } else {
      for (const [node, wasInert] of inertStates) node.inert = wasInert;
      inertStates.clear();
      form.removeAttribute("role");
      form.removeAttribute("aria-modal");
      form.removeAttribute("aria-label");
    }
    expanded = value;
    form.classList.toggle("composer-expanded", value);
    document.body.classList.toggle("composer-is-expanded", value);
    render();
    scroller.scrollTop = value ? currentScroll : scrollTop;
    if (!value) (previousFocus?.isConnected ? previousFocus : button).focus({preventScroll: true});
    window.dispatchEvent(new Event("resize"));
  }
  button.addEventListener("click", () => setExpanded(!expanded));
  document.addEventListener("keydown", event => {
    if (!expanded || event.isComposing || document.querySelector("dialog[open]")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setExpanded(false);
    } else if (event.key === "Tab") {
      const controls = Array.from(form.querySelectorAll(
        "button:not(:disabled),select:not(:disabled),input:not(:disabled),textarea:not(:disabled),[tabindex='0'],[contenteditable='true']",
      )).filter(node => !node.hidden && node.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    }
  });
  render();
})();
