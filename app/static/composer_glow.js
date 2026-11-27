/* Local appearance preference, driven by the current conversation's Stop control. */
(() => {
  "use strict";
  if (window.AiMateFeatures?.composerGlow === false) return;
  const form = document.querySelector("#chatForm");
  const stop = document.querySelector("#stop");
  const appearance = document.querySelector("#appearanceDialog");
  if (!form || !stop || !appearance) return;
  const key = "aimate.composer.glow";
  let enabled = true;
  try { enabled = localStorage.getItem(key) !== "false"; } catch {}
  const label = document.createElement("label");
  label.className = "composer-glow-setting";
  const toggle = document.createElement("input");
  toggle.type = "checkbox";
  toggle.id = "composerGlowToggle";
  toggle.checked = enabled;
  const copy = document.createElement("span");
  const title = document.createElement("strong");
  title.textContent = "Reply border light";
  const hint = document.createElement("small");
  hint.textContent = "Soft red heartbeat while AiMate prepares a reply.";
  copy.append(title, hint);
  label.append(toggle, copy);
  appearance.querySelector(".hint").before(label);
  form.classList.add("composer-glow-ready");
  function refresh() {
    form.classList.toggle("composer-generating",
      enabled && !stop.hidden && document.visibilityState !== "hidden");
  }
  toggle.addEventListener("change", () => {
    enabled = toggle.checked;
    try { localStorage.setItem(key, String(enabled)); } catch {}
    refresh();
  });
  new MutationObserver(refresh).observe(stop, {attributes: true, attributeFilter: ["hidden"]});
  document.addEventListener("visibilitychange", refresh);
  window.addEventListener("storage", event => {
    if (event.key !== key && event.key !== null) return;
    try { enabled = localStorage.getItem(key) !== "false"; } catch { return; }
    toggle.checked = enabled;
    refresh();
  });
  refresh();
})();
