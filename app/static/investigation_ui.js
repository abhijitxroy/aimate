(() => {
  "use strict";
  const dialog = document.querySelector("#investigationDialog");
  const preset = document.querySelector("#investigationPreset");
  const target = document.querySelector("#investigationTarget");
  const notes = document.querySelector("#investigationNotes");
  const steps = document.querySelector("#investigationSteps");
  const sources = document.querySelector("#investigationEvidence");
  const status = document.querySelector("#investigationStatus");
  let conversation = null, workflows = {}, session = csrf;
  const trigger = document.createElement("button");
  trigger.type = "button"; trigger.textContent = "Investigation workspace"; trigger.id = "openInvestigation";
  document.querySelector("#chatMenu > div").prepend(trigger);
  function renderSteps(checked = []) {
    steps.replaceChildren();
    for (const [index, text] of (workflows[preset.value]?.steps || []).entries()) {
      const label = document.createElement("label"), input = document.createElement("input");
      input.type = "checkbox"; input.value = index; input.checked = checked.includes(index);
      label.append(input, document.createTextNode(text)); steps.append(label);
    }
  }
  preset.onchange = () => renderSteps();
  function body() {
    return {preset:preset.value, target:target.value, notes:notes.value,
      checked:[...steps.querySelectorAll("input:checked")].map(input => Number(input.value))};
  }
  trigger.onclick = async () => {
    if (!cid || privateChat) { document.querySelector("#activity").textContent = "Use a saved chat for a persistent investigation."; return; }
    const id = cid, sessionAtOpen = csrf;
    try {
      const data = await api(`/api/conversations/${id}/investigation`);
      if (cid !== id || sessionAtOpen !== csrf) return;
      conversation = id; workflows = data.presets; preset.replaceChildren();
      for (const [key, value] of Object.entries(workflows)) {
        const option = document.createElement("option"); option.value = key; option.textContent = value.name; preset.append(option);
      }
      const record = data.record;
      preset.value = record?.preset || "linked";
      target.value = record?.target || ""; notes.value = record?.notes || "";
      renderSteps(record?.checked || []);
      status.textContent = record ? "Saved " + new Date(record.updated * 1000).toLocaleString() : "Choose a workflow and save a checkpoint.";
      sources.replaceChildren();
      if (!data.evidence.length) sources.textContent = "No readable, currently scoped sources saved in this chat yet.";
      for (const item of data.evidence) {
        const card = document.createElement("article"); card.className = "investigation-source";
        const link = document.createElement("a");
        const url = new URL(item.url);
        if (!["http:", "https:"].includes(url.protocol)) continue;
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.textContent = item.service + " · " + url.pathname;
        const details = document.createElement("small");
        details.textContent = item.coverage + " · " + new Date(item.read_at * 1000).toLocaleString() + " · " + item.fingerprint;
        card.append(link, details); sources.append(card);
      }
      dialog.showModal();
    } catch (error) { document.querySelector("#activity").textContent = error.message; }
  };
  document.querySelector("#investigationForm").onsubmit = async event => {
    event.preventDefault();
    try {
      await api(`/api/conversations/${conversation}/investigation`, {method:"PUT",body:JSON.stringify(body())});
      status.textContent = "Checkpoint saved. Checklist ticks are your notes, not a verified verdict.";
      status.classList.add("success");
    } catch (error) { status.textContent = error.message; status.classList.remove("success"); }
  };
  document.querySelector("#resumeInvestigation").onclick = async () => {
    if (!target.value.trim()) { target.focus(); return; }
    try {
      await api(`/api/conversations/${conversation}/investigation`, {method:"PUT",body:JSON.stringify(body())});
      const value = `Continue the ${workflows[preset.value].name.toLowerCase()} for ${target.value.trim()}. Use the saved checkpoint, recheck mutable sources and report evidence coverage and remaining steps.`;
      dialog.close();
      document.dispatchEvent(new CustomEvent("aimate:choice",{detail:value}));
    } catch (error) { status.textContent = error.message; }
  };
  document.addEventListener("aimate:state", () => {
    if (session !== csrf || document.querySelector("#workspace").hidden) {
      session = csrf;
      dialog.close(); conversation = null; notes.value = ""; target.value = ""; sources.replaceChildren(); steps.replaceChildren();
    }
  });
})();
