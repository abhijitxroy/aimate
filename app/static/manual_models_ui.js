/* Direct model choice affects one request, never saved Standard/Analysis slots. */
window.AiMateManualModels = (() => {
  "use strict";
  let generation = 0;
  function syncActive() {
    const picker = document.querySelector("#modelMode"), group = picker.querySelector("[data-manual-models]");
    const unavailable = config.ai?.provider !== "bedrock" || demo || window.AiMateLocalAI?.active();
    if (group) { group.hidden = Boolean(unavailable); group.disabled = Boolean(unavailable); }
    if (unavailable && picker.value.startsWith("manual:")) picker.value = "auto";
  }
  async function update() {
    const picker = document.querySelector("#modelMode"), version = ++generation;
    if (config.ai?.provider !== "bedrock" || demo || window.AiMateLocalAI?.active()) {
      picker.querySelector("[data-manual-models]")?.remove();
      if (picker.value.startsWith("manual:")) picker.value = "auto";
      return;
    }
    try {
      const result = await api("/api/bedrock/models");
      if (version !== generation || config.ai?.provider !== "bedrock") return;
      const current = picker.value, saved = localStorage.getItem("aimate-model-mode");
      picker.querySelector("[data-manual-models]")?.remove();
      if (!result.manual_enabled) { renderModelSelection(); return; }
      const group = document.createElement("optgroup");
      group.label = window.AiMateFeatures?.latestModelChoices === false ? "Claude · direct selection" : "Claude · latest models";
      group.dataset.manualModels = "true";
      const models = [...new Map([...result.presets, ...result.models].map(row => [row.id, row])).values()];
      // Settings may already be open with the fallback presets. Refresh its
      // saved-account catalog too, without replacing an unsaved draft.
      bedrockCatalog = models;
      bedrockPresetEndpoint = config.ai.bedrock_endpoint || "runtime";
      if (!dirtyConnections.has("ai") && document.querySelector("#settingsForm").elements["ai.provider"].value === "bedrock") {
        document.querySelector("#bedrockModelsHint").textContent = result.message;
        renderBedrockModels();
      }
      const preferred = current.startsWith("manual:") ? current : saved?.startsWith("manual:") ? saved : current;
      const choices = window.AiMateLatestModels?.choose(models, {
        region:config.ai.region,endpoint:config.ai.bedrock_endpoint,
        preferred:[preferred?.replace(/^manual:/,""),config.ai.model,config.ai.analysis_model].filter(Boolean)
      }) || models;
      for (const row of choices) {
        const option = document.createElement("option");
        option.value = "manual:" + row.id; option.dataset.manualModel = row.id;
        option.textContent = shortModelName(row.id);
        option.title = "Invocation access is checked when used." +
          (/opus|fable/.test(row.id) ? " Higher-cost model; manual selection." : "");
        group.append(option);
      }
      picker.append(group);
      if ([...picker.options].some(option => option.value === preferred)) picker.value = preferred;
      else if(preferred?.startsWith("manual:")) {
        picker.value="auto";
        document.querySelector("#activity").textContent="The previous model is not in the latest list. Choose a model; saved Standard/Analysis settings are unchanged.";
        localStorage.setItem("aimate-model-mode","auto");
      }
      syncActive();
      renderModelSelection();
    } catch { /* Existing Auto/Standard/Analysis remain usable if discovery fails. */ }
  }
  document.addEventListener("aimate:state", update);
  window.addEventListener("aimate-import-state", update);
  return Object.freeze({update,syncActive});
})();
