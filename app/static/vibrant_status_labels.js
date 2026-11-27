/* Optional semantic palette; never changes the evidence or assessment wording. */
(() => {
  if (window.AiMateFeatures?.vibrantStatusLabels === false) return;
  document.documentElement.classList.add("vibrant-status-labels");
})();
