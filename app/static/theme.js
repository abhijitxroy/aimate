(() => {
  function apply(theme) {
    theme = ["navy", "beige", "black-blue"].includes(theme) ? theme : "navy";
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("aimate.theme", theme); } catch {}
    window.dispatchEvent(new CustomEvent("aimate-theme", {detail: theme}));
  }
  let saved = "navy";
  try { saved = localStorage.getItem("aimate.theme") || "navy"; } catch {}
  apply(saved);
  window.AiMateAppearance = {apply};
})();
