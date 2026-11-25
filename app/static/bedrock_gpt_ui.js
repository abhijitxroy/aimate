/* Optional GPT-via-Bedrock settings, registered through updateBedrock(). */
(() => {
  "use strict";
  const provider="bedrock-openai", form=document.querySelector("#settingsForm");
  const field=name => form.elements[name];
  const get=id => document.getElementById(id);
  let catalog, generation=0;
  const pick=get("bedrockGPTModel");
  pick.onchange=()=>{
    if (pick.value !== "custom") field("ai.model").value=pick.value;
    get("apiModelLabel").hidden=pick.value !== "custom";
    field("ai.model").dispatchEvent(new Event("input",{bubbles:true}));
  };
  async function update(_, config) {
    const version=++generation, selected=field("ai.provider").value === provider;
    get("bedrockGPTModels").hidden=!selected;
    get("bedrockEndpointLabel").hidden=selected;
    get("bedrockAuthLabel").hidden=selected;
    if (!selected) {
      get("bedrockSimpleHint").textContent="Claude Haiku 5.5 · us-east-2 · Bedrock API key. Just add your token.";
      return;
    }
    const simple=field("ai.bedrock_mode").value !== "advanced";
    field("ai.bedrock_auth").value="bearer";
    field("ai.bedrock_endpoint").value="runtime";
    if (!field("ai.model").value) field("ai.model").value="us.openai.gpt-6.2-sol";
    if (simple || !field("ai.region").value) field("ai.region").value="us-east-2";
    get("bedrockSetup").hidden=false;
    get("bedrockSimpleHint").hidden=!simple;
    get("bedrockSimpleHint").textContent="GPT via Bedrock · us-east-2 · reuse your Bedrock key.";
    get("bedrockSettings").hidden=simple;
    get("analysisModelLabel").hidden=false;
    if (["bedrock","bedrock-openai"].includes(config.ai?.provider) && config.ai?.api_key_configured) {
      field("ai.api_key").placeholder="Saved Bedrock key · leave blank to keep";
    }
    try {
      catalog ||= api("/api/bedrock/gpt/models").catch(error=>{catalog=null;throw error;});
      const result=await catalog;
      if (version !== generation || field("ai.provider").value !== provider) return;
      field("ai.provider").querySelector(`[value="${provider}"]`).disabled=!result.enabled;
      pick.replaceChildren();
      for (const model of result.models || []) {
        const option=document.createElement("option");
        option.value=model.id;option.textContent=model.title;pick.append(option);
      }
      const custom=document.createElement("option");
      custom.value="custom";custom.textContent="Custom profile ID";pick.append(custom);
      pick.value=(result.models || []).some(model=>model.id === field("ai.model").value) ? field("ai.model").value : "custom";
      get("apiModelLabel").hidden=pick.value !== "custom";
      get("bedrockGPTHint").textContent=result.message;
    } catch {
      get("apiModelLabel").hidden=false;
      get("bedrockGPTHint").textContent="Model presets could not load. Enter your exact profile ID.";
    }
  }
  window.AiMateBedrockGPT=Object.freeze({update});
})();
