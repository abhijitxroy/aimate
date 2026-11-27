/* Presentation only: keep exact IDs/routes internally; never change saved slots. */
(function(root) {
  "use strict";
  const families=["haiku","sonnet","opus","fable"];
  function describe(id) {
    const modern=String(id).match(/claude-([a-z]+)-(\d+)(?:[-.](\d{1,2})(?!\d))?/i);
    const legacy=String(id).match(/claude-(\d+)(?:-(\d{1,2}))?-(haiku|sonnet|opus)/i);
    if(!modern && !legacy) return null;
    const family=(modern ? modern[1] : legacy[3]).toLowerCase();
    const major=Number(modern ? modern[2] : legacy[1]),minor=Number((modern ? modern[3] : legacy[2]) || 0);
    return {family,major,minor,label:family[0].toUpperCase()+family.slice(1)+" "+major+(minor ? "."+minor : "")};
  }
  function choose(rows,{region="us-east-2",endpoint="runtime",preferred=[]}={}) {
    if(root.AiMateFeatures?.latestModelChoices===false) return rows;
    const route=region.startsWith("eu-") ? "eu." : region.startsWith("ap-") ? "apac." : "us.";
    function score(row) {
      const known=preferred.indexOf(row.id);
      if(known>=0) return 1000-known;
      if(endpoint==="mantle") return row.id.startsWith("anthropic.") ? 100 : 0;
      return row.id.startsWith(route) ? 100 : row.id.startsWith("global.") ? 80 :
        /^(?:us|eu|apac|au)\./.test(row.id) ? 60 : 20;
    }
    const latest=new Map();
    for(const row of rows) {
      const version=describe(row.id);
      if(!version) continue;
      const old=latest.get(version.family);
      if(!old || version.major>old.major || version.major===old.major && version.minor>old.minor ||
         version.major===old.major && version.minor===old.minor && score(row)>score(old.row)) {
        latest.set(version.family,{...version,row});
      }
    }
    const order=[...families,...[...latest.keys()].filter(family=>!families.includes(family)).sort()];
    return order.filter(family=>latest.has(family)).map(family=>{
      const selected=latest.get(family);
      return {...selected.row,label:selected.label};
    });
  }
  function guidance(id) {
    const family=describe(id)?.family;
    return {
      haiku:["Fastest","Low-cost, high-volume work."],
      sonnet:["Balanced","Daily work."],
      opus:["High capability","Detailed knowledge work."],
      fable:["Premium","Use explicitly for specialist work; check access and budget in Connections."]
    }[family] || ["",""];
  }
  function compactPicker(picker,{model,analysis_model,currentModel},shortName) {
    const enabled=root.AiMateFeatures?.cleanModelPicker!==false;
    const selected=picker.selectedOptions[0];
    const chosenId=selected?.dataset.manualModel || currentModel ||
      (["analysis","auto-quality"].includes(picker.value) ? analysis_model : model);
    const manual=[...picker.options].filter(option=>option.dataset.manualModel && !option.parentElement.disabled);
    const seen=new Set();
    // Retain the active routing value. Cleaning its label must not silently turn
    // a saved Auto policy into a fixed model or rewrite configured model slots.
    for(const option of picker.options) {
      if(!enabled) { option.hidden=false; continue; }
      const id=option===selected ? chosenId : option.dataset.manualModel ||
        (["analysis","auto-quality"].includes(option.value) ? analysis_model : model);
      const active=option===selected;
      const manualChoice=Boolean(option.dataset.manualModel);
      const equivalent=manual.some(row=>row.dataset.manualModel===id);
      option.hidden=!active && (manualChoice ? id===chosenId :
        option.value.startsWith("auto") || equivalent || !id || id===chosenId || seen.has(id));
      if(!option.hidden) seen.add(id);
      const [category,detail]=guidance(id);
      const name=shortName(id);
      option.textContent=name+(category ? " · "+category : "");
      option.dataset.modelHelp ||= option.title;
      option.title=[detail,option.dataset.modelHelp].filter(Boolean).join(" ");
    }
    if(enabled) picker.setAttribute("aria-label","Model: "+shortName(chosenId));
  }
  const api=Object.freeze({choose,describe,guidance,compactPicker});
  if(typeof module==="object" && module.exports) module.exports=api;
  root.AiMateLatestModels=api;
})(globalThis);
