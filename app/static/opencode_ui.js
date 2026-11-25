/* Optional OpenCode gateway settings. No CLI or environment credentials are read. */
(() => {
  "use strict";
  const form=document.querySelector("#settingsForm"), provider="opencode";
  const field=name=>form.elements[name], get=id=>document.getElementById(id);
  let pending, generation=0;
  for (const [id,name] of [["opencodeModel","ai.model"],["opencodeAnalysis","ai.analysis_model"]]) {
    get(id).onchange=()=>{
      field(name).value=get(id).value;
      field(name).dispatchEvent(new Event("input",{bubbles:true}));
    };
  }
  get("downloadOpenCode").onclick=async()=>{
    try {
      const config=await api("/api/opencode/config");
      const url=URL.createObjectURL(new Blob([JSON.stringify(config,null,2)+"\n"],{type:"application/json"}));
      const link=document.createElement("a");link.href=url;link.download="opencode.json";link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(error) {get("opencodeHint").textContent=error.message;}
  };
  async function update(_,config) {
    const version=++generation, selected=field("ai.provider").value===provider;
    get("opencodeModels").hidden=!selected;
    if (!selected) return;
    get("bedrockSetup").hidden=true;get("bedrockSettings").hidden=true;
    get("bedrockGPTModels").hidden=true;get("apiModelLabel").hidden=true;
    get("analysisModelLabel").hidden=true;
    field("ai.region").value="us-east-2";field("ai.bedrock_auth").value="bearer";
    field("ai.bedrock_endpoint").value="runtime";
    if (["bedrock","bedrock-openai",provider].includes(config.ai?.provider) && config.ai?.api_key_configured)
      field("ai.api_key").placeholder="Saved Bedrock key · leave blank to keep";
    try {
      pending ||= api("/api/opencode/models").catch(error=>{pending=null;throw error;});
      const result=await pending;
      if (version!==generation || field("ai.provider").value!==provider) return;
      field("ai.provider").querySelector('[value="opencode"]').disabled=!result.enabled;
      get("opencodeHint").textContent=result.enabled ? result.message : "OpenCode is disabled on this server.";
      for (const [id,name,optional] of [["opencodeModel","ai.model",false],["opencodeAnalysis","ai.analysis_model",true]]) {
        const picker=get(id);picker.replaceChildren();
        if (optional) {const option=new Option("Use Standard only","");picker.add(option);}
        for (const model of result.models) {
          const option=new Option(model.title+(model.vision?"":" · text only")+(model.premium?" · premium":""),
            model.id);
          option.title=model.id;picker.add(option);
        }
        const saved=field(name).value;
        picker.value=result.models.some(model=>model.id===saved) ? saved :
          optional ? "" : "bedrock-runtime-openai/us.openai.gpt-6.2-sol";
        field(name).value=picker.value;
      }
    } catch {
      get("apiModelLabel").hidden=false;
      get("opencodeHint").textContent="Catalog could not load. Retry before saving OpenCode.";
    }
  }
  window.AiMateOpenCode=Object.freeze({update});
})();
