/* Local appearance preference, driven by the current conversation's Stop control. */
(() => {
  "use strict";
  if (window.AiMateFeatures?.composerGlow === false) return;
  const form = document.querySelector("#chatForm");
  const stop = document.querySelector("#stop");
  const appearance = document.querySelector("#appearanceDialog");
  if (!form || !stop || !appearance) return;
  const key = "aimate.composer.glow";
  const colourKey = key + ".colour";
  const savedColour = () => {
    try {
      const value = localStorage.getItem(colourKey);
      return /^#[0-9a-f]{6}$/i.test(value || "") ? value : null;
    } catch { return null; }
  };
  let customColour = savedColour();
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
  hint.textContent = "One heartbeat travels left to right while AiMate prepares a reply.";
  copy.append(title, hint);
  label.append(toggle, copy);
  appearance.querySelector(".hint").before(label);
  const colourRow = document.createElement("div");
  colourRow.className = "composer-glow-colour";
  const colourLabel = document.createElement("label");
  colourLabel.textContent = "Heartbeat colour";
  colourLabel.htmlFor = "composerGlowColour";
  const colour = document.createElement("input");
  colour.type = "color"; colour.id = "composerGlowColour";
  const reset = document.createElement("button");
  reset.type = "button"; reset.textContent = "Default";
  reset.title = "Restore the theme's default red";
  colourRow.append(colourLabel, colour, reset);
  label.after(colourRow);
  const heartbeat = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  heartbeat.classList.add("composer-heartbeat");
  heartbeat.setAttribute("preserveAspectRatio", "none");
  heartbeat.setAttribute("aria-hidden", "true");
  heartbeat.setAttribute("focusable", "false");
  const trace = document.createElementNS(heartbeat.namespaceURI, "g");
  trace.classList.add("heartbeat-trace");
  const path = document.createElementNS(heartbeat.namespaceURI, "path");
  path.setAttribute("vector-effect", "non-scaling-stroke");
  trace.append(path); heartbeat.append(trace);
  form.append(heartbeat);
  form.classList.add("composer-glow-ready");
  function resizeWave() {
    const width = Math.max(40, form.clientWidth - 2), pulseWidth = Math.min(80, width);
    const point = value => (value * pulseWidth / 80).toFixed(1);
    heartbeat.setAttribute("viewBox", `0 0 ${width} 26`);
    heartbeat.style.setProperty("--heartbeat-travel", `${width - pulseWidth}px`);
    path.setAttribute("d", `M0 13H${point(20)}L${point(26)} 9L${point(32)} 13H${point(40)}`
      + `L${point(47)} 3L${point(55)} 23L${point(63)} 13H${pulseWidth}`);
  }
  function refreshColour() {
    if (customColour) form.style.setProperty("--composer-activity-color", customColour);
    else form.style.removeProperty("--composer-activity-color");
    colour.value = getComputedStyle(form).getPropertyValue("--composer-activity-color").trim() || "#e97b87";
  }
  colour.addEventListener("input", () => {
    customColour = colour.value;
    try { localStorage.setItem(colourKey, customColour); } catch {}
    refreshColour();
  });
  reset.addEventListener("click", () => {
    customColour = null;
    try { localStorage.removeItem(colourKey); } catch {}
    refreshColour();
  });
  new ResizeObserver(resizeWave).observe(form);
  new MutationObserver(refreshColour).observe(document.documentElement,
    {attributes: true, attributeFilter: ["data-theme"]});
  resizeWave(); refreshColour();
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
    if (event.key !== key && event.key !== colourKey && event.key !== null) return;
    try { enabled = localStorage.getItem(key) !== "false"; } catch { return; }
    customColour = savedColour(); refreshColour();
    toggle.checked = enabled;
    refresh();
  });
  refresh();
})();
